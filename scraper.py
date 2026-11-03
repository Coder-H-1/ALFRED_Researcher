"""
scraper.py - Function 2: Scraper and Multi-Content Fetcher
Fetches content from websites using Obscura binary with HTTP fallback.
Handles single, batch, and concurrent parallel fetching across multiple URLs.
"""

import os
import subprocess
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx

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

from .cleaner import format_research_note

# Locate Obscura binary flexibly across local or parent paths
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

def _find_obscura_bin() -> str:
    candidates = [
        os.path.join(CURRENT_DIR, "bin", "obscura.exe"),
        os.path.join(os.path.dirname(CURRENT_DIR), "FILES", "bin", "obscura.exe"),
        os.path.join(os.path.dirname(CURRENT_DIR), "bin", "obscura.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    import shutil
    return shutil.which("obscura.exe") or "obscura.exe"

OBSCURA_BIN = _find_obscura_bin()


def _fetch_via_obscura(url: str, timeout: int = 15) -> Optional[str]:
    """Execute local obscura.exe in headless stealth mode to fetch rendered markdown."""
    if not os.path.isfile(OBSCURA_BIN):
        return None

    cmd = [
        OBSCURA_BIN,
        "fetch",
        url,
        "--dump", "markdown",
        "--stealth",
        "-q"
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creationflags
        )
        if res.returncode == 0 and res.stdout.strip():
            logger.info(f"Obscura successfully fetched {len(res.stdout)} chars from {url}")
            return res.stdout
    except Exception as e:
        logger.warning(f"Obscura execution failed for {url}: {e}")
    return None


def _fetch_via_http(url: str, timeout: int = 15) -> Optional[str]:
    """Fallback fetcher using standard HTTP client."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7"
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                logger.info(f"HTTP GET fetched {len(resp.text)} chars from {url}")
                return resp.text
            else:
                logger.warning(f"HTTP GET {url} failed with status {resp.status_code}")
    except Exception as e:
        logger.error(f"HTTP fetch error for {url}: {e}")
    return None


def fetch_url(url: str, timeout: int = 15) -> str:
    """Fetch website content via Obscura first, falling back to HTTP client."""
    content = _fetch_via_obscura(url, timeout=timeout)
    if content:
        return content
    
    content = _fetch_via_http(url, timeout=timeout)
    return content or ""


def fetch_urls_parallel(
    urls: List[str], 
    max_workers: int = 5, 
    timeout: int = 15
) -> Dict[str, str]:
    """
    Fetch a batch of URLs concurrently using ThreadPoolExecutor.
    Returns mapping of url -> raw content string.
    """
    results: Dict[str, str] = {}
    if not urls:
        return results

    logger.info(f"Parallel fetching {len(urls)} URLs with {max_workers} threads.")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(fetch_url, url, timeout): url for url in urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                data = future.result()
                if data:
                    results[url] = data
            except Exception as e:
                logger.warning(f"Error parallel fetching {url}: {e}")
                
    return results


def scrape_and_store_multiple(
    urls: List[str], 
    timeout: int = 15,
    max_words_per_site: int = 6000
) -> List[Dict[str, Any]]:
    """
    Primary interface for Function 2 & 3.
    Scrapes a batch of websites and returns cleaned, structured documents.
    """
    results: List[Dict[str, Any]] = []
    logger.info(f"Scraping batch of {len(urls)} websites")

    for idx, url in enumerate(urls, start=1):
        try:
            logger.info(f"[{idx}/{len(urls)}] Fetching: {url}")
            raw = fetch_url(url, timeout=timeout)
            if not raw:
                logger.warning(f"Empty content from {url}, skipping.")
                continue

            cleaned_doc = format_research_note(
                raw_content=raw,
                source_url=url,
                max_words=max_words_per_site
            )
            cleaned_doc["index"] = idx
            results.append(cleaned_doc)
        except Exception as e:
            logger.error(f"Failed scraping {url}: {e}", exc_info=True)

    logger.info(f"Finished scraping. Successfully extracted {len(results)} sources.")
    return results
