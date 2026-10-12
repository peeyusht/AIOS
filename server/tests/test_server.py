"""Fleet server, phase 1. Runs against a throwaway database in the PostgreSQL started by docker-compose
(127.0.0.1:5433); skipped when that is not running. The important tests are the ones that try to cross from
one organisation to another: through the API, and directly in SQL as the application's database role."""
import os
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OWNER = os.environ.get("TEST_DATABASE_URL_OWNER", "postgresql://postgres:postgres@127.0.0.1:5433/postgres")
APP_PASSWORD = os.environ.get("FLEET_APP_PASSWORD", "fleet_app")
NAME = "fleet_test_" + uuid.uuid4().hex[:10]

try:
    import psycopg
    from psycopg import sql
    with psycopg.connect(OWNER, autocommit=True, connect_timeout=3) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(NAME)))
    READY = True
except Exception as e:  # no database server: nothing here can run
    READY, WHY = False, str(e).splitlines()[0][:120]

if READY:
    base = OWNER.rsplit("/", 1)[0]
    os.environ["DATABASE_URL_OWNER"] = f"{base}/{NAME}"
    os.environ["DATABASE_URL"] = f"postgresql://fleet_app:{APP_PASSWORD}@{base.split('@', 1)[1]}/{NAME}"
    from fastapi.testclient import TestClient
    from app import db, manage
    from app.main import app, MAX_BODY


def tearDownModule():
    if READY:
        db.close()
        with psycopg.connect(OWNER, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(NAME)))


SNAP = {"device": {"name": "DEMO-PC", "manufacturer": "Contoso", "model": "Tower 5", "windows": "Windows 11 Professional 25H2"},
        "apps": {"apps": [{"name": "Kettle Archive", "version": "24.08", "kind": "desktop", "available": "25.01"},
                          {"name": "Notes", "version": "1.0", "kind": "desktop", "available": None},
                          {"name": "Sketch Pad", "version": "2.1", "kind": "packaged", "available": None}]},
        "network": {"firewall": [{"name": "Domain", "enabled": True}, {"name": "Private", "enabled": False}, {"name": "Public", "enabled": True}],
                    "listening": [{"port": 27017, "reach": "network", "windows": False}, {"port": 135, "reach": "network", "windows": True}]},
        "posture": {"antivirus_on": True, "drives_encrypted": False, "daily_account_is_admin": True}}


@unittest.skipUnless(READY, "PostgreSQL on 127.0.0.1:5433 is not running (docker compose up -d db)")
class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with manage.connect() as c:
            c.execute(manage.SCHEMA.read_text(encoding="utf-8"))          # the tables; fleet_app's password is left alone
            c.execute(manage.SCHEMA.read_text(encoding="utf-8"))          # and running it again is harmless
            cls.org_a, cls.org_b = manage.create_org(c, "Acme Ltd"), manage.create_org(c, "Globex")
            cls.admin_a, cls.admin_b = manage.create_admin_key(c, cls.org_a), manage.create_admin_key(c, cls.org_b)
            cls.token_a = manage.create_token(c, cls.org_a, uses=2)
            cls.token_b = manage.create_token(c, cls.org_b, uses=1)
            cls.expired = manage.create_token(c, cls.org_a, uses=5, days=-1)
        cls.http = TestClient(app)

    def auth(self, key):
        return {"Authorization": "Bearer " + key}

    def enrol(self, token, name="DEMO-PC"):
        return self.http.post("/api/v1/enrol", json={"token": token, "name": name, "agent_version": "0.1"})

    def test_1_enrol_and_report(self):
        r = self.enrol(self.token_a)
        self.assertEqual(r.status_code, 200, r.text)
        key, dev = r.json()["device_key"], r.json()["device_id"]
        type(self).key_a, type(self).dev_a = key, dev
        with manage.connect() as c:      # only hashes are stored: neither the token nor the key is in the database
            everything = " ".join(str(x) for row in c.execute("SELECT key_hash FROM devices UNION ALL SELECT token_hash FROM enrolment_tokens UNION ALL SELECT key_hash FROM admin_keys") for x in row)
        for secret in (key, self.token_a, self.admin_a):
            self.assertNotIn(secret, everything)
        r = self.http.post("/api/v1/checkin", headers=self.auth(key), json={"agent_version": "0.1", "snapshots": SNAP})
        self.assertEqual((r.status_code, sorted(r.json()["stored"])), (200, ["apps", "device", "network", "posture"]))
        r = self.http.post("/api/v1/checkin", headers=self.auth(key), json={"agent_version": "0.1", "snapshots": SNAP})
        self.assertEqual(r.json()["stored"], [])                         # nothing changed: nothing kept
        changed = {**SNAP, "posture": {**SNAP["posture"], "drives_encrypted": True}}
        r = self.http.post("/api/v1/checkin", headers=self.auth(key), json={"agent_version": "0.2", "snapshots": changed})
        self.assertEqual(r.json()["stored"], ["posture"])
        fleet = self.http.get("/api/v1/devices", headers=self.auth(self.admin_a)).json()
        d = fleet["devices"][0]
        self.assertEqual((fleet["organisation"], len(fleet["devices"]), d["name"], d["agent_version"]), ("Acme Ltd", 1, "DEMO-PC", "0.2"))
        self.assertEqual(d["summary"], {"windows": "Windows 11 Professional 25H2", "model": "Contoso Tower 5", "programs": 2, "updates": 1,
                                        "firewall": "partly", "ports_open": 1, "antivirus": True, "encrypted": True, "daily_admin": True})
        detail = self.http.get(f"/api/v1/devices/{dev}", headers=self.auth(self.admin_a)).json()
        self.assertEqual({h["kind"]: h["versions"] for h in detail["history"]}, {"apps": 1, "device": 1, "network": 1, "posture": 2})
        self.assertTrue(detail["snapshots"]["posture"]["payload"]["drives_encrypted"])
        log = self.http.get("/api/v1/audit", headers=self.auth(self.admin_a)).json()["entries"]
        self.assertEqual((log[0]["action"], log[0]["detail"]["name"]), ("device.enrolled", "DEMO-PC"))

    def test_2_tokens_run_out_and_expire(self):
        self.assertEqual(self.enrol(self.token_a, "SECOND-PC").status_code, 200)       # its second and last use
        for token in (self.token_a, self.expired, "sfe_made_up", ""):
            self.assertIn(self.enrol(token).status_code, (400, 403), token)
        self.assertEqual(self.enrol(self.token_a, "").status_code, 400)

    def test_3_bad_requests(self):
        for headers in ({}, {"Authorization": "Bearer nope"}, self.auth("x" * 43), self.auth(self.admin_a)):
            self.assertEqual(self.http.post("/api/v1/checkin", headers=headers, json={"snapshots": {}}).status_code, 401)
        self.assertEqual(self.http.get("/api/v1/devices", headers=self.auth(self.key_a)).status_code, 401)   # a device key is not a console key
        bad = self.http.post("/api/v1/checkin", headers=self.auth(self.key_a), json={"snapshots": {"files": {}}})
        self.assertEqual(bad.status_code, 400)                                        # only the five known kinds
        self.assertEqual(self.http.post("/api/v1/checkin", headers=self.auth(self.key_a), json={"snapshots": {"apps": "text"}}).status_code, 400)
        big = self.http.post("/api/v1/checkin", headers=self.auth(self.key_a), content=b"x" * (MAX_BODY + 1))
        self.assertEqual(big.status_code, 413)
        self.assertEqual(self.http.get("/healthz").json(), {"ok": True})
        page = self.http.get("/")
        self.assertEqual((page.status_code, "default-src 'self'" in page.headers["content-security-policy"]), (200, True))

    def test_4_one_organisation_cannot_see_another(self):
        other = self.enrol(self.token_b, "GLOBEX-PC").json()
        self.http.post("/api/v1/checkin", headers=self.auth(other["device_key"]), json={"snapshots": {"device": {"name": "GLOBEX-PC"}}})
        # through the API
        a = self.http.get("/api/v1/devices", headers=self.auth(self.admin_a)).json()
        b = self.http.get("/api/v1/devices", headers=self.auth(self.admin_b)).json()
        self.assertEqual((sorted(d["name"] for d in a["devices"]), [d["name"] for d in b["devices"]]), (["DEMO-PC", "SECOND-PC"], ["GLOBEX-PC"]))
        self.assertEqual(self.http.get(f"/api/v1/devices/{self.dev_a}", headers=self.auth(self.admin_b)).status_code, 404)
        self.assertEqual(self.http.get(f"/api/v1/devices/{other['device_id']}", headers=self.auth(self.admin_a)).status_code, 404)
        self.assertEqual(self.http.get("/api/v1/audit", headers=self.auth(self.admin_b)).json()["entries"][0]["detail"]["name"], "GLOBEX-PC")
        # and in SQL, as the role the API uses: this is what holds even if a query in the application is wrong
        with db.anon() as c:                                    # no organisation set: nothing at all
            for table in ("devices", "snapshots", "audit_log", "enrolment_tokens", "admin_keys", "organisations"):
                self.assertEqual(c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"], 0, table)
        with db.org(self.org_b) as c:
            self.assertEqual([r["name"] for r in c.execute("SELECT name FROM devices")], ["GLOBEX-PC"])
            self.assertEqual(c.execute("SELECT count(*) AS n FROM devices WHERE id = %s", (self.dev_a,)).fetchone()["n"], 0)
            self.assertEqual(c.execute("UPDATE devices SET name = 'taken' WHERE id = %s", (self.dev_a,)).rowcount, 0)
            self.assertEqual(c.execute("DELETE FROM snapshots WHERE device_id = %s", (self.dev_a,)).rowcount, 0)
            self.assertEqual([r["name"] for r in c.execute("SELECT name FROM organisations")], ["Globex"])
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):      # nor plant a row in another organisation
            with db.org(self.org_b) as c:
                c.execute("INSERT INTO devices (org_id, name, key_hash) VALUES (%s, 'planted', 'h')", (self.org_a,))
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):      # the audit log cannot be rewritten
            with db.org(self.org_a) as c:
                c.execute("DELETE FROM audit_log")
        with db.anon() as c:
            self.assertFalse(c.execute("SELECT rolsuper OR rolbypassrls AS x FROM pg_roles WHERE rolname = current_user").fetchone()["x"])
        with db.org(self.org_a) as c:                                       # A's own data is still all there
            self.assertEqual(c.execute("SELECT count(*) AS n FROM devices").fetchone()["n"], 2)


if __name__ == "__main__":
    unittest.main()
