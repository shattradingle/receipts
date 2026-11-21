from __future__ import annotations

import json

from receipts.store import Store, state_dir


def test_save_and_load_round_trip(store, board):
    store.save_board(board)
    loaded = store.load_board(board["id"])
    assert loaded == board


def test_save_is_idempotent(store, board):
    store.save_board(board)
    store.save_board(board)
    assert store.load_board(board["id"]) == board
    assert len(store.list_runs()) == 1


def test_list_runs_newest_first(store, board):
    older = json.loads(json.dumps(board))
    older["id"] = "r-20261120-100000"
    older["started_at"] = "2026-11-20T10:00:00Z"
    newer = json.loads(json.dumps(board))
    newer["id"] = "r-20261121-100000"
    newer["started_at"] = "2026-11-21T10:00:00Z"
    store.save_board(older)
    store.save_board(newer)
    rows = store.list_runs()
    assert [row["id"] for row in rows] == [newer["id"], older["id"]]


def test_next_run_id_is_readable_and_unique(store, board):
    first = store.next_run_id("2026-11-21T15:30:12Z")
    assert first == "r-20261121-153012"
    board = dict(board)
    board["id"] = first
    store.save_board(board)
    second = store.next_run_id("2026-11-21T15:30:12Z")
    assert second == first + "-2"


def test_missing_run(store):
    assert store.load_board("r-nope") is None


def test_hits_are_recorded(store, board):
    from receipts.models import Hit

    hits = [
        Hit(url="https://example.com/a", title="A", date="2026-11-01", kind="web", via="q"),
        Hit(url="https://example.com/b", title="B", date="", kind="wiki", via="q"),
    ]
    store.save_board(board)
    store.save_hits(board["id"], hits, {"https://example.com/b"})
    assert store.hit_count(board["id"]) == 2


def test_requests_are_recorded(store, board):
    store.save_board(board)
    store.record_request(board["id"], "search", "GET", "https://example.com/x", 200, True, 0.2)
    store.record_request(board["id"], "fetch", "GET", "https://example.com/y", 403, False, 0.1, "403")
    assert store.request_count(board["id"]) == 2


def test_state_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RECEIPTS_HOME", str(tmp_path / "custom"))
    assert state_dir() == tmp_path / "custom"
    instance = Store()
    assert instance.path == tmp_path / "custom" / "receipts.db"
    instance.close()
