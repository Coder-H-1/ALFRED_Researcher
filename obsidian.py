"""
obsidian.py - Functions 4, 5, and 7: Obsidian Vault Management
Handles thread-locked storage, retrieval, and global access for Obsidian markdown notes and knowledge graphs.
"""

import os
import re
import json
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
from filelock import FileLock

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

# Default vault folder: Prefer root workspace Vault (alongside main.py) for easy accessibility
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_ROOT = os.path.abspath(os.path.join(_CURRENT_DIR, ".."))
if os.path.isfile(os.path.join(_PARENT_ROOT, "main.py")):
    DEFAULT_VAULT_DIR = os.path.join(_PARENT_ROOT, "Vault")
else:
    DEFAULT_VAULT_DIR = os.path.join(_CURRENT_DIR, "Vault")

# Process-level thread lock
_VAULT_THREAD_LOCK = threading.RLock()


class ObsidianVault:
    """Thread-safe and process-safe Obsidian vault manager."""

    def __init__(self, vault_path: Optional[str] = None):
        self.vault_path = os.path.abspath(vault_path or DEFAULT_VAULT_DIR)
        os.makedirs(self.vault_path, exist_ok=True)
        obsidian_config = os.path.join(self.vault_path, ".obsidian")
        os.makedirs(obsidian_config, exist_ok=True)
        self.lock_file = os.path.join(self.vault_path, ".vault.lock")
        self._flock = FileLock(self.lock_file, timeout=20.0)

    def _sanitize_filename(self, title: str) -> str:
        """Sanitize string to valid Windows/Obsidian filename."""
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', title).strip()
        sanitized = re.sub(r'\s+', '_', sanitized)
        return sanitized[:100] or "Untitled"

    # ==========================================
    # Function 4: Store Data in Obsidian
    # ==========================================
    def store_note(
        self,
        title: str,
        content: str,
        tags: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        wikilinks: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        folder: str = ""
    ) -> str:
        """
        Function 4: Store or update note in Obsidian with thread and file locking.
        Generates YAML frontmatter and [[wikilinks]] for Knowledge Graph.
        """
        tags = tags or ["research"]
        sources = sources or []
        wikilinks = wikilinks or []
        metadata = metadata or {}

        filename = f"{self._sanitize_filename(title)}.md"
        target_dir = os.path.join(self.vault_path, folder) if folder else self.vault_path
        os.makedirs(target_dir, exist_ok=True)
        file_path = os.path.join(target_dir, filename)

        now_str = datetime.now().isoformat()

        # Build YAML frontmatter
        frontmatter_lines = [
            "---",
            f"title: \"{title}\"",
            f"updated: {now_str}",
            f"tags: {json.dumps(tags)}",
            f"sources: {json.dumps(sources)}"
        ]
        for k, v in metadata.items():
            if k not in ("title", "updated", "tags", "sources"):
                frontmatter_lines.append(f"{k}: {json.dumps(v)}")
        frontmatter_lines.append("---\n")

        # Strip any existing '## Related Entities' block from content to prevent duplicate stacking
        content_cleaned = re.sub(r'\n*## Related Entities.*$', '', content, flags=re.DOTALL).strip()

        # Sanitize and deduplicate wikilinks for Obsidian Knowledge Graph
        clean_links = []
        seen = set()
        for w in wikilinks:
            w_clean = re.sub(r'[\r\n]+', ' ', w).strip(' "[]():*#_-')
            w_lower = w_clean.lower()
            if not w_clean or len(w_clean) < 3 or len(w_clean) > 40:
                continue
            if w_lower in seen:
                continue
            if any(bad in w_lower for bad in (
                "dark mode", "sign in", "web source", "source reference", 
                "topic analysis", "deep sub", "theoretical foundation", 
                "primary knowledge base", "incremental analysis", "integrated empirical"
            )):
                continue
            seen.add(w_lower)
            clean_links.append(w_clean)

        link_section = ""
        if clean_links:
            link_section = "\n\n## Related Entities\n" + "\n".join(f"- [[{link}]]" for link in clean_links)

        full_document = "\n".join(frontmatter_lines) + content_cleaned + link_section + "\n"

        # Apply thread-lock and file-lock
        with _VAULT_THREAD_LOCK:
            with self._flock:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(full_document)
                self._update_graph_index(title, clean_links, tags)

        logger.info(f"[Obsidian Function 4] Successfully saved note: '{title}' -> {file_path}")
        return file_path

    def _update_graph_index(self, note_title: str, wikilinks: List[str], tags: List[str]):
        """Maintain a master Knowledge_Graph.md index file inside vault."""
        index_file = os.path.join(self.vault_path, "Knowledge_Graph.md")
        entry = f"- [[{note_title}]] (Tags: {', '.join(tags)})"
        if wikilinks:
            entry += f" -> connects to: {', '.join(f'[[{w}]]' for w in wikilinks)}"

        existing_lines = []
        if os.path.isfile(index_file):
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    existing_lines = f.read().splitlines()
            except Exception:
                pass

        if not any(f"[[{note_title}]]" in line for line in existing_lines):
            if not existing_lines:
                existing_lines = ["# Knowledge Graph Index\n\n## Master Notes\n"]
            existing_lines.append(entry)
            with open(index_file, "w", encoding="utf-8") as f:
                f.write("\n".join(existing_lines) + "\n")

    # ==========================================
    # Function 5: Fetch Data from Obsidian
    # ==========================================
    def fetch_note(self, title: str, folder: str = "") -> Optional[Dict[str, Any]]:
        """
        Function 5: Retrieve note contents and metadata from Obsidian.
        Thread-safe and process-safe read.
        """
        filename = f"{self._sanitize_filename(title)}.md"
        target_dir = os.path.join(self.vault_path, folder) if folder else self.vault_path
        file_path = os.path.join(target_dir, filename)

        if not os.path.isfile(file_path):
            return None

        with _VAULT_THREAD_LOCK:
            with self._flock:
                with open(file_path, "r", encoding="utf-8") as f:
                    raw = f.read()

        # Parse YAML frontmatter
        metadata = {}
        content_body = raw
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                yaml_block = parts[1]
                content_body = parts[2].strip()
                for line in yaml_block.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        try:
                            metadata[k.strip()] = json.loads(v.strip())
                        except Exception:
                            metadata[k.strip()] = v.strip()

        # Strip any existing '## Related Entities' block from content_body
        content_body = re.sub(r'\n*## Related Entities.*$', '', content_body, flags=re.DOTALL).strip()

        # Extract clean single-line wikilinks from body
        wikilinks = re.findall(r'\[\[([^\]\r\n\|]+)(?:\|[^\]\r\n]+)?\]\]', raw)

        return {
            "title": title,
            "path": file_path,
            "metadata": metadata,
            "wikilinks": list(set(wikilinks)),
            "content": content_body,
            "raw": raw
        }

    # ==========================================
    # Function 7: Global Accessor for External Tools
    # ==========================================
    def list_notes(self) -> List[str]:
        """Global Function 7: List all available notes in the vault."""
        with _VAULT_THREAD_LOCK:
            with self._flock:
                files = os.listdir(self.vault_path)
                notes = [
                    os.path.splitext(f)[0] 
                    for f in files 
                    if f.endswith(".md") and f not in ("Knowledge_Graph.md",)
                ]
                return sorted(notes)

    def query_vault(self, keyword: str) -> List[Dict[str, Any]]:
        """Global Function 7: Search notes containing keyword."""
        results = []
        for note_title in self.list_notes():
            note = self.fetch_note(note_title)
            if note and (keyword.lower() in note["title"].lower() or keyword.lower() in note["content"].lower()):
                results.append(note)
        return results

    def export_graph_json(self) -> Dict[str, Any]:
        """
        Global Function 7: Exports complete Knowledge Graph as nodes and links
        compatible with D3.js or external graph visualizers.
        """
        nodes = []
        links = []
        seen_nodes = set()

        for title in self.list_notes():
            note = self.fetch_note(title)
            if not note:
                continue

            if title not in seen_nodes:
                seen_nodes.add(title)
                nodes.append({
                    "id": title,
                    "title": title,
                    "tags": note["metadata"].get("tags", []),
                    "word_count": len(note["content"].split())
                })

            for target in note["wikilinks"]:
                if target not in seen_nodes:
                    seen_nodes.add(target)
                    nodes.append({"id": target, "title": target, "tags": []})
                links.append({"source": title, "target": target})

        return {"nodes": nodes, "links": links}


# Global singleton vault instance for easy external tool access
_DEFAULT_VAULT = ObsidianVault()


# Module-level convenience functions matching user prompt definitions
def store_in_obsidian(title: str, content: str, **kwargs) -> str:
    """Parallel Function 4: Store in Obsidian with thread lock."""
    return _DEFAULT_VAULT.store_note(title, content, **kwargs)


def fetch_from_obsidian(title: str) -> Optional[Dict[str, Any]]:
    """Parallel Function 5: Fetch from Obsidian with thread lock."""
    return _DEFAULT_VAULT.fetch_note(title)


def global_fetch_obsidian_data(query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Global Function 7: Collect data from Obsidian for external tools."""
    if query:
        return _DEFAULT_VAULT.query_vault(query)
    all_notes = []
    for title in _DEFAULT_VAULT.list_notes():
        n = _DEFAULT_VAULT.fetch_note(title)
        if n:
            all_notes.append(n)
    return all_notes

