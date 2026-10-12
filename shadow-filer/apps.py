"""
Applications: what is installed on this PC, in which version, and what changed since the last look.
Shown on Library > Applications. READ-ONLY: nothing is installed, updated, removed or started from here.

  desktop    programs from Windows' own "installed programs" lists in the registry (all users 64-bit, all
             users 32-bit, this user), minus what Windows Settings also hides: system components, patches
             and entries that belong to another program.
  packaged   Store and other packaged apps of this user (Get-AppxPackage), minus frameworks, resource
             packages and Windows' own system parts.

What is read: the registry, and for packaged apps one fixed PowerShell call (the package list, the Start menu
names and each package's manifest, for the name and publisher). None of your files are opened. Nothing goes
online, with one exception that is off until switched on: asking winget which applications have a newer
version (see "newer versions" below).

A list of versions only shows today, so every scan is compared with the one before and the differences are
kept in `apps_history` (installed, updated from -> to, removed, with the day the agent noticed). The very
first scan records nothing: everything would be "installed today". If a list cannot be read, the entries
from the previous scan are kept for it, so a failed read never shows up as "everything was removed".

An MSI gets a new registry key with every version and many names carry the version ("7-Zip 24.08 (x64)"), so
an application is recognised by its name with the version taken out, not by its registry key.

Measured on the user's PC (12 Oct 2026): 281 registry entries, 258 with a name, 89 after the filter; of
those 86 carry a version, 87 a publisher, 56 a size, 45 an install date and 40 an install folder. Where
the date is missing the day the registry entry last changed is shown instead, marked as such: it moves with
every update. 194 packages, 84 after the filter (69 from the Store).
"""
import json
import os
import re
import sqlite3
import subprocess
from datetime import date, datetime, timedelta

CREATE_NO_WINDOW = 0x08000000
UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
PATCH_TYPES = {"security update", "update rollup", "hotfix", "update", "servicepack"}
HISTORY_DAYS = 366
VERSION_IN_NAME = re.compile(r"(?<![A-Za-z0-9.])v?\d+(?:\.\d+)+(?![A-Za-z0-9])", re.I)
NOISE = re.compile(r"\((?:x64|x86|64-bit|32-bit|arm64|user|remove only)\)|\b(?:x64|x86|amd64|win64|win32|64-bit|32-bit|"
                   r"setup|installer|install)\b", re.I)


# --------------------------------------------------------------------------- reading
def read_desktop() -> list | None:
    """Raw entries of the three registry lists. None when the registry cannot be read (not Windows)."""
    try:
        import winreg
    except ImportError:
        return None
    views = ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, "machine", "64-bit"),
             (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, "machine", "32-bit"),
             (winreg.HKEY_CURRENT_USER, 0, "user", ""))
    out, opened = [], 0
    for hive, flag, scope, arch in views:
        try:
            top = winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | flag)
        except OSError:
            continue
        opened += 1
        with top:
            for i in range(winreg.QueryInfoKey(top)[0]):
                try:
                    sub = winreg.EnumKey(top, i)
                    with winreg.OpenKey(top, sub) as k:
                        _, n_values, changed = winreg.QueryInfoKey(k)
                        vals = {}
                        for j in range(n_values):
                            name, value, _ = winreg.EnumValue(k, j)
                            vals[name] = value
                except OSError:
                    continue
                out.append({"id": f"{scope}{arch[:2]}:{sub}", "scope": scope, "arch": arch, "values": vals,
                            "changed": changed / 1e7 - 11644473600})   # 100 ns since 1601 -> Unix time
    return out if opened else None


PACKAGED_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$start = @{}
foreach ($a in Get-StartApps) { $fam = ($a.AppID -split '!')[0]; if (-not $start.ContainsKey($fam)) { $start[$fam] = $a.Name } }
$out = foreach ($p in Get-AppxPackage) {
  if ($p.IsFramework -or $p.IsResourcePackage -or $p.IsBundle -or "$($p.SignatureKind)" -eq 'System') { continue }
  $m = (Get-AppxPackageManifest $p).Package.Properties
  $made = ''
  if ($p.InstallLocation) { $d = Get-Item -LiteralPath $p.InstallLocation; if ($d) { $made = $d.CreationTime.ToString('yyyy-MM-dd') } }
  [pscustomobject]@{ id = "$($p.PackageFamilyName)"; name = "$($p.Name)"; display = "$($m.DisplayName)";
    start = "$($start[$p.PackageFamilyName])"; version = "$($p.Version)"; subject = "$($p.Publisher)";
    publisher = "$($m.PublisherDisplayName)"; arch = "$($p.Architecture)"; location = "$($p.InstallLocation)";
    installed = $made; signature = "$($p.SignatureKind)" }
}
$json = ConvertTo-Json -InputObject @($out) -Compress
'JSON:' + [regex]::Replace($json, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
"""


def read_packaged() -> list | None:
    """Raw packaged apps of this user. None when Windows could not be asked."""
    if os.name != "nt":
        return None
    root = os.environ.get("SystemRoot", r"C:\Windows")
    ps = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    try:
        r = subprocess.run([ps if os.path.exists(ps) else "powershell.exe", "-NoProfile", "-NonInteractive",
                            "-Command", PACKAGED_PS], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180, creationflags=CREATE_NO_WINDOW)
        line = next((x for x in r.stdout.splitlines() if x.startswith("JSON:")), None)
        rows = json.loads(line[5:]) if line else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else None


# --------------------------------------------------------------------------- tidying
def name_key(name: str, version: str = "") -> str:
    """'7-Zip 24.08 (x64)' -> '7zip': the name without its version, so an update is the same application."""
    s = name or ""
    if version and len(version) > 1:
        s = s.replace(version, " ")
    s = NOISE.sub(" ", VERSION_IN_NAME.sub(" ", s))
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def version_tuple(v: str | None) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:6])


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _install_date(v) -> str | None:
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", _text(v) if isinstance(v, str) else str(v or ""))
    if not m:
        return None
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return d.isoformat() if 1995 <= d.year and d <= date.today() + timedelta(days=1) else None


def desktop_apps(raw: list) -> list:
    """The registry entries Windows Settings would list, one per application and version."""
    out, seen = [], set()
    for e in raw:
        v = e.get("values") or {}
        name = _text(v.get("DisplayName"))
        if (not name or v.get("SystemComponent") == 1 or _text(v.get("ParentKeyName"))
                or _text(v.get("ReleaseType")).lower() in PATCH_TYPES):
            continue
        version = _text(v.get("DisplayVersion"))
        key = "desktop:" + (name_key(name, version) or name.lower())
        if (key, version) in seen:      # listed in both the 64-bit and the 32-bit view, or for the user too
            continue
        seen.add((key, version))
        installed = _install_date(v.get("InstallDate"))
        size = v.get("EstimatedSize")
        out.append({"id": e["id"], "key": key, "name": name, "version": version,
                    "publisher": _text(v.get("Publisher")), "kind": "desktop", "from_store": False,
                    "scope": e.get("scope") or "machine", "arch": e.get("arch") or "",
                    "installed": installed or datetime.fromtimestamp(e.get("changed") or 0).date().isoformat(),
                    "date_is": "installed" if installed else "changed",
                    "size": size * 1024 if isinstance(size, int) and size > 0 else None,
                    "location": _text(v.get("InstallLocation")).strip('"') or None})
    return out


def _plain(s: str) -> str:
    """A manifest text, unless it is a pointer into the package's resources ('ms-resource:...')."""
    s = _text(s)
    return "" if s.lower().startswith("ms-resource:") else s


def _pretty(package: str) -> str:
    """'Microsoft.WindowsCalculator' -> 'Windows Calculator'."""
    last = (package or "").split(".")[-1]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", last) or package


def packaged_apps(raw: list) -> list:
    out = []
    for p in raw:
        fam = _text(p.get("id"))
        if not fam:
            continue
        m = re.search(r'(?:^|,\s*)CN=("([^"]+)"|[^,]+)', _text(p.get("subject")))
        cn = (m.group(2) or m.group(1)).strip() if m else ""
        if re.fullmatch(r"[0-9A-Fa-f-]{30,}", cn):      # a Store publisher id, not a name
            cn = ""
        arch = {"X64": "64-bit", "X86": "32-bit", "Arm64": "ARM 64-bit"}.get(_text(p.get("arch")), "")
        out.append({"id": "packaged:" + fam, "key": "packaged:" + fam.lower(),
                    "name": _plain(p.get("display")) or _text(p.get("start")) or _pretty(_text(p.get("name"))),
                    "version": _text(p.get("version")), "publisher": _plain(p.get("publisher")) or cn,
                    "kind": "packaged", "from_store": _text(p.get("signature")) == "Store", "scope": "user",
                    "arch": arch, "installed": _text(p.get("installed")) or None, "date_is": "changed",
                    "size": None, "location": _text(p.get("location")) or None})
    return out


# --------------------------------------------------------------------------- what changed
def diff(before: list, after: list) -> list:
    """Events between two lists: {'event': installed | updated | removed, name, old_version, new_version, ...}.
    One version gone and one new under the same name is an update; anything else is counted one by one
    (two versions side by side, like two Python releases, stay two applications)."""
    def by_key(apps):
        d = {}
        for a in apps:
            d.setdefault(a["key"], {})[a["version"]] = a
        return d

    old, new, out = by_key(before), by_key(after), []
    for key in sorted(set(old) | set(new)):
        o, n = old.get(key, {}), new.get(key, {})
        gone, came = [o[v] for v in o if v not in n], [n[v] for v in n if v not in o]
        if len(gone) == 1 and len(came) == 1:
            a = came[0]
            out.append({"event": "updated", "key": key, "name": a["name"], "publisher": a["publisher"],
                        "kind": a["kind"], "old_version": gone[0]["version"], "new_version": a["version"]})
            continue
        for a in came:
            out.append({"event": "installed", "key": key, "name": a["name"], "publisher": a["publisher"],
                        "kind": a["kind"], "old_version": "", "new_version": a["version"]})
        for a in gone:
            out.append({"event": "removed", "key": key, "name": a["name"], "publisher": a["publisher"],
                        "kind": a["kind"], "old_version": a["version"], "new_version": ""})
    return out


def _conn(db_path):
    c = sqlite3.connect(str(db_path), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS apps_state (k TEXT PRIMARY KEY, value TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS apps_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, event TEXT, key TEXT, name TEXT, publisher TEXT,
        kind TEXT, old_version TEXT, new_version TEXT)""")
    return c


def _snapshot(c) -> dict | None:
    r = c.execute("SELECT value FROM apps_state WHERE k='snapshot'").fetchone()
    try:
        return json.loads(r[0]) if r else None
    except ValueError:
        return None


def scan(cfg: dict, desktop=read_desktop, packaged=read_packaged, now: datetime | None = None, log=None) -> dict | None:
    """Read both lists, note what changed since the last scan, keep the new list. None if nothing could be read."""
    now = now or datetime.now()
    raw_d, raw_p = desktop(), packaged()
    c = _conn(cfg["database"])
    try:
        prev = _snapshot(c)
        kept = (prev or {}).get("apps", [])
        if raw_d is None and raw_p is None:
            return None
        # a list that could not be read keeps what it had last time
        d = desktop_apps(raw_d) if raw_d is not None else [a for a in kept if a["kind"] == "desktop"]
        p = packaged_apps(raw_p) if raw_p is not None else [a for a in kept if a["kind"] == "packaged"]
        apps = sorted(d + p, key=lambda a: (a["name"].lower(), version_tuple(a["version"])))
        events = diff(kept, apps) if prev else []
        ts = now.isoformat(timespec="seconds")
        c.executemany("INSERT INTO apps_history (ts, event, key, name, publisher, kind, old_version, new_version) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      [(ts, e["event"], e["key"], e["name"], e["publisher"], e["kind"], e["old_version"],
                        e["new_version"]) for e in events])
        c.execute("DELETE FROM apps_history WHERE ts < ?", ((now - timedelta(days=HISTORY_DAYS)).isoformat(),))
        snap = {"scanned_at": ts, "desktop_read": raw_d is not None, "packaged_read": raw_p is not None,
                "first_scan": (prev or {}).get("first_scan") or ts, "apps": apps}
        c.execute("INSERT OR REPLACE INTO apps_state VALUES ('snapshot', ?)", (json.dumps(snap),))
        c.commit()
    finally:
        c.close()
    if log:
        log.info("applications: %d desktop, %d packaged, %d change(s) since the last scan",
                 len(d), len(p), len(events))
    return {**snap, "events": events}


def history(db_path, since: str, limit: int = 500) -> list:
    """Changes noticed on or after `since` (an ISO day), newest first."""
    c = _conn(db_path)
    try:
        return [dict(r) for r in c.execute(
            "SELECT ts, event, key, name, publisher, kind, old_version, new_version FROM apps_history "
            "WHERE ts >= ? ORDER BY ts DESC, id DESC LIMIT ?", (since, limit))]
    finally:
        c.close()


# --------------------------------------------------------------------------- what the page shows
def view(cfg: dict, days: int = 90, today: date | None = None) -> dict:
    """The last list, the counts the page shows and what changed in the last `days` days."""
    c = _conn(cfg["database"])
    try:
        snap = _snapshot(c)
    finally:
        c.close()
    if not snap:
        return {"scanned_at": None, "apps": [], "changes": [], "changes_days": days, "history_since": None,
                "desktop_read": False, "packaged_read": False,
                "counts": {"desktop": 0, "packaged": 0, "store": 0, "no_version": 0, "date_is_a_guess": 0},
                "total_bytes": 0, "sized": 0}
    apps = snap["apps"]
    since = ((today or date.today()) - timedelta(days=days)).isoformat()
    desk = [a for a in apps if a["kind"] == "desktop"]
    return {"scanned_at": snap["scanned_at"], "apps": apps, "changes": history(cfg["database"], since),
            "changes_days": days, "history_since": snap.get("first_scan"),
            "desktop_read": snap.get("desktop_read", True), "packaged_read": snap.get("packaged_read", True),
            "counts": {"desktop": len(desk), "packaged": len(apps) - len(desk),
                       "store": sum(1 for a in apps if a["from_store"]),
                       "no_version": sum(1 for a in desk if not a["version"]),
                       "date_is_a_guess": sum(1 for a in desk if a["date_is"] != "installed")},
            "total_bytes": sum(a["size"] or 0 for a in desk), "sized": sum(1 for a in desk if a["size"])}


# --------------------------------------------------------------------------- newer versions (online, optional)
# The one part of this file that goes online, and only when `library.check_updates` is on. `winget upgrade`
# compares what is installed with winget's package catalogue. Only the community catalogue is asked
# ("--source winget"): winget downloads that catalogue's index from Microsoft's servers and compares on this
# PC. The Store catalogue is left out: it is asked about one package at a time, which tells it what is
# installed. Nothing is ever updated from here: the list says what is available, you update yourself.
WINGET_ARGS = ["upgrade", "--source", "winget", "--disable-interactivity"]


def parse_upgrades(text: str) -> list:
    """Rows of winget's table(s): {'name', 'id', 'version', 'available'}. The columns are found from where
    the header words start, so the header's language does not matter."""
    lines = [ln.split("\r")[-1].rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    out, seen = [], set()
    for i, line in enumerate(lines):
        if i == 0 or not re.fullmatch(r"-{20,}", line):
            continue
        cols = [m.start() for m in re.finditer(r"\S+", lines[i - 1])]
        if len(cols) < 4:
            continue
        for row in lines[i + 1:]:
            if len(row) <= cols[3] or row[cols[1] - 1] != " ":
                break       # the footer ("31 upgrades available."), or the end of this table
            name, pid = row[:cols[1]].strip(), row[cols[1]:cols[2]].strip()
            version = row[cols[2]:cols[3]].strip()
            available = row[cols[3]:cols[4]].strip() if len(cols) > 4 else row[cols[3]:].strip()
            if not name or not re.fullmatch(r"\S+", pid) or not available or pid in seen:
                continue
            seen.add(pid)
            out.append({"name": name, "id": pid, "version": version, "available": available})
    return out


def read_updates() -> dict:
    """Ask winget which installed applications have a newer version. {'ok', 'error', 'rows'}."""
    import shutil
    exe = shutil.which("winget") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps",
                                                 "winget.exe")
    if os.name != "nt" or not os.path.exists(exe):
        return {"ok": False, "error": "winget (Windows' App Installer) was not found on this PC.", "rows": []}
    try:
        r = subprocess.run([exe, *WINGET_ARGS], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": f"winget did not answer ({type(e).__name__}).", "rows": []}
    rows = parse_upgrades(r.stdout or "")
    if r.returncode != 0 and not rows:
        return {"ok": False, "error": f"winget stopped with code {r.returncode}. Run 'winget upgrade' once in a "
                                      "terminal to see why (it may be asking you to accept its terms).", "rows": []}
    return {"ok": True, "error": None, "rows": rows}


def _updates(c) -> dict | None:
    r = c.execute("SELECT value FROM apps_state WHERE k='updates'").fetchone()
    try:
        return json.loads(r[0]) if r else None
    except ValueError:
        return None


def check_updates(cfg: dict, read=read_updates, now: datetime | None = None, log=None) -> dict:
    """Ask once and keep the answer. A failed check keeps the previous list, and says so."""
    got = read()
    c = _conn(cfg["database"])
    try:
        prev = _updates(c) or {}
        ts = (now or datetime.now()).isoformat(timespec="seconds")
        installed = (_snapshot(c) or {}).get("apps", [])
        new = {"checked_at": ts, "ok": bool(got["ok"]), "error": got.get("error"),
               "rows": match_updates(installed, got["rows"]) if got["ok"] else prev.get("rows", []),
               "rows_from": ts if got["ok"] else prev.get("rows_from")}
        c.execute("INSERT OR REPLACE INTO apps_state VALUES ('updates', ?)", (json.dumps(new),))
        c.commit()
    finally:
        c.close()
    if log:
        if got["ok"]:
            log.info("applications: winget lists %d newer version(s)", len(got["rows"]))
        else:
            log.warning("applications: update check failed: %s", got.get("error"))
    return new


def updates_due(cfg: dict, hours: int, now: datetime | None = None) -> bool:
    c = _conn(cfg["database"])
    try:
        last = (_updates(c) or {}).get("checked_at")
    finally:
        c.close()
    try:
        return not last or (now or datetime.now()) - datetime.fromisoformat(last) >= timedelta(hours=hours)
    except ValueError:
        return True


def match_updates(apps: list, rows: list) -> list:
    """The rows, each with the application it is about: 'app_id' and 'app_version' (None when it fits
    nothing in the list). By name: winget shows the name Windows lists, but often writes the version
    differently ("3.11.1" for "3.11.1150.0"), so the version only decides between two of the same name.
    winget can list one application under two package ids; the second row is dropped."""
    by_name, by_key = {}, {}
    for a in apps:
        by_name.setdefault(a["name"].lower(), []).append(a)
        by_key.setdefault(name_key(a["name"], a["version"]), []).append(a)
    out, taken = [], set()
    for r in rows:
        known = by_name.get(r["name"].lower()) or by_key.get(name_key(r["name"], r["version"])) or []
        if not known:       # a packaged app: winget's id is the package's own name
            known = [a for a in apps if a["key"].startswith(f"packaged:{r['id'].lower()}_")]
        cands = [a for a in known if a["id"] not in taken]
        if known and not cands:
            continue
        same = [a for a in cands if a["version"] == r["version"]]
        hit = same[0] if same else min(cands, key=lambda a: version_tuple(a["version"])) if cands else None
        if hit:
            taken.add(hit["id"])
        out.append({**r, "app_id": hit["id"] if hit else None, "app_version": hit["version"] if hit else None})
    return out


def with_updates(cfg: dict, v: dict, enabled: bool, hours: int) -> dict:
    """The page's view plus what the last update check found."""
    c = _conn(cfg["database"])
    try:
        u = _updates(c) if enabled else None
    finally:
        c.close()
    # a row counts only while the installed version is still the one the check saw, so an application you
    # have updated since stops showing as out of date
    rows = {r["app_id"]: r for r in (u or {}).get("rows", []) if r.get("app_id")}
    apps = []
    for a in v["apps"]:
        r = rows.get(a["id"])
        ok = bool(r) and r["app_version"] == a["version"]
        apps.append({**a, "available": r["available"] if ok else None, "update_id": r["id"] if ok else None})
    loose = [{k: r[k] for k in ("name", "id", "version", "available")} for r in (u or {}).get("rows", [])
             if not r.get("app_id")]
    return {**v, "apps": apps,
            "updates": {"enabled": enabled, "hours": hours, "checked_at": (u or {}).get("checked_at"),
                        "listed_at": (u or {}).get("rows_from"), "ok": (u or {}).get("ok", True),
                        "error": (u or {}).get("error"), "count": sum(1 for a in apps if a["available"]),
                        "unmatched": loose}}


# --------------------------------------------------------------------------- installer files you hold
def match_installers(installers: list, apps: list) -> list:
    """For each program file from the Library scan, the installed application it belongs to, if one is
    plainly the same product: {'installed_name', 'installed_version', 'file_is': older | same | newer | None}."""
    by = {}
    for a in apps:
        if a["kind"] == "desktop":
            k = a["key"].split(":", 1)[1]
            if k not in by or version_tuple(a["version"]) > version_tuple(by[k]["version"]):
                by[k] = a
    out = []
    for i in installers:
        version = i.get("version") or ""
        cands = [name_key(i.get("product") or "", version), name_key(os.path.splitext(i["name"])[0], version)]
        hit = next((by[k] for k in cands if k in by), None)
        if not hit:      # "Git" inside "Git for Windows": a prefix counts once it is long enough to mean something
            hit = next((a for k in cands if len(k) >= 5 for ak, a in by.items()
                        if len(ak) >= 5 and (ak.startswith(k) or k.startswith(ak))), None)
        if not hit:
            out.append(i)
            continue
        mine, theirs = version_tuple(version), version_tuple(hit["version"])
        n = min(len(mine), len(theirs))      # "24.8" against "24.8.0.0" is the same version
        is_ = None if not n else "older" if mine[:n] < theirs[:n] else "newer" if mine[:n] > theirs[:n] else "same"
        out.append({**i, "installed_name": hit["name"], "installed_version": hit["version"], "file_is": is_})
    return out


def as_text(v: dict, packaged: bool = False) -> str:
    if not v["scanned_at"]:
        return "No applications listed yet.\n"
    rows = [a for a in v["apps"] if packaged or a["kind"] == "desktop"]
    w = min(48, max((len(a["name"]) for a in rows), default=10))
    c = v["counts"]
    lines = [f"{c['desktop']} programs, {c['packaged']} Store and packaged apps "
             f"(listed {v['scanned_at'].replace('T', ' ')})", ""]
    for a in rows:
        when = (a["installed"] or "") + ("" if a["date_is"] == "installed" or not a["installed"] else "*")
        newer = f"  -> {a['available']}" if a.get("available") else ""
        lines.append(f"{a['name'][:w]:<{w}}  {a['version'][:22]:<22}  {when:<11}  {a['publisher'][:36]}{newer}")
    lines += ["", "* no install date recorded: the day the entry last changed (moves with every update)"]
    u = v.get("updates")
    if u and u["enabled"]:
        lines += ["", f"Newer versions (winget, asked {(u['checked_at'] or 'never').replace('T', ' ')}): {u['count']}"
                  + (f", and {len(u['unmatched'])} for applications not in this list" if u["unmatched"] else "")]
        lines += [f"  {r['name']}: {r['version']} -> {r['available']}" for r in u["unmatched"]]
        if u["error"]:
            lines.append("  The last check failed: " + u["error"])
    if v["changes"]:
        lines += ["", f"Changed in the last {v['changes_days']} days:"]
        lines += ["  " + change_text(e, with_day=True) for e in v["changes"]]
    return "\n".join(lines) + "\n"


def change_text(e: dict, with_day: bool = False) -> str:
    day = e["ts"][:10] + "  " if with_day else ""
    if e["event"] == "updated":
        return f"{day}Updated {e['name']}: {e['old_version'] or '?'} -> {e['new_version'] or '?'}"
    if e["event"] == "installed":
        return f"{day}Installed {e['name']} {e['new_version']}".rstrip()
    return f"{day}Removed {e['name']} {e['old_version']}".rstrip()
