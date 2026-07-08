"""Bindery — local document → Kindle-EPUB converter. Run: python app.py"""
import html as html_mod
import json
import logging
import re
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import ai_formatter, converters, key_manager, kindle_mail
from backend.epub_builder import build_epub, eink_css, set_epub_metadata, validate_epub
from backend.models import ConversionError, Document

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "storage" / "uploads"
OUTPUT = ROOT / "storage" / "output"
for d in (UPLOADS, OUTPUT):
    d.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD = 80 * 1024 * 1024
log = logging.getLogger("bindery")
app = FastAPI(title="Bindery")

# ponytail: in-memory stores, fine for a single-user localhost tool
DOCS: dict[str, dict] = {}   # doc_id -> {"original": Document, "formatted": Document|None}
EPUBS: dict[str, Path] = {}


@app.exception_handler(ConversionError)
async def conversion_error(_: Request, exc: ConversionError):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(Exception)
async def unexpected_error(_: Request, exc: Exception):
    log.exception("unexpected error", exc_info=exc)
    return JSONResponse(status_code=500, content={
        "error": "Something went wrong on the server. Check the terminal for details."})


# ---------------------------------------------------------------- pipeline

def _doc_summary(doc: Document) -> dict:
    return {"title": doc.title, "author": doc.author,
            "chapters": [{"title": c.title, "words": c.word_count()} for c in doc.chapters]}


@app.post("/api/extract")
async def extract(file: UploadFile):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise ConversionError("File is larger than 80 MB — that's beyond this tool's scope.")
    if not data:
        raise ConversionError("The uploaded file is empty.")
    name = Path(file.filename or "upload").name
    tmp = UPLOADS / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
    tmp.write_bytes(data)
    try:
        doc = converters.convert(tmp, name)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # a stray temp file must never mask the real error; storage/ is disposable
    doc_id = uuid.uuid4().hex
    DOCS[doc_id] = {"original": doc, "formatted": None}
    return {"doc_id": doc_id, **_doc_summary(doc)}


class AIFormatRequest(BaseModel):
    doc_id: str
    provider: str
    model: str = ""


@app.post("/api/ai-format")
def ai_format(req: AIFormatRequest):
    entry = DOCS.get(req.doc_id)
    if not entry:
        raise ConversionError("Session expired — please upload the file again.")
    if req.provider not in ai_formatter.CALLERS:
        raise ConversionError(f"Unknown provider: {req.provider}")
    key = key_manager.get_key(req.provider)
    if not key:
        raise ConversionError(
            f"No API key saved for {req.provider.title()} — add one in Settings first.")
    model = req.model.strip() or ai_formatter.DEFAULT_MODELS[req.provider]
    original = entry["original"]
    original_text = original.plain_text()
    chunks = ai_formatter.chunk_text(original_text)

    def stream():
        out = []
        try:
            gen = ai_formatter.format_chunks(chunks, req.provider, model, key)
            for i, formatted in enumerate(gen, 1):
                out.append(formatted)
                yield json.dumps({"chunk": i, "total": len(chunks)}) + "\n"
            merged = "\n\n".join(out)
            doc = converters.md_to_document(merged, original.title)
            doc.title, doc.author, doc.language = (original.title, original.author,
                                                   original.language)
            entry["formatted"] = doc
            yield json.dumps({"done": True, "original": original_text,
                              "formatted": merged,
                              **_doc_summary(doc)}) + "\n"
        except ConversionError as e:
            yield json.dumps({"error": str(e)}) + "\n"
        except Exception:
            log.exception("ai formatting failed")
            yield json.dumps({"error": "AI formatting failed unexpectedly — "
                                       "check the terminal for details."}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class BuildRequest(BaseModel):
    doc_id: str
    use_ai: bool = False
    title: str = ""
    author: str = ""
    language: str = "en"
    text_align: str = "justify"        # justify | left
    paragraph_style: str = "indent"    # indent | spaced


@app.post("/api/build")
def build(req: BuildRequest):
    entry = DOCS.get(req.doc_id)
    if not entry:
        raise ConversionError("Session expired — please upload the file again.")
    doc = entry["formatted"] if req.use_ai and entry["formatted"] else entry["original"]
    if req.title.strip():
        doc.title = req.title.strip()
    doc.author = req.author.strip()
    doc.language = req.language.strip() or "en"
    align = req.text_align if req.text_align in ("justify", "left") else "justify"
    pstyle = req.paragraph_style if req.paragraph_style in ("indent", "spaced") else "indent"

    slug = re.sub(r"[^\w\- ]", "", doc.title).strip().replace(" ", "-")[:60] or "book"
    epub_id = uuid.uuid4().hex
    out_path = OUTPUT / f"{slug}-{epub_id[:6]}.epub"
    build_epub(doc, out_path, align, pstyle)
    validation = validate_epub(out_path)
    EPUBS[epub_id] = out_path

    first = doc.chapters[0]
    preview = (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + eink_css(align, pstyle)
        + "body{max-width:34em;margin:0 auto;padding:2.5em 1.5em;"
          "background:#FDFBF7;color:#1a1a1a;font-size:17px;}"
        + "</style></head><body>"
        + f"<h1 class='chapter'>{html_mod.escape(first.title)}</h1>{first.html}"
        + "</body></html>")

    return {"epub_id": epub_id, "filename": out_path.name,
            "size": out_path.stat().st_size, "validation": validation,
            "preview_html": preview}


@app.get("/api/download/{epub_id}")
def download(epub_id: str):
    path = EPUBS.get(epub_id)
    if not path or not path.exists():
        raise ConversionError("That EPUB is no longer available — build it again.")
    return FileResponse(path, media_type="application/epub+zip", filename=path.name)


# ---------------------------------------------------------- send to kindle

class KindleConfig(BaseModel):
    smtp_user: str = ""
    smtp_pass: str = ""
    kindle_email: str = ""
    smtp_host: str = ""


def _kindle_status() -> dict:
    cfg = key_manager.get_config("kindle")
    return {"configured": kindle_mail.configured(cfg),
            "smtp_user": cfg.get("smtp_user", ""),
            "kindle_email": cfg.get("kindle_email", ""),
            "smtp_host": cfg.get("smtp_host", ""),
            "has_pass": bool(cfg.get("smtp_pass"))}


@app.get("/api/kindle")
def kindle_status():
    return _kindle_status()


@app.put("/api/kindle")
def kindle_save(req: KindleConfig):
    old = key_manager.get_config("kindle")
    key_manager.set_config("kindle", {
        "smtp_user": req.smtp_user.strip(),
        "kindle_email": req.kindle_email.strip(),
        "smtp_host": req.smtp_host.strip(),
        # an empty password field means "keep the one already saved"
        "smtp_pass": req.smtp_pass.strip() or old.get("smtp_pass", "")})
    return _kindle_status()


@app.delete("/api/kindle")
def kindle_delete():
    key_manager.set_config("kindle", {})
    return _kindle_status()


class SendRequest(BaseModel):
    title: str = ""


@app.post("/api/send/{epub_id}")
def send_to_kindle(epub_id: str, req: SendRequest = SendRequest()):
    path = EPUBS.get(epub_id)
    if not path or not path.exists():
        raise ConversionError("That EPUB is no longer available — build it again.")
    kindle_mail.send(path, key_manager.get_config("kindle"), req.title)
    return {"sent": True}


@app.post("/api/send-epub")
async def send_epub_direct(file: UploadFile, title: str = Form(""), author: str = Form("")):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise ConversionError("File is larger than 80 MB — that's beyond this tool's scope.")
    if not data:
        raise ConversionError("The uploaded file is empty.")
    name = Path(file.filename or "book.epub").name
    if not name.lower().endswith(".epub"):
        raise ConversionError("That's not an .epub file.")
    tmp = UPLOADS / f"{uuid.uuid4().hex}.epub"
    tmp.write_bytes(data)
    clean_title = title.strip() or Path(name).stem
    try:
        try:
            set_epub_metadata(tmp, clean_title, author.strip())
        except Exception:
            log.warning("could not rewrite metadata for %s; sending as-is", name)
        kindle_mail.send(tmp, key_manager.get_config("kindle"), clean_title)
    finally:
        tmp.unlink(missing_ok=True)
    return {"sent": True}


# -------------------------------------------------------------------- keys

class KeyRequest(BaseModel):
    key: str


@app.get("/api/keys")
def keys_status():
    return {"keys": key_manager.masked(),
            "defaults": ai_formatter.DEFAULT_MODELS}


@app.put("/api/keys/{provider}")
def set_key(provider: str, req: KeyRequest):
    if provider not in key_manager.PROVIDERS:
        raise ConversionError(f"Unknown provider: {provider}")
    if not req.key.strip():
        raise ConversionError("Key is empty.")
    key_manager.set_key(provider, req.key)
    return {"keys": key_manager.masked()}


@app.delete("/api/keys/{provider}")
def delete_key(provider: str):
    key_manager.delete_key(provider)
    return {"keys": key_manager.masked()}


# ---------------------------------------------------------------- frontend

app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")


if __name__ == "__main__":
    print("\n  Bindery -> http://127.0.0.1:8118\n")
    uvicorn.run(app, host="127.0.0.1", port=8118, log_level="warning")
