"""HTML to plain text, with no third-party parser.

A small tree is built with html.parser, then the best content container is
scored by text mass, punctuation and link density. Extraction keeps block text
in document order so sentences stay verbatim: nothing here rewrites a word.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
SKIP_TAGS = {
    "script", "style", "noscript", "template", "svg", "canvas", "iframe",
    "form", "nav", "footer", "aside", "header", "button", "select", "option",
    "textarea", "label", "menu",
}
BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "li", "td", "th", "blockquote",
    "pre", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt", "figcaption",
    "caption",
}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
CANDIDATE_TAGS = {"article", "main", "section", "div", "td", "body"}

BOILER_RE = re.compile(
    r"(?:^|[-_ ])(nav|navbar|menu|footer|header|sidebar|breadcrumb|cookie|consent|"
    r"banner|related|share|social|promo|subscribe|newsletter|advert|adverts|ads|"
    r"comment-meta|comments-meta|meta|masthead|toolbar|pagination|pager|modal|"
    r"popup|skip|arxivlabs|endorsers|submission|download|lab-name|bibliographic|"
    r"connected-papers|scite)(?:$|[-_ ])",
    re.I,
)
CONTENT_RE = re.compile(
    r"(article[-_]?body|post[-_]?content|entry[-_]?content|mw-parser-output|"
    r"markdown-body|comment[-_]?body|story[-_]?body|article[-_]?content|"
    r"content[-_]?body|main[-_]?content|prose|post[-_]?body|thread[-_]?body)",
    re.I,
)


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list["Node | str"] = field(default_factory=list)
    parent: "Node | None" = None
    depth: int = 0

    def attr(self, name: str) -> str:
        return self.attrs.get(name, "")

    @property
    def ident(self) -> str:
        return f"{self.attrs.get('class', '')} {self.attrs.get('id', '')}".strip()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{self.tag} {self.attr('class')}>"


class _DOM(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {})
        self.stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        current = self.stack[-1]
        # A small set of implied end tags covers the malformed HTML that survives
        # in the wild (unclosed paragraphs and list items above all).
        if tag in {"p", "li", "tr", "td", "th", "option"} and current.tag == tag:
            self.stack.pop()
            current = self.stack[-1]
        node = Node(tag, {k.lower(): (v or "") for k, v in attrs}, parent=current,
                    depth=current.depth + 1)
        current.children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID and self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def parse_dom(html: str) -> Node:
    parser = _DOM()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        # html.parser is forgiving; if it still throws, return what was built.
        pass
    return parser.root


def clean_text(text: str) -> str:
    text = unescape(text or "").replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def iter_nodes(root: Node, tags: set[str] | None = None):
    for child in root.children:
        if isinstance(child, Node):
            if tags is None or child.tag in tags:
                yield child
            yield from iter_nodes(child, tags)


def find_all(root: Node, tag: str) -> list[Node]:
    return [n for n in iter_nodes(root, {tag})]


def find_first(root: Node, tag: str) -> Node | None:
    for node in iter_nodes(root, {tag}):
        return node
    return None


def direct_text(node: Node) -> str:
    parts: list[str] = []

    def walk(item: Node) -> None:
        for child in item.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag in SKIP_TAGS:
                continue
            elif child.tag == "br":
                parts.append("\n")
            else:
                walk(child)

    walk(node)
    return clean_text("".join(parts))


def node_text(node: Node) -> str:
    """All text under a node, skipping boilerplate tags."""
    parts: list[str] = []

    def walk(item: Node) -> None:
        for child in item.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag in SKIP_TAGS:
                continue
            elif child.tag == "br":
                parts.append("\n")
            elif child.tag in BLOCK_TAGS:
                parts.append("\n")
                walk(child)
                parts.append("\n")
            else:
                walk(child)

    walk(node)
    text = "".join(parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _link_text(node: Node) -> int:
    total = 0
    for child in node.children:
        if isinstance(child, str):
            continue
        if child.tag == "a":
            total += len(clean_text(node_text(child)))
        elif child.tag not in SKIP_TAGS:
            total += _link_text(child)
    return total


def _stats(node: Node) -> tuple[int, int, int]:
    text = node_text(node)
    links = _link_text(node)
    punctuation = len(re.findall(r"[.!?;:]", text))
    return len(text), links, punctuation


def _boilerplate(node: Node) -> bool:
    return bool(BOILER_RE.search(node.ident))


def _content_hint(node: Node) -> bool:
    return bool(CONTENT_RE.search(node.ident)) or node.tag in {"article", "main"}


def choose_container(root: Node) -> Node:
    """Pick the densest coherent content block, then walk into it.

    The best-scoring node is usually the page wrapper, so descend while a single
    child still carries nearly all of the score. That lands on the article body
    instead of the whole document without picking one paragraph out of a thread.
    """
    ranked: list[tuple[float, int, Node]] = []
    for node in iter_nodes(root):
        if node.tag not in CANDIDATE_TAGS:
            continue
        if _boilerplate(node):
            continue
        length, links, punctuation = _stats(node)
        if length < 200:
            continue
        score = length - 2 * links + 30 * punctuation
        if _content_hint(node):
            score += 400
        ranked.append((score, node.depth, node))
    if not ranked:
        return find_first(root, "body") or root
    ranked.sort(key=lambda item: (-item[0], -item[1]))
    node = ranked[0][2]
    score = ranked[0][0]
    while True:
        best_child = None
        best_child_score = -1.0
        for child in node.children:
            if not isinstance(child, Node) or child.tag not in CANDIDATE_TAGS:
                continue
            if _boilerplate(child):
                continue
            length, links, punctuation = _stats(child)
            if length < 200:
                continue
            child_score = length - 2 * links + 30 * punctuation
            if _content_hint(child):
                child_score += 400
            if child_score > best_child_score:
                best_child, best_child_score = child, child_score
        if best_child is not None and best_child_score >= score * 0.85:
            node, score = best_child, best_child_score
        else:
            return node



def _block_text(node: Node) -> str:
    """Text belonging to one block, excluding nested blocks."""
    parts: list[str] = []

    def walk(item: Node) -> None:
        for child in item.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag in SKIP_TAGS:
                continue
            elif child.tag == "br":
                parts.append("\n")
            elif child.tag in BLOCK_TAGS:
                continue
            else:
                walk(child)

    walk(node)
    return clean_text("".join(parts))


def _in_skipped(node: Node, stop: Node | None = None) -> bool:
    """True when a skip tag or boilerplate wrapper sits between node and stop.

    The walk stops at the chosen content container. Above it, malformed pages
    can wrap <main> inside an unclosed footer div; that must not mark the whole
    article as boilerplate.
    """
    parent = node.parent
    while parent is not None:
        if parent.tag in SKIP_TAGS:
            return True
        # html and body carry site-wide classes ("...-in-header-enabled") that
        # look like boilerplate but are not a container to skip.
        if parent.tag not in {"html", "body"} and _boilerplate(parent):
            return True
        if stop is not None and parent is stop:
            break
        parent = parent.parent
    return False


def _blocks(container: Node) -> list[str]:
    blocks: list[str] = []
    seen: set[str] = set()

    for node in iter_nodes(container):
        if node.tag in SKIP_TAGS or _boilerplate(node) or _in_skipped(node, container):
            continue
        is_block = node.tag in BLOCK_TAGS
        has_block_child = any(
            isinstance(c, Node) and c.tag in BLOCK_TAGS for c in node.children
        )
        if not is_block or (has_block_child and node.tag not in {"li", "blockquote", "td"}):
            continue
        text = _block_text(node)
        if not text or text in seen:
            continue
        words = len(text.split())
        if node.tag in HEADING_TAGS:
            if len(text) < 12 or words > 40:
                continue
        elif node.tag == "li":
            if len(text) < 40:
                continue
        elif node.tag in {"td", "th", "dd", "dt", "caption"}:
            if len(text) < 40:
                continue
        else:
            if len(text) < 30:
                continue
        if len(text) > 60 and _link_text(node) / max(1, len(text)) > 0.55:
            continue
        if re.search(r"(accept (all )?cookies|privacy policy|sign up to our newsletter)", text, re.I):
            continue
        seen.add(text)
        blocks.append(text)

    if not blocks:
        # Some pages wrap every sentence in a bare div. Take those too.
        for node in iter_nodes(container, {"div", "section"}):
            if _boilerplate(node) or _in_skipped(node, container) or any(
                isinstance(c, Node) and c.tag in BLOCK_TAGS for c in node.children
            ):
                continue
            text = direct_text(node)
            if len(text) >= 80 and len(re.findall(r"[.!?]", text)) >= 2:
                if text not in seen:
                    seen.add(text)
                    blocks.append(text)
    return blocks


@dataclass
class Extracted:
    title: str = ""
    description: str = ""
    text: str = ""
    date: str = ""
    links: list[str] = field(default_factory=list)
    status: str = "ok"


def _meta(root: Node, names: set[str]) -> str:
    for node in iter_nodes(root, {"meta"}):
        key = (node.attr("property") or node.attr("name") or node.attr("itemprop")).lower()
        if key in names:
            value = clean_text(node.attr("content"))
            if value:
                return value
    return ""


def _extract_date(html: str, root: Node) -> str:
    from .models import date_only

    candidates = [
        _meta(root, {"article:published_time", "og:published_time", "datepublished",
                     "citation_date", "citation_publication_date", "date", "pubdate",
                     "publishdate", "article:modified_time"}),
    ]
    for node in iter_nodes(root, {"time"}):
        candidates.append(node.attr("datetime"))
    match = re.search(r'"(?:datePublished|dateCreated)"\s*:\s*"([^"]{4,40})"', html or "")
    if match:
        candidates.append(match.group(1))
    for value in candidates:
        normalised = date_only(value)
        if normalised:
            return normalised
    return ""


def _extract_links(container: Node, base_url: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for node in iter_nodes(container, {"a"}):
        href = clean_text(node.attr("href"))
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(absolute)
        if len(out) >= 30:
            break
    return out


def extract_page(html: str, url: str) -> Extracted:
    """Extract title, date, main text and body links from one HTML document."""
    root = parse_dom(html)
    container = choose_container(root)

    title_node = find_first(root, "title")
    title = clean_text(node_text(title_node)) if title_node else ""
    if not title:
        title = clean_text(_meta(root, {"og:title", "twitter:title"}))
    description = _meta(root, {"description", "og:description", "twitter:description"})
    date = _extract_date(html, root)

    blocks = _blocks(container)
    text = "\n\n".join(blocks)
    status = "ok"
    if len(text) < 200:
        fallback = [part for part in (title, description) if part]
        if len(" ".join(fallback)) > len(text):
            text = "\n\n".join(fallback)
            status = "thin"
    if not text.strip():
        status = "empty"
    return Extracted(
        title=title,
        description=description,
        text=text,
        date=date,
        links=_extract_links(container, url),
        status=status,
    )


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"p", "br", "li", "div"}:
            self.parts.append(" ")


def strip_tags(html: str) -> str:
    """Plain text from a fragment (RSS descriptions and search snippets)."""
    stripper = _Stripper()
    try:
        stripper.feed(html or "")
        stripper.close()
    except Exception:
        return clean_text(re.sub(r"<[^>]+>", " ", html or ""))
    return clean_text("".join(stripper.parts))
