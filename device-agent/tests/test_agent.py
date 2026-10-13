"""The device agent: what a release must be before it is installed, how the agent enrols and keeps its folder
to itself, how it reads a PC as a service, and what the installer may contain. No server is contacted, nothing
is installed, and the release key used here is made for the test.

Run with the other agent's Python:  ..\\shadow-filer\\.venv\\Scripts\\python -m unittest discover -s tests
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))
import agent  # noqa: E402  (adds shadow-filer/ to the path)
import apps  # noqa: E402
import fleet  # noqa: E402
import make_msi  # noqa: E402
import release  # noqa: E402
import selfupdate  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

LOG = logging.getLogger("test-sfagent")
LOG.addHandler(logging.NullHandler())
LOG.propagate = False


def new_pem() -> bytes:
    return Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                      serialization.NoEncryption())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sfagent-test-"))
        self.cfg = agent.config(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def enrol(self):
        fleet.enrol(self.cfg, "https://fleet.example.com", "sfe_x", send=lambda *a: {"device_id": "dev-1"})


class ReleaseTest(Base):
    def test_only_what_the_release_key_signed(self):
        pem, other = new_pem(), new_pem()
        keys = (release.public_of(pem),)
        data = b"an installer"
        text = release.manifest("1.2.3", "ShadowFilerAgent-1.2.3.msi", data)
        sig = release.sign(text, pem)
        m = release.verify(text, sig, keys)
        self.assertEqual((m["version"], m["size"]), ("1.2.3", len(data)))
        release.check_package(m, data)
        self.assertRaises(ValueError, release.check_package, m, data + b"!")
        self.assertRaises(ValueError, release.verify, text, release.sign(text, other), keys)       # somebody else's key
        self.assertRaises(ValueError, release.verify, text.replace("1.2.3", "1.2.4"), sig, keys)   # changed after signing
        self.assertRaises(ValueError, release.verify, text, "not base64!", keys)
        self.assertRaises(ValueError, release.verify, text, "", keys)
        self.assertRaises(ValueError, release.verify, text, sig)                                   # the real key did not sign this
        self.assertEqual(release.verify(text, sig, (release.public_of(other), keys[0]))["version"], "1.2.3")   # while a key is being replaced

    def test_a_signed_manifest_must_still_describe_our_installer(self):
        pem = new_pem()
        keys = (release.public_of(pem),)
        good = json.loads(release.manifest("1.2.3", "a.msi", b"x"))
        for change in ({"product": "Something Else"}, {"version": "1.2"}, {"version": "1.2.3-beta"}, {"file": "..\\..\\evil.msi"},
                       {"file": "C:/x.msi"}, {"file": "a.exe"}, {"file": "a.msi "}, {"file": "%TEMP%.msi"}, {"size": 0}, {"size": True},
                       {"size": release.MAX_PACKAGE + 1}, {"size": "1"}, {"sha256": "abc"}, {"sha256": None}):
            text = json.dumps({**good, **change})
            self.assertRaises(ValueError, release.verify, text, release.sign(text, pem), keys)
        for text in ("[]", "not json", '"text"'):
            self.assertRaises(ValueError, release.verify, text, release.sign(text, pem), keys)

    def test_versions_are_compared_as_numbers(self):
        self.assertTrue(release.newer("0.10.0", "0.9.9"))
        self.assertTrue(release.newer("1.0.0", "0.99.99"))
        for a, b in (("0.4.0", "0.4.0"), ("0.3.9", "0.4.0"), ("1.0", "0.4.0"), ("9.9.9.9", "0.4.0"), ("", "0.4.0"), ("9.9.9", "dev"), ("١.٢.٣", "0.4.0")):
            self.assertFalse(release.newer(a, b), (a, b))

    def test_the_key_in_the_source_is_a_public_key(self):
        import base64
        for k in release.RELEASE_KEYS:
            self.assertEqual(len(base64.b64decode(k)), 32)
        self.assertEqual(agent.VERSION, ".".join(str(n) for n in release.version_tuple(agent.VERSION)))


class UpdateTest(Base):
    def setUp(self):
        super().setUp()
        self.pem = new_pem()
        self.keys = (release.public_of(self.pem),)
        self.data = b"MSI" * 1000
        self.enrol()
        self.ran = []

    def server(self, version="0.5.0", data=None, pem=None, manifest=None, send=None):
        data = self.data if data is None else data
        text = manifest or release.manifest(version, f"ShadowFilerAgent-{version}.msi", data)
        sig = release.sign(text, pem or self.pem)
        asked = []

        def call(server, path, body=None, sign=None, limit=0):
            asked.append((path, sorted(sign("GET", path, b"")), limit))
            if path == "/api/v1/agent/release":
                return {"version": version, "manifest": text, "signature": sig}
            return send if send is not None else data
        call.asked = asked
        return call

    def update(self, call, offered="0.5.0", now=None, **more):
        fleet._save(self.cfg, release=offered)
        return selfupdate.maybe(self.cfg, "0.4.0", self.tmp / "updates", log=LOG, call=call, keys=self.keys, now=now,
                                install=lambda package, log_file: self.ran.append((package, package.read_bytes())), **more)

    def test_a_good_release_is_installed(self):
        call = self.server()
        self.assertEqual(self.update(call), "installing 0.5.0")
        package, content = self.ran[0]
        self.assertEqual((package.name, package.parent, content), ("ShadowFilerAgent-0.5.0.msi", self.tmp / "updates", self.data))
        # both requests were signed by this PC, and the download was told how much to accept at most
        self.assertEqual(call.asked, [("/api/v1/agent/release", ["X-Device", "X-Signature", "X-Stamp"], 0),
                                      ("/api/v1/agent/package/0.5.0", ["X-Device", "X-Signature", "X-Stamp"], len(self.data))])

    def test_nothing_else_is(self):
        cases = {
            "another key signed it": self.server(pem=new_pem()),
            "the installer was swapped": self.server(send=b"EVIL" * 750),
            "the installer is cut short": self.server(send=self.data[:-1]),
            "an old release offered as new": self.server(version="0.3.0"),
            "the same version again": self.server(version="0.4.0"),
            "a manifest for another product": self.server(manifest=json.dumps({"product": "Other", "version": "0.5.0", "file": "a.msi", "size": 3, "sha256": "0" * 64})),
        }
        for why, call in cases.items():
            fleet._save(self.cfg, update_try=None)
            got = self.update(call)
            self.assertTrue(got.startswith("failed: "), (why, got))
        self.assertEqual(self.ran, [])
        self.assertEqual(list((self.tmp / "updates").glob("*.msi")) if (self.tmp / "updates").exists() else [], [])
        self.assertTrue(fleet.state(self.cfg)["update_error"])

    def test_when_it_does_not_even_ask(self):
        call = self.server()
        for offered in ("0.4.0", "0.3.9", "", "latest"):
            self.assertEqual(self.update(call, offered=offered), "up to date")
        fleet._save(self.cfg, updates="off")
        self.assertEqual(self.update(call), "off")
        fleet._save(self.cfg, updates=None)
        self.assertIn("development run", self.update(call, installed=False))
        self.assertEqual((call.asked, self.ran), ([], []))

    def test_a_version_that_does_not_take_is_left_alone(self):
        bad, t = self.server(pem=new_pem()), datetime(2026, 10, 13, 9)
        self.assertTrue(self.update(bad, now=t).startswith("failed"))
        self.assertEqual(self.update(bad, now=t + timedelta(hours=1)), "waiting before trying again")
        self.assertTrue(self.update(bad, now=t + timedelta(hours=7)).startswith("failed"))
        self.assertTrue(self.update(bad, now=t + timedelta(hours=14)).startswith("failed"))
        self.assertIn("left alone", self.update(self.server(), now=t + timedelta(days=30)))        # three tries, then never again
        self.assertEqual(self.ran, [])
        self.assertEqual(self.update(self.server(version="0.6.0"), offered="0.6.0", now=t + timedelta(days=30)), "installing 0.6.0")   # a newer one is a new start


class AgentTest(Base):
    def test_enrolling_from_what_the_installer_left(self):
        left = {"Server": "https://fleet.example.com", "Token": "sfe_once"}

        def registry(write=None, delete=()):
            for name in delete:
                left.pop(name, None)
            return dict(left)
        t = datetime(2026, 10, 13, 9)
        with mock.patch.object(fleet, "enrol", side_effect=RuntimeError("The server could not be reached (timed out).")) as enrol:
            self.assertIn("could not be reached", agent.enrol_if_asked(self.cfg, LOG, registry, now=t))
            self.assertIsNone(agent.enrol_if_asked(self.cfg, LOG, registry, now=t + timedelta(minutes=1)))      # not every minute
            self.assertEqual(enrol.call_count, 1)
            for i in range(1, agent.ENROL_TRIES):
                agent.enrol_if_asked(self.cfg, LOG, registry, now=t + timedelta(minutes=6 * i))
            self.assertEqual((enrol.call_count, "Token" in left, "Server" in left), (agent.ENROL_TRIES, False, True))    # given up: the token does not lie about
            self.assertIn("could not be reached", agent.status_text(self.cfg))
        left["Token"] = "sfe_second"
        with mock.patch.object(fleet, "call", return_value={"device_id": "dev-9"}) as call:
            self.assertIsNone(agent.enrol_if_asked(self.cfg, LOG, registry, now=t + timedelta(hours=3)))
        self.assertEqual((left, call.call_args[0][2]["token"], fleet.status(self.cfg)["device_id"]), ({}, "sfe_second", "dev-9"))
        text = agent.status_text(self.cfg)
        self.assertIn("enrolled:     yes, with https://fleet.example.com", text)
        self.assertNotIn("sfe_", text + json.dumps(fleet.state(self.cfg)))                # the token is kept nowhere
        self.assertIsNone(agent.enrol_if_asked(self.cfg, LOG, registry))                  # nothing left to do

    def test_a_persons_settings_outlast_their_signing_out(self):
        base = {"as_system": True, "computer": "DEMO-PC", "me_admin": False}
        signed_in = {**base, "user_hive": True, "screensaver": {"active": "1", "secure": "1", "timeout": "300"}, "autoplay_off": 1}
        signed_out = {**base, "user_hive": False, "screensaver": {"active": "", "secure": "", "timeout": ""}, "autoplay_off": 0}
        with mock.patch("compliance.read_posture", return_value=dict(signed_out)):
            self.assertEqual(agent.read_posture(self.cfg)["autoplay_off"], 0)             # never seen signed in: nothing to go by
        with mock.patch("compliance.read_posture", return_value=dict(signed_in)):
            self.assertEqual(agent.read_posture(self.cfg)["screensaver"]["timeout"], "300")
        with mock.patch("compliance.read_posture", return_value=dict(signed_out)):
            got = agent.read_posture(self.cfg)
        self.assertEqual((got["screensaver"]["timeout"], got["autoplay_off"], got["user_hive"]), ("300", 1, False))
        ordinary = {"as_system": False, "user_hive": True, "autoplay_off": 0, "screensaver": {}}
        with mock.patch("compliance.read_posture", return_value=dict(ordinary)):          # not a service: as read
            self.assertEqual(agent.read_posture(self.cfg), ordinary)
        with mock.patch("compliance.read_posture", return_value=None):
            self.assertIsNone(agent.read_posture(self.cfg))

    def test_a_persons_programs_outlast_their_signing_out(self):
        def entry(name, owner=None):
            return {"id": "user:" + name, "scope": "user" if owner else "machine", "arch": "", "changed": 1.0,
                    "values": {"DisplayName": name, "DisplayVersion": "1.0", "UninstallString": "C:\\Users\\ada\\x.exe", "Blob": b"\x00"},
                    **({"owner": owner} if owner else {})}
        ada, bo, gone = "S-1-5-21-1-2-3-1001", "S-1-12-1-9-9-9-9", "S-1-5-21-1-2-3-1009"

        def read(raw, loaded, have=(ada, bo)):
            with mock.patch("apps.read_desktop", return_value=list(raw)), mock.patch("apps.running_as_system", return_value=True), \
                    mock.patch("apps.loaded_users", return_value=list(loaded)), mock.patch("agent.profiles", return_value=set(have)):
                return sorted(a["name"] for a in apps.desktop_apps(agent.read_desktop(self.cfg)))
        machine = [entry("Kettle Archive")]
        self.assertEqual(read(machine + [entry("Ada's Editor", ada), entry("Bo's Player", bo)], [ada, bo]),
                         ["Ada's Editor", "Bo's Player", "Kettle Archive"])
        self.assertEqual(read(machine + [entry("Bo's Player", bo)], [bo]), ["Ada's Editor", "Bo's Player", "Kettle Archive"])   # Ada signed out
        self.assertEqual(read(machine, []), ["Ada's Editor", "Bo's Player", "Kettle Archive"])                                    # nobody signed in
        self.assertEqual(read(machine + [entry("Bo's Player", bo)], [ada, bo]), ["Bo's Player", "Kettle Archive"])                # Ada removed hers
        self.assertEqual(read(machine, [], have=(ada,)), ["Kettle Archive"])                                                       # Bo's profile is gone
        kept = fleet.state(self.cfg)["user_programs"]
        self.assertNotIn("UninstallString", kept)                 # only the few values a program is listed by
        old = entry("Old Thing", gone)
        del old["values"]["Blob"]
        fleet._save(self.cfg, user_programs=json.dumps({gone: [old]}))
        self.assertEqual(read(machine, []), ["Kettle Archive"])   # an account without a profile here is forgotten
        with mock.patch("apps.read_desktop", return_value=machine), mock.patch("apps.running_as_system", return_value=False):
            self.assertEqual(agent.read_desktop(self.cfg), machine)

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_a_folder_somebody_else_made_is_not_believed(self):
        folder = self.tmp / "ShadowFiler Agent"
        folder.mkdir()
        (folder / "agent.db").write_text("planted")
        me = agent.owner_of(folder)
        self.assertRegex(me or "", r"^S-1-")
        if me in agent.TRUSTED_OWNERS:
            self.skipTest("run from an administrator's prompt: every folder made here belongs to Administrators")
        try:
            agent.secure(folder)
            aside = [p for p in self.tmp.iterdir() if ".not-ours-" in p.name]
            self.assertEqual((len(aside), (aside[0] / "agent.db").read_text()), (1, "planted"))
            acl = subprocess.run(["icacls", str(folder)], capture_output=True, text=True).stdout
            self.assertIn("NT AUTHORITY\\SYSTEM:(OI)(CI)(F)", acl)
            self.assertEqual((acl.count(":("), "BUILTIN\\Administrators:(OI)(CI)(F)" in acl), (2, True))      # those two and nobody else
            self.assertRaises(PermissionError, lambda: list(folder.iterdir()))        # closed, even to the one who made it
        finally:
            subprocess.run(["icacls", str(folder), "/reset"], capture_output=True)

    def test_what_the_installer_holds(self):
        files = set(make_msi.SHARED) | set(make_msi.OWN)
        self.assertEqual(files & make_msi.NEVER, set())
        for name in make_msi.SHARED:
            self.assertTrue((ROOT.parent / "shadow-filer" / name).is_file(), name)
        for name in make_msi.OWN:
            self.assertTrue((ROOT / name).is_file(), name)
        # and the agent, as far as it gets building a report, loads nothing else of ours
        code = ("import sys, json; sys.argv=['x']; import agent, fleet, apps, services, network, compliance, selfupdate, release, winsvc;"
                "from unittest import mock;"
                "p = mock.patch.multiple;"
                "import tempfile; d = tempfile.mkdtemp(); cfg = agent.config(__import__('pathlib').Path(d));"
                "a = mock.patch('apps.read_desktop', return_value=[]); b = mock.patch('apps.read_packaged', return_value=[]);"
                "c = mock.patch('services.read_services', return_value=[]); n = mock.patch('network.view', return_value={'read_at': None});"
                "q = mock.patch('compliance.read_posture', return_value={'computer': 'X', 'build': 26200});"
                "[m.start() for m in (a, b, c, n, q)]; apps.scan(cfg); out = fleet.payload(cfg, settings=agent.SETTINGS, posture=lambda: agent.read_posture(cfg));"
                "ours = sorted(m for m in sys.modules if getattr(sys.modules[m], '__file__', None) and "
                "('shadow-filer' in sys.modules[m].__file__ or 'device-agent' in sys.modules[m].__file__) and '.venv' not in sys.modules[m].__file__);"
                "print(json.dumps([ours, sorted(out['snapshots']), out['agent_version']]))")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        loaded, kinds, version = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(sorted(m + ".py" for m in loaded), sorted(files))
        self.assertEqual((kinds, version), (["apps", "device", "posture", "services"], agent.VERSION))


if __name__ == "__main__":
    unittest.main()
