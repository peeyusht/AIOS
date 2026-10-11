"""Work journal: a dated record of what arrived, what was filed where, what was deleted and what was worked on."""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import journal  # noqa: E402
import mover  # noqa: E402

TODAY = date(2026, 10, 11)


def ts(day: str, hm: str = "10:00") -> float:
    return datetime.fromisoformat(f"{day}T{hm}:00").timestamp()


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.inbox, self.para = self.tmp / "inbox", self.tmp / "para"
        self.acme = self.para / "1-Projects" / "Acme"
        (self.acme / "drafts").mkdir(parents=True)
        (self.para / "2-Areas" / "Finance").mkdir(parents=True)
        self.inbox.mkdir()
        self.cfg = {"inbox_folders": [self.inbox], "para_root": self.para, "database": self.tmp / "t.db",
                    "destination_depth": 2}
        journal._recorded["at"] = 0
        c = mover._conn(self.cfg["database"])       # creates the moves table as the agent would
        c.executescript("""
            CREATE TABLE predictions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, path TEXT NOT NULL,
                filename TEXT NOT NULL, size INTEGER, sha256 TEXT, method TEXT NOT NULL, predicted TEXT,
                confidence REAL, reason TEXT, actual TEXT, actual_ts TEXT);
            CREATE TABLE cleanup_action (ts TEXT, path TEXT, size INTEGER, category TEXT, mode TEXT, result TEXT);
        """)
        c.commit()
        c.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sql(self, q, *a):
        c = sqlite3.connect(self.cfg["database"])
        c.execute(q, a)
        c.commit()
        c.close()

    def doc(self, p: Path, day: str):
        p.write_text("x", encoding="utf-8")
        os.utime(p, (ts(day), ts(day)))
        return p

    def build(self, days=30):
        journal._recorded["at"] = 0
        return journal.build(self.cfg, days, today=TODAY)

    def day(self, rep, d):
        return next(x for x in rep["days"] if x["date"] == d)

    def test_arrived_filed_deleted(self):
        gone = str(self.inbox / "gone.pdf")
        self.sql("INSERT INTO predictions (ts, path, filename, size, method, predicted) VALUES (?,?,?,?,?,?)",
                 "2026-10-09T09:30:00", gone, "gone.pdf", 10, "model", "2-Areas/Finance")
        self.sql("INSERT INTO predictions (ts, path, filename, size, method, predicted) VALUES (?,?,?,?,?,?)",
                 "2026-10-10T08:00:00", gone, "gone.pdf", 10, "model", "2-Areas/Finance")     # seen again: one arrival
        self.sql("INSERT INTO predictions (ts, path, filename, size, method, actual, actual_ts) VALUES (?,?,?,?,?,?,?)",
                 "2026-10-08T09:00:00", str(self.inbox / "byhand.pdf"), "byhand.pdf", 5, "model",
                 "2-Areas/Finance", "2026-10-10T11:00:00")
        for i, (name, source, status, undone) in enumerate((("a.pdf", "name", "moved", None),
                                                           ("b.pdf", "auto:origin", "undone", "2026-10-11T09:00:00"),
                                                           ("c.pdf", "manual", "pending", None))):
            self.sql("INSERT INTO moves (ts, src, dest, size, folder, source, rank, status, undone_ts) VALUES (?,?,?,?,?,?,1,?,?)",
                     f"2026-10-10T12:0{i}:00", str(self.inbox / name), str(self.acme / name), 100, "1-Projects/Acme",
                     source, status, undone)
        self.sql("INSERT INTO cleanup_action VALUES (?,?,?,?,?,?)", "2026-10-10T20:00:00", str(self.inbox / "old.zip"),
                 5000, "duplicate", "recycle", "deleted")
        self.sql("INSERT INTO cleanup_action VALUES (?,?,?,?,?,?)", "2026-10-10T20:01:00", str(self.inbox / "kept.zip"),
                 9000, "duplicate", "recycle", "skipped")
        rep = self.build()
        d10 = self.day(rep, "2026-10-10")
        self.assertEqual([(a["name"], a["still_there"], a["time"]) for a in d10["arrived"]], [("gone.pdf", False, "08:00")])
        self.assertEqual([(f["name"], f["folder"], f["how"], f["undone"]) for f in d10["filed"]],
                         [("b.pdf", "1-Projects/Acme", "auto", True), ("a.pdf", "1-Projects/Acme", "inbox", False),
                          ("byhand.pdf", "2-Areas/Finance", "hand", False)])
        self.assertEqual([(x["name"], x["size"]) for x in d10["deleted"]], [("old.zip", 5000)])
        self.assertEqual([u["name"] for u in self.day(rep, "2026-10-11")["undone"]], ["b.pdf"])
        self.assertEqual({k: rep["totals"][k] for k in ("filed", "auto_filed", "undone", "deleted", "deleted_bytes")},
                         {"filed": 3, "auto_filed": 1, "undone": 1, "deleted": 1, "deleted_bytes": 5000})
        # the undone auto-move does not count for its folder
        self.assertEqual([(g["folder"], g["filed"]) for g in rep["folders"]], [("1-Projects/Acme", 1), ("2-Areas/Finance", 1)])
        self.assertIn("Filed a.pdf -> 1-Projects/Acme", rep["text"])
        self.assertIn("Filed b.pdf -> 1-Projects/Acme (automatically) (undone later)", rep["text"])
        self.assertIn("Deleted 1 file (4.9 KB)", rep["text"])

    def test_arrival_is_dated_by_the_file_while_it_is_there(self):
        p = self.doc(self.inbox / "here.pdf", "2026-10-03")
        self.sql("INSERT INTO predictions (ts, path, filename, size, method) VALUES (?,?,?,?,?)",
                 "2026-10-10T08:00:00", str(p), "here.pdf", 1, "model")       # noticed late, by a catch-up run
        a = [x for d in self.build()["days"] for x in d["arrived"]]
        self.assertEqual(len(a), 1)
        self.assertTrue(a[0]["still_there"])
        self.assertNotEqual(a[0]["ts"][:10], "2026-10-10")     # the file's own date (its creation, here: today's run)

    def test_worked_on_remembers_earlier_days(self):
        p = self.doc(self.acme / "drafts" / "plan.docx", "2026-10-06")
        self.doc(self.para / "2-Areas" / "Finance" / "budget.xlsx", "2026-10-06")
        c = journal._conn(self.cfg["database"])       # as recorded when the agent looked on the 6th and the 8th
        c.executemany("INSERT INTO journal_touch VALUES (?,?,?,?,?)",
                      [("2026-10-06", str(p), "1-Projects/Acme", "plan.docx", "added"),
                       ("2026-10-08", str(p), "1-Projects/Acme", "plan.docx", "changed"),
                       ("2025-01-01", str(p), "1-Projects/Acme", "plan.docx", "changed")])
        c.commit()
        c.close()
        rep = self.build()
        self.assertEqual([(w["folder"], [f["kind"] for f in w["files"]]) for w in self.day(rep, "2026-10-08")["worked"]],
                         [("1-Projects/Acme", ["changed"])])
        self.assertEqual(self.day(rep, "2026-10-06")["worked"][0]["folder"], "1-Projects/Acme")
        acme = next(g for g in rep["folders"] if g["folder"] == "1-Projects/Acme")
        self.assertGreaterEqual(acme["days"], 2)
        c = sqlite3.connect(self.cfg["database"])     # notes older than a year are dropped
        self.assertEqual(c.execute("SELECT COUNT(*) FROM journal_touch WHERE day < '2025-10-01'").fetchone()[0], 0)
        c.close()

    def test_touches_are_noted_once_and_files_are_untouched(self):
        self.doc(self.acme / "notes.docx", "2026-10-09")
        before = sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in self.para.rglob("*"))
        journal._recorded["at"] = 0
        first = journal.record_touches(self.cfg, today=TODAY)
        journal._recorded["at"] = 0
        again = journal.record_touches(self.cfg, today=TODAY)
        self.assertEqual((first, again), (1, 0))
        self.assertEqual(journal.record_touches(self.cfg, today=TODAY), 0)     # and not walked again within minutes
        self.assertEqual(sorted((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in self.para.rglob("*")), before)

    def test_a_filed_file_is_not_also_worked_on(self):
        p = self.doc(self.acme / "a.pdf", "2026-10-10")
        self.sql("INSERT INTO moves (ts, src, dest, size, folder, source, rank, status) VALUES (?,?,?,?,?,?,1,'moved')",
                 datetime.fromtimestamp(os.stat(p).st_ctime).isoformat(timespec="seconds"), str(self.inbox / "a.pdf"),
                 str(p), 1, "1-Projects/Acme", "name")
        rep = self.build()
        self.assertEqual(sum(d["counts"]["worked_files"] for d in rep["days"]), 0)
        self.assertEqual(rep["totals"]["filed"], 1)

    def test_range_and_empty(self):
        self.sql("INSERT INTO cleanup_action VALUES (?,?,?,?,?,?)", "2026-09-01T20:00:00", "C:/Dl/x.zip", 1, "d", "recycle", "deleted")
        self.assertEqual(self.build(7)["days"], [])
        self.assertEqual(len(self.build(60)["days"]), 1)
        self.assertEqual((self.build(7)["from"], self.build(7)["to"]), ("2026-10-05", "2026-10-11"))
        self.assertEqual(journal.build(self.cfg, 99999, today=TODAY)["days_asked"], journal.MAX_DAYS)


if __name__ == "__main__":
    unittest.main()
