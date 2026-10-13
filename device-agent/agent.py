"""
Shadow Filer device agent: what is installed on a customer's PC.

It reads the PC's programs, services, firewall and security settings and reports them to the organisation's
fleet server every 15 minutes, as a Windows service that needs nobody signed in. That is all it does:

  - it sends what `fleet.payload()` lists and nothing else (shadow-filer/fleet.py: SENT / NEVER SENT);
  - it changes nothing on the PC. The code that moves files, updates programs, stops services or switches the
    firewall (mover.py, remedy.py) is not in the installer, and nothing can send this agent a command;
  - it listens on no port: it only makes outgoing HTTPS requests to its own fleet server;
  - the one thing it installs is a newer version of itself, and only one signed with the release key
    (selfupdate.py).

It runs as the SYSTEM account, because a service that must see every person's programs and settings, drive
encryption and the local accounts cannot be less. Its folder in ProgramData (key, state, log) is closed to
everyone but SYSTEM and administrators.

    sfagent status                      enrolled? last report, last error, version
    sfagent enrol <server> <token>      join an organisation (the service does the enrolling within a minute)
    sfagent show [--json]               the last report, exactly as it was sent
    sfagent leave                       forget the server and this PC's key
    sfagent updates on|off              let the agent install newer signed versions of itself (on by default)

All but `version` need an administrator's prompt. For silent installs:
    msiexec /i ShadowFilerAgent-x.y.z.msi /qn SERVER=https://fleet.example.com TOKEN=sfe_...
"""
import argparse
import json
import logging
import logging.handlers
import os
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
if not (HERE / "fleet.py").exists():          # a development checkout: the shared modules live with the other agent
    sys.path.insert(0, str(HERE.parent / "shadow-filer"))

import apps  # noqa: E402
import compliance  # noqa: E402
import fleet  # noqa: E402
import network  # noqa: E402
import selfupdate  # noqa: E402

VERSION = "0.4.0"
SERVICE = "ShadowFilerAgent"
NAME = "ShadowFiler Agent"
REG_KEY = r"SOFTWARE\ShadowFiler Agent"
SCAN_MINUTES = 60
ENROL_TRIES, ENROL_WAIT_MINUTES = 12, 5
# what the full agent takes from its Library settings. winget does not run for the SYSTEM account, so this
# agent does not ask which programs have a newer version (the server says so on its pages).
SETTINGS = {"enabled": True, "applications": True, "check_updates": False, "update_hours": 24}
TRUSTED_OWNERS = {"S-1-5-18", "S-1-5-32-544"}        # SYSTEM, Administrators
USER_VALUES = ("DisplayName", "DisplayVersion", "Publisher", "InstallDate", "EstimatedSize", "InstallLocation",
               "SystemComponent", "ParentKeyName", "ReleaseType")

fleet.AGENT_VERSION = VERSION


def data_dir() -> Path:
    return Path(os.environ.get("ProgramData") or r"C:\ProgramData") / NAME


def config(folder: Path) -> dict:
    return {"database": str(folder / "agent.db"), "library": dict(SETTINGS)}


# --------------------------------------------------------------------------- the agent's own folder
def owner_of(path: Path) -> str | None:
    """The SID that owns a file or folder."""
    import ctypes
    from ctypes import wintypes
    adv, k32 = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD] + [ctypes.c_void_p] * 5
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    sid, descriptor, text = ctypes.c_void_p(), ctypes.c_void_p(), wintypes.LPWSTR()
    if adv.GetNamedSecurityInfoW(str(path), 1, 0x1, ctypes.byref(sid), None, None, None, ctypes.byref(descriptor)):     # a file, its owner
        return None
    try:
        if not adv.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            return None
        try:
            return text.value
        finally:
            k32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        k32.LocalFree(descriptor)


def secure(folder: Path) -> None:
    """Make the agent's folder and close it to everyone but SYSTEM and administrators. ProgramData lets any
    signed-in person create folders, so a folder that is already there and belongs to somebody else is not
    believed: it is set aside and a new one made (a planted database could name another server)."""
    if folder.exists() and owner_of(folder) not in TRUSTED_OWNERS:
        folder.rename(folder.with_name(f"{folder.name}.not-ours-{datetime.now():%Y%m%d%H%M%S}"))
    folder.mkdir(parents=True, exist_ok=True)
    icacls = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")
    r = subprocess.run([icacls, str(folder), "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
                       capture_output=True, text=True, creationflags=0x08000000)
    if r.returncode:
        raise OSError(f"The agent's folder could not be closed to other accounts: {(r.stdout + r.stderr).strip()[:200]}")


def settle_service(log) -> None:
    """Two things the installer cannot say: start a little after Windows has (the network is up by then), and
    start again by itself if it ever stops unexpectedly (after 1, 1 and 5 minutes)."""
    sc = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "sc.exe")
    for args in (["config", SERVICE, "start=", "delayed-auto"],
                 ["failure", SERVICE, "reset=", "86400", "actions=", "restart/60000/restart/60000/restart/300000"]):
        try:
            r = subprocess.run([sc, *args], capture_output=True, text=True, timeout=30, creationflags=0x08000000)
            if r.returncode:
                log.warning("service setting not applied (sc %s): %s", args[0], r.stdout.strip()[:200])
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("service setting not applied (sc %s): %s", args[0], e)


def make_log(folder: Path) -> logging.Logger:
    log = logging.getLogger("sfagent")
    if not log.handlers:
        h = logging.handlers.RotatingFileHandler(folder / "agent.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


# --------------------------------------------------------------------------- reading the PC as a service
def read_posture(cfg: dict):
    """The PC's settings. The screen lock and AutoPlay are a person's settings, readable only while that
    person's part of the registry is loaded; while it is not, the last reading stands, so that a PC does not
    look different every time somebody signs out."""
    raw = compliance.read_posture()
    if raw and raw.get("as_system"):
        if raw.get("user_hive"):
            fleet._save(cfg, user_settings=json.dumps({k: raw.get(k) for k in ("screensaver", "autoplay_off")}))
        else:
            try:
                raw.update(json.loads(fleet.state(cfg).get("user_settings") or "{}"))
            except ValueError:
                pass
    return raw


def profiles() -> set:
    """The accounts that have a profile on this PC."""
    import winreg
    out = set()
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList") as top:
            for i in range(winreg.QueryInfoKey(top)[0]):
                out.add(winreg.EnumKey(top, i))
    except OSError:
        pass
    return out


def read_desktop(cfg: dict):
    """Installed programs. Those a person installed for themselves are visible only while that person is
    signed in; for everybody else who has a profile here the last reading is used, so a program does not
    count as removed whenever its owner signs out. That list never leaves the agent's own database."""
    raw = apps.read_desktop()
    if raw is None or not apps.running_as_system():
        return raw
    try:
        cache = json.loads(fleet.state(cfg).get("user_programs") or "{}")
        loaded = set(apps.loaded_users())
    except (ValueError, OSError):
        return raw
    for sid in loaded:
        cache[sid] = [{**e, "values": {k: v for k, v in e["values"].items() if k in USER_VALUES and isinstance(v, (str, int))}}
                      for e in raw if e.get("owner") == sid]
    have = profiles()
    cache = {sid: entries for sid, entries in cache.items() if sid in have}
    fleet._save(cfg, user_programs=json.dumps(cache))
    return raw + [e for sid, entries in cache.items() if sid not in loaded for e in entries]


def build(cfg: dict, folder: Path) -> dict:
    """What this report sends. A copy is kept so that `sfagent show` can print exactly what was sent."""
    network.view(force=True)
    p = fleet.payload(cfg, settings=SETTINGS, posture=lambda: read_posture(cfg))
    try:
        (folder / "last-report.json").write_text(json.dumps(p, indent=1), encoding="utf-8")
    except OSError:
        pass
    return p


# --------------------------------------------------------------------------- enrolling
def _registry(write: dict | None = None, delete: tuple = ()) -> dict:
    """The agent's key in the registry: where the installer and `sfagent enrol` leave the server and token."""
    import winreg
    access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY | (winreg.KEY_WRITE if write is not None or delete else 0)
    out = {}
    try:
        k = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, REG_KEY, 0, access) if write is not None else \
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_KEY, 0, access)
    except FileNotFoundError:
        return out
    with k:
        for name, value in (write or {}).items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        for name in delete:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
        for i in range(winreg.QueryInfoKey(k)[1]):
            name, value, _ = winreg.EnumValue(k, i)
            out[name] = value
    return out


def enrol_if_asked(cfg: dict, log, registry=_registry, now: datetime | None = None) -> str | None:
    """Enrol with the server and token the installer or `sfagent enrol` left in the registry. The token is
    removed as soon as it has worked, and after an hour of failures."""
    now = now or datetime.now()
    try:
        asked = registry()
    except OSError:
        return None
    server, token = str(asked.get("Server") or "").strip(), str(asked.get("Token") or "").strip()
    if not server or not token:
        return None
    s = fleet.state(cfg)
    tries = int(s.get("enrol_tries") or 0)
    try:
        if now - datetime.fromisoformat(s.get("enrol_tried") or "") < timedelta(minutes=ENROL_WAIT_MINUTES) and tries:
            return None
    except ValueError:
        pass
    try:
        st = fleet.enrol(cfg, server, token)
    except (RuntimeError, ValueError) as e:
        tries += 1
        fleet._save(cfg, enrol_tries=tries, enrol_tried=now.isoformat(timespec="seconds"), enrol_error=str(e)[:300])
        log.warning("enrolment failed (try %d of %d): %s", tries, ENROL_TRIES, e)
        if tries >= ENROL_TRIES:
            registry(delete=("Token",))
            fleet._save(cfg, enrol_tries=None)
            log.warning("enrolment given up; the token was removed. Run 'sfagent enrol' with a new one.")
        return str(e)
    registry(delete=("Token", "Server"))
    fleet._save(cfg, enrol_tries=None, enrol_tried=None, enrol_error=None)
    log.info("enrolled with %s as device %s", st["server"], st["device_id"])
    return None


# --------------------------------------------------------------------------- the service's work
def tick(cfg: dict, folder: Path, log, installed: bool) -> None:
    if not fleet.status(cfg)["enrolled"]:
        enrol_if_asked(cfg, log)
    if not fleet.due(cfg):
        return
    s = fleet.state(cfg)
    try:
        scan_due = datetime.now() - datetime.fromisoformat(s.get("scanned") or "") >= timedelta(minutes=SCAN_MINUTES)
    except ValueError:
        scan_due = True
    if scan_due and apps.scan(cfg, desktop=lambda: read_desktop(cfg), log=log):
        fleet._save(cfg, scanned=datetime.now().isoformat(timespec="seconds"))
    r = fleet.checkin(cfg, build=lambda c: build(c, folder), log=log)
    if r.get("ok"):
        did = selfupdate.maybe(cfg, VERSION, folder / "updates", log=log, installed=installed)
        if did not in ("up to date", "off", "waiting before trying again"):
            log.info("update: %s", did)


def work(stop: threading.Event, folder: Path, installed: bool) -> None:
    try:
        if installed:
            secure(folder)
        else:
            folder.mkdir(parents=True, exist_ok=True)
        log = make_log(folder)
    except Exception:       # nowhere to write: nothing to do but stop, the service manager records it
        return
    cfg = config(folder)
    log.info("%s %s started (%s)", NAME, VERSION, "service" if installed else "development run")
    if installed:
        settle_service(log)
    selfupdate.tidy(folder / "updates")
    while not stop.is_set():
        try:
            tick(cfg, folder, log, installed)
        except Exception:
            log.exception("a round failed; trying again in a minute")
        stop.wait(60)
    log.info("stopped")


# --------------------------------------------------------------------------- commands
def status_text(cfg: dict) -> str:
    st, s = fleet.status(cfg), fleet.state(cfg)
    lines = [f"{NAME} {VERSION}",
             f"enrolled:     {'yes, with ' + st['server'] if st['enrolled'] else 'no'}"]
    if st["enrolled"]:
        lines += [f"device id:    {st['device_id']}", f"last report:  {st['last_ok'] or 'none yet'}",
                  f"server kept:  {st['last_stored'] or '-'}"]
    if st["last_error"]:
        lines.append(f"last error:   {st['last_error']}")
    if s.get("enrol_error") and not st["enrolled"]:
        lines.append(f"enrolment:    {s['enrol_error']}")
    lines.append(f"self-update:  {'off' if s.get('updates') == 'off' else 'on'}"
                 + (f"; the server offers {s['release']}" if s.get("release") else "")
                 + (f"; last try failed: {s['update_error']}" if s.get("update_error") else ""))
    return "\n".join(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="sfagent", description=f"{NAME} {VERSION}")
    ap.add_argument("--data", default="", help="development only: keep state in this folder instead of ProgramData")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("service")
    r = sub.add_parser("run")
    r.add_argument("--once", action="store_true")
    e = sub.add_parser("enrol")
    e.add_argument("server")
    e.add_argument("token")
    sh = sub.add_parser("show")
    sh.add_argument("--json", action="store_true")
    for name in ("status", "leave", "version"):
        sub.add_parser(name)
    u = sub.add_parser("updates")
    u.add_argument("state", choices=["on", "off"])
    a = ap.parse_args(argv)
    if a.cmd == "version":
        print(VERSION)
        return
    folder = Path(a.data) if a.data else data_dir()
    if a.cmd == "service":
        import winsvc
        if not winsvc.run(SERVICE, lambda stop: work(stop, folder, installed=True)):
            sys.exit("This is started by Windows as a service. To try the agent by hand: sfagent --data <folder> run")
        return
    if a.cmd == "run":
        if not a.data:
            sys.exit("A run by hand needs --data <folder>, so that it does not touch the installed service's state.")
        stop = threading.Event()
        if a.once:
            folder.mkdir(parents=True, exist_ok=True)
            tick(config(folder), folder, make_log(folder), installed=False)
            print(status_text(config(folder)))
            return
        try:
            work(stop, folder, installed=False)
        except KeyboardInterrupt:
            stop.set()
        return
    cfg = config(folder)
    if a.data:
        folder.mkdir(parents=True, exist_ok=True)
    try:
        if a.cmd == "enrol":
            if fleet.status(cfg)["enrolled"]:
                sys.exit("This PC is already enrolled. Run 'sfagent leave' first to enrol it somewhere else.")
            try:
                server = fleet.check_server(a.server)
            except ValueError as err:
                sys.exit(str(err))
            if a.data:          # development: enrol here and now, as this account
                folder.mkdir(parents=True, exist_ok=True)
                print(f"Enrolled as device {fleet.enrol(cfg, server, a.token)['device_id']}.")
            else:               # the service holds the PC's key, so the service enrols
                _registry(write={"Server": server, "Token": a.token.strip()})
                fleet._save(cfg, enrol_tries=None, enrol_tried=None, enrol_error=None)
                print("Noted. The service enrols within a minute; see how it went with: sfagent status")
        elif a.cmd == "leave":
            fleet.leave(cfg)
            if not a.data:
                _registry(delete=("Token", "Server"))
            print("This PC no longer reports to a server. What was already sent stays there until its administrator removes the device.")
        elif a.cmd == "updates":
            fleet._save(cfg, updates=None if a.state == "on" else "off")
            print(f"Self-update is {a.state}.")
        elif a.cmd == "show":
            try:
                p = json.loads((folder / "last-report.json").read_text(encoding="utf-8"))
            except FileNotFoundError:
                sys.exit("Nothing has been sent yet.")
            print(json.dumps(p, indent=1) if a.json else f"Sent at {p.get('sent_at')}.\n\n" + fleet.as_text(p))
        else:
            print(status_text(cfg))
    except (PermissionError, RuntimeError, sqlite3.Error) as err:
        sys.exit(f"{err}\nThis needs an administrator's prompt (the agent's folder and settings are closed to other accounts).")
    except OSError as err:
        sys.exit(f"{err}\nIs the agent installed? Its folder is {folder}.")


if __name__ == "__main__":
    main()
