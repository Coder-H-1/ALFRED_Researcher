"""
temp_manager.py - Staged Storage Manager for Research Pipeline
Saves raw and cleaned website data into FILES/Researcher/Temp temporary files
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

TEMP_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Temp")


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
                        entries.append(data)
                except Exception as e:
                    logger.warning(f"Error reading temp file {full_path}: {e}")

        # Sort: main pages (is_sublink=False) first, then by index
        entries.sort(key=lambda x: (1 if x.get("is_sublink") else 0, x.get("index", 0)))
        return entries

    def clear(self) -> None:
        """Cleans up temporary directory for this topic."""
        if os.path.isdir(self.topic_dir):
            try:
                shutil.rmtree(self.topic_dir, ignore_errors=True)
                logger.info(f"Cleared temp folder for topic: {self.topic}")
            except Exception as e:
                logger.warning(f"Failed to clear temp folder {self.topic_dir}: {e}")
