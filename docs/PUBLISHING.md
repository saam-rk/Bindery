# Publishing Bindery

This checklist is for publishing the **source repository**, not a binary release
or a public hosted service. The project remains a personal, single-user local tool.

## Before making the repository public

1. Review and merge the AGPL preparation branch into `main` using your normal Git
   workflow. Do not publish an older `main` whose `LICENSE` still says MIT.
2. Ensure `LICENSE` (AGPLv3), `NOTICE`, `THIRD_PARTY_NOTICES.md`, the full
   `docs/licenses/` directory, `requirements.txt` and `constraints.txt` are included.
3. Run, in the virtual environment:
   ```sh
   python -m pip install -r requirements.txt
   python -m pip check
   python test_pipeline.py
   python -m unittest -v test_publication
   ```
   OCR tests require Windows, `winocr` and an installed supported language.
   A skipped OCR test is not evidence that OCR works on that machine.
4. Inspect the staged files and the **Git history**, not just `.gitignore`, for
   documents, credentials and personal data. Ignoring a file does not remove earlier
   commits. If a real credential has ever been committed, revoke/rotate it; simply
   deleting it in a later commit is not enough.
5. Keep `storage/`, `.venv/`, `.env*`, `*.key`, `*.enc`, `*.pem` and optional `vendor/`
   contents out of the repository. The existing local `start.ps1` is excluded and
   has not been reviewed for publication. Do not force-add these files.
6. The current `docs/demo.gif` was reviewed frame by frame: eight frames of generic
   photosynthesis notes, with no visible personal credentials or identifying data.
   Recheck it whenever you replace it. Only demonstrate material you may publish.
7. The original commit-email metadata was anonymized with the owner's authorization.
   To avoid GitHub retaining old commit objects in the publication target, the owner
   selected a fresh private repository at the usual Bindery URL; the former repository
   remains a **separate private historical backup**. Only the sanitized `main` branch
   is uploaded, not a mirror or an original-history bundle. Never make the historical
   backup public or upload the local private backup. Recheck this if importing branches
   or tags from another clone: they may still contain the original email.
8. After the updated source is on `main`, make the GitHub repository public yourself
   and verify that the UI's source/license/third-party-notice links resolve without
   a GitHub login. The UI currently links to `https://github.com/saam-rk/Bindery`.

## AGPL and redistribution

- The original Bindery application is `AGPL-3.0-only`. PyMuPDF's AGPL option and
  EbookLib's AGPLv3-or-later terms are retained. Fonts remain OFL; other dependencies
  retain their respective licenses.
- Preserve copyright, license and warranty notices when sharing the application.
  Publish/provide corresponding source in the manner required for your distribution.
- This repository contains application source and license notices, **not copies of
  Python dependency binaries**. pip retrieves the dependencies from their upstream
  distributions. Their projects and versions are identified in the notices and pins.
- If you ship an executable, container, installer, dependency wheel bundle or virtual
  environment, audit **that artifact**. In particular, provide the required corresponding
  source for included AGPL components (PyMuPDF, MuPDF, EbookLib), and the notices/source
  obligations of other included native and Python components. A link to Bindery's
  source alone is not a complete source provision for bundled third-party libraries.
- Modified versions offered over a network must satisfy AGPL section 13. Update the
  footer's source links in `frontend/index.html` to the exact source of your version,
  including your modifications and any necessary installation/build files. Keep
  that source accessible to the users who interact with it.
- If you modify font files, respect OFL restrictions, including Reserved Font Names.
- No production deployment, binary packaging or remote-hosting security audit has
  been performed as part of this source-publication preparation.

The completed review and its limits are recorded in [PUBLICATION_AUDIT.md](PUBLICATION_AUDIT.md).

The checklist explains practical project decisions; the actual license texts govern.
It is not a legal opinion or a guarantee of compliance for every distribution method.

## Portfolio description

> **Bindery — local document-to-EPUB converter for Kindle**
>
> Personal tool for converting study documents to EPUB, with Windows OCR for scanned
> PDFs, optional and reviewable AI structure cleanup, and email delivery to Kindle.
> Used regularly to prepare study material. Python, FastAPI and vanilla JavaScript.
> Developed with extensive AI assistance; published under AGPLv3.

Use "published" only after the repository is actually public. The functional tests
cover representative samples, not every malformed document. Do not present the AI
formatting as guaranteed lossless or the app as production-hardened.
