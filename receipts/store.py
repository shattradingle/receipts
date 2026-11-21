"""SQLite state: runs, sources, quotes, themes, failures and every request.

The board is written as rows so `receipts board <id>` is a database read, not a
replay of the network. Requests are kept separately: they are the audit trail,
including the ones that failed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

from .models import now_iso

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    seconds REAL NOT NULL,
    queries INTEGER NOT NULL,
    hits INTEGER NOT NULL,
    pages_ok INTEGER NOT NULL,
    pages_failed INTEGER NOT NULL,
    quotes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS run_sources (
    run_id TEXT NOT NULL,
    pos INTEGER NOT NULL,
    sid TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    domain TEXT NOT NULL,
    date TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    quote_count INTEGER NOT NULL,
    via TEXT NOT NULL,
    PRIMARY KEY (run_id, sid)
);
CREATE TABLE IF NOT EXISTS run_quotes (
    run_id TEXT NOT NULL,
    pos INTEGER NOT NULL,
    qid TEXT NOT NULL,
    text TEXT NOT NULL,
    source_id TEXT NOT NULL,
    score REAL NOT NULL,
    terms_json TEXT NOT NULL,
    PRIMARY KEY (run_id, qid)
);
CREATE TABLE IF NOT EXISTS run_themes (
    run_id TEXT NOT NULL,
    pos INTEGER NOT NULL,
    term TEXT NOT NULL,
    count INTEGER NOT NULL,
    quotes_json TEXT NOT NULL,
    PRIMARY KEY (run_id, pos)
);
CREATE TABLE IF NOT EXISTS run_failures (
    run_id TEXT NOT NULL,
    pos INTEGER NOT NULL,
    url TEXT NOT NULL,
    reason TEXT NOT NULL,
    stage TEXT NOT NULL,
    PRIMARY KEY (run_id, pos)
);
CREATE TABLE IF NOT EXISTS run_hits (
    run_id TEXT NOT NULL,
    pos INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    date TEXT NOT NULL,
    kind TEXT NOT NULL,
    via TEXT NOT NULL,
    selected INTEGER NOT NULL,
    PRIMARY KEY (run_id, pos)
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    at TEXT NOT NULL,
    stage TEXT NOT NULL,
    method TEXT NOT NULL,
    url TEXT NOT NULL,
    status INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    elapsed REAL NOT NULL,
    note TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS requests_run ON requests(run_id, id);
CREATE INDEX IF NOT EXISTS runs_started ON runs(started_at DESC);
"""


def state_dir() -> Path:
    """Directory for the database and exports.

    RECEIPTS_HOME wins, then XDG_STATE_HOME, then ~/.local/state/receipts.
    Tests point RECEIPTS_HOME at a tmp dir.
    """
    override = os.environ.get("RECEIPTS_HOME")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "state"
    return base / "receipts"


def default_db_path() -> Path:
    return state_dir() / "receipts.db"


class Store:
    """One connection, guarded by a lock.

    Requests are recorded from fetch worker threads, so the connection is opened
    with check_same_thread=False and every write takes the lock.
    """

    def __init__(self, path: str | Path | None = None):
        if path is not None and str(path) == ":memory:":
            self.path = Path(":memory:")
            target = ":memory:"
        else:
            self.path = Path(path) if path is not None else default_db_path()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            target = str(self.path)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(target, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        with self._lock:
            self._con.executescript(SCHEMA)
            self._con.commit()

    def close(self) -> None:
        with self._lock:
            self._con.close()

    # ------------------------------------------------------------------ runs
    def next_run_id(self, when: str | None = None) -> str:
        """Timestamp id with a numeric suffix on collision. No randomness."""
        stamp = (when or now_iso()).replace("-", "").replace(":", "").replace("T", "-")
        # 20261121-153012Z -> r-20261121-153012
        base = "r-" + stamp.replace("Z", "")[:15]
        with self._lock:
            candidate, n = base, 1
            while self._con.execute("SELECT 1 FROM runs WHERE id=?", (candidate,)).fetchone():
                n += 1
                candidate = f"{base}-{n}"
            return candidate

    def has_run(self, run_id: str) -> bool:
        with self._lock:
            return self._con.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone() is not None

    def save_board(self, board: dict) -> None:
        """Replace the stored copy of one board, atomically."""
        coverage = board["coverage"]
        with self._lock, self._con:
            self._con.execute("DELETE FROM runs WHERE id=?", (board["id"],))
            self._con.execute("DELETE FROM run_sources WHERE run_id=?", (board["id"],))
            self._con.execute("DELETE FROM run_quotes WHERE run_id=?", (board["id"],))
            self._con.execute("DELETE FROM run_themes WHERE run_id=?", (board["id"],))
            self._con.execute("DELETE FROM run_failures WHERE run_id=?", (board["id"],))
            self._con.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    board["id"], board["question"], board["started_at"],
                    board["finished_at"], float(board["seconds"]),
                    int(coverage["queries"]), int(coverage["hits"]),
                    int(coverage["pages_ok"]), int(coverage["pages_failed"]),
                    int(coverage["quotes"]),
                ),
            )
            for pos, source in enumerate(board["sources"]):
                self._con.execute(
                    "INSERT INTO run_sources VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        board["id"], pos, source["id"], source["url"],
                        source["title"], source["domain"], source["date"],
                        source["kind"], source["status"], int(source["quotes"]),
                        source["via"],
                    ),
                )
            for pos, quote in enumerate(board["quotes"]):
                self._con.execute(
                    "INSERT INTO run_quotes VALUES (?,?,?,?,?,?,?)",
                    (
                        board["id"], pos, quote["id"], quote["text"],
                        quote["source_id"], float(quote["score"]),
                        json.dumps(list(quote["terms"]), ensure_ascii=False),
                    ),
                )
            for pos, theme in enumerate(board["themes"]):
                self._con.execute(
                    "INSERT INTO run_themes VALUES (?,?,?,?,?)",
                    (
                        board["id"], pos, theme["term"], int(theme["count"]),
                        json.dumps(list(theme["quotes"]), ensure_ascii=False),
                    ),
                )
            for pos, failure in enumerate(board["failures"]):
                self._con.execute(
                    "INSERT INTO run_failures VALUES (?,?,?,?,?)",
                    (
                        board["id"], pos, failure["url"],
                        failure["reason"], failure.get("stage", "fetch"),
                    ),
                )

    def load_board(self, run_id: str) -> dict | None:
        with self._lock:
            run = self._con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                return None
            sources = self._con.execute(
                "SELECT * FROM run_sources WHERE run_id=? ORDER BY pos", (run_id,)
            ).fetchall()
            quotes = self._con.execute(
                "SELECT * FROM run_quotes WHERE run_id=? ORDER BY pos", (run_id,)
            ).fetchall()
            themes = self._con.execute(
                "SELECT * FROM run_themes WHERE run_id=? ORDER BY pos", (run_id,)
            ).fetchall()
            failures = self._con.execute(
                "SELECT * FROM run_failures WHERE run_id=? ORDER BY pos", (run_id,)
            ).fetchall()
        return {
            "id": run["id"],
            "question": run["question"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "seconds": run["seconds"],
            "coverage": {
                "queries": run["queries"],
                "hits": run["hits"],
                "pages_ok": run["pages_ok"],
                "pages_failed": run["pages_failed"],
                "quotes": run["quotes"],
            },
            "sources": [
                {
                    "id": s["sid"],
                    "url": s["url"],
                    "title": s["title"],
                    "domain": s["domain"],
                    "date": s["date"],
                    "kind": s["kind"],
                    "status": s["status"],
                    "quotes": s["quote_count"],
                    "via": s["via"],
                }
                for s in sources
            ],
            "quotes": [
                {
                    "id": q["qid"],
                    "text": q["text"],
                    "source_id": q["source_id"],
                    "score": q["score"],
                    "terms": json.loads(q["terms_json"]),
                }
                for q in quotes
            ],
            "themes": [
                {"term": t["term"], "count": t["count"], "quotes": json.loads(t["quotes_json"])}
                for t in themes
            ],
            "failures": [
                {"url": f["url"], "reason": f["reason"], "stage": f["stage"]} for f in failures
            ],
        }

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._con.execute(
                "SELECT id, question, started_at, seconds, quotes, pages_ok "
                "FROM runs ORDER BY started_at DESC, id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "question": r["question"],
                "started_at": r["started_at"],
                "seconds": r["seconds"],
                "quotes": r["quotes"],
                "pages_ok": r["pages_ok"],
            }
            for r in rows
        ]

    def save_hits(self, run_id: str, hits: list, selected_urls=()) -> None:
        """Every deduped search hit, with whether it was chosen for fetching."""
        selected = set(selected_urls or ())
        with self._lock, self._con:
            self._con.execute("DELETE FROM run_hits WHERE run_id=?", (run_id,))
            for pos, hit in enumerate(hits):
                self._con.execute(
                    "INSERT INTO run_hits VALUES (?,?,?,?,?,?,?,?)",
                    (
                        run_id, pos, hit.url, hit.title, hit.date, hit.kind, hit.via,
                        int(hit.url in selected),
                    ),
                )

    def hit_count(self, run_id: str) -> int:
        with self._lock:
            row = self._con.execute(
                "SELECT COUNT(*) AS n FROM run_hits WHERE run_id=?", (run_id,)
            ).fetchone()
            return int(row["n"])

    def record_request(
        self,
        run_id: str,
        stage: str,
        method: str,
        url: str,
        status: int,
        ok: bool,
        elapsed: float,
        note: str = "",
    ) -> None:
        with self._lock, self._con:
            self._con.execute(
                "INSERT INTO requests (run_id, at, stage, method, url, status, ok, elapsed, note) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, now_iso(), stage, method, url, int(status), int(bool(ok)),
                 round(float(elapsed), 3), note[:500]),
            )

    def request_count(self, run_id: str) -> int:
        with self._lock:
            row = self._con.execute(
                "SELECT COUNT(*) AS n FROM requests WHERE run_id=?", (run_id,)
            ).fetchone()
            return int(row["n"])


def exports_dir() -> Path:
    path = state_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path
