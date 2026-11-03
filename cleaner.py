"""
cleaner.py - Function 3: Cleaner and Formatter
Cleans extracted textual content, strips HTML boilerplate, removes navigation junk,
and normalizes into structured Markdown suitable for deep research synthesis.
"""

import re
import html
import urllib.parse
from typing import Dict, Any, List, Optional

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


# Common navigation, footer, and UI noise patterns
UI_NOISE_PATTERNS = [
    r'^\s*\[?!\[.*?\]\(.*?\)\s*(\]\(.*?\))?\s*$',  # Standalone markdown images/badges/logos
    r'^\s*[*_]{2,}\s*$',                            # Stray bold/italic symbols like ** or __
    r'^\s*[-*•]?\s*(Courses|Tutorials|Practice|Jobs|Sign In|Sign Up|Log In|Register)\s*[*_]*\s*$',
    r'^\s*[*_]*\s*(Switch to Dark Mode|Dark Mode|Light Mode|Share Your Experiences|Share your thoughts)\s*[*_]*\s*$',
    r'^\s*[-*•]?\s*(\[?Jump to content|Main menu|move to sidebar|hide|Personal tools|Appearance|Contribute).*$',
    r'^\s*[-*•]?\s*(Special:|donate\.wikimedia|About Wikipedia|Contact us|Help:Contents|Learn to edit).*$',
    r'^\s*[-*•]?\s*(Community portal|Recent changes|Upload file|SpecialPages|CreateAccount|UserLogin).*$',
    r'^\s*[-*•]?\s*(Cookie policy|Privacy policy|Terms of service|Terms of use|Disclaimer|All rights reserved).*$',
    r'^\s*[-*•]?\s*(Follow us on|Connect with us|Subscribe|Newsletter|Advertisement|Sponsored).*$',
    r'^\s*[-*•]?\s*The Wayback Machine\b.*$',
    r'^\s*\[\d+\s+captures\].*$'
]
_COMPILED_UI_NOISE = re.compile("|".join(f"(?:{p})" for p in UI_NOISE_PATTERNS), re.IGNORECASE)

# Junk patterns in hyperlinks that must be purged
JUNK_LINK_URL_OR_TEXT = re.compile(
    r'(course|tutorial|practice|job|login|signin|signup|donate|special:|'
    r'wayback|web\.archive\.org|captures|createaccount|userlogin|privacy|terms)',
    re.IGNORECASE
)


def strip_html_tags(raw_html: str) -> str:
    """Removes script, style, comments, and boilerplate HTML tags while keeping structural text."""
    if not raw_html:
        return ""
    
    # Preserve blockquotes as Markdown quotes before stripping
    text = re.sub(
        r'<blockquote[^>]*>(.*?)</blockquote>', 
        lambda m: f"\n> {m.group(1).strip()}\n", 
        raw_html, 
        flags=re.DOTALL | re.IGNORECASE
    )
    
    # Remove heavy non-content tags: script, style, head, noscript, svg, nav, footer, header, aside, form
    text = re.sub(
        r'<(script|style|head|noscript|svg|nav|footer|header|aside|form)[^>]*>.*?</\1>', 
        ' ', 
        text, 
        flags=re.DOTALL | re.IGNORECASE
    )
    
    # Strip HTML comments
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.DOTALL)
    
    # Convert block tags to linebreaks
    text = re.sub(r'<(p|div|br|hr|h[1-6]|li|tr)[^>]*>', '\n', text, flags=re.IGNORECASE)
    
    # Convert remaining tags
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Decode HTML entities
    text = html.unescape(text)
    return text


def extract_title(content: str, default: str = "Untitled Document") -> str:
    """Extract document title from HTML or Markdown."""
    # Try <title> tag
    title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
    if title_match:
        t = re.sub(r'\s+', ' ', title_match.group(1)).strip()
        if t:
            return t
    
    # Try Markdown # Title
    md_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if md_match:
        t = md_match.group(1).strip()
        if t:
            return t
    
    return default


def extract_referenced_links(content: str, base_url: str = "") -> List[Dict[str, str]]:
    """
    Extracts on-page hyperlinks (anchor text and URL) from Markdown or HTML.
    Useful for discovering deep referenced pages (e.g. Faraday's Law, Lenz's Law).
    """
    links: List[Dict[str, str]] = []
    seen_urls = set()

    # 1. Match Markdown links [Text](url)
    md_links = re.findall(r'\[([^\]]+)\]\((https?://[^\s\)]+|/[^\s\)]+)\)', content)
    for title, url in md_links:
        full_url = urllib.parse.urljoin(base_url, url) if base_url else url
        if full_url.startswith("http") and full_url not in seen_urls:
            seen_urls.add(full_url)
            links.append({"title": title.strip(), "url": full_url})

    # 2. Match HTML <a href="...">text</a>
    html_links = re.findall(r'<a\s+(?:[^>]*?\s+)?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', content, re.IGNORECASE | re.DOTALL)
    for url, inner in html_links:
        full_url = urllib.parse.urljoin(base_url, url) if base_url else url
        clean_text = re.sub(r'<[^>]+>', '', inner).strip()
        if full_url.startswith("http") and full_url not in seen_urls and clean_text:
            seen_urls.add(full_url)
            links.append({"title": clean_text, "url": full_url})

    return links


def clean_markdown_formatting(text: str) -> str:
    """
    Standardize markdown content:
    - Normalizes excessive newlines and indentation.
    - Strips UI noise (Courses, Tutorials, Practice, Jobs, Sign In, Dark mode).
    - Filters out navigation link dumps and standalone sidebar links.
    - Preserves quotes ('>'), list items ('-', '*'), mathematical formulas, and headers ('#').
    - Removes zero-width characters and junk symbols.
    """
    # Replace non-breaking and zero-width spaces
    text = re.sub(r'[\u200B-\u200D\uFEFF\u00A0]', ' ', text)
    
    # Normalize carriage returns
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # Remove broken multi-line wikilinks containing newlines inside brackets
    text = re.sub(r'\[\[[^\]]*\n+[^\]]*\]\]', ' ', text)

    # Strip existing Related Entities section if present to avoid recursive pollution
    text = re.sub(r'\n*## Related Entities.*$', '', text, flags=re.DOTALL)

    lines = [line.strip() for line in text.split('\n')]
    cleaned_lines = []
    blank_count = 0

    for line in lines:
        if not line:
            blank_count += 1
            if blank_count <= 2:
                cleaned_lines.append("")
            continue
        
        blank_count = 0

        # Check if line matches UI noise
        if _COMPILED_UI_NOISE.match(line):
            continue

        # Strip trailing stray bold markdown like Mechanics** or Force**
        line = re.sub(r'\*{2,}$', '', line).strip()
        if not line or line in ("**", "__"):
            continue

        # Check if line is a standalone image logo or badge
        if re.search(r'!\[.*?\]\(.*?\)', line) and any(kw in line.lower() for kw in ("logo", "svg", "badge", "icon", "banner", "wordmark")):
            continue

        # Check if line contains junk link targets
        if JUNK_LINK_URL_OR_TEXT.search(line) and re.match(r'^[-*•]?\s*\[[^\]]+\]\([^\)]+\)$', line):
            continue

        # Check if line is a pure bulleted navigation link (closed or unclosed truncated):
        if re.match(r'^[-*•]?\s*\[[^\]]+\]\([^\)]*\)?$', line):
            continue

        # Strip standalone category headings that were part of nav sidebars
        if line.lower() in ("mechanics", "physics", "chemistry", "biology", "maths", "acoustics", "kinematics"):
            continue

        cleaned_lines.append(line)

    # Reassemble and collapse blank lines
    result = '\n'.join(cleaned_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def format_research_note(
    raw_content: str, 
    source_url: str = "", 
    title: Optional[str] = None, 
    max_words: Optional[int] = None
) -> Dict[str, Any]:
    """
    Primary interface for Function 3.
    Cleans raw HTML/Markdown into structured research text with metadata and referenced links.
    """
    detected_title = title or extract_title(raw_content, default="Research Source")
    
    # Check if raw_content looks like HTML
    if bool(re.search(r'<html|<body|<div|<p>|<article', raw_content, re.IGNORECASE)):
        cleaned_body = strip_html_tags(raw_content)
    else:
        cleaned_body = raw_content

    # Extract referenced links from raw content before stripping
    referenced_links = extract_referenced_links(raw_content, base_url=source_url)

    cleaned_body = clean_markdown_formatting(cleaned_body)
    
    words = cleaned_body.split()
    word_count = len(words)

    if max_words and word_count > max_words:
        cleaned_body = " ".join(words[:max_words]) + f"\n\n*(Truncated from {word_count} to {max_words} words)*"
        word_count = max_words

    formatted_markdown = (
        f"# {detected_title}\n\n"
        f"- **Source**: {source_url or 'Local/Unknown'}\n"
        f"- **Word Count**: {word_count}\n\n"
        f"---\n\n"
        f"{cleaned_body}\n"
    )

    return {
        "title": detected_title,
        "source": source_url,
        "word_count": word_count,
        "content": cleaned_body,
        "formatted_markdown": formatted_markdown,
        "referenced_links": referenced_links
    }
