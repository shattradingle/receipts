# How receipts works

`receipts` runs a question through six keyless sources, fetches the pages those
sources return, and keeps sentences that were already on the page. It never asks
a model to write anything.

```
question
   │
   ├─ expand ──► 1 variant at depth 1, 3 at depth 2/3
   │
   ├─ search ──► web · news · hn · wiki · arxiv · reddit     6 threads
   │
   ├─ dedupe ──► normalised URL, then near-identical title
   │
   ├─ select ──► round-robin by source, relevance first, cap --max-pages
   │
   ├─ fetch  ──► 4 threads, 10 s timeout, 1.5 MB cap, 1 rps per host
   │              │
   │              └─ extract main text with html.parser
   │
   ├─ quote  ──► 20–45 word verbatim sentences, max 3 per source
   │
   ├─ theme  ──► shared unigrams/bigrams, no embeddings
   │
   └─ record ──► SQLite + board JSON + Markdown/HTML export
```

## Sources

| adapter | endpoint | why it looks like this |
| --- | --- | --- |
| `web` | `bing.com/search` HTML, `li.b_algo` | Bing is the only HTML engine here that answers without a key. Mojeek is the fallback when Bing returns no organic results. |
| `news` | Google News RSS, then Bing News RSS | Google News item links are JavaScript redirects with no article body, so they cannot be quoted. Bing News RSS links carry the publisher URL in a `url` parameter and can be fetched. |
| `hn` | `hn.algolia.com/api/v1/search` | Public, JSON, no key. Ask HN posts with no external URL fall back to the HN item page. |
| `wiki` | `en.wikipedia.org/w/api.php` | MediaWiki search. Natural-language questions are turned into a short quoted phrase before the request. |
| `arxiv` | `export.arxiv.org/api/query` | Atom search; abstracts are quoted, not PDFs. |
| `reddit` | `arctic-shift.photon-reddit.com` | The archive has no global search. A keyword query only works when scoped to a subreddit, so the adapter fans out over 12 curated subs. |

### Why Reddit is fetched this way

The obvious keyless Reddit routes are all broken for a server-side tool, measured
on 2026-11-06 in the sibling `reddit-rail` project:

- `www.reddit.com/search.rss` does not search. It returns r/all trending junk.
- `www.reddit.com/**.json` returns 403 from datacenter IPs without auth.
- `search.rss` starts returning 429 after a handful of requests.
- `api.pullpush.io` and the popular mirrors have been down.

The public arctic-shift archive is the one that still works. Its limit, a query
must be scoped to one subreddit, is why the adapter fans out. Every blocked sub
is recorded as a search failure, not silently dropped.

## Quote rules

A quote must be a contiguous slice of the extracted page text. It is never
spliced, paraphrased or assembled from several sentences.

1. Split paragraphs into sentences, with guards for `Dr.`, `U.S.`, decimals and
   closing quotes.
2. Keep 20 to 45 words. A sentence longer than 45 words is cut at a word boundary
   and marked with ` …`; a shorter one is skipped.
3. Drop link-heavy blocks, cookie notices, share prompts, page metadata such as
   `10 pages, 7 figures`, and sentences with no terminal punctuation unless they
   are long and comma-punctuated.
4. Score by question-term coverage, term density and position in the page:
   `0.55 * coverage + 0.30 * min(1, density * 3) + 0.15 * position`.
5. Keep up to 3 per source, dedupe by normalised text, drop zero-term quotes when
   at least five quotes do match a term.
6. Sort by source date descending, then score descending, then URL. Ids follow
   that order.

Themes use unigrams and bigrams that appear in at least two quotes. Bigrams get a
1.4x preference because "context window" says more than "context". Candidates
that are subsets of an already chosen theme are skipped. Six themes maximum.

## Determinism

The pipeline has no randomness. For the same set of fetched pages, the board
content is identical: same source ids, quote ids, ordering, scores and themes.
Run ids and timestamps obviously change. The search results themselves are the
live web, so the same question tomorrow can produce a different board.

Page selection is deterministic for a given hit set: hits are grouped by source,
sorted by question-term relevance then original rank, and taken round-robin so
one adapter cannot fill the board. Depth 3 secondary links are same-domain only,
two per page and eight total, which keeps a runaway crawl out of the result.

## Every request is recorded

`run_hits` in SQLite holds every deduped search hit, including the ones not
chosen for fetching. `requests` holds each request's stage, URL, status, elapsed
time and note. `--max-pages` caps fetches, but every search variant still counts against
the shared request cap (120 by default). When the cap is hit, the board records
one budget failure instead of one per abandoned URL.

Fetch outcomes:

| status | meaning |
| --- | --- |
| `ok` | text extracted, quote candidates considered |
| `thin` | only title or meta description found |
| `empty` | fetched, no text to quote |
| `blocked` | 401/403/418/429/451, reason recorded |
| `timeout` | 10 s timeout or socket timeout |
| `failed` | connection, DNS, bad response |

## Live outcome, 2026-11-21

Measured from this machine through its logging proxy. The demo board uses the
sources marked below.

| adapter | what happened | used in demo |
| --- | --- | --- |
| `web` | Bing returned 200 with 10 organic results, but they were generic dictionary pages for a natural-language question. 6 pages fetched, 0 quotes. Mojeek returned 403. | no |
| `news` | 18 hits, 6 pages ok, 2 blocked (Forbes and ThePrint, both 403), 15 quotes. The Google News results were redirects, so the Bing News fallback supplied the fetchable URLs. | yes |
| `hn` | 16 hits, 12 pages ok, 0 failed, 18 quotes at depth 1 after the content-word query edit. | yes |
| `wiki` | phrase search works. Combined with HN at depth 1 it produced 26 hits, 12 pages ok and 20 quotes, but Wikipedia pages drift on a question this specific (Omarchy, Chemotherapy, GLM), so it was left out of the demo. | no |
| `arxiv` | 12 hits, 6 pages ok, 18 quotes. Abstracts only. | yes |
| `reddit` | not called live from the build shell because the local research rail forbids raw archive calls. The adapter is fixture-tested: 2 posts, 2 comments, deleted comments skipped, fetch builds a page from archive comments. | no |

The baked demo board is a real run of `news,hn,arxiv` at depth 2: 9 queries, 66
hits, 11 pages ok, 1 blocked page, 25 quotes, 8.8 s. Its one failure is the
Forbes 403, kept in the board on purpose.

## No model, no keys

- `tests/test_no_network.py` scans every adapter for hosts outside the six source
  domains, for `reddit.com/search`, for `search.rss`, for `pullpush`, and for
  model or HTTP-client imports.
- `pyproject.toml` has no `[project.dependencies]` at all.
- The desk has no external font, CDN, image or script. It is three files served
  by `http.server`.
- The static HTML export inlines CSS and JS and embeds the board, so it opens
  from `file://` with no server.

Quotes and titles are inserted with `textContent`, never `innerHTML`. The JSON
embedded in a static export escapes `<` and `>` so a verbatim `</script>` in a
quote cannot break out of its tag.

## State

SQLite lives at `${XDG_STATE_HOME:-~/.local/state}/receipts/receipts.db`, or at
`$RECEIPTS_HOME/receipts.db` when set. Exports default to
`$RECEIPTS_HOME/exports`. Nothing is sent anywhere except the six source
domains.
