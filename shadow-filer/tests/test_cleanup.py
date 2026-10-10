"""cleanup.recheck (the last look before a delete) and the cloud-only rule."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cleanup  # noqa: E402
import shadow_agent as sa  # noqa: E402
import suggest  # noqa: E402


class RecheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.inbox, self.para = self.tmp / "inbox", self.tmp / "para"
        self.inbox.mkdir()
        self.para.mkdir()
        self.cfg = {"inbox_folders": [self.inbox], "para_root": self.para}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def item(self, p: Path, category="installer", level="likely", related=None):
        st = p.stat()
        return {"path": str(p), "name": p.name, "is_dir": False, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "category": category, "level": level, "related": str(related) if related else None}

    def test_unchanged_recommendation_still_holds(self):
        p = self.inbox / "setup.exe"
        p.write_bytes(b"x" * 10)
        self.assertIsNone(cleanup.recheck(self.item(p), self.cfg))

    def test_keep_items_and_files_outside_the_inbox_are_refused(self):
        p = self.inbox / "fw.bin"
        p.write_bytes(b"x")
        self.assertIsNotNone(cleanup.recheck(self.item(p, "firmware_or_image", "keep"), self.cfg))
        q = self.para / "doc.pdf"
        q.write_bytes(b"x")
        self.assertIsNotNone(cleanup.recheck(self.item(q), self.cfg))
        self.assertIsNotNone(cleanup.recheck({**self.item(p, level="likely"), "path": str(self.inbox)}, self.cfg))

    def test_changed_or_missing_files_are_refused(self):
        p = self.inbox / "setup.exe"
        p.write_bytes(b"x" * 10)
        it = self.item(p)
        p.write_bytes(b"y" * 11)
        self.assertIsNotNone(cleanup.recheck(it, self.cfg))
        p.unlink()
        self.assertIsNotNone(cleanup.recheck(it, self.cfg))

    def test_duplicate_needs_the_kept_copy_to_still_be_identical(self):
        p, kept = self.inbox / "a.pdf", self.para / "a.pdf"
        p.write_bytes(b"same")
        kept.write_bytes(b"same")
        it = self.item(p, "duplicate_of_filed", "safe", kept)
        self.assertIsNone(cleanup.recheck(it, self.cfg))
        self.assertIsNotNone(cleanup.recheck({**it, "related": str(p)}, self.cfg))   # "kept copy" is itself
        kept.write_bytes(b"diff")
        self.assertIsNotNone(cleanup.recheck(it, self.cfg))
        kept.unlink()
        self.assertIsNotNone(cleanup.recheck(it, self.cfg))


class CloudOnlyTest(unittest.TestCase):
    """A cloud-only placeholder must never be opened: opening it downloads it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.p = self.tmp / "a.pdf"
        self.p.write_bytes(b"%PDF-1.4 not really")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_attribute_bits(self):
        self.assertFalse(sa.is_cloud_only(self.p))
        self.assertFalse(sa.is_cloud_only(self.tmp / "missing"))
        for bit in (0x1000, 0x40000, 0x400000):
            with mock.patch.object(sa.os, "stat", return_value=mock.Mock(st_file_attributes=bit | 0x20)):
                self.assertTrue(sa.is_cloud_only(self.p))

    def test_prediction_path_does_not_open_placeholders(self):
        cfg = {"inbox_folders": [self.tmp], "ignore_patterns": [], "hash_max_mb": 200,
               "extraction": {"max_chars": 100, "max_pdf_pages": 1}}
        boom = mock.Mock(side_effect=AssertionError("opened a cloud-only file"))
        with mock.patch.object(sa, "is_cloud_only", return_value=True), \
                mock.patch.object(sa, "_extract_text", boom), mock.patch.object(sa, "sha256_of", boom), \
                mock.patch.object(sa, "predict", boom), mock.patch("builtins.open", boom):
            self.assertEqual(sa.extract_text(self.p, cfg), "")
            self.assertFalse(sa.is_encrypted_pdf(self.p))
            sa._process_inbox_file(self.p, cfg, None, mock.Mock())

    def test_inbox_listing_reports_when_a_file_arrived(self):
        old = 1_000_000_000
        os.utime(self.p, (old, old))   # modified date from 2001, as an unzip or a copy would keep it
        (it,) = suggest.list_inbox({"inbox_folders": [self.tmp]}, {}, lambda p: False)
        self.assertEqual(int(it["mtime"]), old)
        if os.name == "nt":            # creation time is when it landed here
            self.assertGreater(it["added"], old + 86400)


if __name__ == "__main__":
    unittest.main()
