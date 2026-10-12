"""Compliance: the checks behind the five control areas, declarations, accepted exceptions and the history.
Made-up settings stand in for Windows; nothing on this PC is read."""
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import compliance  # noqa: E402
import dashboard  # noqa: E402

TODAY = date(2026, 10, 12)


def pc(**over):
    p = {"computer": "DEMO-PC", "user": "alex", "manufacturer": "Contoso", "model": "Tower 5", "serial": "SN123",
         "edition": "Professional", "display_version": "25H2", "build": 26200, "ubr": 1234,
         "last_update": "2026-10-01", "last_update_id": "KB5000001", "no_auto_update": 0, "paused_until": "",
         "antivirus": [{"name": "Windows Defender", "state": 0x61100}],
         "defender": {"present": True, "enabled": True, "realtime": True, "signature_age": 1},
         "drives": [{"letter": "C:", "size": 1, "protection": 1}],
         "users": [{"name": "alex", "enabled": True, "password_required": True, "last_logon": "2026-10-12", "sid": "S-1-5-21-1-1001"},
                   {"name": "Guest", "enabled": False, "password_required": False, "last_logon": "", "sid": "S-1-5-21-1-501"},
                   {"name": "admin", "enabled": True, "password_required": True, "last_logon": "2026-09-01", "sid": "S-1-5-21-1-1002"}],
         "admins": [{"name": "DEMO-PC\\admin", "kind": "User"}], "admins_read": True, "me_admin": False,
         "screensaver": {"active": "1", "secure": "1", "timeout": "600"}, "inactivity": 0,
         "display_off": 0, "sleep_after": 0, "lock_on_wake": -1, "autoplay_off": 1, "autorun_policy": 0, "inbound_allow_rules": 40}
    p.update(over)
    return p


def net(**over):
    n = {"read_at": "2026-10-12T09:00:00", "other_firewalls": [],
         "firewall": [{"name": x, "enabled": True, "inbound": "Block", "outbound": "Allow"} for x in ("Domain", "Private", "Public")],
         "listening": [], "shares": []}
    n.update(over)
    return n


def flaw(score, published, kev=False):
    return {"id": "CVE-X", "score": score, "published": published, "kev": kev}


VUL = {"scanned_at": "2026-10-12T09:00:00", "recognised": 2, "installed": 3, "apps": [
    {"name": "Kettle Archive", "judged_version": "24.08", "update": {"to": "25.01", "blocked": None},
     "cves": [flaw(9.8, "2026-08-01", True), flaw(7.5, "2026-10-05"), flaw(5.0, "2026-01-01")]},
    {"name": "Brightpad Notes", "judged_version": "4.1", "update": None, "cves": [flaw(8.0, "2026-10-01")]}]}
APPS = {"updates": {"enabled": True, "count": 1}, "apps": [{"name": "Kettle Archive", "version": "24.08", "available": "25.01"}]}


def by_id(checks):
    return {c["id"]: c for c in checks}


class ChecksTest(unittest.TestCase):
    def test_a_well_kept_pc_passes(self):
        self.assertEqual({c["status"] for c in compliance.configuration_checks(pc())}, {"pass"})
        self.assertEqual({c["status"] for c in compliance.access_checks(pc())}, {"pass"})
        self.assertEqual({c["status"] for c in compliance.malware_checks(pc())}, {"pass"})
        self.assertEqual({c["status"] for c in compliance.firewall_checks(net())}, {"pass"})

    def test_firewall(self):
        off = [{"name": x, "enabled": False, "inbound": "NotConfigured", "outbound": ""} for x in ("Domain", "Private", "Public")]
        c = by_id(compliance.firewall_checks(net(firewall=off)))
        self.assertEqual((c["fw.on"]["status"], c["fw.default"]["status"], c["fw.on"]["to"]), ("fail", "unknown", "/network"))
        c = by_id(compliance.firewall_checks(net(firewall=off, other_firewalls=["Contoso Firewall"])))
        self.assertEqual(c["fw.on"]["status"], "warn")                       # another product has the job
        allow = [{"name": "Public", "enabled": True, "inbound": "Allow", "outbound": "Allow"}]
        self.assertEqual(by_id(compliance.firewall_checks(net(firewall=allow)))["fw.default"]["status"], "fail")
        c = by_id(compliance.firewall_checks(net(
            listening=[{"reach": "network", "windows": False, "proto": "TCP", "process": "tessd", "port": 27017},
                       {"reach": "network", "windows": True, "proto": "TCP", "process": "svchost", "port": 135},
                       {"reach": "this PC", "windows": False, "proto": "TCP", "process": "x", "port": 1}],
            shares=[{"name": "Scans", "builtin": False, "printer": False}, {"name": "C$", "builtin": True, "printer": False}])))
        self.assertEqual((c["fw.ports"]["status"], c["fw.ports"]["evidence"], c["fw.shares"]["status"], c["fw.shares"]["evidence"]),
                         ("info", ["tessd: TCP 27017"], "warn", ["Scans"]))
        self.assertEqual(compliance.firewall_checks(None)[0]["status"], "unknown")

    def test_configuration(self):
        bad = pc(screensaver={"active": "1", "secure": "", "timeout": ""}, autoplay_off=0,
                 drives=[{"letter": "C:", "protection": 2}, {"letter": "D:", "protection": 1}],
                 users=[{"name": "alex", "enabled": True, "password_required": False, "last_logon": "2026-10-12", "sid": "S-1-5-21-1-1001"},
                        {"name": "Guest", "enabled": True, "password_required": False, "last_logon": "", "sid": "S-1-5-21-1-501"}])
        c = by_id(compliance.configuration_checks(bad))
        self.assertEqual({k: v["status"] for k, v in c.items()},
                         {"cfg.lock": "warn", "cfg.autoplay": "fail", "cfg.guest": "fail", "cfg.password": "fail",
                          "cfg.unused": "warn", "cfg.encryption": "fail"})
        self.assertEqual((c["cfg.password"]["evidence"], c["cfg.encryption"]["detail"][:18]), (["alex", "Guest"], "Not encrypted: C:."))
        for ok in (dict(inactivity=600), dict(display_off=300, lock_on_wake=1), dict(autorun_policy=0xFF, autoplay_off=0)):
            c = by_id(compliance.configuration_checks(pc(screensaver={}, **ok)))
            self.assertEqual("pass", c["cfg.autoplay" if "autorun_policy" in ok else "cfg.lock"]["status"], ok)
        # going dark without asking to sign in again is not a lock; neither is a lock after an hour
        for no in (dict(display_off=300, lock_on_wake=0), dict(inactivity=3600)):
            self.assertEqual(by_id(compliance.configuration_checks(pc(screensaver={}, **no)))["cfg.lock"]["status"], "warn", no)

    def test_updates(self):
        c = by_id(compliance.update_checks(pc(), VUL, APPS, TODAY))
        self.assertEqual({k: v["status"] for k, v in c.items()},
                         {"upd.supported": "pass", "upd.windows": "pass", "upd.automatic": "pass", "upd.flaws": "fail",
                          "upd.coverage": "info", "upd.pending": "warn"})
        # only high or critical flaws older than 14 days count: the 7.5 from a week ago and the 5.0 do not
        self.assertEqual(c["upd.flaws"]["evidence"], ["Kettle Archive 24.08: 1 high or critical, oldest 72 days, fix: update to 25.01"])
        self.assertIn("1 of the flaws is being used in real attacks", c["upd.flaws"]["detail"])
        old = by_id(compliance.update_checks(pc(build=19045, last_update="2026-08-01", no_auto_update=1), None, None, TODAY))
        self.assertEqual({k: v["status"] for k, v in old.items()},
                         {"upd.supported": "fail", "upd.windows": "fail", "upd.automatic": "fail", "upd.flaws": "unknown", "upd.pending": "unknown"})
        self.assertIn("Windows 10", old["upd.supported"]["detail"])
        self.assertEqual(compliance.windows_name(pc()), "Windows 11 Professional 25H2")     # the registry still says "Windows 10"
        paused = by_id(compliance.update_checks(pc(paused_until="2026-11-01T00:00:00Z"), VUL, APPS, TODAY))
        self.assertEqual(paused["upd.automatic"]["status"], "warn")

    def test_access_and_malware(self):
        c = by_id(compliance.access_checks(pc(me_admin=True, admins_read=False)))
        self.assertEqual((c["acc.daily"]["status"], c["acc.admins"]["status"]), ("fail", "unknown"))
        c = by_id(compliance.malware_checks(pc(antivirus=[{"name": "Windows Defender", "state": 0x60100}],
                                              defender={"present": True, "enabled": False, "realtime": False, "signature_age": 30})))
        self.assertEqual({k: v["status"] for k, v in c.items()}, {"mal.present": "fail", "mal.realtime": "fail", "mal.signatures": "fail"})
        self.assertEqual(compliance.malware_checks(pc(antivirus=[], defender={}))[0]["status"], "unknown")


class PageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.cfg = {"database": self.tmp / "t.db"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assess(self, **over):
        return compliance.assess(self.cfg, pc(**over), net(), VUL, APPS, TODAY)

    def test_controls_declarations_exceptions_history(self):
        v = self.assess(me_admin=True)
        self.assertEqual([(g["key"], g["status"]) for g in v["controls"]],
                         [("firewalls", "pass"), ("configuration", "pass"), ("updates", "fail"), ("access", "fail"), ("malware", "pass")])
        self.assertEqual({k: v["summary"][k] for k in ("controls_passing", "fail", "warn", "accepted", "declared_open")},
                         {"controls_passing": 3, "fail": 2, "warn": 1, "accepted": 0, "declared_open": 7})
        self.assertEqual(v["device"]["windows"], "Windows 11 Professional 25H2")
        self.assertEqual([compliance.serial(s) for s in ("SN123", "Default string", "To be filled by O.E.M.", "", None)],
                         ["SN123", "", "", "", ""])              # a placeholder is not a serial number
        # an exception needs a reason, and only failing or doubtful checks can carry one
        db = self.cfg["database"]
        self.assertTrue(compliance.accept(db, "acc.daily", "Sole user; a separate admin account is planned for November."))
        self.assertTrue(compliance.accept(db, "mal.present", "pointless"))
        self.assertFalse(compliance.accept(db, "acc.daily; drop table", "x"))
        v = self.assess(me_admin=True)
        acc = by_id(v["controls"][3]["checks"])["acc.daily"]
        self.assertEqual((acc["status"], acc["accepted"]["reason"][:9], v["controls"][3]["status"], v["summary"]["accepted"], v["summary"]["fail"]),
                         ("fail", "Sole user", "pass", 1, 1))               # still shown as failing, no longer counted
        self.assertIsNone(by_id(v["controls"][4]["checks"])["mal.present"]["accepted"])     # it passes: nothing to accept
        self.assertTrue(compliance.accept(db, "acc.daily", ""))             # withdrawn
        self.assertEqual(self.assess(me_admin=True)["summary"]["accepted"], 0)
        # declarations: only the listed questions, only yes / no / does not apply
        self.assertTrue(compliance.declare(db, "mfa", "yes", "Authenticator app on all mailboxes"))
        self.assertTrue(compliance.declare(db, "backups", "no"))
        self.assertFalse(compliance.declare(db, "made_up", "yes"))
        self.assertFalse(compliance.declare(db, "mfa", "maybe"))
        v = self.assess()
        d = {q["key"]: q for q in v["declared"]}
        self.assertEqual((d["mfa"]["answer"], d["mfa"]["note"], d["backups"]["answer"], d["router"]["answer"], v["summary"]["declared_open"]),
                         ("yes", "Authenticator app on all mailboxes", "no", None, 5))
        text = compliance.as_text({**v, "patch_log": [{"ts": "2026-10-12T16:04:49", "ok": 1, "message": "Updated Harbor from 1 to 2."}]})
        for part in ("Security posture of DEMO-PC", "SECURITY UPDATE MANAGEMENT: FAIL", "[FAIL] No high or critical flaw older than 14 days",
                     "DECLARED BY THE OWNER (not measured)", "Yes             Multi-factor login", "Updated Harbor from 1 to 2.", "not a certificate"):
            self.assertIn(part, text)
        # one line a day; the last assessment of the day wins; the dashboard reads it without asking Windows
        compliance.record(self.cfg, self.assess(me_admin=True), date(2026, 10, 11))
        compliance.record(self.cfg, v, TODAY)
        compliance.record(self.cfg, self.assess(autoplay_off=0), TODAY)
        h = compliance.history(self.cfg, 90, TODAY)
        self.assertEqual([(r["day"], r["controls"]["access"], r["controls"]["configuration"]) for r in h],
                         [("2026-10-11", "fail", "pass"), ("2026-10-12", "pass", "fail")])
        self.assertEqual(h[-1]["checks"]["cfg.autoplay"], "fail")
        got = dashboard.attention({"compliance": {"controls": h[-1]["controls"], "summary": h[-1]["summary"]}})
        self.assertEqual([(a["level"], a["to"]) for a in got], [("warning", "/compliance")])
        self.assertIn("2 of 5 security control areas have a failing check (2 checks in all)", got[0]["text"])

    def test_cannot_read_windows(self):
        compliance._cache.update(at=0.0, raw=None)
        v = compliance.view({**self.cfg, "library": {}}, read=lambda: None)
        self.assertEqual((v["assessed_at"], v["controls"], bool(v["error"])), (None, [], True))


if __name__ == "__main__":
    unittest.main()
