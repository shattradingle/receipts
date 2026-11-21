from __future__ import annotations

import json

from receipts.export import board_html, board_json, board_markdown, export_board

EXPECTED_MD = """# receipts · why do AI coding agents waste context window

2026-11-21T15:30:12Z · 3 quotes · 2 pages · 9 queries · 34.2s

No model. Every quote below is verbatim from a fetched page.

## Coverage

- queries: 9
- results: 87
- pages: 2 ok / 1 failed
- quotes: 3

## Themes

- **context window** (2): q1, q3
- **working set** (1): q2

## Quotes

> Every long-running coding agent eventually hits the same wall, and the wall is not intelligence but the size of the context window it has to carry.

— [bbc.co.uk](https://www.bbc.co.uk/news/context) · 2026-11-04 · via “why do AI coding agents waste context window”

> The practical fix is not a bigger model but a smaller working set: keep the task, the current files and the last error, and drop the rest.

— [example.org](https://example.org/context) · 2026-11-02 · via “ai coding agents”

> Teams that measured this found that trimming the history cut token spend by roughly half without changing the number of successful patches.

— [bbc.co.uk](https://www.bbc.co.uk/news/context) · 2026-11-04 · via “why do AI coding agents waste context window”

## Sources

| # | source | kind | status | date | quotes |
| --- | --- | --- | --- | --- | --- |
| s1 | [Why agents lose the thread](https://www.bbc.co.uk/news/context) | news | ok | 2026-11-04 | 2 |
| s2 | [Managing context](https://example.org/context) | wiki | ok | 2026-11-02 | 1 |
| s3 | [A page that refused](https://blocked.example.net/x) | web | blocked | n/a | 0 |

## Failures

- https://blocked.example.net/x · 403 (fetch)

---

No model wrote any sentence here. Every quote is a verbatim slice of a fetched page.
"""


def test_markdown_exact_string(board):
    assert board_markdown(board) == EXPECTED_MD


def test_markdown_no_failures(store, board):
    board = json.loads(json.dumps(board))
    board["failures"] = []
    text = board_markdown(board)
    assert "- None. Every request produced a page." in text


def test_json_export_round_trips(board):
    assert json.loads(board_json(board)) == board


def test_html_export_is_self_contained(board):
    html = board_html(board)
    assert "<title>receipts · why do AI coding agents waste context window</title>" in html
    assert "window.__RECEIPTS_BOARD__" in html
    assert "window.__RECEIPTS_STATIC__ = true" in html
    assert "__RECEIPTS_STATIC__" in html
    assert "<style>" in html
    assert "body class=\"static-board\"" in html
    assert board["quotes"][0]["text"] in html
    assert "<link rel=\"stylesheet\"" not in html
    assert 'src="http' not in html
    assert "<script src=" not in html
    # The inline CSS and JS came from package data, not from a CDN.
    assert "--accent: #8a1f11" in html
    assert "function renderBoard" in html


def test_html_export_has_open_graph_tags(board):
    html = board_html(board)
    assert '<meta property="og:title" content="receipts · why do AI coding agents waste context window">' in html
    assert '<meta property="og:image" content="https://shattradingle.github.io/receipts/screenshots/desk-light.png">' in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    assert "quotes from" in html and "blocked" in html


def test_html_export_escapes_script_close(board):
    board = json.loads(json.dumps(board))
    board["quotes"][0]["text"] = "A quote that tries </script><script>alert(1)</script> to break out."
    html = board_html(board)
    assert "</script><script>alert(1)" not in html
    assert "\\u003c/script\\u003e" in html


def test_export_board_writes_files(tmp_path, board):
    path = export_board(board, "md", tmp_path / "board.md")
    assert path.read_text(encoding="utf-8") == EXPECTED_MD
    html_path = export_board(board, "html", tmp_path / "board.html")
    assert "receipts" in html_path.read_text(encoding="utf-8")
    json_path = export_board(board, "json", tmp_path / "board.json")
    assert json.loads(json_path.read_text(encoding="utf-8")) == board


def test_export_rejects_unknown_format(tmp_path, board):
    import pytest

    with pytest.raises(ValueError):
        export_board(board, "pdf", tmp_path / "x")
