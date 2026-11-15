"""
temp_manager.py - Staged Storage Manager for Research Pipeline
Saves raw and cleaned website data into Researcher/Temp temporary files
before passing one by one to the LLM synthesizer.
"""

import os
import re
import json
import shutil
import hashlib
from typing import List, Dict, Any, Optional

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

# Base directory for temporary research files:
# Self-contained in Researcher/Temp
LOCAL_TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Temp")
TEMP_BASE_DIR = LOCAL_TEMP_DIR


def _safe_slug(text: str) -> str:
    """Create a safe filesystem directory or file name."""
    slug = re.sub(r'[^a-zA-Z0-9_\-]', '_', text.strip())
    return re.sub(r'_+', '_', slug)[:60] or "temp_research"


class TempResearchStorage:
    """Manages temporary files for raw and cleaned research data."""

    def __init__(self, topic: str):
        self.topic = topic
        self.slug = _safe_slug(topic)
        self.topic_dir = os.path.join(TEMP_BASE_DIR, self.slug)
        os.makedirs(self.topic_dir, exist_ok=True)

    def save_page_data(
        self,
        index: int,
        url: str,
        title: str,
        raw_content: str,
        cleaned_doc: Dict[str, Any],
        is_sublink: bool = False
    ) -> str:
        """
        Saves a research page artifact to Temp/ as JSON and clean Markdown.
        """
        os.makedirs(self.topic_dir, exist_ok=True)
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
        prefix = f"sub_{index:02d}" if is_sublink else f"main_{index:02d}"
        filename_base = f"{prefix}_{url_hash}"

        payload = {
            "index": index,
            "topic": self.topic,
            "url": url,
            "source": url,
            "title": title or cleaned_doc.get("title", "Untitled"),
            "is_sublink": is_sublink,
            "word_count": cleaned_doc.get("word_count", 0),
            "content": cleaned_doc.get("content", ""),
            "raw_snippet": raw_content[:1000] if raw_content else ""
        }

        json_path = os.path.join(self.topic_dir, f"{filename_base}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        md_path = os.path.join(self.topic_dir, f"{filename_base}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(cleaned_doc.get("formatted_markdown", cleaned_doc.get("content", "")))

        logger.info(f"Saved temp page {prefix} ({url}) -> {json_path}")
        return json_path

    def save_chunk_synthesis(
        self,
        doc_index: int,
        chunk_id: int,
        chunk_text: str,
        synthesis_result: str,
        source_title: str = ""
    ) -> str:
        """Saves intermediate LLM chunk synthesis output in Temp/<topic>/chunk_syntheses/."""
        chunk_dir = os.path.join(self.topic_dir, "chunk_syntheses")
        os.makedirs(chunk_dir, exist_ok=True)
        filename = f"chunk_doc{doc_index:02d}_part{chunk_id:02d}.json"
        target_path = os.path.join(chunk_dir, filename)

        payload = {
            "doc_index": doc_index,
            "chunk_id": chunk_id,
            "source_title": source_title,
            "chunk_text": chunk_text,
            "synthesis_result": synthesis_result
        }

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        md_path = os.path.join(chunk_dir, f"chunk_doc{doc_index:02d}_part{chunk_id:02d}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(synthesis_result)

        logger.info(f"Saved intermediate chunk synthesis to {target_path}")
        return target_path

    def load_chunk_syntheses(self, doc_index: Optional[int] = None) -> List[Dict[str, Any]]:
        """Loads intermediate chunk syntheses for a document or entire topic."""
        chunk_dir = os.path.join(self.topic_dir, "chunk_syntheses")
        if not os.path.isdir(chunk_dir):
            return []

        results = []
        for fname in sorted(os.listdir(chunk_dir)):
            if fname.endswith(".json"):
                full_path = os.path.join(chunk_dir, fname)
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if doc_index is None or data.get("doc_index") == doc_index:
                            results.append(data)
                except Exception as e:
                    logger.warning(f"Error reading chunk file {full_path}: {e}")

        results.sort(key=lambda x: (x.get("doc_index", 0), x.get("chunk_id", 0)))
        return results

    def load_all_staged(self) -> List[Dict[str, Any]]:
        """
        Loads all staged JSON files sorted so main pages come first, then sublinks.
        """
        if not os.path.isdir(self.topic_dir):
            return []

        entries = []
        for fname in os.listdir(self.topic_dir):
            if fname.endswith(".json"):
                full_path = os.path.join(self.topic_dir, fname)
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if "source" not in data and "url" in data:
                            data["source"] = data["url"]
                        entries.append(data)
                except Exception as e:
                    logger.warning(f"Error reading temp file {full_path}: {e}")

        # Sort: main pages (is_sublink=False) first, then by index
        entries.sort(key=lambda x: (1 if x.get("is_sublink") else 0, x.get("index", 0)))
        return entries

    def clear(self, force: bool = False) -> None:
        """Cleans up temporary directory only if force is explicitly True; otherwise preserves files for research audit."""
        if not force:
            logger.info(f"Preserving staged research temp files in: {self.topic_dir}")
            return
        if os.path.isdir(self.topic_dir):
            try:
                shutil.rmtree(self.topic_dir, ignore_errors=True)
                logger.info(f"Cleared temp folder for topic: {self.topic}")
            except Exception as e:
                logger.warning(f"Failed to clear temp folder {self.topic_dir}: {e}")


def cleanup_topic_temp(topic: str) -> bool:
    """
    Specifically removes the Temp directory for a single specified topic.
    """
    if not topic or not topic.strip():
        return False
    slug = _safe_slug(topic)
    topic_dir = os.path.join(TEMP_BASE_DIR, slug)
    if os.path.isdir(topic_dir):
        try:
            shutil.rmtree(topic_dir, ignore_errors=True)
            logger.info(f"Successfully cleaned temp storage for topic '{topic}' -> {topic_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete temp storage for topic '{topic}': {e}")
            return False
    return False


def cleanup_all_temp_storage() -> Dict[str, Any]:
    """
    Removes all topic temp directories inside Researcher/Temp.
    """
    cleaned_folders = 0
    if os.path.isdir(TEMP_BASE_DIR):
        for entry in os.listdir(TEMP_BASE_DIR):
            full_path = os.path.join(TEMP_BASE_DIR, entry)
            if os.path.isdir(full_path):
                try:
                    shutil.rmtree(full_path, ignore_errors=True)
                    cleaned_folders += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {full_path}: {e}")
    logger.info(f"Cleaned {cleaned_folders} topic temp folder(s) from {TEMP_BASE_DIR}")
    return {"cleaned_folders": cleaned_folders, "temp_base_dir": TEMP_BASE_DIR}
