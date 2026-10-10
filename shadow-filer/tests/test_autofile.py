"""autofile.py: what makes a folder proven, and when a file would be filed on its own."""
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import autofile  # noqa: E402
import mover  # noqa: E402

F = "1-Projects/A"


class AutofileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.cfg = {"database": self.tmp / "t.db"}
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add(self, count=1, folder=F, top=F, top_source="similar", source=None, rank=1, status="moved",
            undone_ts=None):
        c = mover._conn(self.cfg["database"])
        for _ in range(count):
            self.n += 1
            c.execute("INSERT INTO moves (ts, src, dest, size, sha256, folder, source, rank, top_folder, "
                      "top_source, status, undone_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (f"2026-01-01T00:{self.n // 60:02d}:{self.n % 60:02d}", "s", "d", 1, "x", folder,
                       source or top_source, rank, top, top_source, status, undone_ts))
        c.commit()
        c.close()

    def decide(self, source="similar", score=0.97, folder=F, age=3600, added=None, hints=None, duplicate=None):
        now = time.time()
        item = {"path": "C:/in/x.pdf", "mtime": now - age, "added": now - age if added is None else added}
        sug = {"candidates": [{"folder": folder, "source": source, "score": score, "exists": True}],
               "duplicate": duplicate}
        return autofile.decide(self.cfg, item, sug, autofile.trust(self.cfg), hints or {}, now)

    def test_the_bar_cannot_be_lowered(self):
        self.cfg["autofile"] = {"enabled": True, "min_decisions": 1, "min_rate": 0.1, "window": 2,
                                "min_score": 0, "delay_minutes": 0}
        s = autofile.settings(self.cfg)
        self.assertEqual((s["min_decisions"], s["min_rate"], s["window"]), (20, 0.9, 20))
        self.assertEqual((s["min_score"], s["delay_minutes"]), (0.5, 1))
        self.cfg["autofile"] = {"enabled": "yes", "min_decisions": "lots", "min_rate": None}
        s = autofile.settings(self.cfg)
        self.assertEqual((s["enabled"], s["min_decisions"], s["min_rate"]), (False, 20, 0.9))
        self.cfg["autofile"] = {"min_decisions": 50, "min_rate": 0.97}   # stricter is fine
        s = autofile.settings(self.cfg)
        self.assertEqual((s["min_decisions"], s["min_rate"], s["window"]), (50, 0.97, 50))

    def test_proven_needs_twenty_decisions(self):
        self.add(19)
        self.assertFalse(autofile.trust(self.cfg)[(F, "similar")]["proven"])
        self.assertFalse(self.decide()["auto"])
        self.add(1)
        t = autofile.trust(self.cfg)[(F, "similar")]
        self.assertEqual((t["proven"], t["decisions"], t["needed"]), (True, 20, 0))
        self.assertTrue(self.decide()["auto"])

    def test_disagreements_and_undone_moves_count_against(self):
        self.add(26)
        self.add(2, folder="2-Areas/B", source="manual", rank=0)   # you filed elsewhere
        self.add(2, status="undone")                               # you filed there, then took it back
        t = autofile.trust(self.cfg)[(F, "similar")]
        self.assertEqual((t["decisions"], t["agreed"], t["proven"]), (30, 26, False))
        self.assertIn("87%", self.decide()["why"])

    def test_trust_is_per_kind_of_suggestion(self):
        self.add(25, top_source="similar")
        self.assertTrue(self.decide("similar")["auto"])
        self.assertFalse(self.decide("name", score=None)["auto"])
        self.assertFalse(self.decide("rule", score=None)["auto"])
        self.add(20, top_source="name")
        self.assertTrue(self.decide("name", score=None)["auto"])

    def test_undoing_an_auto_move_wipes_the_folder(self):
        self.add(30, top_source="similar")
        self.add(30, top_source="name")
        self.add(1, source="auto:similar", status="undone", undone_ts="2026-02-01T00:00:00")
        tr = autofile.trust(self.cfg)
        self.assertEqual((tr[(F, "similar")]["proven"], tr[(F, "similar")]["decisions"]), (False, 1))
        self.assertEqual((tr[(F, "name")]["proven"], tr[(F, "name")]["decisions"]), (False, 0))
        self.assertIn("undid", self.decide()["why"])
        self.n = 60 * 60 * 24 * 40   # decisions made after the undo count again
        c = mover._conn(self.cfg["database"])
        c.executemany("INSERT INTO moves (ts, src, dest, size, sha256, folder, source, rank, top_folder, "
                      "top_source, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      [(f"2026-03-01T00:00:{i:02d}", "s", "d", 1, "x", F, "similar", 1, F, "similar", "moved")
                       for i in range(20)])
        c.commit()
        c.close()
        t = autofile.trust(self.cfg)[(F, "similar")]
        self.assertEqual((t["decisions"], t["agreed"], t["proven"]), (21, 20, True))

    def test_auto_moves_you_kept_and_interrupted_moves_are_not_evidence(self):
        self.add(40, source="auto:similar")
        self.add(40, status="pending")
        self.add(40, status="interrupted")
        self.assertEqual(autofile.trust(self.cfg), {})

    def test_other_reasons_a_file_is_left_alone(self):
        self.add(30)
        self.assertFalse(self.decide("model", score=None)["auto"])
        self.assertFalse(self.decide(score=0.94)["auto"])
        self.assertFalse(self.decide(folder="2-Areas/B")["auto"])
        self.assertFalse(self.decide(hints={"C:/in/x.pdf": "duplicate_of_filed"})["auto"])
        self.assertFalse(self.decide(duplicate={"folder": F})["auto"])
        self.assertTrue(self.decide()["auto"])

    def test_the_wait_counts_from_arrival_not_from_an_old_modified_date(self):
        self.add(30)
        d = self.decide(age=86400 * 400, added=time.time() - 60)   # old document, downloaded a minute ago
        self.assertEqual((d["auto"], d.get("soon")), (False, True))


if __name__ == "__main__":
    unittest.main()
