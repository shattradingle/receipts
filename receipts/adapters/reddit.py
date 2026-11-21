"""Reddit through the public arctic-shift archive.

Reddit's own search RSS returns r/all trending junk and its JSON endpoints 403
from datacenter IPs, so neither is used. arctic-shift has no global search: a
keyword query only works when it is scoped to one subreddit, which is why this
adapter fans out over a curated list. A fan-out is also what research wants,
because the right sub for a question is rarely the biggest one.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from urllib.parse import urlencode

from ..extract import clean_text
from ..text import search_phrase
from ..models import Hit
from .base import Adapter, FetchError

ARCTIC = "https://arctic-shift.photon-reddit.com/api"
SUBS = (
    "technology", "programming", "webdev", "MachineLearning", "LocalLLaMA",
    "selfhosted", "AskReddit", "science", "worldnews", "todayilearned",
    "datascience", "devops",
)
POST_ID = re.compile(r"/comments/([a-z0-9]+)")


def _utc_date(value) -> str:
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    return datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y-%m-%d")


def parse_reddit_posts(payload: str | bytes | dict) -> list[dict]:
    if isinstance(payload, (str, bytes)):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []
    else:
        data = payload
    rows = data.get("data") or []
    if isinstance(rows, dict):
        rows = [rows]
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = clean_text(row.get("title") or "")
        permalink = row.get("permalink") or ""
        post_id = str(row.get("id") or "")
        if not post_id:
            match = POST_ID.search(permalink)
            post_id = match.group(1) if match else ""
        if not title or not post_id:
            continue
        url = "https://www.reddit.com" + permalink if permalink.startswith("/") else (
            f"https://www.reddit.com/comments/{post_id}/"
        )
        selftext = clean_text(row.get("selftext") or "")
        out.append({
            "url": url,
            "title": title,
            "snippet": selftext[:300],
            "date": _utc_date(row.get("created_utc")),
            "subreddit": row.get("subreddit") or "",
            "id": post_id,
            "score": row.get("score") or 0,
        })
    return out


def parse_reddit_comments(payload: str | bytes | dict) -> list[dict]:
    if isinstance(payload, (str, bytes)):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []
    else:
        data = payload
    rows = data.get("data") or []
    if isinstance(rows, dict):
        rows = [rows]
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        body = clean_text(row.get("body") or "")
        if not body or body in {"[deleted]", "[removed]"}:
            continue
        out.append({
            "body": body,
            "score": int(row.get("score") or 0),
            "created_utc": int(row.get("created_utc") or 0),
            "author": str(row.get("author") or ""),
        })
    return out


class RedditAdapter(Adapter):
    kind = "reddit"
    name = "reddit"

    def search(self, query: str) -> list[Hit]:
        hits: list[Hit] = []
        errors: list[FetchError] = []
        attempted = 0
        phrase = search_phrase(query, 4)
        for sub in SUBS:
            params = {"subreddit": sub, "query": phrase, "limit": "25", "sort": "desc"}
            url = f"{ARCTIC}/posts/search?{urlencode(params)}"
            try:
                response = self.http.get(url, stage="search",
                                         accept="application/json")
                rows = parse_reddit_posts(response.text)
                if not rows:
                    # arctic-shift reports slow queries inside a 200 body.
                    payload = json.loads(response.text or "{}")
                    error = str(payload.get("error") or "")
                    if "imeout" in error:
                        token = max(query.split(), key=len) if query.split() else query
                        if token and token != query:
                            retry = f"{ARCTIC}/posts/search?" + urlencode({
                                "subreddit": sub, "query": token, "limit": "25",
                                "sort": "desc",
                            })
                            response = self.http.get(retry, stage="search",
                                                     accept="application/json")
                            rows = parse_reddit_posts(response.text)
                    if not rows:
                        attempted += 1
                        continue
                for row in rows:
                    hits.append(Hit(
                        url=row["url"],
                        title=row["title"],
                        snippet=row["snippet"],
                        date=row["date"],
                        kind="reddit",
                        via=query,
                        rank=len(hits),
                    ))
                attempted += 1
            except (FetchError, json.JSONDecodeError) as exc:
                attempted += 1
                reason = exc.reason if isinstance(exc, FetchError) else "bad json"
                errors.append(FetchError(0, f"r/{sub}: {reason}", url))
        self.failures.extend((error.url, error.reason) for error in errors)
        if attempted and len(errors) == attempted:
            raise errors[-1]
        return hits

    def fetch(self, url: str):
        match = POST_ID.search(url)
        if not match:
            raise FetchError(0, "not a reddit post url", url)
        post_id = match.group(1)
        api = f"{ARCTIC}/comments/search?" + urlencode({"link_id": post_id, "limit": "50"})
        response = self.http.get(api, stage="fetch", accept="application/json")
        try:
            comments = parse_reddit_comments(response.text)
        except (json.JSONDecodeError, ValueError):
            comments = []
        if not comments:
            from ..models import Page

            return Page(url=url, kind="reddit", status="empty",
                        reason="no comments in archive", domain="reddit.com")
        comments.sort(key=lambda row: (-row["score"], row["created_utc"], row["body"]))
        # Comment bodies are already plain text. Do not re-parse them as HTML:
        # a stray "<" in a comment must not be mistaken for a tag.
        text = "\n\n".join(row["body"] for row in comments[:80])
        from ..models import Page

        return Page(
            url=url,
            title="",
            text=text,
            kind="reddit",
            status="ok" if text else "empty",
            reason="" if text else "no comment text",
            domain="reddit.com",
        )
