"""The pipeline: expand, search, dedupe, fetch, extract, quote, theme, record.

Every stage is deterministic given the same fetched inputs. Network results
obviously vary with the web; identical page text produces an identical board.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import time
from urllib.parse import urlsplit

from .adapters import build_adapters
from .adapters.base import (
    Adapter, Budget, FetchError, HttpClient, domain_of, normalise_url, title_similar,
)
from .models import DEFAULT_SOURCES, Hit, Page, date_only, now_iso
from .quotes import quote_candidates, quote_is_verbatim
from .store import Store
from .text import content_terms, normalise_quote
from .themes import cluster_themes

FAILURE_ORDER = {"search": 0, "fetch": 1, "extract": 2, "budget": 3}


def expand_queries(question: str, depth: int = 1) -> list[str]:
    """One variant at depth 1; phrase, every content term and a key phrase at 2+."""
    cleaned = " ".join((question or "").split())
    if not cleaned:
        raise ValueError("question is empty")
    if depth <= 1:
        return [cleaned]
    terms = content_terms(cleaned)
    raw = [cleaned, f'"{cleaned}"']
    if terms:
        raw.extend([" ".join(terms), " ".join(terms[:3])])
    out: list[str] = []
    seen: set[str] = set()
    for variant in raw:
        key = variant.casefold().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(variant)
    # depth 2 means three variants: keep the phrase and the two derived forms.
    if len(out) > 3:
        out = [out[1]] + out[2:4]
    return out[:3]


def dedupe_hits(hits: list[Hit]) -> list[Hit]:
    """URL first, then near-identical titles. First hit wins."""
    kept: list[Hit] = []
    seen_urls: set[str] = set()
    for hit in hits:
        if urlsplit(hit.url).scheme not in {"http", "https"}:
            continue
        key = normalise_url(hit.url)
        if key in seen_urls:
            continue
        if hit.title and any(title_similar(hit.title, other.title) for other in kept):
            continue
        seen_urls.add(key)
        kept.append(hit)
    return kept


def _relevance(hit: Hit, terms: list[str]) -> int:
    """Count question terms in the title and snippet; the title counts double."""
    title = hit.title.lower()
    text = (title + " " + hit.snippet.lower())
    title_hits = sum(1 for term in terms if term in title)
    text_hits = sum(1 for term in terms if term in text)
    return title_hits * 2 + text_hits


def select_pages(hits: list[Hit], selected: list[str], max_pages: int,
                 terms: list[str] | None = None) -> list[Hit]:
    """Round-robin across sources, most relevant hit first inside each source."""
    terms = terms or []
    groups: dict[str, list[Hit]] = {name: [] for name in selected}
    for hit in hits:
        groups.setdefault(hit.kind, []).append(hit)
    for name in groups:
        groups[name].sort(key=lambda hit: (-_relevance(hit, terms), hit.rank, hit.url))
    chosen: list[Hit] = []
    while len(chosen) < max_pages:
        added = False
        for name in selected:
            if len(chosen) >= max_pages:
                break
            if groups.get(name):
                chosen.append(groups[name].pop(0))
                added = True
        if not added:
            break
    return chosen


def _emit(progress, data: dict) -> None:
    if progress is None:
        return
    try:
        progress(data)
    except Exception:
        pass


def _add_failure(failures: list[dict], url: str, reason: str, stage: str) -> None:
    entry = {"url": url, "reason": reason, "stage": stage}
    if entry not in failures:
        failures.append(entry)


def _page_status_for(error: FetchError) -> str:
    if error.blocked:
        return "blocked"
    if error.reason == "timeout":
        return "timeout"
    return "failed"


def _sorted_failures(failures: list[dict]) -> list[dict]:
    failure = sorted(
        failures,
        key=lambda item: (FAILURE_ORDER.get(item.get("stage", ""), 9), item["url"], item["reason"]),
    )
    # The request cap is one event, not one per abandoned URL.
    capped = [item for item in failure if item["reason"].startswith("request cap")]
    if capped:
        failure = [item for item in failure if not item["reason"].startswith("request cap")]
        first = capped[0]
        failure.insert(0, {"url": "", "reason": first["reason"], "stage": "budget"})
    return failure


def _fetch_all(adapter_map: dict[str, Adapter], hits: list[Hit], workers: int = 4):
    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [(hit, pool.submit(adapter_map[hit.kind].fetch, hit.url)) for hit in hits]
        for hit, future in futures:
            try:
                results.append((hit, future.result(), None))
            except FetchError as error:
                results.append((hit, None, error))
            except Exception:
                results.append((hit, None, FetchError(0, "error", hit.url)))
    return results


def run_research(
    question: str,
    sources: list[str] | tuple[str, ...] | None = None,
    depth: int = 1,
    max_pages: int = 12,
    store: Store | None = None,
    progress=None,
    registry=None,
    http: HttpClient | None = None,
    run_id: str | None = None,
    budget: Budget | None = None,
) -> dict:
    """Run one research question and return the board dict. Raises ValueError on bad input."""
    selected = list(sources or DEFAULT_SOURCES)
    if not selected:
        raise ValueError("no sources selected")
    if depth not in (1, 2, 3):
        raise ValueError("depth must be 1, 2 or 3")
    if max_pages < 1:
        raise ValueError("max-pages must be at least 1")
    variants = expand_queries(question, depth)

    owned_store = store is None
    store = store or Store()
    run_id = run_id or store.next_run_id()
    client = http or HttpClient(store=store, run_id=run_id, budget=budget)
    adapter_map = build_adapters(client, selected, adapters=registry)

    started_at = now_iso()
    clock = time.monotonic()
    failures: list[dict] = []
    hits: list[Hit] = []
    source_entries: list[dict] = []
    query_total = len(selected) * len(variants)
    queries_done = 0

    _emit(progress, {
        "stage": "searching", "queries": 0, "queries_total": query_total,
        "hits": 0, "pages_ok": 0, "pages_failed": 0, "quotes": 0,
    })

    tasks = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for name in selected:
            for index, query in enumerate(variants):
                tasks.append((name, index, query, pool.submit(adapter_map[name].search, query)))
        for name, index, query, future in tasks:
            try:
                found = future.result() or []
            except FetchError as error:
                _add_failure(failures, error.url or name, error.reason, "search")
                found = []
            except Exception:
                _add_failure(failures, name, "error", "search")
                found = []
            for hit in found:
                if not hit.url:
                    continue
                hits.append(replace(hit, kind=name, via=variants[index]))
            queries_done += 1
            _emit(progress, {
                "stage": "searching", "queries": queries_done, "queries_total": query_total,
                "hits": len(hits), "pages_ok": 0, "pages_failed": 0, "quotes": 0,
            })

    for adapter in adapter_map.values():
        for url, reason in getattr(adapter, "failures", []) or []:
            _add_failure(failures, url, reason, "search")

    hits = dedupe_hits(hits)
    terms = content_terms(question)
    chosen = select_pages(hits, selected, max_pages, terms)
    store.save_hits(run_id, hits, {hit.url for hit in chosen})
    pages_total = len(chosen)
    _emit(progress, {
        "stage": "fetching", "queries": query_total, "queries_total": query_total,
        "hits": len(hits), "pages_ok": 0, "pages_failed": 0, "pages_total": pages_total,
        "quotes": 0,
    })

    fetched = _fetch_all(adapter_map, chosen)
    pages_ok = 0
    pages_failed = 0
    for hit, page, error in fetched:
        if error is not None:
            pages_failed += 1
            _add_failure(failures, hit.url, error.reason, "fetch")
            source_entries.append({
                "url": hit.url, "title": hit.title, "domain": domain_of(hit.url),
                "date": date_only(hit.date), "kind": hit.kind,
                "status": _page_status_for(error), "quotes": 0, "via": hit.via,
                "_page": None,
            })
            continue
        page = _normalise_page(page, hit)
        if page.status == "empty":
            pages_failed += 1
            _add_failure(failures, page.url, page.reason or "no extractable text", "extract")
        else:
            pages_ok += 1
        source_entries.append({
            "url": page.url, "title": page.title or hit.title,
            "domain": page.domain or domain_of(page.url), "date": date_only(page.date or hit.date),
            "kind": hit.kind, "status": page.status, "quotes": 0, "via": hit.via,
            "_page": page,
        })
        _emit(progress, {
            "stage": "fetching", "queries": query_total, "queries_total": query_total,
            "hits": len(hits), "pages_ok": pages_ok, "pages_failed": pages_failed,
            "pages_total": pages_total, "quotes": 0,
        })

    if depth >= 3:
        extras, pages_ok, pages_failed = _secondary_pages(
            adapter_map, source_entries, pages_ok, pages_failed, failures, client,
        )
        for entry in extras:
            source_entries.append(entry)
        pages_total += len(extras)
        _emit(progress, {
            "stage": "fetching", "queries": query_total, "queries_total": query_total,
            "hits": len(hits), "pages_ok": pages_ok, "pages_failed": pages_failed,
            "pages_total": pages_total, "quotes": 0,
        })

    # Sources are sorted newest first; then one row per URL. Ids follow that order.
    source_entries.sort(key=lambda entry: (entry["date"], entry["url"]), reverse=True)
    unique: list[dict] = []
    seen: set[str] = set()
    for entry in source_entries:
        key = normalise_url(entry["url"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    source_entries = unique
    for index, entry in enumerate(source_entries):
        entry["id"] = f"s{index + 1}"

    sid_for_url: dict[str, str] = {}
    date_for_url: dict[str, str] = {}
    for entry in source_entries:
        sid_for_url[entry["url"]] = entry["id"]
        sid_for_url[normalise_url(entry["url"])] = entry["id"]
        date_for_url[entry["url"]] = entry["date"]

    candidates = []
    for entry in source_entries:
        page = entry.get("_page")
        if not page or not page.text:
            continue
        for quote in quote_candidates(page.text, terms):
            candidate = replace(quote, source_url=page.url)
            if quote_is_verbatim(candidate.text, page.text):
                candidates.append(candidate)

    best: dict[str, object] = {}
    for quote in candidates:
        key = normalise_quote(quote.text)
        if not key:
            continue
        previous = best.get(key)
        if previous is None or quote.score > previous.score:  # type: ignore[attr-defined]
            best[key] = quote
    chosen_quotes = list(best.values())
    # A sentence that contains none of the question's content terms is board
    # noise (page furniture, site notices). Keep it only if there is little else.
    with_terms = [quote for quote in chosen_quotes if quote.terms]
    if len(with_terms) >= 5:
        chosen_quotes = with_terms
    chosen_quotes.sort(key=lambda quote: quote.source_url)
    chosen_quotes.sort(
        key=lambda quote: (date_for_url.get(quote.source_url, ""), quote.score),
        reverse=True,
    )

    quote_rows: list[dict] = []
    for index, quote in enumerate(chosen_quotes):
        sid = sid_for_url.get(quote.source_url) or sid_for_url.get(normalise_url(quote.source_url))
        if sid is None:
            continue
        quote_rows.append({
            "id": f"q{len(quote_rows) + 1}",
            "text": quote.text,
            "source_id": sid,
            "score": round(float(quote.score), 3),
            "terms": list(quote.terms),
        })

    counts: dict[str, int] = {}
    for row in quote_rows:
        counts[row["source_id"]] = counts.get(row["source_id"], 0) + 1
    for entry in source_entries:
        entry["quotes"] = counts.get(entry["id"], 0)

    themes = cluster_themes(quote_rows)

    finished_at = now_iso()
    board = {
        "id": run_id,
        "question": " ".join(question.split()),
        "started_at": started_at,
        "finished_at": finished_at,
        "seconds": round(time.monotonic() - clock, 3),
        "coverage": {
            "queries": query_total,
            "hits": len(hits),
            "pages_ok": pages_ok,
            "pages_failed": pages_failed,
            "quotes": len(quote_rows),
        },
        "sources": [
            {
                "id": entry["id"], "url": entry["url"], "title": entry["title"],
                "domain": entry["domain"], "date": entry["date"], "kind": entry["kind"],
                "status": entry["status"], "quotes": entry["quotes"], "via": entry["via"],
            }
            for entry in source_entries
        ],
        "quotes": quote_rows,
        "themes": themes,
        "failures": _sorted_failures(failures),
    }
    store.save_board(board)
    _emit(progress, {
        "stage": "done", "queries": query_total, "queries_total": query_total,
        "hits": len(hits), "pages_ok": pages_ok, "pages_failed": pages_failed,
        "pages_total": pages_total, "quotes": len(quote_rows),
    })
    if owned_store:
        store.close()
    return board


def _normalise_page(page: Page, hit: Hit) -> Page:
    page.kind = page.kind or hit.kind
    page.via = page.via or hit.via
    page.title = page.title or hit.title
    page.date = date_only(page.date or hit.date)
    page.url = page.url or hit.url
    page.domain = page.domain or domain_of(page.url)
    return page


def _secondary_pages(adapter_map, source_entries, pages_ok, pages_failed, failures, client):
    """Depth 3: follow up to two same-domain links from each of the top five pages."""
    seen = {normalise_url(entry["url"]) for entry in source_entries}
    candidates: list[tuple[str, str, str]] = []
    primary = [entry for entry in source_entries if entry.get("_page") and entry["_page"].links]
    for entry in primary[:5]:
        page = entry["_page"]
        taken = 0
        for link in page.links:
            if taken >= 2:
                break
            if domain_of(link) != page.domain:
                continue
            key = normalise_url(link)
            if key in seen:
                continue
            seen.add(key)
            candidates.append((entry["kind"], f"linked from {page.domain}", link))
            taken += 1
    extras: list[dict] = []
    if not candidates:
        return extras, pages_ok, pages_failed
    for kind, via, url in candidates[:8]:
        adapter = adapter_map.get(kind)
        page = None
        error = None
        try:
            if adapter is None:
                raise FetchError(0, "no adapter for link", url)
            page = adapter.fetch(url)
        except FetchError as exc:
            error = exc
        except Exception:
            error = FetchError(0, "error", url)
        if error is not None:
            pages_failed += 1
            _add_failure(failures, url, error.reason, "fetch")
            extras.append({
                "url": url, "title": "", "domain": domain_of(url), "date": "",
                "kind": kind, "status": _page_status_for(error), "quotes": 0,
                "via": via, "_page": None,
            })
            continue
        if page.status == "empty":
            pages_failed += 1
            _add_failure(failures, page.url, page.reason or "no extractable text", "extract")
        else:
            pages_ok += 1
        extras.append({
            "url": page.url, "title": page.title, "domain": domain_of(page.url),
            "date": date_only(page.date), "kind": kind, "status": page.status,
            "quotes": 0, "via": via, "_page": page,
        })
    return extras, pages_ok, pages_failed
