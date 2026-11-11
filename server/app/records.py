"""
Governance and reviews (spec F-23 and F-24): who is in charge of security, when the security policy was approved
and is next due for review, and the sign-offs of the periodic reviews: access (CERT-In ACIM.3, quarterly) and logs
(DPDP Rule 6(1)(c) "logs, monitoring and review"; the rule gives no period). Overdue items show on the Overview.

A review is a person's statement that they did it: recorded under their name, never edited or deleted (a newer
one replaces it as "the last review"). The policy document itself waits for evidence uploads (spec D-4).

  GET  /api/v1/records          the governance record, the reviews with their due dates, what is overdue
  POST /api/v1/reviews          sign off a review: {kind: access|logs, reviewed_on, note}
  POST /api/v1/governance       the security in-charge and the policy dates (only the fields sent)
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb

from . import db
from .judge import agent
from .people import editor, reader

router = APIRouter(prefix="/api/v1")

# access: CERT-In ACIM.3 asks for a quarterly review. logs: DPDP asks for review without a period; 30 days is our own.
REVIEWS = {"access": {"title": "Access review", "days": 90,
                      "about": "Who has which accounts and rights, on every PC and service; leavers removed. CERT-In ACIM.3: quarterly and on exit."},
           "logs": {"title": "Log review", "days": 30,
                    "about": "Someone looked at the logs for signs of unauthorised access. DPDP Rule 6(1)(c) asks for review and gives no "
                             "period; 30 days is our own number."}}
GOV_TEXT = {"incharge_name": 200, "incharge_contact": 300}


def _past_day(v, name: str) -> str:
    d = agent.valid_date(v)
    if not d:
        raise HTTPException(400, f"{name}: a day that has passed (yyyy-mm-dd).")
    return d


def _any_day(v, name: str):
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)).isoformat() if len(str(v)) == 10 else None
    except ValueError:
        raise HTTPException(400, f"{name}: a day (yyyy-mm-dd).")


def view(c, today: date) -> dict:
    out = {"reviews": {}, "governance": None, "due": []}
    for kind, r in REVIEWS.items():
        rows = c.execute("SELECT reviewed_on, note, actor, at FROM reviews WHERE kind = %s ORDER BY reviewed_on DESC, at DESC LIMIT 20", (kind,)).fetchall()
        last = rows[0]["reviewed_on"] if rows else None
        due = last + timedelta(days=r["days"]) if last else None
        state = "never" if not last else "overdue" if today > due else "done"
        out["reviews"][kind] = {**r, "last": last.isoformat() if last else None, "due": due.isoformat() if due else None, "state": state,
                                "history": [{"reviewed_on": x["reviewed_on"].isoformat(), "note": x["note"], "actor": x["actor"],
                                             "at": x["at"].isoformat(timespec="seconds")} for x in rows]}
        if state != "done":
            out["due"].append({"kind": kind, "text": f"{r['title']}: " + ("never recorded." if state == "never" else f"due since {due.isoformat()}.")})
    g = c.execute("SELECT * FROM governance").fetchone()
    if g:
        out["governance"] = {"incharge_name": g["incharge_name"], "incharge_contact": g["incharge_contact"],
                             "policy_approved_on": g["policy_approved_on"].isoformat() if g["policy_approved_on"] else None,
                             "policy_next_review": g["policy_next_review"].isoformat() if g["policy_next_review"] else None,
                             "updated_at": g["updated_at"].isoformat(timespec="seconds"), "updated_by": g["updated_by"]}
    gv = out["governance"] or {}
    if not gv.get("incharge_name"):
        out["due"].append({"kind": "incharge", "text": "No security in-charge is named (CERT-In GC.1)."})
    if not gv.get("policy_approved_on"):
        out["due"].append({"kind": "policy", "text": "No approval date for a security policy is recorded (CERT-In GC.2)."})
    elif gv.get("policy_next_review") and gv["policy_next_review"] < today.isoformat():
        out["due"].append({"kind": "policy", "text": f"The security policy was due for review on {gv['policy_next_review']} (CERT-In GC.3)."})
    return out


@router.get("/records")
def records(who: dict = Depends(reader)):
    with db.org(who["org_id"]) as c:
        return view(c, datetime.now(timezone.utc).date())


@router.post("/reviews")
async def add_review(request: Request, who: dict = Depends(editor)):
    body = await request.json()
    kind = body.get("kind") if isinstance(body, dict) else None
    if kind not in REVIEWS:
        raise HTTPException(400, "kind is access or logs.")
    day = _past_day(body.get("reviewed_on"), "reviewed_on")
    note = str(body.get("note") or "").strip()[:1000]
    with db.org(who["org_id"]) as c:
        c.execute("INSERT INTO reviews (org_id, kind, reviewed_on, note, actor) VALUES (%s,%s,%s,%s,%s)", (who["org_id"], kind, day, note, who["actor"]))
        c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                  (who["org_id"], who["actor"], "review.recorded", Jsonb({"kind": kind, "reviewed_on": day, "note": note})))
    return {"ok": True}


@router.post("/governance")
async def set_governance(request: Request, who: dict = Depends(editor)):
    body = await request.json()
    body = body if isinstance(body, dict) else {}
    f = {k: str(body[k] or "").strip()[:n] for k, n in GOV_TEXT.items() if k in body}
    if "policy_approved_on" in body:
        f["policy_approved_on"] = _past_day(body["policy_approved_on"], "policy_approved_on") if body["policy_approved_on"] else None
    if "policy_next_review" in body:
        f["policy_next_review"] = _any_day(body["policy_next_review"], "policy_next_review")
    if not f:
        raise HTTPException(400, "Nothing to change.")
    cols = list(f)
    with db.org(who["org_id"]) as c:
        c.execute(f"INSERT INTO governance (org_id, updated_by, {', '.join(cols)}) VALUES (%s,%s,{', '.join(['%s'] * len(cols))}) "
                  f"ON CONFLICT (org_id) DO UPDATE SET updated_at = now(), updated_by = EXCLUDED.updated_by, "
                  + ", ".join(f"{k} = EXCLUDED.{k}" for k in cols), (who["org_id"], who["actor"], *f.values()))
        c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                  (who["org_id"], who["actor"], "governance.changed", Jsonb({k: f[k] for k in cols})))
    return {"ok": True}
