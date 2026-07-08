"""Optional LLM cleanup of extracted text. Structure only — never content.

Providers are called directly over HTTPS with httpx; no provider SDKs.
The user's key goes to that provider and nowhere else.
"""
import re
import time

import httpx

from .models import ConversionError

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-5-mini",
    "google": "gemini-2.5-flash",
}

SYSTEM_PROMPT = """\
You clean up the STRUCTURE of text extracted from documents (school notes, \
articles, textbooks). The extraction process often breaks paragraphs, loses \
headings, and leaves artifacts. Your job:

- Rejoin paragraphs broken mid-sentence; split run-together paragraphs.
- Mark headings with Markdown: # for chapters/major sections, ## and ### below.
- Remove extraction artifacts: stray page numbers, repeated page headers/footers,
  broken hyphen-ation across line breaks, garbled OCR characters (only when the
  correction is unambiguous).
- Format obvious lists as Markdown lists; keep emphasis as **bold** / *italic*.

STRICT RULES — these override everything else:
- Preserve the original wording, meaning, order, and language EXACTLY.
- Never summarize, paraphrase, expand, comment, or add content of your own.
- Keep existing Markdown headings as they are.
- Output ONLY the cleaned Markdown text. No preamble, no explanations, and do
  not wrap the whole output in a code fence.\
"""


def chunk_text(text: str, target: int = 12000) -> list[str]:
    """Greedy paragraph packing; prefers starting new chunks at '# ' headings."""
    chunks, cur, size = [], [], 0
    for para in text.split("\n\n"):
        if cur and (size + len(para) > target
                    or (para.startswith("# ") and size > target // 3)):
            chunks.append("\n\n".join(cur))
            cur, size = [], 0
        while len(para) > target:  # single monster paragraph: hard split
            cut = para.rfind(". ", 0, target) + 1 or target
            chunks.append(para[:cut])
            para = para[cut:].lstrip()
        cur.append(para)
        size += len(para) + 2
    if cur:
        chunks.append("\n\n".join(cur))
    return [c for c in chunks if c.strip()]


def _friendly_error(provider: str, status: int, body: str) -> ConversionError:
    detail = ""
    m = re.search(r'"message"\s*:\s*"([^"]{1,200})"', body)
    if m:
        detail = f" ({m.group(1)})"
    msgs = {
        401: "rejected the API key — check it in Settings",
        403: "rejected the API key — check it in Settings",
        404: "does not recognize that model name",
        429: "rate limit or quota exceeded — wait a moment and retry",
    }
    what = msgs.get(status, f"returned an error (HTTP {status}){detail}")
    return ConversionError(f"{provider.title()} {what}.")


def _post(provider: str, url: str, headers: dict, payload: dict) -> dict:
    for attempt in (1, 2):
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=240)
        except httpx.TimeoutException:
            raise ConversionError(f"{provider.title()} request timed out — try again.")
        except httpx.HTTPError:
            raise ConversionError(f"Could not reach {provider.title()} — check your connection.")
        if r.status_code < 400:
            return r.json()
        if attempt == 1 and r.status_code in (429, 500, 502, 503, 529):
            time.sleep(3)
            continue
        raise _friendly_error(provider, r.status_code, r.text[:500])


def _call_anthropic(key: str, model: str, text: str) -> str:
    data = _post("anthropic", "https://api.anthropic.com/v1/messages",
                 {"x-api-key": key, "anthropic-version": "2023-06-01"},
                 {"model": model, "max_tokens": 8192, "system": SYSTEM_PROMPT,
                  "messages": [{"role": "user", "content": text}]})
    return "".join(b.get("text", "") for b in data.get("content", []))


def _call_openai(key: str, model: str, text: str) -> str:
    data = _post("openai", "https://api.openai.com/v1/chat/completions",
                 {"Authorization": f"Bearer {key}"},
                 {"model": model, "messages": [
                     {"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": text}]})
    return data["choices"][0]["message"]["content"] or ""


def _call_google(key: str, model: str, text: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = _post("google", url, {"x-goog-api-key": key},
                 {"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                  "contents": [{"role": "user", "parts": [{"text": text}]}]})
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        raise ConversionError("Google returned an empty response — the content "
                              "may have been blocked by a safety filter.")
    return "".join(p.get("text", "") for p in parts)


CALLERS = {"anthropic": _call_anthropic, "openai": _call_openai, "google": _call_google}


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = re.sub(r"^```[a-z]*\n", "", text)[: -3].strip()
    return text


def format_chunks(chunks: list[str], provider: str, model: str, key: str):
    """Generator: yields each formatted chunk in order (call per chunk)."""
    call = CALLERS[provider]
    for chunk in chunks:
        yield _strip_fence(call(key, model, chunk))
