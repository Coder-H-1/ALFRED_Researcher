"""
server.py — Standalone Stdio Model Context Protocol (MCP) Server for Researcher

Allows Researcher to run in its own dedicated process and plug directly into
any MCP host (Claude Desktop, Cursor, Antigravity, or ALFRED's MCP bridge).
"""

import os
import sys
import json
import logging

# Ensure workspace and module directories are in sys.path
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKSPACE_ROOT = os.path.dirname(_BASE_DIR)
for p in (_WORKSPACE_ROOT, _BASE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from .pipeline import ResearchPipeline
    from .obsidian import _DEFAULT_VAULT
except (ImportError, ValueError):
    try:
        from pipeline import ResearchPipeline
        from obsidian import _DEFAULT_VAULT
    except ImportError:
        from Researcher.pipeline import ResearchPipeline
        from Researcher.obsidian import _DEFAULT_VAULT

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("ResearcherMCPServer")


def handle_list_tools() -> dict:
    """Returns MCP tools supported by Researcher."""
    return {
        "tools": [
            {
                "name": "deep_research",
                "description": "Performs iterative textual deep research into an Obsidian vault and produces HTML & PDF reports.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "The research topic or question"
                        },
                        "max_sites": {
                            "type": "integer",
                            "description": "Maximum number of sites to harvest (default 3)",
                            "default": 3
                        }
                    },
                    "required": ["topic"]
                }
            },
            {
                "name": "list_vault_notes",
                "description": "Lists all research notes currently present in the Obsidian Vault.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "read_vault_note",
                "description": "Reads the full markdown content of a research note from the Obsidian Vault.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "note_title": {
                            "type": "string",
                            "description": "Name or title of the note (with or without .md extension)"
                        }
                    },
                    "required": ["note_title"]
                }
            }
        ]
    }


def handle_call_tool(name: str, arguments: dict) -> dict:
    """Dispatches tool execution."""
    if name == "deep_research":
        topic = arguments.get("topic", "").strip()
        max_sites = int(arguments.get("max_sites", 3))
        if not topic:
            return {"error": "Missing 'topic' argument"}

        pipeline = ResearchPipeline(topic=topic)
        result = pipeline.run_iterative_research(
            inputs=[topic],
            max_sites=max_sites,
            auto_open_report=False
        )
        return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}

    elif name == "list_vault_notes":
        vault_path = _DEFAULT_VAULT.vault_path
        if not os.path.isdir(vault_path):
            return {"content": [{"type": "text", "text": "Vault directory not found."}]}
        notes = [f for f in os.listdir(vault_path) if f.endswith(".md")]
        return {"content": [{"type": "text", "text": json.dumps(notes, indent=2)}]}

    elif name == "read_vault_note":
        vault_path = _DEFAULT_VAULT.vault_path
        title = arguments.get("note_title", "").strip()
        if not title.endswith(".md"):
            title = f"{title}.md"
        path = os.path.join(vault_path, title)
        if not os.path.isfile(path):
            return {"error": f"Note '{title}' not found in vault."}
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": [{"type": "text", "text": content}]}

    return {"error": f"Unknown tool: {name}"}


def main():
    """Stdio JSON-RPC loop adhering to the Model Context Protocol."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            if method == "tools/list":
                res = handle_list_tools()
                response = {"jsonrpc": "2.0", "id": req_id, "result": res}
            elif method == "tools/call":
                res = handle_call_tool(params.get("name"), params.get("arguments", {}))
                response = {"jsonrpc": "2.0", "id": req_id, "result": res}
            elif method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "researcher-mcp-server", "version": "1.0.0"},
                        "capabilities": {"tools": {}}
                    }
                }
            elif method == "notifications/initialized":
                continue
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                }

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except Exception as e:
            logger.error(f"Error handling request: {e}", exc_info=True)


if __name__ == "__main__":
    main()
