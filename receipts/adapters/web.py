"""Web search through Bing's HTML, with Mojeek as the fallback."""

from __future__ import annotations

import base64
import html as html_module
import re
from urllib.parse import urlencode

from ..extract import clean_text, find_all, node_text, parse_dom
from ..text import search_phrase
from ..models import Hit
from .base import Adapter, FetchError


BING_REDIRECT = re.compile(r"[?&]u=a1([A-Za-z0-9_\-=]+)")


def resolve_bing_url(href: str) -> str:
    """Bing's HTML wraps organic links in /ck/a?...&u=a1<base64url>.

    Returns the destination for a wrapped link, the input unchanged for a plain
    one, and an empty string for a link that only points back into Bing.
    """
    href = html_module.unescape(href or "").strip()
    if not href:
        return ""
    match = BING_REDIRECT.search(href)
    if match:
        payload = match.group(1)
        payload += "=" * (-len(payload) % 4)
        try:
            target = base64.urlsafe_b64decode(payload).decode("utf-8", "replace")
        except (ValueError, base64.binascii.Error):
            target = ""
        if target.startswith(("http://", "https://")):
            href = target
        elif target.startswith("/"):
            return ""
    if "bing.com/ck/a" in href or href.startswith(("https://www.bing.com/", "https://bing.com/")):
        return ""
    return href


def parse_bing(html: str) -> list[dict]:
    """Extract organic results from li.b_algo. Nav and ads are ignored."""
    root = parse_dom(html)
    out: list[dict] = []
    for li in find_all(root, "li"):
        classes = li.attr("class").split()
        if "b_algo" not in classes:
            continue
        anchor = None
        for h2 in find_all(li, "h2"):
            for a in find_all(h2, "a"):
                if a.attr("href"):
                    anchor = a
                    break
            if anchor:
                break
        if anchor is None:
            for a in find_all(li, "a"):
                if a.attr("href"):
                    anchor = a
                    break
        if anchor is None:
            continue
        href = resolve_bing_url(anchor.attr("href").strip())
        if not href.startswith(("http://", "https://")):
            continue
        title = clean_text(node_text(anchor))
        snippet = ""
        for p in find_all(li, "p"):
            text = clean_text(node_text(p))
            if text:
                snippet = text
                break
        if not snippet:
            for node in find_all(li, "div"):
                if "b_caption" in node.attr("class"):
                    text = clean_text(node_text(node))
                    if text:
                        snippet = text
                        break
        if title:
            out.append({"url": href, "title": title, "snippet": snippet})
    return out


def parse_mojeek(html: str) -> list[dict]:
    """Mojeek keeps results in ul.results-standard; the markup is simple."""
    root = parse_dom(html)
    out: list[dict] = []
    for li in find_all(root, "li"):
        h2 = None
        for node in find_all(li, "h2"):
            h2 = node
            break
        if h2 is None:
            continue
        anchor = None
        for a in find_all(h2, "a"):
            if a.attr("href").startswith(("http://", "https://")):
                anchor = a
                break
        if anchor is None:
            continue
        snippet = ""
        for p in find_all(li, "p"):
            text = clean_text(node_text(p))
            if text:
                snippet = text
                break
        out.append({
            "url": anchor.attr("href").strip(),
            "title": clean_text(node_text(anchor)),
            "snippet": snippet,
        })
    return out


class WebAdapter(Adapter):
    kind = "web"
    name = "web"

    def search(self, query: str) -> list[Hit]:
        phrase = search_phrase(query)
        bing_url = "https://www.bing.com/search?" + urlencode({
            "q": phrase, "count": "20", "setlang": "en-GB", "cc": "GB",
        })
        bing_error = None
        try:
            response = self.http.get(bing_url, stage="search")
            rows = parse_bing(response.text)
            if rows:
                return self._hits(rows, query)
            bing_error = "no results in Bing HTML"
        except FetchError as exc:
            bing_error = exc.reason
        mojeek_url = "https://www.mojeek.com/search?" + urlencode({"q": phrase})
        try:
            response = self.http.get(mojeek_url, stage="search")
            rows = parse_mojeek(response.text)
            if rows:
                return self._hits(rows, query)
        except FetchError as exc:
            if bing_error:
                self.failures.append((bing_url, bing_error))
            self.failures.append((mojeek_url, exc.reason))
            raise
        if bing_error:
            self.failures.append((bing_url, bing_error))
        return []

    @staticmethod
    def _hits(rows: list[dict], query: str) -> list[Hit]:
        return [
            Hit(
                url=row["url"],
                title=row["title"],
                snippet=row["snippet"],
                kind="web",
                via=query,
                rank=i,
            )
            for i, row in enumerate(rows)
            if row.get("url") and row.get("title")
        ]
