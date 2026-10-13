"""Fleet: enrolment, check-in, and above all WHAT is sent. Made-up PC facts go in full of things that must
never leave (account names, paths, addresses); the test checks none of them come out. No server is contacted."""
import base64
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apps  # noqa: E402
import fleet  # noqa: E402
from test_compliance import pc  # noqa: E402
from test_network import raw as net_raw  # noqa: E402
import network  # noqa: E402

SECRET_USER = "alexandra.private"
SERVICES = [{"name": "TessSvc", "display": "Tessellate Engine", "state": "Running", "start": "Auto", "account": "LocalSystem",
             "exe": f"C:\\Users\\{SECRET_USER}\\AppData\\tess\\engine.exe", "pid": 100, "company": "Tessellate Inc.",
             "product": "Tessellate", "version": "4.94.0", "listens": ["0.0.0.0|27017"]}]


def reg(sub, name, version, **more):
    return {"id": "machine64:" + sub, "scope": "machine", "arch": "64-bit", "changed": 0,
            "values": {"DisplayName": name, "DisplayVersion": version, **more}}


class FleetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sf-test-"))
        self.cfg = {"database": self.tmp / "t.db", "cve_database": self.tmp / "cve.db", "library": {"check_updates": True}}
        apps.scan(self.cfg, packaged=lambda: [], now=datetime(2026, 10, 12, 9), desktop=lambda: [
            reg("k", "Kettle Archive", "24.08", Publisher="Kettle Software", InstallLocation=f"C:\\Users\\{SECRET_USER}\\Kettle"),
            reg("n", "Notes", "1.0")])
        posture = pc(user=SECRET_USER, computer="DEMO-PC",
                     users=[{"name": SECRET_USER, "enabled": True, "password_required": False, "last_logon": "2026-10-12", "sid": "S-1-5-21-1-1001"}],
                     admins=[{"name": f"DEMO-PC\\{SECRET_USER}", "kind": "User"}], me_admin=True)
        shares = [{"name": "FamilyPhotos", "path": f"C:\\Users\\{SECRET_USER}\\Pictures", "type": 0, "description": ""}]
        rules = ["v2.31|Action=Allow|Active=TRUE|Dir=In|App=C:\\Apps\\harbor.exe|Name=Harbor|"]
        view = network.tidy(net_raw(shares=shares, rules=rules, hosts=["10.9.8.7 secret-host.example"]))
        for p in (mock.patch("compliance._posture", return_value=posture), mock.patch("services.read_services", return_value=SERVICES),
                  mock.patch("network.peek", return_value=view)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_what_is_sent_and_what_never_is(self):
        p = fleet.payload(self.cfg)
        sn = p["snapshots"]
        self.assertEqual(sorted(sn), ["apps", "device", "network", "posture", "services"])
        self.assertEqual(sn["device"], {"name": "DEMO-PC", "manufacturer": "Contoso", "model": "Tower 5", "serial": "SN123",
                                        "windows": "Windows 11 Professional 25H2", "build": "26200.1234"})
        self.assertEqual(sorted(sn["apps"]["apps"][0]), ["arch", "available", "date_is", "from_store", "installed", "kind", "name",
                                                         "publisher", "scope", "size", "update_to", "version"])
        self.assertEqual([a["name"] for a in sn["apps"]["apps"]], ["Kettle Archive", "Notes"])
        svc = sn["services"]["services"][0]
        self.assertEqual((svc["name"], svc["account"], svc["ports"], svc["exposed"]), ("Tessellate Engine", "system", [{"port": 27017, "network": True}], True))
        self.assertEqual(sn["posture"]["accounts_without_password"], 1)        # a count, not who
        self.assertEqual((sn["posture"]["daily_account_is_admin"], sn["posture"]["admin_accounts"], sn["posture"]["drives_encrypted"]), (True, 1, True))
        self.assertEqual((sn["network"]["shared_folders"], sn["network"]["rules"]["programs"]), (1, 1))
        self.assertEqual(sorted(sn["network"]["listening"][0]), ["port", "process", "proto", "reach", "windows"])
        self.assertEqual(sorted(sn["network"]["interfaces"][0]), ["category", "internet", "kind", "up"])
        sent = json.dumps(p)
        for never in (SECRET_USER, "C:\\\\", "AppData", "engine.exe", "harbor.exe", "FamilyPhotos", "Pictures", "192.168.", "93.184.216.34",
                      "AA-BB-CC", "11-22-33", "secret-host", "10.9.8.7", "fe80", "S-1-5-21", "DEMO-PC\\\\"):
            self.assertNotIn(never, sent, never)
        text = fleet.as_text(p)
        self.assertIn("apps      2 programs", text)
        self.assertIn("Not sent: files and documents, account names", text)

    def test_enrol_checkin_leave(self):
        calls = []

        def send(server, path, body=None, sign=None):
            data = json.dumps(body).encode()
            calls.append((server + path, sign("POST", path, data), body, data))
            if path.endswith("/enrol"):
                return {"device_id": "dev-1", "checkin_seconds": 900}
            return {"ok": True, "stored": ["apps", "device"], "agent_release": "0.9.0"}
        self.assertFalse(fleet.due(self.cfg))                                  # not enrolled: never
        self.assertEqual(fleet.checkin(self.cfg, send=send)["message"], "This PC is not enrolled.")
        st = fleet.enrol(self.cfg, "https://fleet.example.com/", "sfe_token", send=send, now=datetime(2026, 10, 12, 9))
        self.assertEqual((st["enrolled"], st["server"], st["device_id"]), (True, "https://fleet.example.com", "dev-1"))
        url, head, body, data = calls[0]
        self.assertEqual((url, sorted(body), sorted(head)), ("https://fleet.example.com/api/v1/enrol",
                                                             ["agent_version", "name", "public_key", "token"], ["X-Signature", "X-Stamp"]))
        # the PC made the key pair: the server is sent the public half, and a signature only the private half can make
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(body["public_key"]))

        def check(head, method, path, data):
            text = f"SFv1\n{method}\n{path}\n{head['X-Stamp']}\n{hashlib.sha256(data).hexdigest()}".encode()
            public.verify(base64.b64decode(head["X-Signature"]), text)          # raises when it does not fit
        check(head, "POST", "/api/v1/enrol", data)
        # the private half is kept sealed, and is in nothing the console or the log is given
        kept = fleet.state(self.cfg)["device_private"]
        private = fleet._seal(base64.b64decode(kept), False)
        self.assertEqual((len(private), private in base64.b64decode(kept)), (32, False))
        self.assertNotIn(kept, json.dumps(st))
        self.assertNotIn("device_private", json.dumps(st))
        self.assertRaises(RuntimeError, fleet.enrol, self.cfg, "https://other.example.com", "t", send)     # one server at a time
        self.assertTrue(fleet.due(self.cfg, now=datetime(2026, 10, 12, 9)))
        r = fleet.checkin(self.cfg, send=send, now=datetime(2026, 10, 12, 9, 1))
        url, head, body, data = calls[-1]
        self.assertEqual((r["ok"], r["stored"], r["release"], url), (True, ["apps", "device"], "0.9.0", "https://fleet.example.com/api/v1/checkin"))
        self.assertEqual(head["X-Device"], "dev-1")
        check(head, "POST", "/api/v1/checkin", data)
        self.assertRaises(Exception, check, head, "POST", "/api/v1/checkin", data + b" ")      # one more byte and it no longer fits
        sign = fleet.own_signer(self.cfg)
        stamps = [int(sign("GET", "/x", b"")["X-Stamp"]) for _ in range(50)]
        self.assertEqual(stamps, sorted(set(stamps)))                          # each request a later stamp than the one before
        self.assertFalse(fleet.due(self.cfg, now=datetime(2026, 10, 12, 9, 10)))
        self.assertTrue(fleet.due(self.cfg, now=datetime(2026, 10, 12, 9, 16)))

        def down(server, path, body=None, sign=None):
            raise RuntimeError("The server could not be reached (timed out).")
        r = fleet.checkin(self.cfg, send=down, now=datetime(2026, 10, 12, 9, 20))
        self.assertEqual((r["ok"], fleet.status(self.cfg)["last_error"], fleet.status(self.cfg)["last_ok"]),
                         (False, "The server could not be reached (timed out).", "2026-10-12T09:01:00"))
        self.assertFalse(fleet.due(self.cfg, now=datetime(2026, 10, 12, 9, 25)))       # a failure is not retried every tick
        fleet.leave(self.cfg)
        self.assertEqual((fleet.status(self.cfg)["enrolled"], fleet.state(self.cfg).get("device_private")), (False, None))
        self.assertFalse(fleet.due(self.cfg))
        # a PC enrolled before key pairs has to enrol again, and is told so
        fleet._save(self.cfg, server="https://fleet.example.com", device_id="dev-0", device_key="OLD-KEY")
        st = fleet.status(self.cfg)
        self.assertEqual((st["enrolled"], "enrol it again" in st["last_error"], fleet.due(self.cfg)), (False, True, False))
        self.assertIn("enrol it again", fleet.checkin(self.cfg, send=send)["message"])

    def test_only_https(self):
        for ok in ("https://fleet.example.com", "https://fleet.example.com/base/", "http://localhost:8770", "http://127.0.0.1:8770"):
            self.assertTrue(fleet.check_server(ok).startswith("http"), ok)
        for bad in ("http://fleet.example.com", "ftp://x", "fleet.example.com", "", "https://user:pw@fleet.example.com", "https://fleet.example.com/?a=1"):
            self.assertRaises(ValueError, fleet.check_server, bad)
        self.assertRaises(ValueError, fleet.enrol, self.cfg, "http://fleet.example.com", "t")


if __name__ == "__main__":
    unittest.main()
