from __future__ import annotations

from dataclasses import replace
import json

from receipts.adapters.base import FetchError
from receipts.models import Hit, Page
from receipts.pipeline import run_research
from receipts.quotes import quote_is_verbatim

TEXT_A = (
    "The context window is the working memory an agent carries between steps, and "
    "every failed attempt left in the prompt crowds out the files that matter. "
    "A smaller working set keeps the task, the current diff and the last error, while "
    "dropping transcripts that no longer affect the next action."
)
TEXT_B = (
    "Researchers measured coding agents with a fixed context window and found that "
    "pruning old tool output cut token spend by half without losing successful patches. "
    "The lesson is that context is a budget, not a bucket, and the agent should spend it "
    "on the current task rather than on its own history."
)


def make_fake(kind, hits, pages, fail_search=False, fail_fetch=False,
              fetch_calls=None, search_calls=None):
    class Fake:
        kind = ""

        def __init__(self, http):
            self.http = http
            self.failures = []

        def search(self, query):
            if search_calls is not None:
                search_calls.append((kind, query))
            if fail_search:
                raise FetchError(403, "403", f"https://{kind}.test/search")
            return [replace(hit, kind=kind) for hit in hits]

        def fetch(self, url):
            if fetch_calls is not None:
                fetch_calls.append(url)
            if fail_fetch:
                raise FetchError(403, "403", url)
            page = pages.get(url)
            if page is None:
                raise FetchError(404, "404", url)
            return replace(page)

    Fake.kind = kind
    return Fake


def page(url, text, title="A page", date="2026-11-04", links=None):
    return Page(url=url, title=title, text=text, date=date, status="ok",
                links=list(links or []), domain="")


def registry_for(web_hits=(), web_pages=None, wiki_hits=(), wiki_pages=None, **kwargs):
    registry = {}
    if web_hits is not None:
        registry["web"] = make_fake(
            "web", list(web_hits), web_pages or {},
            fetch_calls=kwargs.get("fetch_calls"), search_calls=kwargs.get("search_calls"),
            fail_search=kwargs.get("web_fail_search", False),
            fail_fetch=kwargs.get("web_fail_fetch", False),
        )
    if wiki_hits is not None:
        registry["wiki"] = make_fake(
            "wiki", list(wiki_hits), wiki_pages or {},
            fetch_calls=kwargs.get("fetch_calls"), search_calls=kwargs.get("search_calls"),
            fail_search=kwargs.get("wiki_fail_search", False),
            fail_fetch=kwargs.get("wiki_fail_fetch", False),
        )
    return registry


def stable(board: dict) -> dict:
    copy = json.loads(json.dumps(board))
    for key in ("id", "started_at", "finished_at", "seconds"):
        copy.pop(key, None)
    return copy


def test_board_shape_and_verbatim(store):
    url_a = "https://a.example/one"
    hit_a = Hit(url=url_a, title="A", date="2026-11-04", kind="web")
    registry = registry_for(
        web_hits=[hit_a], web_pages={url_a: page(url_a, TEXT_A)},
        wiki_hits=None,
    )
    board = run_research(
        "why do AI coding agents waste context window",
        sources=["web"], depth=2, max_pages=4, store=store, registry=registry,
    )
    assert list(board) == [
        "id", "question", "started_at", "finished_at", "seconds", "coverage",
        "sources", "quotes", "themes", "failures",
    ]
    assert board["coverage"] == {"queries": 3, "hits": 1, "pages_ok": 1,
                                 "pages_failed": 0, "quotes": len(board["quotes"])}
    assert board["sources"][0]["id"] == "s1"
    assert board["sources"][0]["status"] == "ok"
    assert [quote["id"] for quote in board["quotes"]] == [
        f"q{i + 1}" for i in range(len(board["quotes"]))
    ]
    assert board["quotes"]
    for quote in board["quotes"]:
        assert quote_is_verbatim(quote["text"], TEXT_A)
    for theme in board["themes"]:
        assert set(theme["quotes"]) <= {quote["id"] for quote in board["quotes"]}


def test_same_inputs_same_board(store):
    url_a = "https://a.example/one"
    def build():
        hit = Hit(url=url_a, title="A", date="2026-11-04", kind="web")
        registry = registry_for(web_hits=[hit], web_pages={url_a: page(url_a, TEXT_A)},
                                wiki_hits=None)
        return run_research("why do AI coding agents waste context window",
                            sources=["web"], depth=1, max_pages=4,
                            store=store, registry=registry)

    first = build()
    second = build()
    assert stable(first) == stable(second)
    assert first["id"] != second["id"]


def test_dates_sort_quotes_desc(store):
    url_a = "https://a.example/one"
    url_b = "https://b.example/two"
    registry = registry_for(
        web_hits=[Hit(url=url_b, title="B", date="2026-11-02", kind="web")],
        web_pages={url_b: page(url_b, TEXT_B, date="2026-11-02")},
        wiki_hits=[Hit(url=url_a, title="A", date="2026-11-04", kind="wiki")],
        wiki_pages={url_a: page(url_a, TEXT_A, date="2026-11-04")},
    )
    board = run_research("context window coding agents", sources=["web", "wiki"],
                         depth=1, store=store, registry=registry)
    dates = []
    by_id = {source["id"]: source for source in board["sources"]}
    for quote in board["quotes"]:
        dates.append(by_id[quote["source_id"]]["date"])
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == "2026-11-04"


def test_failure_is_listed_not_raised(store):
    url_b = "https://b.example/two"
    registry = registry_for(
        web_hits=[],
        wiki_hits=[Hit(url=url_b, title="B", date="2026-11-02", kind="wiki")],
        wiki_pages={url_b: page(url_b, TEXT_B, date="2026-11-02")},
        wiki_fail_search=False,
        web_fail_search=True,
    )
    board = run_research("context window coding agents", sources=["web", "wiki"],
                         depth=1, store=store, registry=registry)
    assert board["coverage"]["quotes"] > 0
    assert any(failure["stage"] == "search" for failure in board["failures"])
    assert any(failure["reason"] == "403" for failure in board["failures"])
    assert all(source["kind"] != "web" for source in board["sources"])


def test_every_source_failed_returns_a_board(store):
    registry = registry_for(
        web_hits=[], wiki_hits=[],
        web_fail_search=True, wiki_fail_search=True,
    )
    board = run_research("context window", sources=["web", "wiki"], depth=1,
                         store=store, registry=registry)
    assert board["coverage"]["pages_ok"] == 0
    assert board["coverage"]["quotes"] == 0
    assert board["sources"] == []
    assert len(board["failures"]) >= 2
    assert board["themes"] == []


def test_max_pages_caps_fetches(store):
    hits = [Hit(url=f"https://a.example/{i}", title=f"A{i}", date="2026-11-04", kind="web")
            for i in range(5)]
    pages = {hit.url: page(hit.url, TEXT_A) for hit in hits}
    calls = []
    registry = registry_for(web_hits=hits, web_pages=pages, wiki_hits=None,
                            fetch_calls=calls)
    board = run_research("context window", sources=["web"], depth=1, max_pages=2,
                         store=store, registry=registry)
    assert len(calls) == 2
    assert board["coverage"]["pages_ok"] == 2


def test_depth_two_runs_three_variants(store):
    calls = []
    registry = registry_for(web_hits=[], wiki_hits=[], search_calls=calls)
    run_research("why do AI coding agents waste context window",
                 sources=["web", "wiki"], depth=2, store=store, registry=registry)
    assert len(calls) == 6
    assert len({query for _kind, query in calls}) == 3


def test_depth_three_follows_two_same_domain_links(store):
    url = "https://a.example/one"
    extra = "https://a.example/two"
    calls = []
    registry = registry_for(
        web_hits=[Hit(url=url, title="A", date="2026-11-04", kind="web")],
        web_pages={
            url: page(url, TEXT_A, links=[extra]),
            extra: page(extra, TEXT_B, date="2026-11-03"),
        },
        wiki_hits=None, fetch_calls=calls,
    )
    board = run_research("context window coding agents", sources=["web"], depth=3,
                         max_pages=1, store=store, registry=registry)
    assert calls == [url, extra]
    assert board["coverage"]["pages_ok"] == 2
    assert any(source["url"] == extra for source in board["sources"])
    assert any(source["via"].startswith("linked from") for source in board["sources"])


def test_depth_three_ignores_cross_domain_links(store):
    url = "https://a.example/one"
    extra = "https://other.example/two"
    calls = []
    registry = registry_for(
        web_hits=[Hit(url=url, title="A", date="2026-11-04", kind="web")],
        web_pages={url: page(url, TEXT_A, links=[extra])},
        wiki_hits=None, fetch_calls=calls,
    )
    board = run_research("context window", sources=["web"], depth=3, max_pages=1,
                         store=store, registry=registry)
    assert calls == [url]
    assert board["coverage"]["pages_ok"] == 1


def test_duplicate_quote_across_sources_is_kept_once(store):
    url_a = "https://a.example/one"
    url_b = "https://b.example/two"
    registry = registry_for(
        web_hits=[Hit(url=url_a, title="A", date="2026-11-04", kind="web")],
        web_pages={url_a: page(url_a, TEXT_A)},
        wiki_hits=[Hit(url=url_b, title="B", date="2026-11-04", kind="wiki")],
        wiki_pages={url_b: page(url_b, TEXT_A)},
    )
    board = run_research("context window coding agents", sources=["web", "wiki"],
                         depth=1, store=store, registry=registry)
    texts = [quote["text"] for quote in board["quotes"]]
    assert len(texts) == len(set(texts))
    assert sum(source["quotes"] for source in board["sources"]) == len(texts)


def test_board_round_trips_through_store(store):
    url = "https://a.example/one"
    registry = registry_for(
        web_hits=[Hit(url=url, title="A", date="2026-11-04", kind="web")],
        web_pages={url: page(url, TEXT_A)}, wiki_hits=None,
    )
    board = run_research("context window", sources=["web"], depth=1,
                         store=store, registry=registry)
    assert store.load_board(board["id"]) == board
