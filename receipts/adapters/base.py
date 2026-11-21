"""HTTP and shared adapter plumbing.

One request per URL, a normal browser user agent, a hard byte cap, a 10 second
timeout and 1 request per second per host. Every attempt is recorded, including
the failures, because a block is not an absence.
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import re
import socket
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ..extract import extract_page
from ..models import Page, date_only
from ..store import Store

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 1_500_000
DEFAULT_REQUEST_CAP = 120

TRACKING = re.compile(
    r"^(utm_.*|gclid|fbclid|mc_cid|mc_eid|igshid|ref_src|ref_url|oc|cmpid|CMP)$"
)


class FetchError(Exception):
    """A request that did not produce a usable body. Carries a short reason."""

    def __init__(self, status: int, reason: str, url: str = ""):
        super().__init__(reason)
        self.status = int(status)
        self.reason = reason
        self.url = url

    @property
    def blocked(self) -> bool:
        return self.status in {401, 403, 418, 429, 451}


@dataclass
class Response:
    url: str
    status: int
    text: str
    elapsed: float
    note: str = ""


class Budget:
    """Total request cap shared by every adapter in one run."""

    def __init__(self, limit: int = DEFAULT_REQUEST_CAP):
        self.limit = int(limit)
        self.used = 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class RateLimiter:
    """Per-host spacing. The sleep happens outside the lock."""

    def __init__(self, interval: float = 1.0, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}

    def wait(self, host: str) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            now = self.clock()
            when = max(now, self._next.get(host, 0.0))
            self._next[host] = when + self.interval
            delay = when - now
        if delay > 0:
            self.sleep(delay)


def normalise_url(url: str) -> str:
    """Canonical form used for dedupe: no tracking params, fragment or trailing slash."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    if (scheme == "http" and host.endswith(":80")) or (scheme == "https" and host.endswith(":443")):
        host = host.rsplit(":", 1)[0]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not TRACKING.match(k)]
    pairs.sort()
    return urlunsplit((scheme, host, path, urlencode(pairs), ""))


def domain_of(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def title_similar(a: str, b: str) -> bool:
    from difflib import SequenceMatcher

    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() > 0.92


def _decode(body: bytes, header_charset: str | None) -> str:
    charset = (header_charset or "").strip().lower()
    if not charset:
        head = body[:2048].decode("ascii", "ignore")
        match = re.search(r'charset=["\']?([a-zA-Z0-9_-]+)', head)
        charset = match.group(1).lower() if match else "utf-8"
    if charset in {"iso-8859-1", "latin-1", "latin1", "cp1252"} and not header_charset:
        # Servers lie about latin-1; utf-8 is far more likely in practice.
        charset = "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _error_reason(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return str(exc.code)
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout"
        if isinstance(reason, socket.gaierror):
            return "dns"
        return "connection"
    return "error"


class HttpClient:
    def __init__(
        self,
        store: Store | None = None,
        run_id: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        budget: Budget | None = None,
        limiter: RateLimiter | None = None,
    ):
        self.store = store
        self.run_id = run_id
        self.timeout = float(timeout)
        self.max_bytes = int(max_bytes)
        self.budget = budget or Budget()
        self.limiter = limiter or RateLimiter(1.0)
        self._lock = threading.Lock()
        self.calls = 0

    def _record(self, stage: str, url: str, status: int, ok: bool,
                elapsed: float, note: str = "") -> None:
        with self._lock:
            self.calls += 1
        if self.store is not None:
            self.store.record_request(self.run_id, stage, "GET", url, status, ok,
                                      elapsed, note)

    def get(self, url: str, stage: str = "fetch", accept: str = "",
            headers: dict[str, str] | None = None) -> Response:
        if not self.budget.take():
            raise FetchError(0, f"request cap {self.budget.limit} reached", url)
        host = urlsplit(url).netloc
        self.limiter.wait(host)
        request_headers = {
            "User-Agent": USER_AGENT,
            "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept-Encoding": "gzip",
            "Connection": "close",
        }
        if headers:
            request_headers.update(headers)
        started = time.monotonic()
        try:
            request = Request(url, headers=request_headers)
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(self.max_bytes + 1)
                elapsed = time.monotonic() - started
                final_url = response.geturl() or url
                note = ""
                if len(raw) > self.max_bytes:
                    raw = raw[: self.max_bytes]
                    note = f"truncated at {self.max_bytes} bytes"
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    try:
                        raw = gzip.decompress(raw)
                    except OSError:
                        note = (note + "; " if note else "") + "gzip decode failed"
                text = _decode(raw, response.headers.get_content_charset())
                status = int(getattr(response, "status", 200) or 200)
                self._record(stage, final_url, status, True, elapsed, note)
                return Response(final_url, status, text, round(elapsed, 3), note)
        except HTTPError as exc:
            elapsed = time.monotonic() - started
            reason = str(exc.code)
            self._record(stage, url, int(exc.code), False, elapsed, reason)
            raise FetchError(int(exc.code), reason, url) from None
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            elapsed = time.monotonic() - started
            reason = _error_reason(exc)
            self._record(stage, url, 0, False, elapsed, reason)
            raise FetchError(0, reason, url) from None


class Adapter:
    """Base adapter: subclasses provide search(), usually inherit fetch()."""

    kind = ""
    name = ""

    def __init__(self, http: HttpClient):
        self.http = http
        # Non-fatal failures (a partial fan-out, a search fallback that also
        # failed) are collected here for the board's failure list.
        self.failures: list[tuple[str, str]] = []

    def search(self, query: str) -> list:
        raise NotImplementedError

    def fetch(self, url: str) -> Page:
        response = self.http.get(url, stage="fetch")
        document = extract_page(response.text, response.url)
        status = document.status
        reason = ""
        if status == "empty":
            reason = "no extractable text"
        elif status == "thin":
            reason = "only title or description found"
        return Page(
            url=url,
            title=document.title,
            text=document.text,
            date=date_only(document.date),
            kind=self.kind,
            status=status,
            reason=reason,
            links=document.links,
            domain=domain_of(url),
        )
