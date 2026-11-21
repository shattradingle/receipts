"""Adapter registry. Importing this module makes no network request."""

from __future__ import annotations

from .arxiv import ArxivAdapter
from .base import Adapter, HttpClient
from .hn import HNAdapter
from .news import NewsAdapter
from .reddit import RedditAdapter
from .web import WebAdapter
from .wiki import WikiAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "web": WebAdapter,
    "news": NewsAdapter,
    "hn": HNAdapter,
    "wiki": WikiAdapter,
    "arxiv": ArxivAdapter,
    "reddit": RedditAdapter,
}

DEFAULT_SOURCES = ("web", "news", "hn", "wiki", "arxiv", "reddit")


def build_adapters(http: HttpClient, names: list[str] | tuple[str, ...] | None = None,
                   adapters: dict[str, type[Adapter]] | None = None) -> dict[str, Adapter]:
    registry = adapters or ADAPTERS
    chosen = list(names or DEFAULT_SOURCES)
    unknown = [name for name in chosen if name not in registry]
    if unknown:
        raise ValueError(f"unknown source(s): {', '.join(unknown)}")
    return {name: registry[name](http) for name in chosen}
