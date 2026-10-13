"""
Devices: how an agent proves who it is, and the agent releases it may fetch.

A device holds a key pair it made itself when it enrolled; the server has only the public half, so nothing
the server stores can be used to pose as a device. Every request from a device carries three headers:

    X-Device      the device id
    X-Stamp       the device's clock, milliseconds since 1970
    X-Signature   Ed25519 over  "SFv1\\n<METHOD>\\n<path>\\n<stamp>\\n<sha256 of the body, hex>"

The stamp must be within ten minutes of the server's clock and higher than the last one this device used,
so a request that was read off the wire cannot be sent again.

Releases: the server passes on what `manage release add` put in the database. It cannot make one: the
agent installs only what is signed with the release key, whose private half is never on a server
(device-agent/release.py). Handing out a release is the one thing here that changes a PC, and the agent
decides: it asks, it checks, it installs. There is still no way to send a device a command.
"""
import base64
import hashlib
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

import release as rel       # device-agent/release.py, copied into the image (see Dockerfile)

from . import db

SKEW_SECONDS = 600
router = APIRouter()
REFUSED = "This device is not known, or its signature is not right. Enrol the PC again if this goes on."


def signed_text(method: str, path: str, stamp: int, body: bytes) -> bytes:
    return f"SFv1\n{method.upper()}\n{path}\n{stamp}\n{hashlib.sha256(body).hexdigest()}".encode("utf-8")


def public_key(text) -> Ed25519PublicKey:
    """An Ed25519 public key from base64 of its 32 bytes. ValueError for anything else."""
    raw = base64.b64decode(str(text or ""), validate=True)
    if len(raw) != 32:
        raise ValueError("not a key")
    return Ed25519PublicKey.from_public_bytes(raw)


def check_signature(key_text: str, request: Request, body: bytes) -> int:
    """The request's stamp, if the holder of this key signed exactly this request just now. 401 otherwise."""
    try:
        stamp = int(request.headers.get("x-stamp") or "")
        sig = base64.b64decode(request.headers.get("x-signature") or "", validate=True)
        key = public_key(key_text)
    except ValueError:
        raise HTTPException(401, REFUSED) from None
    if abs(time.time() * 1000 - stamp) > SKEW_SECONDS * 1000:
        raise HTTPException(401, "This PC's clock and the server's differ by more than ten minutes. Set the PC's clock.")
    try:
        key.verify(sig, signed_text(request.method, request.url.path, stamp, body))
    except InvalidSignature:
        raise HTTPException(401, REFUSED) from None
    return stamp


async def device(request: Request) -> dict:
    """The device that signed this request: {device_id, org_id}."""
    try:
        dev = str(uuid.UUID(request.headers.get("x-device") or ""))
    except ValueError:
        raise HTTPException(401, "A device signature is required.") from None
    body = await request.body()
    with db.anon() as c:
        row = c.execute("SELECT * FROM auth_device(%s::uuid)", (dev,)).fetchone()
    if not row:
        raise HTTPException(401, REFUSED)
    stamp = check_signature(row["public_key"], request, body)
    with db.org(row["org_id"]) as c:      # each stamp once, and only forwards: the same request sent again is refused
        fresh = c.execute("UPDATE devices SET last_stamp = %s WHERE id = %s AND last_stamp < %s RETURNING id",
                          (stamp, row["device_id"], stamp)).fetchone()
    if not fresh:
        raise HTTPException(401, "This request was already used.")
    return {"device_id": row["device_id"], "org_id": row["org_id"]}


# --------------------------------------------------------------------------- releases of the agent
def latest_release(c) -> str | None:
    """The highest version on offer. Compared as numbers: '0.10.0' is newer than '0.9.0'."""
    versions = [r["version"] for r in c.execute("SELECT version FROM agent_releases WHERE NOT withdrawn")]
    versions = [v for v in versions if rel.version_tuple(v)]
    return max(versions, key=rel.version_tuple) if versions else None


@router.get("/api/v1/agent/release")
def agent_release(who: dict = Depends(device)):
    """The newest release's signed manifest. The agent checks the signature itself; the server's word is not enough."""
    with db.anon() as c:
        v = latest_release(c)
        row = c.execute("SELECT version, manifest, signature FROM agent_releases WHERE version = %s", (v,)).fetchone() if v else None
    return row or {"version": None}


@router.get("/api/v1/agent/package/{version}")
def agent_package(version: str, who: dict = Depends(device)):
    if not rel.version_tuple(version):
        raise HTTPException(404, "No such release.")
    with db.anon() as c:
        row = c.execute("SELECT package FROM agent_releases WHERE version = %s AND NOT withdrawn", (version,)).fetchone()
    if not row:
        raise HTTPException(404, "No such release.")
    return Response(bytes(row["package"]), media_type="application/octet-stream")
