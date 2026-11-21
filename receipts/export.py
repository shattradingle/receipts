"""Markdown, JSON and one self-contained HTML file.

The HTML export inlines the desk's CSS and JS and embeds the board, because the
public demo is opened straight from disk with no server and no network.
"""

from __future__ import annotations

from html import escape
import json
from importlib import resources
from pathlib import Path

from .store import exports_dir


def _data_text(name: str) -> str:
    return resources.files("receipts").joinpath("data", name).read_text(encoding="utf-8")


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def _md_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def board_markdown(board: dict) -> str:
    coverage = board["coverage"]
    sources = {source["id"]: source for source in board.get("sources", [])}
    lines: list[str] = [
        f"# receipts · {board['question']}",
        "",
        (
            f"{board['started_at']} · {coverage['quotes']} "
            f"{_plural(coverage['quotes'], 'quote', 'quotes')} · "
            f"{coverage['pages_ok']} {_plural(coverage['pages_ok'], 'page', 'pages')} · "
            f"{coverage['queries']} {_plural(coverage['queries'], 'query', 'queries')} · "
            f"{float(board['seconds']):.1f}s"
        ),
        "",
        "No model. Every quote below is verbatim from a fetched page.",
        "",
        "## Coverage",
        "",
        f"- queries: {coverage['queries']}",
        f"- results: {coverage['hits']}",
        f"- pages: {coverage['pages_ok']} ok / {coverage['pages_failed']} failed",
        f"- quotes: {coverage['quotes']}",
        "",
    ]

    themes = board.get("themes") or []
    lines.extend(["## Themes", ""])
    if themes:
        for theme in themes:
            lines.append(
                f"- **{theme['term']}** ({theme['count']}): " + ", ".join(theme["quotes"])
            )
    else:
        lines.append("- No term appeared in two or more quotes.")
    lines.append("")

    lines.extend(["## Quotes", ""])
    if not board.get("quotes"):
        lines.append("No sentence met the quote rules. The failures are listed below.")
        lines.append("")
    for quote in board.get("quotes", []):
        source = sources.get(quote["source_id"], {})
        url = source.get("url", "")
        domain = source.get("domain", "")
        date = source.get("date") or "date n/a"
        via = source.get("via", "")
        lines.append(f"> {quote['text']}")
        lines.append("")
        lines.append(f"— [{domain}]({url}) · {date} · via “{via}”")
        lines.append("")

    lines.extend([
        "## Sources",
        "",
        "| # | source | kind | status | date | quotes |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for source in board.get("sources", []):
        lines.append(
            f"| {source['id']} | [{_md_cell(source['title'] or source['domain'])}]"
            f"({source['url']}) | {source['kind']} | {source['status']} | "
            f"{source['date'] or 'n/a'} | {source['quotes']} |"
        )
    if not board.get("sources"):
        lines.append("| - | no sources | - | - | - | - |")
    lines.append("")

    lines.extend(["## Failures", ""])
    failures = board.get("failures") or []
    if failures:
        for failure in failures:
            where = failure.get("url") or "(run)"
            lines.append(
                f"- {where} · {failure['reason']} ({failure.get('stage', 'fetch')})"
            )
    else:
        lines.append("- None. Every request produced a page.")
    lines.extend([
        "",
        "---",
        "",
        "No model wrote any sentence here. Every quote is a verbatim slice of a fetched page.",
        "",
    ])
    return "\n".join(lines)


def _script_json(data: dict) -> str:
    # Escape angle brackets so a verbatim "</script>" in a quote cannot close the tag.
    text = json.dumps(data, ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _og_block(board: dict, title: str) -> str:
    """Open Graph tags so a shared link previews as the board, not a blank page."""
    from html import escape as esc

    coverage = board.get("coverage") or {}
    quotes = len(board.get("quotes") or [])
    sources = len(board.get("sources") or [])
    pages_ok = coverage.get("pages_ok", 0)
    pages_failed = coverage.get("pages_failed", 0)
    description = (
        f"{quotes} quotes from {sources} sources, {pages_ok} pages fetched and "
        f"{pages_failed} blocked. Every sentence carries its URL, its date and the "
        f"query that found it. No model was used."
    )
    image = "https://shattradingle.github.io/receipts/screenshots/desk-light.png"
    return (
        f'<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{esc(title)}">\n'
        f'<meta property="og:description" content="{esc(description)}">\n'
        f'<meta property="og:url" content="https://shattradingle.github.io/receipts/">\n'
        f'<meta property="og:image" content="{image}">\n'
        f'<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{esc(title)}">\n'
        f'<meta name="twitter:description" content="{esc(description)}">\n'
    )


def board_html(board: dict) -> str:
    """One file, opened straight from disk: inline CSS, inline JS, embedded board."""
    import re

    index = _data_text("index.html")
    css = _data_text("app.css")
    js = _data_text("app.js")
    title = f"receipts · {board['question']}"
    payload = _script_json(board)
    html = index.replace(
        '<link rel="stylesheet" href="app.css" data-receipts-asset="css">',
        f"<style>\n{css}\n</style>",
    )
    html = html.replace(
        '<script src="app.js" data-receipts-asset="js" defer></script>',
        f'<script>window.__RECEIPTS_BOARD__ = {payload}; window.__RECEIPTS_STATIC__ = true;</script>\n'
        f"<script>\n{js}\n</script>",
    )
    html = html.replace("<body>", '<body class="static-board">', 1)
    html = re.sub(r"<title>.*?</title>", f"<title>{escape(title)}</title>", html,
                  count=1, flags=re.S)
    og = _og_block(board, title)
    html = html.replace("</head>", og + "</head>", 1)
    return html


def board_json(board: dict) -> str:
    return json.dumps(board, indent=2, ensure_ascii=False) + "\n"


def export_board(board: dict, fmt: str, out: str | Path | None = None) -> Path:
    fmt = fmt.lower().lstrip(".")
    if fmt not in {"md", "html", "json"}:
        raise ValueError("format must be md, html or json")
    path = Path(out) if out else exports_dir() / f"receipts-{board['id']}.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        text = board_markdown(board)
    elif fmt == "html":
        text = board_html(board)
    else:
        text = board_json(board)
    path.write_text(text, encoding="utf-8")
    return path
