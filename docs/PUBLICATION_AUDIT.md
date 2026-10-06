# Source-publication audit

Scope: preparing Bindery's source repository for public sharing under AGPLv3.
This is an engineering and license-documentation review, **not a legal opinion,
penetration-test certification, or guarantee of perfect operation**.

## Privacy and provenance

- Reviewed the tracked source files, historical file paths and reachable historical
  text blobs for credentials, personal paths, document stores and personal identifiers.
  No committed API/SMTP secrets or private PDF/EPUB/key-store files were found by the
  patterns reviewed. Pattern matching cannot prove the absence of every possible secret.
- The owner's personal email occurred in commit author/committer metadata. With the
  owner's permission, all five original commits were recreated with the public
  `saam-rk@users.noreply.github.com` identity, preserving trees, messages and dates.
  New commits use that same identity. An original-history backup is stored privately
  **outside the repository** and is not part of the publication. With explicit owner
  permission, the old GitHub repository is retained as a separate private backup and
  the publication target is recreated privately, receiving only sanitized history.
- Reviewed all eight frames of `docs/demo.gif` and its GIF metadata. It shows generic
  photosynthesis notes, not settings, credentials or personal document identifiers.
  The owner confirmed that the original code and demonstration material may be published.
- Inspected every bundled font's name/copyright/license metadata. Families and copyright
  statements match the OFL texts provided for Albert Sans, Besley and IBM Plex Mono.
- Public project identity (`saam-rk`, repository URL and copyright) is intentional.
  Third-party authors' attribution in license notices is legally relevant and retained.
- `storage/`, temporary audit artifacts, credentials, virtual environments, optional
  EPUBCheck binaries and the existing unreviewed `start.ps1` remain excluded from Git.

**GitHub retention handling:** a force-push alone cannot prove that GitHub erased
old unreachable commits or cached views. To avoid carrying those objects into the
publication target, the owner chose a new private repository at the canonical URL,
while the old repository remains private under a different name. Only the sanitized
`main` history is uploaded to the new repository, never a mirror of the old object
store. Keep the historical backup private: it deliberately still contains the old
metadata. This strategy does not claim that GitHub erased the private backup.

## License review

- Bindery's current original application code is declared `AGPL-3.0-only`, with the
  complete license, copyright notice and no-warranty statement.
- Installed PyMuPDF 1.28.0 declares AGPLv3 or Artifex commercial licensing; Bindery
  elects AGPL, not a commercial license. EbookLib 0.20 is AGPLv3-or-later, used under v3.
  Their upstream declarations and installed license metadata were checked.
- Font metadata and full OFL notices were checked against the upstream Google Fonts
  license texts. The fonts retain OFL rather than being relicensed as AGPL.
- Dependency license notices are included for pinned direct/transitive runtime packages.
  The PyWinRT wheels omit license files; the upstream MIT license is retained instead.
- The source repository does not bundle dependency wheels, native libraries, a Python
  interpreter or EPUBCheck. A packaged/binary/container release needs a separate audit
  and corresponding source/notices for the components actually distributed.
- The application visibly links to its source, license and third-party notices.
  Those links must resolve anonymously after publication. Hosted modifications/forks
  must link to their own corresponding source, not merely an unmodified upstream.
- Prior MIT grants, if any were made for original-code revisions, are not revoked by
  the current licensing change. Those grants never remove dependency license obligations.

Based on the inspected declarations and the owner's provenance confirmation, no
unresolved license incompatibility was identified for **this source-only AGPL publication**.
Only a qualified legal adviser can assess all jurisdiction-specific facts or provide
professional legal assurance; no license choice guarantees freedom from every claim.

## Fixes prompted by the audit

- Remove remote HTML images and unsafe link schemes; drop unavailable image references.
- Sandbox the preview and restrict it with CSP; embed extracted images as data, without
  automatically retrieving external content or local API resources.
- Reject cross-site browser API requests and untrusted Host headers. These protections
  do **not** turn the localhost app into an authenticated public service.
- Correct empty chapter splitting and a Windows temporary-file handle leak when an
  invalid PDF is rejected by MuPDF.
- Add a reachable cover landmark and unique per-chapter image paths for valid EPUBs.
- Use DefusedXML for untrusted EPUB XML, bound expanded archive sizes and refuse invalid
  direct-send EPUBs instead of silently emailing them unchanged.
- Read EPUBCheck's explicit JSON report and check its exit status rather than assuming
  empty stdout means successful validation.
- Explicitly verify SMTP TLS certificates and strip control characters from email titles.
- Update vulnerable pinned versions: cryptography 50.0.0, anyio 4.14.2, soupsieve 2.9.
  Existing core libraries, including PyMuPDF and EbookLib, are retained.
- Correct privacy language, document that AI is not guaranteed lossless, and remove the
  misleading suggestion that stock Kindle devices read EPUB copied directly over USB.

## Validation evidence

- Created a new isolated Python 3.11 virtual environment on Windows, installed the pinned
  runtime dependencies and verified them with `pip check`.
- `test_pipeline.py`: Markdown, TXT, HTML, DOCX, text PDF, scanned PDF with Windows OCR,
  EPUB generation, chunking and the unconfigured Kindle-send guard passed.
- `python -m unittest -v test_publication`: 15 regression tests passed, covering API
  conversion/download, malformed/empty/password-protected inputs, cleanup, HTML safety,
  preview images, encrypted temporary credentials, cross-site/Host rejection, XML entities,
  metadata edits, cover navigation, repeated images, mocked AI, all three provider
  payloads with mocked HTTPS, and mocked SMTP/TLS.
- EPUBCheck **5.4.0**: seven representative books passed without errors or warnings
  (the six converter/OCR cases plus a repeated-image book). The earlier OPF-096 cover
  finding was fixed and the books were regenerated and revalidated.
- Automated Edge browser smoke test: paste, convert, download, preview, theme, synthetic
  settings, mocked AI review/acceptance and mocked Kindle sending passed. No browser
  JavaScript errors or external requests occurred during these local flows. Untrusted
  HTML did not run scripts or request tracking images.
- `node --check frontend/app.js` passed. Changed Python modules were checked during
  editing; active LSP diagnostics can be inconclusive on this environment, so absence
  of an LSP finding alone was not used as proof of correctness.
- `pip-audit` against the final pinned requirements reported **no known vulnerabilities**
  across 39 resolved runtime package entries. This is a point-in-time advisory-database
  result, not evidence that the packages have no undiscovered vulnerabilities.

## Limits and publication step

- No real AI requests or Kindle emails were sent: external integrations were mocked to
  avoid using private credentials, spending API credit or contacting recipients.
  Provider model availability, quotas and Amazon delivery can change independently.
- Windows/Python 3.11 and representative files were tested; other operating systems,
  Python versions and all possible malformed documents were not exhaustively tested.
- This remains a single-user tool bound to `127.0.0.1`. Do not expose it publicly.
- The audited source and sanitized history are prepared for GitHub's `main` in a clean
  private publication target. The owner must deliberately change the **new target's**
  visibility, never the historical backup's. Verify the source/license/notice links
  without login after that change. See [PUBLISHING.md](PUBLISHING.md).
