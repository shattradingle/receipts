"""Command line: serve, demo, research, board, list, export, mcp."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import __version__
from .adapters import DEFAULT_SOURCES
from .export import board_json, board_markdown, export_board
from .mcp import main as mcp_main
from .pipeline import run_research
from .server import serve
from .store import Store


class ReceiptsParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(64, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = ReceiptsParser(
        prog="receipts",
        description="A research desk that cannot hallucinate: verbatim quotes with receipts.",
    )
    parser.add_argument("--version", action="version", version=f"receipts {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    desk = sub.add_parser("serve", help="serve the desk")
    desk.add_argument("--host", default="127.0.0.1")
    desk.add_argument("--port", type=int, default=8787)
    desk.add_argument("--open", action="store_true", help="open the desk in a browser")
    desk.set_defaults(func=cmd_serve)

    demo = sub.add_parser("demo", help="serve a baked board with no network")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8788)
    demo.set_defaults(func=cmd_demo)

    research = sub.add_parser("research", help="run a question")
    research.add_argument("question")
    research.add_argument("--sources", default=",".join(DEFAULT_SOURCES),
                          metavar="web,news,reddit,hn,wiki,arxiv")
    research.add_argument("--depth", type=int, choices=(1, 2, 3), default=1)
    research.add_argument("--max-pages", type=int, default=12, metavar="N")
    research.add_argument("--json", action="store_true", dest="as_json")
    research.add_argument("--out", metavar="DIR", help="write board.json, board.md and board.html")
    research.set_defaults(func=cmd_research)

    board = sub.add_parser("board", help="print a stored board")
    board.add_argument("run_id")
    board.add_argument("--json", action="store_true", dest="as_json")
    board.set_defaults(func=cmd_board)

    listing = sub.add_parser("list", help="list recent runs")
    listing.add_argument("--limit", type=int, default=20)
    listing.set_defaults(func=cmd_list)

    export = sub.add_parser("export", help="export a stored board")
    export.add_argument("run_id")
    group = export.add_mutually_exclusive_group(required=True)
    group.add_argument("--md", action="store_const", const="md", dest="fmt")
    group.add_argument("--html", action="store_const", const="html", dest="fmt")
    export.add_argument("--out", metavar="FILE")
    export.set_defaults(func=cmd_export)

    mcp = sub.add_parser("mcp", help="stdio MCP server")
    mcp.set_defaults(func=cmd_mcp)
    return parser


def parse_sources(value: str) -> list[str]:
    requested = [part.strip() for part in (value or "").split(",") if part.strip()]
    unknown = [name for name in requested if name not in DEFAULT_SOURCES]
    if unknown:
        raise ValueError(f"unknown source(s): {', '.join(unknown)}")
    selected = [name for name in DEFAULT_SOURCES if name in requested]
    if not selected:
        raise ValueError("pick at least one source")
    return selected


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def _short(text: str, width: int = 72) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def print_board(board: dict) -> None:
    coverage = board["coverage"]
    sources = {source["id"]: source for source in board.get("sources", [])}
    print(f"receipts · {board['question']}")
    print(
        f"{board['started_at']} · {coverage['quotes']} "
        f"{_plural(coverage['quotes'], 'quote', 'quotes')} · "
        f"{coverage['pages_ok']} {_plural(coverage['pages_ok'], 'page', 'pages')} ok / "
        f"{coverage['pages_failed']} blocked · "
        f"{coverage['queries']} {_plural(coverage['queries'], 'query', 'queries')} · "
        f"{float(board['seconds']):.1f}s"
    )
    print()
    print("THEMES")
    themes = board.get("themes") or []
    if themes:
        for theme in themes:
            print(f"  {theme['term']} ({theme['count']})")
    else:
        print("  no term appears in two quotes")
    print()
    print("QUOTES")
    if board.get("quotes"):
        for quote in board["quotes"]:
            source = sources.get(quote["source_id"], {})
            print(f'  "{quote["text"]}"')
            print(
                f"  — {source.get('domain', '?')} · {source.get('date') or 'date n/a'}"
                f" · via “{source.get('via', '')}”"
            )
            print()
    else:
        print("  no sentence met the quote rules")
        print()
    print("SOURCES")
    if board.get("sources"):
        for source in board["sources"]:
            title = _short(source["title"] or source["domain"], 54)
            print(
                f"  {source['id']:<3} {source['status']:<8} {source['kind']:<7} "
                f"{source['quotes']:>2}q  {source['domain']}  {title}"
            )
    else:
        print("  none")
    print()
    print("FAILURES")
    failures = board.get("failures") or []
    if failures:
        for failure in failures:
            print(f"  {failure.get('url') or '(run)'}  {failure['reason']} ({failure.get('stage', 'fetch')})")
    else:
        print("  none: every request produced a page")
    print()
    print("Nothing here was generated.")


def cmd_research(args) -> int:
    try:
        sources = parse_sources(args.sources)
    except ValueError as exc:
        print(f"receipts: {exc}", file=sys.stderr)
        return 64
    if args.max_pages < 1:
        print("receipts: --max-pages must be at least 1", file=sys.stderr)
        return 64
    store = Store()
    try:
        board = run_research(
            args.question,
            sources=sources,
            depth=args.depth,
            max_pages=args.max_pages,
            store=store,
        )
        if args.out:
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "board.json").write_text(board_json(board), encoding="utf-8")
            (out / "board.md").write_text(board_markdown(board), encoding="utf-8")
            export_board(board, "html", out / "board.html")
        if args.as_json:
            sys.stdout.write(board_json(board))
        else:
            print_board(board)
        coverage = board["coverage"]
        if coverage["pages_ok"] == 0 and len(board["failures"]) >= len(sources):
            return 2
        if coverage["quotes"] == 0:
            return 1
        return 0
    except ValueError as exc:
        print(f"receipts: {exc}", file=sys.stderr)
        return 64
    finally:
        store.close()


def cmd_board(args) -> int:
    store = Store()
    try:
        board = store.load_board(args.run_id)
    finally:
        store.close()
    if board is None:
        print(f"receipts: no run named {args.run_id}", file=sys.stderr)
        return 1
    if args.as_json:
        sys.stdout.write(board_json(board))
    else:
        print_board(board)
    return 0


def cmd_list(args) -> int:
    store = Store()
    try:
        rows = store.list_runs(max(1, args.limit))
    finally:
        store.close()
    if not rows:
        print("No runs yet. Try: receipts research \"your question\" --sources hn,wiki")
        return 0
    print(f"{'ID':<22} {'QUOTES':>6} {'PAGES':>5} {'SECONDS':>7}  QUESTION")
    for row in rows:
        print(
            f"{row['id']:<22} {row['quotes']:>6} {row['pages_ok']:>5} "
            f"{float(row['seconds']):>7.1f}  {_short(row['question'], 80)}"
        )
    return 0


def cmd_export(args) -> int:
    store = Store()
    try:
        board = store.load_board(args.run_id)
        if board is None:
            print(f"receipts: no run named {args.run_id}", file=sys.stderr)
            return 1
        path = export_board(board, args.fmt, args.out)
    finally:
        store.close()
    print(path)
    return 0


def _serve_or_report(args, demo: bool) -> int:
    try:
        serve(host=args.host, port=args.port, demo=demo,
              open_browser=getattr(args, "open", False))
    except FileNotFoundError:
        print("receipts: demo_board.json is missing from package data", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"receipts: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        # EADDRINUSE is 98 on Linux, 48 on macOS and 10048 on Windows.
        if getattr(exc, "errno", None) in {48, 98, 10048}:
            print(
                f"receipts: port {args.port} is already in use. "
                f"Try --port {args.port + 1}.",
                file=sys.stderr,
            )
            return 1
        raise
    return 0


def cmd_serve(args) -> int:
    return _serve_or_report(args, demo=False)


def cmd_demo(args) -> int:
    return _serve_or_report(args, demo=True)


def cmd_mcp(args) -> int:
    return mcp_main()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
