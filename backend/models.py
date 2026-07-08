"""Shared intermediate document structure.

Every converter emits a Document; the EPUB builder and AI formatter only
ever consume Documents, keeping them format-agnostic.
"""
from dataclasses import dataclass, field

from bs4 import BeautifulSoup


class ConversionError(Exception):
    """Human-readable error, safe to show in the UI."""


# Tags allowed inside chapter body HTML. Everything else is unwrapped
# (text kept) or, for the junk list below, removed entirely.
ALLOWED_TAGS = {
    "p", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "strong", "em",
    "b", "i", "u", "s", "code", "pre", "table", "thead", "tbody", "tr",
    "th", "td", "img", "a", "hr", "br", "sup", "sub", "figure", "figcaption",
}
JUNK_TAGS = {"script", "style", "head", "title", "meta", "link", "iframe",
             "svg", "canvas", "form", "button", "input", "select", "nav",
             "noscript", "video", "audio", "object", "template"}
ALLOWED_ATTRS = {"a": {"href"}, "img": {"src", "alt"}}


def sanitize(html: str) -> str:
    """Reduce arbitrary HTML to the clean semantic subset above."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        if tag.decomposed:
            continue
        if tag.name in JUNK_TAGS:
            tag.decompose()
        elif tag.name in ("h5", "h6"):
            tag.name = "h4"
            tag.attrs = {}
        elif tag.name not in ALLOWED_TAGS and tag.name != "h1":
            tag.unwrap()  # h1 survives so the chapter splitter can see it
        else:
            allowed = ALLOWED_ATTRS.get(tag.name, set())
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in allowed}
    # drop empty paragraphs left over from the cleanup
    for p in soup.find_all("p"):
        if not p.get_text(strip=True) and not p.find("img"):
            p.decompose()
    return str(soup).strip()


@dataclass
class Chapter:
    title: str
    html: str  # sanitized body HTML, no h1 (the title becomes the h1)
    images: dict[str, bytes] = field(default_factory=dict)  # filename -> data

    def word_count(self) -> int:
        return len(BeautifulSoup(self.html, "html.parser").get_text(" ").split())


@dataclass
class Document:
    title: str = ""
    author: str = ""
    language: str = "en"
    chapters: list[Chapter] = field(default_factory=list)

    def plain_text(self) -> str:
        """Markdown-ish text of the whole document, for the AI step."""
        return "\n\n".join(_chapter_markdown(c) for c in self.chapters)


def _chapter_markdown(ch: Chapter) -> str:
    soup = BeautifulSoup(ch.html, "html.parser")
    blocks = [f"# {ch.title}"] if ch.title else []
    for el in soup.children:
        name = getattr(el, "name", None)
        if name is None:
            if str(el).strip():
                blocks.append(str(el).strip())
            continue
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if name in ("h2", "h3", "h4"):
            blocks.append("#" * int(name[1]) + " " + text)
        elif name in ("ul", "ol"):
            lines = []
            for i, li in enumerate(el.find_all("li", recursive=False), 1):
                bullet = f"{i}." if name == "ol" else "-"
                lines.append(f"{bullet} {li.get_text(' ', strip=True)}")
            blocks.append("\n".join(lines))
        elif name == "blockquote":
            blocks.append("\n".join("> " + ln for ln in text.splitlines()))
        elif name == "pre":
            blocks.append("```\n" + el.get_text().strip() + "\n```")
        else:
            blocks.append(text)
    return "\n\n".join(blocks)
