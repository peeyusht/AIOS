"""
Fleet: report this PC to a central server (docs/architecture.md, phase 1). THE ONLY CODE THAT SENDS ANYTHING
ABOUT THIS PC OFF IT. Off until the PC is enrolled by hand (`shadow_agent.py fleet enrol <server> <token>`);
`fleet leave` forgets the key and stops it. Enrolling replaces "nothing leaves this PC" with the list below.

`payload()` builds exactly what is sent, and `shadow_agent.py fleet show` prints it before anything is sent.

SENT, per kind:
  device     the PC's name, make, model, serial number, Windows version and build
  apps       installed programs: name, version, publisher, kind, install date, size, newer version available
  services   services that are not part of Windows: name, state, start mode, account type, product, version,
             port numbers, the application it belongs to
  network    firewall state per profile, the network's Public/Private mark, listening ports (number, program
             name, reachable from the network or not), counts of rules, left-over rules and shared folders,
             and for each interface only its kind and whether it is connected
  posture    security settings as true/false, dates or counts: antivirus, drive encryption, lock, AutoPlay,
             Windows update date, how many administrator accounts, whether the everyday account is one

NEVER SENT, and `payload()` is built so they cannot slip in (it copies named fields, never whole records):
  anything about files or documents (the whole file-organising half); account names; install folders and
  program paths (they contain the user name); IP and MAC addresses; the addresses of open connections; the
  list of neighbouring devices; the routing table; DNS servers and the hosts file; share names; the text of
  the update log.

Transport: HTTPS only; a plain http:// server is refused unless it is localhost (development).

Identity: when it enrols, the PC makes a key pair of its own (Ed25519). The server gets the public half; the
private half never leaves this PC and is kept in the agent's database, sealed by Windows for the account the
agent runs as (DPAPI). Every request is signed (see `signer`), so the server holds nothing with which
somebody could pose as this PC. `status()` never returns the key and it is never logged.

Used by two programs: this file-organising agent, and the device agent that is installed on a customer's PC
as a Windows service (device-agent/), which passes its own settings and its own reading of the PC to
`payload()`.
"""
import base64
import hashlib
import json
import os
import socket
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import urlparse

AGENT_VERSION = "0.2"       # the device agent sets its own (device-agent/agent.py)
CHECK_MINUTES = 15
TIMEOUT = 30


# --------------------------------------------------------------------------- what is sent
def _pick(d: dict, *names) -> dict:
    """Named fields only: a record is never passed on whole."""
    return {n: d.get(n) for n in names}


DISCOVERY = {1900, 3702, 5353, 5355}      # SSDP, WS-Discovery, mDNS, LLMNR: "who is out there" chatter, not a service


def _steady(e: dict) -> bool:
    """A listening port worth reporting: reachable from the network, and not one of the short-lived ports
    (49152 and up) that Windows and programs open and close by the minute for their own outgoing traffic."""
    if e["proto"] == "UDP" and e["port"] in DISCOVERY:      # every browser and Windows itself open and close these
        return False
    return e["reach"] == "network" and not (e["port"] >= 49152 and (e["proto"] == "UDP" or e["windows"]))


def payload(cfg: dict, settings: dict | None = None, posture=None) -> dict:
    """Exactly what a check-in sends. Reads what the other modules already hold; asks Windows only for the
    settings read the Compliance page also makes. The device agent has no Library settings and reads the PC's
    settings its own way, so it passes both in; what is picked out of them is the same either way."""
    import apps
    import compliance
    import network
    import services
    if settings is None:
        import library
        settings = library.settings(cfg)
    s = settings
    snaps = {}
    raw = posture() if posture else compliance._posture()
    if raw:
        snaps["device"] = {"name": raw.get("computer") or "", "manufacturer": raw.get("manufacturer") or "", "model": raw.get("model") or "",
                           "serial": compliance.serial(raw.get("serial")), "windows": compliance.windows_name(raw),
                           "build": f"{raw.get('build') or 0}.{raw.get('ubr') or 0}"}
        users = [u for u in raw.get("users") or [] if isinstance(u, dict)]
        drives = [d for d in raw.get("drives") or [] if isinstance(d, dict)]
        av = [a for a in raw.get("antivirus") or [] if isinstance(a, dict)]
        d = raw.get("defender") or {}
        lock = compliance.configuration_checks(raw)[0]["status"] == "pass"
        snaps["posture"] = {
            "antivirus_on": any((int(a.get("state") or 0) >> 12) & 0xF == 1 for a in av) if av else None,
            "antivirus_products": len(av), "realtime_protection": d.get("realtime") if d.get("present") else None,
            "signature_age_days": d.get("signature_age") if d.get("present") else None,
            "drives": len(drives), "drives_encrypted": all(x.get("protection") in (1, 3, 5) for x in drives) if drives else None,
            "lock_found": lock, "autoplay_off": raw.get("autoplay_off") == 1 or (raw.get("autorun_policy") or 0) >= 0x91,
            "guest_enabled": any(u.get("enabled") and str(u.get("sid") or "").endswith("-501") for u in users),
            "accounts_enabled": sum(1 for u in users if u.get("enabled")),
            "accounts_without_password": sum(1 for u in users if u.get("enabled") and not u.get("password_required")),
            "admin_accounts": len(raw.get("admins") or []) if raw.get("admins_read") else None,
            "daily_account_is_admin": bool(raw.get("me_admin")),
            "windows_last_update": raw.get("last_update") or None, "windows_updates_off": raw.get("no_auto_update") == 1,
            "windows_updates_paused": bool(raw.get("paused_until")),
            "browser_updates_off": [k for k, v in (raw.get("browser_policy") or {}).items()
                                    if (k.endswith("_default") or k.endswith("_period")) and v == "0" or k == "firefox_off" and v == "1"]}
    if s["enabled"] and s["applications"]:
        v = apps.with_updates(cfg, apps.view(cfg), s["check_updates"], s["update_hours"])
        if v.get("scanned_at"):
            # no timestamps inside a kind: the server keeps a kind only when its content changed
            snaps["apps"] = {"apps": [
                {**_pick(a, "name", "version", "publisher", "kind", "from_store", "scope", "arch", "installed", "date_is", "size", "available"),
                 "update_to": (a.get("update") or {}).get("to") if not (a.get("update") or {}).get("blocked") else None}
                for a in v["apps"]]}
            raw_s = services.read_services()
            if raw_s is not None:
                snaps["services"] = {"services": [
                    {**_pick(x, "name", "service", "running", "start", "account", "product", "version", "publisher", "exposed", "app_name"),
                     "ports": [_pick(p, "port", "network") for p in x.get("ports") or []]}
                    for x in services.tidy(raw_s, v["apps"])]}
    n = network.peek() or network.view()
    if n and n.get("read_at"):
        ru = n.get("rules") or {}
        snaps["network"] = {
            "firewall": [_pick(f, "name", "enabled", "inbound", "outbound") for f in n["firewall"]],
            "other_firewalls": list(n.get("other_firewalls") or []),
            "interfaces": [_pick(a, "kind", "up", "internet", "category") for a in n["adapters"]],
            # ports other devices can reach; the ones only this PC can reach come and go and say little
            "listening": sorted((_pick(e, "proto", "port", "process", "reach", "windows") for e in n["listening"] if _steady(e)),
                                key=lambda e: (e["proto"], e["port"], e["process"])),
            "shared_folders": sum(1 for x in n["shares"] if not x["builtin"] and not x["printer"]),
            "rules": {"total": ru.get("total"), "windows": ru.get("windows"), "programs": len(ru.get("programs") or []),
                      "left_over": ru.get("missing"), "any_program_any_port": len(ru.get("wide_open") or [])} if ru else None}
    return {"agent_version": AGENT_VERSION, "sent_at": datetime.now().isoformat(timespec="seconds"), "snapshots": snaps}


# --------------------------------------------------------------------------- state
def _conn(db_path):
    c = sqlite3.connect(str(db_path), timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS fleet_state (k TEXT PRIMARY KEY, v TEXT)")
    return c


def state(cfg: dict) -> dict:
    c = _conn(cfg["database"])
    try:
        return {k: v for k, v in c.execute("SELECT k, v FROM fleet_state")}
    finally:
        c.close()


def _save(cfg: dict, **values) -> None:
    c = _conn(cfg["database"])
    try:
        for k, v in values.items():
            if v is None:
                c.execute("DELETE FROM fleet_state WHERE k=?", (k,))
            else:
                c.execute("INSERT OR REPLACE INTO fleet_state VALUES (?,?)", (k, str(v)))
        c.commit()
    finally:
        c.close()


def status(cfg: dict) -> dict:
    """What the console may show: never the key itself."""
    s = state(cfg)
    out = {"enrolled": bool(s.get("device_private")), "server": s.get("server"), "device_id": s.get("device_id"),
           "enrolled_at": s.get("enrolled_at"), "last_ok": s.get("last_ok"), "last_error": s.get("last_error") or None,
           "last_stored": s.get("last_stored")}
    if s.get("device_key") and not out["enrolled"]:
        out["last_error"] = "This PC was enrolled with an older agent. Run 'fleet leave', then enrol it again with a new token."
    return out


# --------------------------------------------------------------------------- the PC's own key
def _seal(data: bytes, seal: bool) -> bytes:
    """Windows keeps the key readable only for the account the agent runs as (DPAPI). Elsewhere: as it is."""
    if os.name != "nt":
        return data
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("n", wintypes.DWORD), ("p", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    fn = crypt.CryptProtectData if seal else crypt.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out)):       # 0x1: never show a prompt
        raise RuntimeError("Windows could not open this PC's fleet key (it belongs to another Windows account). Run 'fleet leave' and enrol again.")
    try:
        return ctypes.string_at(out.p, out.n)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(ctypes.cast(out.p, ctypes.c_void_p))


def new_key() -> tuple:
    """(private half as 32 bytes, public half as text) of a new key pair."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, base64.b64encode(public).decode("ascii")


def signer(private: bytes, device_id: str | None = None):
    """Makes the three headers that prove a request comes from this PC: who, when, and a signature over the
    method, the path, the time and the body's hash. The time only goes up, so the server can refuse a request
    it has seen before."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key, last = Ed25519PrivateKey.from_private_bytes(private), [0]

    def headers(method: str, path: str, data: bytes) -> dict:
        last[0] = stamp = max(int(time.time() * 1000), last[0] + 1)
        text = f"SFv1\n{method.upper()}\n{path}\n{stamp}\n{hashlib.sha256(data).hexdigest()}".encode("utf-8")
        h = {"X-Stamp": str(stamp), "X-Signature": base64.b64encode(key.sign(text)).decode("ascii")}
        if device_id:
            h["X-Device"] = device_id
        return h
    return headers


def own_signer(cfg: dict):
    """The signer for this PC's stored key. None when the PC is not enrolled."""
    s = state(cfg)
    if not s.get("device_private"):
        return None
    return signer(_seal(base64.b64decode(s["device_private"]), False), s.get("device_id"))


# --------------------------------------------------------------------------- talking to the server
def check_server(server: str) -> str:
    """The server address, cleaned. HTTPS only, except localhost for development."""
    u = urlparse((server or "").strip().rstrip("/"))
    if u.scheme not in ("https", "http") or not u.hostname or u.username or u.query or u.fragment:
        raise ValueError("The server address must look like https://fleet.example.com")
    if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("The server address must start with https:// (plain http is only allowed for localhost).")
    return f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"


def call(server: str, path: str, body: dict | None = None, sign=None, limit: int = 0):
    """One request to the fleet server: POST with a body, GET without. `sign` is this PC's signer. With `limit`
    the answer is a file of at most that many bytes and comes back as bytes; otherwise it is JSON."""
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    method = "POST" if body is not None else "GET"
    req = urllib.request.Request(server + path, data=data if body is not None else None, method=method, headers={
        "Content-Type": "application/json", "User-Agent": f"ShadowFiler-agent/{AGENT_VERSION}",
        **(sign(method, path, data) if sign else {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if limit:
                got = r.read(limit + 1)
                if len(got) > limit:
                    raise RuntimeError("The server sent more than was announced.")
                return got
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail")
        except Exception:
            detail = None
        raise RuntimeError(detail or f"The server answered {e.code}.") from None
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"The server could not be reached ({getattr(e, 'reason', e)}).") from None


def enrol(cfg: dict, server: str, token: str, send=None, now: datetime | None = None) -> dict:
    """Join an organisation with a one-time token. From here on this PC reports to that server. The key pair
    is made here; the server is sent the public half and a signature that shows this PC holds the other."""
    if status(cfg)["enrolled"]:
        raise RuntimeError("This PC is already enrolled. Run 'fleet leave' first to enrol it somewhere else.")
    server = check_server(server)
    private, public = new_key()
    got = (send or call)(server, "/api/v1/enrol", {"token": (token or "").strip(), "name": socket.gethostname(),
                                         "agent_version": AGENT_VERSION, "public_key": public}, signer(private))
    if not isinstance(got, dict) or not got.get("device_id"):
        raise RuntimeError("The server did not answer with a device identity.")
    _save(cfg, server=server, device_id=got["device_id"], device_private=base64.b64encode(_seal(private, True)).decode("ascii"),
          device_key=None, last_error=None, last_ok=None, enrolled_at=(now or datetime.now()).isoformat(timespec="seconds"))
    return status(cfg)


def leave(cfg: dict) -> None:
    """Forget the server and the key. The server keeps what it was sent; ask its administrator to delete it."""
    _save(cfg, server=None, device_id=None, device_key=None, device_private=None, enrolled_at=None, last_ok=None,
          last_error=None, last_stored=None, last_tried=None, release=None)


def checkin(cfg: dict, send=None, build=payload, now: datetime | None = None, log=None) -> dict:
    """Send the current picture. Failures are remembered and tried again at the next round; nothing is queued."""
    s = state(cfg)
    if not s.get("device_private"):
        return {"ok": False, "message": status(cfg)["last_error"] or "This PC is not enrolled."}
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    try:
        body = build(cfg)
        got = (send or call)(s["server"], "/api/v1/checkin", body, own_signer(cfg))
        # the newest agent version the server offers; only the device agent acts on it (device-agent/selfupdate.py)
        _save(cfg, last_ok=stamp, last_error=None, last_tried=stamp, last_stored=",".join(got.get("stored") or []) or "nothing changed",
              release=str(got.get("agent_release") or "")[:20] or None)
        if log:      # kinds only: nothing that was sent is repeated in the log
            log.info("fleet check-in: sent %s; the server kept %s", ", ".join(sorted(body["snapshots"])), ", ".join(got.get("stored") or []) or "nothing new")
        return {"ok": True, "stored": got.get("stored") or [], "sent": sorted(body["snapshots"]), "release": got.get("agent_release")}
    except Exception as e:
        _save(cfg, last_error=str(e)[:300], last_tried=stamp)
        if log:
            log.warning("fleet check-in failed: %s", e)
        return {"ok": False, "message": str(e)[:300]}


def due(cfg: dict, now: datetime | None = None) -> bool:
    s = state(cfg)
    if not s.get("device_private"):
        return False
    try:
        return (now or datetime.now()) - datetime.fromisoformat(s.get("last_tried") or "") >= timedelta(minutes=CHECK_MINUTES)
    except ValueError:
        return True


def as_text(p: dict) -> str:
    """The payload in a form a person can read before agreeing to send it."""
    sn = p["snapshots"]
    lines = ["This is everything a check-in sends (the full data follows with --json):", ""]
    if "device" in sn:
        d = sn["device"]
        lines.append(f"device    {d['name']} | {d['manufacturer']} {d['model']} | serial {d['serial'] or '(none)'} | {d['windows']}, build {d['build']}")
    if "apps" in sn:
        lines.append(f"apps      {len(sn['apps']['apps'])} programs: name, version, publisher, install date, size, newer version")
    if "services" in sn:
        lines.append(f"services  {len(sn['services']['services'])} services: name, state, account type, product, version, port numbers")
    if "network" in sn:
        n = sn["network"]
        lines.append(f"network   firewall per profile, {len(n['listening'])} listening ports with the program name, "
                     f"{len(n['interfaces'])} interfaces (kind and connected only), counts of rules and shared folders")
    if "posture" in sn:
        lines.append(f"posture   {len(sn['posture'])} settings as true/false, dates or counts")
    lines += ["", "Not sent: files and documents, account names, folders and program paths, IP and MAC addresses,",
              "open connections, neighbouring devices, routes, DNS servers, the hosts file, share names."]
    return "\n".join(lines) + "\n"
