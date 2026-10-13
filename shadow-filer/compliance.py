"""
Compliance: is this PC in the state an insurer's questionnaire or a Cyber Essentials assessment asks for?
One page of evidence for one PC: the five Cyber Essentials control areas, each with checks that are measured
here, plus the things no program on the PC can measure (multi-factor login, backups, a response plan), which
you declare yourself and which are always shown as declared, never as measured.

READ-ONLY and local. One fixed PowerShell call with no arguments reads settings Windows already holds (build
and update dates, antivirus state, drive encryption, lock and AutoPlay settings, local accounts). The rest
comes from what the other modules keep: firewall and open ports (network.py), known flaws and their age
(cve.py), pending updates and the update log (apps.py, remedy.py). Nothing is changed and nothing is sent.
Account names stay on this PC: they are shown on the page, not written to the log.

What it writes, all in the agent's database: one line per day with each check's result (`compliance_history`,
kept 400 days, so "patched within 14 days" can be shown for past months), your declarations and your accepted
exceptions (each with a reason and a date).

Honest limits, stated on the page too:
  - "up to date" for Windows means "an update was installed in the last 35 days": whether a newer build
    exists cannot be known without going online;
  - the age of a flaw counts from the day it was published, the nearest thing the CVE list has to "the day
    the fix came out";
  - 49 of 85 programs on the user's PC match no product in the CVE list and are not judged;
  - the checks follow the published Cyber Essentials control areas, but this is not the scheme's own tool and
    passing here is not a certificate. The thresholds (14 days, 15 minutes) are in THRESHOLDS for checking
    against the current official text.

Measured on the user's PC (12 Oct 2026): see CLAUDE.md.
"""
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import date, datetime, timedelta

CREATE_NO_WINDOW = 0x08000000
THRESHOLDS = {"patch_days": 14, "windows_update_days": 35, "lock_seconds": 900, "signature_days": 7, "high_score": 7.0}
HISTORY_DAYS = 400
CACHE_SECONDS = 300
_lock = threading.Lock()
_cache = {"at": 0.0, "raw": None}

POSTURE_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
function Reg($path, $name) { (Get-ItemProperty -Path $path -Name $name).$name }
function Iso($d) { if ($d) { ([datetime]$d).ToString('yyyy-MM-dd') } else { '' } }
function Power($sub, $set) {
  $o = powercfg /q SCHEME_CURRENT $sub $set
  $l = $o | Where-Object { $_ -match 'Current AC Power Setting Index' } | Select-Object -First 1
  if ($l -match '0x([0-9a-fA-F]+)') { [Convert]::ToInt64($Matches[1], 16) } else { -1 }
}
# The device agent runs as a Windows service (SYSTEM), which has no settings of its own worth judging: there
# the person's settings are those of the account that signed in last, read from that account's part of the
# registry while it is loaded (user_hive says whether it was).
$system = ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -eq 'S-1-5-18')
$usid = ''
if ($system) { $usid = "$(Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\LogonUI' 'LastLoggedOnUserSID')" }
$hkcu = if ($system) { "Registry::HKEY_USERS\$usid" } else { 'HKCU:' }
$hive = if ($system) { [bool]($usid -and (Test-Path -LiteralPath $hkcu)) } else { $true }
$cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$bios = Get-CimInstance Win32_BIOS
$cs = Get-CimInstance Win32_ComputerSystem
$hot = Get-HotFix | Where-Object InstalledOn | Sort-Object InstalledOn -Descending | Select-Object -First 1
$av = @(Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct | ForEach-Object {
  [pscustomobject]@{ name = "$($_.displayName)"; state = [long]$_.productState } })
$mp = Get-MpComputerStatus
$shell = New-Object -ComObject Shell.Application
# Explorer's answer works for an ordinary account. Windows' own BitLocker list needs administrator rights and
# is asked second: a service has no Explorer to ask. Its 0 / 1 / 2 (off, on, cannot tell) become 2 / 1 / 0.
$bl = @{}
foreach ($v in Get-CimInstance -Namespace root/cimv2/Security/MicrosoftVolumeEncryption -ClassName Win32_EncryptableVolume) {
  if ($v.DriveLetter) { $bl["$($v.DriveLetter)"] = [int]$v.ProtectionStatus } }
$drives = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
  $p = [int]$shell.NameSpace($_.DeviceID).Self.ExtendedProperty('System.Volume.BitLockerProtection')
  if ($p -eq 0 -and $bl.ContainsKey("$($_.DeviceID)")) { $p = @(2, 1, 0)[[Math]::Min(2, [Math]::Max(0, $bl["$($_.DeviceID)"]))] }
  [pscustomobject]@{ letter = "$($_.DeviceID)"; size = [long]$_.Size; protection = $p } })
$users = @(Get-LocalUser | ForEach-Object {
  [pscustomobject]@{ name = "$($_.Name)"; enabled = [bool]$_.Enabled; password_required = [bool]$_.PasswordRequired;
    last_logon = (Iso $_.LastLogon); sid = "$($_.SID)" } })
$admins = @(Get-LocalGroupMember -SID 'S-1-5-32-544' | ForEach-Object {
  [pscustomobject]@{ name = "$($_.Name)"; kind = "$($_.ObjectClass)"; sid = "$($_.SID)" } })
$who = if ($system) { '' } else { & "$env:SystemRoot\System32\whoami.exe" /groups }
$desk = "$hkcu\Control Panel\Desktop"
$out = [pscustomobject]@{
  computer = "$env:COMPUTERNAME"; user = "$env:USERNAME"; manufacturer = "$($cs.Manufacturer)"; model = "$($cs.Model)";
  serial = "$($bios.SerialNumber)"; edition = "$($cv.EditionID)"; display_version = "$($cv.DisplayVersion)";
  build = [int]$cv.CurrentBuild; ubr = [int]$cv.UBR;
  last_update = (Iso $hot.InstalledOn); last_update_id = "$($hot.HotFixID)";
  no_auto_update = [int](Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' 'NoAutoUpdate');
  paused_until = "$(Reg 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings' 'PauseUpdatesExpiryTime')";
  antivirus = $av; defender = [pscustomobject]@{ present = [bool]$mp; enabled = [bool]$mp.AntivirusEnabled;
    realtime = [bool]$mp.RealTimeProtectionEnabled; signature_age = if ($mp) { [int]$mp.AntivirusSignatureAge } else { -1 } };
  drives = $drives; users = $users; admins = $admins; admins_read = [bool]$admins;
  me_admin = if ($system) { [bool]($usid -and (@($admins | ForEach-Object { $_.sid }) -contains $usid)) } else { [bool]($who -match 'S-1-5-32-544') };
  as_system = $system; user_hive = $hive;
  screensaver = [pscustomobject]@{ active = "$(Reg $desk 'ScreenSaveActive')"; secure = "$(Reg $desk 'ScreenSaverIsSecure')";
    timeout = "$(Reg $desk 'ScreenSaveTimeOut')" };
  inactivity = [int](Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'InactivityTimeoutSecs');
  display_off = (Power 'SUB_VIDEO' 'VIDEOIDLE'); sleep_after = (Power 'SUB_SLEEP' 'STANDBYIDLE'); lock_on_wake = (Power 'SUB_NONE' 'CONSOLELOCK');
  autoplay_off = [int](Reg "$hkcu\Software\Microsoft\Windows\CurrentVersion\Explorer\AutoplayHandlers" 'DisableAutoplay');
  autorun_policy = [int](Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer' 'NoDriveTypeAutoRun');
  browser_policy = [pscustomobject]@{
    chrome_default = "$(Reg 'HKLM:\SOFTWARE\Policies\Google\Update' 'UpdateDefault')";
    chrome_period = "$(Reg 'HKLM:\SOFTWARE\Policies\Google\Update' 'AutoUpdateCheckPeriodMinutes')";
    edge_default = "$(Reg 'HKLM:\SOFTWARE\Policies\Microsoft\EdgeUpdate' 'UpdateDefault')";
    firefox_off = "$(Reg 'HKLM:\SOFTWARE\Policies\Mozilla\Firefox' 'DisableAppUpdate')" };
  update_services = @(Get-CimInstance Win32_Service | Where-Object { $_.Name -match '^(gupdate|GoogleUpdater|edgeupdate|MozillaMaintenance)' } | ForEach-Object {
    [pscustomobject]@{ name = "$($_.Name)"; start = "$($_.StartMode)" } }) }
$json = ConvertTo-Json -InputObject $out -Compress -Depth 5
'JSON:' + [regex]::Replace($json, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
"""


def read_posture() -> dict | None:
    if os.name != "nt":
        return None
    root = os.environ.get("SystemRoot", r"C:\Windows")
    ps = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    try:
        r = subprocess.run([ps if os.path.exists(ps) else "powershell.exe", "-NoProfile", "-NonInteractive",
                            "-Command", POSTURE_PS], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, creationflags=CREATE_NO_WINDOW)
        line = next((x for x in r.stdout.splitlines() if x.startswith("JSON:")), None)
        raw = json.loads(line[5:]) if line else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return raw if isinstance(raw, dict) else None


def _posture(read=read_posture, force: bool = False) -> dict | None:
    with _lock:
        if not force and _cache["raw"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["raw"]
        raw = read()
        if raw is not None:
            _cache.update(at=time.time(), raw=raw)
        return raw


# --------------------------------------------------------------------------- the checks
def _list(v) -> list:
    return v if isinstance(v, list) else [] if v is None else [v]


def _check(cid, title, status, detail, evidence=None, fix=None, to=None) -> dict:
    """status: pass | fail | warn | unknown | info. `to` is the console page where it can be dealt with."""
    return {"id": cid, "title": title, "status": status, "detail": detail, "evidence": evidence or [], "fix": fix, "to": to}


def _days(iso: str | None, today: date) -> int | None:
    try:
        return (today - date.fromisoformat((iso or "")[:10])).days
    except ValueError:
        return None


def serial(s: str | None) -> str:
    """The serial number, unless the maker left a placeholder in the firmware ('Default string')."""
    s = (s or "").strip()
    return "" if re.fullmatch(r"(?i)default string|to be filled by o\.?e\.?m\.?|system serial number|none|n/?a|0+|\.*", s) else s


def windows_name(p: dict) -> str:
    """Windows 11 still calls itself 'Windows 10' in the registry; the build number tells them apart."""
    gen = "Windows 11" if (p.get("build") or 0) >= 22000 else "Windows 10" if (p.get("build") or 0) >= 10240 else "Windows"
    return " ".join(x for x in (gen, p.get("edition") or "", p.get("display_version") or "") if x)


def firewall_checks(net: dict | None) -> list:
    if not net or not net.get("read_at"):
        return [_check("fw.on", "Windows Firewall is on for every profile", "unknown", "The network has not been read yet.", to="/network")]
    off = [f["name"] for f in net["firewall"] if not f.get("enabled")]
    other = net.get("other_firewalls") or []
    out = [_check("fw.on", "Windows Firewall is on for every profile",
                  "pass" if not off else "warn" if other else "fail",
                  "On for Domain, Private and Public." if not off else
                  f"Off for {', '.join(off)}." + (f" {', '.join(other)} is registered as the firewall instead." if other else
                                                 " No other firewall is registered with Windows."),
                  [f"{f['name']}: {'on' if f.get('enabled') else 'OFF'}, incoming {str(f.get('inbound') or '?').lower()}" for f in net["firewall"]],
                  None if not off else "Network > Exposure > Turn on.", "/network")]
    allow_all = [f["name"] for f in net["firewall"] if f.get("enabled") and str(f.get("inbound") or "").lower() == "allow"]
    out.append(_check("fw.default", "Incoming connections are blocked unless a rule allows them",
                      "unknown" if off and len(off) == len(net["firewall"]) else "fail" if allow_all else "pass",
                      "Cannot be judged while the firewall is off." if off and len(off) == len(net["firewall"]) else
                      f"The {', '.join(allow_all)} profile lets every incoming connection through." if allow_all else
                      "Each profile that is on blocks incoming connections by default.", to="/network"))
    ports = [e for e in net["listening"] if e["reach"] == "network" and not e["windows"] and e["proto"] == "TCP"]
    names = sorted({e["process"] for e in ports if e["process"]})
    out.append(_check("fw.ports", "Programs that accept connections from the network are known and wanted",
                      "info" if ports else "pass",
                      f"{len(ports)} TCP port{'s' if len(ports) != 1 else ''} opened by {len(names)} program{'s' if len(names) != 1 else ''} "
                      "that are not part of Windows. Each should be one you want reachable." if ports else
                      "No program outside Windows accepts connections from the network.",
                      [f"{e['process']}: TCP {e['port']}" for e in ports[:30]], to="/network"))
    ru = net.get("rules")
    if ru is None:
        out.append(_check("fw.rules", "Every rule that lets connections in is for a program you know", "unknown",
                          "The firewall rules could not be read.", to="/network"))
    else:
        progs, wide = ru["programs"], ru["wide_open"]
        gone = [g["program"] for g in progs if g["missing"]]

        def line(g):
            ports = "any port" if g["any_port"] else "port " + ", ".join(g["ports"]) + (f" and {g['more_ports']} more" if g["more_ports"] else "")
            return (f"{g['program']}: {ports}; {'all profiles' if 'all' in g['profiles'] else ', '.join(g['profiles'])}; "
                    f"{'from any address' if g['any_address'] else 'from listed addresses only'}" + (" (program no longer there)" if g["missing"] else ""))
        out.append(_check("fw.rules", "Every rule that lets connections in is for a program you know",
                          "fail" if wide else "warn" if gone else "info" if progs else "pass",
                          (f"{len(wide)} rule{'s let' if len(wide) != 1 else ' lets'} any program in on any port: {', '.join(w['name'] for w in wide[:4])}. " if wide else "")
                          + (f"{len(gone)} rule set{'s are' if len(gone) != 1 else ' is'} left over from programs that are no longer on this PC. " if gone else "")
                          + f"{ru['total']} rules let connections in: {ru['windows']} are Windows' own, the rest cover {len(progs)} "
                            f"program{'s' if len(progs) != 1 else ''}. Each should be one you approve of.",
                          [f"ANY PROGRAM, ANY PORT: {w['name']}" for w in wide] + [line(g) for g in progs[:40]],
                          "Windows Security > Firewall > Advanced settings > Inbound Rules: delete what you do not need."
                          if wide or gone else None, "/network"))
    shares = [s for s in net["shares"] if not s["builtin"] and not s["printer"]]
    out.append(_check("fw.shares", "No folders are shared from this PC without a reason",
                      "warn" if shares else "pass",
                      f"{len(shares)} folder{'s are' if len(shares) != 1 else ' is'} shared." if shares else "No folders are shared.",
                      [s["name"] for s in shares], to="/network"))
    return out


def configuration_checks(p: dict) -> list:
    t = THRESHOLDS["lock_seconds"]
    ss = p.get("screensaver") or {}
    try:
        ss_time = int(ss.get("timeout") or 0)
    except ValueError:
        ss_time = 0
    ways = []
    if 0 < (p.get("inactivity") or 0) <= t:
        ways.append(f"Windows locks after {p['inactivity'] // 60} minutes without input (policy)")
    if ss.get("active") == "1" and ss.get("secure") == "1" and 0 < ss_time <= t:
        ways.append(f"a screen saver that asks for the password starts after {ss_time // 60} minutes")
    idle = min([x for x in (p.get("display_off"), p.get("sleep_after")) if isinstance(x, int) and x > 0] or [0])
    if 0 < idle <= t and p.get("lock_on_wake") == 1:
        ways.append(f"the screen goes off or the PC sleeps after {idle // 60} minutes and asks to sign in on waking")
    out = [_check("cfg.lock", "The PC locks by itself when left alone",
                  "pass" if ways else "warn",
                  ("Found: " + "; ".join(ways) + ".") if ways else
                  f"No automatic lock within {t // 60} minutes was found (no locking screen saver, no inactivity limit, "
                  "and the screen is not set to go off and ask to sign in). Windows Hello's dynamic lock is not visible here.",
                  fix=None if ways else "Settings > Accounts > Sign-in options, and Settings > System > Power > Screen and sleep.")]
    auto_off = p.get("autoplay_off") == 1 or (p.get("autorun_policy") or 0) >= 0x91
    out.append(_check("cfg.autoplay", "AutoPlay is off, so a plugged-in drive runs nothing by itself",
                      "pass" if auto_off else "fail",
                      "AutoPlay is off." if auto_off else "AutoPlay is on for removable drives.",
                      fix=None if auto_off else "Settings > Bluetooth & devices > AutoPlay: switch it off."))
    users = _list(p.get("users"))
    guest = [u for u in users if u.get("enabled") and (str(u.get("sid") or "").endswith("-501") or (u.get("name") or "").lower() == "guest")]
    out.append(_check("cfg.guest", "The Guest account is disabled", "fail" if guest else "pass" if users else "unknown",
                      "The Guest account is enabled." if guest else "Disabled." if users else "The local accounts could not be read."))
    nopw = [u["name"] for u in users if u.get("enabled") and not u.get("password_required")]
    out.append(_check("cfg.password", "Every account that can sign in needs a password",
                      "fail" if nopw else "pass" if users else "unknown",
                      f"{len(nopw)} enabled account{'s do' if len(nopw) != 1 else ' does'} not require a password. "
                      "It may still have one; Windows just does not insist." if nopw else
                      "Every enabled account requires a password." if users else "The local accounts could not be read.",
                      nopw, None if not nopw else "In an administrator terminal: net user <name> /passwordreq:yes"))
    stale = [u["name"] for u in users if u.get("enabled") and not u.get("last_logon")]
    if stale:
        out.append(_check("cfg.unused", "No enabled accounts that nobody uses", "warn",
                          f"{len(stale)} enabled account{'s have' if len(stale) != 1 else ' has'} never signed in.", stale))
    drives = _list(p.get("drives"))
    plain = [d["letter"] for d in drives if d.get("protection") not in (1, 3, 5)]
    out.append(_check("cfg.encryption", "Drives are encrypted (BitLocker)",
                      "unknown" if not drives else "fail" if plain else "pass",
                      "The drives could not be read." if not drives else
                      f"Not encrypted: {', '.join(plain)}. A lost or stolen PC gives up its files." if plain else
                      f"Encrypted: {', '.join(d['letter'] for d in drives)}.",
                      [f"{d['letter']} {'encrypted' if d.get('protection') in (1, 3, 5) else 'not encrypted'}" for d in drives],
                      None if not plain else "Settings > Privacy & security > Device encryption, or Manage BitLocker. "
                                             "Asked for by insurers; not one of the five Cyber Essentials controls."))
    return out


def browser_checks(p: dict, appsv: dict | None) -> dict | None:
    """Do the installed browsers update themselves? A browser is the program most exposed to the internet."""
    if not appsv:
        return None
    names = " | ".join(a["name"].lower() for a in appsv.get("apps", []))
    pol, svc = p.get("browser_policy") or {}, _list(p.get("update_services"))
    off = lambda rx: (lambda s: bool(s) and all((x.get("start") or "").lower() == "disabled" for x in s))(
        [x for x in svc if re.match(rx, x.get("name") or "", re.I)])
    found, bad, doubt = [], [], []
    if "google chrome" in names:
        found.append("Google Chrome")
        if pol.get("chrome_default") == "0" or pol.get("chrome_period") == "0":
            bad.append("Google Chrome: updates are switched off by policy")
        elif off(r"gupdate|GoogleUpdater"):
            doubt.append("Google Chrome: its update service is disabled")
    if "microsoft edge" in names:
        found.append("Microsoft Edge")
        if pol.get("edge_default") == "0":
            bad.append("Microsoft Edge: updates are switched off by policy")
        elif off(r"edgeupdate"):
            doubt.append("Microsoft Edge: its update service is disabled")
    if "firefox" in names:
        found.append("Firefox")
        if pol.get("firefox_off") == "1":
            bad.append("Firefox: updates are switched off by policy")
    if not found:
        return None
    return _check("upd.browsers", "Browsers update themselves", "fail" if bad else "warn" if doubt else "pass",
                  (f"{len(bad) + len(doubt)} of {len(found)} installed browsers will not update by itself." if bad or doubt else
                   f"Automatic updates are not switched off for {', '.join(found)}."), bad + doubt,
                  "Remove the policy, or set the update service back to automatic." if bad or doubt else None)


def update_checks(p: dict, vul: dict | None, appsv: dict | None, today: date, cfg: dict | None = None) -> list:
    out = []
    build = p.get("build") or 0
    win = {"state": "unknown", "line": None, "until": None}
    if cfg is not None and build:
        import eol
        win = eol.windows(cfg, build, p.get("display_version") or "", p.get("edition") or "", today)
    if win["state"] == "unknown":           # no local end-of-life list, or it does not know this release
        ended = build and build <= 22000    # Windows 10 (ended 14 Oct 2025) and Windows 11 21H2
        win = {"state": "ended" if ended else "unlisted", "line": None, "until": None}
    name = f"{windows_name(p)} (build {build}.{p.get('ubr') or 0})"
    out.append(_check("upd.supported", "Windows is a version that still gets security updates",
                      "unknown" if not build else "fail" if win["state"] == "ended" else "warn" if win["state"] == "soon" else "pass",
                      "The Windows version could not be read." if not build else
                      f"{name} stopped getting security updates" + (f" on {win['until']}" if win["until"] else "") + ", unless extended support was bought."
                      if win["state"] == "ended" else
                      f"{name} gets security updates until {win['until']}: less than {90} days from now." if win["state"] == "soon" else
                      f"{name} gets security updates until {win['until']}." if win["until"] else
                      f"{name}. Not known to be out of support.",
                      fix="Upgrade Windows." if win["state"] in ("ended", "soon") else None))
    age = _days(p.get("last_update"), today)
    lim = THRESHOLDS["windows_update_days"]
    out.append(_check("upd.windows", f"Windows installed an update in the last {lim} days",
                      "unknown" if age is None else "pass" if 0 <= age <= lim else "fail",
                      "The date of the last update could not be read." if age is None else
                      f"Last update {p.get('last_update_id') or ''} on {p['last_update']}, {age} days ago. "
                      "Whether a newer one exists is not checked (that would go online).",
                      fix=None if age is not None and age <= lim else "Settings > Windows Update > Check for updates."))
    off, paused = p.get("no_auto_update") == 1, bool(p.get("paused_until"))
    out.append(_check("upd.automatic", "Windows installs updates by itself",
                      "fail" if off else "warn" if paused else "pass",
                      "Automatic updates are switched off by policy." if off else
                      f"Updates are paused until {str(p.get('paused_until'))[:10]}." if paused else
                      "Automatic updates are not switched off or paused."))
    if not vul or not vul.get("scanned_at"):
        out.append(_check("upd.flaws", f"No high or critical flaw older than {THRESHOLDS['patch_days']} days in installed programs",
                          "unknown", "The vulnerability check is off or has not run. Switch it on in Settings > Security.", to="/security"))
    else:
        old, rows = [], []
        for a in vul.get("apps", []):
            hit = [x for x in a["cves"] if (x.get("score") or 0) >= THRESHOLDS["high_score"]
                   and (_days(x.get("published"), today) or 0) > THRESHOLDS["patch_days"]]
            if hit:
                old.append(a["name"])
                worst = max(_days(x.get("published"), today) or 0 for x in hit)
                rows.append(f"{a['name']} {a.get('judged_version') or ''}: {len(hit)} high or critical, oldest {worst} days"
                            + (f", fix: update to {(a.get('update') or {}).get('to')}" if (a.get("update") or {}).get("to") and not (a.get("update") or {}).get("blocked") else ""))
        kev = sum(1 for a in vul.get("apps", []) for x in a["cves"] if x.get("kev"))
        out.append(_check("upd.flaws", f"No high or critical flaw older than {THRESHOLDS['patch_days']} days in installed programs",
                          "fail" if old else "pass",
                          (f"{len(old)} program{'s have' if len(old) != 1 else ' has'} high or critical flaws published more than "
                           f"{THRESHOLDS['patch_days']} days ago" + (f"; {kev} of the flaws {'is' if kev == 1 else 'are'} being used in real attacks." if kev else ".")) if old else
                          f"None among the {vul.get('recognised', 0)} programs that could be compared.",
                          rows, "Security > Programs: Update, or the fix version shown." if old else None, "/security"))
        out.append(_check("upd.coverage", "Every installed program can be compared with the list of known flaws", "info",
                          f"{vul.get('recognised', 0)} of {vul.get('installed', 0)} programs match a product in the CVE list. "
                          "The others are not judged: unknown, not safe.", to="/security"))
    if cfg is not None and appsv:
        import eol
        st = eol.status(cfg)
        if not st["products"]:
            out.append(_check("upd.unsupported", "Installed programs are versions that still get security updates", "unknown",
                              "The end-of-life list has not been downloaded. It comes with the vulnerability check (Settings > Security).", to="/security"))
        else:
            judged = [x for x in eol.match(cfg, [a for a in appsv.get("apps", []) if a.get("kind") == "desktop"], today) if x["product"]]
            ended = [x for x in judged if x["state"] == "ended"]
            soon = [x for x in judged if x["state"] == "soon"]
            row = lambda x, verb: (f"{x['name']}: the {x['line']} line {verb} {x['until'] or '(no date given)'}"
                                   + (f"; newest in that line is {x['latest']}" if x.get("latest") and x["state"] != "ended" else ""))
            out.append(_check("upd.unsupported", "Installed programs are versions that still get security updates",
                              "fail" if ended else "warn" if soon else "pass",
                              (f"{len(ended)} program{'s are' if len(ended) != 1 else ' is'} a release line that no longer gets security updates. " if ended else "")
                              + (f"{len(soon)} more lose{'s' if len(soon) == 1 else ''} support within 90 days. " if soon else "")
                              + f"{len(judged)} of {sum(1 for a in appsv.get('apps', []) if a.get('kind') == 'desktop')} programs are in the "
                                "end-of-life list; the others are not judged.",
                              [row(x, "ended on") for x in ended] + [row(x, "ends on") for x in soon],
                              "Move to a supported release line of the program." if ended or soon else None, "/library"))
    b = browser_checks(p, appsv)
    if b:
        out.append(b)
    if appsv and appsv.get("updates", {}).get("enabled"):
        n = appsv["updates"]["count"]
        out.append(_check("upd.pending", "Installed programs are on their newest version", "warn" if n else "pass",
                          f"{n} program{'s have' if n != 1 else ' has'} a newer version available." if n else
                          "winget lists no newer version for any installed program.",
                          [f"{a['name']}: {a['version']} -> {a['available']}" for a in appsv["apps"] if a.get("available")][:40],
                          "Library > Applications > Updates." if n else None, "/library"))
    else:
        out.append(_check("upd.pending", "Installed programs are on their newest version", "unknown",
                          "The check for newer versions is off. Switch it on in Settings > Library.", to="/library"))
    return out


def access_checks(p: dict) -> list:
    admins, users = _list(p.get("admins")), _list(p.get("users"))
    me = p.get("user") or "your account"
    out = [_check("acc.daily", "The account used every day is not an administrator",
                  "fail" if p.get("me_admin") else "pass",
                  f"{me} is a member of the Administrators group. Anything that runs as you can ask for full control of the PC "
                  "with one click on a prompt." if p.get("me_admin") else f"{me} is a standard account.",
                  fix="Create a separate administrator account and make the everyday one a standard user "
                      "(Settings > Accounts > Other users)." if p.get("me_admin") else None)]
    if p.get("admins_read"):
        people = [a["name"] for a in admins if (a.get("kind") or "").lower() == "user"]
        on = {u["name"].lower() for u in users if u.get("enabled")}
        active = [n for n in people if n.split("\\")[-1].lower() in on or "\\" in n and n.split("\\")[0].upper() != (p.get("computer") or "").upper()]
        out.append(_check("acc.admins", "Few accounts have administrator rights", "warn" if len(active) > 2 else "pass",
                          f"{len(active)} enabled account{'s are' if len(active) != 1 else ' is'} in the Administrators group"
                          + (f" ({len(people) - len(active)} more {'is' if len(people) - len(active) == 1 else 'are'} disabled)."
                             if len(people) > len(active) else "."), active))
    else:
        out.append(_check("acc.admins", "Few accounts have administrator rights", "unknown",
                          "The Administrators group could not be read."))
    return out


def malware_checks(p: dict) -> list:
    av, d = _list(p.get("antivirus")), p.get("defender") or {}
    # productState: byte 2 = on (0x10) or off; byte 3 = signatures up to date (0x00) or not (0x10)
    on = [a["name"] for a in av if (int(a.get("state") or 0) >> 12) & 0xF == 1]
    stale = [a["name"] for a in av if (int(a.get("state") or 0) >> 4) & 0xF != 0]
    out = [_check("mal.present", "Antivirus protection is installed and switched on",
                  "pass" if on else "fail" if av else "unknown",
                  f"On: {', '.join(on)}." if on else
                  f"Installed but switched off: {', '.join(a['name'] for a in av)}." if av else
                  "Windows did not report an antivirus product (Security Center is not available on server editions).",
                  [f"{a['name']}: {'on' if a['name'] in on else 'off'}" for a in av],
                  None if on else "Windows Security > Virus & threat protection.")]
    if d.get("present"):
        out.append(_check("mal.realtime", "Files are checked as they are opened (real-time protection)",
                          "pass" if d.get("realtime") else "warn" if on and "Windows Defender" not in on else "fail",
                          "Microsoft Defender's real-time protection is on." if d.get("realtime") else
                          "Microsoft Defender's real-time protection is off" + ("; another antivirus product is on." if on and "Windows Defender" not in on else ".")))
        age = d.get("signature_age", -1)
        lim = THRESHOLDS["signature_days"]
        out.append(_check("mal.signatures", f"Antivirus definitions are less than {lim} days old",
                          "unknown" if age is None or age < 0 else "pass" if age <= lim and not stale else "fail",
                          "The age of the definitions could not be read." if age is None or age < 0 else
                          f"Microsoft Defender's definitions are {age} day{'s' if age != 1 else ''} old."
                          + (f" Windows reports out-of-date definitions for {', '.join(stale)}." if stale else "")))
    elif av:
        out.append(_check("mal.signatures", "Antivirus definitions are up to date", "fail" if stale else "pass",
                          f"Windows reports out-of-date definitions for {', '.join(stale)}." if stale else "Windows reports them as up to date."))
    return out


CONTROLS = (("firewalls", "Firewalls", "Every device is protected by a firewall, and only what is needed is reachable."),
            ("configuration", "Secure configuration", "The PC is set up to reduce what an attacker can use: no open accounts, a lock, nothing that runs by itself."),
            ("updates", "Security update management", "Windows and installed programs are supported and patched promptly."),
            ("access", "User access control", "Administrator rights are used only when needed."),
            ("malware", "Malware protection", "Antivirus is on and current."))

DECLARED = (("mfa", "Multi-factor login is on for email and cloud services", "Asked by insurers and by Cyber Essentials for cloud services."),
            ("backups", "Important files are backed up, with one copy offline or unchangeable", "Asked by insurers."),
            ("backup_test", "A restore from backup was tested in the last 12 months", "Asked by insurers."),
            ("incident_plan", "There is a written plan for what to do after a break-in", "Asked by insurers."),
            ("training", "Everyone who uses the PC has had security awareness training", "Asked by insurers."),
            ("router", "The router's default password was changed and its firmware is current", "Cyber Essentials: boundary firewall."),
            ("admin_separate", "Administrator accounts are not used for email or browsing", "Cyber Essentials: user access control."))


# --------------------------------------------------------------------------- what you declared and accepted
def _conn(db_path):
    c = sqlite3.connect(str(db_path), timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE IF NOT EXISTS compliance_history (day TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS compliance_declared (key TEXT PRIMARY KEY, answer TEXT, note TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS compliance_accepted (check_id TEXT PRIMARY KEY, reason TEXT, ts TEXT);
    """)
    return c


def declare(db_path, key: str, answer: str | None, note: str = "") -> bool:
    """answer: 'yes' | 'no' | 'na' | None (clears it). Only the questions in DECLARED exist."""
    if key not in {k for k, _, _ in DECLARED} or answer not in ("yes", "no", "na", None):
        return False
    c = _conn(db_path)
    try:
        if answer is None:
            c.execute("DELETE FROM compliance_declared WHERE key=?", (key,))
        else:
            c.execute("INSERT OR REPLACE INTO compliance_declared VALUES (?,?,?,?)",
                      (key, answer, (note or "").strip()[:500], datetime.now().isoformat(timespec="seconds")))
        c.commit()
    finally:
        c.close()
    return True


def accept(db_path, check_id: str, reason: str | None) -> bool:
    """Record that a failing check is accepted, with why. reason None or empty withdraws it."""
    if not re.fullmatch(r"[a-z]{2,4}\.[a-z_]{2,20}", check_id or ""):
        return False
    c = _conn(db_path)
    try:
        if not (reason or "").strip():
            c.execute("DELETE FROM compliance_accepted WHERE check_id=?", (check_id,))
        else:
            c.execute("INSERT OR REPLACE INTO compliance_accepted VALUES (?,?,?)",
                      (check_id, reason.strip()[:500], datetime.now().isoformat(timespec="seconds")))
        c.commit()
    finally:
        c.close()
    return True


# --------------------------------------------------------------------------- putting it together
def _roll(checks: list) -> str:
    s = [c["status"] for c in checks if not c.get("accepted")]
    return "fail" if "fail" in s else "warn" if "warn" in s else "unknown" if "unknown" in s else "pass"


def assess(cfg: dict, raw: dict, net: dict | None, vul: dict | None, appsv: dict | None, today: date | None = None) -> dict:
    """Everything the page shows, from the PC's settings and what the other modules found."""
    today = today or date.today()
    c = _conn(cfg["database"])
    try:
        accepted = {r["check_id"]: {"reason": r["reason"], "ts": r["ts"]} for r in c.execute("SELECT * FROM compliance_accepted")}
        said = {r["key"]: dict(r) for r in c.execute("SELECT * FROM compliance_declared")}
    finally:
        c.close()
    groups = {"firewalls": firewall_checks(net), "configuration": configuration_checks(raw),
              "updates": update_checks(raw, vul, appsv, today, cfg), "access": access_checks(raw), "malware": malware_checks(raw)}
    controls = []
    for key, title, about in CONTROLS:
        checks = groups[key]
        for ch in checks:
            a = accepted.get(ch["id"])
            ch["accepted"] = a if a and ch["status"] in ("fail", "warn") else None
        controls.append({"key": key, "title": title, "about": about, "status": _roll(checks), "checks": checks,
                         "counts": {s: sum(1 for ch in checks if ch["status"] == s and not ch["accepted"]) for s in ("pass", "fail", "warn", "unknown")},
                         "accepted": sum(1 for ch in checks if ch["accepted"])})
    declared = [{"key": k, "title": t, "about": why, "answer": (said.get(k) or {}).get("answer"),
                 "note": (said.get(k) or {}).get("note") or "", "ts": (said.get(k) or {}).get("ts")} for k, t, why in DECLARED]
    every = [ch for g in controls for ch in g["checks"]]
    out = {"assessed_at": datetime.now().isoformat(timespec="seconds"),
           "device": {"name": raw.get("computer") or "", "manufacturer": raw.get("manufacturer") or "", "model": raw.get("model") or "",
                      "serial": serial(raw.get("serial")), "windows": windows_name(raw),
                      "build": f"{raw.get('build') or 0}.{raw.get('ubr') or 0}", "user": raw.get("user") or ""},
           "controls": controls, "declared": declared, "thresholds": THRESHOLDS,
           "summary": {"controls_passing": sum(1 for g in controls if g["status"] == "pass"), "controls": len(controls),
                       "fail": sum(1 for ch in every if ch["status"] == "fail" and not ch["accepted"]),
                       "warn": sum(1 for ch in every if ch["status"] == "warn" and not ch["accepted"]),
                       "unknown": sum(1 for ch in every if ch["status"] == "unknown"),
                       "passed": sum(1 for ch in every if ch["status"] == "pass"),
                       "accepted": sum(1 for ch in every if ch["accepted"]),
                       "declared_yes": sum(1 for d in declared if d["answer"] == "yes"),
                       "declared_no": sum(1 for d in declared if d["answer"] == "no"),
                       "declared_open": sum(1 for d in declared if not d["answer"])}}
    return out


def record(cfg: dict, v: dict, today: date | None = None) -> None:
    """Keep today's result per check, so a past month can be shown. One line a day; the last one of the day wins."""
    day = (today or date.today()).isoformat()
    line = {"controls": {g["key"]: g["status"] for g in v["controls"]},
            "checks": {ch["id"]: ("accepted" if ch["accepted"] else ch["status"]) for g in v["controls"] for ch in g["checks"]},
            "summary": {k: v["summary"][k] for k in ("controls_passing", "fail", "warn", "unknown")}}
    c = _conn(cfg["database"])
    try:
        c.execute("INSERT OR REPLACE INTO compliance_history VALUES (?,?)", (day, json.dumps(line)))
        c.execute("DELETE FROM compliance_history WHERE day < ?", (((today or date.today()) - timedelta(days=HISTORY_DAYS)).isoformat(),))
        c.commit()
    finally:
        c.close()


def history(cfg: dict, days: int = 90, today: date | None = None) -> list:
    since = ((today or date.today()) - timedelta(days=days)).isoformat()
    c = _conn(cfg["database"])
    try:
        rows = c.execute("SELECT day, value FROM compliance_history WHERE day >= ? ORDER BY day", (since,)).fetchall()
    finally:
        c.close()
    out = []
    for r in rows:
        try:
            out.append({"day": r["day"], **json.loads(r["value"])})
        except ValueError:
            pass
    return out


def view(cfg: dict, force: bool = False, read=read_posture, log=None, today: date | None = None) -> dict:
    """Assess now and return the page's data. Reads Windows at most every five minutes unless forced."""
    import library
    s = library.settings(cfg)
    raw = _posture(read, force)
    if raw is None:
        return {"assessed_at": None, "error": "Windows could not be asked about this PC's settings.", "controls": [], "declared": [],
                "summary": {}, "history": [], "patch_log": [], "device": {}, "thresholds": THRESHOLDS}
    import network
    net = network.view(force=force, log=log) if force else (network.peek() or network.view(log=log))
    vul = appsv = None
    if s["enabled"] and s["applications"]:
        import apps
        appsv = apps.with_updates(cfg, apps.view(cfg), s["check_updates"], s["update_hours"])
        if s["vulnerabilities"]:
            import cve
            vul = cve.view(cfg)
    v = assess(cfg, raw, net, vul, appsv, today)
    record(cfg, v, today)
    import remedy
    v["history"] = history(cfg, 90, today)
    v["patch_log"] = [h for h in remedy.history(cfg["database"], 100)]
    v["text"] = as_text(v)
    if log:      # counts only: no account names in the log
        m = v["summary"]
        log.info("compliance: %d of %d controls pass, %d failing check(s), %d to look at, %d unknown, %d accepted",
                 m["controls_passing"], m["controls"], m["fail"], m["warn"], m["unknown"], m["accepted"])
    return v


def brief(cfg: dict) -> dict | None:
    """Today's line from the history, for the dashboard: no read of Windows, None before the first assessment."""
    rows = history(cfg, 1)
    return rows[-1] if rows else None


MARK = {"pass": "PASS", "fail": "FAIL", "warn": "LOOK", "unknown": " ?  ", "info": "note"}


def as_text(v: dict) -> str:
    """The same evidence as plain text, to paste into a questionnaire or send to a broker."""
    d, m = v["device"], v["summary"]
    lines = [f"Security posture of {d.get('name')} ({d.get('manufacturer')} {d.get('model')}, serial {d.get('serial') or '-'})",
             f"{d.get('windows')}, build {d.get('build')}. Assessed {v['assessed_at'].replace('T', ' ')} by Shadow Filer on the PC itself.",
             f"{m['controls_passing']} of {m['controls']} control areas pass; {m['fail']} failing checks, {m['warn']} to look at, "
             f"{m['unknown']} could not be checked, {m['accepted']} accepted with a reason.", ""]
    for g in v["controls"]:
        lines.append(f"{g['title'].upper()}: {MARK[g['status']].strip()}")
        for ch in g["checks"]:
            lines.append(f"  [{MARK[ch['status']]}] {ch['title']}")
            lines.append(f"         {ch['detail']}")
            for e in ch["evidence"][:12]:
                lines.append(f"           - {e}")
            if ch["accepted"]:
                lines.append(f"         Accepted on {ch['accepted']['ts'][:10]}: {ch['accepted']['reason']}")
        lines.append("")
    lines.append("DECLARED BY THE OWNER (not measured)")
    for q in v["declared"]:
        a = {"yes": "Yes", "no": "No", "na": "Does not apply", None: "Not answered"}[q["answer"]]
        lines.append(f"  {a:<15} {q['title']}" + (f" ({q['note']})" if q["note"] else "") + (f" [{q['ts'][:10]}]" if q["ts"] else ""))
    if v.get("patch_log"):
        lines += ["", "UPDATES AND CHANGES MADE FROM THE CONSOLE"]
        for h in v["patch_log"][:40]:
            lines.append(f"  {h['ts'][:16].replace('T', ' ')}  {'ok    ' if h['ok'] else 'FAILED'}  {h['message']}")
    lines += ["", "Measured on the PC by Shadow Filer. This follows the Cyber Essentials control areas but is not a certificate."]
    return "\n".join(lines) + "\n"
