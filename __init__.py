"""
Researcher Package
Modular iterative web-research system with Obsidian integration, thread-locking,
and LLM synthesis with strict false-consensus and quote-erasure protections.
"""

from .collector import (
    collect_links, 
    collect_links_from_search, 
    collect_links_from_content,
    filter_relevant_sublinks
)
from .scraper import fetch_url, fetch_urls_parallel, scrape_and_store_multiple
from .cleaner import (
    format_research_note, 
    clean_markdown_formatting, 
    strip_html_tags,
    extract_referenced_links
)
from .temp_manager import TempResearchStorage
from .obsidian import (
    ObsidianVault,
    store_in_obsidian,
    fetch_from_obsidian,
    global_fetch_obsidian_data,
    _DEFAULT_VAULT
)
from .synthesizer import synthesize_and_update
from .showcase import generate_web_view
from .pipeline import ResearchPipeline
from .llm_manager import (
    ResearcherLLM,
    ResearchContextManager,
    ResearchSynthesizer,
    get_researcher_llm,
    unload_researcher_llm
)

__all__ = [
    # Function 1
    "collect_links",
    "collect_links_from_search",
    "collect_links_from_content",
    "filter_relevant_sublinks",
    # Function 2
    "fetch_url",
    "fetch_urls_parallel",
    "scrape_and_store_multiple",
    # Function 3
    "format_research_note",
    "clean_markdown_formatting",
    "strip_html_tags",
    "extract_referenced_links",
    # Temp Storage
    "TempResearchStorage",
    # Function 4
    "store_in_obsidian",
    # Function 5
    "fetch_from_obsidian",
    # Function 6
    "synthesize_and_update",
    # Function 7
    "global_fetch_obsidian_data",
    # Showcase & Pipeline
    "ObsidianVault",
    "generate_web_view",
    "ResearchPipeline",
    # LLM Manager
    "ResearcherLLM",
    "ResearchContextManager",
    "ResearchSynthesizer",
    "get_researcher_llm",
    "unload_researcher_llm"
]
