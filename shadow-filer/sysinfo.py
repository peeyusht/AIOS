"""
System information for Shadow Filer: hardware, OS, storage, GPUs and what Ollama is doing.

Read-only. Uses only the standard library plus `requests` (already a dependency):
- Windows hardware/OS/storage: one PowerShell call to Get-CimInstance / Get-PhysicalDisk.
- NVIDIA GPUs: nvidia-smi (real VRAM; Windows' own "Adapter RAM" field is wrong above 4 GB).
- Ollama: /api/version and /api/ps (shows how much of a loaded model sits in GPU memory).
- CUDA_VISIBLE_DEVICES: from this process and from the user/system environment in the registry,
  because Ollama reads it when *Ollama* starts, not when this agent starts.

Nothing here takes user input into a command line; every command is fixed.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path, PureWindowsPath

import requests

IS_WIN = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # pythonw must not flash consoles

# Get-PhysicalDisk returns enum numbers when serialised.
MEDIA = {"0": "Unspecified", "3": "HDD", "4": "SSD", "5": "SCM"}
BUS = {"1": "SCSI", "2": "ATAPI", "3": "ATA", "4": "1394", "5": "SSA", "6": "Fibre Channel",
       "7": "USB", "8": "RAID", "9": "iSCSI", "10": "SAS", "11": "SATA", "12": "SD", "13": "MMC",
       "15": "File-backed virtual", "16": "Storage Spaces", "17": "NVMe"}

PS_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
function D($d) { if ($d) { $d.ToString('s') } else { $null } }
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$bios = Get-CimInstance Win32_BIOS
$bb = Get-CimInstance Win32_BaseBoard
$o = [ordered]@{
  os = [ordered]@{ caption = $os.Caption; version = $os.Version; build = $os.BuildNumber
        arch = $os.OSArchitecture; installed = (D $os.InstallDate); last_boot = (D $os.LastBootUpTime)
        total_kb = $os.TotalVisibleMemorySize; free_kb = $os.FreePhysicalMemory }
  computer = [ordered]@{ name = $cs.Name; manufacturer = $cs.Manufacturer; model = $cs.Model
        board = ("{0} {1}" -f $bb.Manufacturer, $bb.Product).Trim()
        bios = ("{0} {1}" -f $bios.Manufacturer, $bios.SMBIOSBIOSVersion).Trim(); bios_date = (D $bios.ReleaseDate) }
  cpu = @(Get-CimInstance Win32_Processor | ForEach-Object { [ordered]@{ name = $_.Name.Trim()
        cores = $_.NumberOfCores; threads = $_.NumberOfLogicalProcessors; mhz = $_.MaxClockSpeed } })
  ram = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object { [ordered]@{ slot = $_.DeviceLocator
        bytes = $_.Capacity; mhz = $_.ConfiguredClockSpeed; rated_mhz = $_.Speed
        maker = $_.Manufacturer; part = "$($_.PartNumber)".Trim() } })
  video = @(Get-CimInstance Win32_VideoController | ForEach-Object { [ordered]@{ name = $_.Name
        driver = $_.DriverVersion; w = $_.CurrentHorizontalResolution; h = $_.CurrentVerticalResolution
        hz = $_.CurrentRefreshRate } })
  disks = @(Get-PhysicalDisk | ForEach-Object { [ordered]@{ number = "$($_.DeviceId)"; model = $_.FriendlyName
        media = "$($_.MediaType)"; bus = "$($_.BusType)"; bytes = $_.Size; health = "$($_.HealthStatus)" } })
  partitions = @(Get-Partition | Where-Object { $_.DriveLetter } | ForEach-Object { [ordered]@{
        letter = "$($_.DriveLetter):"; disk = "$($_.DiskNumber)" } })
  volumes = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object { [ordered]@{
        letter = $_.DeviceID; label = $_.VolumeName; fs = $_.FileSystem; bytes = $_.Size; free = $_.FreeSpace } })
}
$o | ConvertTo-Json -Depth 5 -Compress
"""


def _run(args: list[str], timeout: int = 30) -> str | None:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _list(x) -> list:
    """PowerShell turns one-item arrays into a bare object; undo that."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _int(x) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- sources
def windows_cim() -> dict:
    out = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-Command", PS_SCRIPT], timeout=45)
    if not out:
        return {}
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


def _nvidia_smi_path() -> str | None:
    p = shutil.which("nvidia-smi")
    if p:
        return p
    if IS_WIN:
        for c in (r"C:\Windows\System32\nvidia-smi.exe",
                  r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
            if Path(c).exists():
                return c
    return None


def nvidia() -> dict:
    exe = _nvidia_smi_path()
    if not exe:
        return {"available": False, "gpus": [], "processes": []}
    fields = ["index", "uuid", "name", "memory.total", "memory.used", "driver_version",
              "temperature.gpu", "utilization.gpu", "pci.bus_id", "compute_cap"]
    out = _run([exe, "--query-gpu=" + ",".join(fields), "--format=csv,noheader,nounits"])
    if out is None:  # older drivers don't know compute_cap
        fields = fields[:-1]
        out = _run([exe, "--query-gpu=" + ",".join(fields), "--format=csv,noheader,nounits"])
    gpus = []
    for line in (out or "").strip().splitlines():
        v = dict(zip(fields, [c.strip() for c in line.split(",")]))
        gpus.append({
            "index": _int(v.get("index")), "uuid": v.get("uuid"), "name": v.get("name"),
            "vram_bytes": (_int(v.get("memory.total")) or 0) * 1024 * 1024 or None,
            "vram_used_bytes": (_int(v.get("memory.used")) or 0) * 1024 * 1024,
            "driver": v.get("driver_version"), "temp_c": _int(v.get("temperature.gpu")),
            "util_pct": _int(v.get("utilization.gpu")), "pci": v.get("pci.bus_id"),
            "compute_cap": v.get("compute_cap"),
        })
    procs = []
    out = _run([exe, "--query-compute-apps=gpu_uuid,pid,process_name", "--format=csv,noheader"])
    for line in (out or "").strip().splitlines():
        parts = [c.strip() for c in line.split(",")]
        if len(parts) >= 3:
            name = PureWindowsPath(parts[2]).name
            # On Windows every app that draws on screen is listed; only the model runner matters here.
            if "llama" in name.lower():
                procs.append({"gpu_uuid": parts[0], "pid": _int(parts[1]), "name": name})
    return {"available": bool(gpus), "gpus": gpus, "processes": procs}


def env_var_everywhere(name: str) -> dict:
    """Value in this process, and in the persistent user/machine environment (Windows)."""
    res = {"this_process": os.environ.get(name), "user": None, "machine": None}
    if IS_WIN:
        import winreg
        for key, hive, path in (("user", winreg.HKEY_CURRENT_USER, r"Environment"),
                                ("machine", winreg.HKEY_LOCAL_MACHINE,
                                 r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(hive, path) as k:
                    res[key] = str(winreg.QueryValueEx(k, name)[0])
            except OSError:
                pass
    return res


def secure_boot() -> bool | None:
    if not IS_WIN:
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\SecureBoot\State") as k:
            return bool(winreg.QueryValueEx(k, "UEFISecureBootEnabled")[0])
    except OSError:
        return None


def ollama(url: str) -> dict:
    base = url.rstrip("/")
    res = {"url": url, "reachable": False, "version": None, "loaded": []}
    try:
        res["version"] = requests.get(base + "/api/version", timeout=3).json().get("version")
        res["reachable"] = True
        for m in requests.get(base + "/api/ps", timeout=3).json().get("models", []):
            size, vram = m.get("size") or 0, m.get("size_vram") or 0
            res["loaded"].append({
                "name": m.get("name"), "bytes": size, "vram_bytes": vram,
                "gpu_pct": round(100 * vram / size) if size else None,
                "params": (m.get("details") or {}).get("parameter_size"),
                "quant": (m.get("details") or {}).get("quantization_level"),
                "context": m.get("context_length"), "expires": m.get("expires_at"),
            })
    except (requests.RequestException, ValueError):
        pass
    return res


# --------------------------------------------------------------------------- assemble
def collect(cfg: dict | None = None) -> dict:
    t0 = time.time()
    cim = windows_cim() if IS_WIN else {}
    nv = nvidia()
    url = (cfg or {}).get("ollama", {}).get("url", "http://localhost:11434")

    os_ = cim.get("os") or {}
    info: dict = {
        "collected": datetime.now().isoformat(timespec="seconds"),
        "os": {
            "name": os_.get("caption") or f"{platform.system()} {platform.release()}",
            "version": os_.get("version") or platform.version(),
            "build": os_.get("build"), "arch": os_.get("arch") or platform.machine(),
            "installed": os_.get("installed"), "last_boot": os_.get("last_boot"),
        },
        "computer": cim.get("computer") or {"name": platform.node()},
        "secure_boot": secure_boot(),
    }

    cpus = _list(cim.get("cpu"))
    info["cpu"] = cpus[0] if cpus else {"name": platform.processor() or None,
                                        "threads": os.cpu_count()}
    if len(cpus) > 1:
        info["cpu"]["sockets"] = len(cpus)

    modules = _list(cim.get("ram"))
    total = (_int(os_.get("total_kb")) or 0) * 1024 or None
    info["memory"] = {
        "installed_bytes": sum(_int(m.get("bytes")) or 0 for m in modules) or total,
        "usable_bytes": total,
        "free_bytes": (_int(os_.get("free_kb")) or 0) * 1024 or None,
        "modules": modules,
    }

    # GPUs: nvidia-smi is authoritative for NVIDIA; Windows adds the display each one drives.
    video = _list(cim.get("video"))
    gpus = []
    for g in nv["gpus"]:
        v = next((x for x in video if (x.get("name") or "").strip() == g["name"]), {})
        gpus.append({**g, "display": _display(v)})
    for v in video:
        if not any((v.get("name") or "").strip() == g["name"] for g in nv["gpus"]):
            gpus.append({"name": v.get("name"), "driver": v.get("driver"), "display": _display(v),
                         "vram_bytes": None, "note": "VRAM not reported by Windows reliably"})
    info["gpus"] = gpus
    info["gpu_processes"] = nv["processes"]

    letters: dict[str, list] = {}
    for p in _list(cim.get("partitions")):
        letters.setdefault(str(p.get("disk")), []).append(p.get("letter"))
    info["disks"] = [{
        "number": d.get("number"), "model": d.get("model"),
        "media": MEDIA.get(str(d.get("media")), d.get("media")),
        "bus": BUS.get(str(d.get("bus")), d.get("bus")),
        "bytes": _int(d.get("bytes")), "health": d.get("health"),
        "letters": sorted(letters.get(str(d.get("number")), [])),
    } for d in sorted(_list(cim.get("disks")), key=lambda d: _int(d.get("number")) or 0)]
    disk_of = {l: d for d in info["disks"] for l in d["letters"]}
    info["volumes"] = [{
        **v, "bytes": _int(v.get("bytes")), "free": _int(v.get("free")),
        "disk": (disk_of.get(v.get("letter")) or {}).get("model"),
        "media": (disk_of.get(v.get("letter")) or {}).get("media"),
    } for v in _list(cim.get("volumes"))]
    if not IS_WIN:  # minimal fallback so the command still works elsewhere
        u = shutil.disk_usage("/")
        info["volumes"] = [{"letter": "/", "bytes": u.total, "free": u.free}]

    info["ollama"] = ollama(url)
    info["cuda_visible_devices"] = env_var_everywhere("CUDA_VISIBLE_DEVICES")
    here = Path(__file__).resolve().parent
    info["agent"] = {"folder": str(here), "drive": here.drive or "/",
                     "python": f"{platform.python_version()} ({sys.executable})"}
    info["notes"] = notes(info)
    info["seconds"] = round(time.time() - t0, 1)
    return info


def _display(v: dict) -> str | None:
    if not v or not v.get("w"):
        return None
    return f"{v['w']} x {v['h']} @ {v.get('hz')} Hz"


def notes(i: dict) -> list[dict]:
    """Facts worth acting on. Level: warn | info."""
    out = []
    for m in i["ollama"]["loaded"]:
        if m["gpu_pct"] is not None and m["gpu_pct"] < 100:
            where = "entirely on the CPU" if m["gpu_pct"] == 0 else f"only {m['gpu_pct']}% in GPU memory"
            out.append({"level": "warn", "text": f"Ollama has {m['name']} loaded {where}; "
                        "the rest runs on the CPU, which is much slower."})
    nvidia_gpus = [g for g in i["gpus"] if g.get("uuid")]
    cvd = i["cuda_visible_devices"]
    ollama_sees = cvd["user"] or cvd["machine"]
    if len(nvidia_gpus) > 1 and not ollama_sees:
        out.append({"level": "warn", "text": "More than one NVIDIA GPU and no persistent CUDA_VISIBLE_DEVICES, "
                    "so Ollama may split a model across both cards."})
    if ollama_sees and ollama_sees.replace(",", "").strip().isdigit() and len(nvidia_gpus) > 1:
        out.append({"level": "info", "text": f"CUDA_VISIBLE_DEVICES={ollama_sees} uses a number. CUDA may order GPUs "
                    "differently from nvidia-smi; a GPU UUID (shown under Graphics) is unambiguous."})
    for v in i["volumes"]:
        if v.get("bytes") and v.get("free") is not None and v["free"] / v["bytes"] < 0.10:
            out.append({"level": "warn", "text": f"{v['letter']} has less than 10% free space."})
    sysvol = next((v for v in i["volumes"] if v.get("letter") == "C:"), None)
    if sysvol and sysvol.get("media") == "HDD":
        out.append({"level": "info", "text": f"Windows (C:) is on a hard disk ({sysvol.get('disk')}); "
                    "an SSD in this machine would be noticeably faster."})
    if i["secure_boot"] is False:
        out.append({"level": "info", "text": "Secure Boot is off."})
    if not i["ollama"]["reachable"]:
        out.append({"level": "warn", "text": f"Ollama is not reachable at {i['ollama']['url']}."})
    return out


# --------------------------------------------------------------------------- caching + text
_cache: dict = {"at": 0.0, "data": None}
_lock = threading.Lock()


def cached(cfg: dict, max_age: int = 300, force: bool = False) -> dict:
    """Hardware barely changes, and a collection takes a few seconds; one at a time."""
    with _lock:
        if force or not _cache["data"] or time.time() - _cache["at"] > max_age:
            _cache["data"], _cache["at"] = collect(cfg), time.time()
        return _cache["data"]


def gb(n) -> str:
    if not n:
        return "-"
    return f"{n / 1024**3:.1f} GB" if n < 1024**4 else f"{n / 1024**4:.2f} TB"


def summary_line(i: dict) -> str:
    gpus = ", ".join(f"{g['name']} {gb(g.get('vram_bytes'))}" for g in i["gpus"]) or "no GPU"
    return (f"{i['os']['name']} build {i['os'].get('build') or '?'} | {i['cpu'].get('name')} "
            f"({i['cpu'].get('threads')} threads) | RAM {gb(i['memory']['installed_bytes'])} | {gpus}")


def as_text(i: dict) -> str:
    L = []
    c, m, o = i["computer"], i["memory"], i["os"]
    L.append(f"System information  ({i['collected']}, {i['seconds']}s)\n")
    L.append(f"Computer   {c.get('name')}  {c.get('manufacturer') or ''} {c.get('model') or ''}".rstrip())
    if c.get("board"):
        L.append(f"Board      {c['board']}, BIOS {c.get('bios')} ({(c.get('bios_date') or '')[:10]})")
    L.append(f"OS         {o['name']}  {o['version']} build {o.get('build')}  {o.get('arch')}")
    if o.get("last_boot"):
        L.append(f"Last boot  {o['last_boot'].replace('T', ' ')}")
    sb = i["secure_boot"]
    L.append(f"SecureBoot {'on' if sb else 'off' if sb is False else 'unknown'}")
    cpu = i["cpu"]
    L.append(f"CPU        {cpu.get('name')}  {cpu.get('cores')} cores / {cpu.get('threads')} threads")
    L.append(f"Memory     {gb(m['installed_bytes'])} installed, {gb(m['free_bytes'])} free"
             + (f"  ({len(m['modules'])} modules)" if m["modules"] else ""))
    L.append("\nGraphics")
    for g in i["gpus"]:
        bits = [f"VRAM {gb(g.get('vram_bytes'))}"]
        if g.get("vram_used_bytes") is not None and g.get("uuid"):
            bits.append(f"used {gb(g['vram_used_bytes'])}")
        if g.get("compute_cap"):
            bits.append(f"compute {g['compute_cap']}")
        if g.get("driver"):
            bits.append(f"driver {g['driver']}")
        if g.get("display"):
            bits.append(f"display {g['display']}")
        idx = f"[{g['index']}] " if g.get("index") is not None else ""
        L.append(f"  {idx}{g['name']}: " + ", ".join(bits))
        if g.get("uuid"):
            L.append(f"      {g['uuid']}")
    for p in i["gpu_processes"]:
        L.append(f"  using a GPU: {p['name']} (pid {p['pid']}) on {p['gpu_uuid']}")
    L.append("\nStorage")
    for d in i["disks"]:
        L.append(f"  Disk {d['number']}: {d['model']}  {gb(d['bytes'])}  {d['media']}/{d['bus']}  "
                 f"{d['health']}  {' '.join(d['letters'])}")
    for v in i["volumes"]:
        L.append(f"  {v['letter']:<3} {v.get('label') or '':<14} {gb(v.get('free'))} free of {gb(v.get('bytes'))}"
                 + (f"  on {v['disk']}" if v.get("disk") else ""))
    ol = i["ollama"]
    L.append(f"\nOllama     {'v' + str(ol['version']) if ol['reachable'] else 'not reachable'} at {ol['url']}")
    for lm in ol["loaded"]:
        L.append(f"  loaded {lm['name']}: {gb(lm['bytes'])}, {lm['gpu_pct']}% in GPU memory")
    if ol["reachable"] and not ol["loaded"]:
        L.append("  no model loaded right now (Ollama unloads idle models after ~5 min)")
    cv = i["cuda_visible_devices"]
    L.append(f"CUDA_VISIBLE_DEVICES  user={cv['user'] or '-'}  machine={cv['machine'] or '-'}  "
             f"this process={cv['this_process'] or '-'}")
    L.append(f"Agent      {i['agent']['folder']}  (Python {i['agent']['python']})")
    if i["notes"]:
        L.append("\nNotes")
        for n in i["notes"]:
            L.append(f"  [{n['level'].upper()}] {n['text']}")
    return "\n".join(L)
