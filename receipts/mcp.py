"""A line-delimited JSON-RPC MCP server over stdio.

Two tools: run a research question, export a stored run. No network at import
time, no model, no key. Logging would corrupt the protocol, so it does not log.
"""

from __future__ import annotations

import json
import sys

from . import __version__
from .export import export_board
from .pipeline import run_research
from .store import Store

PROTOCOL = "2025-06-18"
SOURCES = ["web", "news", "hn", "wiki", "arxiv", "reddit"]

TOOLS = [
    {
        "name": "receipts_research",
        "description": (
            "Run a research question through keyless sources and return a board of "
            "verbatim quotes. Every quote has a source URL, a date and the query that "
            "found it. Nothing is generated."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to research."},
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": SOURCES},
                    "description": "Defaults to all six sources.",
                },
                "depth": {
                    "type": "integer", "minimum": 1, "maximum": 3,
                    "description": "1 one query, 2 three variants, 3 three variants plus links.",
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
    {
        "name": "receipts_export",
        "description": "Write a stored board to Markdown or HTML and return the file path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "The board id, for example r-20261121-153012."},
                "fmt": {"type": "string", "enum": ["md", "html", "json"]},
            },
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
]


def _result(request_id, value: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(request: dict, store: Store, run_fn=run_research) -> dict | None:
    """Handle one parsed JSON-RPC request. Returns a response dict or None."""
    if not isinstance(request, dict):
        return _error(None, -32600, "invalid request")
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "receipts", "version": __version__},
            "instructions": (
                "A source board, not an answer. Every quote is verbatim from a fetched "
                "page and keeps its URL, date and query."
            ),
        })
    if method in {"notifications/initialized", "initialized"}:
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        return _call(params, request_id, store, run_fn)
    if request_id is None:
        return None
    return _error(request_id, -32601, f"unknown method: {method}")


def _call(params: dict, request_id, store: Store, run_fn) -> dict:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name == "receipts_research":
        question = str(arguments.get("question") or "").strip()
        if len(question) < 3:
            return _error(request_id, -32602, "question must be at least 3 characters")
        sources = arguments.get("sources")
        if sources is not None:
            if not isinstance(sources, list) or not sources:
                return _error(request_id, -32602, "sources must be a non-empty list")
            bad = [item for item in sources if item not in SOURCES]
            if bad:
                return _error(request_id, -32602, f"unknown sources: {', '.join(map(str, bad))}")
        try:
            depth = int(arguments.get("depth", 2))
        except (TypeError, ValueError):
            return _error(request_id, -32602, "depth must be 1, 2 or 3")
        if depth not in (1, 2, 3):
            return _error(request_id, -32602, "depth must be 1, 2 or 3")
        try:
            board = run_fn(question=question, sources=sources, depth=depth, store=store)
        except Exception as exc:
            return _result(request_id, {
                "content": [{"type": "text", "text": f"run failed: {type(exc).__name__}: {exc}"}],
                "isError": True,
            })
        compact = json.dumps(board, ensure_ascii=False, separators=(",", ":"))
        return _result(request_id, {
            "content": [{"type": "text", "text": compact}],
            "structuredContent": board,
            "isError": False,
        })

    if name == "receipts_export":
        run_id = str(arguments.get("run_id") or "").strip()
        fmt = str(arguments.get("fmt") or "md").lower()
        if not run_id:
            return _error(request_id, -32602, "run_id is required")
        if fmt not in {"md", "html", "json"}:
            return _error(request_id, -32602, "fmt must be md, html or json")
        board = store.load_board(run_id)
        if board is None:
            return _result(request_id, {
                "content": [{"type": "text", "text": f"no run named {run_id}"}],
                "isError": True,
            })
        try:
            path = export_board(board, fmt)
        except Exception as exc:
            return _result(request_id, {
                "content": [{"type": "text", "text": f"export failed: {type(exc).__name__}: {exc}"}],
                "isError": True,
            })
        return _result(request_id, {
            "content": [{"type": "text", "text": str(path)}],
            "isError": False,
        })

    return _error(request_id, -32602, f"unknown tool: {name}")


def main(stdin=None, stdout=None, store: Store | None = None, run_fn=run_research) -> int:
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    owned = store is None
    store = store or Store()
    try:
        for line in source:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                response = _error(None, -32700, "parse error")
            else:
                try:
                    response = handle(request, store, run_fn)
                except Exception as exc:
                    response = _error(
                        request.get("id") if isinstance(request, dict) else None,
                        -32603, f"internal error: {type(exc).__name__}",
                    )
            if response is not None:
                sink.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
                sink.flush()
    finally:
        if owned:
            store.close()
    return 0
