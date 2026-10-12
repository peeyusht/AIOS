"""Remediation: updating one application through winget and stopping one service. winget, the registry and
Windows' service control are never touched here: made-up answers stand in for them."""
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apps  # noqa: E402
import cve  # noqa: E402
import library  # noqa: E402
import remedy  # noqa: E402

OWN = f"{sys.version_info[0]}.{sys.version_info[1]}"


def reg(sub, name, version, publisher=""):
    return {"id": "machine64:" + sub, "scope": "machine", "arch": "64-bit", "changed": 0,
            "values": {"DisplayName": name, "DisplayVersion": version, "Publisher": publisher}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.cfg = {"database": self.tmp / "t.db", "cve_database": self.tmp / "cve.db",
                    "library": {"remediate": True, "check_updates": True}}
        self.raw = [reg("k", "Kettle Archive", "24.1.0"), reg("m", "Mongo", "7.0.5"), reg("b", "Big Jump", "2.0"),
                    reg("p", f"Python {OWN}.1 (64-bit)", f"{OWN}.1150.0")]
        self.scan()
        rows = [{"name": "Kettle Archive", "id": "Kettle.Archive", "version": "24.1.0", "available": "24.9.0"},
                {"name": "Mongo", "id": "Mongo.Server", "version": "7.0.5", "available": "9.0.2"},
                {"name": "Big Jump", "id": "Big.Jump", "version": "2.0", "available": "3.0"},
                {"name": f"Python {OWN}.1 (64-bit)", "id": f"Python.Python.{OWN}", "version": f"{OWN}.1",
                 "available": f"{OWN}.9"}]
        catalogue = {"Mongo.Server": ["9.0.2", "8.3.11", "8.0.23", "7.0.28", "7.0.9", "6.0.27"], "Big.Jump": ["3.0", "2.0"]}
        apps.check_updates(self.cfg, read=lambda: {"ok": True, "error": None, "rows": rows},
                           versions=lambda i: catalogue.get(i, []), now=datetime(2026, 10, 12, 9))
        remedy.state.update(running=False, ok=None, message=None)
        self.ran = []
        p = mock.patch.object(remedy, "_refresh")          # the real one would read this PC's registry
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scan(self):
        apps.scan(self.cfg, desktop=lambda: self.raw, packaged=lambda: [], now=datetime(2026, 10, 12, 9))

    def app(self, name):
        return next(a for a in remedy._installed(self.cfg) if a["name"].startswith(name))

    def run_ok(self, new_version=None, code=0):
        def run(args):
            self.ran.append(args)
            if new_version:                                 # the installer did its work: Windows lists the new version
                i = next(i for i, r in enumerate(self.raw) if r["values"]["DisplayName"] == self.updating)
                self.raw[i] = reg("new", self.updating, new_version)
                self.scan()
            return code, "Successfully installed" if code == 0 else "Installer failed with exit code: 1602"
        return run


class PlanTest(Base):
    def test_what_the_update_button_would_do(self):
        self.assertEqual(self.app("Kettle")["update"],
                         {"id": "Kettle.Archive", "to": "24.9.0", "kind": "latest", "latest": "24.9.0", "blocked": None})
        m = self.app("Mongo")["update"]                     # 9.0.2 is a major jump: stay on the 7.0 line
        self.assertEqual((m["to"], m["kind"], m["latest"], m["blocked"]), ("7.0.28", "same_line", "9.0.2", None))
        b = self.app("Big Jump")["update"]                  # nothing newer on its own line: not done from here
        self.assertEqual((b["kind"], bool(b["blocked"])), ("latest", True))
        self.assertIn("major-version jump", b["blocked"])
        self.assertIn("agent itself runs on this Python", self.app("Python")["update"]["blocked"])

    def test_lines_and_jumps(self):
        for a, b, want in (("7.0.5", "9.0.2", True), ("22.12.0", "22.23.2", False), ("157.0.1", "158.0", False),
                           ("24.08", "25.01", True), ("", "2.0", False), ("< 3.14.7", "3.14.7", False)):
            self.assertEqual(apps.major_jump(a, b), want, (a, b))
        v = ["9.0.2", "8.3.11", "8.0.23", "7.0.28", "7.0.9", "6.0.27"]
        self.assertEqual(apps.same_line("7.0.5", v), "7.0.28")
        self.assertEqual(apps.same_line("8.0.18", v), "8.0.23")       # the line you are on first,
        self.assertEqual(apps.same_line("8.1.0", v), "8.3.11")        # else the same first number
        self.assertIsNone(apps.same_line("7.0.28", v))
        self.assertIsNone(apps.same_line("5.0.1", v))

    def test_the_one_command(self):
        self.assertEqual(remedy.winget_args("Kettle.Archive", None),
                         ["upgrade", "--id", "Kettle.Archive", "--exact", "--source", "winget", "--silent",
                          "--accept-package-agreements", "--disable-interactivity"])
        self.assertEqual(remedy.winget_args("Mongo.Server", "7.0.28")[-2:], ["--version", "7.0.28"])
        for bad in ("", "--all", "a b", "x;calc", "A.B --all", "-r"):
            self.assertRaises(ValueError, remedy.winget_args, bad, None)
        self.assertRaises(ValueError, remedy.winget_args, "A.B", "1.0 --force")
        self.assertFalse({"--all", "-r", "--recurse", "--force", "--include-unknown", "--accept-source-agreements",
                          "install", "uninstall"} & set(remedy.winget_args("A.B", "1.0")))


class UpdateTest(Base):
    def update(self, name, terms=True, **kw):
        self.updating = self.app(name)["name"]
        return remedy.start_update(self.cfg, self.app(name)["id"], terms, wait=True, **kw)

    def test_refused_before_anything_runs(self):
        run = self.run_ok()
        off = {**self.cfg, "library": {"check_updates": True}}
        self.assertIn("switched off", remedy.start_update(off, self.app("Kettle")["id"], True, run=run, wait=True)["message"])
        self.assertIn("No update is listed", remedy.start_update(self.cfg, "machine64:nope", True, run=run, wait=True)["message"])
        self.assertIn("No update is listed", remedy.start_update(self.cfg, "Kettle.Archive", True, run=run, wait=True)["message"])
        self.assertIn("major-version jump", self.update("Big Jump", run=run)["message"])
        self.assertIn("agent itself", self.update("Python", run=run)["message"])
        for terms in (False, None, "yes", 1):               # only a plain yes counts
            self.assertIn("licence terms", self.update("Kettle", terms=terms, run=run)["message"])
        remedy.state["running"] = True
        self.assertIn("still running", self.update("Kettle", run=run)["message"])
        self.assertEqual((self.ran, remedy.history(self.cfg["database"])), ([], []))
        self.assertIs(library.settings({})["remediate"], False)

    def test_update_to_the_latest(self):
        r = self.update("Kettle", run=self.run_ok("24.9.0"))
        self.assertTrue(r["ok"])
        self.assertEqual(self.ran, [remedy.winget_args("Kettle.Archive", None)])
        s = remedy.state
        self.assertEqual((s["running"], s["ok"], s["message"]), (False, True, "Updated Kettle Archive from 24.1.0 to 24.9.0."))
        h = remedy.history(self.cfg["database"])[0]
        self.assertEqual((h["action"], h["name"], h["target"], h["before"], h["after"], h["ok"]),
                         ("update", "Kettle Archive", "24.9.0", "24.1.0", "24.9.0", 1))
        self.assertIsNone(self.app("Kettle")["update"])     # the row is stale now: nothing more to offer

    def test_update_within_the_line(self):
        self.update("Mongo", run=self.run_ok("7.0.28"))
        self.assertEqual(self.ran[0][-2:], ["--version", "7.0.28"])      # never the 9.0.2 winget calls latest
        self.assertEqual(remedy.state["message"], "Updated Mongo from 7.0.5 to 7.0.28.")

    def test_an_installer_that_needs_rights_is_tried_once_more_as_administrator(self):
        # measured: a silent MSI without administrator rights does not ask, it fails (winget 0x8a150030)
        needs = self.run_ok(code=0x8A150030 - (1 << 32))

        def as_admin(args):
            self.ran.append(["as admin", *args])
            self.raw[0] = reg("new", "Kettle Archive", "24.9.0")
            self.scan()
            return 0, ""
        self.update("Kettle", run=needs, elevated=as_admin)
        self.assertEqual(self.ran, [remedy.winget_args("Kettle.Archive", None),
                                    ["as admin", *remedy.winget_args("Kettle.Archive", None)]])   # the very same command
        self.assertEqual((remedy.state["ok"], remedy.state["message"]), (True, "Updated Kettle Archive from 24.1.0 to 24.9.0."))
        # declining the Windows prompt is a failed update, said plainly
        self.raw[0] = reg("k", "Kettle Archive", "24.1.0")
        self.scan()
        self.update("Kettle", run=needs, elevated=lambda a: (-3, "You declined the Windows permission prompt."))
        self.assertEqual((remedy.state["ok"], remedy.state["message"]),
                         (False, "Not updated: You declined the Windows permission prompt. The installer needs administrator rights."))
        # any other failure is not retried with more rights
        never = mock.Mock()
        self.update("Kettle", run=self.run_ok(code=0x8A15002B - (1 << 32)), elevated=never)
        never.assert_not_called()

    def test_a_failed_update_is_reported_as_such(self):
        self.update("Kettle", run=self.run_ok(code=0x8A150006 - (1 << 32)), elevated=lambda a: (1603, ""))
        s, h = remedy.state, remedy.history(self.cfg["database"])[0]
        self.assertEqual((s["ok"], h["ok"], h["after"]), (False, 0, "24.1.0"))
        self.assertIn("did not go through (winget code 0x643).", s["message"])
        self.update("Kettle", run=self.run_ok())            # winget says done, Windows still lists the old one
        self.assertIn("still lists version 24.1.0", remedy.state["message"])
        self.update("Kettle", run=mock.Mock(side_effect=RuntimeError("boom")))
        self.assertEqual((remedy.state["running"], remedy.state["ok"]), (False, False))


class StopTest(Base):
    def setUp(self):
        super().setUp()
        raw = [{"name": "KettleSvc", "display": "Kettle Indexer", "state": "Running", "start": "Auto",
                "account": "LocalSystem", "exe": "C:\\Kettle\\svc.exe", "pid": 1, "company": "", "product": "",
                "version": "1.0", "listens": ["0.0.0.0|8443"]}]
        cve.scan(self.cfg, read_services=lambda: raw, now=datetime(2026, 10, 12, 9))

    def test_stop_one_listed_service(self):
        stop = mock.Mock(return_value=(True, "Stopped."))
        with mock.patch.object(cve, "scan"):
            for bad in ("Nope", "", "KettleSvc & calc"):
                self.assertIn("Unknown service", remedy.start_stop(self.cfg, bad, stop=stop, wait=True)["message"])
            off = {**self.cfg, "library": {}}
            self.assertIn("switched off", remedy.start_stop(off, "KettleSvc", stop=stop, wait=True)["message"])
            stop.assert_not_called()
            self.assertTrue(remedy.start_stop(self.cfg, "KettleSvc", stop=stop, wait=True)["ok"])
            stop.assert_called_once_with("KettleSvc")
            h = remedy.history(self.cfg["database"])[0]
            self.assertEqual((h["action"], h["name"], h["target"], h["after"], h["ok"]),
                             ("stop", "Kettle Indexer", "KettleSvc", "stopped", 1))
            remedy.start_stop(self.cfg, "KettleSvc", stop=mock.Mock(return_value=(False, "You declined the Windows permission prompt.")), wait=True)
            self.assertEqual((remedy.state["ok"], remedy.state["message"]), (False, "You declined the Windows permission prompt."))
        self.assertEqual(remedy.stop_elevated("bad;name")[0], False)
        self.assertEqual(remedy.view(self.cfg)["enabled"], True)


class FirewallTest(Base):
    def test_on_only_and_only_known_profiles(self):
        on = mock.Mock(return_value=(True, "Windows Firewall is on for all profiles."))
        with mock.patch("network.view"):
            off = {**self.cfg, "library": {}}
            self.assertIn("switched off", remedy.start_firewall_on(off, "all", turn_on=on, wait=True)["message"])
            for bad in ("", "allprofiles state off", "public", "Public & calc", "off"):
                self.assertIn("Unknown firewall profile", remedy.start_firewall_on(self.cfg, bad, turn_on=on, wait=True)["message"])
            on.assert_not_called()
            self.assertTrue(remedy.start_firewall_on(self.cfg, "all", turn_on=on, wait=True)["ok"])
            on.assert_called_once_with("all")
            h = remedy.history(self.cfg["database"])[0]
            self.assertEqual((h["action"], h["name"], h["target"], h["before"], h["after"], h["ok"]),
                             ("firewall", "Windows Firewall", "all profiles", "off", "on", 1))
            remedy.start_firewall_on(self.cfg, "Private", wait=True,
                                     turn_on=mock.Mock(return_value=(False, "You declined the Windows permission prompt.")))
            self.assertEqual((remedy.state["ok"], remedy.history(self.cfg["database"])[0]["after"]), (False, "off"))
        # the only commands that exist switch a profile ON; nothing in the module can switch one off
        self.assertEqual(set(remedy.FIREWALL), {"all", "Domain", "Private", "Public"})
        src = Path(remedy.__file__).read_text(encoding="utf-8")
        self.assertIn('state on"', src)
        self.assertNotIn("state off", src)
        self.assertEqual(remedy.firewall_on_elevated("everything")[0], False)


if __name__ == "__main__":
    unittest.main()
