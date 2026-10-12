"""
Fleet server, phase 1: agents enrol and report what is installed; an administrator sees the list of devices.

Agents call:    POST /api/v1/enrol      a one-time token -> a device id and key
                POST /api/v1/checkin    the device key   -> stores what changed since the last report
Console calls:  GET  /api/v1/devices, /api/v1/devices/{id}, /api/v1/audit      with an organisation admin key
Anyone:         GET  /healthz, and the fleet page at /

Nothing here judges a device yet (flaws, compliance): that is phase 2. Nothing can send a command to a device:
that is phase 5. See docs/architecture.md.
"""
import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb

from . import db

KINDS = ("device", "apps", "services", "network", "posture")
MAX_BODY = 5 * 1024 * 1024          # a full report from the first PC is about 60 KB
CHECKIN_SECONDS = 900
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app):
    yield
    db.close()


app = FastAPI(title="Shadow Filer fleet server", version="0.1.0", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def limits_and_headers(request: Request, call_next):
    size = request.headers.get("content-length")
    if size and size.isdigit() and int(size) > MAX_BODY:
        return JSONResponse({"detail": "The report is too large."}, status_code=413)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer ") or len(authorization) < 20:
        raise HTTPException(401, "A key is required.")
    return authorization[7:].strip()


def device(authorization: str | None = Header(default=None)) -> dict:
    with db.anon() as c:
        row = c.execute("SELECT * FROM auth_device(%s)", (db.digest(_bearer(authorization)),)).fetchone()
    if not row:
        raise HTTPException(401, "Unknown device key.")
    return row


def admin(authorization: str | None = Header(default=None)) -> dict:
    with db.anon() as c:
        row = c.execute("SELECT * FROM auth_admin(%s)", (db.digest(_bearer(authorization)),)).fetchone()
    if not row:
        raise HTTPException(401, "Unknown admin key.")
    return row


def _text(v, limit: int = 200) -> str:
    return str(v or "").strip()[:limit]


def summarise(snaps: dict) -> dict:
    """The few facts the fleet list shows per device, from what it reported. No judging: that is phase 2."""
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
def fleet_page():
    return FileResponse(STATIC / "index.html")


@app.post("/api/v1/enrol")
async def enrol(request: Request):
    """Swap a valid enrolment token for a device identity. The device key is shown once and never stored."""
    body = await request.json()
    token, name = _text(body.get("token"), 200), _text(body.get("name"), 100)
    if not token or not name:
        raise HTTPException(400, "A token and a device name are required.")
    with db.anon() as c:
        row = c.execute("SELECT * FROM redeem_token(%s)", (db.digest(token),)).fetchone()
    if not row:
        raise HTTPException(403, "That enrolment token is not valid, has expired or has been used up.")
    key = secrets.token_urlsafe(32)
    with db.org(row["org_id"]) as c:
        dev = c.execute("INSERT INTO devices (org_id, name, key_hash, agent_version) VALUES (%s,%s,%s,%s) RETURNING id",
                        (row["org_id"], name, db.digest(key), _text(body.get("agent_version"), 40))).fetchone()
        c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                  (row["org_id"], f"token:{row['token_id']}", "device.enrolled", Jsonb({"device": str(dev["id"]), "name": name})))
    return {"device_id": str(dev["id"]), "device_key": key, "checkin_seconds": CHECKIN_SECONDS}


@app.post("/api/v1/checkin")
async def checkin(request: Request, who: dict = Depends(device)):
    """Store what the device reports. A kind is stored only when it differs from the last one kept."""
    body = await request.json()
    snaps = body.get("snapshots")
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
        c.execute("UPDATE devices SET last_seen = now(), agent_version = %s, summary = %s WHERE id = %s",
                  (_text(body.get("agent_version"), 40), Jsonb(summarise(latest)), who["device_id"]))
    return {"ok": True, "stored": stored, "checkin_seconds": CHECKIN_SECONDS}


def _iso(v):
    return v.astimezone(timezone.utc).isoformat(timespec="seconds") if isinstance(v, datetime) else v


@app.get("/api/v1/devices")
def devices(who: dict = Depends(admin)):
    with db.org(who["org_id"]) as c:
        org = c.execute("SELECT name FROM organisations").fetchone()
        rows = c.execute("SELECT id, name, enrolled_at, last_seen, agent_version, summary FROM devices ORDER BY lower(name)").fetchall()
    now = datetime.now(timezone.utc)
    return {"organisation": org["name"] if org else "", "generated_at": _iso(now), "checkin_seconds": CHECKIN_SECONDS,
            "devices": [{"id": str(r["id"]), "name": r["name"], "enrolled_at": _iso(r["enrolled_at"]), "last_seen": _iso(r["last_seen"]),
                         "silent_seconds": int((now - r["last_seen"]).total_seconds()) if r["last_seen"] else None,
                         "agent_version": r["agent_version"], "summary": r["summary"]} for r in rows]}


@app.get("/api/v1/devices/{device_id}")
def device_detail(device_id: str, who: dict = Depends(admin)):
    with db.org(who["org_id"]) as c:
        try:
            dev = c.execute("SELECT id, name, enrolled_at, last_seen, agent_version, summary FROM devices WHERE id = %s", (device_id,)).fetchone()
        except Exception:
            raise HTTPException(404, "No such device.")
        if not dev:
            raise HTTPException(404, "No such device.")          # also the answer for another organisation's device
        snaps = c.execute("SELECT DISTINCT ON (kind) kind, received_at, payload FROM snapshots WHERE device_id=%s "
                          "ORDER BY kind, received_at DESC, id DESC", (device_id,)).fetchall()
        history = c.execute("SELECT kind, count(*) AS versions, min(received_at) AS first, max(received_at) AS last FROM snapshots "
                            "WHERE device_id=%s GROUP BY kind ORDER BY kind", (device_id,)).fetchall()
    return {"id": str(dev["id"]), "name": dev["name"], "enrolled_at": _iso(dev["enrolled_at"]), "last_seen": _iso(dev["last_seen"]),
            "agent_version": dev["agent_version"], "summary": dev["summary"],
            "snapshots": {s["kind"]: {"received_at": _iso(s["received_at"]), "payload": s["payload"]} for s in snaps},
            "history": [{"kind": h["kind"], "versions": h["versions"], "first": _iso(h["first"]), "last": _iso(h["last"])} for h in history]}


@app.get("/api/v1/audit")
def audit(who: dict = Depends(admin)):
    with db.org(who["org_id"]) as c:
        rows = c.execute("SELECT at, actor, action, detail FROM audit_log ORDER BY at DESC, id DESC LIMIT 200").fetchall()
    return {"entries": [{"at": _iso(r["at"]), "actor": r["actor"], "action": r["action"], "detail": r["detail"]} for r in rows]}
