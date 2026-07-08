"""EPUB3 generation tuned for Kindle e-ink, plus validation."""
import html as html_mod
import io
import json
import mimetypes
import re
import shutil
import subprocess
import textwrap
import uuid
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from ebooklib import epub
from PIL import Image, ImageDraw, ImageFont

from .models import Document

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- css

def eink_css(text_align: str, paragraph_style: str) -> str:
    if paragraph_style == "spaced":
        p_rule = "p { margin: 0 0 0.7em; text-indent: 0; }"
    else:  # book-style indents
        p_rule = ("p { margin: 0; text-indent: 1.2em; }\n"
                  "h1 + p, h2 + p, h3 + p, h4 + p, blockquote + p, hr + p,\n"
                  "p:first-child { text-indent: 0; }")
    return f"""\
html, body {{ margin: 0; padding: 0; }}
body {{ font-family: serif; line-height: 1.5; text-align: {text_align}; }}
h1, h2, h3, h4 {{ font-weight: bold; line-height: 1.25; text-align: left;
  page-break-after: avoid; }}
h1 {{ font-size: 1.55em; margin: 1.6em 0 1em; }}
h1.chapter {{ margin-top: 2.8em; }}
h2 {{ font-size: 1.3em; margin: 1.4em 0 0.6em; }}
h3 {{ font-size: 1.15em; margin: 1.2em 0 0.5em; }}
h4 {{ font-size: 1em; margin: 1.1em 0 0.4em; }}
{p_rule}
blockquote {{ margin: 1em 1.4em; font-style: italic; }}
ul, ol {{ margin: 0.8em 0; padding-left: 1.6em; }}
li {{ margin: 0.25em 0; text-indent: 0; }}
code {{ font-family: monospace; font-size: 0.9em; }}
pre {{ font-family: monospace; font-size: 0.85em; white-space: pre-wrap;
  margin: 1em 0; text-align: left; }}
img {{ max-width: 100%; }}
table {{ border-collapse: collapse; margin: 1em 0; font-size: 0.9em; }}
th, td {{ border: 1px solid #777; padding: 0.3em 0.5em; text-align: left; }}
hr {{ border: none; border-top: 1px solid #777; margin: 1.6em 20%; }}
.titlepage {{ text-align: center; margin-top: 28%; }}
.titlepage h1 {{ font-size: 1.9em; text-align: center; margin: 0 0 0.4em; }}
.titlepage .rule {{ margin: 1.2em 38%; border: none; border-top: 2px solid #444; }}
.titlepage p {{ text-indent: 0; text-align: center; font-size: 1.05em; }}
"""


# --------------------------------------------------------------- cover

PAPER, INK, SIENNA = "#F6F1E7", "#231F1A", "#B4552D"


def _cover_font(size: int) -> ImageFont.FreeTypeFont:
    for f in (ROOT / "frontend" / "fonts").glob("*.ttf"):
        try:
            font = ImageFont.truetype(str(f), size)
            try:
                font.set_variation_by_axes([560])  # semibold-ish on variable fonts
            except OSError:
                pass
            return font
        except OSError:
            continue
    return ImageFont.load_default(size)


def make_cover(title: str, author: str) -> bytes:
    W, H = 1200, 1600
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    lines, size = [], 96
    while size >= 48:
        font = _cover_font(size)
        lines = textwrap.wrap(title, width=max(8, int((W - 280) / (size * 0.52))))
        if len(lines) <= 5:
            break
        size -= 12
    line_h = size * 1.25
    y = H * 0.30 - (len(lines) * line_h) / 2
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text(((W - w) / 2, y), ln, font=font, fill=INK)
        y += line_h
    y += 40
    d.rectangle([(W - 160) / 2, y, (W + 160) / 2, y + 6], fill=SIENNA)
    if author:
        afont = _cover_font(44)
        w = d.textlength(author, font=afont)
        d.text(((W - w) / 2, y + 60), author, font=afont, fill=INK)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# --------------------------------------------------------------- build

def build_epub(doc: Document, out_path: Path, text_align: str = "justify",
               paragraph_style: str = "indent") -> None:
    book = epub.EpubBook()
    book.set_identifier(f"urn:uuid:{uuid.uuid4()}")
    book.set_title(doc.title)
    book.set_language(doc.language or "en")
    if doc.author:
        book.add_author(doc.author)
    book.add_metadata("DC", "date", date.today().isoformat())

    css = epub.EpubItem(uid="style", file_name="style/book.css",
                        media_type="text/css",
                        content=eink_css(text_align, paragraph_style))
    book.add_item(css)

    book.set_cover("cover.png", make_cover(doc.title, doc.author))

    titlepage = epub.EpubHtml(uid="titlepage", title="Title Page",
                              file_name="titlepage.xhtml", lang=doc.language)
    titlepage.content = (
        '<div class="titlepage">'
        f"<h1>{html_mod.escape(doc.title)}</h1>"
        '<hr class="rule"/>'
        + (f"<p>{html_mod.escape(doc.author)}</p>" if doc.author else "")
        + f"<p>{date.today().strftime('%B %Y')}</p></div>")
    titlepage.add_item(css)
    book.add_item(titlepage)

    chapters = []
    for i, ch in enumerate(doc.chapters, 1):
        item = epub.EpubHtml(uid=f"ch{i}", title=ch.title or f"Section {i}",
                             file_name=f"chap_{i:03}.xhtml", lang=doc.language)
        body = re.sub(r'src="([^"/]+)"', r'src="images/\1"', ch.html)
        item.content = f'<h1 class="chapter">{html_mod.escape(ch.title)}</h1>{body}'
        item.add_item(css)
        book.add_item(item)
        chapters.append(item)
        for name, data in ch.images.items():
            mt = mimetypes.guess_type(name)[0] or "image/png"
            book.add_item(epub.EpubImage(uid=f"i{i}_{name.split('.')[0]}",
                                         file_name=f"images/{name}",
                                         media_type=mt, content=data))

    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["cover", titlepage, *chapters]
    epub.write_epub(str(out_path), book)


# --------------------------------------------------------- metadata edit

_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container",
       "opf": "http://www.idpf.org/2007/opf"}
_DC = "{http://purl.org/dc/elements/1.1/}"


def set_epub_metadata(path: Path, title: str = "", author: str = "") -> None:
    """Rewrite dc:title/dc:creator in an existing EPUB's OPF — for epubs that
    arrive pre-built (direct Send-to-Kindle) rather than through build_epub()."""
    if not title and not author:
        return
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        entries = {n: z.read(n) for n in names}

    container = ET.fromstring(entries["META-INF/container.xml"])
    opf_path = container.find(".//c:rootfile", _NS).get("full-path")
    opf = ET.fromstring(entries[opf_path])
    metadata_el = opf.find(f"{{{_NS['opf']}}}metadata")

    def _set(tag: str, value: str) -> None:
        el = metadata_el.find(f"{_DC}{tag}")
        if el is None:
            el = ET.SubElement(metadata_el, f"{_DC}{tag}")
        el.text = value

    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    ET.register_namespace("opf", "http://www.idpf.org/2007/opf")
    if title:
        _set("title", title)
    if author:
        _set("creator", author)
    entries[opf_path] = ET.tostring(opf, encoding="utf-8", xml_declaration=True)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), entries.pop("mimetype"), zipfile.ZIP_STORED)
        for name, content in entries.items():
            z.writestr(name, content)


# ---------------------------------------------------------- validation


def validate_epub(path: Path) -> dict:
    """Internal structural checks, plus epubcheck when java + jar are present."""
    errors, warnings, info = [], [], []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            first = z.infolist()[0]
            if first.filename != "mimetype":
                errors.append("mimetype is not the first entry in the archive.")
            elif first.compress_type != zipfile.ZIP_STORED:
                errors.append("mimetype entry is compressed (must be stored).")
            container = ET.fromstring(z.read("META-INF/container.xml"))
            opf_path = container.find(".//c:rootfile", _NS).get("full-path")
            opf_dir = str(Path(opf_path).parent)
            opf = ET.fromstring(z.read(opf_path))

            manifest = {it.get("id"): it for it in opf.iter(f"{{{_NS['opf']}}}item")}
            for it in manifest.values():
                href = str(Path(opf_dir) / it.get("href")).replace("\\", "/")
                href = href.removeprefix("./")
                if href not in names:
                    errors.append(f"Manifest references missing file: {it.get('href')}")
                elif it.get("media-type") == "application/xhtml+xml":
                    try:
                        ET.fromstring(z.read(href))
                    except ET.ParseError as e:
                        errors.append(f"{it.get('href')} is not well-formed XHTML ({e}).")

            spine = [r.get("idref") for r in opf.iter(f"{{{_NS['opf']}}}itemref")]
            if not spine:
                errors.append("Spine is empty.")
            for idref in spine:
                if idref not in manifest:
                    errors.append(f"Spine references unknown item: {idref}")
            if not any(it.get("properties") == "nav" for it in manifest.values()):
                errors.append("No nav document (table of contents) found.")
            info.append(f"{len(spine)} spine items, {len(manifest)} manifest items — structure OK."
                        if not errors else "Structural problems detected.")
    except Exception as e:
        errors.append(f"Could not inspect EPUB archive: {e}")

    epubcheck_used = False
    jar = ROOT / "vendor" / "epubcheck.jar"
    if jar.exists() and shutil.which("java"):
        try:
            r = subprocess.run(["java", "-jar", str(jar), str(path), "--json", "-"],
                               capture_output=True, text=True, timeout=90)
            data = json.loads(r.stdout or "{}")
            for msg in data.get("messages", []):
                sev, text = msg.get("severity", ""), msg.get("message", "")
                if sev in ("ERROR", "FATAL"):
                    errors.append(f"epubcheck: {text}")
                elif sev == "WARNING":
                    warnings.append(f"epubcheck: {text}")
            epubcheck_used = True
            if not any(m.startswith("epubcheck") for m in errors + warnings):
                info.append("epubcheck passed with no issues.")
        except Exception:
            warnings.append("epubcheck is present but failed to run; internal checks only.")

    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "info": info, "epubcheck": epubcheck_used}
