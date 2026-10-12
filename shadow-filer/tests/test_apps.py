"""Applications: the installed-programs list, what counts as one application, and what changed between scans.
The registry and PowerShell are never touched here: made-up entries go in where Windows would be asked."""
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apps  # noqa: E402
import config_io  # noqa: E402
import journal  # noqa: E402
import library  # noqa: E402

CHANGED = datetime(2026, 3, 5, 10, 0).timestamp()


def reg(sub, scope="machine", arch="64-bit", **values):
    return {"id": f"{scope}{arch[:2]}:{sub}", "scope": scope, "arch": arch, "values": values, "changed": CHANGED}


def zip_tool(version="24.08", sub="7-Zip"):
    return reg(sub, DisplayName=f"7-Zip {version} (x64)", DisplayVersion=version, Publisher="Igor Pavlov",
               InstallDate="20260110", EstimatedSize=5600, InstallLocation='"C:\\Program Files\\7-Zip\\"')


class DesktopListTest(unittest.TestCase):
    def test_what_is_left_out(self):
        got = apps.desktop_apps([
            zip_tool(),
            reg("{A}", DisplayVersion="1.0"),                                           # no name
            reg("{B}", DisplayName="Runtime part", SystemComponent=1),
            reg("{C}", DisplayName="Update for Suite", ParentKeyName="Suite"),
            reg("KB123", DisplayName="Security Update KB123", ReleaseType="Security Update"),
            reg("Notes", DisplayName="Notes", SystemComponent=0),
        ])
        self.assertEqual([a["name"] for a in got], ["7-Zip 24.08 (x64)", "Notes"])

    def test_details(self):
        a, b = apps.desktop_apps([zip_tool(), reg("Notes", scope="user", arch="", DisplayName="Notes",
                                                  InstallDate="not a date", EstimatedSize=0)])
        self.assertEqual((a["version"], a["publisher"], a["installed"], a["date_is"], a["size"], a["location"],
                          a["arch"], a["scope"]),
                         ("24.08", "Igor Pavlov", "2026-01-10", "installed", 5600 * 1024, "C:\\Program Files\\7-Zip\\",
                          "64-bit", "machine"))
        # no usable install date: the day the registry entry last changed, and marked as such
        self.assertEqual((b["installed"], b["date_is"], b["size"], b["location"], b["version"], b["scope"]),
                         ("2026-03-05", "changed", None, None, "", "user"))

    def test_listed_twice_is_one_application(self):
        got = apps.desktop_apps([zip_tool(), zip_tool(sub="7-Zip-32") | {"arch": "32-bit"}, zip_tool("23.01", "{old}")])
        self.assertEqual([(a["version"], a["arch"]) for a in got], [("24.08", "64-bit"), ("23.01", "64-bit")])

    def test_name_without_its_version(self):
        for name, version, want in (
            ("7-Zip 24.08 (x64)", "24.08", "7zip"),
            ("7-Zip 25.01 (x64)", "25.01", "7zip"),
            ("Python 3.12.4 (64-bit)", "3.12.4150.0", "python"),
            ("Visual Studio Community 2022", "17.9.2", "visualstudiocommunity2022"),   # a year is part of the name
            ("Notes", "", "notes"),
        ):
            self.assertEqual(apps.name_key(name, version), want, name)


class PackagedListTest(unittest.TestCase):
    def test_names_and_publishers(self):
        raw = [
            {"id": "Vendor.Sketch_abc", "name": "Vendor.Sketch", "display": "Sketch Pad", "start": "Sketch",
             "version": "2.1.0.0", "subject": "CN=Vendor Ltd, O=Vendor Ltd", "publisher": "Vendor Ltd",
             "arch": "X64", "location": "C:\\Apps\\Sketch", "installed": "2026-02-01", "signature": "Store"},
            {"id": "Microsoft.WindowsCalculator_8w", "name": "Microsoft.WindowsCalculator",
             "display": "ms-resource:AppStoreName", "start": "Calculator", "version": "11.0",
             "subject": "CN=Microsoft Corporation, O=Microsoft", "publisher": "ms-resource:Publisher", "arch": "X64",
             "location": "", "installed": "", "signature": "Store"},
            {"id": "Side.LoadedTool_zz", "name": "Side.LoadedTool", "display": "ms-resource:x", "start": "",
             "version": "1.0", "subject": "CN=0F1E2D3C-4B5A-6978-8796-A5B4C3D2E1F0", "publisher": "", "arch": "Neutral",
             "location": "", "installed": "", "signature": "Developer"},
            {"name": "no family name"},
        ]
        got = apps.packaged_apps(raw)
        self.assertEqual([(a["name"], a["publisher"], a["from_store"], a["arch"]) for a in got], [
            ("Sketch Pad", "Vendor Ltd", True, "64-bit"),
            ("Calculator", "Microsoft Corporation", True, "64-bit"),     # resource pointers are not names
            ("Loaded Tool", "", False, ""),                               # a publisher id is not a name either
        ])
        self.assertEqual(got[0]["key"], "packaged:vendor.sketch_abc")


class ChangesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.cfg = {"database": self.tmp / "t.db", "inbox_folders": [], "para_root": self.tmp / "para",
                    "destination_depth": 2}
        journal._recorded["at"] = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scan(self, raw, day, packaged=None):
        return apps.scan(self.cfg, desktop=lambda: raw, packaged=lambda: packaged,
                         now=datetime(2026, 10, day, 9, 30))

    def test_update_install_remove(self):
        notes = reg("Notes", DisplayName="Notes", DisplayVersion="1.0")
        first = self.scan([zip_tool(), notes], 1)
        self.assertEqual(first["events"], [])                    # the first list is the starting point
        self.assertEqual(apps.view(self.cfg, today=date(2026, 10, 1))["changes"], [])
        # an MSI update: new registry key, new name, same application
        new = reg("Paint", DisplayName="Paint", DisplayVersion="3")
        got = self.scan([zip_tool("25.01", "{new-key}"), new], 2)["events"]
        self.assertEqual([(e["event"], e["name"], e["old_version"], e["new_version"]) for e in got], [
            ("updated", "7-Zip 25.01 (x64)", "24.08", "25.01"),
            ("removed", "Notes", "1.0", ""),
            ("installed", "Paint", "", "3"),
        ])
        self.assertEqual(self.scan([zip_tool("25.01", "{new-key}"), new], 3)["events"], [])
        v = apps.view(self.cfg, today=date(2026, 10, 3))
        self.assertEqual(len(v["changes"]), 3)
        self.assertEqual(v["counts"]["desktop"], 2)
        self.assertEqual(v["history_since"], "2026-10-01T09:30:00")
        self.assertIn("Updated 7-Zip 25.01 (x64): 24.08 -> 25.01", apps.as_text(v))

    def test_two_versions_side_by_side_stay_two(self):
        def py(v):
            return reg("py" + v, DisplayName=f"Python {v} (64-bit)", DisplayVersion=v)
        self.scan([py("3.11.9")], 1)
        got = self.scan([py("3.11.9"), py("3.12.4")], 2)["events"]
        self.assertEqual([(e["event"], e["new_version"]) for e in got], [("installed", "3.12.4")])
        got = self.scan([py("3.11.9"), py("3.12.6"), py("3.13.0")], 3)["events"]
        # one gone, two new: which one replaced it is a guess, so nothing is called an update
        self.assertEqual(sorted((e["event"], e["old_version"], e["new_version"]) for e in got),
                         [("installed", "", "3.12.6"), ("installed", "", "3.13.0"), ("removed", "3.12.4", "")])

    def test_a_list_that_cannot_be_read_removes_nothing(self):
        store = [{"id": "Vendor.Sketch_abc", "name": "Vendor.Sketch", "display": "Sketch Pad", "version": "2.1",
                  "signature": "Store"}]
        self.scan([zip_tool()], 1, packaged=store)
        r = self.scan([zip_tool()], 2, packaged=None)            # PowerShell did not answer
        self.assertEqual(r["events"], [])
        self.assertFalse(r["packaged_read"])
        self.assertEqual([a["name"] for a in r["apps"] if a["kind"] == "packaged"], ["Sketch Pad"])
        r = apps.scan(self.cfg, desktop=lambda: None, packaged=lambda: store, now=datetime(2026, 10, 3))
        self.assertEqual((r["events"], len(r["apps"])), ([], 2))
        self.assertIsNone(apps.scan(self.cfg, desktop=lambda: None, packaged=lambda: None))
        self.assertEqual(len(apps.view(self.cfg)["apps"]), 2)    # and the list is still there

    def test_changes_reach_the_work_journal(self):
        self.scan([zip_tool()], 1)
        self.scan([zip_tool("25.01")], 2)
        rep = journal.build(self.cfg, days=7, today=date(2026, 10, 3))
        self.assertEqual(rep["totals"]["apps"], 1)
        day = rep["days"][0]
        self.assertEqual((day["date"], day["counts"]["apps"], day["apps"][0]["event"]), ("2026-10-02", 1, "updated"))
        self.assertIn("Updated 7-Zip 25.01 (x64): 24.08 -> 25.01", rep["text"])
        self.assertIn("1 application change,", rep["text"])

    def test_library_page_carries_the_list_and_the_switch(self):
        self.scan([zip_tool()], 1)
        with mock.patch.object(library, "REPORT_FILE", self.tmp / "none.json"):
            self.assertEqual(library.view(self.cfg)["applications"]["counts"]["desktop"], 1)
            self.assertIsNone(library.view({**self.cfg, "library": {"applications": False}})["applications"])
            self.assertIsNone(library.view({**self.cfg, "library": {"enabled": False}})["applications"])
        self.assertIn("library.applications", [f[0] for f in config_io.FIELDS])


class InstallerFilesTest(unittest.TestCase):
    def test_which_installed_application_a_file_belongs_to(self):
        installed = apps.desktop_apps([zip_tool("24.08"), reg("Git", DisplayName="Git for Windows",
                                                              DisplayVersion="2.47.0"),
                                       reg("Fox", DisplayName="Mozilla Firefox (x64 en-US)", DisplayVersion="158.0"),
                                       reg("Go", DisplayName="Go", DisplayVersion="1.23")])
        files = [
            {"name": "7z2301-x64.exe", "product": "7-Zip", "version": "23.01"},
            {"name": "7z-setup.exe", "product": "7-Zip", "version": "24.08.0.0"},
            {"name": "Firefox Setup 159.0.exe", "product": "Mozilla Firefox", "version": "159.0"},
            {"name": "Git-2.48.1-64-bit.exe", "product": "", "version": "2.48.1"},      # "git" is too short to go on
            {"name": "GoodSync-setup.exe", "product": "GoodSync", "version": "12.0"},    # not "Go"
            {"name": "tool.msi", "product": "", "version": ""},
        ]
        got = apps.match_installers(files, installed)
        self.assertEqual([(g.get("installed_name"), g.get("installed_version"), g.get("file_is")) for g in got], [
            ("7-Zip 24.08 (x64)", "24.08", "older"),
            ("7-Zip 24.08 (x64)", "24.08", "same"),
            ("Mozilla Firefox (x64 en-US)", "158.0", "newer"),
            (None, None, None),
            (None, None, None),
            (None, None, None),
        ])

    def test_version_of_a_program_file(self):
        self.assertEqual(library.program_version("24.08.0.0", "7z.exe"), "24.08.0.0")
        self.assertEqual(library.program_version("", "Tool-3.2.1-x64.msi"), "3.2.1")
        self.assertEqual(library.program_version(None, "setup.exe"), "")


if __name__ == "__main__":
    unittest.main()
