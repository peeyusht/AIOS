"""Inbox › New folder: one empty folder under an existing PARA folder, nothing else."""
import logging
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mover  # noqa: E402
import shadow_agent as sa  # noqa: E402
import web_ui  # noqa: E402


class NewFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.inbox, self.para = self.tmp / "inbox", self.tmp / "para"
        for d in (self.inbox, self.para / "1-Projects" / "A" / "deep", self.para / "2-Areas",
                  self.para / "4-Archives" / "Old", self.para / ".hidden"):
            d.mkdir(parents=True)
        self.cfg = {"inbox_folders": [self.inbox], "para_root": self.para, "database": self.tmp / "t.db",
                    "destination_depth": 2, "exclude_destinations": ["4-Archives", "2-Areas/Private"]}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tree(self):
        return sorted(p.relative_to(self.para).as_posix() for p in self.para.rglob("*"))

    def test_parents_are_existing_folders_above_destination_depth(self):
        self.assertEqual(mover.folder_parents(self.cfg), ["1-Projects", "2-Areas"])
        self.assertEqual(mover.folder_parents({**self.cfg, "destination_depth": 3}),
                         ["1-Projects", "1-Projects/A", "2-Areas"])
        self.assertEqual(mover.folder_parents({**self.cfg, "destination_depth": 1}), [])

    def test_create_then_file_into_it(self):
        res = mover.make_folder(self.cfg, "1-Projects", "  GR  One ")
        self.assertEqual(res, {"ok": True, "folder": "1-Projects/GR One"})
        self.assertEqual(list((self.para / "1-Projects" / "GR One").iterdir()), [])
        self.assertIn("1-Projects/GR One", sa.Destinations(self.cfg).get())
        p = self.inbox / "a.txt"
        p.write_bytes(b"hello")
        mover.move(self.cfg, str(p), res["folder"])
        self.assertEqual((self.para / "1-Projects" / "GR One" / "a.txt").read_bytes(), b"hello")

    def test_refuses_everything_else_and_changes_nothing(self):
        (self.para / "2-Areas" / "report.txt").write_bytes(b"x")
        before = self.tree()
        bad = [("1-Projects", "A"), ("1-Projects", "a"),               # exists (any letter case)
               ("2-Areas", "REPORT.TXT"),                              # a file has that name
               ("1-Projects", ""), ("1-Projects", "   "), ("1-Projects", "x" * 81),
               ("1-Projects", "a/b"), ("1-Projects", "a\\b"), ("1-Projects", ".."), ("1-Projects", "..\\..\\x"),
               ("1-Projects", "C:evil"), ("1-Projects", "what?"), ("1-Projects", "tab\tname\x01"),
               ("1-Projects", ".git"), ("1-Projects", "name."), ("1-Projects", "CON"), ("1-Projects", "lpt1.txt"),
               ("", "New"), ("..", "New"), ("1-Projects/..", "New"), ("1-Projects/A", "New"),   # not a parent
               ("3-Missing", "New"), (".hidden", "New"), (str(self.tmp), "New"),
               ("4-Archives", "New"), ("2-Areas", "Private")]          # excluded in Settings
        for parent, name in bad:
            with self.assertRaises(mover.MoveError, msg=f"{parent!r} / {name!r}"):
                mover.make_folder(self.cfg, parent, name)
        self.assertEqual(self.tree(), before)
        self.assertEqual(list(self.tmp.glob("New")), [])

    def test_api_creates_and_refreshes_destinations(self):
        dests = sa.Destinations(self.cfg)
        dests.get()
        web_ui.Ctx.cfg, web_ui.Ctx.dests, web_ui.Ctx.log = self.cfg, dests, logging.getLogger("sf-test")
        h = mock.Mock()
        web_ui._inbox_post(h, "/api/inbox/mkdir", {"parent": "2-Areas", "name": "Health"})
        h._send.assert_called_with(200, {"ok": True, "folder": "2-Areas/Health"})
        self.assertIn("2-Areas/Health", dests.get())
        web_ui._inbox_post(h, "/api/inbox/mkdir", {"parent": "2-Areas", "name": "health"})
        code, body = h._send.call_args[0]
        self.assertEqual((code, body["ok"]), (200, False))
        web_ui._inbox_post(h, "/api/inbox/mkdir", {"parent": None, "name": ["x"]})
        self.assertFalse(h._send.call_args[0][1]["ok"])


if __name__ == "__main__":
    unittest.main()
