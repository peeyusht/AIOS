"""Showing a document as it looks: file bytes are handed out only against a short-lived ticket, only for
files the agent knows, only for kinds a browser can show safely, and never for a password-protected PDF."""
import io
import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import search_index as si  # noqa: E402
import web_ui  # noqa: E402


class FakeHandler:
    """Enough of BaseHTTPRequestHandler to run Handler._file and see what it sent."""
    def __init__(self):
        self.status, self.headers_out, self.wfile = None, {}, io.BytesIO()

    def send_response(self, code):
        self.status = code

    def send_header(self, k, v):
        self.headers_out[k] = v

    def end_headers(self):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.status, self.body = code, body


class ViewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.inbox, self.para = self.tmp / "inbox", self.tmp / "para"
        self.inbox.mkdir()
        self.para.mkdir()
        self.files = {}
        for name, data in (("report.pdf", b"%PDF-1.4 made up"), ("letter.docx", b"PK made up"), ("photo.png", b"\x89PNG made up"),
                           ("secret.pdf", b"%PDF-1.4 locked"), ("page.html", b"<script>alert(1)</script>"),
                           ("drawing.svg", b"<svg onload='alert(1)'/>"), ("notes.txt", b"plain text")):
            p = self.para / name
            p.write_bytes(data)
            self.files[name] = str(p)
        status = {self.files["secret.pdf"]: "locked"}
        self.idx = SimpleNamespace(preview=lambda p: ({"status": status.get(p, "ok")} if p in self.files.values() else None))
        web_ui.Ctx.cfg, web_ui.Ctx.log = {"inbox_folders": [self.inbox]}, logging.getLogger("sf-test")
        web_ui._tickets.clear()
        p = mock.patch.object(si, "get", return_value=self.idx)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, url):
        h = FakeHandler()
        web_ui.Handler._file(h, url[len("/api/file/"):])
        return h

    def test_pdf_docx_and_pictures_get_a_ticket_and_the_right_headers(self):
        for name, kind, ctype, disp in (("report.pdf", "pdf", "application/pdf", "inline"),
                                        ("photo.png", "image", "image/png", "inline"),
                                        ("letter.docx", "docx", web_ui.VIEWABLE[".docx"][1], "attachment")):
            t = web_ui.issue_ticket(self.files[name])
            self.assertEqual((t["ok"], t["kind"]), (True, kind), name)
            h = self.get(t["url"])
            self.assertEqual(h.status, 200)
            self.assertEqual(h.wfile.getvalue(), Path(self.files[name]).read_bytes())
            self.assertEqual((h.headers_out["Content-Type"], h.headers_out["Content-Disposition"]),
                             (ctype, f"{disp}; filename*=UTF-8\'\'{name}"))
            self.assertTrue(t["url"].endswith("/" + name))
            self.assertEqual(h.headers_out["X-Content-Type-Options"], "nosniff")
            self.assertEqual(h.headers_out["Cache-Control"], "no-store")
            self.assertEqual(h.headers_out["Content-Security-Policy"], "frame-ancestors 'self'")

    def test_what_is_never_handed_out(self):
        for name, why in (("secret.pdf", "Password-protected"), ("page.html", "can't be shown"),
                          ("drawing.svg", "can't be shown"), ("notes.txt", "can't be shown")):
            t = web_ui.issue_ticket(self.files[name])
            self.assertFalse(t["ok"], name)
            self.assertIn(why, t["message"])
        outside = self.tmp / "outside.pdf"          # exists, but the agent does not know it
        outside.write_bytes(b"%PDF-1.4")
        self.assertEqual(web_ui.issue_ticket(str(outside)), {"ok": False, "message": "Unknown file."})
        self.assertEqual(web_ui.issue_ticket(r"C:\Windows\win.ini")["ok"], False)
        self.assertEqual(web_ui._tickets, {})

    def test_a_new_file_in_downloads_can_be_shown_before_it_is_indexed(self):
        p = self.inbox / "fresh.png"
        p.write_bytes(b"\x89PNG new")
        self.assertTrue(web_ui.issue_ticket(str(p))["ok"])
        (self.inbox / "sub").mkdir()
        deep = self.inbox / "sub" / "deep.png"      # not directly in the watched folder, not indexed
        deep.write_bytes(b"\x89PNG")
        self.assertFalse(web_ui.issue_ticket(str(deep))["ok"])

    def test_cloud_only_and_too_big(self):
        with mock.patch.object(si, "is_cloud_only", return_value=True):
            t = web_ui.issue_ticket(self.files["report.pdf"])
        self.assertIn("only in the cloud", t["message"])
        with mock.patch.dict(web_ui.VIEW_MAX_MB, {"pdf": 0}):
            self.assertIn("Too big", web_ui.issue_ticket(self.files["report.pdf"])["message"])

    def test_a_ticket_expires_and_dies_with_a_changed_file(self):
        t = web_ui.issue_ticket(self.files["report.pdf"])
        ticket = t["url"].split("/")[3]
        self.assertEqual(self.get(t["url"]).status, 200)
        self.assertEqual(self.get(t["url"]).status, 200)                 # a viewer may ask more than once
        self.assertEqual(self.get("/api/file/not-a-ticket").status, 404)
        Path(self.files["report.pdf"]).write_bytes(b"%PDF-1.4 something else now")
        self.assertEqual(self.get(t["url"]).status, 404)                 # not the file the ticket was for
        t2 = web_ui.issue_ticket(self.files["photo.png"])
        web_ui._tickets[t2["url"].split("/")[3]]["expires"] = 0
        self.assertEqual(self.get(t2["url"]).status, 404)
        self.assertNotIn(t2["url"].split("/")[3], web_ui._tickets)
        self.assertNotEqual(ticket, web_ui.issue_ticket(self.files["photo.png"])["url"].split("/")[3])
        os.remove(self.files["photo.png"])
        self.assertFalse(web_ui.issue_ticket(self.files["photo.png"])["ok"])

    def test_tickets_do_not_pile_up(self):
        for _ in range(230):
            web_ui.issue_ticket(self.files["photo.png"])
        self.assertLessEqual(len(web_ui._tickets), 200)

    def test_preview_says_what_can_be_shown(self):
        full = {"path": "", "name": "", "ext": ".pdf", "size": 1, "modified": "", "read_at": "", "text": "", "chars": 0,
                "truncated": False, "openable": True, "note": ""}
        status = {self.files["secret.pdf"]: "locked"}
        self.idx.preview = lambda p: ({**full, "status": status.get(p, "ok")} if p in self.files.values() else None)

        class H:
            def _send(self, code, body, ctype="application/json"):
                self.code, self.body = code, body
        h = H()
        for name, want in (("report.pdf", "pdf"), ("letter.docx", "docx"), ("photo.png", "image"),
                           ("secret.pdf", None), ("notes.txt", None)):
            web_ui._search_post(h, "/api/search/preview", {"path": self.files[name]})
            self.assertEqual((h.code, h.body["view"]), (200, want), name)


if __name__ == "__main__":
    unittest.main()
