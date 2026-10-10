"""Filing from the Inbox page: the evidence in the journal comes from the server, not from the request."""
import logging
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mover  # noqa: E402
import web_ui  # noqa: E402


class FakeHandler:
    def _send(self, code, body, ctype="application/json"):
        self.code, self.body = code, body


class InboxFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.inbox, self.para = self.tmp / "inbox", self.tmp / "para"
        for d in (self.inbox, self.para / "1-Projects" / "A", self.para / "2-Areas" / "B"):
            d.mkdir(parents=True)
        self.cfg = {"inbox_folders": [self.inbox], "para_root": self.para, "database": self.tmp / "t.db"}
        web_ui.Ctx.cfg, web_ui.Ctx.log = self.cfg, logging.getLogger("sf-test")
        self.cands = [{"folder": "1-Projects/A", "source": "name", "score": None, "rank": 1},
                      {"folder": "2-Areas/B", "source": "similar", "score": 0.8, "rank": 2}]
        sg = mock.Mock()
        sg.suggest.return_value = {"candidates": self.cands}
        patcher = mock.patch.object(web_ui, "_suggester", return_value=sg)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def file(self, name, folder, **claims):
        p = self.inbox / name
        p.write_bytes(b"hello")
        h = FakeHandler()
        web_ui._inbox_post(h, "/api/inbox/file", {"path": str(p), "folder": folder, "size": 5, **claims})
        self.assertTrue(h.body["ok"], h.body)
        return mover.journal(self.cfg)[0]

    def test_claims_from_the_page_are_ignored(self):
        r = self.file("a.txt", "2-Areas\\B\\", source="auto:similar", rank=1, top_folder="2-Areas/B",
                      top_score=0.99, top_source="similar")
        self.assertEqual((r["folder"].strip("\\/").replace("\\", "/"), r["source"], r["rank"]),
                         ("2-Areas/B", "similar", 2))
        self.assertEqual((r["top_folder"], r["top_source"], r["top_score"]), ("1-Projects/A", "name", None))

    def test_agreeing_with_the_first_suggestion(self):
        r = self.file("b.txt", "1-Projects/A")
        self.assertEqual((r["source"], r["rank"], r["top_folder"], r["top_source"]),
                         ("name", 1, "1-Projects/A", "name"))

    def test_a_folder_that_was_not_suggested_is_a_manual_choice(self):
        (self.para / "3-Resources" / "C").mkdir(parents=True)
        r = self.file("c.txt", "3-Resources/C", source="name", rank=1)
        self.assertEqual((r["source"], r["rank"], r["top_folder"]), ("manual", 0, "1-Projects/A"))


if __name__ == "__main__":
    unittest.main()
