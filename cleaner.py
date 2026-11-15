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
    r'^\s*\[\d+\s+captures\].*$',
    r'^\s*[-*•]?\s*(Toggle\s+.*?(subsection|table of contents))\s*$',
    r'^\s*[-*•]?\s*(\d+\s+languages)\s*$',
    r'^\s*[-*•]?\s*(Navigation|Search|Print/export|Printable version|In other projects|General|Tools|Actions)\s*$',
    r'^\s*[-*•]?\s*(Small|Standard|Large|Wide|Automatic|Light|Dark)\s*$',
    r'^\s*This page always uses small font size.*$',
    r'^\s*The content is as wide as possible.*$',
    r'^\s*Skip to chapter text\s*$',
    r'^\s*Check\s+Show answer\b.*$',
    r'^\s*Show step \d+\b.*$',
    r'^\s*Show full solution\b.*$',
    r'^\s*Try it yourself first\b.*$',
    r'^\s*Tap an item on the left.*$',
    r'^\s*Match each ligand with its denticity.*$',
    r'^\s*Recommended:\s*Buy the Printed NCERT.*$',
    r'^\s*Contains Amazon affiliate links\b.*$',
    r'^\s*Check the latest price on Amazon\b.*$',
    r'^\s*Buy on Amazon\b.*$',
    r'^\s*Price and availability may change.*$',
    r'^\s*As an Amazon Associate.*$',
    r'^\s*Written by\s+[A-Z][a-z]+.*$',
    r'^\s*NCERTBooks\.org is an independent.*$',
    r'^\s*📄 Want this offline\? Download the free PDF.*$',
    r'^\s*NCERT Books-\s*\d+\s*to\s*\d+.*$',
    r'^\s*Class \d+ NCERT Books.*$',
    r'^\s*Continue Practising\s*—\s*NCERT Solutions.*$',
    r'^\s*NCERT Solutions for Class\s+(?:[6-9]|1[0-2]).*$',
    r'^\s*Class\s+(?:[6-9]|1[0-2])\s+collections?:.*$',
    r'^\s*(?:English|Maths|Science|Hindi|Sanskrit|Social Science|Accountancy|Economics|History|Geography)\s*[–—-].*$',
    r'^\s*Existing NCERT books continue in.*$',
    r'^\s*Complete solutions to the Class.*$',
    r'^\s*Chapter-wise solutions to.*$',
    r'^\s*Step-by-step solutions to every example.*$',
    r'^\s*Looking for a specific chapter\?.*$',
    r'^\s*ClearStudy is an independent resource.*$',
    r'^\s*FAQs about NCERT Solutions.*$',
    r'^\s*Match the class, book title, part and chapter.*$',
    r'^\s*Attempt the questions first, compare your reasoning.*$'
]
_COMPILED_UI_NOISE = re.compile("|".join(f"(?:{p})" for p in UI_NOISE_PATTERNS), re.IGNORECASE)

# Junk patterns in hyperlinks that must be purged
JUNK_LINK_URL_OR_TEXT = re.compile(
    r'(course|tutorial|practice|job|login|signin|signup|donate|special:|'
    r'wayback|web\.archive\.org|captures|createaccount|userlogin|privacy|terms|amazon\.com|ncertbooks\.org.*affiliate)',
    re.IGNORECASE
)


def convert_mathml_and_katex(text: str) -> str:
    """
    Converts KaTeX and MathML XML structures into standard LaTeX equations ($ ... $ or $$ ... $$).
    Eliminates phantom markers, mangled chemical formulas, and broken spaces.
    """
    if not text:
        return ""

    # 1. First check if KaTeX annotation block with raw TeX is present
    def _replace_annotation(match):
        tex = match.group(1).strip()
        return f" ${tex}$ " if tex else " "

    text = re.sub(
        r'<span[^>]*class=["\'][^"\']*katex[^"\']*["\'][^>]*>.*?<annotation[^>]*encoding=["\']application/x-tex["\'][^>]*>(.*?)</annotation>.*?</span>',
        _replace_annotation,
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    # 2. Convert <math>...</math> blocks (e.g. from ncert.ai, Wikipedia)
    def _clean_math_block(match):
        raw = match.group(0)
        # Strip phantom alignment elements (<mphantom>X</mphantom>)
        t = re.sub(r'<mphantom>.*?</mphantom>', '', raw, flags=re.DOTALL)
        # Handle msub with mpadded or plain
        t = re.sub(r'<msub>\s*(.*?)\s*<mpadded[^>]*>\s*<m[no]>(.*?)</m[no]>\s*</mpadded>\s*</msub>', r'\1_{\2}', t, flags=re.DOTALL)
        t = re.sub(r'<msub>\s*(.*?)\s*<m[no]>(.*?)</m[no]>\s*</msub>', r'\1_{\2}', t, flags=re.DOTALL)
        # Handle msup with mpadded or plain
        t = re.sub(r'<msup>\s*(.*?)\s*<mpadded[^>]*>\s*(?:<mrow>)?(.*?)(?:</mrow>)?\s*</mpadded>\s*</msup>', r'\1^{\2}', t, flags=re.DOTALL)
        t = re.sub(r'<msup>\s*(.*?)\s*<m[no]>(.*?)</m[no]>\s*</msup>', r'\1^{\2}', t, flags=re.DOTALL)
        # Strip all other MathML tags
        t = re.sub(r'</?(?:math|mrow|mi|mn|mo|mtext|mpadded|span|mstyle)[^>]*>', '', t)
        # Decode HTML entities
        t = html.unescape(t)
        # Collapse internal spaces
        t = re.sub(r'\s+', '', t).strip()
        if not t:
            return ""
        return f"${t}$"

    text = re.sub(r'<math[^>]*>.*?</math>', _clean_math_block, text, flags=re.DOTALL | re.IGNORECASE)

    # 3. Handle standard HTML <sub> and <sup>
    text = re.sub(r'<sub[^>]*>(.*?)</sub>', r'_{ \1 }', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<sup[^>]*>(.*?)</sup>', r'^{ \1 }', text, flags=re.DOTALL | re.IGNORECASE)

    return text


def convert_html_tables_to_markdown(raw_html: str) -> str:
    """Converts HTML <table> elements into GitHub Flavored Markdown tables."""
    if not raw_html or "<table" not in raw_html.lower():
        return raw_html

    def _table_to_md(match):
        table_html = match.group(0)
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, flags=re.DOTALL | re.IGNORECASE)
        if not rows:
            return ""

        table_data = []
        for r in rows:
            cells = re.findall(r'<(?:td|th)[^>]*>(.*?)</(?:td|th)>', r, flags=re.DOTALL | re.IGNORECASE)
            cleaned_cells = []
            for c in cells:
                c_clean = re.sub(r'<[^>]+>', ' ', c)
                c_clean = html.unescape(c_clean)
                c_clean = re.sub(r'\s+', ' ', c_clean).strip()
                cleaned_cells.append(c_clean.replace('|', r'\|'))
            if any(cleaned_cells):
                table_data.append(cleaned_cells)

        if not table_data:
            return ""

        max_cols = max(len(row) for row in table_data)
        normalized_data = [row + [""] * (max_cols - len(row)) for row in table_data]

        header = normalized_data[0]
        header_text = " ".join(header).lower()
        # Reject non-scientific tables (school book catalogs, prose/poem lists, syllabus indexes)
        if any(bad in header_text for bad in [
            "prose", "poem", "syllabus", "cbse", "sample paper", 
            "class 6", "class 7", "class 8", "class 9", "class 10", "class 11",
            "textbook list", "download pdf", "book part", "school resource",
            "unit | prose"
        ]):
            return ""

        separator = ["---"] * max_cols
        body = normalized_data[1:]

        md_lines = ["\n"]
        md_lines.append("| " + " | ".join(header) + " |")
        md_lines.append("| " + " | ".join(separator) + " |")
        for row in body:
            md_lines.append("| " + " | ".join(row) + " |")
        md_lines.append("\n")

        return "\n".join(md_lines)

    return re.sub(r'<table[^>]*>.*?</table>', _table_to_md, raw_html, flags=re.DOTALL | re.IGNORECASE)


def reconstruct_chemical_formulas(text: str) -> str:
    """
    Heuristically repairs mangled chemical formulas and symbols where letters were spaced out
    or MathML was flattened to plain text.
    """
    # 1. Superscript charges (e.g. "X 3 +" or "X 2 -" or "X −")
    text = re.sub(r'\bX\s*([1-6])\s*([+\-\u2212])', r'^{\1\2}', text)
    text = re.sub(r'\bX\s*([+\-\u2212])', r'^{\1}', text)
    # 2. Subscript numbers (e.g. "X 3" -> "_3")
    text = re.sub(r'\bX\s*(\d{1,2})\b', r'_{\1}', text)
    # 3. Known chemical element pairs spaced out by MathML flattening
    element_map = [
        (r'\bC\s+o\b', 'Co'), (r'\bC\s+l\b', 'Cl'), (r'\bN\s+H\b', 'NH'),
        (r'\bA\s+g\b', 'Ag'), (r'\bC\s+r\b', 'Cr'), (r'\bP\s+t\b', 'Pt'),
        (r'\bZ\s+n\b', 'Zn'), (r'\bF\s+e\b', 'Fe'), (r'\bC\s+u\b', 'Cu'),
        (r'\bI\s+r\b', 'Ir'), (r'\bR\s+h\b', 'Rh'), (r'\bN\s+i\b', 'Ni'),
        (r'\bB\s+r\b', 'Br'), (r'\bS\s+O\b', 'SO'), (r'\bN\s+O\b', 'NO'),
        (r'\bH\s+O\b', 'HO'), (r'\bC\s+O\b', 'CO'), (r'\bC\s+N\b', 'CN')
    ]
    for pattern, repl in element_map:
        text = re.sub(pattern, repl, text)

    return text


def strip_html_tags(raw_html: str) -> str:
    """Removes script, style, comments, and boilerplate HTML tags while keeping structural text."""
    if not raw_html:
        return ""

    # Convert KaTeX & MathML into LaTeX first before stripping tags
    text = convert_mathml_and_katex(raw_html)

    # Convert HTML tables to Markdown tables
    text = convert_html_tables_to_markdown(text)
    
    # Preserve blockquotes as Markdown quotes before stripping
    text = re.sub(
        r'<blockquote[^>]*>(.*?)</blockquote>', 
        lambda m: f"\n> {m.group(1).strip()}\n", 
        text, 
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

    # Reconstruct chemical formulas that were damaged
    text = reconstruct_chemical_formulas(text)
    return text


JUNK_TITLES_RE = re.compile(
    r'^(Client Challenge|Access Denied|Attention Required|Just a moment\.\.\.|Security Check|Cloudflare|'
    r'403 Forbidden|404 Not Found|Untitled Document|Page Not Found|Sign In|Log In)$',
    re.IGNORECASE
)


def extract_title(content: str, default: str = "Untitled Document") -> str:
    """Extract document title from HTML or Markdown, filtering out bot challenge junk."""
    # 1. Try Markdown # Title first if it looks like a substantive subject title
    md_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if md_match:
        t = md_match.group(1).strip()
        if t and not JUNK_TITLES_RE.match(t) and len(t) > 3:
            return t

    # 2. Try <title> tag
    title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
    if title_match:
        t = re.sub(r'\s+', ' ', title_match.group(1)).strip()
        # Clean common site suffixes (e.g. " | Learn CBSE", " - Free NCERT Notes")
        t = re.sub(r'\s*[-|–—]\s*(LearnCBSE|AglaSem|Scribd|GeeksforGeeks|Wikipedia).*$', '', t, flags=re.IGNORECASE).strip()
        if t and not JUNK_TITLES_RE.match(t) and len(t) > 3:
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
