"""
collector.py - Function 1: Link Collector
Collects, discovers, filters target links, and discovers relevant on-page sub-topics for deep research scraping.
"""

import os
import re
import urllib.parse
import subprocess
import shutil
import base64
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


BINARY_EXTENSIONS = (
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z", ".exe", ".bin",
    ".docx", ".xlsx", ".pptx", ".mp3", ".mp4", ".avi", ".mkv",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"
)

STOP_WORDS = {
    "class", "from", "with", "into", "that", "this", "what", "which",
    "ncert", "cbse", "solutions", "solution", "notes", "books", "book",
    "chapter", "session", "questions", "question", "guide", "guides",
    "part", "textbook", "textbooks", "grade", "syllabus", "edition"
}

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

def _find_obscura_bin() -> Optional[str]:
    candidates = [
        os.path.join(CURRENT_DIR, "bin", "obscura.exe"),
        os.path.join(os.path.dirname(CURRENT_DIR), "FILES", "bin", "obscura.exe"),
        os.path.join(os.path.dirname(CURRENT_DIR), "bin", "obscura.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    found = shutil.which("obscura.exe")
    return found if (found and os.path.isfile(found)) else None


def _decode_bing_url(u_param: str) -> Optional[str]:
    """Decodes Bing redirect parameter u=a1<base64> to extract the real destination URL."""
    try:
        raw = u_param[2:] if u_param.startswith("a1") else u_param
        # Support urlsafe base64 characters
        raw = raw.replace("-", "+").replace("_", "/")
        raw += "=" * ((4 - len(raw) % 4) % 4)
        decoded = base64.b64decode(raw).decode("utf-8", errors="ignore")
        return decoded if decoded.startswith("http") else None
    except Exception:
        return None


def is_valid_url(url: str) -> bool:
    """Validate if string is a valid HTTP/HTTPS URL and not a raw binary download."""
    try:
        parsed = urllib.parse.urlparse(url)
        if not (parsed.scheme in ("http", "https") and parsed.netloc):
            return False
        clean_path = parsed.path.lower()
        if any(clean_path.endswith(ext) for ext in BINARY_EXTENSIONS):
            return False
        if any(bad in clean_path for bad in ("-notes-pdf", "sample-paper", "sample-papers", "download-pdf")):
            return False
        return True
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
    Eliminates site boilerplate, syllabus directories, social, courses, and job links.
    """
    # Tokenize topic into meaningful keywords (excluding stop words)
    raw_tokens = set(re.findall(r'[a-zA-Z]{3,}', topic.lower()))
    topic_tokens = {w for w in raw_tokens if w not in STOP_WORDS}
    if not topic_tokens:
        topic_tokens = raw_tokens
    
    # Generic junk, bot challenge, and navigation patterns to strictly reject
    junk_patterns = re.compile(
        r'(job|course|tutorial|practice|login|sign[-_]?in|sign[-_]?up|register|'
        r'privacy|terms|cookie|contact|about|donate|feedback|account|cart|'
        r'school[-_]?resources|share[-_]?experiences|notes[-_]?class|'
        r'class[-_]?[0-9]|syllabus|curriculum|sample[-_]?papers|download[-_]?pdf|'
        r'ncert[-_]?solutions|ncert[-_]?books|chapter[-_]?list|'
        r'client[-_ ]?challenge|access[-_ ]?denied|attention[-_ ]?required|'
        r'just[-_ ]?a[-_ ]?moment|captcha|security[-_ ]?check|cloudflare)',
        re.IGNORECASE
    )

    scored_links = []
    seen_urls = set()

    # Determine broad topic domain to prevent cross-contamination
    topic_lower = topic.lower()
    is_chem = any(k in topic_lower for k in ("chem", "halo", "alkane", "arene", "organic", "compound", "reaction", "acid", "biomolecule"))
    is_phys = any(k in topic_lower for k in ("phys", "electromagnet", "induction", "optics", "quantum", "mechanics", "flux"))

    for item in candidate_links:
        title = item.get("title", "").strip()
        raw_url = item.get("url", "").strip()
        if not raw_url:
            continue
        # Strip tracking queries and fragments (e.g. #b-o4dwteqs) to avoid re-scraping the same page
        url = clean_url(raw_url)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        # Skip obvious navigation or site infrastructure links
        combined_text = f"{title} {url}".lower()
        if junk_patterns.search(combined_text):
            continue

        # Reject cross-domain formula/sidebar links (e.g. Maths/Physics links when researching Chemistry)
        if is_chem and any(bad in combined_text for bad in ("physics-formula", "maths-formula", "math-formula", "physics_formula", "maths_formula")):
            continue
        if is_phys and any(bad in combined_text for bad in ("chemistry-formula", "maths-formula", "math-formula")):
            continue

        # Score relevance based on keyword overlap
        topic_score = 0
        for token in topic_tokens:
            if token in title.lower():
                topic_score += 4
            if token in url.lower():
                topic_score += 3

        # Domain affinity bonuses per scientific branch
        domain_bonuses = []
        if is_chem:
            domain_bonuses.extend([
                "mechanism", "substitution", "elimination", "synthesis", "reaction",
                "preparation", "properties", "isomerism", "structure", "stereochemistry",
                "kinetics", "carbocation", "nucleophile", "electrophile", "haloalkane",
                "haloarene", "halide", "compound", "bonding", "acid"
            ])
        if is_phys:
            domain_bonuses.extend([
                "law", "theory", "flux", "field", "induction", "force", "energy",
                "electromagnet", "magnetic", "circuit", "current", "faraday", "lenz",
                "maxwell", "voltage", "emf", "motion", "mechanics"
            ])
        if not is_chem and not is_phys:
            domain_bonuses.extend([
                "law", "theory", "principle", "experiment", "force", "energy",
                "structure", "mechanism", "synthesis", "properties"
            ])

        bonus_score = 0
        for bonus in domain_bonuses:
            if bonus in title.lower() or bonus in url.lower():
                bonus_score += 1

        total_score = topic_score + bonus_score
        if total_score > 0 and (topic_score > 0 or bonus_score >= 1):
            scored_links.append((total_score, item))

    # Sort descending by relevance score
    scored_links.sort(key=lambda x: x[0], reverse=True)
    selected = [link for _, link in scored_links[:max_links]]
    logger.info(f"Discovered {len(candidate_links)} sublinks -> selected top {len(selected)} relevant sublinks.")
    return selected


def collect_links_from_search(query: str, max_results: int = 5) -> List[str]:
    """
    Search DuckDuckGo using multi-tier resilient collection:
    1. Local Obscura browser with stealth mode to bypass bot/Cloudflare challenges.
    2. DuckDuckGo Lite POST endpoint fallback.
    3. DuckDuckGo HTML GET fallback.
    """
    logger.info(f"Collecting links for query: '{query}' (limit {max_results})")
    urls: List[str] = []

    # Tier 1: Local Obscura engine with stealth
    obscura_bin = _find_obscura_bin()
    if obscura_bin and os.path.isfile(obscura_bin):
        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
            cmd = [
                obscura_bin,
                "fetch",
                search_url,
                "--dump", "links",
                "--stealth",
                "-q"
            ]
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                creationflags=creationflags
            )
            if res.returncode == 0 and res.stdout:
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    target_url = None
                    if "uddg=" in line:
                        m = re.search(r'uddg=([^&\s\t]+)', line)
                        if m:
                            target_url = urllib.parse.unquote(m.group(1))
                    elif line.startswith("http://") or line.startswith("https://"):
                        target_url = line.split("\t")[0].split()[0]

                    if target_url and is_valid_url(target_url) and "duckduckgo.com" not in target_url:
                        cleaned = clean_url(target_url)
                        if cleaned and cleaned not in urls:
                            urls.append(cleaned)
                            if len(urls) >= max_results:
                                break
            if urls:
                logger.info(f"Obscura collected {len(urls)} links for '{query}'")
        except Exception as e:
            logger.warning(f"Obscura link extraction failed: {e}")

    # Tier 2: Bing HTML search with base64 redirect extraction
    if len(urls) < max_results:
        try:
            encoded_query = urllib.parse.quote_plus(query)
            bing_url = f"https://www.bing.com/search?q={encoded_query}"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
            with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
                resp = client.get(bing_url)
                if resp.status_code == 200 and resp.text:
                    bing_u_matches = re.findall(r'(?:[?&]|&amp;)u=([a-zA-Z0-9_\-]+)', resp.text)
                    for u_match in bing_u_matches:
                        real_url = _decode_bing_url(u_match)
                        if real_url and is_valid_url(real_url) and not any(skip in real_url for skip in ["bing.com", "microsoft.com"]):
                            cleaned = clean_url(real_url)
                            if cleaned and cleaned not in urls:
                                urls.append(cleaned)
                                if len(urls) >= max_results:
                                    break
            if urls:
                logger.info(f"Total links after Bing fallback: {len(urls)}")
        except Exception as e:
            logger.warning(f"Bing search fallback failed: {e}")

    # Tier 3: DuckDuckGo Lite POST
    if len(urls) < max_results:
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
            with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
                resp = client.post("https://lite.duckduckgo.com/lite/", data={"q": query})
                if resp.status_code == 200 and resp.text:
                    found_hrefs = re.findall(r'href=[\'"]([^\'"]+)[\'"]', resp.text)
                    for h in found_hrefs:
                        target_url = None
                        if "uddg=" in h:
                            m = re.search(r'uddg=([^&"\'\s]+)', h)
                            if m:
                                target_url = urllib.parse.unquote(m.group(1))
                        elif h.startswith("http://") or h.startswith("https://"):
                            if "duckduckgo.com" not in h:
                                target_url = h

                        if target_url and is_valid_url(target_url) and "duckduckgo.com" not in target_url:
                            cleaned = clean_url(target_url)
                            if cleaned and cleaned not in urls:
                                urls.append(cleaned)
                                if len(urls) >= max_results:
                                    break
            if urls:
                logger.info(f"Total links after DDG Lite: {len(urls)}")
        except Exception as e:
            logger.warning(f"DDG Lite search failed: {e}")

    # Tier 3: Standard DDG HTML GET fallback
    if len(urls) < max_results:
        try:
            encoded_query = urllib.parse.quote_plus(query)
            search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            }
            with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
                resp = client.get(search_url)
                if resp.status_code == 200 and resp.text:
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
            logger.warning(f"DDG HTML search failed: {e}")

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
