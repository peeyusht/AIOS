"""Dashboard: the summary and the "needs attention" lines. Built from made-up parts; nothing is scanned."""
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dashboard  # noqa: E402


class AttentionTest(unittest.TestCase):
    def test_most_serious_first_and_each_goes_somewhere(self):
        d = {"agent": {"watching": True, "model_ok": False, "problem": None},
             "security": {"summary": {"kev": 1, "critical": 3, "apps_affected": 2, "services_exposed": 1, "services_affected": 1},
                          "exposed": [{"name": "Tessellate Engine", "ports": [27017], "cves": 4}]},
             "watch": {"counts": {"soon": 2, "sensitive": 1}, "next": [{"days": 0}]},
             "inbox": {"waiting": 1}, "apps": {"updates": 3},
             "storage": {"volumes": [{"letter": "C:", "bytes": 100, "free": 5}, {"letter": "D:", "bytes": 100, "free": 60}]},
             "cleanup": {"safe": {"count": 7}}}
        got = dashboard.attention(d)
        self.assertEqual([(a["level"], a["to"]) for a in got], [
            ("warning", "/settings"), ("danger", "/security"), ("danger", "/security"), ("warning", "/security"),
            ("warning", "/watch"), ("warning", "/cleanup"), ("info", "/watch"), ("info", "/inbox"),
            ("info", "/library"), ("info", "/cleanup")])
        text = " | ".join(a["text"] for a in got)
        for part in ("1 known flaw is being used in real attacks", "Tessellate Engine has known flaws and accepts connections",
                     "3 critical flaws in 2 installed programs", "2 dates are coming up in your documents; the next is today",
                     "Drive C: has 5% free", "1 file with personal or financial details is sitting", "1 file is waiting",
                     "3 installed applications have a newer version", "7 files in Downloads look safe to remove"):
            self.assertIn(part, text)
        self.assertEqual(dashboard.attention({}), [])
        self.assertEqual(dashboard.attention({"agent": {"watching": False}})[0]["level"], "danger")
        # an exposed service with no known flaws is not an alarm
        quiet = {"security": {"summary": {"services_exposed": 1, "services_affected": 1}, "exposed": [{"name": "x", "cves": 0}]}}
        self.assertEqual(dashboard.attention(quiet), [])


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.cfg = {"database": self.tmp / "t.db", "cve_database": self.tmp / "cve.db", "inbox_folders": [],
                    "para_root": self.tmp / "para", "destination_depth": 2, "library": {"vulnerabilities": True}}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_one_broken_part_leaves_the_rest(self):
        import journal
        journal._recorded["at"] = 0
        files = [{"added": 0, "size": 10}, {"added": 9e12, "size": 5}]
        with mock.patch.object(dashboard, "_storage", side_effect=RuntimeError("no disks")), \
                mock.patch.object(dashboard, "_watch", return_value={"enabled": True, "counts": {"soon": 0, "sensitive": 3}, "next": []}), \
                mock.patch.object(dashboard, "_cleanup", return_value={"scanned_at": None, "safe": {"count": 0, "bytes": 0}}):
            d = dashboard.build(self.cfg, {"watching": True, "ollama": True, "model": "m"}, files, {"disabled": True},
                                today=date(2026, 10, 12))
        self.assertEqual(d["storage"], {"error": "no disks"})
        self.assertEqual((d["inbox"]["waiting"], d["inbox"]["bytes"], d["inbox"]["added_7d"]), (2, 15, 1))
        self.assertEqual((d["agent"]["watching"], d["agent"]["model_ok"], d["agent"]["search"]), (True, True, None))
        self.assertEqual([x["date"] for x in d["activity"]["days"]][::6], ["2026-10-06", "2026-10-12"])   # always 7 days
        self.assertEqual((d["security"]["enabled"], d["security"]["summary"]["kev"], d["security"]["top"]), (True, 0, []))
        self.assertEqual((d["apps"]["enabled"], d["apps"]["programs"], d["remedy"]["enabled"]), (True, 0, False))
        # sensitive files are a count here, never what was found in them
        self.assertEqual([a["to"] for a in d["attention"]], ["/watch", "/inbox"])
        off = dashboard.build({**self.cfg, "library": {"applications": False}}, {}, [], None, today=date(2026, 10, 12))
        self.assertEqual((off["security"], off["apps"]), ({"enabled": False}, {"enabled": False}))


if __name__ == "__main__":
    unittest.main()
