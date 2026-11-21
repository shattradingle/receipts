from __future__ import annotations

import io
import json

from receipts.mcp import TOOLS, handle, main


def test_initialize():
    response = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, None)
    assert response["id"] == 1
    result = response["result"]
    assert result["serverInfo"]["name"] == "receipts"
    assert result["capabilities"]["tools"] == {}
    assert result["protocolVersion"]


def test_tools_list():
    response = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, None)
    tools = response["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["receipts_research", "receipts_export"]
    assert tools[0]["inputSchema"]["required"] == ["question"]
    assert "reddit" in tools[0]["inputSchema"]["properties"]["sources"]["items"]["enum"]


def test_research_call(store, board):
    calls = {}

    def runner(**kwargs):
        calls.update(kwargs)
        result = json.loads(json.dumps(board))
        result["question"] = kwargs["question"]
        return result

    response = handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "receipts_research", "arguments": {
            "question": "why do AI coding agents waste context window",
            "sources": ["web", "wiki"], "depth": 2,
        }},
    }, store, runner)
    result = response["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["quotes"]
    assert result["structuredContent"] == payload
    assert calls["question"].startswith("why do")
    assert calls["sources"] == ["web", "wiki"]
    assert calls["depth"] == 2


def test_research_rejects_empty_question(store):
    response = handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "receipts_research", "arguments": {"question": ""}},
    }, store)
    assert response["error"]["code"] == -32602


def test_research_rejects_unknown_source(store):
    response = handle({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "receipts_research",
                   "arguments": {"question": "a question", "sources": ["myspace"]}},
    }, store)
    assert response["error"]["code"] == -32602


def test_export_call(store, board, tmp_path):
    store.save_board(board)
    response = handle({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "receipts_export",
                   "arguments": {"run_id": board["id"], "fmt": "md"}},
    }, store)
    path = response["result"]["content"][0]["text"]
    assert response["result"]["isError"] is False
    assert path.endswith(".md")
    with open(path, encoding="utf-8") as handle_file:
        assert "why do AI coding agents waste context window" in handle_file.read()


def test_export_missing_run(store):
    response = handle({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "receipts_export", "arguments": {"run_id": "r-nope"}},
    }, store)
    assert response["result"]["isError"] is True


def test_unknown_tool(store):
    response = handle({
        "jsonrpc": "2.0", "id": 8, "method": "tools/call",
        "params": {"name": "nope", "arguments": {}},
    }, store)
    assert response["error"]["code"] == -32602


def test_unknown_method():
    response = handle({"jsonrpc": "2.0", "id": 9, "method": "nope"}, None)
    assert response["error"]["code"] == -32601


def test_notification_has_no_response():
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, None) is None


def test_stdio_loop(store):
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "nope"},
    ]
    source = io.StringIO("\n".join(json.dumps(line) for line in lines) + "\n")
    sink = io.StringIO()
    assert main(stdin=source, stdout=sink, store=store) == 0
    output = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert len(output) == 3
    assert output[0]["id"] == 1
    assert output[1]["result"]["tools"]
    assert output[2]["error"]["code"] == -32601


def test_stdio_parse_error(store):
    source = io.StringIO("this is not json\n")
    sink = io.StringIO()
    main(stdin=source, stdout=sink, store=store)
    output = json.loads(sink.getvalue())
    assert output["error"]["code"] == -32700
