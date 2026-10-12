"""Fleet server, phases 1 to 3. Runs against a throwaway database in the PostgreSQL started by docker-compose
(127.0.0.1:5433); skipped when that is not running. The important tests are the ones that try to cross from
one organisation to another: through the API, and directly in SQL as the application's database role.
Phase 2 is judged against a tiny made-up copy of the reference lists; nothing is downloaded."""
import os
import shutil
import sys
import tempfile
import time
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
    os.environ.setdefault("FLEET_SECRET_KEY", "ZGV2ZWxvcGVyLXBjLW9ubHktbm90LWEtc2VjcmV0ISE=")
    from fastapi.testclient import TestClient
    import cve
    import eol
    from app import auth, db, manage, people, worker
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


PASSWORD = "four unrelated words here"


def code(secret: str, ahead: int = 0) -> str:
    return auth.totp_at(secret, int(time.time() // 30) + ahead)


def person(org, email: str, role: str) -> tuple:
    """A person who has set a password and a second factor and is signed in: (their browser, the authenticator
    secret, their recovery codes)."""
    with manage.connect() as c:
        token = people.add_first_user(c, org, email, role)
    browser = TestClient(app)
    assert browser.post("/api/v1/auth/setup", json={"token": token, "password": PASSWORD}).status_code == 200
    assert browser.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json() == {"stage": "mfa_setup"}
    secret = browser.get("/api/v1/auth/mfa/setup").json()["secret"]
    used = code(secret)
    done = browser.post("/api/v1/auth/mfa/setup", json={"code": used}).json()
    assert done["stage"] == "ok" and len(done["recovery_codes"]) == 8, done
    browser.headers["X-Fleet-Console"] = "1"
    return browser, secret, done["recovery_codes"] + [used]


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
        cls.owner_a, cls.secret_a, cls.codes_a = person(cls.org_a, "olive@acme.example", "owner")
        cls.owner_b, _, _ = person(cls.org_b, "bo@globex.example", "owner")
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
        self.assertEqual(self.owner_b.post(url, json={"check_id": "fw.on", "reason": "x"}).status_code, 404)
        self.assertEqual(self.http.post(url, headers=self.auth(self.key_a), json={"check_id": "fw.on", "reason": "x"}).status_code, 401)
        self.assertEqual(self.http.post(url, headers=self.auth(self.admin_a), json={"check_id": "fw.on", "reason": "x"}).status_code, 403)   # a key only reads
        for bad, status in (({"check_id": "'; DROP", "reason": "x"}, 400), ({"check_id": "zz.nothing", "reason": "x"}, 404)):
            self.assertEqual(self.owner_a.post(url, json=bad).status_code, status)
        ok = self.owner_a.post(url, json={"check_id": "fw.on", "reason": "Behind the office firewall until March."})
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
        self.assertEqual(self.owner_a.post(url, json={"check_id": "fw.on", "reason": ""}).status_code, 200)
        d = self.http.get(f"/api/v1/devices/{self.dev_a}", headers=self.auth(self.admin_a)).json()
        self.assertEqual((d["judgement"]["compliance"]["accepted"], d["judgement"]["compliance"]["areas"]["firewalls"]), (0, "fail"))
        # declarations belong to the organisation and are only ever shown as declared
        for bad in ({"key": "nonsense", "answer": "yes"}, {"key": "mfa", "answer": "maybe"}):
            self.assertEqual(self.owner_a.post("/api/v1/declarations", json=bad).status_code, 400)
        self.assertEqual(self.owner_a.post("/api/v1/declarations", json={"key": "mfa", "answer": "yes", "note": "all mailboxes"}).status_code, 200)
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
        who = self.http.get("/api/v1/audit", headers=self.auth(self.admin_a)).json()["entries"][0]["actor"]
        self.assertEqual(who, "user:olive@acme.example")                    # a named person, not a shared key

    def test_7_judgements_stay_inside_their_organisation(self):
        with db.anon() as c:
            for table in ("judgements", "compliance_history", "declarations", "exceptions", "users", "sessions", "setup_links",
                          "recovery_codes", "share_links"):
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

    def login(self, email, password=PASSWORD):
        browser = TestClient(app)
        return browser, browser.post("/api/v1/auth/login", json={"email": email, "password": password})

    def test_8_signing_in(self):
        refused = self.login("olive@acme.example", "not the password")[1]
        nobody = self.login("nobody@acme.example")[1]
        self.assertEqual((refused.status_code, nobody.status_code, refused.json(), "set-cookie" in refused.headers), (401, 401, nobody.json(), False))
        browser, r = self.login("olive@acme.example")
        self.assertEqual(r.json(), {"stage": "mfa"})
        self.assertTrue("HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"])
        # the password alone opens nothing
        self.assertEqual(browser.get("/api/v1/devices").status_code, 401)
        self.assertEqual(browser.get("/api/v1/auth/me").json(), {"stage": "mfa", "email": "olive@acme.example"})
        self.assertEqual(browser.get("/api/v1/auth/mfa/setup").status_code, 400)                  # the secret is not shown a second time
        self.assertEqual(browser.post("/api/v1/auth/mfa", json={"code": "000000"}).status_code, 401)
        self.assertEqual(browser.post("/api/v1/auth/mfa", json={"code": self.codes_a[-1]}).status_code, 401)        # the code used at set-up: good once
        self.assertEqual(browser.post("/api/v1/auth/mfa", json={"code": code(self.secret_a, 1)}).json(), {"stage": "ok"})
        me = browser.get("/api/v1/auth/me").json()
        self.assertEqual((me["stage"], me["role"], me["organisation"]), ("ok", "owner", "Acme Ltd"))
        self.assertEqual(len(browser.get("/api/v1/devices").json()["devices"]), 2)
        # a change needs the console's own header as well as the cookie
        self.assertEqual(browser.post("/api/v1/declarations", json={"key": "backups", "answer": "yes"}).status_code, 403)
        # a recovery code works once
        b2, _ = self.login("olive@acme.example")
        self.assertEqual(b2.post("/api/v1/auth/mfa", json={"code": self.codes_a[0]}).json(), {"stage": "ok", "recovery_left": 7})
        b3, _ = self.login("olive@acme.example")
        self.assertEqual(b3.post("/api/v1/auth/mfa", json={"code": self.codes_a[0]}).status_code, 401)
        # signing out ends that session only; an idle session ends by itself
        self.assertEqual(b2.post("/api/v1/auth/logout").status_code, 200)
        self.assertEqual((b2.get("/api/v1/devices").status_code, browser.get("/api/v1/devices").status_code), (401, 200))
        with manage.connect() as c:
            c.execute("UPDATE sessions SET last_seen = now() - interval '3 hours' WHERE org_id = %s", (self.org_a,))
        self.assertEqual((browser.get("/api/v1/devices").status_code, self.owner_a.get("/api/v1/devices").status_code), (401, 401))
        type(self).owner_a = b4 = self.login("olive@acme.example")[0]
        self.assertEqual(b4.post("/api/v1/auth/mfa", json={"code": self.codes_a[1]}).status_code, 200)
        b4.headers["X-Fleet-Console"] = "1"
        # nothing that opens a door is stored as it is
        with manage.connect() as c:
            stored = " ".join(str(x) for row in c.execute(
                "SELECT password_hash || ' ' || coalesce(totp_secret, '') FROM users UNION ALL SELECT token_hash FROM sessions "
                "UNION ALL SELECT code_hash FROM recovery_codes UNION ALL SELECT token_hash FROM setup_links") for x in row)
        for secret in (PASSWORD, self.secret_a, self.codes_a[2], b4.cookies.get(auth.COOKIE)):
            self.assertNotIn(secret, stored)
        # five wrong passwords lock the account for a while, even for the right one
        with manage.connect() as c:
            token = people.add_first_user(c, self.org_a, "lee@acme.example", "auditor")
        self.assertEqual(self.http.post("/api/v1/auth/setup", json={"token": token, "password": "short"}).status_code, 400)
        self.assertEqual(self.http.post("/api/v1/auth/setup/check", json={"token": token}).json()["email"], "lee@acme.example")
        self.assertEqual(self.http.post("/api/v1/auth/setup", json={"token": token, "password": PASSWORD}).status_code, 200)
        self.assertEqual(self.http.post("/api/v1/auth/setup", json={"token": token, "password": PASSWORD + "!"}).status_code, 404)      # the link works once
        for _ in range(auth.MAX_FAILED):
            self.assertEqual(self.login("lee@acme.example", "a wrong guess")[1].status_code, 401)
        self.assertEqual(self.login("lee@acme.example")[1].status_code, 401)
        log = b4.get("/api/v1/audit").json()["entries"]
        self.assertEqual((log[0]["action"], log[0]["actor"]), ("signin.locked", "user:lee@acme.example"))
        with manage.connect() as c:
            c.execute("UPDATE users SET locked_until = now() - interval '1 minute' WHERE email = 'lee@acme.example'")
        self.assertEqual(self.login("lee@acme.example")[1].json(), {"stage": "mfa_setup"})

    def test_9_roles_people_and_share_links(self):
        boss = self.owner_a
        added = boss.post("/api/v1/users", json={"email": "Ada@Acme.example", "name": "Ada", "role": "admin"}).json()
        self.assertTrue(added["ok"] and added["setup_token"].startswith("sfu_"))
        self.assertEqual(boss.post("/api/v1/users", json={"email": "bo@globex.example", "role": "auditor"}).status_code, 400)       # taken, in another organisation
        self.assertEqual(boss.post("/api/v1/users", json={"email": "not an address", "role": "admin"}).status_code, 400)
        self.assertEqual(self.http.post("/api/v1/auth/setup", json={"token": added["setup_token"], "password": PASSWORD}).status_code, 200)
        ada = self.login("ada@acme.example")[0]
        secret = ada.get("/api/v1/auth/mfa/setup").json()
        self.assertTrue(secret["qr"].startswith("data:image/svg+xml") and secret["secret"] in secret["uri"])
        self.assertEqual(ada.post("/api/v1/auth/mfa/setup", json={"code": code(secret["secret"])}).json()["stage"], "ok")
        ada.headers["X-Fleet-Console"] = "1"
        vera, _, _ = person(self.org_a, "vera@acme.example", "auditor")
        # an auditor reads; an admin also records; only an owner manages people
        self.assertEqual((vera.get("/api/v1/fleet").status_code, vera.get("/api/v1/report").status_code), (200, 200))
        for url, body in (("/api/v1/declarations", {"key": "backups", "answer": "yes"}), ("/api/v1/share-links", {"label": "x"}),
                          ("/api/v1/tokens", {}), (f"/api/v1/devices/{self.dev_a}/remove", {}), ("/api/v1/users", {"email": "x@acme.example", "role": "owner"})):
            self.assertEqual(vera.post(url, json=body).status_code, 403, url)
        self.assertEqual((vera.get("/api/v1/access").json()["users"], vera.get("/api/v1/access").json()["me"]["role"]), ([], "auditor"))
        self.assertEqual(ada.post("/api/v1/declarations", json={"key": "backups", "answer": "yes"}).status_code, 200)
        self.assertEqual(ada.post("/api/v1/users", json={"email": "x@acme.example", "role": "owner"}).status_code, 403)
        self.assertEqual(ada.post(f"/api/v1/users/{added['id']}", json={"action": "role", "role": "owner"}).status_code, 403)       # nor promote herself
        people_a = {u["email"]: u for u in boss.get("/api/v1/access").json()["users"]}
        self.assertEqual(sorted(people_a), ["ada@acme.example", "lee@acme.example", "olive@acme.example", "vera@acme.example"])
        self.assertEqual((people_a["ada@acme.example"]["role"], people_a["ada@acme.example"]["second_factor"], people_a["lee@acme.example"]["second_factor"]),
                         ("admin", True, False))
        self.assertEqual([u["email"] for u in self.owner_b.get("/api/v1/access").json()["users"]], ["bo@globex.example"])
        me = boss.get("/api/v1/access").json()["me"]["id"]
        self.assertEqual(boss.post(f"/api/v1/users/{me}", json={"action": "disable"}).status_code, 400)                # not yourself
        self.assertEqual(self.owner_b.post(f"/api/v1/users/{added['id']}", json={"action": "disable"}).status_code, 404)  # not another organisation's
        self.assertEqual(boss.post("/api/v1/users/nonsense", json={"action": "disable"}).status_code, 404)
        vera_id = people_a["vera@acme.example"]["id"]
        self.assertEqual(boss.post(f"/api/v1/users/{vera_id}", json={"action": "disable"}).status_code, 200)
        self.assertEqual((vera.get("/api/v1/fleet").status_code, self.login("vera@acme.example")[1].status_code), (401, 401))
        self.assertEqual(boss.post(f"/api/v1/users/{vera_id}", json={"action": "enable"}).status_code, 200)
        self.assertEqual(boss.post(f"/api/v1/users/{vera_id}", json={"action": "reset_second_factor"}).status_code, 200)
        self.assertEqual(self.login("vera@acme.example")[1].json(), {"stage": "mfa_setup"})
        again = boss.post(f"/api/v1/users/{vera_id}", json={"action": "reset_password"}).json()
        self.assertEqual(self.http.post("/api/v1/auth/setup", json={"token": again["setup_token"], "password": PASSWORD + " again"}).status_code, 200)
        self.assertEqual((self.login("vera@acme.example")[1].status_code, self.login("vera@acme.example", PASSWORD + " again")[1].status_code), (401, 200))
        # a share link: the evidence, read-only, for someone without an account
        link = ada.post("/api/v1/share-links", json={"label": "Broker, renewal 2027", "days": 14}).json()["share_token"]
        seen = self.http.get("/api/v1/shared", headers={"Authorization": "Share " + link})
        self.assertEqual(seen.status_code, 200, seen.text)
        d = seen.json()
        self.assertEqual((d["organisation"], d["label"], sorted(x["name"] for x in d["device_list"]), d["judged"]), ("Acme Ltd", "Broker, renewal 2027", ["DEMO-PC", "SECOND-PC"], 1))
        self.assertTrue("Security posture of Acme Ltd" in d["text"] and "GLOBEX" not in seen.text and len(d["device_list"][0]["compliance"]["controls"]) == 5)
        for url in ("/api/v1/devices", "/api/v1/fleet", "/api/v1/audit", "/api/v1/access"):                              # it opens that one page and nothing else
            self.assertEqual(self.http.get(url, headers={"Authorization": "Share " + link}).status_code, 401, url)
            self.assertEqual(self.http.get(url, headers=self.auth(link)).status_code, 401, url)
        listed = ada.get("/api/v1/access").json()["share_links"][0]
        self.assertEqual((listed["label"], listed["state"], listed["opened"], listed["created_by"]), ("Broker, renewal 2027", "active", 1, "user:ada@acme.example"))
        self.assertEqual(self.owner_b.post(f"/api/v1/share-links/{listed['id']}/revoke").status_code, 404)
        self.assertEqual(ada.post(f"/api/v1/share-links/{listed['id']}/revoke").status_code, 200)
        self.assertEqual(self.http.get("/api/v1/shared", headers={"Authorization": "Share " + link}).status_code, 401)
        self.assertEqual(self.http.get("/api/v1/shared", headers={"Authorization": "Share sfl_made_up"}).status_code, 401)
        with manage.connect() as c:
            self.assertNotIn(link, " ".join(r[0] for r in c.execute("SELECT token_hash FROM share_links")))
        # an enrolment token made in the console, and removing a device
        token = ada.post("/api/v1/tokens", json={"label": "front desk", "uses": 1, "days": 3}).json()["enrolment_token"]
        new = self.enrol(token, "THIRD-PC").json()["device_id"]
        self.assertEqual(self.enrol(token, "FOURTH-PC").status_code, 403)
        self.assertEqual(self.owner_b.post(f"/api/v1/devices/{new}/remove").status_code, 404)
        self.assertEqual(ada.post(f"/api/v1/devices/{new}/remove").status_code, 200)
        self.assertEqual(sorted(x["name"] for x in ada.get("/api/v1/devices").json()["devices"]), ["DEMO-PC", "SECOND-PC"])
        # changing a password needs the current one and signs out the other browsers
        other = self.login("ada@acme.example")[0]
        self.assertEqual(ada.post("/api/v1/auth/password", json={"current": "wrong", "new": PASSWORD + " 2"}).status_code, 400)
        self.assertEqual(ada.post("/api/v1/auth/password", json={"current": PASSWORD, "new": "tiny"}).status_code, 400)
        self.assertEqual(ada.post("/api/v1/auth/password", json={"current": PASSWORD, "new": PASSWORD + " 2"}).status_code, 200)
        self.assertEqual((ada.get("/api/v1/auth/me").json()["stage"], other.get("/api/v1/auth/me").status_code), ("ok", 401))
        actions = [e["action"] for e in boss.get("/api/v1/audit").json()["entries"]]
        for a in ("user.added", "user.disable", "user.reset_second_factor", "share_link.created", "share_link.withdrawn", "enrolment_token.created",
                  "device.removed", "password.changed", "signin", "mfa.set_up"):
            self.assertIn(a, actions)


if __name__ == "__main__":
    unittest.main()
