"""
Mail domain check (spec F-3, CERT-In NES.4 "SPF, DKIM and DMARC"). The organisation enters its own mail domain
(and, optionally, the DKIM selectors it uses: a DKIM record cannot be found without its selector). Once a day the
worker looks up the domain's TXT records: SPF at the domain, DMARC at _dmarc.<domain>, DKIM at
<selector>._domainkey.<domain>.

This is the one request the worker makes that carries something about a customer: the DNS query names the
domain. Allowed by the owner on 11 Nov 2026 (spec decision D-3). It goes through the container's own resolver and
nowhere else; nothing about devices is in it.

Judging (`org.mail`, an organisation-level check shown for CERT-In): SPF present and DMARC policy quarantine or
reject = pass; DMARC p=none = a look (it only reports); no SPF or no DMARC = fail; a named DKIM selector with no
key = a look. A lookup that failed (no answer, timeout) is unknown, never a pass.

  GET  /api/v1/mail-domain        the domain, the selectors and the last result
  POST /api/v1/mail-domain        set the domain and selectors ({domain: ""} removes it)
"""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb

from . import db
from .people import editor, reader

router = APIRouter(prefix="/api/v1")
DOMAIN = re.compile(r"(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
SELECTOR = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,62})")


def _txt(resolve, name: str):
    """The TXT strings at a name: a list (empty when the name has none), or None when the lookup failed."""
    try:
        return resolve(name)
    except Exception:          # timeout, no server, refused: not known
        return None


def dns_resolver(timeout: float = 5.0):
    import dns.exception
    import dns.resolver
    r = dns.resolver.Resolver()
    r.lifetime = timeout

    def resolve(name: str) -> list:
        try:
            ans = r.resolve(name, "TXT")
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []
        return [b"".join(x.strings).decode("utf-8", "replace") for x in ans]
    return resolve


def look_up(domain: str, selectors: list, resolve) -> dict:
    """What the DNS says now. Only the records' own words are kept, and only those that are about mail."""
    spf = _txt(resolve, domain)
    dmarc = _txt(resolve, f"_dmarc.{domain}")
    out = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "spf": None if spf is None else [t for t in spf if t.lower().startswith("v=spf1")],
           "dmarc": None if dmarc is None else [t for t in dmarc if t.lower().startswith("v=dmarc1")], "dkim": {}}
    for s in selectors:
        k = _txt(resolve, f"{s}._domainkey.{domain}")
        out["dkim"][s] = None if k is None else any("p=" in t.replace(" ", "") for t in k)
    return out


def _policy(dmarc: list) -> str | None:
    m = re.search(r"(?:^|;)\s*p\s*=\s*([a-z]+)", (dmarc or [""])[0].lower())
    return m.group(1) if m else None


def check(row: dict | None) -> dict | None:
    """The organisation's mail check from the last lookup; None when no domain is entered."""
    if not row or not row.get("domain"):
        return None
    title = "The mail domain is protected against spoofing (SPF, DKIM, DMARC)"
    res = row.get("result") or {}
    base = {"id": "org.mail", "title": title, "evidence": [], "to": "evidence", "accepted": None}
    if not res:
        return {**base, "status": "unknown", "detail": f"{row['domain']} has not been looked up yet (once a day).", "fix": None}
    spf, dmarc, dkim = res.get("spf"), res.get("dmarc"), res.get("dkim") or {}
    if spf is None or dmarc is None:
        return {**base, "status": "unknown", "detail": f"The DNS lookup for {row['domain']} failed on {res['checked_at'][:10]}.", "fix": None}
    pol = _policy(dmarc)
    gaps = (["no SPF record"] if not spf else []) + (["no DMARC record"] if not dmarc else [])
    looks = (["DMARC only reports (p=none): spoofed mail is still delivered"] if dmarc and pol == "none" else []) + \
        [f"no DKIM key for the selector {s}" for s, ok in dkim.items() if ok is False] + \
        [f"the DKIM lookup for {s} failed" for s, ok in dkim.items() if ok is None]
    status = "fail" if gaps else "warn" if looks or pol not in ("quarantine", "reject", "none") else "pass"
    return {**base, "status": status,
            "detail": (f"{row['domain']}: " + "; ".join(gaps + looks) + "." if gaps or looks else
                       f"{row['domain']} has SPF and a DMARC policy of {pol}" + (f", and DKIM keys for {', '.join(dkim)}." if dkim else
                                                                                   ". No DKIM selector was named, so DKIM is not checked."))
            + f" Looked up {res['checked_at'][:10]}.",
            "evidence": [f"SPF: {spf[0]}" if spf else "SPF: none", f"DMARC: {dmarc[0]}" if dmarc else "DMARC: none"]
            + [f"DKIM {s}: {'key found' if ok else 'no key' if ok is False else 'lookup failed'}" for s, ok in dkim.items()],
            "fix": None if status == "pass" else "At the domain's DNS host: publish SPF (v=spf1 ... -all), DKIM from the mail provider, and "
                                                 "DMARC with p=quarantine or p=reject once reports look right."}


@router.get("/mail-domain")
def get_domain(who: dict = Depends(reader)):
    with db.org(who["org_id"]) as c:
        r = c.execute("SELECT domain, selectors, result, updated_by FROM mail_domains").fetchone()
    return {"domain": r["domain"] if r else "", "selectors": list(r["selectors"]) if r else [], "result": r["result"] if r else None,
            "check": check(dict(r)) if r else None}


@router.post("/mail-domain")
async def set_domain(request: Request, who: dict = Depends(editor)):
    body = await request.json()
    body = body if isinstance(body, dict) else {}
    domain = str(body.get("domain") or "").strip().lower().rstrip(".")
    sel = body.get("selectors") or []
    if domain and not DOMAIN.fullmatch(domain):
        raise HTTPException(400, "That is not a domain name (like example.co.in).")
    if not isinstance(sel, list) or len(sel) > 5 or not all(isinstance(s, str) and SELECTOR.fullmatch(s.strip().lower()) for s in sel):
        raise HTTPException(400, "DKIM selectors: up to five names like selector1 or google.")
    sel = sorted({s.strip().lower() for s in sel})
    with db.org(who["org_id"]) as c:
        if domain:
            c.execute("INSERT INTO mail_domains (org_id, domain, selectors, updated_by) VALUES (%s,%s,%s,%s) ON CONFLICT (org_id) DO UPDATE "
                      "SET domain = EXCLUDED.domain, selectors = EXCLUDED.selectors, result = NULL, checked_day = NULL, updated_at = now(), "
                      "updated_by = EXCLUDED.updated_by", (who["org_id"], domain, sel, who["actor"]))
        else:
            c.execute("DELETE FROM mail_domains")
        c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)",
                  (who["org_id"], who["actor"], "mail_domain.changed", Jsonb({"domain": domain, "selectors": sel})))
    return {"ok": True}


def run(today, resolve=None, log=None) -> int:
    """For the worker: look up every organisation's domain not yet looked up today. Returns how many."""
    resolve = resolve or dns_resolver()
    with db.anon() as c:
        due = [r["org_id"] for r in c.execute("SELECT * FROM mail_queue(%s)", (today,))]
    for org in due:
        with db.org(org) as c:
            r = c.execute("SELECT domain, selectors FROM mail_domains").fetchone()
        if not r:
            continue
        res = look_up(r["domain"], list(r["selectors"]), resolve)          # no database connection held while waiting on DNS
        with db.org(org) as c:
            c.execute("UPDATE mail_domains SET result = %s, checked_day = %s WHERE domain = %s", (Jsonb(res), today, r["domain"]))
        if log:
            log.info("mail domain of organisation %s looked up", org)       # never the domain in the log
    return len(due)
