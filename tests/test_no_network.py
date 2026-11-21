from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent

ALLOWED_HOSTS = {
    "www.bing.com",
    "www.mojeek.com",
    "news.google.com",
    "hn.algolia.com",
    "en.wikipedia.org",
    "export.arxiv.org",
    "arxiv.org",
    "arctic-shift.photon-reddit.com",
    "www.reddit.com",
    "news.ycombinator.com",
    "www.w3.org",  # Atom XML namespace in the arXiv parser, never requested
}
URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
BANNED_IMPORTS = {
    "openai", "anthropic", "google", "requests", "httpx", "bs4", "flask",
    "fastapi", "jinja2", "transformers", "torch", "litellm", "langchain",
}


def adapter_files():
    return sorted((ROOT / "receipts" / "adapters").glob("*.py"))


def test_adapter_hosts_are_the_six_sources():
    for path in adapter_files():
        text = path.read_text(encoding="utf-8")
        for url in URL_RE.findall(text):
            host = urlsplit(url.rstrip(".,;")).hostname or ""
            assert host in ALLOWED_HOSTS, f"{path.name} contains {url}"


def test_no_reddit_search_or_json_endpoints():
    for path in adapter_files():
        text = path.read_text(encoding="utf-8")
        assert "reddit.com/search" not in text
        assert "search.rss" not in text
        assert "pullpush" not in text
        assert not re.search(r"reddit\.com/[^\s\"']*\.json", text)


def test_no_plain_http_except_arxiv():
    for path in adapter_files():
        text = path.read_text(encoding="utf-8")
        for url in URL_RE.findall(text):
            if url.startswith("http://"):
                host = urlsplit(url).hostname or ""
                assert host in {"export.arxiv.org", "arxiv.org", "www.w3.org"}, (
                    f"{path.name} uses plain http for {url}"
                )


def test_no_model_or_http_client_imports():
    for path in sorted((ROOT / "receipts").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        imports = re.findall(r"^(?:from|import)\s+([A-Za-z_][\w.]*)", text, re.MULTILINE)
        for name in imports:
            root = name.split(".")[0].lower()
            assert root not in BANNED_IMPORTS, f"{path} imports {name}"
        assert "openai" not in text.lower()
        assert "anthropic" not in text.lower()


def test_no_runtime_dependencies():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.dependencies]" not in text
    assert not re.search(r"^dependencies\s*=", text, re.MULTILINE)
    assert "requests" not in text
    assert "httpx" not in text


def test_no_personal_paths_or_secrets():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in {".venv", "__pycache__", ".pytest_cache", "docs"} for part in path.parts):
            continue
        if path.suffix not in {".py", ".md", ".toml", ".html", ".css", ".js", ".yml", ".svg", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        personal = "/" + "home/" + "zero"
        assert personal not in text, f"{path} contains a personal path"
        assert not re.search(r"sk-[A-Za-z0-9]{16,}", text)
        assert ("ghp" + "_") not in text


def test_no_external_assets_in_desk():
    html = (ROOT / "receipts" / "data" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "receipts" / "data" / "app.css").read_text(encoding="utf-8")
    assert "http://" not in html
    assert "https://" not in html
    assert "@import" not in css
    assert "url(http" not in css
    assert "cdn." not in html.lower()
    assert "fonts.googleapis" not in css
