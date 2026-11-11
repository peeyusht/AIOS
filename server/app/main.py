"""
Fleet server: agents enrol and report what is installed; the worker judges each device (known flaws, end of
support, the compliance checks); an administrator sees the fleet, each device, and the evidence report.

Agents call (app/agents.py: every request is signed with the device's own key):
                POST /api/v1/enrol      a one-time token and the device's public key -> a device id
                POST /api/v1/checkin    stores what changed since the last report
                GET  /api/v1/agent/release, /agent/package/{version}     a newer agent, signed with the release key
Console calls (a signed-in person, see app/people.py for signing in, roles, people and share links; an
organisation key can read but change nothing):
                GET  /api/v1/fleet                      the dashboard: control areas, what fails where, history
                GET  /api/v1/devices, /devices/{id}     the list; one device with its judgement and history
                GET  /api/v1/software                   which program is on which devices
                GET  /api/v1/report, /devices/{id}/report      the evidence as plain text
                POST /api/v1/declarations               what the organisation states about what cannot be measured
                POST /api/v1/devices/{id}/exceptions    accept a failing check with a reason, or withdraw that
                POST /api/v1/frameworks                 which frameworks the console shows (Cyber Essentials, CERT-In, DPDP)
                POST /api/v1/devices/{id}/labels        mark a device as holding personal data, or as critical
                GET/POST /api/v1/incidents[/{id}]       the incident register with CERT-In's and DPDP's clocks (app/incidents.py)
                GET /api/v1/records, POST /reviews, /governance   reviews signed off and the governance record (app/records.py)
                GET/POST /api/v1/mail-domain            the mail domain whose SPF/DMARC/DKIM the worker looks up (app/mail.py)
                (fleet, report and shared take ?framework=ce|certin|dpdp; the default is the organisation's first)
                GET  /api/v1/audit
                GET  /api/v1/agent/installer            the newest agent installer, for whoever may add a PC
With a share link:  GET /api/v1/shared                  the organisation's evidence, read-only, until the link expires
Anyone:         GET  /healthz, and the console at /

The API reads judgements; it does not make them (app/worker.py does) and never opens the reference lists.
Nothing can send a command to a device: that is phase 5. See docs/architecture.md.
"""
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb

from . import agents, db, incidents, judge, mail, people, records
from .agents import device
from .people import editor, reader

KINDS = ("device", "apps", "services", "network", "posture")
MAX_BODY = 5 * 1024 * 1024          # a full report from the first PC is about 60 KB
CHECKIN_SECONDS = 900
CONSOLE = Path(__file__).parent / "console"       # the built front end (see Dockerfile)
SILENT_HOURS = 24
HISTORY_DAYS = 90


@asynccontextmanager
async def lifespan(_app):
    yield
    db.close()


app = FastAPI(title="Shadow Filer fleet server", version="0.2.0", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(people.router)
app.include_router(agents.router)
app.include_router(incidents.router)
app.include_router(records.router)
app.include_router(mail.router)
if (CONSOLE / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=CONSOLE / "assets"), name="assets")


@app.middleware("http")
async def limits_and_headers(request: Request, call_next):
    size = request.headers.get("content-length")
    if size and size.isdigit() and int(size) > MAX_BODY:
        return JSONResponse({"detail": "The report is too large."}, status_code=413)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    # scripts only from this server; styles may be set inline because the component library does that
    resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'"
    if not request.url.path.startswith("/assets/"):          # built files carry a hash in their name
        resp.headers["Cache-Control"] = "no-store"
    return resp


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer ") or len(authorization) < 20:
        raise HTTPException(401, "A key is required.")
    return authorization[7:].strip()


def _text(v, limit: int = 200) -> str:
    return str(v or "").strip()[:limit]


def summarise(snaps: dict) -> dict:
    """The few facts the fleet list shows per device, from what it reported. No judging here: the worker does that."""
    out = {}
    d = snaps.get("device")
    if isinstance(d, dict):
        out.update(windows=_text(d.get("windows"), 80), model=_text(f"{d.get('manufacturer') or ''} {d.get('model') or ''}", 80))
    a = snaps.get("apps")
    if isinstance(a, dict) and isinstance(a.get("apps"), list):
        out.update(programs=sum(1 for x in a["apps"] if isinstance(x, dict) and x.get("kind") == "desktop"),
                   updates=sum(1 for x in a["apps"] if isinstance(x, dict) and x.get("available")))
    s = snaps.get("services")
    if isinstance(s, dict) and isinstance(s.get("services"), list):
        out.update(services=len(s["services"]), services_exposed=sum(1 for x in s["services"] if isinstance(x, dict) and x.get("exposed")))
    n = snaps.get("network")
    if isinstance(n, dict) and isinstance(n.get("firewall"), list):
        on = [bool(f.get("enabled")) for f in n["firewall"] if isinstance(f, dict)]
        out.update(firewall=None if not on else "on" if all(on) else "off" if not any(on) else "partly",
                   ports_open=sum(1 for x in n.get("listening") or [] if isinstance(x, dict) and x.get("reach") == "network" and not x.get("windows")))
    p = snaps.get("posture")
    if isinstance(p, dict):
        out.update(antivirus=p.get("antivirus_on"), encrypted=p.get("drives_encrypted"), daily_admin=p.get("daily_account_is_admin"))
    return out


@app.get("/healthz")
def healthz():
    with db.anon() as c:
        c.execute("SELECT 1")
    return {"ok": True}


@app.get("/")
def console_page():
    page = CONSOLE / "index.html"
    if not page.is_file():
        return JSONResponse({"detail": "The console has not been built into this image."}, status_code=503)
    return FileResponse(page)


@app.post("/api/v1/enrol")
async def enrol(request: Request):
    """Swap a valid enrolment token for a device identity. The device sends the public half of a key pair it
    made, and signs this request with the private half to show it holds it. The server never has a secret of
    the device's."""
    try:
        body = json.loads(await request.body())
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, "A token and a device name are required.")
    token, name, key = _text(body.get("token"), 200), _text(body.get("name"), 100), _text(body.get("public_key"), 100)
    if not token or not name:
        raise HTTPException(400, "A token and a device name are required.")
    try:
        agents.public_key(key)
    except ValueError:
        raise HTTPException(400, "This agent is too old for this server: it did not send a device key. Install the current agent.") from None
    agents.check_signature(key, request, await request.body())       # before the token: a bad request must not use it up
    with db.anon() as c:
        row = c.execute("SELECT * FROM redeem_token(%s)", (db.digest(token),)).fetchone()
    if not row:
        raise HTTPException(403, "That enrolment token is not valid, has expired or has been used up.")
    with db.org(row["org_id"]) as c:
        dev = c.execute("INSERT INTO devices (org_id, name, public_key, agent_version) VALUES (%s,%s,%s,%s) RETURNING id",
                        (row["org_id"], name, key, _text(body.get("agent_version"), 40))).fetchone()
        c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                  (row["org_id"], f"token:{row['token_id']}", "device.enrolled", Jsonb({"device": str(dev["id"]), "name": name})))
    return {"device_id": str(dev["id"]), "checkin_seconds": CHECKIN_SECONDS}


@app.post("/api/v1/checkin")
async def checkin(request: Request, who: dict = Depends(device)):
    """Store what the device reports. A kind is stored only when it differs from the last one kept."""
    try:
        body = json.loads(await request.body())
    except ValueError:
        body = None
    snaps = body.get("snapshots") if isinstance(body, dict) else None
    if not isinstance(snaps, dict) or any(k not in KINDS for k in snaps):
        raise HTTPException(400, f"snapshots must be an object with keys from {', '.join(KINDS)}.")
    stored = []
    with db.org(who["org_id"]) as c:
        for kind, payload in snaps.items():
            if not isinstance(payload, (dict, list)):
                raise HTTPException(400, f"{kind} must be an object or a list.")
            sha = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            last = c.execute("SELECT sha256 FROM snapshots WHERE device_id=%s AND kind=%s ORDER BY received_at DESC, id DESC LIMIT 1",
                             (who["device_id"], kind)).fetchone()
            if not last or last["sha256"] != sha:
                c.execute("INSERT INTO snapshots (org_id, device_id, kind, sha256, payload) VALUES (%s,%s,%s,%s,%s)",
                          (who["org_id"], who["device_id"], kind, sha, Jsonb(payload)))
                stored.append(kind)
        latest = {r["kind"]: r["payload"] for r in c.execute(
            "SELECT DISTINCT ON (kind) kind, payload FROM snapshots WHERE device_id=%s ORDER BY kind, received_at DESC, id DESC",
            (who["device_id"],))}
        # facts_at moves only when something new was kept: that is what sends the device to the worker again
        c.execute("UPDATE devices SET last_seen = now(), agent_version = %s, summary = %s, "
                  "facts_at = CASE WHEN %s THEN clock_timestamp() ELSE facts_at END WHERE id = %s",
                  (_text(body.get("agent_version"), 40), Jsonb(summarise(latest)), bool(stored), who["device_id"]))
    with db.anon() as c:      # only the number: the agent fetches and checks the signed manifest itself
        newest = agents.latest_release(c)
    return {"ok": True, "stored": stored, "checkin_seconds": CHECKIN_SECONDS, "agent_release": newest}


@app.get("/api/v1/agent/installer")
def agent_installer(who: dict = Depends(editor)):
    """The newest agent installer, for the people who may add a PC. The same file a device would fetch."""
    with db.anon() as c:
        v = agents.latest_release(c)
        row = c.execute("SELECT package FROM agent_releases WHERE version = %s", (v,)).fetchone() if v else None
    if not row:
        raise HTTPException(404, "This server has no agent installer on offer yet.")
    return Response(bytes(row["package"]), media_type="application/x-msi",
                    headers={"Content-Disposition": f'attachment; filename="ShadowFilerAgent-{v}.msi"'})


def _iso(v):
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat(timespec="seconds")
    return v.isoformat() if isinstance(v, date) else v


def _actor(who: dict) -> str:
    return who["actor"]


def _device_row(r: dict, now: datetime) -> dict:
    return {"id": str(r["id"]), "name": r["name"], "enrolled_at": _iso(r["enrolled_at"]), "last_seen": _iso(r["last_seen"]),
            "silent_seconds": int((now - r["last_seen"]).total_seconds()) if r["last_seen"] else None,
            "agent_version": r["agent_version"], "summary": r["summary"],
            "judged_at": _iso(r["judged_at"]), "judgement": r["judgement"], "labels": list(r.get("labels") or [])}


DEVICES_SQL = ("SELECT d.id, d.name, d.enrolled_at, d.last_seen, d.agent_version, d.summary, j.judged_at, j.summary AS judgement, "
               "(SELECT coalesce(array_agg(l.label ORDER BY l.label), '{}') FROM device_labels l WHERE l.device_id = d.id) AS labels "
               "FROM devices d LEFT JOIN judgements j ON j.device_id = d.id ")


def _reference(c) -> dict:
    """How fresh the worker's lists are."""
    m = {r["k"]: r["v"] for r in c.execute("SELECT k, v FROM reference_status")}
    num = lambda k: int(m[k]) if (m.get(k) or "").isdigit() else 0
    return {"cve_synced_at": m.get("cve_synced_at") or None, "complete": m.get("cve_complete") == "1", "cves": num("cves"),
            "kev": num("kev"), "eol_synced_at": m.get("eol_synced_at") or None, "eol_products": num("eol_products"),
            "syncing": m.get("syncing") == "1", "error": m.get("cve_error") or m.get("eol_error") or None}


def _declared(c, fw: str = "ce") -> list:
    return judge.declared([{**r, "at": _iso(r["at"]), "dated": r["dated"].isoformat() if r["dated"] else ""}
                           for r in c.execute("SELECT key, answer, note, at, dated FROM declarations")], fw)


def _frameworks(c) -> list:
    """The frameworks this organisation shows, in its order; Cyber Essentials when none is set."""
    r = c.execute("SELECT frameworks FROM organisations").fetchone()
    return [k for k in (r["frameworks"] if r else []) or [] if k in judge.FRAMEWORKS] or ["ce"]


def _pick(c, asked: str | None) -> tuple:
    shown = _frameworks(c)
    fw = asked if asked in judge.FRAMEWORKS else shown[0]
    return fw, [{"key": k, "title": f["title"], "scheme": f["scheme"], "footer": f["footer"], "shown": k in shown,
                 "areas": [{"key": a, "title": t} for a, t, _about, _ids in f["controls"]]} for k, f in judge.FRAMEWORKS.items()]


def _areas(fw: str) -> list:
    return [(k, t, about) for k, t, about, _ids in judge.FRAMEWORKS[fw]["controls"]]


@app.get("/api/v1/devices")
def devices(who: dict = Depends(reader)):
    with db.org(who["org_id"]) as c:
        org = c.execute("SELECT name FROM organisations").fetchone()
        rows = c.execute(DEVICES_SQL + "ORDER BY lower(d.name)").fetchall()
        fw, fws = _pick(c, None)
    now = datetime.now(timezone.utc)
    return {"organisation": org["name"] if org else "", "generated_at": _iso(now), "checkin_seconds": CHECKIN_SECONDS,
            "framework": fw, "frameworks": fws, "devices": [_device_row(r, now) for r in rows]}


@app.get("/api/v1/fleet")
def fleet(framework: str | None = None, who: dict = Depends(reader)):
    """The dashboard for one framework: how many devices pass each control area, which checks fail on which
    devices, flaws that are being used in real attacks, and the last 90 days."""
    now = datetime.now(timezone.utc)
    with db.org(who["org_id"]) as c:
        org = c.execute("SELECT name FROM organisations").fetchone()
        fw, fws = _pick(c, framework)
        rows = [_device_row(r, now) for r in c.execute(DEVICES_SQL + "ORDER BY lower(d.name)")]
        hist = c.execute("SELECT day, line FROM compliance_history WHERE day >= %s AND framework = %s ORDER BY day",
                         (now.date() - timedelta(days=HISTORY_DAYS - 1), fw)).fetchall()
        ref, said = _reference(c), _declared(c, fw)
        due = records.view(c, now.date())["due"] if fw != "ce" else []     # CERT-In and DPDP ask for these; Cyber Essentials does not
        md = c.execute("SELECT domain, selectors, result FROM mail_domains").fetchone() if fw == "certin" else None
        org_checks = [x for x in [mail.check(dict(md)) if md else None] if x]          # CERT-In NES.4
    judged = [d for d in rows if d["judgement"]]
    short = {d["id"]: judge.framework_summary(d["judgement"], fw) for d in judged}
    sup = lambda d: d["judgement"].get("support") or {}
    areas = [{"key": k, "title": t, "about": about,
              **{s: sum(1 for d in judged if ((short[d["id"]] or {}).get("areas") or {}).get(k) == s) for s in ("pass", "fail", "warn", "unknown", "info")}}
             for k, t, about in _areas(fw)]
    failing = {}
    for d in judged:
        for f in (short[d["id"]] or {}).get("failing") or []:
            failing.setdefault(f["id"], {**f, "devices": []})["devices"].append({"id": d["id"], "name": d["name"]})
    sec = [d for d in judged if d["judgement"].get("security")]
    days = {}
    for h in hist:
        x = days.setdefault(h["day"], {"day": _iso(h["day"]), "devices": 0, "all_passing": 0, "areas": {k: 0 for k, _, _ in _areas(fw)}})
        ctl = h["line"].get("controls") or {}
        x["devices"] += 1
        x["all_passing"] += int(bool(ctl) and all(v in ("pass", "info") for v in ctl.values()))
        for k, v in ctl.items():
            if k in x["areas"] and v == "pass":
                x["areas"][k] += 1
    return {"organisation": org["name"] if org else "", "generated_at": _iso(now), "devices": len(rows), "judged": len(judged),
            "framework": fw, "frameworks": fws, "records_due": due, "org_checks": org_checks,
            "silent": [{"id": d["id"], "name": d["name"], "last_seen": d["last_seen"]} for d in rows
                       if d["silent_seconds"] is None or d["silent_seconds"] > SILENT_HOURS * 3600],
            "all_passing": sum(1 for v in short.values() if v and v["controls_passing"] == v["controls"]),
            "areas": areas, "failing": sorted(failing.values(), key=lambda f: (-len(f["devices"]), f["id"])),
            "exploited": [{"device_id": d["id"], "device": d["name"], **e} for d in sec for e in d["judgement"]["security"].get("exploited") or []],
            "unsupported": [{"device_id": d["id"], "device": d["name"], "windows": sup(d).get("windows") == "ended",
                             "windows_until": sup(d).get("windows_until"), "programs": sup(d).get("ended") or []}
                            for d in judged if sup(d).get("windows") == "ended" or sup(d).get("ended")],
            "totals": {"with_flaws": sum(1 for d in sec if d["judgement"]["security"]["apps_affected"]),
                       "programs_with_flaws": sum(d["judgement"]["security"]["apps_affected"] for d in sec),
                       "exploited": sum(d["judgement"]["security"]["kev"] for d in sec),
                       "critical": sum(d["judgement"]["security"]["critical"] for d in sec),
                       "updates": sum((d["summary"] or {}).get("updates") or 0 for d in rows),
                       "accepted": sum((v or {}).get("accepted") or 0 for v in short.values())},
            "history": list(days.values()), "reference": ref, "declared": said, "thresholds": judge.T,
            "silent_hours": SILENT_HOURS, "device_list": rows}


def _one_device(c, device_id: str, now: datetime) -> dict:
    try:
        dev = c.execute(DEVICES_SQL + "WHERE d.id = %s", (device_id,)).fetchone()
    except Exception:
        raise HTTPException(404, "No such device.")
    if not dev:
        raise HTTPException(404, "No such device.")          # also the answer for another organisation's device
    return _device_row(dev, now)


@app.get("/api/v1/devices/{device_id}")
def device_detail(device_id: str, who: dict = Depends(reader)):
    now = datetime.now(timezone.utc)
    with db.org(who["org_id"]) as c:
        dev = _one_device(c, device_id, now)
        snaps = c.execute("SELECT DISTINCT ON (kind) kind, received_at, payload FROM snapshots WHERE device_id=%s "
                          "ORDER BY kind, received_at DESC, id DESC", (device_id,)).fetchall()
        history = c.execute("SELECT kind, count(*) AS versions, min(received_at) AS first, max(received_at) AS last FROM snapshots "
                            "WHERE device_id=%s GROUP BY kind ORDER BY kind", (device_id,)).fetchall()
        j = c.execute("SELECT security, compliance FROM judgements WHERE device_id = %s", (device_id,)).fetchone()
        days = c.execute("SELECT day, framework, line FROM compliance_history WHERE device_id = %s AND day >= %s ORDER BY day",
                         (device_id, now.date() - timedelta(days=HISTORY_DAYS - 1))).fetchall()
        ref = _reference(c)
        fw, fws = _pick(c, None)
    return {**dev, "snapshots": {s["kind"]: {"received_at": _iso(s["received_at"]), "payload": s["payload"]} for s in snaps},
            "history": [{"kind": h["kind"], "versions": h["versions"], "first": _iso(h["first"]), "last": _iso(h["last"])} for h in history],
            "compliance": j["compliance"] if j else None, "flaws": (j["security"] or {}).get("flaws") if j else None,
            "support": (j["security"] or {}).get("support") if j else None,
            "compliance_history": [{"day": _iso(d["day"]), **d["line"]} for d in days if d["framework"] == "ce"],
            "histories": {k: [{"day": _iso(d["day"]), **d["line"]} for d in days if d["framework"] == k] for k in judge.FRAMEWORKS},
            "framework": fw, "frameworks": fws, "reference": ref}


@app.post("/api/v1/devices/{device_id}/exceptions")
async def accept_check(device_id: str, request: Request, who: dict = Depends(editor)):
    """Accept a failing check on one device, with the reason; an empty reason withdraws it. The check keeps its
    failing mark and stops counting against its control area. Written to the audit log."""
    body = await request.json()
    check_id, reason = _text(body.get("check_id"), 40), _text(body.get("reason"), 500)
    if not judge.CHECK_ID.fullmatch(check_id):
        raise HTTPException(400, "That is not a check.")
    now = datetime.now(timezone.utc)
    with db.org(who["org_id"]) as c:
        dev = _one_device(c, device_id, now)
        j = c.execute("SELECT security, compliance FROM judgements WHERE device_id = %s FOR UPDATE", (device_id,)).fetchone()
        if not j or not any(ch["id"] == check_id for g in j["compliance"].get("controls") or [] for ch in g["checks"]):
            raise HTTPException(404, "This device has no such check.")
        if reason:
            c.execute("INSERT INTO exceptions (org_id, device_id, check_id, reason, actor) VALUES (%s,%s,%s,%s,%s) "
                      "ON CONFLICT (device_id, check_id) DO UPDATE SET reason = EXCLUDED.reason, at = now(), actor = EXCLUDED.actor",
                      (who["org_id"], device_id, check_id, reason, _actor(who)))
        else:
            c.execute("DELETE FROM exceptions WHERE device_id = %s AND check_id = %s", (device_id, check_id))
        accepted = {r["check_id"]: {"reason": r["reason"], "ts": _iso(r["at"]), "actor": r["actor"]}
                    for r in c.execute("SELECT check_id, reason, at, actor FROM exceptions WHERE device_id = %s", (device_id,))}
        comp = judge.overlay(j["compliance"], accepted)       # the same counting the worker does, on what it stored
        sec = j["security"] or {}
        c.execute("UPDATE judgements SET compliance = %s, summary = %s WHERE device_id = %s",
                  (Jsonb(comp), Jsonb(judge.summary(comp, sec.get("flaws"), sec.get("support"))), device_id))
        for fw, line in judge.history_lines(comp).items():
            c.execute("INSERT INTO compliance_history (org_id, device_id, day, framework, line) VALUES (%s,%s,%s,%s,%s) "
                      "ON CONFLICT (device_id, day, framework) DO UPDATE SET line = EXCLUDED.line",
                      (who["org_id"], device_id, now.date(), fw, Jsonb(line)))
        c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                  (who["org_id"], _actor(who), "check.accepted" if reason else "check.acceptance_withdrawn",
                   Jsonb({"device": device_id, "name": dev["name"], "check": check_id, "reason": reason})))
    return {"ok": True}


LABELS = {"personal_data": "holds personal data", "critical": "critical"}


@app.post("/api/v1/devices/{device_id}/labels")
async def label_device(device_id: str, request: Request, who: dict = Depends(editor)):
    """Put a label on a device or take it off (spec F-1). A label is a person's statement, so it is recorded under
    their name; the device is judged again, because DPDP judges encryption and log retention by it."""
    body = await request.json()
    label, on = body.get("label"), body.get("on")
    if label not in LABELS or not isinstance(on, bool):
        raise HTTPException(400, "That is not a label, or not on/off.")
    now = datetime.now(timezone.utc)
    with db.org(who["org_id"]) as c:
        dev = _one_device(c, device_id, now)
        if on:
            done = c.execute("INSERT INTO device_labels (org_id, device_id, label, actor) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                             (who["org_id"], device_id, label, _actor(who))).rowcount
        else:
            done = c.execute("DELETE FROM device_labels WHERE device_id = %s AND label = %s", (device_id, label)).rowcount
        if done:
            c.execute("UPDATE devices SET judged_day = NULL WHERE id = %s", (device_id,))      # judge it again with the label
            c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                      (who["org_id"], _actor(who), "device.labelled" if on else "device.unlabelled",
                       Jsonb({"device": device_id, "name": dev["name"], "label": label})))
    return {"ok": True}


@app.post("/api/v1/declarations")
async def declare(request: Request, who: dict = Depends(editor)):
    """What the organisation states about things no program can measure. answer: yes | no | na | null (clears)."""
    body = await request.json()
    key, answer, note = _text(body.get("key"), 40), body.get("answer"), _text(body.get("note"), 500)
    dated = judge.agent.valid_date(body.get("dated"))
    if key not in judge.KEYS or answer not in ("yes", "no", "na", None):
        raise HTTPException(400, "That is not one of the declared questions, or not an answer.")
    if dated is None:
        raise HTTPException(400, "The date must be a day that has passed (yyyy-mm-dd).")
    with db.org(who["org_id"]) as c:
        if answer is None:
            c.execute("DELETE FROM declarations WHERE key = %s", (key,))
        else:
            c.execute("INSERT INTO declarations (org_id, key, answer, note, actor, dated) VALUES (%s,%s,%s,%s,%s,%s) "
                      "ON CONFLICT (org_id, key) DO UPDATE SET answer = EXCLUDED.answer, note = EXCLUDED.note, at = now(), actor = EXCLUDED.actor, "
                      "dated = EXCLUDED.dated", (who["org_id"], key, answer, note, _actor(who), dated or None))
        c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                  (who["org_id"], _actor(who), "declaration.changed", Jsonb({"key": key, "answer": answer, "note": note, "dated": dated})))
    return {"ok": True}


@app.post("/api/v1/frameworks")
async def set_frameworks(request: Request, who: dict = Depends(editor)):
    """Which frameworks the organisation's console shows, in order. Every device is judged under all of them
    anyway; this only chooses what is shown, and the first is shown first."""
    body = await request.json()
    keys = body.get("frameworks")
    if not isinstance(keys, list) or not keys or any(k not in judge.FRAMEWORKS for k in keys) or len(set(keys)) != len(keys):
        raise HTTPException(400, "Choose at least one of the listed frameworks.")
    with db.org(who["org_id"]) as c:
        before = _frameworks(c)
        c.execute("UPDATE organisations SET frameworks = %s", (keys,))
        c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                  (who["org_id"], _actor(who), "frameworks.changed", Jsonb({"from": before, "to": keys})))
    return {"ok": True, "frameworks": keys}


def _report(c, now: datetime, only: str | None = None, fw: str = "ce") -> str:
    org = c.execute("SELECT name FROM organisations").fetchone()
    rows = c.execute("SELECT d.id, d.name, d.last_seen, d.summary, j.judged_at, j.security, j.compliance FROM devices d "
                     "LEFT JOIN judgements j ON j.device_id = d.id " + ("WHERE d.id = %s " if only else "") + "ORDER BY lower(d.name)",
                     (only,) if only else ()).fetchall()
    stamp = lambda v: (_iso(v) or "")[:16].replace("T", " ") or None
    devs = [({"name": r["name"], "windows": (r["summary"] or {}).get("windows"), "model": ((r["summary"] or {}).get("model") or "").strip(),
              "last_seen": stamp(r["last_seen"])},
             r["compliance"], (r["security"] or {}).get("flaws") if r["compliance"] else None, stamp(r["judged_at"])) for r in rows]
    return judge.report_text(org["name"] if org else "", stamp(now) + " UTC", devs, _declared(c, fw), fw)


@app.get("/api/v1/report")
def report(framework: str | None = None, who: dict = Depends(reader)):
    """The evidence for the whole organisation as plain text: to paste into a questionnaire or send to a broker."""
    now = datetime.now(timezone.utc)
    with db.org(who["org_id"]) as c:
        fw, _ = _pick(c, framework)
        text = _report(c, now, fw=fw)
    return {"generated_at": _iso(now), "framework": fw, "text": text}


@app.get("/api/v1/devices/{device_id}/report")
def device_report(device_id: str, framework: str | None = None, who: dict = Depends(reader)):
    now = datetime.now(timezone.utc)
    with db.org(who["org_id"]) as c:
        _one_device(c, device_id, now)
        fw, _ = _pick(c, framework)
        text = _report(c, now, device_id, fw)
    return {"generated_at": _iso(now), "framework": fw, "text": text}


@app.get("/api/v1/shared")
def shared(framework: str | None = None, authorization: str | None = Header(default=None)):
    """What a share link shows: the organisation's devices with their checks, the declarations and the report.
    Read-only, no account needed, until the link expires or is withdrawn. Every opening is counted."""
    token = authorization[6:].strip() if authorization and authorization.lower().startswith("share ") else ""
    with db.anon() as c:
        link = c.execute("SELECT * FROM auth_share(%s)", (db.digest(token),)).fetchone() if token else None
    if not link:
        raise HTTPException(401, "This link is not valid any more: it expired or was withdrawn.")
    now = datetime.now(timezone.utc)
    with db.org(link["org_id"]) as c:
        org = c.execute("SELECT name FROM organisations").fetchone()
        rows = c.execute("SELECT d.id, d.name, d.last_seen, d.summary, j.judged_at, j.summary AS judgement, j.compliance FROM devices d "
                         "LEFT JOIN judgements j ON j.device_id = d.id ORDER BY lower(d.name)").fetchall()
        fw, fws = _pick(c, framework)
        fws = [f for f in fws if f["shown"]]                  # a share link sees only what the organisation shows
        if fw not in [f["key"] for f in fws]:
            fw = fws[0]["key"]
        said, text = _declared(c, fw), _report(c, now, fw=fw)
    judged = [r for r in rows if r["judgement"]]
    short = {r["id"]: judge.framework_summary(r["judgement"], fw) for r in judged}
    return {"organisation": org["name"] if org else "", "label": link["label"], "expires_at": _iso(link["expires_at"]), "generated_at": _iso(now),
            "devices": len(rows), "judged": len(judged),
            "framework": fw, "frameworks": fws,
            "all_passing": sum(1 for v in short.values() if v and v["controls_passing"] == v["controls"]),
            "areas": [{"key": k, "title": t, "about": about,
                       **{s: sum(1 for v in short.values() if ((v or {}).get("areas") or {}).get(k) == s) for s in ("pass", "fail", "warn", "unknown", "info")}}
                      for k, t, about in _areas(fw)],
            "device_list": [{"id": str(r["id"]), "name": r["name"], "windows": (r["summary"] or {}).get("windows"),
                             "model": ((r["summary"] or {}).get("model") or "").strip(), "last_seen": _iso(r["last_seen"]),
                             "judged_at": _iso(r["judged_at"]), "compliance": judge.profile(r["compliance"], fw),
                             "security": (r["judgement"] or {}).get("security")} for r in rows],
            "declared": said, "text": text}


@app.get("/api/v1/software")
def software(who: dict = Depends(reader)):
    """Which program is on which devices, in which versions, with what is known about it."""
    with db.org(who["org_id"]) as c:
        rows = c.execute("SELECT d.id, d.name, s.payload, j.security FROM devices d "
                         "JOIN LATERAL (SELECT payload FROM snapshots WHERE device_id = d.id AND kind = 'apps' "
                         "              ORDER BY received_at DESC, id DESC LIMIT 1) s ON true "
                         "LEFT JOIN judgements j ON j.device_id = d.id ORDER BY lower(d.name)").fetchall()
    out = {}
    for r in rows:
        sec = r["security"] or {}
        flaw = {(a["name"], a.get("version")): a for a in (sec.get("flaws") or {}).get("apps") or []}
        sup = {(a["name"], a.get("version")): a for a in (sec.get("support") or {}).get("programs") or []}
        for a in (r["payload"].get("apps") if isinstance(r["payload"], dict) else None) or []:
            if not isinstance(a, dict) or not a.get("name"):
                continue
            name, ver = _text(a["name"], 200), _text(a.get("version"), 80)
            e = out.setdefault((name.lower(), a.get("kind")), {"name": name, "publisher": _text(a.get("publisher"), 120), "kind": a.get("kind"),
                                                              "devices": 0, "versions": {}, "cves": 0, "exploited": 0, "ended": False, "newer": None})
            e["devices"] += 1
            e["versions"].setdefault(ver, []).append({"id": str(r["id"]), "name": r["name"]})
            f, u = flaw.get((a["name"], a.get("version"))), sup.get((a["name"], a.get("version")))
            if f:
                e["cves"] = max(e["cves"], len(f["cves"]))
                e["exploited"] = max(e["exploited"], sum(1 for x in f["cves"] if x.get("kev")))
            e["ended"] = e["ended"] or bool(u and u.get("state") == "ended")
            e["newer"] = e["newer"] or a.get("available")
    items = [{**e, "versions": [{"version": v, "devices": d} for v, d in sorted(e["versions"].items())]} for e in out.values()]
    items.sort(key=lambda e: (-e["exploited"], -e["cves"], not e["ended"], e["name"].lower()))
    return {"devices": len(rows), "programs": items}


@app.get("/api/v1/audit")
def audit(who: dict = Depends(reader)):
    with db.org(who["org_id"]) as c:
        rows = c.execute("SELECT at, actor, action, detail FROM audit_log ORDER BY at DESC, id DESC LIMIT 200").fetchall()
    return {"entries": [{"at": _iso(r["at"]), "actor": r["actor"], "action": r["action"], "detail": r["detail"]} for r in rows]}
