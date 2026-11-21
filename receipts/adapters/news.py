"""News through Google News RSS, with Bing News RSS as the fetchable fallback.

Google News item links are JavaScript redirects: the server HTML contains no
article body, so they cannot be fetched or quoted. When every discovered link is
one of those redirects, the adapter asks Bing News RSS instead, whose item links
carry the publisher URL in a `url` parameter.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from ..extract import strip_tags
from ..models import Hit, date_only
from .base import Adapter, FetchError


def _child_text(item: ET.Element, name: str) -> str:
    for child in item:
        tag = child.tag.split("}")[-1]
        if tag == name:
            return (child.text or "").strip()
    return ""


def parse_gnews(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[dict] = []
    for item in root.iter("item"):
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        if not title or not link:
            continue
        source = ""
        for child in item:
            if child.tag.split("}")[-1] == "source":
                source = (child.text or "").strip()
                break
        out.append({
            "url": link,
            "title": title,
            "source": source,
            "date": date_only(_child_text(item, "pubDate")),
        })
    return out


def _resolve_bing_link(link: str) -> str:
    """Bing News wraps the publisher URL in an apiclick redirect."""
    try:
        parts = urlsplit(link)
    except ValueError:
        return link
    if "bing.com" not in parts.netloc or "apiclick" not in parts.path:
        return link
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "url" and value.startswith(("http://", "https://")):
            return unquote(value)
    return link


def parse_bing_news(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[dict] = []
    for item in root.iter("item"):
        title = _child_text(item, "title")
        link = _resolve_bing_link(_child_text(item, "link"))
        if not title or not link:
            continue
        out.append({
            "url": link,
            "title": title,
            "source": _child_text(item, "Source"),
            "date": date_only(_child_text(item, "pubDate")),
        })
    return out


class NewsAdapter(Adapter):
    kind = "news"
    name = "news"

    def search(self, query: str) -> list[Hit]:
        gnews_url = "https://news.google.com/rss/search?" + urlencode({
            "q": query, "hl": "en-GB", "gl": "GB", "ceid": "GB:en",
        })
        rows: list[dict] = []
        gnews_error = None
        try:
            response = self.http.get(gnews_url, stage="search")
            rows = parse_gnews(response.text)
        except FetchError as exc:
            gnews_error = exc.reason

        fetchable = [row for row in rows if "news.google.com" not in urljoin_host(row["url"])]
        if not fetchable:
            bing_url = "https://www.bing.com/news/search?" + urlencode({
                "q": query, "format": "RSS", "setlang": "en-GB", "cc": "GB",
            })
            bing_error = None
            try:
                response = self.http.get(bing_url, stage="search")
                fallback = parse_bing_news(response.text)
                if fallback:
                    return self._hits(fallback, query)
            except FetchError as exc:
                bing_error = exc.reason
            if gnews_error:
                self.failures.append((gnews_url, gnews_error))
            if bing_error:
                self.failures.append((bing_url, bing_error))
        return self._hits(fetchable or rows, query)

    def fetch(self, url: str):
        if "news.google.com" in urljoin_host(url):
            raise FetchError(0, "google news redirect has no article body", url)
        resolved = _resolve_bing_link(url)
        return super().fetch(resolved)

    @staticmethod
    def _hits(rows: list[dict], query: str) -> list[Hit]:
        hits: list[Hit] = []
        for i, row in enumerate(rows):
            url = row.get("url", "")
            if not url or not row.get("title"):
                continue
            hits.append(Hit(
                url=url,
                title=row["title"],
                snippet=strip_tags(row.get("source", "")),
                date=date_only(row.get("date", "")),
                kind="news",
                via=query,
                rank=i,
            ))
        return hits


def urljoin_host(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower()
    except ValueError:
        return ""
