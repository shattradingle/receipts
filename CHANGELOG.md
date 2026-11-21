# Changelog

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
