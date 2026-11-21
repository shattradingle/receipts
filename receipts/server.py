"""The desk server. Stdlib http.server, one page, no external assets.

GET  /                     the desk
GET  /app.css /app.js      its two assets
GET  /api/config           demo flag and version
POST /api/runs             start a run {question, sources, depth}
GET  /api/runs/<id>        running progress, or the finished board
GET  /api/runs/<id>/board  the board alone
GET  /api/runs/<id>/export?fmt=md|html|json
GET  /api/demo             the baked board, demo mode only
GET  /api/demo/export?fmt=...
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
import json
import sys
import threading
from urllib.parse import parse_qs, urlparse
import webbrowser

from . import __version__
from .adapters import DEFAULT_SOURCES
from .demo import demo_board as load_demo_board
from .export import board_html, board_json, board_markdown
from .pipeline import run_research
from .store import Store

MAX_BODY = 64 * 1024
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/banner.svg": ("banner.svg", "image/svg+xml"),
}
EXPORT_TYPES = {
    "md": ("text/markdown; charset=utf-8", "md"),
    "html": ("text/html; charset=utf-8", "html"),
    "json": ("application/json; charset=utf-8", "json"),
}


def _data(name: str) -> str:
    return resources.files("receipts").joinpath("data", name).read_text(encoding="utf-8")


class DeskServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store: Store, demo: bool = False,
                 runner=None, demo_board: dict | None = None):
        super().__init__(address, DeskHandler)
        self.store = store
        self.demo = bool(demo)
        self.runner = runner or run_research
        self.demo_board = demo_board
        self.runs: dict[str, dict] = {}
        self.lock = threading.Lock()

    # ---------------------------------------------------------- run registry
    def allocate_id(self) -> str:
        with self.lock:
            base = self.store.next_run_id()
            candidate, n = base, 1
            while candidate in self.runs or self.store.has_run(candidate):
                n += 1
                candidate = f"{base}-{n}"
            self.runs[candidate] = {
                "status": "queued",
                "progress": {
                    "stage": "queued", "queries": 0, "queries_total": 0,
                    "hits": 0, "pages_ok": 0, "pages_failed": 0, "quotes": 0,
                },
            }
            return candidate

    def progress(self, run_id: str, data: dict) -> None:
        with self.lock:
            run = self.runs.get(run_id)
            if run is not None:
                run["progress"] = dict(data)

    def finish(self, run_id: str, board: dict) -> None:
        with self.lock:
            run = self.runs.get(run_id)
            if run is not None:
                run["status"] = "done"
                run["board"] = board
                run["progress"] = {
                    "stage": "done", **board["coverage"],
                    "queries_total": board["coverage"]["queries"],
                }

    def fail(self, run_id: str, message: str) -> None:
        with self.lock:
            run = self.runs.get(run_id)
            if run is not None:
                run["status"] = "error"
                run["error"] = message

    def work(self, run_id: str, question: str, sources: list[str], depth: int) -> None:
        try:
            board = self.runner(
                question=question,
                sources=sources,
                depth=depth,
                store=self.store,
                run_id=run_id,
                progress=lambda data: self.progress(run_id, data),
            )
            self.finish(run_id, board)
        except Exception as exc:  # a bad run must not stop the server
            self.fail(run_id, f"{type(exc).__name__}: {exc}")

    def find_board(self, run_id: str) -> dict | None:
        with self.lock:
            run = self.runs.get(run_id)
            if run is not None and run.get("status") == "done":
                return run.get("board")
        return self.store.load_board(run_id)


class DeskHandler(BaseHTTPRequestHandler):
    server_version = "receipts/" + __version__
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------ send
    def _send(self, status: int, body: bytes, content_type: str,
              extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    # ------------------------------------------------------------------- GET
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return

        if path in STATIC:
            name, content_type = STATIC[path]
            try:
                body = _data(name).encode("utf-8")
            except FileNotFoundError:
                self._error(500, f"missing package data: {name}")
                return
            self._send(200, body, content_type)
            return

        if path == "/api/config":
            self._json(200, {
                "demo": self.server.demo,
                "version": __version__,
                "sources": list(DEFAULT_SOURCES),
                "default_depth": 2,
            })
            return

        if path == "/api/demo":
            if not self.server.demo or not self.server.demo_board:
                self._error(404, "no demo board in this mode")
                return
            self._json(200, self.server.demo_board)
            return

        if path == "/api/demo/export":
            if not self.server.demo or not self.server.demo_board:
                self._error(404, "no demo board in this mode")
                return
            self._export(self.server.demo_board, "demo", query)
            return

        if path == "/api/runs":
            rows = self.server.store.list_runs(20) if not self.server.demo else []
            self._json(200, {"runs": rows})
            return

        if path.startswith("/api/runs/"):
            rest = path[len("/api/runs/"):]
            parts = [part for part in rest.split("/") if part]
            if not parts:
                self._error(400, "run id required")
                return
            run_id = parts[0]
            if len(parts) == 1:
                self._run_status(run_id)
                return
            if parts[1] == "board" and len(parts) == 2:
                board = self.server.find_board(run_id)
                if board is None:
                    self._error(404, "run not found")
                else:
                    self._json(200, board)
                return
            if parts[1] == "export" and len(parts) == 2:
                board = self.server.find_board(run_id)
                if board is None:
                    self._error(404, "run not found")
                    return
                self._export(board, run_id, query)
                return
        self._error(404, "not found")

    def _run_status(self, run_id: str) -> None:
        if self.server.demo:
            self._error(404, "demo mode has no live runs")
            return
        with self.server.lock:
            run = dict(self.server.runs.get(run_id)) if run_id in self.server.runs else None
        if run is not None:
            if run["status"] == "done":
                self._json(200, {"status": "done", "board": run["board"]})
            elif run["status"] == "error":
                self._json(200, {"status": "error", "error": run.get("error", "run failed")})
            else:
                self._json(200, {"status": "running", "progress": run.get("progress", {})})
            return
        board = self.server.store.load_board(run_id)
        if board is None:
            self._error(404, "run not found")
            return
        self._json(200, {"status": "done", "board": board})

    def _export(self, board: dict, run_id: str, query: dict) -> None:
        fmt = (query.get("fmt") or ["md"])[0].lower()
        if fmt not in EXPORT_TYPES:
            self._error(400, "fmt must be md, html or json")
            return
        content_type, extension = EXPORT_TYPES[fmt]
        if fmt == "md":
            body = board_markdown(board)
        elif fmt == "html":
            body = board_html(board)
        else:
            body = board_json(board)
        filename = f"receipts-{run_id}.{extension}"
        self._send(200, body.encode("utf-8"), content_type, {
            "Content-Disposition": f'attachment; filename="{filename}"',
        })

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/runs":
            self._error(404, "not found")
            return
        if self.server.demo:
            self._error(409, "demo mode serves a baked board and makes no network requests")
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._error(400, "expected a small JSON body")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(400, "body is not JSON")
            return
        if not isinstance(payload, dict):
            self._error(400, "body must be a JSON object")
            return
        question = " ".join(str(payload.get("question") or "").split())
        if len(question) < 3 or len(question) > 400:
            self._error(400, "question must be 3 to 400 characters")
            return
        requested = payload.get("sources")
        if requested is None:
            sources = list(DEFAULT_SOURCES)
        elif isinstance(requested, list):
            sources = [name for name in DEFAULT_SOURCES if name in requested]
        else:
            self._error(400, "sources must be a list")
            return
        if not sources:
            self._error(400, "pick at least one known source")
            return
        try:
            depth = int(payload.get("depth", 2))
        except (TypeError, ValueError):
            self._error(400, "depth must be 1, 2 or 3")
            return
        if depth not in (1, 2, 3):
            self._error(400, "depth must be 1, 2 or 3")
            return
        run_id = self.server.allocate_id()
        thread = threading.Thread(
            target=self.server.work, args=(run_id, question, sources, depth), daemon=True
        )
        thread.start()
        self._json(202, {"id": run_id, "status": "started"})

    # ------------------------------------------------------------------ HEAD
    def do_HEAD(self) -> None:
        self.do_GET()

    def log_message(self, format: str, *args) -> None:
        # A quiet desk. The CLI prints the URL it is serving.
        return


def make_server(host: str = "127.0.0.1", port: int = 8787, demo: bool = False,
                store: Store | None = None, runner=None) -> DeskServer:
    store = store or Store()
    board = load_demo_board() if demo else None
    return DeskServer((host, int(port)), store, demo=demo, runner=runner, demo_board=board)


def serve(host: str = "127.0.0.1", port: int = 8787, demo: bool = False,
          open_browser: bool = False, store: Store | None = None) -> None:
    server = make_server(host, port, demo=demo, store=store)
    actual_host, actual_port = server.server_address[0], server.server_address[1]
    url = f"http://{actual_host}:{actual_port}/"
    label = "demo" if demo else "desk"
    print(f"receipts {label} → {url}")
    print("Ctrl-C to stop.")
    sys.stdout.flush()
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print()
    finally:
        server.shutdown()
        server.server_close()
        server.store.close()
