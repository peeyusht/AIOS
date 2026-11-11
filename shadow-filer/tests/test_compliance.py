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
         "display_off": 0, "sleep_after": 0, "lock_on_wake": -1, "autoplay_off": 1, "autorun_policy": 0, "inbound_allow_rules": 40,
         "lockout_threshold": 10, "pw_min_length": 14, "pw_max_age_days": 90, "pw_history": 5,
         "smb1_on": False, "rdp_on": False, "rdp_nla": True, "remote_registry_on": False, "psv2_present": False,
         "bios_version": "F39", "bios_date": "2024-03-22", "usb_storage": "read_only",
         "wifi": {"adapter": True, "connected": True, "auth": "wpa2", "open_auto": 0},
         "logs": {"mode": "circular", "oldest": "2026-01-01"}, "audit": {"logon": 3, "users": 1}, "backups": ["agent"]}
    p.update(over)
    return p


def net(**over):
    n = {"read_at": "2026-10-12T09:00:00", "other_firewalls": [],
         "firewall": [{"name": x, "enabled": True, "inbound": "Block", "outbound": "Allow"} for x in ("Domain", "Private", "Public")],
         "listening": [], "shares": [], "rules": {"total": 12, "windows": 12, "programs": [], "wide_open": [], "missing": 0}}
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
        prog = {"program": "tessd.exe", "path": "C:\\T\\tessd.exe", "rules": 2, "ports": ["27017"], "more_ports": 0, "any_port": False,
                "profiles": ["all"], "any_address": True, "public": True, "missing": False}
        rules = lambda **o: {"total": 20, "windows": 15, "programs": [prog], "wide_open": [], "missing": 0, **o}
        c = by_id(compliance.firewall_checks(net(rules=rules())))["fw.rules"]
        self.assertEqual((c["status"], c["evidence"]), ("info", ["tessd.exe: port 27017; all profiles; from any address"]))   # yours to approve
        gone = {**prog, "program": "old.exe", "missing": True, "any_port": True, "ports": []}
        c = by_id(compliance.firewall_checks(net(rules=rules(programs=[gone, prog], missing=1))))["fw.rules"]
        self.assertEqual((c["status"], c["evidence"][0]), ("warn", "old.exe: any port; all profiles; from any address (program no longer there)"))
        c = by_id(compliance.firewall_checks(net(rules=rules(wide_open=[{"name": "Allow everything", "profiles": ["all"], "any_address": True}]))))["fw.rules"]
        self.assertEqual((c["status"], c["evidence"][0]), ("fail", "ANY PROGRAM, ANY PORT: Allow everything"))
        self.assertEqual(by_id(compliance.firewall_checks(net(rules=None)))["fw.rules"]["status"], "unknown")

    def test_browsers(self):
        apps = {"apps": [{"name": "Google Chrome"}, {"name": "Microsoft Edge"}, {"name": "Mozilla Firefox (x64 en-US)"}, {"name": "Notes"}]}
        ok = compliance.browser_checks(pc(), apps)
        self.assertEqual((ok["status"], ok["detail"]), ("pass", "Automatic updates are not switched off for Google Chrome, Microsoft Edge, Firefox."))
        bad = compliance.browser_checks(pc(browser_policy={"chrome_default": "0", "firefox_off": "1"},
                                           update_services=[{"name": "edgeupdate", "start": "Disabled"}, {"name": "edgeupdatem", "start": "Disabled"}]), apps)
        self.assertEqual((bad["status"], bad["evidence"]), ("fail", [
            "Google Chrome: updates are switched off by policy", "Firefox: updates are switched off by policy",
            "Microsoft Edge: its update service is disabled"]))
        one = compliance.browser_checks(pc(update_services=[{"name": "edgeupdate", "start": "Disabled"}, {"name": "edgeupdatem", "start": "Manual"}]), apps)
        self.assertEqual(one["status"], "pass")                                    # one of its two services can still run
        self.assertIsNone(compliance.browser_checks(pc(), {"apps": [{"name": "Notes"}]}))     # no browser: no check
        self.assertIsNone(compliance.browser_checks(pc(), None))

    def test_configuration(self):
        bad = pc(screensaver={"active": "1", "secure": "", "timeout": ""}, autoplay_off=0, lockout_threshold=0, pw_min_length=0,
                 drives=[{"letter": "C:", "protection": 2}, {"letter": "D:", "protection": 1}],
                 users=[{"name": "alex", "enabled": True, "password_required": False, "last_logon": "2026-10-12", "sid": "S-1-5-21-1-1001"},
                        {"name": "Guest", "enabled": True, "password_required": False, "last_logon": "", "sid": "S-1-5-21-1-501"}])
        c = by_id(compliance.configuration_checks(bad))
        self.assertEqual({k: v["status"] for k, v in c.items()},
                         {"cfg.lock": "info", "cfg.unlock": "fail", "cfg.pwpolicy": "warn", "cfg.autoplay": "fail", "cfg.guest": "fail", "cfg.password": "fail",
                          "cfg.unused": "warn", "cfg.encryption": "info", "cfg.smb1": "pass", "cfg.rdp": "pass", "cfg.remreg": "pass", "cfg.psv2": "pass", "cfg.usb": "pass",
                          "cfg.builtin_admin": "pass"})
        # Cyber Essentials v3.3 sets no lock time and does not ask for encryption: notes, never failing the area
        self.assertEqual(compliance._roll([c["cfg.lock"], c["cfg.encryption"], c["cfg.guest"] | {"status": "pass"}]), "pass")
        self.assertEqual(compliance._roll([c["cfg.lock"], c["cfg.encryption"]]), "info")         # notes alone are not "met"
        self.assertEqual(compliance.configuration_checks(bad)[0]["id"], "cfg.lock")      # fleet.payload reads it first
        self.assertEqual((c["cfg.password"]["evidence"], c["cfg.encryption"]["detail"][:18]), (["alex", "Guest"], "Not encrypted: C:."))
        for ok in (dict(inactivity=600), dict(display_off=300, lock_on_wake=1), dict(autorun_policy=0xFF, autoplay_off=0)):
            c = by_id(compliance.configuration_checks(pc(screensaver={}, **ok)))
            self.assertEqual("pass", c["cfg.autoplay" if "autorun_policy" in ok else "cfg.lock"]["status"], ok)
        # going dark without asking to sign in again is not a lock; neither is a lock after an hour
        for no in (dict(display_off=300, lock_on_wake=0), dict(inactivity=3600)):
            self.assertEqual(by_id(compliance.configuration_checks(pc(screensaver={}, **no)))["cfg.lock"]["status"], "info", no)

    def test_unlock_tries(self):
        st = lambda n: compliance.unlock_check(pc(lockout_threshold=n))["status"]
        self.assertEqual([st(n) for n in (1, 5, 10, 11, 50, 0, -1, None, True)],
                         ["pass", "pass", "pass", "fail", "fail", "fail", "unknown", "unknown", "unknown"])
        self.assertIn("never lock", compliance.unlock_check(pc(lockout_threshold=0))["detail"])

    def test_password_policy(self):
        """F-13: Cyber Essentials 12+ (else a look: a deny list or multi-factor login may make up for it);
        CERT-In 8+, with expiry and no reuse; unreadable (another language, no answer) is unknown everywhere."""
        tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = {"database": tmp / "t.db", "cve_database": tmp / "cve.db"}

        def st(**pw):
            checks = compliance.measure(cfg, pc(**pw), net(), VUL, APPS, TODAY)
            return tuple(by_id([c for g in compliance.judge_framework(k, checks, {})["controls"] for c in g["checks"]])["cfg.pwpolicy"]["status"]
                         for k in ("ce", "certin", "dpdp"))
        self.assertEqual(st(), ("pass", "pass", "pass"))                                         # 14, 90 days, 5 remembered
        self.assertEqual(st(pw_min_length=0, pw_max_age_days=42, pw_history=0), ("warn", "fail", "warn"))     # Windows' defaults
        self.assertEqual(st(pw_min_length=10), ("warn", "pass", "warn"))
        self.assertEqual(st(pw_min_length=12, pw_max_age_days=0), ("pass", "warn", "pass"))      # never expires: CE is content
        self.assertEqual(st(pw_min_length=12, pw_history=0), ("pass", "warn", "pass"))
        for bad in (-1, None, "12", True):
            self.assertEqual(st(pw_min_length=bad), ("unknown", "unknown", "unknown"), bad)
        c = compliance.password_policy_check(pc(pw_min_length=0, pw_max_age_days=42))
        self.assertIn("no minimum length", c["detail"])
        self.assertIn("advises against", c["detail"])                                            # forced expiry
        self.assertEqual(c["fix"], "In an administrator terminal: net accounts /minpwlen:12, or turn on multi-factor login.")
        c = compliance.password_policy_check(pc(pw_min_length=0, pw_max_age_days=0, pw_history=0), "certin")
        self.assertIn("our own suggestion", c["fix"])
        self.assertIn("passwords never expire; old passwords can be used again", c["detail"])

    def test_old_protocols(self):
        """F-7: SMBv1 fails; Remote Desktop without sign-in first is a look, with it a note; Remote Registry and
        PowerShell 2.0 are looks. Anything that is not true/false is unknown, never a pass."""
        st = lambda **o: {c["id"]: c["status"] for c in compliance.protocol_checks(pc(**o))}
        self.assertEqual(st(), {"cfg.smb1": "pass", "cfg.rdp": "pass", "cfg.remreg": "pass", "cfg.psv2": "pass"})
        self.assertEqual(st(smb1_on=True, rdp_on=True, rdp_nla=False, remote_registry_on=True, psv2_present=True),
                         {"cfg.smb1": "fail", "cfg.rdp": "warn", "cfg.remreg": "warn", "cfg.psv2": "warn"})
        self.assertEqual(st(rdp_on=True)["cfg.rdp"], "info")                     # on, with sign-in first
        self.assertEqual(st(rdp_on=True, rdp_nla=None)["cfg.rdp"], "unknown")
        self.assertEqual(st(rdp_on=False, rdp_nla=None)["cfg.rdp"], "pass")      # off: how it would sign in does not matter
        for bad in (None, 0, 1, "False"):
            self.assertEqual(set(st(smb1_on=bad, rdp_on=bad, remote_registry_on=bad, psv2_present=bad).values()), {"unknown"}, bad)
        self.assertIn("Set-SmbServerConfiguration -EnableSMB1Protocol $false", compliance.protocol_checks(pc(smb1_on=True))[0]["fix"])

    def test_builtin_admin_and_unused(self):
        users = lambda *extra: pc()["users"] + list(extra)
        c = by_id(compliance.configuration_checks(pc(users=users({"name": "Administrator", "enabled": True, "password_required": True,
                                                                    "last_logon": "", "sid": "S-1-5-21-1-500"}))))
        self.assertEqual((c["cfg.builtin_admin"]["status"], c["cfg.builtin_admin"]["evidence"], c["cfg.unused"]["evidence"]),
                         ("warn", ["Administrator"], ["Administrator"]))
        renamed = {"name": "Boss", "enabled": True, "password_required": True, "last_logon": "2026-10-01", "sid": "S-1-5-21-1-500"}
        self.assertEqual(by_id(compliance.configuration_checks(pc(users=users(renamed))))["cfg.builtin_admin"]["evidence"], ["Boss"])  # by its id
        self.assertEqual(by_id(compliance.configuration_checks(pc(users=[])))["cfg.builtin_admin"]["status"], "unknown")
        self.assertNotIn("cfg.unused", by_id(compliance.configuration_checks(pc())))                       # none: no line, as before
        self.assertEqual([compliance.builtin_admin_check(x)["status"] for x in (True, False, None, 1)], ["warn", "pass", "unknown", "unknown"])
        self.assertEqual([bool(compliance.unused_check(x)) for x in (2, 0, None, True)], [True, False, False, False])

    def test_wifi(self):
        """F-2: open or WEP fails, WPA (v1) or open networks joined by themselves are a look; no adapter, no check;
        a reading that failed is unknown; the facts are kinds and counts only."""
        w = lambda **o: compliance.wifi_facts(pc(wifi={"adapter": True, "connected": True, "auth": "wpa2", "open_auto": 0, **o}))
        st = lambda **o: compliance.wifi_check(w(**o))["status"]
        self.assertEqual([st(auth=a) for a in ("wpa3", "wpa2", "wpa", "wep", "open", "", "WPA2PSK")],
                         ["pass", "pass", "warn", "fail", "fail", "unknown", "unknown"])
        self.assertEqual([st(connected=False, auth=""), st(open_auto=2), st(connected=False, open_auto=-1), st(connected="yes")],
                         ["pass", "warn", "unknown", "unknown"])
        self.assertIsNone(compliance.wifi_facts(pc(wifi={"adapter": False, "connected": False, "auth": "", "open_auto": -1})))   # no Wi-Fi
        self.assertEqual(compliance.wifi_facts(pc(wifi=None)), {"wifi_connected": None, "wifi_auth": None, "wifi_open_autoconnect": None})
        self.assertEqual(w(connected=False), {"wifi_connected": False, "wifi_auth": None, "wifi_open_autoconnect": 0})
        tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = {"database": tmp / "t.db", "cve_database": tmp / "cve.db"}
        ids = lambda raw: [c["id"] for c in compliance.measure(cfg, raw, net(), VUL, APPS, TODAY)]
        self.assertIn("net.wifi", ids(pc()))
        self.assertNotIn("net.wifi", ids(pc(wifi={"adapter": False})))
        self.assertIn("Connected to an open network", compliance.wifi_check(w(auth="open"))["detail"])

    def test_logs(self):
        """F-10: notes in Cyber Essentials; CERT-In 180 days and DPDP 365 (personal-data devices only) for a log that
        overwrites itself; an archiving log is never failed on its age; unread (no administrator rights) is unknown."""
        tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = {"database": tmp / "t.db", "cve_database": tmp / "cve.db"}

        def st(labels=(), **o):
            checks = compliance.measure(cfg, pc(**o), net(), VUL, APPS, TODAY)
            return {k: tuple(by_id([c for g in compliance.judge_framework(k, checks, {}, labels)["controls"] for c in g["checks"]])[i]["status"]
                             for i in ("log.retention", "log.audit")) for k in ("ce", "certin", "dpdp")}
        self.assertEqual(st(), {"ce": ("info", "pass"), "certin": ("pass", "pass"), "dpdp": ("info", "pass")})       # 284 days, audited
        self.assertEqual(st(("personal_data",)), {"ce": ("info", "pass"), "certin": ("pass", "pass"), "dpdp": ("fail", "pass")})
        self.assertEqual(st(logs={"mode": "circular", "oldest": "2026-09-01"})["certin"], ("fail", "pass"))      # 41 days
        self.assertEqual(st(("personal_data",), logs={"mode": "autobackup", "oldest": "2026-09-01"})["dpdp"], ("pass", "pass"))   # archives
        self.assertEqual(st(audit={"logon": 1, "users": 1}), {"ce": ("info", "info"), "certin": ("pass", "fail"), "dpdp": ("info", "fail")})
        self.assertEqual(st(audit={"logon": 3, "users": 2})["certin"], ("pass", "warn"))
        # not elevated: unknown where the framework asks, a note where it does not (it must not pull a CE area down)
        self.assertEqual(st(logs=None, audit=None), {"ce": ("info", "info"), "certin": ("unknown", "unknown"), "dpdp": ("info", "unknown")})
        self.assertEqual(st(("personal_data",), logs=None, audit=None)["dpdp"], ("unknown", "unknown"))
        v = compliance.judge_framework("ce", compliance.measure(cfg, pc(logs=None, audit=None, usb_storage=None), net(), VUL, APPS, TODAY), {})
        self.assertEqual({g["key"]: g["status"] for g in v["controls"]}["malware"], "pass")
        self.assertEqual(st(logs={"mode": "Circular", "oldest": "2026-01-01"})["certin"][0], "unknown")
        self.assertEqual(st(logs={"mode": "Circular", "oldest": "2026-01-01"})["ce"][0], "info")
        f = compliance.log_facts(pc(), TODAY)
        self.assertEqual(f, {"log_days_security": 284, "log_mode_security": "circular", "audit_logon": True, "audit_account_mgmt": True})
        c = compliance.log_checks({**f, "log_days_security": 10}, "certin")[0]
        self.assertIn("never collects logs", c["fix"])
        self.assertIn("declared, not measured", c["detail"])

    def test_backups(self):
        """F-12: never a fail; no tool is a look in CERT-In and DPDP, a note in Cyber Essentials; unread is unknown
        only where asked."""
        tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = {"database": tmp / "t.db", "cve_database": tmp / "cve.db"}

        def st(**o):
            checks = compliance.measure(cfg, pc(**o), net(), VUL, APPS, TODAY)
            return tuple(by_id([c for g in compliance.judge_framework(k, checks, {})["controls"] for c in g["checks"]])["bak.recent"]["status"]
                         for k in ("ce", "certin", "dpdp"))
        self.assertEqual([st(backups=b) for b in (["agent"], ["onedrive", "filehistory"], [], ["made-up"], None, "agent")],
                         [("pass",) * 3, ("pass",) * 3, ("info", "warn", "warn"), ("info", "warn", "warn"), ("info", "unknown", "unknown"),
                          ("info", "unknown", "unknown")])
        c = compliance.backup_check(compliance.backup_facts(pc(backups=["filehistory", "onedrive"])), "certin")
        self.assertIn("Found: Windows File History, OneDrive folder backup.", c["detail"])
        self.assertIn("not visible from the PC", c["detail"])
        self.assertEqual(compliance.backup_check({"backup_tool": True, "backup_last_days": 9}, "dpdp")["status"], "warn")
        self.assertNotIn("fail", [compliance.backup_check({"backup_tool": t, "backup_last_days": d}, r)["status"]
                                  for t in (True, False, None) for d in (None, 1, 99) for r in ("ce", "certin", "dpdp")])

    def test_usb_storage(self):
        """F-5: allowed USB storage is a note in Cyber Essentials and DPDP, a look in CERT-In (restrict or control,
        not block); blocked or read-only passes; anything else is unknown."""
        tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = {"database": tmp / "t.db", "cve_database": tmp / "cve.db"}

        def st(u):
            checks = compliance.measure(cfg, pc(usb_storage=u), net(), VUL, APPS, TODAY)
            return tuple(by_id([c for g in compliance.judge_framework(k, checks, {})["controls"] for c in g["checks"]])["cfg.usb"]["status"]
                         for k in ("ce", "certin", "dpdp"))
        self.assertEqual([st(u) for u in ("blocked", "read_only", "allowed", "", None, "BLOCKED")],
                         [("pass",) * 3, ("pass",) * 3, ("info", "warn", "info"), ("info", "unknown", "info"), ("info", "unknown", "info"),
                          ("info", "unknown", "info")])
        self.assertIn("CERT-In EMS.4", compliance.usb_check({"usb_storage": "allowed"}, strict=True)["detail"])

    def test_firmware_age(self):
        """F-8: older than 3 years (our own number, and the text says so) is a look; never "out of date"."""
        fw = lambda d: by_id(compliance.update_checks(pc(bios_date=d), None, None, TODAY))["upd.firmware"]
        self.assertEqual([fw(d)["status"] for d in ("2024-03-22", "2023-10-13", "2023-10-11", "2015-01-01", "", None, "2027-01-01")],
                         ["pass", "pass", "warn", "warn", "unknown", "unknown", "unknown"])     # 1095 days is still within
        self.assertIn("our own limit", fw("2015-01-01")["detail"])
        self.assertIn("F39 released 2015-01-01", fw("2015-01-01")["detail"])
        self.assertNotIn("out of date", fw("2015-01-01")["detail"])
        self.assertEqual([compliance.firmware_check(x)["status"] for x in (0, 1095, 1096, -1, None, True, "900")],
                         ["pass", "pass", "warn", "unknown", "unknown", "unknown", "unknown"])

    def test_windows_monthly_release(self):
        due = compliance.security_release_due
        # second Tuesdays: 8 Sep, 13 Oct, 10 Nov 2026; 9 Dec 2025, 13 Jan 2026
        self.assertEqual([due(date.fromisoformat(d)).isoformat() for d in
                          ("2026-10-12", "2026-10-26", "2026-10-27", "2026-11-23", "2026-11-24", "2026-01-26", "2026-01-27")],
                         ["2026-09-08", "2026-09-08", "2026-10-13", "2026-10-13", "2026-11-10", "2025-12-09", "2026-01-13"])
        w = lambda last, today: compliance.windows_update_check(last, "KB1", date.fromisoformat(today))["status"]
        self.assertEqual([w("2026-10-13", "2026-10-27"), w("2026-10-12", "2026-10-27"), w("2026-10-12", "2026-10-26"),
                          w("2026-10-20", "2026-11-23"), w("", "2026-11-23"), w(None, "2026-11-23")],
                         ["pass", "fail", "pass", "pass", "unknown", "unknown"])

    def test_unscored_flaw_counts(self):
        # v3.3: a fix whose severity is not given is due within 14 days like a high or critical one
        self.assertEqual([compliance.high_or_unscored({"score": s}) for s in (9.8, 7.0, 6.9, 0, None)],
                         [True, True, False, False, True])

    def test_updates(self):
        c = by_id(compliance.update_checks(pc(), VUL, APPS, TODAY))
        self.assertEqual({k: v["status"] for k, v in c.items()},
                         {"upd.supported": "pass", "upd.windows": "pass", "upd.firmware": "pass", "upd.automatic": "pass", "upd.flaws": "fail",
                          "upd.coverage": "info", "upd.pending": "warn"})
        # only high or critical flaws older than 14 days count: the 7.5 from a week ago and the 5.0 do not
        self.assertEqual(c["upd.flaws"]["evidence"], ["Kettle Archive 24.08: 1 high or critical, oldest 72 days, fix: update to 25.01"])
        self.assertIn("1 of the flaws is being used in real attacks", c["upd.flaws"]["detail"])
        old = by_id(compliance.update_checks(pc(build=19045, last_update="2026-08-01", no_auto_update=1), None, None, TODAY))
        self.assertEqual({k: v["status"] for k, v in old.items()},
                         {"upd.supported": "fail", "upd.windows": "fail", "upd.firmware": "pass", "upd.automatic": "fail", "upd.flaws": "unknown", "upd.pending": "unknown"})
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


class FrameworksTest(unittest.TestCase):
    """F-0: one measurement, a verdict per framework (docs/spec-india-cert-in-dpdp.md, section 2)."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.cfg = {"database": self.tmp / "t.db", "cve_database": self.tmp / "cve.db"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def verdicts(self, labels=(), **over):
        checks = compliance.measure(self.cfg, pc(**over), net(), VUL, APPS, TODAY)
        return {k: {ch["id"]: ch for g in compliance.judge_framework(k, checks, {}, labels)["controls"] for ch in g["checks"]}
                for k in compliance.FRAMEWORKS}

    def test_the_table_in_the_spec(self):
        unenc = [{"letter": "C:", "protection": 2}]
        v = self.verdicts(lockout_threshold=10, drives=unenc)
        self.assertEqual({k: (x["cfg.unlock"]["status"], x["cfg.encryption"]["status"], x["cfg.lock"]["status"]) for k, x in v.items()},
                         {"ce": ("pass", "info", "pass"), "certin": ("fail", "info", "pass"), "dpdp": ("pass", "info", "pass")})
        self.assertIn("CERT-In asks for 3 to 5", v["certin"]["cfg.unlock"]["detail"])
        self.assertEqual(v["certin"]["cfg.unlock"]["fix"], "In an administrator terminal: net accounts /lockoutthreshold:5")
        self.assertIn("not marked as holding personal data", v["dpdp"]["cfg.encryption"]["detail"])
        # encryption fails only in DPDP, and only on a device labelled as holding personal data
        v = self.verdicts(("personal_data",), drives=unenc)
        self.assertEqual([v[k]["cfg.encryption"]["status"] for k in ("ce", "certin", "dpdp")], ["info", "info", "fail"])
        self.assertIn("Rule 6(1)(a)", v["dpdp"]["cfg.encryption"]["detail"])
        self.assertEqual(self.verdicts(("personal_data",))["dpdp"]["cfg.encryption"]["status"], "pass")      # encrypted: passes
        # CERT-In's 3 to 5: below is stricter (a look, not a fail), never-locking fails everywhere, unreadable is unknown
        st = lambda n: tuple(self.verdicts(lockout_threshold=n)[k]["cfg.unlock"]["status"] for k in ("ce", "certin", "dpdp"))
        self.assertEqual([st(n) for n in (1, 3, 5, 6, 0, -1)],
                         [("pass", "warn", "pass"), ("pass", "pass", "pass"), ("pass", "pass", "pass"), ("pass", "fail", "pass"),
                          ("fail", "fail", "fail"), ("unknown", "unknown", "unknown")])
        # the measured check is never changed by a framework's verdict
        checks = compliance.measure(self.cfg, pc(lockout_threshold=10), net(), VUL, APPS, TODAY)
        compliance.judge_framework("certin", checks, {})
        self.assertEqual(by_id(checks)["cfg.unlock"]["status"], "pass")

    def test_every_check_has_a_place(self):
        ce = {i for _, _, _, ids in compliance.FRAMEWORKS["ce"]["controls"] for i in ids}
        for k, f in compliance.FRAMEWORKS.items():
            ids = [i for _, _, _, x in f["controls"] for i in x]
            self.assertEqual((set(ids), len(ids)), (ce, len(set(ids))), k)             # each check exactly once
        bad = pc(me_admin=True, autoplay_off=0, users=pc()["users"] + [{"name": "old", "enabled": True, "password_required": True, "last_logon": ""}])
        checks = compliance.measure(self.cfg, bad, net(), VUL, APPS, TODAY)
        for k in compliance.FRAMEWORKS:
            j = compliance.judge_framework(k, checks + [compliance._check("zz.new", "A check nobody placed", "fail", "")], {})
            self.assertEqual(sorted(ch["id"] for g in j["controls"] for ch in g["checks"]), sorted([c["id"] for c in checks] + ["zz.new"]), k)

    def test_page_per_framework(self):
        db = self.cfg["database"]
        self.assertEqual(compliance.shown_frameworks(db), ["ce"])                        # nothing changes until chosen
        self.assertFalse(compliance.set_frameworks(db, ["ce", "iso27001"]))
        self.assertFalse(compliance.set_frameworks(db, []))
        self.assertTrue(compliance.set_frameworks(db, ["dpdp", "certin"]))
        self.assertEqual(compliance.shown_frameworks(db), ["certin", "dpdp"])
        self.assertTrue(compliance.accept(db, "acc.daily", "Sole user."))
        self.assertTrue(compliance.declare(db, "perimeter", "yes"))                       # CERT-In's own question
        out = {}
        for k in compliance.FRAMEWORKS:
            v = compliance.assess(self.cfg, pc(me_admin=True, lockout_threshold=10), net(), VUL, APPS, TODAY, k)
            out[k] = v
            acc = [ch for g in v["controls"] for ch in g["checks"] if ch["id"] == "acc.daily"][0]
            self.assertEqual((acc["status"], bool(acc["accepted"])), ("fail", True), k)     # accepted everywhere, failing mark kept
        self.assertEqual([g["key"] for g in out["certin"]["controls"]], ["nes", "ems", "sc", "pm", "rpp", "acim", "lm", "dpbp"])
        self.assertEqual([g["key"] for g in out["dpdp"]["controls"]], ["enc", "access", "cont", "logs", "other"])
        self.assertEqual({k: [q["key"] for q in v["declared"]].count("perimeter") for k, v in out.items()}, {"ce": 0, "certin": 1, "dpdp": 0})
        self.assertEqual([q["answer"] for q in out["certin"]["declared"] if q["key"] == "perimeter"], ["yes"])
        self.assertEqual({g["key"]: g["status"] for g in out["certin"]["controls"]}, {"nes": "pass", "ems": "pass", "sc": "unknown", "pm": "fail", "rpp": "fail", "acim": "pass", "lm": "pass", "dpbp": "pass"})   # sc: no end-of-life list here
        t = {k: compliance.as_text(v) for k, v in out.items()}
        self.assertIn("Judged against: CERT-In Elemental Cyber Defense Controls", t["certin"])
        self.assertIn("may have a yearly baseline audit", t["certin"])
        self.assertNotIn("mandatory", t["certin"].lower())
        self.assertIn("Rule 6 and 7 evidence", t["dpdp"])
        self.assertIn("Not a statement of DPDP compliance", t["dpdp"])
        self.assertNotIn("DPDP compliant", t["dpdp"])
        # one history line per day per framework; lines kept before frameworks existed count as Cyber Essentials
        c = compliance._conn(db)
        c.execute("INSERT INTO compliance_history VALUES ('2026-10-10', ?)", ('{"controls": {"firewalls": "pass"}}',))
        c.commit()
        c.close()
        for v in out.values():
            compliance.record(self.cfg, v, TODAY)
        self.assertEqual([h["day"] for h in compliance.history(self.cfg, 90, TODAY)], ["2026-10-10", "2026-10-12"])
        self.assertEqual([(h["day"], sorted(h["controls"])) for h in compliance.history(self.cfg, 90, TODAY, "dpdp")],
                         [("2026-10-12", ["access", "cont", "enc", "logs", "other"])])
        self.assertEqual(compliance.brief(self.cfg, TODAY)["framework"], "certin")                 # the dashboard follows the first shown


class PageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.cfg = {"database": self.tmp / "t.db", "cve_database": self.tmp / "cve.db"}     # never this PC's real CVE copy

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
