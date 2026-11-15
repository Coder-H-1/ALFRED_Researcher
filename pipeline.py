"""
pipeline.py - Orchestrator for Iterative Research Workflow
Coordinates all functions:
1. Link collection & relevance discovery (collector.py)
2. Scraping, sub-topic harvesting, & parallel fetching (scraper.py)
3. Cleaning & boilerplate stripping (cleaner.py)
4. Temporary staging in Researcher/Temp (temp_manager.py)
5. One-by-one iterative LLM synthesis with 64k token budget & deep theory (synthesizer.py)
6. Thread-locked Obsidian storage & graph linking (obsidian.py)
7. Global retrieval & presentation showcase (showcase.py)
"""

import os
import time
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

try:
    from .logger import get_logger
    logger = get_logger(__name__)
except (ImportError, ValueError):
    try:
        from logger import get_logger
        logger = get_logger(__name__)
    except Exception:
        import logging
        logger = logging.getLogger(__name__)

from .collector import collect_links, filter_relevant_sublinks, clean_url
from .scraper import fetch_url, fetch_urls_parallel
from .cleaner import format_research_note
from .temp_manager import TempResearchStorage
from .synthesizer import synthesize_and_update
from .showcase import generate_web_view
from .obsidian import global_fetch_obsidian_data, _DEFAULT_VAULT

try:
    from .llm_manager import (
        ResearcherLLM,
        get_researcher_llm,
        unload_researcher_llm
    )
except (ImportError, ValueError):
    try:
        from llm_manager import (
            ResearcherLLM,
            get_researcher_llm,
            unload_researcher_llm
        )
    except Exception:
        ResearcherLLM = None
        get_researcher_llm = None
        unload_researcher_llm = None


class ResearchPipeline:
    """End-to-end orchestrator for deep iterative textual research."""

    def __init__(self, topic: str, vault_dir: Optional[str] = None):
        self.topic = topic
        self.note_title = f"Research_{topic.replace(' ', '_')}"
        if vault_dir:
            self.vault = ObsidianVault(vault_dir)
        else:
            self.vault = _DEFAULT_VAULT
        self.temp_storage = TempResearchStorage(topic)

    def run_iterative_research(
        self,
        inputs: List[str],
        max_sites: int = 3,
        max_sublinks_per_site: int = 2,
        auto_open_report: bool = False
    ) -> Dict[str, Any]:
        """
        Executes the deep iterative research workflow:
        1. Collects primary target links (Function 1).
        2. Fetches each primary page and extracts relevant on-page sublinks.
        3. Parallel-fetches referenced sub-topics.
        4. Staged all data into Researcher/Temp/<topic>/.
        5. Feeds staged files into LLM synthesizer one-by-one to build deep, well-linked Obsidian notes.
        6. Generates Showcase reports (HTML + PDF).
        """
        logger.info(f"=== Starting Deep Iterative Research for topic: '{self.topic}' ===")
        start_time = time.time()

        # Step 1: Collect Links
        urls = collect_links(inputs, max_per_query=max_sites)
        if not urls:
            logger.warning("No URLs found or provided.")
            return {"status": "error", "message": "No valid links collected."}

        target_urls = urls[:max_sites]
        logger.info(f"Targeting {len(target_urls)} primary sites: {target_urls}")

        staged_count = 0

        # Step 2 & 3: Fetch, clean, harvest sublinks, and stage in Temp
        for step, url in enumerate(target_urls, start=1):
            logger.info(f"\n--- [Stage 1: Fetching & Staging {step}/{len(target_urls)}] {url} ---")
            raw_html_or_md = fetch_url(url)
            if not raw_html_or_md:
                logger.warning(f"Failed to fetch content from {url}. Continuing to next site.")
                continue

            cleaned_doc = format_research_note(
                raw_content=raw_html_or_md,
                source_url=url,
                max_words=6000
            )

            # Save primary page to Temp/
            self.temp_storage.save_page_data(
                index=step,
                url=url,
                title=cleaned_doc["title"],
                raw_content=raw_html_or_md,
                cleaned_doc=cleaned_doc,
                is_sublink=False
            )
            staged_count += 1

            # Discover and parallel-fetch relevant on-page sublinks (excluding parent page)
            parent_clean = clean_url(url)
            candidate_sublinks = [
                item for item in cleaned_doc.get("referenced_links", [])
                if clean_url(item.get("url", "")) and clean_url(item.get("url", "")) != parent_clean
            ]
            relevant_sublinks = filter_relevant_sublinks(
                candidate_sublinks, 
                topic=self.topic, 
                max_links=max_sublinks_per_site
            )

            if relevant_sublinks:
                sublink_urls = [item["url"] for item in relevant_sublinks]
                logger.info(f"Parallel fetching {len(sublink_urls)} relevant sub-topics: {sublink_urls}")
                parallel_results = fetch_urls_parallel(sublink_urls, max_workers=3, timeout=12)

                for sub_idx, sub_item in enumerate(relevant_sublinks, start=1):
                    sub_url = sub_item["url"]
                    sub_raw = parallel_results.get(sub_url, "")
                    if not sub_raw:
                        continue
                    sub_clean = format_research_note(
                        raw_content=sub_raw,
                        source_url=sub_url,
                        title=sub_item.get("title"),
                        max_words=4000
                    )
                    sub_clean["is_sublink"] = True
                    self.temp_storage.save_page_data(
                        index=step * 10 + sub_idx,
                        url=sub_url,
                        title=sub_clean["title"],
                        raw_content=sub_raw,
                        cleaned_doc=sub_clean,
                        is_sublink=True
                    )
                    staged_count += 1

        # Step 4: Load all staged files from Temp
        staged_docs = self.temp_storage.load_all_staged()
        logger.info(f"\n--- [Stage 2: Sequential Synthesis] Processing {len(staged_docs)} staged docs from Temp ---")

        processed_notes = []
        try:
            # Smart warm load: load model once for whole research session
            if get_researcher_llm:
                logger.info("Initializing dedicated Researcher LLM (SmolLM2) for session...")
                get_researcher_llm()

            for idx, doc in enumerate(staged_docs, start=1):
                if "source" not in doc and "url" in doc:
                    doc["source"] = doc["url"]
                logger.info(f"Synthesizing staged doc {idx}/{len(staged_docs)}: '{doc.get('title')}'")
                saved_note_path = synthesize_and_update(
                    topic=self.topic,
                    new_doc=doc,
                    note_title=self.note_title,
                    doc_index=idx,
                    temp_storage=self.temp_storage
                )
                processed_notes.append(saved_note_path)
        finally:
            # Unload model after the whole research is done to free memory
            if unload_researcher_llm:
                logger.info("Research synthesis complete. Unloading Researcher LLM and freeing memory...")
                unload_researcher_llm()

        # Step 5: Showcase web view & PDF generation
        report_res = None
        try:
            report_res = generate_web_view(self.note_title, auto_open=auto_open_report, create_pdf=True)
        except Exception as e:
            logger.error(f"Failed to generate showcase web view: {e}")

        # Step 6: Post-research temp staging preservation (kept for audit & multi-source evidence)
        try:
            self.temp_storage.clear(force=False)
            logger.info(f"Staged temporary research files preserved in: {self.temp_storage.topic_dir}")
        except Exception as e:
            logger.warning(f"Failed in temp storage handler: {e}")

        elapsed = round(time.time() - start_time, 2)
        logger.info(f"=== Completed Research in {elapsed}s. Report: {report_res} ===")

        note_file = os.path.join(self.vault.vault_path, f"{self.note_title}.md")

        return {
            "status": "success",
            "topic": self.topic,
            "note_title": self.note_title,
            "note_file": note_file,
            "vault_dir": self.vault.vault_path,
            "sources_processed": len(staged_docs),
            "report_html": report_res.get("html") if report_res else None,
            "report_pdf": report_res.get("pdf") if report_res else None,
            "elapsed_seconds": elapsed
        }

    def parallel_scrape_and_iterative_synthesize(
        self,
        urls: List[str],
        max_workers: int = 3,
        auto_open_report: bool = False
    ) -> Dict[str, Any]:
        """
        Parallelized variant:
        Fetches & cleans multiple sites concurrently, stages to Temp,
        then feeds each staged document into the synthesis engine one by one.
        """
        logger.info(f"Parallel fetching {len(urls)} sites with {max_workers} threads...")

        parallel_raw = fetch_urls_parallel(urls, max_workers=max_workers)
        staged_docs = []
        for idx, (target_url, raw) in enumerate(parallel_raw.items(), start=1):
            cleaned = format_research_note(raw, source_url=target_url, max_words=6000)
            self.temp_storage.save_page_data(
                index=idx,
                url=target_url,
                title=cleaned["title"],
                raw_content=raw,
                cleaned_doc=cleaned,
                is_sublink=False
            )

        staged_docs = self.temp_storage.load_all_staged()
        logger.info(f"Staged {len(staged_docs)} documents into Temp. Beginning sequential synthesis.")

        try:
            if get_researcher_llm:
                logger.info("Initializing dedicated Researcher LLM (SmolLM2) for parallel-staged session...")
                get_researcher_llm()

            for idx, doc in enumerate(staged_docs, start=1):
                logger.info(f"Synthesizing source {idx}/{len(staged_docs)} into Obsidian vault...")
                synthesize_and_update(
                    topic=self.topic,
                    new_doc=doc,
                    note_title=self.note_title
                )
        finally:
            if unload_researcher_llm:
                logger.info("Research synthesis complete. Unloading Researcher LLM and freeing memory...")
                unload_researcher_llm()

        report_res = generate_web_view(self.note_title, auto_open=auto_open_report, create_pdf=True)
        return {
            "status": "success",
            "topic": self.topic,
            "sources_processed": len(staged_docs),
            "report_html": report_res.get("html") if report_res else None,
            "report_pdf": report_res.get("pdf") if report_res else None
        }
