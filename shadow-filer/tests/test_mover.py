"""mover.py on throwaway folders: never overwrite, verified cross-drive copy, rollback, journal, undo."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mover  # noqa: E402


class MoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.inbox, self.para = self.tmp / "inbox", self.tmp / "para"
        (self.para / "1-Projects" / "A").mkdir(parents=True)
        self.inbox.mkdir()
        self.cfg = {"inbox_folders": [self.inbox], "para_root": self.para, "database": self.tmp / "t.db"}
        self.dest = self.para / "1-Projects" / "A"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, name="a.txt", data=b"hello"):
        p = self.inbox / name
        p.write_bytes(data)
        return p

    def rows(self):
        return mover.journal(self.cfg)

    def cross_drive(self, src):
        """Make the first rename of `src` fail the way a move to another drive does."""
        real = mover._no_replace_rename

        def fake(a, b):
            if a == str(src):
                raise OSError(18, "Invalid cross-device link")
            return real(a, b)
        return mock.patch.object(mover, "_no_replace_rename", fake)

    def test_move_then_undo(self):
        p = self.make()
        res = mover.move(self.cfg, str(p), "1-Projects/A", {"size": 5, "top_source": "similar"})
        self.assertTrue(res["ok"])
        self.assertFalse(p.exists())
        self.assertEqual((self.dest / "a.txt").read_bytes(), b"hello")
        row = self.rows()[0]
        self.assertEqual((row["status"], row["top_source"], row["size"]), ("moved", "similar", 5))
        back = mover.undo(self.cfg, res["id"])
        self.assertEqual(Path(back["restored"]), p)
        self.assertEqual(p.read_bytes(), b"hello")
        self.assertFalse((self.dest / "a.txt").exists())
        self.assertEqual(self.rows()[0]["status"], "undone")
        with self.assertRaises(mover.MoveError):
            mover.undo(self.cfg, res["id"])

    def test_identical_copy_is_refused(self):
        p = self.make()
        (self.dest / "a.txt").write_bytes(b"hello")
        with self.assertRaises(mover.MoveError):
            mover.move(self.cfg, str(p), "1-Projects/A")
        self.assertTrue(p.exists())
        self.assertEqual(self.rows(), [])

    def test_different_file_with_same_name_is_never_overwritten(self):
        p = self.make()
        (self.dest / "a.txt").write_bytes(b"other")
        res = mover.move(self.cfg, str(p), "1-Projects/A")
        self.assertTrue(res["renamed"])
        self.assertEqual((self.dest / "a.txt").read_bytes(), b"other")
        self.assertEqual((self.dest / "a (2).txt").read_bytes(), b"hello")

    def test_refuses_sources_and_destinations_outside_the_rules(self):
        p = self.make()
        sub = self.inbox / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_bytes(b"x")
        outside = self.tmp / "elsewhere.txt"
        outside.write_bytes(b"x")
        for src, folder in ((sub / "deep.txt", "1-Projects/A"), (outside, "1-Projects/A"), (sub, "1-Projects/A"),
                            (p, "../inbox"), (p, "1-Projects/Missing"), (p, ""), (p, "1-Projects/A/../../..")):
            with self.assertRaises(mover.MoveError, msg=f"{src} -> {folder}"):
                mover.move(self.cfg, str(src), folder)
        with self.assertRaises(mover.MoveError):
            mover.move(self.cfg, str(p), "1-Projects/A", {"size": 999})  # changed since it was suggested
        self.assertTrue(p.exists())
        self.assertEqual(self.rows(), [])

    def test_cross_drive_copy_is_verified_and_leaves_no_temp_file(self):
        p = self.make(data=os.urandom(300_000))
        data = p.read_bytes()
        with self.cross_drive(p):
            mover.move(self.cfg, str(p), "1-Projects/A")
        self.assertFalse(p.exists())
        self.assertEqual((self.dest / "a.txt").read_bytes(), data)
        self.assertEqual([f.name for f in self.dest.iterdir()], ["a.txt"])

    def test_cross_drive_bad_copy_moves_nothing(self):
        p = self.make()
        with self.cross_drive(p), mock.patch.object(mover.shutil, "copy2",
                                                    lambda a, b: Path(b).write_bytes(b"corrupt")):
            with self.assertRaises(mover.MoveError):
                mover.move(self.cfg, str(p), "1-Projects/A")
        self.assertEqual(p.read_bytes(), b"hello")
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertEqual(self.rows(), [])

    def test_cross_drive_rolls_back_when_the_original_is_in_use(self):
        p = self.make()
        real = os.remove

        def locked(path):
            if str(path) == str(p):
                e = PermissionError(13, "in use")
                e.winerror = 32
                raise e
            return real(path)
        with self.cross_drive(p), mock.patch.object(mover.os, "remove", locked):
            with self.assertRaises(mover.MoveError):
                mover.move(self.cfg, str(p), "1-Projects/A")
        self.assertEqual(p.read_bytes(), b"hello")
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertEqual(self.rows(), [])

    def test_undo_refuses_when_the_filed_copy_changed(self):
        p = self.make()
        res = mover.move(self.cfg, str(p), "1-Projects/A")
        (self.dest / "a.txt").write_bytes(b"HELLO")
        with self.assertRaises(mover.MoveError):
            mover.undo(self.cfg, res["id"])
        self.assertEqual((self.dest / "a.txt").read_bytes(), b"HELLO")
        self.assertEqual(self.rows()[0]["status"], "moved")

    def test_undo_does_not_overwrite_a_new_file_in_the_inbox(self):
        p = self.make()
        res = mover.move(self.cfg, str(p), "1-Projects/A")
        p.write_bytes(b"newer download")
        back = mover.undo(self.cfg, res["id"])
        self.assertEqual(Path(back["restored"]).name, "a (2).txt")
        self.assertEqual(p.read_bytes(), b"newer download")

    def test_journal_is_written_before_the_file_moves(self):
        p = self.make()
        seen = {}
        real = mover._transfer

        def spy(src, dest, digest):
            seen["status"] = self.rows()[0]["status"]
            return real(src, dest, digest)
        with mock.patch.object(mover, "_transfer", spy):
            mover.move(self.cfg, str(p), "1-Projects/A")
        self.assertEqual(seen["status"], "pending")
        self.assertEqual(self.rows()[0]["status"], "moved")

    def pending(self, src, dest, size=5):
        c = mover._conn(self.cfg["database"])
        c.execute("INSERT INTO moves (ts, src, dest, size, sha256, folder, source, rank, status) "
                  "VALUES ('2026-01-01T00:00:00', ?, ?, ?, 'x', '1-Projects/A', 'manual', 0, 'pending')",
                  (str(src), str(dest), size))
        c.commit()
        c.close()

    def test_recover_settles_interrupted_moves_without_removing_your_files(self):
        moved = self.dest / "moved.txt"           # crash after the move, before the journal was completed
        moved.write_bytes(b"hello")
        self.pending(self.inbox / "moved.txt", moved)
        untouched = self.make("untouched.txt")    # crash before / during the copy
        partial = self.dest / "untouched.txt.shadowfiler-partial"
        partial.write_bytes(b"hel")
        self.pending(untouched, self.dest / "untouched.txt")
        both_src = self.make("both.txt")          # crash between "copy in place" and "remove original"
        both_dest = self.dest / "both.txt"
        both_dest.write_bytes(b"hello")
        self.pending(both_src, both_dest)

        self.assertEqual(mover.recover(self.cfg), 3)
        by_dest = {Path(r["dest"]).name: r["status"] for r in self.rows()}
        self.assertEqual(by_dest, {"moved.txt": "moved", "both.txt": "interrupted"})
        self.assertFalse(partial.exists())
        self.assertTrue(untouched.exists() and moved.exists() and both_src.exists() and both_dest.exists())
        self.assertEqual(mover.recover(self.cfg), 0)


if __name__ == "__main__":
    unittest.main()
