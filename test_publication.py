"""Publication regressions. Run: python -m unittest -v test_publication.

Uses synthetic documents and temporary credentials only. AI and SMTP are mocked:
no real provider calls, emails, or changes to the user's credential store.
"""
import io
import ssl
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import fitz
import httpx
from bs4 import BeautifulSoup
from defusedxml.common import DefusedXmlException
from fastapi.testclient import TestClient
from PIL import Image

import app as server
from backend import ai_formatter, converters, key_manager, kindle_mail
from backend.epub_builder import build_epub, set_epub_metadata, validate_epub
from backend.models import Chapter, ConversionError, Document, sanitize


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bindery-regression-")
        self.root = Path(self.tmp.name)
        self.uploads = self.root / "uploads"
        self.output = self.root / "output"
        self.uploads.mkdir()
        self.output.mkdir()
        self.patches = [
            patch.object(server, "UPLOADS", self.uploads),
            patch.object(server, "OUTPUT", self.output),
            patch.object(server, "DOCS", {}),
            patch.object(server, "EPUBS", {}),
            patch.object(key_manager, "MASTER", self.root / "keys" / "master.key"),
            patch.object(key_manager, "STORE", self.root / "keys.enc"),
        ]
        for mock in self.patches:
            mock.start()
        self.client = TestClient(server.app, base_url="http://127.0.0.1")

    def tearDown(self):
        self.client.close()
        for mock in reversed(self.patches):
            mock.stop()
        self.tmp.cleanup()

    def upload(self, text, name="notes.md"):
        response = self.client.post("/api/extract", files={"file": (name, text.encode())})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(list(self.uploads.iterdir()))
        return response.json()["doc_id"]

    def test_unsafe_html(self):
        body = sanitize('''<script>secret()</script><p onclick="secret()">Text</p>
            <img src="https://example.invalid/tracker.png"><img src="/api/keys">
            <img src="img1.png" onerror="secret()"><a href="javascript:secret()">A</a>
            <a href="java&#10;script:secret()">B</a><a href="file:///private">C</a>
            <a href="https://[broken">D</a><a href="https://example.invalid">Safe</a>''')
        soup = BeautifulSoup(body, "html.parser")
        self.assertEqual([i.get("src") for i in soup.find_all("img")], ["img1.png"])
        self.assertEqual([a.get("href") for a in soup.find_all("a")],
                         [None, None, None, None, "https://example.invalid"])
        self.assertNotIn("secret()", body)
        self.assertNotIn("onclick", body)
        self.assertNotIn("onerror", body)

    def test_empty_chapter_split(self):
        self.assertEqual(converters.split_chapters("", "Empty"), (None, []))
        doc_id = self.upload("# Title\n\nSome study notes.")
        self.assertIn(doc_id, server.DOCS)
        for text in ("", "   ", "# Only a title"):
            response = self.client.post("/api/extract", files={"file": ("empty.md", text.encode())})
            self.assertEqual(response.status_code, 400)
        self.assertFalse(list(self.uploads.iterdir()))

    def test_upload_errors_and_cleanup(self):
        for name, data in (("file.exe", b"x"), ("bad.pdf", b"not a pdf"),
                           ("bad.docx", b"not a zip")):
            response = self.client.post("/api/extract", files={"file": (name, data)})
            self.assertEqual(response.status_code, 400, response.text)
            self.assertNotIn("Traceback", response.text)
            self.assertFalse(list(self.uploads.iterdir()))
        with patch.object(server, "MAX_UPLOAD", 4):
            response = self.client.post("/api/extract", files={"file": ("large.txt", b"12345")})
            self.assertEqual(response.status_code, 400)

    def test_password_protected_pdf(self):
        path = self.root / "locked.pdf"
        with fitz.open() as pdf:
            pdf.new_page().insert_text((50, 50), "Synthetic notes")
            pdf.save(path, encryption=5,  # PyMuPDF's PDF_ENCRYPT_AES_256 enum
                     owner_pw="synthetic-owner", user_pw="synthetic-reader")
        with self.assertRaisesRegex(ConversionError, "password-protected"):
            converters.convert(path, path.name)

    def test_api_build_download_and_preview(self):
        doc_id = self.upload('# Example\n\nA **synthetic** document. <img src="https://example.invalid/t.png"><img src="img99.png">')
        response = self.client.post("/api/build", json={"doc_id": doc_id, "title": "Sample <book>"})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["validation"]["ok"], data["validation"])
        self.assertIn("Content-Security-Policy", data["preview_html"])
        self.assertNotIn("example.invalid", data["preview_html"])
        self.assertNotIn("img99.png", data["preview_html"])
        self.assertIn("Example", data["preview_html"])  # preview uses the chapter title
        download = self.client.get(f"/api/download/{data['epub_id']}")
        self.assertEqual(download.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            self.assertEqual(archive.read("mimetype"), b"application/epub+zip")
            self.assertIn(b"Sample &lt;book&gt;", archive.read("EPUB/titlepage.xhtml"))
        page = self.client.get("/").text
        self.assertIn('sandbox=""', page)
        self.assertIn("AGPL-3.0-only", page)
        self.assertEqual(self.client.get("/api/download/missing").status_code, 400)

    def test_embedded_preview_image(self):
        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), "red").save(buffer, "PNG")
        server.DOCS["image"] = {"original": Document(title="Images", chapters=[
            Chapter("Image", '<p><img src="img1.png" alt="Example"/></p>', {"img1.png": buffer.getvalue()})
        ]), "formatted": None}
        response = self.client.post("/api/build", json={"doc_id": "image"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('src="data:image/png;base64,', response.json()["preview_html"])

    def test_encrypted_credentials_and_masking(self):
        synthetic = "synthetic-test-key-1234"
        response = self.client.put("/api/keys/google", json={"key": synthetic})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(synthetic, response.text)
        self.assertEqual(key_manager.get_key("google"), synthetic)
        self.assertNotIn(synthetic.encode(), key_manager.STORE.read_bytes())
        self.assertEqual(self.client.get("/api/keys").json()["keys"]["google"], "…1234")
        self.assertEqual(self.client.put("/api/keys/unknown", json={"key": synthetic}).status_code, 400)
        self.client.delete("/api/keys/google")
        self.assertIsNone(key_manager.get_key("google"))
        cfg = {"smtp_user": "sender@example.invalid", "smtp_pass": "synthetic-password",
               "kindle_email": "reader@kindle.com"}
        response = self.client.put("/api/kindle", json=cfg)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(cfg["smtp_pass"], response.text)
        self.assertNotIn(cfg["smtp_pass"].encode(), key_manager.STORE.read_bytes())
        self.client.delete("/api/kindle")
        self.assertFalse(self.client.get("/api/kindle").json()["configured"])

    def test_ai_is_explicit_and_reviewable(self):
        doc_id = self.upload("# Original\n\nSynthetic paragraph.")
        missing = self.client.post("/api/ai-format", json={"doc_id": doc_id, "provider": "google"})
        self.assertEqual(missing.status_code, 400)
        key_manager.set_key("google", "synthetic-key")
        with patch.object(server.ai_formatter, "format_chunks", return_value=iter(["# Tidied\n\nSynthetic paragraph."])) as call:
            response = self.client.post("/api/ai-format", json={"doc_id": doc_id, "provider": "google"})
            self.assertEqual(response.status_code, 200)
            self.assertIn('"done": true', response.text)
            call.assert_called_once()
        entry = server.DOCS[doc_id]
        self.assertIsNotNone(entry["formatted"])
        self.assertIn("Synthetic paragraph", entry["original"].plain_text())

    def test_provider_payloads_without_network(self):
        responses = {
            "google": {"candidates": [{"content": {"parts": [{"text": "Cleaned"}]}}]},
            "anthropic": {"content": [{"type": "text", "text": "Cleaned"}]},
            "openai": {"choices": [{"message": {"content": "Cleaned"}}]},
        }
        urls = {"google": "https://generativelanguage.googleapis.com/",
                "anthropic": "https://api.anthropic.com/", "openai": "https://api.openai.com/"}
        for provider, body in responses.items():
            with self.subTest(provider=provider), patch("backend.ai_formatter.httpx.post") as post:
                post.return_value = httpx.Response(200, json=body)
                result = ai_formatter.CALLERS[provider]("synthetic-api-key", "synthetic-model", "Synthetic text.")
                self.assertEqual(result, "Cleaned")
                self.assertTrue(post.call_args.args[0].startswith(urls[provider]))
                self.assertNotIn("synthetic-api-key", post.call_args.args[0])
                self.assertIn("Synthetic text.", str(post.call_args.kwargs["json"]))

    def test_smtp_tls_and_attachment_without_network(self):
        epub = self.root / "book.epub"
        build_epub(Document(title="Sample", chapters=[Chapter("Study", "<p>Notes.</p>")]), epub)
        cfg = {"smtp_user": "sender@example.invalid", "smtp_pass": "synthetic-password",
               "kindle_email": "reader@kindle.com"}
        with patch("backend.kindle_mail.smtplib.SMTP_SSL") as smtp:
            kindle_mail.send(epub, cfg, "A\r\nbook")
            context = smtp.call_args.kwargs["context"]
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertEqual(message["Subject"], "Abook")
            self.assertEqual(next(message.iter_attachments()).get_content_type(), "application/epub+zip")
        with patch("backend.kindle_mail.smtplib.SMTP") as smtp:
            kindle_mail.send(epub, {**cfg, "smtp_host": "smtp.example.invalid:587"})
            smtp.return_value.__enter__.return_value.starttls.assert_called_once()
        for host in ("smtp.example.invalid:abc", "smtp.example.invalid:70000"):
            with self.assertRaisesRegex(ConversionError, "SMTP port"):
                kindle_mail.send(epub, {**cfg, "smtp_host": host})
        with self.assertRaisesRegex(ConversionError, "control characters"):
            kindle_mail.send(epub, {**cfg, "smtp_user": "sender\n@example.invalid"})

    def test_cross_site_and_untrusted_hosts(self):
        self.assertEqual(self.client.get("/api/keys", headers={"Host": "evil.example.invalid"}).status_code, 400)
        self.assertEqual(self.client.put("/api/keys/google", json={"key": "synthetic"},
                                        headers={"Origin": "https://evil.example.invalid"}).status_code, 403)
        self.assertEqual(self.client.get("/api/keys", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.get("/api/keys", headers={"Origin": "http://127.0.0.1"}).status_code, 200)
        self.assertIsNone(key_manager.get_key("google"))

    def test_cover_landmark_and_repeated_images(self):
        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), "red").save(buffer, "PNG")
        doc = Document(title="Illustrated", chapters=[
            Chapter(f"Chapter {i}", '<p><img src="img1.png" alt="Sample"/></p>', {"img1.png": buffer.getvalue()})
            for i in range(2)
        ])
        path = self.root / "images.epub"
        build_epub(doc, path)
        self.assertTrue(validate_epub(path)["ok"])
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
            self.assertIn(b'href="cover.xhtml"', archive.read("EPUB/nav.xhtml"))
            self.assertIn("EPUB/images/1_img1.png", archive.namelist())
            self.assertIn("EPUB/images/2_img1.png", archive.namelist())

    def test_xml_entities_are_rejected(self):
        path = self.root / "entities.epub"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
            archive.writestr("META-INF/container.xml", '''<!DOCTYPE container [<!ENTITY secret SYSTEM "file:///private">]>
                <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">&secret;</container>''')
        self.assertFalse(validate_epub(path)["ok"])
        with self.assertRaises(DefusedXmlException):
            set_epub_metadata(path, "Title")

    def test_invalid_epub_is_never_sent(self):
        with patch.object(kindle_mail, "send") as send:
            response = self.client.post("/api/send-epub", files={"file": ("bad.epub", b"not a zip")})
            self.assertEqual(response.status_code, 400)
            send.assert_not_called()
        self.assertFalse(list(self.uploads.iterdir()))

    def test_epub_metadata_and_direct_send(self):
        path = self.root / "sample.epub"
        build_epub(Document(title="Old", chapters=[Chapter("Chapter", "<p>Study.</p>")]), path)
        set_epub_metadata(path, "New title", "Example author")
        self.assertTrue(validate_epub(path)["ok"])
        with zipfile.ZipFile(path) as archive:
            opf = archive.read("EPUB/content.opf")
            self.assertIn(b"New title", opf)
            self.assertIn(b"Example author", opf)
        with patch.object(kindle_mail, "send") as send:
            response = self.client.post("/api/send-epub", files={"file": ("book.epub", path.read_bytes())},
                                        data={"title": "Direct title", "author": "Author"})
            self.assertEqual(response.status_code, 200, response.text)
            send.assert_called_once()
        self.assertFalse(list(self.uploads.iterdir()))


if __name__ == "__main__":
    unittest.main()
