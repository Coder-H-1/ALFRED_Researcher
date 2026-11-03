"""
cli.py - Command-line interface for the Researcher module.
"""

import sys
import argparse
from .pipeline import ResearchPipeline


def main():
    parser = argparse.ArgumentParser(
        description="Iterative Research Pipeline with Obsidian Vault & LLM Synthesis"
    )
    parser.add_argument("topic", type=str, help="Research topic or primary query")
    parser.add_argument(
        "--inputs", 
        nargs="*", 
        help="Optional specific URLs or sub-queries. If omitted, topic is queried.",
        default=None
    )
    parser.add_argument("--max-sites", type=int, default=3, help="Number of sites to analyze (default: 3)")
    parser.add_argument("--open", action="store_true", help="Automatically open generated web view in browser")
    parser.add_argument("--vault", type=str, default=None, help="Custom Obsidian vault directory")

    args = parser.parse_args()

    pipeline = ResearchPipeline(topic=args.topic, vault_dir=args.vault)
    inputs = args.inputs if args.inputs else [args.topic]

    print(f"[*] Starting research on: '{args.topic}' across up to {args.max_sites} sources...")
    result = pipeline.run_iterative_research(
        inputs=inputs,
        max_sites=args.max_sites,
        auto_open_report=args.open
    )

    if result.get("status") == "success":
        print("\n[+] Research completed successfully!")
        print(f"    Topic:          {result['topic']}")
        print(f"    Vault Location: {result.get('vault_dir')}")
        print(f"    Note Created:   {result.get('note_file')}")
        print(f"    Sources:        {result['sources_processed']}")
        print(f"    Web View:       {result['report_html']}")
        print(f"    PDF Export:     {result['report_pdf']}")
        print(f"    Duration:       {result['elapsed_seconds']}s\n")
    else:
        print(f"\n[-] Research failed: {result.get('message')}")
        sys.exit(1)


if __name__ == "__main__":
    main()

