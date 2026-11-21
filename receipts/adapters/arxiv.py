"""arXiv search through the public Atom API."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlencode

from ..extract import clean_text
from ..models import Hit, date_only
from .base import Adapter, FetchError

ATOM = "{http://www.w3.org/2005/Atom}"


def parse_arxiv(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[dict] = []
    for entry in root.findall(f"{ATOM}entry"):
        title = clean_text(entry.findtext(f"{ATOM}title") or "")
        identifier = (entry.findtext(f"{ATOM}id") or "").strip()
        summary = clean_text(entry.findtext(f"{ATOM}summary") or "")
        published = date_only(entry.findtext(f"{ATOM}published") or "")
        if not title or not identifier:
            continue
        out.append({
            "url": identifier,
            "title": title,
            "snippet": summary[:300],
            "date": published,
        })
    return out


class ArxivAdapter(Adapter):
    kind = "arxiv"
    name = "arxiv"

    def search(self, query: str) -> list[Hit]:
        # The documented API endpoint is plain http and redirects to https.
        base = "http://export.arxiv.org/api/query?"
        url = base + urlencode({"search_query": f"all:{query}", "max_results": "10"})
        try:
            response = self.http.get(url, stage="search", accept="application/atom+xml")
        except FetchError:
            raise
        rows = parse_arxiv(response.text)
        return [
            Hit(
                url=row["url"],
                title=row["title"],
                snippet=row["snippet"],
                date=row["date"],
                kind="arxiv",
                via=query,
                rank=i,
            )
            for i, row in enumerate(rows)
        ]
