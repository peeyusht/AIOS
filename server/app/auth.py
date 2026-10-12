"""
People signing in to the console (phase 3): passwords, the second factor, sessions.

  password        scrypt (hashlib), a fresh salt each time; only the hash is stored.
  second factor   time-based one-time codes (RFC 6238, what every authenticator app speaks). Required for
                  everyone: a session that has not given a code opens nothing. A code is good once.
                  The secret has to be readable to check a code, so it is stored encrypted with
                  FLEET_SECRET_KEY, which the database never sees: a copy of the database alone does not
                  give anyone a second factor.
  recovery codes  eight, shown once when the second factor is set up, each good once; stored as hashes.
  session         a random value in an HttpOnly, SameSite=Strict cookie; only its hash is stored. It ends
                  after IDLE_SECONDS without a request and after SESSION_HOURS at the latest.

Nothing here talks to the database; app/main.py does that.
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

COOKIE = "sf_session"
SESSION_HOURS = 12
IDLE_SECONDS = 2 * 3600
PENDING_MINUTES = 10            # how long a session may wait for its second factor
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 12
SETUP_DAYS = 7
ROLES = ("auditor", "admin", "owner")           # each can do what the ones before it can
ISSUER = "Shadow Filer fleet"
_N, _R, _P = 2 ** 16, 8, 1                      # 64 MB per check: slow for someone guessing, fine for one sign-in


# --------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, maxmem=2 ** 28, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def check_password(password: str, stored: str | None) -> bool:
    """Always does the work, also for an account that does not exist or has no password yet, so that the
    time an answer takes does not say which addresses have accounts."""
    try:
        _, n, r, p, salt, want = (stored or DUMMY).split("$")
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), maxmem=2 ** 28, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(want)) and bool(stored)
    except (ValueError, TypeError):
        return False


DUMMY = hash_password(secrets.token_urlsafe(16))


def password_problem(password: str, email: str = "") -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"The password needs at least {MIN_PASSWORD} characters. A few unrelated words work well."
    if len(password) > 200:
        return "The password is too long."
    if email and password.lower() in (email.lower(), email.lower().split("@")[0]):
        return "The password must not be your email address."
    if len(set(password)) < 5:
        return "The password repeats the same few characters."
    return None


# --------------------------------------------------------------------------- the second factor
def _box() -> Fernet:
    key = os.environ.get("FLEET_SECRET_KEY") or ""
    if not key:
        raise RuntimeError("FLEET_SECRET_KEY is not set: the server cannot keep second-factor secrets.")
    return Fernet(key.encode("ascii"))


def seal(secret: str) -> str:
    return _box().encrypt(secret.encode("ascii")).decode("ascii")


def unseal(sealed: str | None) -> str | None:
    try:
        return _box().decrypt((sealed or "").encode("ascii")).decode("ascii") if sealed else None
    except (InvalidToken, ValueError):
        return None


def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii")


def totp_at(secret: str, step: int) -> str:
    mac = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    at = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[at:at + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def totp_step(code: str, secret: str, last_step: int = 0, now: float | None = None) -> int | None:
    """The time step a code belongs to (this half minute, the one before or the one after), or None when it is
    wrong or was already used. The caller stores the step so the same code cannot be used twice."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != 6:
        return None
    current = int((now or time.time()) // 30)
    for step in (current, current - 1, current + 1):
        if step > last_step and hmac.compare_digest(totp_at(secret, step), code):
            return step
    return None


def totp_uri(secret: str, email: str) -> str:
    return f"otpauth://totp/{quote(ISSUER)}:{quote(email)}?secret={secret}&issuer={quote(ISSUER)}&algorithm=SHA1&digits=6&period=30"


def qr_data_uri(text: str) -> str:
    """The setup address as a picture an authenticator app can scan, drawn here: nothing is fetched."""
    import segno
    return segno.make(text, error="m").svg_data_uri(scale=5, border=2)


def new_recovery_codes(n: int = 8) -> list:
    return ["-".join(secrets.token_hex(2) for _ in range(3)) for _ in range(n)]         # like 3f9a-0c21-b7e4


def tidy_recovery(code: str) -> str:
    return "".join(ch for ch in (code or "").lower() if ch in "0123456789abcdef")


def new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def rank(role: str) -> int:
    return ROLES.index(role) if role in ROLES else -1
