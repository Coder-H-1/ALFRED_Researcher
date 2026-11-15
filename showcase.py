"""
showcase.py - Showcasing Tools
Uses Function 7 to fetch data from Obsidian and generates presentable web views (HTML) 
and publication-quality standalone PDFs using headless Chrome.
Optimized for readability: clean white theme, compact typography (15px screen / 13.5px print),
2-column split grid for related sub-topics, closed-rectangle formula containers,
and zero-gap print layout without orphan page breaks.
"""

import os
import sys
import re
import html
import subprocess
import webbrowser
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

from .obsidian import global_fetch_obsidian_data, fetch_from_obsidian, _DEFAULT_VAULT

if getattr(sys, "frozen", False):
    _EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.basename(_EXE_DIR).lower() == "bin":
        OUTPUT_DIR = os.path.join(os.path.dirname(_EXE_DIR), "Exports")
    else:
        OUTPUT_DIR = os.path.join(_EXE_DIR, "Exports")
else:
    OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Exports")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_preferred_browser() -> Optional[str]:
    """Locates preferred Chrome or Edge binary on Windows."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def convert_html_to_pdf(html_path: str, pdf_path: Optional[str] = None) -> Optional[str]:
    """
    Exports HTML page to PDF using preferred headless Chrome.
    Ensures MathJax formulas and stylesheets render completely.
    """
    if not pdf_path:
        base, _ = os.path.splitext(html_path)
        pdf_path = f"{base}.pdf"

    browser = get_preferred_browser()
    if not browser:
        logger.warning("No Chrome or Edge browser found for PDF export.")
        return None

    file_url = f"file:///{os.path.abspath(html_path).replace(os.sep, '/')}"
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--virtual-time-budget=2000",
        f"--print-to-pdf={pdf_path}",
        file_url
    ]

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        logger.info(f"Rendering PDF with {os.path.basename(browser)}: {pdf_path}")
        res = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            creationflags=creationflags
        )
        if os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 0:
            logger.info(f"Successfully generated PDF: {pdf_path} ({os.path.getsize(pdf_path)} bytes)")
            return pdf_path
        else:
            logger.warning(f"Browser exited code {res.returncode} but PDF not created: {res.stderr.decode(errors='replace')}")
    except Exception as e:
        logger.error(f"Failed to generate PDF via browser: {e}", exc_info=True)

    return None


def _render_inline_markdown(text: str) -> str:
    """Renders inline markdown formatting: bold, italic, links, and Obsidian wikilinks."""
    # Obsidian [[wikilinks]]
    text = re.sub(r'\[\[([^\]]+)\]\]', r'<span class="wikilink">\1</span>', text)
    # Standard Markdown hyperlinks [text](url)
    text = re.sub(
        r'\[([^\]]+)\]\((https?://[^\s\)]+|/[^\s\)]+)\)', 
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', 
        text
    )
    # Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
    # Italic *text* or _text_ (single asterisks, avoiding double or LaTeX symbols)
    text = re.sub(r'(?<!\*)\*([^\*\n]+?)\*(?!\*)', r'<em>\1</em>', text)
    return text


def markdown_to_html_enhanced(md_text: str) -> str:
    """
    Converts structured markdown into semantic HTML cards with formula boxes,
    bold parsing, and a 2-column split grid for related sub-topics.
    """
    lines = md_text.splitlines()
    html_lines = []
    in_list = False
    in_quote = False
    in_math_block = False
    math_buffer = []
    in_card = False
    in_subtopics_grid = False
    in_subtopic_item = False
    is_subtopics_section = False

    def close_open_containers():
        nonlocal in_list, in_quote
        if in_list:
            html_lines.append("</ul>")
            in_list = False
        if in_quote:
            html_lines.append("</blockquote>")
            in_quote = False

    for line in lines:
        stripped = line.strip()

        # Handle display math blocks $$
        if stripped.startswith("$$"):
            if not in_math_block:
                in_math_block = True
                math_buffer = [stripped]
                if stripped.endswith("$$") and len(stripped) > 2:
                    in_math_block = False
                    close_open_containers()
                    html_lines.append(f'<div class="formula-box">{stripped}</div>')
                continue
            else:
                math_buffer.append(stripped)
                in_math_block = False
                close_open_containers()
                html_lines.append(f'<div class="formula-box">{" ".join(math_buffer)}</div>')
                continue

        if in_math_block:
            math_buffer.append(stripped)
            continue

        # Handle blockquotes
        if stripped.startswith(">"):
            if not in_quote:
                close_open_containers()
                html_lines.append('<blockquote class="quote-box">')
                in_quote = True
            raw_quote = stripped.lstrip("> ").strip()
            html_lines.append(f"<p>{_render_inline_markdown(raw_quote)}</p>")
            continue
        elif in_quote:
            html_lines.append("</blockquote>")
            in_quote = False

        # Handle Section headings (##) -> Wraps into distinct boxed cards
        if stripped.startswith("## "):
            close_open_containers()
            if in_subtopic_item:
                html_lines.append("</div><!-- /.subtopic-item -->\n")
                in_subtopic_item = False
            if in_subtopics_grid:
                html_lines.append("</div><!-- /.subtopics-grid -->\n")
                in_subtopics_grid = False
            if in_card:
                html_lines.append("</div><!-- /.content-card -->\n")
            
            in_card = True
            heading_txt = stripped[3:].strip()
            is_subtopics_section = any(k in heading_txt.lower() for k in ("sub-topic", "empirical", "related topic"))
            badge = ""
            if "discrepancies" in heading_txt.lower():
                badge = ' <span class="badge badge-warning">Caution</span>'
            html_lines.append('<div class="content-card">')
            html_lines.append(f'<h2 class="section-title">{_render_inline_markdown(heading_txt)}{badge}</h2>')
            continue

        # Handle Subsection headings (###)
        if stripped.startswith("### "):
            close_open_containers()
            sub_title = stripped[4:].strip()

            if is_subtopics_section:
                # Group related sub-topics into a 2-column split grid
                if in_subtopic_item:
                    html_lines.append("</div><!-- /.subtopic-item -->\n")
                if not in_subtopics_grid:
                    html_lines.append('<div class="subtopics-grid">\n')
                    in_subtopics_grid = True
                
                html_lines.append('<div class="subtopic-item">\n')
                in_subtopic_item = True
                html_lines.append(f'<h4 class="subtopic-title">{_render_inline_markdown(sub_title)}</h4>')
            else:
                html_lines.append(f'<h3 class="subsection-title">{_render_inline_markdown(sub_title)}</h3>')
            continue

        # Handle Main title (#) -> Skip or render cleanly
        if stripped.startswith("# "):
            close_open_containers()
            # If main title is already in header-card, we can skip duplicating it
            continue

        # Handle bullet points (- or *)
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            item_text = stripped[2:].strip()
            html_lines.append(f"<li>{_render_inline_markdown(item_text)}</li>")
            continue
        elif in_list:
            html_lines.append("</ul>")
            in_list = False

        if not stripped:
            continue

        # Normal paragraph
        p_rendered = _render_inline_markdown(stripped)
        html_lines.append(f"<p>{p_rendered}</p>")

    close_open_containers()
    if in_subtopic_item:
        html_lines.append("</div><!-- /.subtopic-item -->\n")
    if in_subtopics_grid:
        html_lines.append("</div><!-- /.subtopics-grid -->\n")
    if in_card:
        html_lines.append("</div><!-- /.content-card -->")

    return "\n".join(html_lines)


def generate_web_view(
    note_title: str, 
    auto_open: bool = False,
    create_pdf: bool = True
) -> Dict[str, Optional[str]]:
    """
    Renders an Obsidian research note into an interactive Web View (HTML)
    and automatically generates a standalone PDF report.
    Enforces a clean white academic theme, compact font size (15px screen, 13.5px print),
    2-column split grid for related sub-topics, closed formula boxes, and eliminates orphan page breaks.
    """
    logger.info(f"Generating clean web view and PDF for note: '{note_title}'")
    notes = global_fetch_obsidian_data(query=note_title)
    target_note = None
    for n in notes:
        if n["title"].lower() == note_title.lower() or note_title.lower() in n["title"].lower():
            target_note = n
            break

    if not target_note:
        target_note = fetch_from_obsidian(note_title)

    if not target_note:
        raise ValueError(f"Note '{note_title}' not found in Obsidian vault.")

    raw_content = target_note["content"]

    # Pre-processing: Exclude '## Primary Source Quotes & Verified Metrics' section
    filtered_content = re.sub(
        r'## Primary Source Quotes & Verified Metrics.*?(?=\n## |\Z)',
        '',
        raw_content,
        flags=re.DOTALL
    ).strip()

    body_html = markdown_to_html_enhanced(filtered_content)
    metadata = target_note.get("metadata", {})
    sources = metadata.get("sources", [])
    display_title = target_note['title'].replace('_', ' ')

    sources_html = "".join(f'<li><a href="{html.escape(s)}" target="_blank" rel="noopener noreferrer">{html.escape(s)}</a></li>' for s in sources) or "<li>Primary Research Input</li>"

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(display_title)} - Research Report</title>
    <!-- MathJax for rendering formulas and calculation symbols -->
    <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
        displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
        processEscapes: true
      }},
      options: {{
        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre']
      }}
    }};
    </script>
    <script type="text/javascript" id="MathJax-script" async
      src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js">
    </script>
    <style>
        :root {{
            --bg-canvas: #f8fafc;
            --bg-card: #ffffff;
            --card-border: #e2e8f0;
            --text-main: #1e293b;
            --text-muted: #64748b;
            --heading-color: #0f172a;
            --link-color: #2563eb;
            --link-hover: #1d4ed8;
            --formula-bg: #ffffff;
            --formula-border: #cbd5e1;
            --wikilink-bg: #f1f5f9;
            --wikilink-color: #1e40af;
            --wikilink-border: #cbd5e1;
            --quote-bg: #f8fafc;
            --quote-border: #3b82f6;
            --warning-bg: #fef2f2;
            --warning-border: #ef4444;
            --warning-text: #b91c1c;
        }}
        @media print {{
            body {{
                background: #ffffff !important;
                font-size: 13.5px !important;
                line-height: 1.45 !important;
                padding: 0 !important;
            }}
            .no-print {{ display: none !important; }}
            .container {{ max-width: 100% !important; padding: 0 !important; }}
            .header-card {{
                box-shadow: none !important;
                border: 1.5px solid #cbd5e1 !important;
                margin-bottom: 14px !important;
                padding: 14px 18px !important;
                page-break-inside: avoid !important;
                break-inside: avoid !important;
            }}
            .content-card {{
                box-shadow: none !important;
                border: 1.5px solid #cbd5e1 !important;
                page-break-inside: auto !important;
                break-inside: auto !important;
                margin-bottom: 14px !important;
                padding: 14px 18px !important;
            }}
            .subtopics-grid {{
                display: grid !important;
                grid-template-columns: 1fr 1fr !important;
                gap: 10px !important;
            }}
            .subtopic-item {{
                background: #ffffff !important;
                border: 1.5px solid #cbd5e1 !important;
                padding: 10px 12px !important;
                page-break-inside: avoid !important;
                break-inside: avoid !important;
                font-size: 0.9em !important;
            }}
            .formula-box {{
                background: #ffffff !important;
                border: 1.5px solid #94a3b8 !important;
                page-break-inside: avoid !important;
                break-inside: avoid !important;
                padding: 10px 14px !important;
                margin: 10px 0 !important;
            }}
        }}
        body {{
            margin: 0;
            padding: 30px 20px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-canvas);
            color: var(--text-main);
            font-size: 15px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 960px;
            margin: 0 auto;
        }}
        .action-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--card-border);
        }}
        .action-meta {{
            font-size: 0.9rem;
            color: var(--text-muted);
            font-weight: 500;
        }}
        .btn {{
            background: #2563eb;
            color: #ffffff;
            font-weight: 600;
            font-size: 0.9rem;
            border: none;
            padding: 7px 16px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .btn:hover {{ background: #1d4ed8; }}
        .header-card {{
            background: var(--bg-card);
            border: 1.5px solid var(--card-border);
            border-radius: 10px;
            padding: 20px 24px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        }}
        .main-title {{
            font-size: 1.7rem;
            font-weight: 800;
            color: var(--heading-color);
            margin: 0 0 6px 0;
            line-height: 1.25;
        }}
        .content-card {{
            background: var(--bg-card);
            border: 1.5px solid var(--card-border);
            border-radius: 10px;
            padding: 20px 24px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        }}
        .section-title {{
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--heading-color);
            margin: 0 0 14px 0;
            padding-bottom: 6px;
            border-bottom: 2px solid var(--card-border);
        }}
        .subsection-title {{
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--heading-color);
            margin: 18px 0 8px 0;
        }}
        .subtopics-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 14px;
            margin: 16px 0;
        }}
        @media (max-width: 768px) {{
            .subtopics-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .subtopic-item {{
            background: #f8fafc;
            border: 1.5px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px 16px;
            font-size: 0.93rem;
        }}
        .subtopic-title {{
            font-size: 1.02rem;
            font-weight: 700;
            color: var(--heading-color);
            margin: 0 0 8px 0;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 4px;
        }}
        p {{
            margin: 0 0 12px 0;
        }}
        ul {{
            margin: 0 0 14px 0;
            padding-left: 22px;
        }}
        li {{
            margin-bottom: 6px;
        }}
        strong {{
            font-weight: 700;
            color: #0f172a;
        }}
        .wikilink {{
            background: var(--wikilink-bg);
            color: var(--wikilink-color);
            border: 1px solid var(--wikilink-border);
            padding: 2px 7px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 0.92em;
        }}
        a {{
            color: var(--link-color);
            text-decoration: none;
            font-weight: 600;
        }}
        a:hover {{
            color: var(--link-hover);
            text-decoration: underline;
        }}
        .formula-box {{
            margin: 14px 0;
            padding: 14px 18px;
            background: var(--formula-bg);
            border: 1.5px solid var(--formula-border);
            border-radius: 8px;
            text-align: center;
            overflow-x: auto;
            font-size: 1.05rem;
            box-shadow: inset 0 1px 2px rgba(0,0,0,0.02);
        }}
        .quote-box {{
            margin: 14px 0;
            padding: 12px 18px;
            background: var(--quote-bg);
            border-left: 4px solid var(--quote-border);
            border-radius: 0 6px 6px 0;
            color: #334155;
            font-style: italic;
        }}
        .quote-box p {{
            margin: 0;
        }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 16px;
            font-size: 0.78rem;
            font-weight: 600;
            margin-left: 8px;
            vertical-align: middle;
        }}
        .badge.badge-warning {{
            background: var(--warning-bg);
            color: var(--warning-text);
            border: 1px solid var(--warning-border);
        }}
        .sources-card {{
            background: var(--bg-card);
            border: 1.5px solid var(--card-border);
            border-radius: 10px;
            padding: 20px 24px;
            margin-top: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        }}
        .sources-card h3 {{
            margin-top: 0;
            color: var(--heading-color);
            font-size: 1.15rem;
            border-bottom: 2px solid var(--card-border);
            padding-bottom: 6px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="action-bar no-print">
            <span class="action-meta">Executive Research Report &bull; {html.escape(display_title)}</span>
            <div>
                <button class="btn" onclick="window.print()">Print / Export PDF</button>
            </div>
        </div>

        <div class="header-card">
            <h1 class="main-title">{html.escape(display_title)}</h1>
            <div class="action-meta">Document Reference &bull; {len(sources)} Sources Analyzed &bull; Knowledge Base Verified</div>
        </div>

        <article>
            {body_html}
        </article>

        <div class="sources-card">
            <h3>Document Sources & Citations</h3>
            <ul>{sources_html}</ul>
        </div>
    </div>
</body>
</html>"""

    output_html_name = f"Report_{target_note['title']}.html"
    output_html_path = os.path.join(OUTPUT_DIR, output_html_name)
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html_template)

    logger.info(f"HTML report exported to: {output_html_path}")

    pdf_path = None
    if create_pdf:
        pdf_path = convert_html_to_pdf(output_html_path)

    if auto_open:
        webbrowser.open(f"file://{os.path.abspath(output_html_path)}")

    return {
        "html": output_html_path,
        "pdf": pdf_path
    }
