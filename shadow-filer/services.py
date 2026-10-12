"""
Windows services that are not part of Windows: what runs in the background on this PC, from which program,
as which account, and whether it listens for connections from the network. READ-ONLY: nothing is started,
stopped or changed.

What is read, by one fixed PowerShell call with no arguments: the service list (Win32_Service), the name,
company and version each service's program states about itself, and which ports each running service's
process listens on. A service whose program lives in the Windows folder is left out (those are Windows' own
and are patched by Windows Update, not judged here). Nothing goes online.

Measured on the user's PC (12 Oct 2026, 1.3 s): 313 services, 151 running; 40 outside the Windows folder
(24 running), 24 of them not from Microsoft. 41 TCP ports are listened on, 24 reachable from the network.
"""
import json
import os
import re
import subprocess

CREATE_NO_WINDOW = 0x08000000
LOCAL_ONLY = {"127.0.0.1", "::1"}

SERVICES_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ports = @{}
foreach ($l in Get-NetTCPConnection -State Listen) {
  $k = [int]$l.OwningProcess
  if (-not $ports.ContainsKey($k)) { $ports[$k] = @() }
  $ports[$k] += "$($l.LocalAddress)|$($l.LocalPort)"
}
$out = foreach ($s in Get-CimInstance Win32_Service) {
  $p = "$($s.PathName)"
  $exe = if ($p -match '^"([^"]+)"') { $Matches[1] } elseif ($p -match '^(.+?\.exe)') { $Matches[1] } else { '' }
  if (-not $exe -or $exe -like "$env:SystemRoot\*") { continue }
  $v = $null
  if (Test-Path -LiteralPath $exe) { $v = (Get-Item -LiteralPath $exe).VersionInfo }
  [pscustomobject]@{ name = "$($s.Name)"; display = "$($s.DisplayName)"; state = "$($s.State)";
    start = "$($s.StartMode)"; account = "$($s.StartName)"; exe = $exe; pid = [int]$s.ProcessId;
    company = "$($v.CompanyName)".Trim(); product = "$($v.ProductName)".Trim();
    version = "$($v.ProductVersion)".Trim(); listens = @($ports[[int]$s.ProcessId]) }
}
$json = ConvertTo-Json -InputObject @($out) -Compress -Depth 4
'JSON:' + [regex]::Replace($json, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
"""


def read_services() -> list | None:
    """Raw third-party services. None when Windows could not be asked."""
    if os.name != "nt":
        return None
    root = os.environ.get("SystemRoot", r"C:\Windows")
    ps = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    try:
        r = subprocess.run([ps if os.path.exists(ps) else "powershell.exe", "-NoProfile", "-NonInteractive",
                            "-Command", SERVICES_PS], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180, creationflags=CREATE_NO_WINDOW)
        line = next((x for x in r.stdout.splitlines() if x.startswith("JSON:")), None)
        rows = json.loads(line[5:]) if line else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else None


def _account(a: str) -> str:
    """'LocalSystem' -> 'system' (full control of the PC), service accounts -> 'limited', a person -> 'user'."""
    a = (a or "").lower()
    if a in ("localsystem", "nt authority\\system", ""):
        return "system"
    if "localservice" in a.replace(" ", "") or "networkservice" in a.replace(" ", "") or a.startswith("nt service\\"):
        return "limited"
    return "user"


def tidy(raw: list, apps: list) -> list:
    """One entry per service, with the installed application it belongs to (by install folder, else by the
    product name its program states) and the ports it listens on."""
    import apps as apps_mod
    by_key = {a["key"].split(":", 1)[1]: a for a in apps if a["kind"] == "desktop"}
    folders = sorted(((os.path.normcase(a["location"].rstrip("\\/")) + os.sep, a) for a in apps
                      if a.get("location") and len(a["location"]) > 6), key=lambda x: -len(x[0]))
    out = []
    for s in raw:
        exe = s.get("exe") or ""
        if not s.get("name") or not exe:
            continue
        owner = next((a for f, a in folders if os.path.normcase(exe).startswith(f)), None)
        if not owner and s.get("product"):
            owner = by_key.get(apps_mod.name_key(s["product"], s.get("version") or ""))
        if not owner:       # same first word and the very same version: 'MongoDB Server' and 'MongoDB 7.0.5 ...'
            first = (re.findall(r"[a-z0-9]+", (s.get("display") or "").lower()) or [""])[0]
            mine = apps_mod.version_tuple(s.get("version"))[:3]
            owner = next((a for a in apps if a["kind"] == "desktop" and len(first) >= 4 and len(mine) >= 2
                          and (re.findall(r"[a-z0-9]+", a["name"].lower()) or [""])[0] == first
                          and mine in (apps_mod.version_tuple(a["version"])[:3],
                                       apps_mod.version_tuple((re.search(r"\d+(?:\.\d+)+", a["name"]) or [""])[0])[:3])),
                         None)
        ports = set()
        for p in s.get("listens") or []:
            m = re.fullmatch(r"(.*)\|(\d+)", p or "")
            if m:
                ports.add((int(m.group(2)), m.group(1) not in LOCAL_ONLY))
        merged = {}
        for port, open_ in ports:
            merged[port] = merged.get(port, False) or open_
        m = re.search(r"\d+(?:\.\d+)+", s.get("version") or "")
        out.append({"id": s["name"], "name": s.get("display") or s["name"], "service": s["name"],
                    "running": (s.get("state") or "").lower() == "running",
                    "start": (s.get("start") or "").lower(), "account": _account(s.get("account")),
                    "exe": exe, "publisher": s.get("company") or "", "product": s.get("product") or "",
                    "version": m.group(0) if m else "",
                    "app_id": owner["id"] if owner else None, "app_name": owner["name"] if owner else None,
                    "ports": [{"port": p, "network": o} for p, o in sorted(merged.items())],
                    "exposed": any(merged.values())})
    out.sort(key=lambda x: (not x["exposed"], not x["running"], x["name"].lower()))
    return out
