"""
Remediation: the only code that changes installed software or a running service. Two actions, each started
by one click in the console and confirmed there, one at a time, each written to `remedy_log`:

  update   run `winget upgrade` for ONE application the last update check listed, to the version that check
           worked out (apps.update_plan): the latest, or the newest of the line you are on when the latest is
           a major-version jump. Never an id or version that came from the page, never "all".
  stop     stop ONE running service the last Security comparison listed (`sc stop`, elevated through the
           normal Windows prompt). It is stopped, not disabled: Windows starts it again at the next boot if
           it is set to start automatically.
  firewall switch Windows Firewall ON for one profile or all three (`netsh advfirewall set ... state on`,
           elevated through the Windows prompt). On only: nothing here can switch it off, change a rule or
           change what a profile allows. Windows' existing rules then apply: a program without an allow rule
           stops accepting connections from other devices.

Off unless `library.remediate` is on (allowed by the user on 12 Oct 2026). Rules that hold whatever the page
sends: the application must be in the current list with an update that is not blocked; the caller must say
the publisher's licence terms were accepted (the dialog says so; winget gets --accept-package-agreements);
the agent's own Python is never updated from here; a major-version jump is never taken; nothing is
uninstalled, no service's start-up setting is changed, no configuration file is edited.

The agent runs as you, not elevated. An update is first tried that way, which is enough for programs
installed for you alone and for installers that ask for permission themselves. A silent installer that needs
administrator rights does NOT ask: it just fails (measured 12 Oct 2026: PuTTY's MSI, "Uninstall failed with
exit code: 1603", nothing changed). Only then is the same winget command started once more as administrator,
which raises the normal Windows permission prompt on your desktop; declining it fails the update, and that is
what is reported. The agent itself never becomes elevated.
"""
import ctypes
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime

CREATE_NO_WINDOW = 0x08000000
ID_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{1,120}")
VERSION_RX = re.compile(r"[0-9][0-9A-Za-z.+_-]{0,40}")
SERVICE_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._$-]{0,200}")
UPDATE_TIMEOUT = 30 * 60
state = {"running": False, "action": None, "name": None, "target": None, "started": None, "finished": None,
         "ok": None, "message": None}
_lock = threading.Lock()


def enabled(cfg: dict) -> bool:
    import library
    s = library.settings(cfg)
    return bool(s["enabled"] and s["applications"] and s["remediate"])


def winget_args(package_id: str, version: str | None) -> list:
    """The one command an update runs. One package, exact id, one catalogue, never "all"."""
    if not ID_RX.fullmatch(package_id or "") or (version is not None and not VERSION_RX.fullmatch(version)):
        raise ValueError("not a package id or version")
    args = ["upgrade", "--id", package_id, "--exact", "--source", "winget", "--silent",
            "--accept-package-agreements", "--disable-interactivity"]
    return args + (["--version", version] if version else [])


def run_winget(args: list) -> tuple:
    """(exit code, the last line winget said)."""
    import shutil
    exe = shutil.which("winget") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps",
                                                 "winget.exe")
    if os.name != "nt" or not os.path.exists(exe):
        return -1, "winget (Windows' App Installer) was not found on this PC."
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=UPDATE_TIMEOUT, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return -2, "The update did not finish in 30 minutes and was stopped."
    except (OSError, subprocess.SubprocessError) as e:
        return -1, f"winget could not be started ({type(e).__name__})."
    lines = [ln.split("\r")[-1].strip() for ln in (r.stdout or "").splitlines()]
    lines = [ln for ln in lines if ln and not re.fullmatch(r"[-\\|/ █▒░0-9.%KMGB/]+", ln)]
    return r.returncode, (lines[-1] if lines else "")[:300]


# --------------------------------------------------------------------------- stopping a service
class _ExecInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong), ("hwnd", ctypes.c_void_p),
                ("lpVerb", ctypes.c_wchar_p), ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
                ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p),
                ("lpIDList", ctypes.c_void_p), ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
                ("dwHotKey", ctypes.c_ulong), ("hIcon", ctypes.c_void_p), ("hProcess", ctypes.c_void_p)]


def _as_admin(exe: str, params: str, wait_ms: int):
    """Start one program as administrator (Windows shows its permission prompt) and wait for it.
    Returns its exit code, or 'declined', or 'error N' when Windows would not start it."""
    info = _ExecInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x8000                            # keep the process handle; no new console
    info.lpVerb, info.lpFile, info.lpParameters, info.nShow = "runas", exe, params, 0
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    if not shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        err = ctypes.get_last_error()
        return "declined" if err == 1223 else f"error {err}"
    code = ctypes.c_ulong(0)
    waited = kernel32.WaitForSingleObject(info.hProcess, wait_ms)
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hProcess)
    return "error timeout" if waited == 0x102 else code.value


# winget's "the installer (or the uninstaller of the old version) failed": what a silent installer without
# administrator rights ends in. Only these are tried again as administrator.
NEEDS_RIGHTS = {0x8A150006, 0x8A150030}


def run_winget_elevated(args: list) -> tuple:
    """The same winget command, as administrator. Its output cannot be read: (exit code, what happened)."""
    exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "winget.exe")
    if os.name != "nt" or not os.path.exists(exe):
        return -1, "winget (Windows' App Installer) was not found on this PC."
    got = _as_admin(exe, subprocess.list2cmdline(args), UPDATE_TIMEOUT * 1000)
    if got == "declined":
        return -3, "You declined the Windows permission prompt."
    if isinstance(got, str):
        return -1, f"Windows would not start winget as administrator ({got})."
    return (got if got < 0x80000000 else got - (1 << 32)), ""


def _sc() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "sc.exe")


def service_running(name: str) -> bool | None:
    """Asks Windows (no rights needed). None when it cannot be asked."""
    try:
        r = subprocess.run([_sc(), "query", name], capture_output=True, text=True, errors="replace", timeout=20,
                           creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"STATE\s*:\s*(\d+)", r.stdout or "")
    return None if not m else m.group(1) != "1"          # 1 = STOPPED


def stop_elevated(name: str) -> tuple:
    """`sc stop <name>` as administrator: Windows shows its permission prompt. (ok, message)."""
    if os.name != "nt":
        return False, "Only available on Windows."
    if not SERVICE_RX.fullmatch(name or ""):
        return False, "Not a service name."
    got = _as_admin(_sc(), f'stop "{name}"', 60_000)
    if got == "declined":
        return False, "You declined the Windows permission prompt."
    if isinstance(got, str):
        return False, f"Windows would not start the command ({got})."
    if got not in (0, 1062):                              # 1062: it was not running any more
        why = {5: "Windows refused: not enough rights.", 1051: "Other running services depend on it; stop those first.",
               1060: "Windows no longer knows this service."}.get(got, f"Windows answered with code {got}.")
        return False, why
    for _ in range(30):                                   # stopping takes a moment
        if service_running(name) is False:
            return True, "Stopped. Windows starts it again at the next boot if it is set to start automatically."
        time.sleep(1)
    return False, "Windows accepted the request, but the service is still running."


# --------------------------------------------------------------------------- the log
def _conn(db_path):
    c = sqlite3.connect(str(db_path), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS remedy_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, action TEXT,
        name TEXT, target TEXT, before TEXT, after TEXT, ok INTEGER, message TEXT)""")
    return c


def _record(db_path, action, name, target, before, after, ok, message) -> None:
    c = _conn(db_path)
    try:
        c.execute("INSERT INTO remedy_log (ts, action, name, target, before, after, ok, message) VALUES (?,?,?,?,?,?,?,?)",
                  (datetime.now().isoformat(timespec="seconds"), action, name, target, before, after, int(ok), message))
        c.commit()
    finally:
        c.close()


def history(db_path, limit: int = 30) -> list:
    c = _conn(db_path)
    try:
        return [dict(r) for r in c.execute("SELECT ts, action, name, target, before, after, ok, message FROM remedy_log "
                                           "ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        c.close()


def view(cfg: dict) -> dict:
    return {"enabled": enabled(cfg), "job": dict(state), "history": history(cfg["database"])}


# --------------------------------------------------------------------------- the two actions
def _installed(cfg: dict) -> list:
    import apps
    import library
    s = library.settings(cfg)
    return apps.with_updates(cfg, apps.view(cfg), s["check_updates"], s["update_hours"])["apps"]


def _refresh(cfg: dict, log=None) -> None:
    """Look again at what is installed, what is newer, and what is vulnerable, so the pages show the result."""
    import apps
    import library
    s = library.settings(cfg)
    apps.scan(cfg, log=log)
    if s["check_updates"]:
        apps.check_updates(cfg, log=log)
    if s["vulnerabilities"]:
        import cve
        cve.scan(cfg, updates=s["check_updates"], hours=s["update_hours"], log=log)


def _begin(action: str, name: str, target: str) -> bool:
    with _lock:
        if state["running"]:
            return False
        state.update(running=True, action=action, name=name, target=target, ok=None, message=None, finished=None,
                     started=datetime.now().isoformat(timespec="seconds"))
        return True


def _end(ok: bool, message: str) -> None:
    state.update(running=False, ok=ok, message=message, finished=datetime.now().isoformat(timespec="seconds"))


def start_update(cfg: dict, app_id: str, terms_accepted: bool, log=None, run=run_winget,
                 elevated=run_winget_elevated, wait: bool = False) -> dict:
    """Start updating one application. Everything about it comes from the agent's own list, not the caller."""
    if not enabled(cfg):
        return {"ok": False, "message": "Updating from the console is switched off in Settings."}
    app = next((a for a in _installed(cfg) if a["id"] == app_id), None)
    plan = (app or {}).get("update")
    if not plan:
        return {"ok": False, "message": "No update is listed for that application. Check for newer versions again."}
    if plan["blocked"]:
        return {"ok": False, "message": plan["blocked"]}
    if terms_accepted is not True:
        return {"ok": False, "message": "The publisher's licence terms have to be accepted first."}
    try:
        args = winget_args(plan["id"], plan["to"] if plan["kind"] == "same_line" else None)
    except ValueError:
        return {"ok": False, "message": "winget's name for this application cannot be used safely."}
    if not _begin("update", app["name"], plan["to"]):
        return {"ok": False, "message": "Another update or stop is still running."}
    before = app["version"]

    def work():
        ok, msg, after = False, "", before
        try:
            if log:
                log.info("REMEDY update %s -> %s (winget %s)", app["name"], plan["to"], " ".join(args))
            code, said = run(args)
            if code & 0xFFFFFFFF in NEEDS_RIGHTS:           # a silent installer without rights fails, it does not ask
                if log:
                    log.info("REMEDY update needs administrator rights (winget code %#x): asking Windows", code & 0xFFFFFFFF)
                state["message"] = "Windows is asking for permission on your desktop."
                code2, said2 = elevated(args)
                code, said = code2, said2 or (said if code2 else "")
            try:
                _refresh(cfg, log)
            except Exception as e:  # the update itself is what counts
                if log:
                    log.warning("refresh after update failed: %s", e)
            now = [a for a in _installed(cfg) if a["key"] == app["key"]]
            after = now[-1]["version"] if now else ""
            changed = bool(now) and after != before
            if code == 0 and changed:
                ok, msg = True, f"Updated {app['name']} from {before or '?'} to {after}."
            elif code == 0:
                ok, msg = True, (f"winget reports the update as done, but Windows still lists version {before or '?'}. "
                                 "It may need the program closed, or a restart.")
            elif code == -3:
                msg = f"Not updated: {said} The installer needs administrator rights."
            else:
                msg = f"The update did not go through (winget code {code & 0xFFFFFFFF:#x})." + (f" {said}" if said else "")
        except Exception as e:  # never leave the job marked as running
            msg = f"The update failed: {str(e)[:200]}"
        try:
            _record(cfg["database"], "update", app["name"], plan["to"], before, after, ok, msg)
        finally:
            _end(ok, msg)
            if log:
                log.info("REMEDY update %s: %s", "ok" if ok else "FAILED", msg)

    if wait:
        work()
    else:
        threading.Thread(target=work, daemon=True, name="remedy").start()
    return {"ok": True, "started": True, "job": dict(state)}


def start_stop(cfg: dict, service_id: str, log=None, stop=stop_elevated, wait: bool = False) -> dict:
    """Start stopping one service the last Security comparison listed as running."""
    if not enabled(cfg):
        return {"ok": False, "message": "Stopping services from the console is switched off in Settings."}
    import cve
    svc = next((s for s in cve.report(cfg)["services"] if s["id"] == service_id), None)
    if not svc or not SERVICE_RX.fullmatch(svc["service"]):
        return {"ok": False, "message": "Unknown service. Check again on the Security page."}
    if not _begin("stop", svc["name"], svc["service"]):
        return {"ok": False, "message": "Another update or stop is still running."}

    def work():
        ok, msg = False, ""
        try:
            if log:
                log.info("REMEDY stop service %s", svc["service"])
            ok, msg = stop(svc["service"])
            try:
                import library
                s = library.settings(cfg)
                if s["vulnerabilities"]:
                    cve.scan(cfg, updates=s["check_updates"], hours=s["update_hours"], log=log)
            except Exception as e:
                if log:
                    log.warning("refresh after stop failed: %s", e)
        except Exception as e:
            msg = f"Stopping failed: {str(e)[:200]}"
        try:
            _record(cfg["database"], "stop", svc["name"], svc["service"], "running", "stopped" if ok else "running", ok, msg)
        finally:
            _end(ok, msg)
            if log:
                log.info("REMEDY stop %s: %s", "ok" if ok else "FAILED", msg)

    if wait:
        work()
    else:
        threading.Thread(target=work, daemon=True, name="remedy").start()
    return {"ok": True, "started": True, "job": dict(state)}


# --------------------------------------------------------------------------- Windows Firewall: on, never off
FIREWALL = {"all": "allprofiles", "Domain": "domainprofile", "Private": "privateprofile", "Public": "publicprofile"}


def _netsh() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "netsh.exe")


def firewall_state() -> dict:
    """{'Domain': True, 'Private': False, ...} as Windows reports it now (no rights needed). {} if unknown."""
    try:
        r = subprocess.run([_netsh(), "advfirewall", "show", "allprofiles", "state"], capture_output=True, text=True,
                           errors="replace", timeout=30, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return {}
    out, name = {}, None
    for ln in (r.stdout or "").splitlines():
        m = re.match(r"\s*(Domain|Private|Public) Profile", ln)
        if m:
            name = m.group(1)
        m = re.match(r"\s*State\s+(ON|OFF)\s*$", ln)
        if m and name:
            out[name] = m.group(1) == "ON"
    return out


def firewall_on_elevated(profile: str) -> tuple:
    """Switch one profile (or all) on, as administrator. (ok, message)."""
    if os.name != "nt":
        return False, "Only available on Windows."
    if profile not in FIREWALL:
        return False, "Unknown firewall profile."
    got = _as_admin(_netsh(), f"advfirewall set {FIREWALL[profile]} state on", 60_000)
    if got == "declined":
        return False, "You declined the Windows permission prompt."
    if isinstance(got, str):
        return False, f"Windows would not start the command ({got})."
    now = firewall_state()
    want = list(now) if profile == "all" else [profile]
    still = [p for p in want if now.get(p) is False]
    if got != 0 or still:
        return False, ("Windows Firewall is still off" + (f" for {', '.join(still)}" if still else "")
                       + ". A policy set by an administrator or another security product may be holding it off.")
    return True, ("Windows Firewall is on for " + ("all profiles" if profile == "all" else f"the {profile} profile")
                  + ". Programs without an allow rule no longer accept connections from other devices.")


def start_firewall_on(cfg: dict, profile: str, log=None, turn_on=firewall_on_elevated, wait: bool = False) -> dict:
    """Start switching Windows Firewall on. There is no way to switch it off from here."""
    if not enabled(cfg):
        return {"ok": False, "message": "Changing things from the console is switched off in Settings."}
    if profile not in FIREWALL:
        return {"ok": False, "message": "Unknown firewall profile."}
    label = "all profiles" if profile == "all" else f"{profile} profile"
    if not _begin("firewall", "Windows Firewall", label):
        return {"ok": False, "message": "Another update or stop is still running."}

    def work():
        ok, msg = False, ""
        try:
            if log:
                log.info("REMEDY firewall on: %s", label)
            ok, msg = turn_on(profile)
            try:
                import network
                network.view(force=True, log=log)       # the Network page and the dashboard show the new state
            except Exception as e:
                if log:
                    log.warning("refresh after firewall change failed: %s", e)
        except Exception as e:
            msg = f"Switching the firewall on failed: {str(e)[:200]}"
        try:
            _record(cfg["database"], "firewall", "Windows Firewall", label, "off", "on" if ok else "off", ok, msg)
        finally:
            _end(ok, msg)
            if log:
                log.info("REMEDY firewall %s: %s", "ok" if ok else "FAILED", msg)

    if wait:
        work()
    else:
        threading.Thread(target=work, daemon=True, name="remedy").start()
    return {"ok": True, "started": True, "job": dict(state)}


def own_python(update_id: str | None) -> bool:
    """Is this winget package the Python the agent itself is running on?"""
    return (update_id or "").lower() == f"python.python.{sys.version_info[0]}.{sys.version_info[1]}"
