"""End of support: the local copy of the end-of-life list and the strict matching. A made-up list stands in
for endoflife.date; nothing is downloaded."""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import compliance  # noqa: E402
import eol  # noqa: E402

TODAY = date(2026, 10, 12)


def rel(name, ended, until, latest=None):
    return {"name": name, "isEol": ended, "eolFrom": until, "latest": {"name": latest} if latest else None}


def listing(extra=()):
    products = [
        {"name": "pine", "label": "Pine Runtime", "aliases": ["pine-lang"], "category": "lang",
         "releases": [rel("3.13", False, "2029-10-31", "3.13.15"), rel("3.12", False, "2026-12-01", "3.12.10"), rel("3.9", True, "2025-10-31")]},
        {"name": "kettle", "label": "Kettle Archive", "aliases": [], "category": "app",
         "releases": [rel("25", False, "2028-01-01"), rel("24", True, "2026-06-01"), rel("lts-2024", False, "2030-01-01")]},
        {"name": "windows", "label": "Microsoft Windows", "aliases": [], "category": "os",
         "releases": [rel("11-25h2-w", False, "2027-10-12"), rel("11-25h2-e", False, "2028-10-10"), rel("11-23h2-w", True, "2025-11-11"), rel("10-22h2", True, "2025-10-14")]},
        {"name": "some-router", "label": "Router", "aliases": [], "category": "device", "releases": [rel("1", False, None)]},
        *extra,
    ]
    products += [{"name": f"filler{i}", "label": f"Filler {i}", "aliases": [], "category": "app", "releases": [rel("1", False, None)]} for i in range(60)]
    return {"result": products}


class EolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.cfg = {"database": self.tmp / "t.db", "cve_database": self.tmp / "cve.db"}
        self.asked = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sync(self, data=None, fail=False):
        def get(url, dest=None, timeout=0):
            self.asked.append(url)
            if fail:
                raise OSError("offline")
            return json.dumps(data if data is not None else listing())
        return eol.sync(self.cfg, get=get, now=datetime(2026, 10, 12, 9))

    def one(self, **item):
        return eol.match(self.cfg, [{"version": "", **item}], TODAY)[0]

    def test_one_fixed_public_file_and_a_failed_download_keeps_the_copy(self):
        self.assertEqual(eol.status(self.cfg), {"synced_at": None, "products": 0, "error": None})
        self.assertEqual(self.one(name="Pine Runtime", version="3.9.1")["state"], "unknown")       # no copy yet
        r = self.sync()
        self.assertEqual((r["ok"], r["products"], self.asked), (True, 63, [eol.URL]))                # devices are left out
        self.assertEqual(eol.status(self.cfg)["synced_at"], "2026-10-12T09:00:00")
        bad = self.sync(fail=True)
        self.assertEqual((bad["ok"], eol.status(self.cfg)["products"], eol.status(self.cfg)["error"]), (False, 63, "offline"))
        self.assertFalse(self.sync({"result": []})["ok"])                                           # an empty list replaces nothing
        self.assertEqual(eol.status(self.cfg)["products"], 63)

    def test_release_lines(self):
        self.sync()
        for item, want in (
            (dict(name="Pine Runtime 3.9.1 (64-bit)", version="3.9.1150.0"), ("Pine Runtime", "3.9", "ended", "2025-10-31")),
            (dict(name="Pine Runtime", version="3.13.2"), ("Pine Runtime", "3.13", "supported", "2029-10-31")),
            (dict(name="Pine Runtime", version="3.12.4"), ("Pine Runtime", "3.12", "soon", "2026-12-01")),       # within 90 days
            (dict(name="Pine Runtime", version="3.10.0"), ("Pine Runtime", None, "unknown", None)),              # a line the list lacks
            (dict(name="Kettle Archive 24.08 (x64)", version="24.08"), ("Kettle Archive", "24", "ended", "2026-06-01")),
            (dict(name="Contoso Kettle Archive", version="25.1"), ("Kettle Archive", "25", "supported", "2028-01-01")),  # maker in front
        ):
            got = self.one(**item)
            self.assertEqual((got["product"], got.get("line"), got["state"], got.get("until")), want, item)
        self.assertEqual(self.one(name="Pine Runtime", version="3.12.4")["latest"], "3.12.10")

    def test_what_is_not_matched(self):
        self.sync(listing(extra=[{"name": "pine-b", "label": "Pine Runtime", "aliases": [], "category": "app", "releases": [rel("3", True, None)]}]))
        self.assertIsNone(self.one(name="Pine Runtime", version="3.9")["product"])        # two products under one name: neither
        self.sync()
        for name in ("Pine Runtime Tools", "Kettle Archive Viewer", "Grammarly for Windows", "Windows", "Router", "Unknown Program"):
            self.assertIsNone(self.one(name=name, version="1.0")["product"], name)        # a part of a name, an OS, a device

    def test_windows(self):
        self.assertEqual(eol.windows(self.cfg, 26200, "25H2", "Professional", TODAY)["state"], "unknown")   # no copy
        self.sync()
        for args, want in (((26200, "25H2", "Professional"), ("supported", "11-25h2-w", "2027-10-12")),
                           ((26200, "25H2", "Enterprise"), ("supported", "11-25h2-e", "2028-10-10")),
                           ((22631, "23H2", "Core"), ("ended", "11-23h2-w", "2025-11-11")),
                           ((19045, "22H2", "Professional"), ("ended", "10-22h2", "2025-10-14")),
                           ((27000, "27H1", "Professional"), ("unknown", None, None))):
            w = eol.windows(self.cfg, *args, TODAY)
            self.assertEqual((w["state"], w["line"], w["until"]), want, args)

    def test_in_the_compliance_checks(self):
        self.sync()
        from test_compliance import pc
        apps = {"updates": {"enabled": False}, "apps": [
            {"name": "Kettle Archive 24.08 (x64)", "version": "24.08", "kind": "desktop"},
            {"name": "Pine Runtime 3.12.4 (64-bit)", "version": "3.12.4150.0", "kind": "desktop"},
            {"name": "Brightpad Notes", "version": "4.1", "kind": "desktop"},
            {"name": "Kettle Archive", "version": "24.0", "kind": "packaged"}]}
        c = {x["id"]: x for x in compliance.update_checks(pc(), None, apps, TODAY, self.cfg)}
        u = c["upd.unsupported"]
        self.assertEqual((u["status"], u["evidence"]), ("fail", [
            "Kettle Archive 24.08 (x64): the 24 line ended on 2026-06-01",
            "Pine Runtime 3.12.4 (64-bit): the 3.12 line ends on 2026-12-01; newest in that line is 3.12.10"]))
        self.assertIn("2 of 3 programs are in the end-of-life list", u["detail"])
        self.assertEqual((c["upd.supported"]["status"], c["upd.supported"]["detail"].endswith("gets security updates until 2027-10-12.")), ("pass", True))
        old = {x["id"]: x for x in compliance.update_checks(pc(build=22631, display_version="23H2", edition="Core"), None, apps, TODAY, self.cfg)}
        self.assertEqual((old["upd.supported"]["status"], "2025-11-11" in old["upd.supported"]["detail"]), ("fail", True))


if __name__ == "__main__":
    unittest.main()
