"""Fleet server, phases 1 and 2. Runs against a throwaway database in the PostgreSQL started by docker-compose
(127.0.0.1:5433); skipped when that is not running. The important tests are the ones that try to cross from
one organisation to another: through the API, and directly in SQL as the application's database role.
Phase 2 is judged against a tiny made-up copy of the reference lists; nothing is downloaded."""
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OWNER = os.environ.get("TEST_DATABASE_URL_OWNER", "postgresql://postgres:postgres@127.0.0.1:5433/postgres")
APP_PASSWORD = os.environ.get("FLEET_APP_PASSWORD", "fleet_app")
WORKER_PASSWORD = os.environ.get("FLEET_WORKER_PASSWORD", "fleet_worker")
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
    import cve
    import eol
    from app import db, manage, worker
    from app.main import app, MAX_BODY


@contextmanager
def as_worker():
    """Run what is inside as the worker's database role instead of the API's."""
    api_url = os.environ["DATABASE_URL"]
    db.close()
    os.environ["DATABASE_URL"] = api_url.replace(f"fleet_app:{APP_PASSWORD}@", f"fleet_worker:{WORKER_PASSWORD}@")
    try:
        yield
    finally:
        db.close()
        os.environ["DATABASE_URL"] = api_url


def make_lists(folder: Path) -> dict:
    """A reference copy with one flaw (known exploited) and one ended release line, both for 'Kettle Archive'."""
    cfg = {"cve_database": folder / "cve.db"}
    c = cve._conn(cfg["cve_database"])
    c.execute("INSERT INTO cve VALUES ('CVE-2026-0001','2026-01-10','2026-01-12','Analyzed',9.8,'CRITICAL','Kettle Archive before 25.0 runs code from a crafted archive.')")
    c.execute("INSERT INTO cve VALUES ('CVE-2020-0002','2020-03-01','2020-03-02','Analyzed',7.5,'HIGH','Kettle Archive before 20.0 leaks memory.')")
    c.execute("INSERT INTO aff VALUES ('CVE-2026-0001','nvd','kettle','kettle_archive','*','','','','25.0')")
    c.execute("INSERT INTO aff VALUES ('CVE-2020-0002','nvd','kettle','kettle_archive','*','','','','20.0')")       # fixed long ago
    c.execute("INSERT INTO aff VALUES ('CVE-2026-0001','nvd','other','notes','*','','','','9.0')")                  # another maker's 'Notes'
    c.execute("INSERT INTO kev VALUES ('CVE-2026-0001','Kettle','Archive','code execution','2026-02-01','Unknown')")
    cve.index_products(c)
    for k, v in (("complete", "1"), ("synced_at", "2026-10-12T06:00:00"), ("tried_at", "2026-10-12T06:00:00")):
        cve._set(c, k, v)
    c.commit()
    c.close()
    c = eol._conn(cfg)
    filler = [{"name": f"filler-{i}", "label": f"Filler {i}", "category": "app", "releases": [{"name": "1", "isEol": False}]} for i in range(60)]
    eol.load(c, {"result": filler + [
        {"name": "kettle-archive", "label": "Kettle Archive", "category": "app",
         "releases": [{"name": "24", "isEol": True, "eolFrom": "2026-06-01", "latest": {"name": "24.12"}}, {"name": "25", "isEol": False}]},
        {"name": "windows", "label": "Windows", "category": "os", "releases": [{"name": "11-25h2-w", "isEol": False, "eolFrom": "2099-10-12"}]}]})
    c.execute("INSERT OR REPLACE INTO meta VALUES ('eol_synced_at', '2026-10-12T06:00:00')")
    c.commit()
    c.close()
    return cfg


def tearDownModule():
    if READY:
        db.close()
        with psycopg.connect(OWNER, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(NAME)))


SNAP = {"device": {"name": "DEMO-PC", "manufacturer": "Contoso", "model": "Tower 5", "windows": "Windows 11 Professional 25H2", "build": "26200.1234"},
        "apps": {"apps": [{"name": "Kettle Archive", "version": "24.08", "kind": "desktop", "available": "25.01"},
                          {"name": "Notes", "version": "1.0", "kind": "desktop", "available": None},
                          {"name": "Sketch Pad", "version": "2.1", "kind": "packaged", "available": None}]},
        "network": {"firewall": [{"name": "Domain", "enabled": True}, {"name": "Private", "enabled": False}, {"name": "Public", "enabled": True}],
                    "listening": [{"port": 27017, "reach": "network", "windows": False}, {"port": 135, "reach": "network", "windows": True}],
                    "shared_folders": 0, "rules": {"total": 10, "windows": 10, "programs": 0, "left_over": 0, "any_program_any_port": 0}},
        "posture": {"antivirus_on": True, "antivirus_products": 1, "realtime_protection": True, "signature_age_days": 1, "drives": 1,
                    "drives_encrypted": False, "lock_found": True, "autoplay_off": True, "guest_enabled": False, "accounts_enabled": 2,
                    "accounts_without_password": 0, "admin_accounts": 2, "daily_account_is_admin": True,
                    "windows_last_update": datetime.now(timezone.utc).date().isoformat(), "windows_updates_off": False,
                    "windows_updates_paused": False, "browser_updates_off": []}}


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
        cls.tmp = Path(tempfile.mkdtemp(prefix="fleet-test-"))
        cls.lists = make_lists(cls.tmp)
        cls.today = datetime.now(timezone.utc).date()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

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

    def test_5_the_worker_judges_each_device(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):      # the queue is the worker's door, not the API's
            with db.anon() as c:
                c.execute("SELECT * FROM judge_queue('x', current_date, 5)")
        before = self.http.get("/api/v1/devices", headers=self.auth(self.admin_a)).json()["devices"]
        self.assertTrue(all(d["judgement"] is None for d in before))
        with as_worker():
            with db.anon() as c:                                            # the worker too sees no customer rows by itself
                self.assertEqual(c.execute("SELECT count(*) AS n FROM devices").fetchone()["n"], 0)
            self.assertEqual(worker.round_(self.lists, self.today), 2)     # DEMO-PC and GLOBEX-PC; SECOND-PC never reported
            self.assertEqual(worker.round_(self.lists, self.today), 0)     # nothing changed: nothing to judge again
        rows = {d["name"]: d for d in self.http.get("/api/v1/devices", headers=self.auth(self.admin_a)).json()["devices"]}
        self.assertIsNone(rows["SECOND-PC"]["judgement"])
        j = rows["DEMO-PC"]["judgement"]
        self.assertEqual((j["security"]["apps_affected"], j["security"]["cves"], j["security"]["kev"], j["security"]["recognised"]), (1, 1, 1, 1))
        self.assertEqual(j["security"]["exploited"], [{"program": "Kettle Archive", "version": "24.08", "cve": "CVE-2026-0001", "fix": None}])
        self.assertEqual((j["support"]["windows"], j["support"]["ended"]), ("supported", ["Kettle Archive"]))
        self.assertEqual(j["compliance"]["areas"], {"firewalls": "fail", "configuration": "pass", "updates": "fail", "access": "fail", "malware": "pass"})
        self.assertEqual(sorted(f["id"] for f in j["failing"]), ["acc.daily", "fw.on", "upd.flaws", "upd.unsupported"])
        d = self.http.get(f"/api/v1/devices/{self.dev_a}", headers=self.auth(self.admin_a)).json()
        self.assertEqual(([a["name"] for a in d["flaws"]["apps"]], d["flaws"]["apps"][0]["cves"][0]["id"], d["flaws"]["apps"][0]["cves"][0]["kev"]),
                         (["Kettle Archive"], "CVE-2026-0001", True))       # 'Notes' is another maker's product: not matched
        self.assertEqual([p["state"] for p in d["support"]["programs"]], ["ended"])
        self.assertEqual((len(d["compliance"]["controls"]), d["compliance_history"][-1]["controls"]["malware"]), (5, "pass"))
        self.assertTrue(d["reference"]["complete"] is False)               # nothing published the list status in this test
        f = self.http.get("/api/v1/fleet", headers=self.auth(self.admin_a)).json()
        self.assertEqual((f["devices"], f["judged"], f["all_passing"], f["totals"]["exploited"]), (2, 1, 0, 1))
        self.assertEqual((f["exploited"][0]["device"], f["exploited"][0]["cve"], [s["name"] for s in f["silent"]]), ("DEMO-PC", "CVE-2026-0001", ["SECOND-PC"]))
        self.assertEqual({a["key"]: (a["pass"], a["fail"]) for a in f["areas"]}["malware"], (1, 0))
        self.assertEqual(f["history"][-1]["areas"]["malware"], 1)
        sw = self.http.get("/api/v1/software", headers=self.auth(self.admin_a)).json()["programs"]
        self.assertEqual((sw[0]["name"], sw[0]["exploited"], sw[0]["ended"], sw[0]["versions"][0]["devices"][0]["name"]), ("Kettle Archive", 1, True, "DEMO-PC"))
        # new facts send the device round again; the other organisation's judgement is its own
        fixed = {**SNAP, "posture": {**SNAP["posture"], "daily_account_is_admin": False}}
        self.http.post("/api/v1/checkin", headers=self.auth(self.key_a), json={"agent_version": "0.2", "snapshots": fixed})
        with as_worker():
            self.assertEqual(worker.round_(self.lists, self.today), 1)
        j = self.http.get("/api/v1/devices", headers=self.auth(self.admin_a)).json()["devices"][0]["judgement"]
        self.assertEqual(j["compliance"]["areas"]["access"], "pass")
        b = self.http.get("/api/v1/fleet", headers=self.auth(self.admin_b)).json()
        self.assertEqual((b["devices"], b["judged"], b["exploited"], [d["name"] for d in b["device_list"]]), (1, 1, [], ["GLOBEX-PC"]))

    def test_6_exceptions_declarations_and_the_report(self):
        url = f"/api/v1/devices/{self.dev_a}/exceptions"
        self.assertEqual(self.http.post(url, headers=self.auth(self.admin_b), json={"check_id": "fw.on", "reason": "x"}).status_code, 404)
        self.assertEqual(self.http.post(url, headers=self.auth(self.key_a), json={"check_id": "fw.on", "reason": "x"}).status_code, 401)
        for bad, code in (({"check_id": "'; DROP", "reason": "x"}, 400), ({"check_id": "zz.nothing", "reason": "x"}, 404)):
            self.assertEqual(self.http.post(url, headers=self.auth(self.admin_a), json=bad).status_code, code)
        ok = self.http.post(url, headers=self.auth(self.admin_a), json={"check_id": "fw.on", "reason": "Behind the office firewall until March."})
        self.assertEqual(ok.status_code, 200, ok.text)
        d = self.http.get(f"/api/v1/devices/{self.dev_a}", headers=self.auth(self.admin_a)).json()
        fw = next(g for g in d["compliance"]["controls"] if g["key"] == "firewalls")
        check = next(ch for ch in fw["checks"] if ch["id"] == "fw.on")
        self.assertEqual((check["status"], check["accepted"]["reason"], fw["status"], fw["accepted"]),
                         ("fail", "Behind the office firewall until March.", "pass", 1))     # still marked failing; no longer counted
        self.assertEqual((d["judgement"]["compliance"]["accepted"], "fw.on" in [f["id"] for f in d["judgement"]["failing"]],
                          d["compliance_history"][-1]["checks"]["fw.on"]), (1, False, "accepted"))
        with as_worker():                                                   # the worker keeps the acceptance when it judges again
            with db.org(self.org_a) as c:
                c.execute("UPDATE devices SET judged_day = NULL WHERE id = %s", (self.dev_a,))
            self.assertEqual(worker.round_(self.lists, self.today), 1)
        d = self.http.get(f"/api/v1/devices/{self.dev_a}", headers=self.auth(self.admin_a)).json()
        self.assertEqual(d["judgement"]["compliance"]["accepted"], 1)
        self.assertEqual(self.http.post(url, headers=self.auth(self.admin_a), json={"check_id": "fw.on", "reason": ""}).status_code, 200)
        d = self.http.get(f"/api/v1/devices/{self.dev_a}", headers=self.auth(self.admin_a)).json()
        self.assertEqual((d["judgement"]["compliance"]["accepted"], d["judgement"]["compliance"]["areas"]["firewalls"]), (0, "fail"))
        # declarations belong to the organisation and are only ever shown as declared
        for bad in ({"key": "nonsense", "answer": "yes"}, {"key": "mfa", "answer": "maybe"}):
            self.assertEqual(self.http.post("/api/v1/declarations", headers=self.auth(self.admin_a), json=bad).status_code, 400)
        self.assertEqual(self.http.post("/api/v1/declarations", headers=self.auth(self.admin_a), json={"key": "mfa", "answer": "yes", "note": "all mailboxes"}).status_code, 200)
        said = {q["key"]: q for q in self.http.get("/api/v1/fleet", headers=self.auth(self.admin_a)).json()["declared"]}
        self.assertEqual((said["mfa"]["answer"], said["mfa"]["note"], said["backups"]["answer"]), ("yes", "all mailboxes", None))
        other = {q["key"]: q["answer"] for q in self.http.get("/api/v1/fleet", headers=self.auth(self.admin_b)).json()["declared"]}
        self.assertIsNone(other["mfa"])
        text = self.http.get("/api/v1/report", headers=self.auth(self.admin_a)).json()["text"]
        for part in ("Security posture of Acme Ltd", "DEMO-PC: Windows 11 Professional 25H2", "SECOND-PC: enrolled, not judged yet", "used in real attacks",
                     "[FAIL] Windows Firewall is on for every profile", "DECLARED BY THE ORGANISATION (not measured)", "Multi-factor login is on for email and cloud services (all mailboxes)", "not a certificate"):
            self.assertIn(part, text)
        self.assertNotIn("GLOBEX", text)
        one = self.http.get(f"/api/v1/devices/{self.dev_a}/report", headers=self.auth(self.admin_a)).json()["text"]
        self.assertTrue("DEMO-PC" in one and "SECOND-PC" not in one)
        self.assertEqual(self.http.get(f"/api/v1/devices/{self.dev_a}/report", headers=self.auth(self.admin_b)).status_code, 404)
        actions = [e["action"] for e in self.http.get("/api/v1/audit", headers=self.auth(self.admin_a)).json()["entries"]]
        self.assertEqual(actions[:3], ["declaration.changed", "check.acceptance_withdrawn", "check.accepted"])

    def test_7_judgements_stay_inside_their_organisation(self):
        with db.anon() as c:
            for table in ("judgements", "compliance_history", "declarations", "exceptions"):
                self.assertEqual(c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"], 0, table)
        with db.org(self.org_b) as c:
            self.assertEqual(c.execute("SELECT count(*) AS n FROM judgements").fetchone()["n"], 1)
            self.assertEqual(c.execute("SELECT count(*) AS n FROM judgements WHERE device_id = %s", (self.dev_a,)).fetchone()["n"], 0)
            self.assertEqual(c.execute("UPDATE judgements SET summary = '{}' WHERE device_id = %s", (self.dev_a,)).rowcount, 0)
            self.assertEqual(c.execute("SELECT count(*) AS n FROM declarations").fetchone()["n"], 0)
            self.assertEqual(c.execute("SELECT count(*) AS n FROM compliance_history WHERE device_id = %s", (self.dev_a,)).fetchone()["n"], 0)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with db.org(self.org_b) as c:
                c.execute("INSERT INTO exceptions (org_id, device_id, check_id, reason) VALUES (%s,%s,'fw.on','planted')", (self.org_a, self.dev_a))
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):      # the API cannot write a judgement of its own
            with db.org(self.org_a) as c:
                c.execute("INSERT INTO judgements (device_id, org_id) VALUES (%s,%s)", (self.dev_a, self.org_a))
        with as_worker():
            with db.anon() as c:
                self.assertFalse(c.execute("SELECT rolsuper OR rolbypassrls AS x FROM pg_roles WHERE rolname = current_user").fetchone()["x"])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):  # the worker cannot touch keys or the audit log
                with db.org(self.org_a) as c:
                    c.execute("SELECT count(*) FROM admin_keys")


if __name__ == "__main__":
    unittest.main()
