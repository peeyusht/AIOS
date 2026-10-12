"""Preview before filing: the text the index already holds for a file, put back together. No file is opened."""
import logging
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import search_index as si  # noqa: E402
import web_ui  # noqa: E402

TEXT = "\n\n".join(
    f"Section {i}. " + " ".join(f"The quick brown fox number {i}-{j} jumps over the lazy dog." for j in range(12))
    for i in range(30))


class JoinTest(unittest.TestCase):
    def test_round_trip(self):
        for size, overlap in ((1000, 150), (300, 60), (120, 30)):
            pieces = si.chunk_text(TEXT, size, overlap, 10_000)
            self.assertGreater(len(pieces), 5)
            self.assertEqual(si.join_chunks(pieces, overlap), TEXT, (size, overlap))

    def test_text_that_repeats_itself_is_not_cut_short(self):
        text = "Quarterly report draft, version A. " * 400
        text = text.strip()
        self.assertEqual(si.join_chunks(si.chunk_text(text, 1000, 150, 10_000)), text)

    def test_no_overlap_and_empty(self):
        self.assertEqual(si.join_chunks(["First part.", "Second part."]), "First part.\n\nSecond part.")
        self.assertEqual(si.join_chunks([]), "")
        self.assertEqual(si.join_chunks(["", "only"]), "only")


class PreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE files (path TEXT PRIMARY KEY, root TEXT, source TEXT, name TEXT, folder TEXT, ext TEXT,
                size INTEGER, mtime_ns INTEGER, status TEXT, chars INTEGER, chunks INTEGER, indexed_at TEXT, error TEXT);
            CREATE TABLE chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, idx INTEGER, text TEXT, vec BLOB);
        """)
        self.idx = SimpleNamespace(cfg={}, lock=threading.Lock(), conn=conn)
        self.idx.preview = lambda p: si.Index.preview(self.idx, p)
        self.idx.is_indexed = lambda p: si.Index.is_indexed(self.idx, p)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, path, status, text="", ext=".pdf", limit=10_000):
        name = path.rsplit("/", 1)[1]
        pieces = si.chunk_text(text, 1000, 150, limit) if text else []
        self.idx.conn.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (path, "", "inbox", name, "Downloads", ext, 1234, 1_700_000_000 * 10**9, status,
                               len(text), len(pieces), "2026-10-12T09:00:00", None))
        hdr = si.header(name, "Downloads")
        for i, p in enumerate(pieces or [""]):
            self.idx.conn.execute("INSERT INTO chunks (path, idx, text) VALUES (?,?,?)", (path, i, f"{hdr}\n{p}" if p else hdr))

    def test_text_comes_back_whole_without_the_header(self):
        self.add("C:/Dl/report.pdf", "ok", TEXT)
        pv = self.idx.preview("C:/Dl/report.pdf")
        self.assertEqual(pv["text"], TEXT)
        self.assertNotIn("File: report.pdf", pv["text"])
        self.assertEqual((pv["status"], pv["truncated"], pv["openable"], pv["note"]), ("ok", False, True, ""))

    def test_long_documents_say_they_are_cut(self):
        self.add("C:/Dl/long.pdf", "ok", TEXT, limit=si.DEFAULTS["max_chunks_per_file"])
        self.idx.conn.execute("UPDATE files SET chunks = ? WHERE path = ?", (si.DEFAULTS["max_chunks_per_file"], "C:/Dl/long.pdf"))
        big = "\n\n".join(TEXT for _ in range(4))
        self.add("C:/Dl/huge.pdf", "ok", big, limit=si.DEFAULTS["max_chunks_per_file"])
        pv = self.idx.preview("C:/Dl/huge.pdf")
        self.assertTrue(pv["truncated"])
        self.assertTrue(big.startswith(pv["text"][:5000]))

    def test_files_without_text_say_why(self):
        self.add("C:/Dl/scan.pdf", "ocr", "Text read from a scan.")
        self.add("C:/Dl/secret.pdf", "locked")
        self.add("C:/Dl/image.iso", "name_only", ext=".iso")
        self.assertIn("OCR", self.idx.preview("C:/Dl/scan.pdf")["note"])
        locked = self.idx.preview("C:/Dl/secret.pdf")
        self.assertEqual((locked["text"], locked["status"]), ("", "locked"))
        self.assertIn("Password-protected", locked["note"])
        iso = self.idx.preview("C:/Dl/image.iso")
        self.assertEqual((iso["text"], iso["openable"]), ("", False))
        self.assertIsNone(self.idx.preview("C:/Dl/unknown.pdf"))

    def test_endpoint_only_answers_for_known_files(self):
        self.add("C:/Dl/report.pdf", "ok", "Hello there.")
        inbox = self.tmp / "inbox"
        inbox.mkdir()
        (inbox / "new.pdf").write_bytes(b"x")
        web_ui.Ctx.cfg, web_ui.Ctx.log = {"inbox_folders": [inbox]}, logging.getLogger("sf-test")

        class H:
            def _send(self, code, body, ctype="application/json"):
                self.code, self.body = code, body
        h = H()
        with mock.patch.object(si, "get", return_value=self.idx):
            web_ui._search_post(h, "/api/search/preview", {"path": "C:/Dl/report.pdf"})
            self.assertEqual((h.code, h.body["ok"], h.body["text"]), (200, True, "Hello there."))
            web_ui._search_post(h, "/api/search/preview", {"path": str(inbox / "new.pdf")})      # arrived, not read yet
            self.assertEqual((h.code, h.body["status"], h.body["text"]), (200, "pending", ""))
            web_ui._search_post(h, "/api/search/preview", {"path": r"C:\Windows\win.ini"})        # not ours to show
            self.assertEqual((h.code, h.body["ok"]), (400, False))


if __name__ == "__main__":
    unittest.main()
