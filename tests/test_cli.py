from __future__ import annotations

import copy
import json

import pytest

from receipts.cli import main
from receipts.store import Store


def run_cli(monkeypatch, tmp_path, argv, board=None):
    monkeypatch.setenv("RECEIPTS_HOME", str(tmp_path / "state"))
    if board is not None:
        def fake_run(question, **kwargs):
            result = copy.deepcopy(board)
            result["question"] = question
            return result
        monkeypatch.setattr("receipts.cli.run_research", fake_run)


def test_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "receipts 1.0.0" in capsys.readouterr().out


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "research" in capsys.readouterr().out


def test_no_command_is_usage_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 64
    assert "usage" in capsys.readouterr().err


def test_unknown_source(tmp_path, monkeypatch, capsys):
    run_cli(monkeypatch, tmp_path, [])
    assert main(["research", "a question", "--sources", "myspace"]) == 64
    assert "unknown source" in capsys.readouterr().err


def test_bad_max_pages(tmp_path, monkeypatch):
    run_cli(monkeypatch, tmp_path, [])
    assert main(["research", "a question", "--sources", "hn", "--max-pages", "0"]) == 64


def test_research_json_and_out(tmp_path, monkeypatch, board, capsys):
    run_cli(monkeypatch, tmp_path, [], board=board)
    out = tmp_path / "board-out"
    code = main([
        "research", "why do AI coding agents waste context window",
        "--sources", "hn,wiki", "--depth", "1", "--json", "--out", str(out),
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["question"] == "why do AI coding agents waste context window"
    assert (out / "board.json").exists()
    assert (out / "board.md").exists()
    assert (out / "board.html").exists()


def test_research_exit_one_when_no_quotes(tmp_path, monkeypatch, board):
    empty = copy.deepcopy(board)
    empty["quotes"] = []
    empty["themes"] = []
    empty["coverage"]["quotes"] = 0
    run_cli(monkeypatch, tmp_path, [], board=empty)
    assert main(["research", "a question", "--sources", "hn"]) == 1


def test_research_exit_two_when_nothing_reached(tmp_path, monkeypatch, board):
    dead = copy.deepcopy(board)
    dead["quotes"] = []
    dead["themes"] = []
    dead["sources"] = []
    dead["coverage"] = {"queries": 1, "hits": 0, "pages_ok": 0, "pages_failed": 0, "quotes": 0}
    dead["failures"] = [{"url": "hn", "reason": "403", "stage": "search"}]
    run_cli(monkeypatch, tmp_path, [], board=dead)
    assert main(["research", "a question", "--sources", "hn"]) == 2


def test_board_and_list(tmp_path, monkeypatch, board, capsys):
    monkeypatch.setenv("RECEIPTS_HOME", str(tmp_path / "state"))
    store = Store()
    store.save_board(board)
    store.close()
    assert main(["board", board["id"]]) == 0
    text = capsys.readouterr().out
    assert board["question"] in text
    assert "Nothing here was generated." in text
    assert main(["board", board["id"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == board["id"]
    assert main(["list"]) == 0
    assert board["id"] in capsys.readouterr().out


def test_board_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RECEIPTS_HOME", str(tmp_path / "state"))
    assert main(["board", "r-nope"]) == 1
    assert "no run named" in capsys.readouterr().err


def test_list_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RECEIPTS_HOME", str(tmp_path / "state"))
    assert main(["list"]) == 0
    assert "No runs yet" in capsys.readouterr().out


def test_export(tmp_path, monkeypatch, board, capsys):
    monkeypatch.setenv("RECEIPTS_HOME", str(tmp_path / "state"))
    store = Store()
    store.save_board(board)
    store.close()
    target = tmp_path / "x.md"
    assert main(["export", board["id"], "--md", "--out", str(target)]) == 0
    assert target.read_text(encoding="utf-8").startswith("# receipts ·")
    assert main(["export", "r-nope", "--md"]) == 1


def test_export_requires_format(tmp_path, monkeypatch):
    monkeypatch.setenv("RECEIPTS_HOME", str(tmp_path / "state"))
    with pytest.raises(SystemExit) as excinfo:
        main(["export", "r-x"])
    assert excinfo.value.code == 64
