"""
Incident register (spec F-21): what happened, when it was noticed, which devices, whether personal data was involved,
and two clocks. Nothing is submitted anywhere: the fields are laid out after CERT-In's incident reporting form so
they can be copied into it, and the owner reports.

  CERT-In: report within 6 hours of noticing the incident (directions under section 70B(6) of the IT Act, 2022).
  DPDP Rule 7(2)(b): when personal data is involved, updated and detailed information to the Data Protection Board
  within 72 hours of becoming aware of the breach (Rule 7(1) and 7(2)(a): the affected people and the Board are
  told without delay).

An incident is evidence: it can be updated and closed, never deleted. Every change is in the audit log under the
person's name. Customer data: `incidents` has org_id and row-level security like every other such table.

  GET  /api/v1/incidents              the register, newest first, with the clocks
  POST /api/v1/incidents              record one
  POST /api/v1/incidents/{id}         change it (only the fields sent)
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb

from . import db
from .people import editor, reader

router = APIRouter(prefix="/api/v1")

CERTIN_HOURS = 6
BOARD_HOURS = 72
# The kinds of incident CERT-In lists as reportable (Annexure I of its directions of 28 Apr 2022), shortened.
KINDS = ("Targeted scanning or probing of critical networks or systems", "Compromise of critical systems or information",
         "Unauthorised access to IT systems or data", "Website defacement or intrusion", "Malicious code (virus, ransomware, bots, spyware)",
         "Attack on servers (database, mail, DNS) or network devices", "Identity theft, spoofing or phishing",
         "Denial of service (DoS, DDoS)", "Attack on critical infrastructure or industrial control systems",
         "Attack on applications (e-governance, e-commerce and others)", "Data breach", "Data leak", "Attack on IoT devices",
         "Incident affecting digital payment systems", "Malicious or fake mobile apps", "Unauthorised access to social media accounts",
         "Incident affecting cloud systems", "Incident affecting big data, blockchain, virtual assets or robotics systems",
         "Incident affecting AI or machine learning systems", "Other")
TEXT = {"title": 200, "description": 4000, "systems": 1000, "actions": 4000, "contact": 300}
TIMES = ("occurred_at", "detected_at", "certin_reported_at", "board_reported_at", "people_told_at", "closed_at")


def _when(v, name: str):
    """An ISO time with its zone, not in the future (a few minutes' slack for clocks), or None to clear."""
    if v in (None, ""):
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"{name}: not a time.")
    if t.tzinfo is None:
        raise HTTPException(400, f"{name}: the time needs its time zone.")
    if t > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(400, f"{name}: that is in the future.")
    return t


def _fields(c, body: dict, new: bool) -> dict:
    out = {}
    for k, n in TEXT.items():
        if k in body:
            out[k] = str(body[k] or "").strip()[:n]
    if "kind" in body:
        if body["kind"] not in KINDS:
            raise HTTPException(400, "That is not one of the listed kinds of incident.")
        out["kind"] = body["kind"]
    if "personal_data" in body:
        if not isinstance(body["personal_data"], bool):
            raise HTTPException(400, "personal_data is true or false.")
        out["personal_data"] = body["personal_data"]
    for k in TIMES:
        if k in body:
            out[k] = _when(body[k], k)
    if "devices" in body:
        ids = body["devices"] if isinstance(body["devices"], list) else None
        try:
            ids = [str(uuid.UUID(str(x))) for x in ids or []] if ids is not None else None
        except ValueError:
            ids = None
        if ids is None or len(ids) > 500:
            raise HTTPException(400, "devices is a list of this organisation's device ids.")
        # row-level security: only this organisation's devices are visible, so another's id is simply not found
        found = {str(r["id"]) for r in c.execute("SELECT id FROM devices WHERE id = ANY(%s::uuid[])", (ids,))}
        if set(ids) - found:
            raise HTTPException(400, "devices is a list of this organisation's device ids.")
        out["devices"] = sorted(set(ids))
    if new and (not out.get("title") or not out.get("detected_at")):
        raise HTTPException(400, "An incident needs a title and the time it was noticed.")
    if "detected_at" in out and out["detected_at"] is None:
        raise HTTPException(400, "The time it was noticed cannot be cleared.")
    return out


def clocks(r: dict, now: datetime) -> dict:
    """The two deadlines, counted from when the incident was noticed."""
    det = r["detected_at"]
    certin_due = det + timedelta(hours=CERTIN_HOURS)
    board_due = det + timedelta(hours=BOARD_HOURS) if r["personal_data"] else None
    state = lambda done, due: None if due is None else "done" if done else "overdue" if now > due else "running"
    return {"certin_due": certin_due.isoformat(timespec="seconds"), "certin": state(r["certin_reported_at"], certin_due),
            "board_due": board_due.isoformat(timespec="seconds") if board_due else None, "board": state(r["board_reported_at"], board_due)}


def _row(r: dict, now: datetime, names: dict) -> dict:
    iso = lambda v: v.isoformat(timespec="seconds") if v else None
    return {"id": str(r["id"]), "title": r["title"], "kind": r["kind"], "description": r["description"], "systems": r["systems"],
            "actions": r["actions"], "contact": r["contact"], "personal_data": r["personal_data"],
            "devices": [{"id": str(d), "name": names.get(str(d), "(removed)")} for d in r["devices"]],
            **{k: iso(r[k]) for k in TIMES}, "created_at": iso(r["created_at"]), "created_by": r["created_by"],
            "updated_at": iso(r["updated_at"]), "updated_by": r["updated_by"], **clocks(r, now)}


@router.get("/incidents")
def list_incidents(who: dict = Depends(reader)):
    now = datetime.now(timezone.utc)
    with db.org(who["org_id"]) as c:
        rows = c.execute("SELECT * FROM incidents ORDER BY detected_at DESC").fetchall()
        names = {str(r["id"]): r["name"] for r in c.execute("SELECT id, name FROM devices")}
    return {"kinds": KINDS, "certin_hours": CERTIN_HOURS, "board_hours": BOARD_HOURS, "generated_at": now.isoformat(timespec="seconds"),
            "incidents": [_row(r, now, names) for r in rows]}


@router.post("/incidents")
async def add_incident(request: Request, who: dict = Depends(editor)):
    body = await request.json()
    with db.org(who["org_id"]) as c:
        f = _fields(c, body if isinstance(body, dict) else {}, True)
        f.setdefault("kind", "Other")
        cols = list(f)
        row = c.execute(f"INSERT INTO incidents (org_id, created_by, updated_by, {', '.join(cols)}) VALUES (%s,%s,%s,{', '.join(['%s'] * len(cols))}) "
                        "RETURNING id", (who["org_id"], who["actor"], who["actor"], *[f[k] for k in cols])).fetchone()
        c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                  (who["org_id"], who["actor"], "incident.recorded", Jsonb({"incident": str(row["id"]), "title": f["title"]})))
    return {"ok": True, "id": str(row["id"])}


@router.post("/incidents/{incident_id}")
async def change_incident(incident_id: str, request: Request, who: dict = Depends(editor)):
    body = await request.json()
    try:
        iid = str(uuid.UUID(incident_id))
    except ValueError:
        raise HTTPException(404, "No such incident.")
    with db.org(who["org_id"]) as c:
        f = _fields(c, body if isinstance(body, dict) else {}, False)
        if not f:
            raise HTTPException(400, "Nothing to change.")
        if "title" in f and not f["title"]:
            raise HTTPException(400, "An incident needs a title.")
        sets = ", ".join(f"{k} = %s" for k in f)
        row = c.execute(f"UPDATE incidents SET {sets}, updated_at = now(), updated_by = %s WHERE id = %s RETURNING title",
                        (*f.values(), who["actor"], iid)).fetchone()
        if row:
            c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                      (who["org_id"], who["actor"], "incident.changed", Jsonb({"incident": iid, "title": row["title"], "fields": sorted(f)})))
    if not row:
        raise HTTPException(404, "No such incident.")           # also the answer for another organisation's incident
    return {"ok": True}
