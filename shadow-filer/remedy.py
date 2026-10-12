"""
Remediation: the only code that changes installed software or a running service. Two actions, each started
by one click in the console and confirmed there, one at a time, each written to `remedy_log`:

  update   run `winget upgrade` for ONE application the last update check listed, to the version that check
           worked out (apps.update_plan): the latest, or the newest of the line you are on when the latest is
           a major-version jump. Never an id or version that came from the page, never "all".
  stop     stop ONE running service the last Security comparison listed (`sc stop`, elevated through the
           normal Windows prompt). It is stopped, not disabled: Windows starts it again at the next boot if
           it is set to start automatically.

Off unless `library.remediate` is on (allowed by the user on 12 Oct 2026). Rules that hold whatever the page
sends: the application must be in the current list with an update that is not blocked; the caller must say
the publisher's licence terms were accepted (the dialog says so; winget gets --accept-package-agreements);
the agent's own Python is never updated from here; a major-version jump is never taken; nothing is
uninstalled, no service's start-up setting is changed, no configuration file is edited.

The agent runs as you, not elevated: an installer that needs administrator rights raises the normal Windows
permission prompt on your desktop, and declining it fails the update, which is reported as such.
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
    info = _ExecInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x8000                            # keep the process handle; no new console
    info.lpVerb, info.lpFile, info.lpParameters, info.nShow = "runas", _sc(), f'stop "{name}"', 0
    shell32, kernel32 = ctypes.windll.shell32, ctypes.windll.kernel32
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.GetLastError() or kernel32.GetLastError()
        return False, ("You declined the Windows permission prompt." if err == 1223
                       else f"Windows would not start the command (error {err}).")
    code = ctypes.c_ulong(0)
    kernel32.WaitForSingleObject(info.hProcess, 60_000)
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hProcess)
    if code.value not in (0, 1062):                       # 1062: it was not running any more
        why = {5: "Windows refused: not enough rights.", 1051: "Other running services depend on it; stop those first.",
               1060: "Windows no longer knows this service."}.get(code.value, f"Windows answered with code {code.value}.")
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


def start_update(cfg: dict, app_id: str, terms_accepted: bool, log=None, run=run_winget, wait: bool = False) -> dict:
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


def own_python(update_id: str | None) -> bool:
    """Is this winget package the Python the agent itself is running on?"""
    return (update_id or "").lower() == f"python.python.{sys.version_info[0]}.{sys.version_info[1]}"
