"""
collector.py - Function 1: Link Collector
Collects, discovers, filters target links, and discovers relevant on-page sub-topics for deep research scraping.
"""

import os
import re
import urllib.parse
from typing import List, Dict, Optional
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


def is_valid_url(url: str) -> bool:
    """Validate if string is a valid HTTP/HTTPS URL."""
    try:
        parsed = urllib.parse.urlparse(url)
        return bool(parsed.scheme in ("http", "https") and parsed.netloc)
    except Exception:
        return False


def clean_url(url: str) -> str:
    """Strip tracking query parameters and fragments."""
    try:
        parsed = urllib.parse.urlparse(url)
        query_pairs = urllib.parse.parse_qsl(parsed.query)
        cleaned_pairs = [
            (k, v) for k, v in query_pairs 
            if not k.startswith("utm_") and k not in ("fbclid", "gclid", "ref", "source", "ref_src")
        ]
        new_query = urllib.parse.urlencode(cleaned_pairs)
        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            new_query,
            ""  # remove fragment
        ))
    except Exception:
        return url


def filter_relevant_sublinks(
    candidate_links: List[Dict[str, str]], 
    topic: str, 
    max_links: int = 5
) -> List[Dict[str, str]]:
    """
    Filters and ranks on-page sub-links by semantic and keyword relevance to the topic.
    Eliminates site boilerplate, social, courses, and job links.
    """
    # Tokenize topic into keywords (length >= 3)
    topic_tokens = set(re.findall(r'[a-zA-Z]{3,}', topic.lower()))
    
    # Generic junk patterns to strictly reject
    junk_patterns = re.compile(
        r'(job|course|tutorial|practice|login|sign[-_]?in|sign[-_]?up|register|'
        r'privacy|terms|cookie|contact|about|donate|feedback|account|cart|'
        r'school[-_]?resources|share[-_]?experiences|notes[-_]?class)',
        re.IGNORECASE
    )

    scored_links = []
    seen_urls = set()

    for item in candidate_links:
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        # Skip obvious navigation or site infrastructure links
        combined_text = f"{title} {url}".lower()
        if junk_patterns.search(combined_text):
            continue

        # Score relevance based on keyword overlap
        score = 0
        for token in topic_tokens:
            if token in title.lower():
                score += 3
            if token in url.lower():
                score += 2

        # Physics / Science / Domain related affinity bonus
        domain_bonuses = ("law", "theory", "formula", "principle", "experiment", "force", 
                          "energy", "field", "flux", "induction", "motion", "mechanics")
        for bonus in domain_bonuses:
            if bonus in title.lower():
                score += 1

        if score > 0:
            scored_links.append((score, item))

    # Sort descending by relevance score
    scored_links.sort(key=lambda x: x[0], reverse=True)
    selected = [link for _, link in scored_links[:max_links]]
    logger.info(f"Discovered {len(candidate_links)} sublinks -> selected top {len(selected)} relevant sublinks.")
    return selected


def collect_links_from_search(query: str, max_results: int = 5) -> List[str]:
    """
    Search DuckDuckGo HTML endpoint without external API dependencies.
    Extracts relevant result links.
    """
    logger.info(f"Collecting links for query: '{query}' (limit {max_results})")
    encoded_query = urllib.parse.quote_plus(query)
    search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    urls: List[str] = []
    resp = None
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(search_url)
            if resp.status_code == 200:
                # Find uddg redirect links or regular hrefs
                matches = re.findall(r'uddg=([^&"\s]+)', resp.text)
                for m in matches:
                    decoded = urllib.parse.unquote(m)
                    if is_valid_url(decoded) and "duckduckgo.com" not in decoded:
                        cleaned = clean_url(decoded)
                        if cleaned not in urls:
                            urls.append(cleaned)
                            if len(urls) >= max_results:
                                break
    except Exception as e:
        logger.error(f"Search request failed: {e}")

    # Fallback pattern if uddg wasn't present
    if not urls and resp and resp.text:
        links = re.findall(r'href=[\'"](https?://[^\'"]+)[\'"]', resp.text)
        for link in links:
            if is_valid_url(link) and not any(skip in link for skip in ["duckduckgo.com", "bing.com", "google.com"]):
                cleaned = clean_url(link)
                if cleaned not in urls:
                    urls.append(cleaned)
                    if len(urls) >= max_results:
                        break

    return urls


def collect_links_from_content(html_or_md: str, base_url: Optional[str] = None, max_results: int = 10) -> List[str]:
    """Extract hyperlinks from raw HTML or Markdown content."""
    urls = []
    
    # Match markdown links [text](url)
    md_matches = re.findall(r'\[.*?\]\((https?://[^\s\)]+)\)', html_or_md)
    for u in md_matches:
        cleaned = clean_url(u)
        if cleaned not in urls and is_valid_url(cleaned):
            urls.append(cleaned)

    # Match HTML href attributes
    html_matches = re.findall(r'href=[\'"]([^\'"\s>]+)[\'"]', html_or_md, re.IGNORECASE)
    for u in html_matches:
        if base_url and not u.startswith("http"):
            u = urllib.parse.urljoin(base_url, u)
        if is_valid_url(u) and not u.startswith("javascript:"):
            cleaned = clean_url(u)
            if cleaned not in urls:
                urls.append(cleaned)

    return urls[:max_results]


def collect_links(
    inputs: List[str], 
    max_per_query: int = 3, 
    filter_domains: Optional[List[str]] = None
) -> List[str]:
    """
    Primary interface for Function 1.
    Accepts mix of direct URLs and search queries.
    Returns deduplicated list of target URLs.
    """
    collected: List[str] = []
    filter_domains = filter_domains or []

    for item in inputs:
        item = item.strip()
        if not item:
            continue

        if is_valid_url(item):
            cleaned = clean_url(item)
            if cleaned not in collected:
                collected.append(cleaned)
        else:
            # Treat as search query
            results = collect_links_from_search(item, max_results=max_per_query)
            for url in results:
                if url not in collected:
                    domain = urllib.parse.urlparse(url).netloc
                    if not any(fd in domain for fd in filter_domains):
                        collected.append(url)

    logger.info(f"Total links collected: {len(collected)}")
    return collected
