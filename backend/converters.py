"""File-format converters. Each takes a path and returns a Document."""
import hashlib
import html as html_mod
import re
from pathlib import Path

import docx
import fitz  # PyMuPDF
import markdown as md_lib
from bs4 import BeautifulSoup

from . import ocr
from .models import Chapter, ConversionError, Document, sanitize

SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".markdown", ".html", ".htm"}


def convert(path: Path, original_name: str) -> Document:
    ext = Path(original_name).suffix.lower()
    handlers = {".pdf": _pdf, ".docx": _docx, ".txt": _txt, ".md": _md,
                ".markdown": _md, ".html": _html, ".htm": _html}
    if ext not in handlers:
        raise ConversionError(
            f"Unsupported file type “{ext or original_name}”. "
            "Supported: PDF, DOCX, TXT, Markdown, HTML.")
    stem = Path(original_name).stem.replace("_", " ").replace("-", " ").strip()
    try:
        doc = handlers[ext](path, stem)
    except ConversionError:
        raise
    except Exception as exc:  # never leak a stack trace to the UI
        raise ConversionError(
            f"Could not read “{original_name}” — the file may be corrupted, "
            "empty, or password-protected.") from exc
    doc.title = (doc.title or stem or "Untitled").strip()
    doc.chapters = [c for c in doc.chapters if c.html.strip() or c.images]
    if not doc.chapters:
        raise ConversionError(
            f"No readable text found in “{original_name}”. If it's a scanned "
            "PDF it contains only images — OCR it first.")
    return doc


# ---------------------------------------------------------------- chapters

def split_chapters(raw_html: str, default_title: str) -> tuple[str | None, list[Chapter]]:
    """Split flat HTML into chapters at the highest heading level present.

    A single *leading* h1 is treated as the document title, not a chapter.
    Returns (detected_doc_title, chapters).
    """
    soup = BeautifulSoup(sanitize(raw_html), "html.parser")
    doc_title = None
    h1s = soup.find_all("h1")
    first_el = next((c for c in soup.children if getattr(c, "name", None)), None)
    if h1s and h1s[0] is first_el:
        # A leading h1 is the document title (not a chapter) when it's the only
        # h1, or when just a short intro separates it from the next h1.
        if len(h1s) == 1:
            promote = True
        else:
            between = 0
            for sib in h1s[0].next_siblings:
                if sib is h1s[1]:
                    break
                between += len(str(sib))
            promote = between < 600
        if promote:
            doc_title = h1s[0].get_text(" ", strip=True)
            h1s[0].decompose()

    level = next((f"h{i}" for i in (1, 2, 3) if soup.find(f"h{i}")), None)
    if level is None:
        body = str(soup).strip()
        return doc_title, [Chapter(doc_title or default_title, body)] if body else (doc_title, [])

    chapters: list[Chapter] = []
    title, buf = None, []

    def flush():
        body = "".join(buf).strip()
        if body or title:
            chapters.append(Chapter(title or doc_title or default_title, body))

    for node in list(soup.children):
        if getattr(node, "name", None) == level:
            if buf or title:
                flush()
            title, buf = node.get_text(" ", strip=True), []
        else:
            buf.append(str(node))
    flush()
    return doc_title, chapters


def _distribute_images(chapters: list[Chapter], images: dict[str, bytes]):
    for ch in chapters:
        for src in re.findall(r'<img[^>]+src="([^"]+)"', ch.html):
            if src in images:
                ch.images[src] = images[src]


# ---------------------------------------------------------------- markdown

def md_to_document(text: str, default_title: str) -> Document:
    body = md_lib.markdown(text, extensions=["extra", "sane_lists"])
    title, chapters = split_chapters(body, default_title)
    return Document(title=title or "", chapters=chapters)


def _md(path: Path, stem: str) -> Document:
    return md_to_document(path.read_text(encoding="utf-8", errors="replace"), stem)


# -------------------------------------------------------------------- html

def _html(path: Path, stem: str) -> Document:
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    page_title = soup.title.get_text(strip=True) if soup.title else None
    body = soup.body.decode_contents() if soup.body else str(soup)
    title, chapters = split_chapters(body, page_title or stem)
    return Document(title=page_title or title or "", chapters=chapters)


# --------------------------------------------------------------------- txt

_HEADING_WORD = re.compile(
    r"^(chapter|part|section|unit|module|lecture|week|topic|lesson)\b[\s\d:.\-]*",
    re.IGNORECASE)
_NUMBERED = re.compile(r"^(\d+(\.\d+)*)[.)]?\s+\S")
_BULLET = re.compile(r"^\s*[-*•◦▪]\s+")


def _is_caps_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return (bool(letters) and len(line) <= 70
            and sum(c.isupper() for c in letters) / len(letters) > 0.9)


def _txt_heading_level(block: list[str]) -> int | None:
    """Return heading level for a single-line block, or None."""
    if len(block) != 1:
        return None
    line = block[0].strip()
    if len(line) > 90 or line.endswith((".", ",", ";", ":")):
        return None
    if _HEADING_WORD.match(line):
        return 1
    if _is_caps_heading(line):
        return 1
    m = _NUMBERED.match(line)
    if m and len(line) < 70:
        return 1 if "." not in m.group(1) else 2
    return None


def _txt(path: Path, stem: str) -> Document:
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    lines = text.split("\n")

    # setext-style underlines: "Title" followed by ==== or ----
    for i in range(len(lines) - 1):
        stripped = lines[i + 1].strip()
        if (lines[i].strip() and len(stripped) >= 3
                and (set(stripped) == {"="} or set(stripped) == {"-"})):
            lines[i] = ("# " if "=" in stripped else "## ") + lines[i].strip()
            lines[i + 1] = ""

    blocks, cur = [], []
    for ln in lines:
        if ln.strip():
            cur.append(ln)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)

    out = []
    for block in blocks:
        first = block[0].strip()
        if first.startswith("#"):  # from setext conversion
            lvl = min(len(first) - len(first.lstrip("#")), 3)
            out.append(f"<h{lvl}>{html_mod.escape(first.lstrip('# ').strip())}</h{lvl}>")
            block = block[1:]
            if not block:
                continue
            first = block[0].strip()
        lvl = _txt_heading_level(block)
        if lvl:
            out.append(f"<h{lvl}>{html_mod.escape(first)}</h{lvl}>")
        elif _BULLET.match(first) and all(
                _BULLET.match(ln) or ln.startswith((" ", "\t")) for ln in block):
            items = []
            for ln in block:
                if _BULLET.match(ln):
                    items.append(html_mod.escape(_BULLET.sub("", ln).strip()))
                elif items:
                    items[-1] += " " + html_mod.escape(ln.strip())
            out.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
        else:
            para = " ".join(ln.strip() for ln in block)
            out.append(f"<p>{html_mod.escape(para)}</p>")

    title, chapters = split_chapters("".join(out), stem)
    return Document(title=title or "", chapters=chapters)


# -------------------------------------------------------------------- docx

def _docx_runs_html(par) -> str:
    parts = []
    for run in par.runs:
        t = html_mod.escape(run.text)
        if not t:
            continue
        if run.bold:
            t = f"<strong>{t}</strong>"
        if run.italic:
            t = f"<em>{t}</em>"
        parts.append(t)
    return "".join(parts) or html_mod.escape(par.text)


def _docx(path: Path, stem: str) -> Document:
    d = docx.Document(str(path))
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    out, images, list_buf, img_n = [], {}, [], 0

    def flush_list():
        nonlocal list_buf
        if list_buf:
            tag = list_buf[0][0]
            out.append(f"<{tag}>" + "".join(f"<li>{t}</li>" for _, t in list_buf) + f"</{tag}>")
            list_buf = []

    for child in d.element.body.iterchildren():
        if child.tag == qn("w:tbl"):
            flush_list()
            rows = []
            for row in Table(child, d).rows:
                cells = "".join(f"<td>{html_mod.escape(c.text.strip())}</td>" for c in row.cells)
                rows.append(f"<tr>{cells}</tr>")
            out.append(f"<table>{''.join(rows)}</table>")
            continue
        if child.tag != qn("w:p"):
            continue
        par = Paragraph(child, d)

        # extract inline images referenced in this paragraph
        img_html = ""
        for blip in child.findall(".//" + qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            part = d.part.related_parts.get(rid) if rid else None
            if part is None:
                continue
            img_n += 1
            name = f"img{img_n}{Path(str(part.partname)).suffix or '.png'}"
            images[name] = part.blob
            img_html += f'<img src="{name}" alt=""/>'

        style = (par.style.name or "").lower() if par.style else ""
        text = _docx_runs_html(par)
        if not text.strip() and not img_html:
            continue
        if style.startswith("heading") and par.text.strip():
            flush_list()
            m = re.search(r"\d+", style)
            lvl = min(int(m.group()) if m else 1, 4)
            out.append(f"<h{lvl}>{html_mod.escape(par.text.strip())}</h{lvl}>")
        elif style == "title":
            flush_list()
            out.append(f"<h1>{html_mod.escape(par.text.strip())}</h1>")
        elif "list" in style:
            tag = "ol" if "number" in style else "ul"
            if list_buf and list_buf[0][0] != tag:
                flush_list()
            list_buf.append((tag, text))
        else:
            flush_list()
            out.append(f"<p>{text}{img_html}</p>")
    flush_list()

    props = d.core_properties
    title, chapters = split_chapters("".join(out), props.title or stem)
    _distribute_images(chapters, images)
    return Document(title=props.title or title or "", author=props.author or "",
                    chapters=chapters)


# --------------------------------------------------------------------- pdf

def _page_has_text(pg: dict) -> bool:
    return any(s["text"].strip()
               for b in pg["blocks"] for ln in b.get("lines", []) for s in ln["spans"])


def _ocr_paragraphs(text: str) -> list[str]:
    # ponytail: a line ending in sentence punctuation closes the paragraph; naive but
    # emit_paragraph() re-merges anything split wrongly
    paras, buf = [], ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        buf = _dehyphenate(buf + " " + line) if buf else line
        if re.search(r'[.!?:;]["\'”»)]?$', line):
            paras.append(buf)
            buf = ""
    if buf:
        paras.append(buf)
    return paras


def _pdf(path: Path, stem: str) -> Document:
    # read everything up front and close the handle, so Windows can delete the temp file
    with fitz.open(str(path)) as pdf:
        if pdf.needs_pass:
            raise ConversionError("This PDF is password-protected. Remove the password and try again.")
        pages = [p.get_text("dict") for p in pdf]
        meta = pdf.metadata or {}
        # pages with no selectable text (scans) fall back to Windows' built-in OCR
        ocr_paras: dict[int, list[str]] = {}
        if ocr.available():
            for i, page in enumerate(pdf):
                if _page_has_text(pages[i]):
                    continue
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), colorspace=fitz.csRGB)
                ocr_paras[i] = _ocr_paragraphs(ocr.page_text(pix))

    # body font size = the size carrying the most characters
    weights: dict[float, int] = {}
    for pg in pages:
        for block in pg["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    size = round(span["size"] * 2) / 2
                    weights[size] = weights.get(size, 0) + len(span["text"])
    if not weights and not any(ocr_paras.values()):
        raise ConversionError(
            "No readable text found in this PDF. It looks like a scan, and "
            + ("the built-in OCR couldn't read it — check that Windows has the document's "
               "language installed (Settings → Time & Language)."
               if ocr.available() else
               "OCR support isn't installed — run “pip install winocr” in Bindery's "
               "environment and try again."))
    body_size = max(weights, key=weights.get) if weights else 0

    # sizes clearly above body text become heading levels, largest first
    heading_sizes = sorted((s for s in weights if s >= body_size * 1.15 and s > body_size + 0.9),
                           reverse=True)[:3]
    levels = {s: i + 1 for i, s in enumerate(heading_sizes)}

    out: list[str] = []           # html blocks
    paragraphs: list[str] = []    # plain text of open paragraphs, parallel to <p> entries
    images: dict[str, bytes] = {}
    seen_hashes: set[str] = set()
    img_n = 0

    def emit_paragraph(text: str):
        text = re.sub(r"\s+", " ", text).strip()
        if not text or re.fullmatch(r"[\d\s\-–—•.]*", text):  # page numbers etc.
            return
        # continuation of the previous paragraph across blocks/pages?
        if (out and out[-1].startswith("<p>") and paragraphs
                and not paragraphs[-1].rstrip().endswith((".", "!", "?", ":", ";", "”", '"'))
                and text[0].islower()):
            joined = _dehyphenate(paragraphs[-1] + " " + text)
            paragraphs[-1] = joined
            out[-1] = f"<p>{html_mod.escape(joined)}</p>"
            return
        paragraphs.append(text)
        out.append(f"<p>{html_mod.escape(text)}</p>")

    for pg_i, pg in enumerate(pages):
        for para in ocr_paras.get(pg_i, []):
            emit_paragraph(para)
        for block in pg["blocks"]:
            if block["type"] == 1:  # image
                if ocr_paras.get(pg_i):  # the page IS the image; keep the text, drop the scan
                    continue
                data = block.get("image")
                if not data or len(data) < 2048:
                    continue
                if min(block["bbox"][2] - block["bbox"][0],
                       block["bbox"][3] - block["bbox"][1]) < 40:
                    continue
                h = hashlib.md5(data).hexdigest()
                if h in seen_hashes:  # repeated logos / watermarks
                    continue
                seen_hashes.add(h)
                img_n += 1
                name = f"img{img_n}.{block.get('ext', 'png')}"
                images[name] = data
                out.append(f'<p><img src="{name}" alt=""/></p>')
                paragraphs.append("")  # keep lists parallel
                continue

            buf = ""
            for line in block.get("lines", []):
                text = "".join(s["text"] for s in line["spans"]).strip()
                if not text:
                    continue
                size = round(max(s["size"] for s in line["spans"]) * 2) / 2
                bold = all("bold" in s["font"].lower() for s in line["spans"])
                lvl = levels.get(size)
                if lvl and len(text) < 120 and not text.endswith("."):
                    if buf:
                        emit_paragraph(buf)
                        buf = ""
                    out.append(f"<h{lvl}>{html_mod.escape(text)}</h{lvl}>")
                    paragraphs.append("")
                elif (bold and size >= body_size and len(text) < 80
                      and len(block.get("lines", [])) == 1 and not text.endswith((".", ","))):
                    # ponytail: whole-line bold at body size = minor heading; heuristic
                    if buf:
                        emit_paragraph(buf)
                        buf = ""
                    out.append(f"<h4>{html_mod.escape(text)}</h4>")
                    paragraphs.append("")
                else:
                    buf = _dehyphenate(buf + " " + text) if buf else text
            if buf:
                emit_paragraph(buf)

    default = (meta.get("title") or "").strip() or stem
    title, chapters = split_chapters("".join(out), default)
    _distribute_images(chapters, images)
    return Document(title=(meta.get("title") or "").strip() or title or "",
                    author=(meta.get("author") or "").strip(), chapters=chapters)


def _dehyphenate(text: str) -> str:
    """word- \nbreak -> wordbreak (only when the next part starts lowercase)."""
    return re.sub(r"(\w)[-‐]\s+([a-zà-ÿ])", r"\1\2", text)
