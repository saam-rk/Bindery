"""OCR fallback for scanned PDF pages, using the OCR engine built into Windows 10/11
(no Tesseract install needed) through the `winocr` package."""
import logging

log = logging.getLogger("bindery")

try:
    import winocr
    from PIL import Image
except ImportError:  # non-Windows or winocr not installed
    winocr = None

# ponytail: fixed language preference list; first one Windows has installed wins
LANGS = ("es", "en")
_lang: str | None = None


def available() -> bool:
    return winocr is not None


def page_text(pix) -> str:
    """OCR a PyMuPDF RGB pixmap. Returns plain text, one OCR line per line
    ('' if nothing was recognised)."""
    global _lang
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    for lang in (_lang,) if _lang else LANGS:
        try:
            result = winocr.recognize_pil_sync(img, lang)
        except Exception as exc:
            log.info("OCR with %r failed: %s", lang, exc)
            continue
        _lang = lang
        if isinstance(result, dict):  # winocr sync API returns a plain dict
            lines = [ln.get("text", "") for ln in result.get("lines", [])]
            return "\n".join(lines) if lines else result.get("text", "")
        return getattr(result, "text", "") or ""
    return ""
