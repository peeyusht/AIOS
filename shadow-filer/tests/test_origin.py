"""Download origin (Zone.Identifier) as a filing signal, and the mover keeping that mark across drives."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import autofile  # noqa: E402
import mover  # noqa: E402
import origin  # noqa: E402
import suggest  # noqa: E402

PORTAL, MAIL = "https://portal.payroll.example/slips/get?id=7", "https://mail.example.com/attachment/1"


def mark(path: Path, host_url=None, referrer=None, raw=None):
    text = raw if raw is not None else "[ZoneTransfer]\r\nZoneId=3\r\n" + (
        f"ReferrerUrl={referrer}\r\n" if referrer else "") + (f"HostUrl={host_url}\r\n" if host_url else "")
    with open(str(path) + ":Zone.Identifier", "w", encoding="utf-8", newline="") as f:
        f.write(text)


@unittest.skipUnless(os.name == "nt", "Zone.Identifier is a Windows (NTFS) feature")
class OriginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.inbox, self.para = self.tmp / "inbox", self.tmp / "para"
        for d in (self.inbox, self.para / "2-Areas" / "Payroll", self.para / "2-Areas" / "Finance",
                  self.para / "1-Projects" / "Acme"):
            d.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new(self, folder: Path, name: str, **kw) -> Path:
        p = folder / name
        p.write_bytes(name.encode())
        if kw:
            mark(p, **kw)
        return p

    def test_read(self):
        p = self.new(self.inbox, "slip.pdf", host_url="https://WWW.Portal.Payroll.Example:8443/a/b?c=d",
                     referrer="https://www.intranet.example/home")
        self.assertEqual(origin.read(str(p)), {"host": "portal.payroll.example", "referrer": "intranet.example"})
        self.assertIsNone(origin.read(str(self.new(self.inbox, "plain.txt"))))
        self.assertIsNone(origin.read(str(self.inbox / "missing.txt")))
        self.assertIsNone(origin.read(str(self.new(self.inbox, "local.txt", raw="[ZoneTransfer]\nZoneId=3\n"))))
        self.assertIsNone(origin.read(str(self.new(self.inbox, "junk.txt", raw="HostUrl=about:internet\n\x00garbage"))))
        self.assertEqual(p.read_bytes(), b"slip.pdf")   # the file itself is untouched

    def test_cloud_only_files_are_not_opened(self):
        p = self.new(self.inbox, "cloud.pdf", host_url=PORTAL)
        with mock.patch.object(origin.os, "stat", return_value=mock.Mock(st_file_attributes=0x400000)), \
                mock.patch("builtins.open", side_effect=AssertionError("opened a cloud-only file")):
            self.assertIsNone(origin.read(str(p)))

    def test_owners_need_enough_files_and_one_clear_folder(self):
        filed = ([("portal", "2-Areas/Payroll")] * 4 + [("portal", "2-Areas/Finance")]      # 4 of 5 = 80%
                 + [("mail", "2-Areas/Finance")] * 5 + [("mail", "1-Projects/Acme")] * 5       # spread
                 + [("rare", "1-Projects/Acme")] * 2                                             # too few
                 + [(None, "1-Projects/Acme")] * 9)
        own = origin.owners(filed)
        self.assertEqual(own, {"portal": {"folder": "2-Areas/Payroll", "files": 4, "total": 5, "share": 0.8}})
        self.assertIn("rare", origin.owners(filed, min_files=2))
        self.assertNotIn("portal", origin.owners(filed, share=0.9))

    def suggester(self):
        examples = []
        for i in range(4):
            examples.append((self.new(self.para / "2-Areas" / "Payroll", f"slip{i}.pdf", host_url=PORTAL), "2-Areas/Payroll"))
        for i, folder in enumerate(["2-Areas/Finance", "1-Projects/Acme", "2-Areas/Payroll", "2-Areas/Finance"]):
            examples.append((self.new(self.para / folder, f"mail{i}.pdf", host_url=MAIL), folder))
        examples.append((self.new(self.para / "1-Projects" / "Acme", "nomark.pdf"), "1-Projects/Acme"))
        dests = mock.Mock()
        dests.get.return_value = ["1-Projects/Acme", "2-Areas/Finance", "2-Areas/Payroll"]
        index = mock.Mock(docvecs={})
        index.labelled.return_value = [(str(p), label, None) for p, label in examples]
        index.fingerprint.return_value = None
        return suggest.Suggester({"rules": [], "destination_depth": 2}, index, dests, None)

    def test_file_from_a_consistent_website_is_suggested_its_folder(self):
        sg = self.suggester()
        res = sg.suggest(str(self.new(self.inbox, "October statement.pdf", host_url=PORTAL)))
        self.assertEqual(res["origin"]["host"], "portal.payroll.example")
        top = res["candidates"][0]
        self.assertEqual((top["folder"], top["source"], top["rank"], top["score"]), ("2-Areas/Payroll", "origin", 1, None))
        self.assertEqual(top["why"], "4 of your 4 files from portal.payroll.example are filed here")
        for name, kw in (("from mail.pdf", {"host_url": MAIL}), ("no mark.pdf", {}),
                         ("other site.pdf", {"host_url": "https://unknown.example/x"})):
            res = sg.suggest(str(self.new(self.inbox, name, **kw)))
            self.assertEqual([c for c in res["candidates"] if c["source"] == "origin"], [], name)
        self.assertEqual(res["origin"], {"host": "unknown.example", "referrer": None})

    def test_a_rule_still_comes_first_and_origin_is_never_auto_filed(self):
        sg = self.suggester()
        sg.cfg["rules"] = [{"name": "pdfs", "extensions": [".pdf"], "destination": "2-Areas/Finance"}]
        res = sg.suggest(str(self.new(self.inbox, "slip-nov.pdf", host_url=PORTAL)))
        self.assertEqual([(c["folder"], c["source"]) for c in res["candidates"]],
                         [("2-Areas/Finance", "rule"), ("2-Areas/Payroll", "origin")])
        self.assertNotIn("origin", autofile.ALLOWED_SOURCES)
        cfg = {"database": self.tmp / "t.db"}
        c = mover._conn(cfg["database"])
        c.executemany("INSERT INTO moves (ts, src, dest, size, sha256, folder, source, rank, top_folder, top_source, "
                      "status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      [(f"2026-01-01T00:00:{i:02d}", "s", "d", 1, "x", "2-Areas/Payroll", "origin", 1,
                        "2-Areas/Payroll", "origin", "moved") for i in range(30)])
        c.commit()
        c.close()
        now = time.time()
        d = autofile.decide(cfg, {"path": "x", "mtime": now - 9999, "added": now - 9999},
                            {"candidates": [{"folder": "2-Areas/Payroll", "source": "origin", "score": None, "exists": True}]},
                            autofile.trust(cfg), {}, now)
        self.assertEqual((d["auto"], d["why"]), (False, "website matches are suggestions only"))

    def cross_drive(self, p):
        real = mover._no_replace_rename

        def other_drive(a, b):
            if a == str(p):
                raise OSError(18, "Invalid cross-device link")
            return real(a, b)
        return mock.patch.object(mover, "_no_replace_rename", other_drive)

    def test_cross_drive_move_keeps_the_mark_and_the_dates(self):
        cfg = {"inbox_folders": [self.inbox], "para_root": self.para, "database": self.tmp / "t.db"}
        p = self.new(self.inbox, "slip-dec.pdf", host_url=PORTAL, referrer="https://intranet.example/")
        old = 1_600_000_000
        os.utime(p, (old, old))
        with self.cross_drive(p):
            res = mover.move(cfg, str(p), "2-Areas/Payroll")
        dest = Path(res["dest"])
        self.assertFalse(p.exists())
        self.assertEqual(origin.read(str(dest)), {"host": "portal.payroll.example", "referrer": "intranet.example"})
        self.assertEqual(int(dest.stat().st_mtime), old)
        self.assertEqual(dest.read_bytes(), b"slip-dec.pdf")
        back = Path(mover.undo(cfg, res["id"])["restored"])        # undo verifies the content hash first
        self.assertEqual(origin.read(str(back))["host"], "portal.payroll.example")

    def test_cross_drive_move_of_a_file_without_a_mark(self):
        cfg = {"inbox_folders": [self.inbox], "para_root": self.para, "database": self.tmp / "t.db"}
        p = self.new(self.inbox, "plain.pdf")
        with self.cross_drive(p):
            dest = Path(mover.move(cfg, str(p), "1-Projects/Acme")["dest"])
        self.assertIsNone(origin.read(str(dest)))
        self.assertEqual(dest.read_bytes(), b"plain.pdf")


if __name__ == "__main__":
    unittest.main()
