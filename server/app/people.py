"""
Who is calling, and what they may do (phase 3): signing in, the second factor, roles, people, share links,
enrolment tokens.

Three roles, each able to do what the one before it can:
  auditor   read everything about the organisation's devices; change nothing
  admin     also: accept a failing check, record a declaration, make and withdraw share links, make enrolment
            tokens, remove a device
  owner     also: add people, change their role, switch them off, let them set a new password or second factor

A person signs in with their address and password, then a code from their authenticator app; without the code
the session opens nothing. Requests that change something must also carry the console's own header, so a
page on another site cannot make a signed-in browser act (the cookie is SameSite=Strict as well).

An organisation key (phase 1, `manage admin-key`) still works for scripts, read-only.

A handler never raises inside `db.org()` after writing something that has to stay (a failed sign-in is
counted even though the request is refused): it leaves the block first.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg import errors
from psycopg.types.json import Jsonb

from . import auth, db

router = APIRouter(prefix="/api/v1")
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,180}\.[^@\s.]{2,24}")
REFUSED = "That address and password do not match an account, or the account is locked for a few minutes after too many tries."
WRONG_CODE = "That code is not right, or it was already used. Wait for the next one."


def _text(v, limit: int = 200) -> str:
    return str(v or "").strip()[:limit]


def _iso(v):
    return v.astimezone(timezone.utc).isoformat(timespec="seconds") if isinstance(v, datetime) else v


def _int(v, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(v)))
    except (TypeError, ValueError):
        return default


def _id(value: str, what: str = "No such entry.") -> str:
    """An id from the address, or 'not found': a made-up one must not reach the database as a broken query."""
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(404, what) from None


def record(c, org_id, actor: str, action: str, detail: dict) -> None:
    c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,%s,%s,%s)", (org_id, actor, action, Jsonb(detail)))


# --------------------------------------------------------------------------- who is calling
def session_of(request: Request) -> dict | None:
    token = request.cookies.get(auth.COOKIE)
    if not token:
        return None
    with db.anon() as c:
        return c.execute("SELECT * FROM auth_session(%s,%s)", (db.digest(token), auth.IDLE_SECONDS)).fetchone()


def principal(request: Request, authorization: str | None = Header(default=None)) -> dict:
    s = session_of(request)
    if s:
        if not s["mfa"]:
            raise HTTPException(401, "The second factor is still needed.")
        if request.method != "GET" and request.headers.get("x-fleet-console") != "1":
            raise HTTPException(403, "This request did not come from the console.")
        return {"org_id": s["org_id"], "role": s["role"], "actor": f"user:{s['email']}", "user_id": s["user_id"],
                "email": s["email"], "name": s["name"], "session_id": s["session_id"]}
    if authorization and authorization.lower().startswith("bearer ") and len(authorization) >= 20:
        with db.anon() as c:
            row = c.execute("SELECT * FROM auth_admin(%s)", (db.digest(authorization[7:].strip()),)).fetchone()
        if row:         # an organisation key: for scripts that read. It can change nothing.
            return {"org_id": row["org_id"], "role": "auditor", "actor": f"key:{row['key_id']}", "user_id": None,
                    "email": None, "name": "", "session_id": None}
    raise HTTPException(401, "Sign in first.")


def need(role: str):
    def allowed(who: dict = Depends(principal)) -> dict:
        if auth.rank(who["role"]) < auth.rank(role):
            raise HTTPException(403, f"This needs the {role} role." if who["user_id"] else "An organisation key can only read.")
        return who
    return allowed


reader, editor, owner = need("auditor"), need("admin"), need("owner")


def _cookie(resp, request: Request, token: str | None, seconds: int = 0) -> None:
    if token is None:
        resp.delete_cookie(auth.COOKIE, path="/")
    else:       # Secure whenever the console is reached over https (always, outside a developer PC)
        resp.set_cookie(auth.COOKIE, token, max_age=seconds, httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/")


def _stage(s: dict) -> str:
    return "ok" if s["mfa"] else "mfa" if s["totp_confirmed"] else "mfa_setup"


def _count_failure(c, user_id) -> bool:
    """One more wrong password or code. True when that locked the account."""
    r = c.execute("UPDATE users SET failed = failed + 1, locked_until = CASE WHEN failed + 1 >= %s THEN now() + make_interval(mins => %s) "
                  "ELSE locked_until END WHERE id = %s RETURNING failed", (auth.MAX_FAILED, auth.LOCK_MINUTES, user_id)).fetchone()
    return bool(r and r["failed"] == auth.MAX_FAILED)


# --------------------------------------------------------------------------- signing in
@router.post("/auth/login")
async def login(request: Request):
    body = await request.json()
    email, password = _text(body.get("email"), 250).lower(), str(body.get("password") or "")[:300]
    with db.anon() as c:
        u = c.execute("SELECT * FROM auth_login(%s)", (email,)).fetchone()
    good = auth.check_password(password, u["password_hash"] if u else None)      # the same work whether or not there is an account
    token = stage = None
    if u:
        with db.org(u["org_id"]) as c:
            locked = bool(u["locked_until"] and u["locked_until"] > datetime.now(timezone.utc))
            if good and not u["disabled"] and not locked:
                row = c.execute("UPDATE users SET failed = 0, locked_until = NULL WHERE id = %s RETURNING totp_confirmed", (u["user_id"],)).fetchone()
                token = auth.new_token("sfs_")
                c.execute("INSERT INTO sessions (org_id, user_id, token_hash, expires_at) VALUES (%s,%s,%s, now() + make_interval(mins => %s))",
                          (u["org_id"], u["user_id"], db.digest(token), auth.PENDING_MINUTES))
                stage = "mfa" if row["totp_confirmed"] else "mfa_setup"
            elif not good and not locked and _count_failure(c, u["user_id"]):
                record(c, u["org_id"], f"user:{email}", "signin.locked", {"minutes": auth.LOCK_MINUTES})
    if not token:
        raise HTTPException(401, REFUSED)
    resp = JSONResponse({"stage": stage})
    _cookie(resp, request, token, auth.PENDING_MINUTES * 60)
    return resp


def _waiting(request: Request) -> dict:
    """The session of someone who gave the right password and still owes the second factor."""
    s = session_of(request)
    if not s:
        raise HTTPException(401, "Sign in first.")
    if s["mfa"]:
        raise HTTPException(400, "You are already signed in.")
    return s


def _open(c, s: dict, request: Request, extra: dict | None = None):
    """The second factor was given: the session opens."""
    c.execute("UPDATE sessions SET mfa = true, expires_at = now() + make_interval(hours => %s) WHERE id = %s", (auth.SESSION_HOURS, s["session_id"]))
    c.execute("UPDATE users SET failed = 0, locked_until = NULL, last_login = now() WHERE id = %s", (s["user_id"],))
    record(c, s["org_id"], f"user:{s['email']}", "signin", {})
    resp = JSONResponse({"stage": "ok", **(extra or {})})
    _cookie(resp, request, request.cookies.get(auth.COOKIE), auth.SESSION_HOURS * 3600)
    return resp


@router.get("/auth/mfa/setup")
def mfa_setup_start(request: Request):
    """The secret for the authenticator app, as text and as a picture to scan. Shown until a code confirms it."""
    s = _waiting(request)
    if s["totp_confirmed"]:
        raise HTTPException(400, "A second factor is already set up.")
    with db.org(s["org_id"]) as c:
        sealed = c.execute("SELECT totp_secret FROM users WHERE id = %s", (s["user_id"],)).fetchone()["totp_secret"]
        secret = auth.unseal(sealed)
        if not secret:
            secret = auth.new_totp_secret()
            c.execute("UPDATE users SET totp_secret = %s WHERE id = %s", (auth.seal(secret), s["user_id"]))
    uri = auth.totp_uri(secret, s["email"])
    return {"secret": secret, "uri": uri, "qr": auth.qr_data_uri(uri), "email": s["email"]}


@router.post("/auth/mfa/setup")
async def mfa_setup_finish(request: Request):
    s = _waiting(request)
    code = _text((await request.json()).get("code"), 20)
    if s["totp_confirmed"]:
        raise HTTPException(400, "A second factor is already set up.")
    resp = None
    with db.org(s["org_id"]) as c:
        u = c.execute("SELECT totp_secret FROM users WHERE id = %s FOR UPDATE", (s["user_id"],)).fetchone()
        secret = auth.unseal(u["totp_secret"])
        step = auth.totp_step(code, secret) if secret else None
        if step:
            codes = auth.new_recovery_codes()
            c.execute("UPDATE users SET totp_confirmed = true, totp_last_step = %s WHERE id = %s", (step, s["user_id"]))
            c.execute("DELETE FROM recovery_codes WHERE user_id = %s", (s["user_id"],))
            for x in codes:
                c.execute("INSERT INTO recovery_codes (org_id, user_id, code_hash) VALUES (%s,%s,%s)", (s["org_id"], s["user_id"], db.digest(auth.tidy_recovery(x))))
            record(c, s["org_id"], f"user:{s['email']}", "mfa.set_up", {})
            resp = _open(c, s, request, {"recovery_codes": codes})
    if not resp:
        raise HTTPException(400, WRONG_CODE)
    return resp


@router.post("/auth/mfa")
async def mfa(request: Request):
    """A code from the authenticator app, or one of the recovery codes (each works once)."""
    s = _waiting(request)
    code = _text((await request.json()).get("code"), 40)
    if not s["totp_confirmed"]:
        raise HTTPException(400, "Set up the second factor first.")
    resp = None
    with db.org(s["org_id"]) as c:
        u = c.execute("SELECT totp_secret, totp_last_step, locked_until FROM users WHERE id = %s FOR UPDATE", (s["user_id"],)).fetchone()
        locked = bool(u["locked_until"] and u["locked_until"] > datetime.now(timezone.utc))
        secret = auth.unseal(u["totp_secret"])
        step = auth.totp_step(code, secret, u["totp_last_step"]) if secret and not locked else None
        spare = auth.tidy_recovery(code)
        if step:
            c.execute("UPDATE users SET totp_last_step = %s WHERE id = %s", (step, s["user_id"]))
            resp = _open(c, s, request)
        elif not locked and len(spare) == 12 and c.execute(
                "UPDATE recovery_codes SET used_at = now() WHERE user_id = %s AND code_hash = %s AND used_at IS NULL RETURNING 1",
                (s["user_id"], db.digest(spare))).fetchone():
            left = c.execute("SELECT count(*) AS n FROM recovery_codes WHERE user_id = %s AND used_at IS NULL", (s["user_id"],)).fetchone()["n"]
            record(c, s["org_id"], f"user:{s['email']}", "mfa.recovery_code_used", {"left": left})
            resp = _open(c, s, request, {"recovery_left": left})
        elif not locked and _count_failure(c, s["user_id"]):
            record(c, s["org_id"], f"user:{s['email']}", "signin.locked", {"minutes": auth.LOCK_MINUTES})
    if not resp:
        raise HTTPException(401, WRONG_CODE)
    return resp


@router.get("/auth/me")
def me(request: Request):
    s = session_of(request)
    if not s:
        raise HTTPException(401, "Sign in first.")
    if not s["mfa"]:
        return {"stage": _stage(s), "email": s["email"]}
    with db.org(s["org_id"]) as c:
        org = c.execute("SELECT name FROM organisations").fetchone()
    return {"stage": "ok", "email": s["email"], "name": s["name"], "role": s["role"], "organisation": org["name"] if org else ""}


@router.post("/auth/logout")
def logout(request: Request):
    s = session_of(request)
    if s:
        with db.org(s["org_id"]) as c:
            c.execute("DELETE FROM sessions WHERE id = %s", (s["session_id"],))
    resp = JSONResponse({"ok": True})
    _cookie(resp, request, None)
    return resp


# --------------------------------------------------------------------------- setting a password
def _link(token: str) -> dict:
    with db.anon() as c:
        row = c.execute("SELECT * FROM auth_setup(%s)", (db.digest(token),)).fetchone() if token else None
    if not row:
        raise HTTPException(404, "This link is not valid any more. Ask an owner of your organisation for a new one.")
    return row


@router.post("/auth/setup/check")
async def setup_check(request: Request):
    """Whose link this is, so the page can say so before a password is typed."""
    return {"email": _link(_text((await request.json()).get("token"), 200))["email"], "min_password": auth.MIN_PASSWORD}


@router.post("/auth/setup")
async def setup(request: Request):
    """Set your own password with a one-time link (a new account, or a forgotten password)."""
    body = await request.json()
    link = _link(_text(body.get("token"), 200))
    password = str(body.get("password") or "")
    problem = auth.password_problem(password, link["email"])
    if problem:
        raise HTTPException(400, problem)
    with db.org(link["org_id"]) as c:
        c.execute("UPDATE users SET password_hash = %s, failed = 0, locked_until = NULL WHERE id = %s", (auth.hash_password(password), link["user_id"]))
        c.execute("UPDATE setup_links SET used_at = now() WHERE user_id = %s AND used_at IS NULL", (link["user_id"],))      # this link and any older one
        c.execute("DELETE FROM sessions WHERE user_id = %s", (link["user_id"],))
        record(c, link["org_id"], f"user:{link['email']}", "password.set", {})
    return {"ok": True, "email": link["email"]}


@router.post("/auth/password")
async def change_password(request: Request, who: dict = Depends(reader)):
    if not who["user_id"]:
        raise HTTPException(403, "An organisation key has no password.")
    body = await request.json()
    new = str(body.get("new") or "")
    with db.org(who["org_id"]) as c:
        stored = c.execute("SELECT password_hash FROM users WHERE id = %s", (who["user_id"],)).fetchone()["password_hash"]
    if not auth.check_password(str(body.get("current") or "")[:300], stored):
        raise HTTPException(400, "The current password is not right.")
    problem = auth.password_problem(new, who["email"])
    if problem:
        raise HTTPException(400, problem)
    with db.org(who["org_id"]) as c:
        c.execute("UPDATE users SET password_hash = %s WHERE id = %s", (auth.hash_password(new), who["user_id"]))
        c.execute("DELETE FROM sessions WHERE user_id = %s AND id <> %s", (who["user_id"], who["session_id"]))      # other browsers are signed out
        record(c, who["org_id"], who["actor"], "password.changed", {})
    return {"ok": True}


def _new_setup_link(c, org_id, user_id) -> str:
    token = auth.new_token("sfu_")
    c.execute("UPDATE setup_links SET used_at = now() WHERE user_id = %s AND used_at IS NULL", (user_id,))
    c.execute("INSERT INTO setup_links (org_id, user_id, token_hash, expires_at) VALUES (%s,%s,%s, now() + make_interval(days => %s))",
              (org_id, user_id, db.digest(token), auth.SETUP_DAYS))
    return token


# --------------------------------------------------------------------------- people, links, tokens
@router.get("/access")
def access(who: dict = Depends(reader)):
    """Who has access, and through what. An auditor sees only their own entry."""
    manage = auth.rank(who["role"]) >= auth.rank("admin")
    with db.org(who["org_id"]) as c:
        users = c.execute("SELECT id, email, name, role, disabled, totp_confirmed, password_hash IS NOT NULL AS has_password, created_at, last_login, "
                          "locked_until > now() AS locked FROM users ORDER BY lower(email)").fetchall() if manage else []
        links = c.execute("SELECT id, label, created_by, created_at, expires_at, revoked_at, opened, last_opened FROM share_links "
                          "ORDER BY created_at DESC LIMIT 100").fetchall() if manage else []
        tokens = c.execute("SELECT id, label, max_uses, uses, expires_at, created_at FROM enrolment_tokens "
                           "WHERE expires_at > now() AND uses < max_uses ORDER BY created_at DESC").fetchall() if manage else []
        keys = c.execute("SELECT count(*) AS n FROM admin_keys").fetchone()["n"] if manage else 0
    now = datetime.now(timezone.utc)
    return {"me": {"email": who["email"], "name": who["name"], "role": who["role"], "id": str(who["user_id"]) if who["user_id"] else None},
            "users": [{"id": str(u["id"]), "email": u["email"], "name": u["name"], "role": u["role"], "disabled": u["disabled"],
                       "second_factor": u["totp_confirmed"], "has_password": u["has_password"], "locked": bool(u["locked"]),
                       "created_at": _iso(u["created_at"]), "last_login": _iso(u["last_login"])} for u in users],
            "share_links": [{"id": str(x["id"]), "label": x["label"], "created_by": x["created_by"], "created_at": _iso(x["created_at"]),
                             "expires_at": _iso(x["expires_at"]), "opened": x["opened"], "last_opened": _iso(x["last_opened"]),
                             "state": "withdrawn" if x["revoked_at"] else "expired" if x["expires_at"] <= now else "active"} for x in links],
            "enrolment_tokens": [{"id": str(t["id"]), "label": t["label"], "uses_left": t["max_uses"] - t["uses"], "expires_at": _iso(t["expires_at"])} for t in tokens],
            "organisation_keys": keys, "roles": list(auth.ROLES), "setup_days": auth.SETUP_DAYS, "session_hours": auth.SESSION_HOURS}


@router.post("/users")
async def add_user(request: Request, who: dict = Depends(owner)):
    """Add a person. They get a one-time link to set their own password; nobody else ever knows it."""
    body = await request.json()
    email, name, role = _text(body.get("email"), 250).lower(), _text(body.get("name"), 100), body.get("role")
    if not EMAIL.fullmatch(email) or role not in auth.ROLES:
        raise HTTPException(400, "An email address and a role (owner, admin or auditor) are needed.")
    token = None
    try:
        with db.org(who["org_id"]) as c:
            uid = c.execute("INSERT INTO users (org_id, email, name, role) VALUES (%s,%s,%s,%s) RETURNING id", (who["org_id"], email, name, role)).fetchone()["id"]
            token = _new_setup_link(c, who["org_id"], uid)
            record(c, who["org_id"], who["actor"], "user.added", {"email": email, "role": role})
    except errors.UniqueViolation:
        raise HTTPException(400, "That address cannot be used: it already has an account on this server.") from None
    return {"ok": True, "id": str(uid), "setup_token": token, "valid_days": auth.SETUP_DAYS}


@router.post("/users/{user_id}")
async def change_user(user_id: str, request: Request, who: dict = Depends(owner)):
    """action: role (with `role`) | disable | enable | reset_password | reset_second_factor."""
    body = await request.json()
    action, role = body.get("action"), body.get("role")
    if action not in ("role", "disable", "enable", "reset_password", "reset_second_factor") or (action == "role" and role not in auth.ROLES):
        raise HTTPException(400, "That is not something that can be done to an account.")
    problem, token, user_id = None, None, _id(user_id, "No such person.")
    with db.org(who["org_id"]) as c:
        u = c.execute("SELECT id, email, role, disabled FROM users WHERE id = %s FOR UPDATE", (user_id,)).fetchone()
        if not u:
            problem = (404, "No such person.")            # also the answer for a person in another organisation
        elif action in ("role", "disable") and str(u["id"]) == str(who["user_id"]):
            problem = (400, "You cannot change your own role or switch yourself off. Another owner can.")
        else:
            others = c.execute("SELECT count(*) AS n FROM users WHERE role = 'owner' AND NOT disabled AND id <> %s", (u["id"],)).fetchone()["n"]
            if u["role"] == "owner" and others == 0 and (action == "disable" or (action == "role" and role != "owner")):
                problem = (400, "This is the only owner. Make someone else an owner first.")
    if problem:
        raise HTTPException(*problem)
    with db.org(who["org_id"]) as c:
        if action == "role":
            c.execute("UPDATE users SET role = %s WHERE id = %s", (role, u["id"]))
        elif action in ("disable", "enable"):
            c.execute("UPDATE users SET disabled = %s, failed = 0, locked_until = NULL WHERE id = %s", (action == "disable", u["id"]))
        elif action == "reset_password":
            token = _new_setup_link(c, who["org_id"], u["id"])
        else:
            c.execute("UPDATE users SET totp_secret = NULL, totp_confirmed = false, totp_last_step = 0 WHERE id = %s", (u["id"],))
            c.execute("DELETE FROM recovery_codes WHERE user_id = %s", (u["id"],))
        if action != "enable" and str(u["id"]) != str(who["user_id"]):
            c.execute("DELETE FROM sessions WHERE user_id = %s", (u["id"],))        # whatever changed, they sign in again
        record(c, who["org_id"], who["actor"], "user." + action, {"email": u["email"], **({"role": role} if action == "role" else {})})
    return {"ok": True, **({"setup_token": token, "valid_days": auth.SETUP_DAYS} if token else {})}


@router.post("/share-links")
async def add_share_link(request: Request, who: dict = Depends(editor)):
    """A link that shows the organisation's evidence, read-only, until it expires. The link is shown once."""
    body = await request.json()
    label, days = _text(body.get("label"), 100), _int(body.get("days"), 1, 90, 14)
    if not label:
        raise HTTPException(400, "Say who the link is for.")
    token = auth.new_token("sfl_")
    with db.org(who["org_id"]) as c:
        c.execute("INSERT INTO share_links (org_id, token_hash, label, created_by, expires_at) VALUES (%s,%s,%s,%s, now() + make_interval(days => %s))",
                  (who["org_id"], db.digest(token), label, who["actor"], days))
        record(c, who["org_id"], who["actor"], "share_link.created", {"label": label, "days": days})
    return {"ok": True, "share_token": token, "days": days}


@router.post("/share-links/{link_id}/revoke")
def revoke_share_link(link_id: str, who: dict = Depends(editor)):
    with db.org(who["org_id"]) as c:
        row = c.execute("UPDATE share_links SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL RETURNING label", (_id(link_id),)).fetchone()
        if row:
            record(c, who["org_id"], who["actor"], "share_link.withdrawn", {"label": row["label"]})
    if not row:
        raise HTTPException(404, "No such link, or it was already withdrawn.")
    return {"ok": True}


@router.post("/tokens")
async def add_enrolment_token(request: Request, who: dict = Depends(editor)):
    """A token with which PCs join this organisation. Shown once."""
    body = await request.json()
    label, uses, days = _text(body.get("label"), 100), _int(body.get("uses"), 1, 500, 1), _int(body.get("days"), 1, 30, 7)
    token = "sfe_" + auth.new_token("")[:32]
    with db.org(who["org_id"]) as c:
        c.execute("INSERT INTO enrolment_tokens (org_id, token_hash, label, max_uses, expires_at) VALUES (%s,%s,%s,%s, now() + make_interval(days => %s))",
                  (who["org_id"], db.digest(token), label, uses, days))
        record(c, who["org_id"], who["actor"], "enrolment_token.created", {"label": label, "uses": uses, "days": days})
    return {"ok": True, "enrolment_token": token, "uses": uses, "days": days}


@router.post("/devices/{device_id}/remove")
def remove_device(device_id: str, who: dict = Depends(editor)):
    """Forget a device and everything it reported. Its key stops working; the PC itself is not touched."""
    with db.org(who["org_id"]) as c:
        row = c.execute("DELETE FROM devices WHERE id = %s RETURNING name", (_id(device_id, "No such device."),)).fetchone()
        if row:
            record(c, who["org_id"], who["actor"], "device.removed", {"device": device_id, "name": row["name"]})
    if not row:
        raise HTTPException(404, "No such device.")
    return {"ok": True}


def add_first_user(c, org_id, email: str, role: str = "owner", name: str = "") -> str:
    """For `manage user`, as the database owner: a person and their set-your-password link."""
    email = email.strip().lower()
    if not EMAIL.fullmatch(email) or role not in auth.ROLES:
        raise ValueError("An email address and a role (owner, admin or auditor) are needed.")
    row = c.execute("INSERT INTO users (org_id, email, name, role) VALUES (%s,%s,%s,%s) ON CONFLICT (lower(email)) DO UPDATE SET email = EXCLUDED.email "
                    "WHERE users.org_id = EXCLUDED.org_id RETURNING id", (org_id, email, name, role)).fetchone()
    if not row:
        raise ValueError("That address already has an account in another organisation.")
    token = auth.new_token("sfu_")
    c.execute("UPDATE setup_links SET used_at = now() WHERE user_id = %s AND used_at IS NULL", (row[0],))
    c.execute("INSERT INTO setup_links (org_id, user_id, token_hash, expires_at) VALUES (%s,%s,%s, now() + make_interval(days => %s))",
              (org_id, row[0], db.digest(token), auth.SETUP_DAYS))
    c.execute("INSERT INTO audit_log (org_id, actor, action, detail) VALUES (%s,'server:manage','user.added',%s)", (org_id, Jsonb({"email": email, "role": role})))
    return token
