# Changelog

## 1.0.2 — 2026-11-21

- **A stronger baked demo.** The demo board is now a real five-source run
  (`web,news,hn,wiki,arxiv`, depth 2): 15 queries, 96 hits, 15 pages ok, 1 blocked page
  (Forbes, 403), 33 quotes from 16 sources, 8.2 s. It replaces the earlier three-source
  board, because the Bing redirect fix made the web source usable.
- README limits table re-measured against that run: web 4 pages / 11 quotes, news 3 pages
  (2 ok, 1 blocked) / 6 quotes, HN 3/4, wiki 3/4, arXiv 3 abstracts / 8 quotes.
- Screenshots regenerated from the new board.

## 1.0.1 — 2026-11-21

- **Bing redirects are decoded.** Bing's HTML now wraps every organic result in
  `/ck/a?…&u=a1<base64url>`; the adapter was fetching Bing's own pages and recording
  `bing.com` as the source domain. `resolve_bing_url` decodes the destination and drops
  links that only point back into Bing.
- **Long questions are asked as content words.** Web and Reddit adapters now send the
  question's content terms (5 and 4 words) instead of the raw sentence, the same way the
  Wikipedia and HN adapters already did. `search_phrase` is in `receipts/text.py`.
- Tests: 125 offline (was 121).

## 1.0.0 — 2026-11-21

First release.

- Six keyless sources: web (Bing, Mojeek fallback), news, Hacker News, Wikipedia, arXiv, Reddit archive.
- Deterministic pipeline: expand, search, dedupe, fetch, extract, quote, theme, record.
- Verbatim quote board in JSON, Markdown and a self-contained HTML file.
- Editorial web desk with live progress, keyboard review, copy and exports.
- `receipts demo` serves a baked board with no network.
- `receipts mcp` over stdio: two tools, no model, no keys.
