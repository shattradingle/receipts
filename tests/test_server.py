from __future__ import annotations

import json

from receipts import __version__
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import receipts.server as server_module
from receipts.server import make_server


def http(url, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def start(store, demo=False, runner=None, board=None, monkeypatch=None):
    if demo:
        monkeypatch.setattr(server_module, "load_demo_board", lambda: board)
    server = make_server("127.0.0.1", 0, demo=demo, store=store, runner=runner)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    return base, server, thread


def stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_index_served(store):
    base, server, thread = start(store)
    try:
        status, headers, body = http(base + "/")
        text = body.decode("utf-8")
        assert status == 200
        assert "text/html" in headers["Content-Type"]
        assert 'id="question"' in text
        assert "app.js" in text
        assert "Every sentence is a quote" in text or "every sentence is a quote" in text
    finally:
        stop(server, thread)


def test_assets_served(store):
    base, server, thread = start(store)
    try:
        status, headers, body = http(base + "/app.css")
        assert status == 200
        assert "--accent: #8a1f11" in body.decode("utf-8")
        status, headers, body = http(base + "/app.js")
        assert status == 200
        assert "function renderBoard" in body.decode("utf-8")
    finally:
        stop(server, thread)


def test_404_is_json(store):
    base, server, thread = start(store)
    try:
        status, headers, body = http(base + "/api/nope")
        assert status == 404
        assert json.loads(body)["error"] == "not found"
        status, headers, body = http(base + "/nope")
        assert status == 404
    finally:
        stop(server, thread)


def test_run_create_poll_board_and_export(store, board):
    def runner(question, sources, depth, store, run_id, progress):
        progress({"stage": "searching", "queries": 1, "queries_total": 3,
                  "hits": 4, "pages_ok": 0, "pages_failed": 0, "quotes": 0})
        result = json.loads(json.dumps(board))
        result["id"] = run_id
        result["question"] = question
        store.save_board(result)
        progress({"stage": "done", **result["coverage"],
                  "queries_total": result["coverage"]["queries"]})
        return result

    base, server, thread = start(store, runner=runner)
    try:
        status, headers, body = http(base + "/api/runs", "POST", {
            "question": "why do AI coding agents waste context window",
            "sources": ["web", "wiki"],
            "depth": 1,
        })
        assert status == 202
        run_id = json.loads(body)["id"]
        deadline = time.time() + 3
        payload = None
        while time.time() < deadline:
            status, headers, body = http(base + "/api/runs/" + run_id)
            payload = json.loads(body)
            if payload["status"] != "running":
                break
            time.sleep(0.02)
        assert payload["status"] == "done"
        assert payload["board"]["id"] == run_id
        assert payload["board"]["quotes"]
        status, headers, body = http(base + "/api/runs/" + run_id + "/board")
        assert status == 200
        assert json.loads(body)["id"] == run_id
        status, headers, body = http(base + "/api/runs/" + run_id + "/export?fmt=md")
        assert status == 200
        assert "attachment" in headers["Content-Disposition"]
        assert "why do AI coding agents waste context window" in body.decode("utf-8")
        status, headers, body = http(base + "/api/runs")
        assert [row["id"] for row in json.loads(body)["runs"]] == [run_id]
    finally:
        stop(server, thread)


def test_post_validation(store):
    base, server, thread = start(store)
    try:
        assert http(base + "/api/runs", "POST", {"question": ""})[0] == 400
        assert http(base + "/api/runs", "POST", {"question": "x"})[0] == 400
        assert http(base + "/api/runs", "POST", {
            "question": "a real question", "sources": ["bogus"],
        })[0] == 400
        assert http(base + "/api/runs", "POST", {
            "question": "a real question", "sources": ["hn"], "depth": 9,
        })[0] == 400
        assert http(base + "/api/runs/nope")[0] == 404
    finally:
        stop(server, thread)


def test_demo_mode(store, board, monkeypatch):
    base, server, thread = start(store, demo=True, board=board, monkeypatch=monkeypatch)
    try:
        status, headers, body = http(base + "/api/config")
        assert json.loads(body)["demo"] is True
        status, headers, body = http(base + "/api/demo")
        assert json.loads(body)["id"] == board["id"]
        status, headers, body = http(base + "/api/runs", "POST", {"question": "anything"})
        assert status == 409
        assert "no network" in json.loads(body)["error"]
        status, headers, body = http(base + "/api/demo/export?fmt=html")
        assert status == 200
        assert "__RECEIPTS_BOARD__" in body.decode("utf-8")
        status, headers, body = http(base + "/api/runs")
        assert json.loads(body)["runs"] == []
    finally:
        stop(server, thread)


def test_config(store):
    base, server, thread = start(store)
    try:
        status, headers, body = http(base + "/api/config")
        payload = json.loads(body)
        assert payload["demo"] is False
        assert payload["version"] == __version__
        assert set(payload["sources"]) == {"web", "news", "hn", "wiki", "arxiv", "reddit"}
    finally:
        stop(server, thread)
