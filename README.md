# Bindery

![Bindery demo](docs/demo.gif)

A local web app that turns text documents — **PDF, DOCX, TXT, Markdown, HTML** — into
clean, Kindle-friendly **EPUB3** books, and sends them straight to your Kindle. Built for
converting school notes into something pleasant to read on e-ink. Conversion runs on
your machine. Network transfers happen only when you request AI tidy-up or Send to Kindle.

> **Before using private documents:** AI tidy-up is optional and off by default.
> Starting it sends the extracted document text to your selected provider
> (**Anthropic, OpenAI or Google**), with your API key. That provider's retention,
> processing and privacy policies apply. Send to Kindle sends the EPUB through your
> SMTP/email provider to Amazon. Skip both features to keep conversion local.

## Features

- **Five input formats** (PDF, DOCX, TXT, Markdown, HTML) normalized into one clean
  EPUB3, with automatic OCR for scanned PDFs.
- **Optional AI tidy-up** (Anthropic / OpenAI / Google, your own key), instructed to
  fix structure while preserving wording, with a side-by-side review before building.
  AI output is not guaranteed to preserve content; review it before accepting.
- **One-click Send to Kindle** by email once it's built.
- **Local-first**: no Bindery account, remote storage service or telemetry. Files and
  credentials are stored locally. API keys go to their own AI provider only when you
  request tidy-up; SMTP credentials go to your email server when you send a book.

## Stack

Python, FastAPI, vanilla HTML/CSS/JS (no build step). PDF via PyMuPDF, EPUB via
ebooklib, cover art via Pillow, OCR via Windows' built-in engine (`winocr`).

## Run it

Use **Python 3.11 or newer**. The pinned environment was validated on Windows with
Python 3.11; macOS/Linux support text-based conversion, but Windows OCR is unavailable.
Bindery is a **single-user localhost tool**, not a hardened public web service: keep
it bound to `127.0.0.1` and do not expose it to the internet.

```
run.bat        # Windows  (run.sh on macOS/Linux)
```

First run creates a `.venv` and installs dependencies; after that it just starts.
Then open **http://127.0.0.1:8118**. Or manually:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

Runtime versions are fixed in `requirements.txt`; transitive dependencies are constrained
in `constraints.txt`, with Windows-only packages marked accordingly. To update an existing
virtual environment after pulling changes, rerun `pip install -r requirements.txt` using
that environment's pip. The launchers only install on first run. Pins are not a security
update policy: review dependencies and rerun the tests when upgrading them.

## How it works

```
upload / paste Markdown → extract (+OCR if scanned) → (optional AI tidy-up + review)
  → build EPUB → validate → download
```

Markdown from a chat (Claude, ChatGPT…) can be pasted straight into the upload panel —
no need to convert it to PDF first; it converts directly and comes out cleaner.

- **`backend/converters.py`** — one extractor per format. Everything is normalized into
  a shared intermediate structure (`backend/models.py`: a `Document` holding `Chapter`s
  of sanitized semantic HTML), so EPUB generation never cares about the input format.
  PDFs get de-hyphenation, paragraph re-joining across pages, and heading detection by
  font size; TXT gets heading/list heuristics.
- **`backend/epub_builder.py`** — EPUB3 via `ebooklib`, with an embedded e-ink stylesheet
  (relative font sizes, 1.5 line-height, configurable justification and paragraph style),
  a generated typographic cover (Pillow), title page, and nav/NCX table of contents.
  Every build is validated: internal structural checks always run; if you drop
  [`epubcheck.jar`](https://github.com/w3c/epubcheck/releases) into `vendor/` and have
  Java on PATH, full epubcheck runs too and its findings show up in the result screen.
  Extract the complete EPUBCheck release into `vendor/`, retaining its `lib/` directory
  beside `vendor/epubcheck.jar`; the JAR alone is not a standalone distribution.
- **`backend/ai_formatter.py`** — optional cleanup of messy extractions. The text is
  chunked by section and sent to Anthropic, OpenAI, or Google (direct HTTPS calls, no
  SDKs) with a prompt that only allows structural fixes — never rewording. You review
  original vs. tidied side-by-side before anything is built.
- **`app.py`** — FastAPI server; also serves the frontend (vanilla HTML/CSS/JS in
  `frontend/`, self-hosted fonts, no build step).

## API keys

Add keys in the app's Settings drawer (key icon, top right). Storage
(`backend/key_manager.py`):

- Keys are encrypted at rest with Fernet (`cryptography`).
- The **master key** lives outside the repo at `~/.bindery/master.key`.
- The **encrypted store** is `storage/.keys/keys.enc` (gitignored).
- Keys are only ever sent to their own provider's API when *you* start a tidy-up.
  They're masked to the last 4 characters in the UI and never logged. Delete a key
  any time from Settings; deleting `~/.bindery/master.key` invalidates the store.

## Getting books onto the Kindle

Set up **Send to Kindle** in the Settings drawer (your email + an app password + your
`@kindle.com` address; SMTP host defaults to Gmail) and a one-click **Send to Kindle**
button appears after every build (`backend/kindle_mail.py`, stdlib `smtplib`). Your
email must be on Amazon's [approved senders](https://www.amazon.com/sendtokindle/email)
list. The SMTP password is stored in the same encrypted store as the API keys.

Or do it by hand: email the `.epub` to your Send-to-Kindle address or use Amazon's
Send to Kindle app/site. Amazon converts EPUB for the device; **copying an EPUB over
USB does not make it natively readable on a stock Kindle**.

## Notes

- Generated books accumulate in `storage/output/` — delete freely.
- Scanned (image-only) PDF pages are OCR'd automatically with the OCR engine built into
  Windows 10/11 (`backend/ocr.py`, via `winocr` — no Tesseract needed). The document's
  language must be installed in Windows (Settings → Time & Language); it tries Spanish,
  then English.
- `python test_pipeline.py` runs an end-to-end self-check of all five converters and
  the EPUB builder.
- `python -m unittest -v test_publication` covers privacy/security regressions, API
  conversion, metadata, encrypted test credentials and mocked AI/SMTP flows. It uses
  temporary stores and does not send real emails or call AI providers.
- Imported HTML's remote images and unsafe URL schemes are removed. The preview is
  sandboxed and allows only embedded image data, preventing automatic remote tracking.
  Ordinary HTTP(S) links remain clickable in an EPUB: opening them is a separate action.
- Direct EPUB sending validates the archive first. EPUBs expanding beyond 256 MB or
  10,000 entries are rejected. No converter can guarantee support for every document.

## Status

Personal project, built for my own use converting study material for e-ink reading.
Works well for its intended formats; not battle-tested against every possible malformed
PDF or DOCX out there.

## License

Copyright © 2026 saam-rk. Bindery's original application code is licensed under the
**[GNU Affero General Public License v3.0 only](LICENSE)** (`AGPL-3.0-only`), not MIT.
It is provided **without warranty**. See [NOTICE](NOTICE) for the application notice
and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for dependency and font licenses.

PyMuPDF is used under its AGPL option; EbookLib is AGPLv3-or-later, used under v3.
The bundled Albert Sans, Besley and IBM Plex Mono fonts remain **SIL OFL 1.1**;
their copyright notices and full license texts are in `docs/licenses/fonts/`.

When distributing Bindery or a modified version, preserve applicable notices and
provide the corresponding source as required by AGPL. If you modify it and let users
interact with it over a network, AGPL section 13 requires a prominent opportunity to
obtain the corresponding source of that version. The UI links to this repository;
**forks and hosted modifications must update those links to their actual source**.
Making an upstream link visible is not enough if it omits your modifications.

Your input documents and generated EPUB content are not automatically AGPL-licensed
just because you process them with Bindery; their own rights still apply.
For publication and redistribution checks, see [docs/PUBLISHING.md](docs/PUBLISHING.md).
