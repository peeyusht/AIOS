"""
Cleanup recommendations for Shadow Filer.

Looks at your inbox folders (Downloads) and recommends what could be deleted:
  - exact duplicates by CONTENT (names may differ), against the PARA tree and within Downloads
  - leftover partial downloads
  - archives you already extracted
  - old installers and driver packages
  - other old executables and old, unopened files (review only)
  - firmware / VM images are listed as KEEP (hard to download again)

SAFETY: scanning is read-only. Files are deleted only when you mark them Agree on the Cleanup
page and then confirm (Recycle Bin by default; see "deleting" below). Files are opened only to compare
them (when another file has exactly the same size), to read a zip's file list, or to look for an installer
signature in an .exe. Cloud-only files (Google Drive streamed,
OneDrive Files-On-Demand) are never opened, so a scan never triggers downloads.
Documents (PDF, Office, text, keys/certificates) are never recommended because of age alone,
only when an identical copy exists.
"""
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPORT_FILE = BASE / "cleanup_report.json"

DEFAULTS = {
    "scan_hours": 24,        # running agent rescans this often (0 = only when you click Scan)
    "installer_days": 30,    # installers / executables older than this are listed
    "driver_days": 30,       # driver packages older than this are listed
    "stale_days": 180,       # other files: listed for review if older than this AND not opened recently
    "max_depth": 4,          # how deep to look inside subfolders of Downloads
    "hash_max_gb": 8,        # bigger same-size files are compared by sampling only (marked "likely")
    "para_duplicates": True, # also report duplicates inside the PARA tree (information only)
}

# --------------------------------------------------------------------------- file types
PARTIAL_EXT = {".crdownload", ".part", ".partial", ".download", ".opdownload", ".tmp"}
INSTALLER_EXT = {".msi", ".msix", ".msixbundle", ".appx", ".appxbundle", ".msp", ".msu"}
EXE_EXT = {".exe"}
ARCHIVE_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".cab"}
# Vendor firmware, OS and VM images: large but hard to get again (support-portal logins, pulled builds).
KEEP_EXT = {".out", ".bin", ".img", ".iso", ".ova", ".ovf", ".qcow2", ".vmdk", ".vhd", ".vhdx",
            ".vdi", ".pkg", ".deb", ".rpm", ".dmg", ".upd", ".swi", ".spk"}
# Never recommended on age: your work, and secrets you may not be able to recreate.
DOC_EXT = {".pdf", ".doc", ".docx", ".dot", ".dotx", ".xls", ".xlsx", ".xlsm", ".xlsb", ".csv", ".ppt",
           ".pptx", ".potx", ".txt", ".md", ".rtf", ".odt", ".ods", ".odp", ".eml", ".msg", ".pst",
           ".vsd", ".vsdx", ".json", ".xml", ".yaml", ".yml", ".html", ".htm", ".pages", ".key",
           ".numbers", ".epub", ".ps1", ".py", ".bat", ".cmd", ".sh", ".sql", ".conf", ".cfg", ".ini"}
SECRET_EXT = {".pem", ".pfx", ".p12", ".cer", ".crt", ".der", ".p7b", ".ppk", ".kdbx", ".ovpn",
              ".lic", ".license", ".gpg", ".asc", ".jks", ".keystore"}
IGNORE_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}

DRIVER_RX = re.compile(
    r"(driver|drv[_\-. ]|nvidia|geforce|quadro|radeon|adrenalin|amd[_\- ]?(chipset|software|ryzen)|"
    r"chipset|realtek|rtl\d|intel.*(graphics|wireless|wi-?fi|bluetooth|chipset|rst|lan|me[_\- ]|ethernet)|"
    r"bluetooth|wlan|wi-?fi[_\- ]|ethernet|mediatek|qualcomm|broadcom|killer|synaptics)", re.I)
INSTALLER_RX = re.compile(
    r"(setup|install|installer|updater|update|redist|bootstrap|webinst|[_\-. ]x64|[_\-. ]x86|win64|win32|"
    r"amd64|arm64|\bv?\d+\.\d+(\.\d+){0,3}\b)", re.I)
# Strings found inside installer executables made with the common installer builders.
INSTALLER_MARKERS = (b"Nullsoft", b"Inno Setup", b"JR.Inno.Setup", b"InstallShield", b".wixburn",
                     b"WixBundle", b"Setup Factory", b"InstallAware", b"Advanced Installer",
                     b"7zS.sfx", b"SquirrelSetup", b"Wise Installation")
COPY_SUFFIX_RX = re.compile(r"\s*(\(\d+\)|- copy( \(\d+\))?|_copy\d*| copy\d*)$", re.I)

# Windows file attributes
FA_REPARSE = 0x400
FA_OFFLINE = 0x1000
FA_RECALL_ON_OPEN = 0x40000
FA_RECALL_ON_DATA = 0x400000
FA_PINNED_UNPINNED = 0x80000 | 0x100000

LEVELS = ("safe", "likely", "review", "keep", "info")
LEVEL_TEXT = {
    "safe": "Safe to delete",
    "likely": "Probably safe",
    "review": "Review",
    "keep": "Keep / archive",
    "info": "Information",
}


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("cleanup") or {})}


# --------------------------------------------------------------------------- helpers
def full_ext(name: str) -> str:
    n = name.lower()
    for double in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if n.endswith(double):
            return ".tgz"
    return os.path.splitext(n)[1]


def stem_of(name: str) -> str:
    n = name
    for double in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if n.lower().endswith(double):
            return n[: -len(double)]
    return os.path.splitext(n)[0]


def base_stem(name: str) -> str:
    """'report (1).pdf' -> 'report'  (browser re-download suffixes removed)."""
    return COPY_SUFFIX_RX.sub("", stem_of(name)).strip().lower()


def attrs(st) -> int:
    return getattr(st, "st_file_attributes", 0) or 0


def is_cloud_only(st) -> bool:
    """Placeholder files whose content lives in the cloud: opening them downloads them."""
    return bool(attrs(st) & (FA_OFFLINE | FA_RECALL_ON_OPEN | FA_RECALL_ON_DATA))


def added_time(st) -> float:
    """When the file arrived here. Windows creation time (birthtime) is the download time;
    mtime can be older when a browser or an unzip preserves the server's date."""
    b = getattr(st, "st_birthtime", None)
    if b is None and os.name == "nt":
        b = st.st_ctime
    # a file you edited after downloading it counts from the edit
    return max(b, st.st_mtime) if b is not None else st.st_mtime


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else None


def last_access_policy() -> dict:
    """Is NTFS recording 'last accessed' times at all? Only informational: we don't rely on it."""
    if os.name != "nt":
        return {"value": None, "text": "not Windows"}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as k:
            v, _ = winreg.QueryValueEx(k, "NtfsDisableLastAccessUpdate")
    except OSError:
        return {"value": None, "text": "unknown"}
    low = v & 0x3
    text = {0: "user managed, enabled", 1: "user managed, disabled",
            2: "system managed, enabled (Windows still turns it off on volumes over 128 GB)",
            3: "system managed, disabled"}[low]
    return {"value": hex(v), "text": text}


def recent_items() -> dict:
    """Windows' Recent Items: one shortcut per file you opened, named after the file, whose
    modified time is when you last opened it. Matched by name, so it's a hint, not proof."""
    out: dict[str, float] = {}
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return out
    folder = Path(appdata) / "Microsoft" / "Windows" / "Recent"
    try:
        for lnk in folder.glob("*.lnk"):
            try:
                ts = lnk.stat().st_mtime
            except OSError:
                continue
            name = lnk.name[:-4].lower()
            if ts > out.get(name, 0):
                out[name] = ts
    except OSError:
        pass
    return out


def looks_like_installer_exe(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            head = f.read(4 * 1024 * 1024)
            try:
                f.seek(-1024 * 1024, os.SEEK_END)
                tail = f.read()
            except OSError:
                tail = b""
    except OSError:
        return False
    return any(m in head or m in tail for m in INSTALLER_MARKERS)


# --------------------------------------------------------------------------- hashing (cached)
class HashCache:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        self.conn.execute("""CREATE TABLE IF NOT EXISTS cleanup_hash (
            path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, quick TEXT, full TEXT)""")
        self.conn.commit()
        self.lock = threading.Lock()

    def _get(self, path: str, size: int, mtime_ns: int):
        with self.lock:
            r = self.conn.execute("SELECT size, mtime_ns, quick, full FROM cleanup_hash WHERE path = ?",
                                  (path,)).fetchone()
        if r and r[0] == size and r[1] == mtime_ns:
            return r[2], r[3]
        return None, None

    def _put(self, path, size, mtime_ns, quick, full):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO cleanup_hash VALUES (?, ?, ?, ?, ?)",
                              (path, size, mtime_ns, quick, full))
            self.conn.commit()

    def quick(self, f: dict) -> str | None:
        q, full = self._get(f["path"], f["size"], f["mtime_ns"])
        if q:
            return q
        try:
            h = hashlib.sha256(str(f["size"]).encode())
            with open(f["path"], "rb") as fh:
                h.update(fh.read(65536))
                if f["size"] > 131072:
                    fh.seek(-65536, os.SEEK_END)
                    h.update(fh.read(65536))
            q = h.hexdigest()
        except OSError:
            return None
        self._put(f["path"], f["size"], f["mtime_ns"], q, full)
        return q

    def full(self, f: dict) -> str | None:
        q, full = self._get(f["path"], f["size"], f["mtime_ns"])
        if full:
            return full
        try:
            h = hashlib.sha256()
            with open(f["path"], "rb") as fh:
                for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                    h.update(chunk)
            full = h.hexdigest()
        except OSError:
            return None
        self._put(f["path"], f["size"], f["mtime_ns"], q, full)
        return full

    def close(self):
        self.conn.close()


# --------------------------------------------------------------------------- decisions
def _decisions_conn(db_path: Path):
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS cleanup_decision (
        path TEXT PRIMARY KEY, size INTEGER, category TEXT, level TEXT, decision TEXT, ts TEXT)""")
    return conn


def load_decisions(db_path: Path) -> dict:
    conn = _decisions_conn(db_path)
    try:
        return {r["path"]: dict(r) for r in conn.execute("SELECT * FROM cleanup_decision")}
    finally:
        conn.close()


def set_decision(db_path: Path, item: dict, decision: str | None) -> None:
    conn = _decisions_conn(db_path)
    try:
        if decision is None:
            conn.execute("DELETE FROM cleanup_decision WHERE path = ?", (item["path"],))
        else:
            conn.execute("INSERT OR REPLACE INTO cleanup_decision VALUES (?, ?, ?, ?, ?, ?)",
                         (item["path"], item["size"], item["category"], item["level"], decision,
                          datetime.now().isoformat(timespec="seconds")))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- walking
def _walk(root: Path, max_depth: int, source: str, files: list, dirs: list, errors: list,
          stats: dict, record_dirs: bool) -> None:
    """Collect files without following junctions/symlinks. Never opens files."""
    stack = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError as e:
            errors.append(f"cannot list {folder}: {e.strerror or e}")
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if attrs(st) & FA_REPARSE:
                continue
            name = e.name
            if e.is_dir(follow_symlinks=False):
                if name.startswith(".") or name.lower() in ("$recycle.bin", "system volume information"):
                    continue
                if record_dirs and depth == 0:
                    dirs.append({"path": e.path, "name": name, "st": st})
                if max_depth is None or depth + 1 <= max_depth:
                    stack.append((Path(e.path), depth + 1))
                continue
            if name.lower() in IGNORE_NAMES or name.startswith("~$"):
                continue
            stats["files_" + source] += 1
            cloud = is_cloud_only(st)
            if cloud:
                stats["cloud_only_" + source] += 1
            files.append({
                "path": e.path, "name": name, "size": st.st_size, "mtime": st.st_mtime,
                "mtime_ns": st.st_mtime_ns, "added": added_time(st), "source": source, "depth": depth,
                "top": depth == 0, "cloud": cloud,
                "fid": (st.st_dev, st.st_ino) if st.st_ino else None,
            })


def _dir_summary(path: str, max_depth: int = 4) -> dict:
    total, count, inf = 0, 0, 0
    stack = [(path, 0)]
    while stack:
        p, d = stack.pop()
        try:
            for e in os.scandir(p):
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if d < max_depth:
                            stack.append((e.path, d + 1))
                        continue
                    total += e.stat(follow_symlinks=False).st_size
                    count += 1
                    if e.name.lower().endswith((".inf", ".sys", ".cat")):
                        inf += 1
                except OSError:
                    continue
        except OSError:
            continue
    return {"size": total, "files": count, "driver_files": inf}


def verify_extracted(zpath: Path, folder: Path) -> dict | None:
    """Compare a zip's file list (central directory only, nothing decompressed) with the folder.
    Accepts both layouts: members at the folder root, or under one top folder of the same name."""
    import zipfile
    try:
        with zipfile.ZipFile(zpath) as z:
            members = [(i.filename, i.file_size) for i in z.infolist() if not i.is_dir()]
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError):
        return None
    if not members:
        return None

    def missing_under(base: Path, strip: str | None):
        bad, example = 0, None
        for name, size in members:
            rel = name
            if strip:
                if not rel.startswith(strip + "/"):
                    return len(members), name
                rel = rel[len(strip) + 1:]
            try:
                ok = (base / rel).stat().st_size == size
            except OSError:
                ok = False
            if not ok:
                bad += 1
                example = example or name
        return bad, example

    results = [missing_under(folder, None)]
    tops = {m[0].split("/")[0] for m in members}
    if len(tops) == 1 and all("/" in m[0] for m in members):
        top = tops.pop()
        results.append(missing_under(folder, top))           # zip has top dir, folder holds its contents
        results.append(missing_under(folder / top, top))     # extracted as folder/top/...
    bad, example = min(results, key=lambda r: r[0])
    return {"members": len(members), "missing": bad, "complete": bad == 0, "example": example}


# --------------------------------------------------------------------------- the scan
def scan(cfg: dict, progress=None, log=None) -> dict:
    s = settings(cfg)
    t0 = time.time()
    now = time.time()
    say = progress or (lambda msg: None)
    errors: list[str] = []
    stats = defaultdict(int)
    inbox_files: list[dict] = []
    inbox_dirs: list[dict] = []
    para_files: list[dict] = []

    say("Listing Downloads")
    for inbox in cfg["inbox_folders"]:
        if inbox.is_dir():
            _walk(inbox, s["max_depth"], "inbox", inbox_files, inbox_dirs, errors, stats, True)
        else:
            errors.append(f"inbox not found: {inbox}")
    para_root = cfg["para_root"]
    inbox_roots = [str(p).lower().rstrip("\\/") for p in cfg["inbox_folders"]]
    if para_root.is_dir():
        say("Listing PARA tree (names and sizes only)")
        _walk(para_root, None, "para", para_files, [], errors, stats, False)
        # if an inbox lives inside PARA root, don't count those files twice
        para_files = [f for f in para_files
                      if not any(f["path"].lower().startswith(r + os.sep) for r in inbox_roots)]
    else:
        errors.append(f"PARA root not found: {para_root}")

    recent = recent_items()
    items: dict[str, dict] = {}   # path -> recommendation

    def add(f_or_d, category, level, reason, size=None, related=None, caution=None, is_dir=False):
        p = f_or_d["path"]
        prev = items.get(p)
        if prev and LEVELS.index(prev["level"]) <= LEVELS.index(level):
            return  # keep the stronger recommendation already made
        added = f_or_d.get("added") if not is_dir else added_time(f_or_d["st"])
        opened = recent.get(f_or_d["name"].lower())
        items[p] = {
            "path": p, "name": f_or_d["name"], "is_dir": is_dir,
            "mtime_ns": f_or_d["st"].st_mtime_ns if is_dir else f_or_d["mtime_ns"],
            "folder": str(Path(p).parent),
            "size": size if size is not None else f_or_d["size"],
            "category": category, "level": level, "reason": reason,
            "related": related, "caution": caution,
            "added": iso(added), "age_days": int((now - added) / 86400) if added else None,
            "last_opened": iso(opened),
        }

    # ---------------- 1. exact duplicates by content
    say("Finding files with identical sizes")
    cache = HashCache(cfg["database"])
    seen_fid = {}
    candidates = []
    for f in inbox_files + para_files:
        if f["size"] == 0:
            continue
        if f["fid"]:
            if f["fid"] in seen_fid:   # hard link: same file, deleting one frees nothing
                continue
            seen_fid[f["fid"]] = f["path"]
        candidates.append(f)
    by_size = defaultdict(list)
    for f in candidates:
        by_size[f["size"]].append(f)
    groups = [g for g in by_size.values() if len(g) > 1 and (
        any(f["source"] == "inbox" for f in g) or s["para_duplicates"])]
    hash_max = s["hash_max_gb"] * 1024 ** 3
    dup_clusters = []      # (confirmed: bool, [files])
    unconfirmed_cloud = 0
    hashed = 0
    for gi, g in enumerate(groups):
        if gi % 50 == 0:
            say(f"Comparing contents: group {gi + 1} of {len(groups)}")
        local = [f for f in g if not f["cloud"] and now - f["mtime"] > 600]  # skip in-progress downloads
        cloud = [f for f in g if f["cloud"]]
        if cloud and any(f["source"] == "inbox" for f in local):
            unconfirmed_cloud += 1
        if len(local) < 2:
            continue
        if not any(f["source"] == "inbox" for f in local) and g[0]["size"] < 100 * 1024:
            continue  # PARA-only duplicates: ignore small files (templates, icons)
        by_quick = defaultdict(list)
        for f in local:
            q = cache.quick(f)
            if q:
                by_quick[q].append(f)
        for qg in by_quick.values():
            if len(qg) < 2:
                continue
            if g[0]["size"] > hash_max:
                dup_clusters.append((False, qg))
                continue
            by_full = defaultdict(list)
            for f in qg:
                h = cache.full(f)
                hashed += 1
                if h:
                    by_full[h].append(f)
            for fg in by_full.values():
                if len(fg) > 1:
                    dup_clusters.append((True, fg))
    cache.close()

    para_dup_groups = []
    for confirmed, cl in dup_clusters:
        para = [f for f in cl if f["source"] == "para"]
        inbox = [f for f in cl if f["source"] == "inbox"]
        lvl = "safe" if confirmed else "likely"
        how = "identical content" if confirmed else "same size and same sampled content (file too big to hash fully)"
        if para:
            keeper = sorted(para, key=lambda f: (f["depth"], f["path"]))[0]
            for f in inbox:
                add(f, "duplicate_of_filed", lvl,
                    f"Already filed: {how} as the copy in your PARA tree.", related=keeper["path"])
        elif len(inbox) > 1:
            keeper = sorted(inbox, key=lambda f: (bool(COPY_SUFFIX_RX.search(stem_of(f["name"]))),
                                                  f["depth"], f["added"], f["name"]))[0]
            for f in inbox:
                if f is not keeper:
                    add(f, "duplicate_in_downloads", lvl,
                        f"Extra copy: {how} as another file in Downloads, which is kept.",
                        related=keeper["path"])
        if len(para) > 1 and s["para_duplicates"]:
            para_dup_groups.append({"size": para[0]["size"], "confirmed": confirmed,
                                    "paths": sorted(f["path"] for f in para)})

    # ---------------- 2. type-based recommendations (top level of Downloads)
    say("Classifying files by type and age")
    top_dir_names = {}
    for d in inbox_dirs:
        top_dir_names.setdefault(str(Path(d["path"]).parent).lower(), set()).add(d["name"].lower())
    for f in inbox_files:
        if not f["top"]:
            continue
        name, ext = f["name"], full_ext(f["name"])
        age = (now - f["added"]) / 86400
        opened = recent.get(name.lower())
        opened_days = (now - opened) / 86400 if opened else None
        stem = stem_of(name)
        if ext in PARTIAL_EXT:
            if age >= 1 and (now - f["mtime"]) / 86400 >= 1:
                add(f, "partial_download", "safe",
                    "Unfinished or temporary download, untouched for over a day.")
            continue
        if ext in SECRET_EXT or ext in DOC_EXT:
            continue  # only duplicates (above) can flag these
        if ext in KEEP_EXT:
            add(f, "firmware_or_image", "keep",
                "Firmware, OS or VM image. Large, but often hard to download again "
                "(portal logins, builds get pulled). Move to an archive instead of deleting.")
            continue
        if ext in ARCHIVE_EXT:
            siblings = top_dir_names.get(str(Path(f["path"]).parent).lower(), set())
            match = next((d for d in siblings if d in (stem.lower(), base_stem(name))), None)
            if match:
                dpath = str(Path(f["path"]).parent / match)
                info = _dir_summary(dpath, 6)
                if info["files"]:
                    chk = verify_extracted(Path(f["path"]), Path(dpath)) if ext == ".zip" and not f["cloud"] else None
                    if chk and chk["complete"]:
                        add(f, "archive_extracted", "safe" if age >= 7 else "likely",
                            f"Already extracted: all {chk['members']} file(s) in this zip are in the folder "
                            f"\"{match}\" next to it, with the same sizes.", related=dpath)
                    elif chk:
                        add(f, "archive_extracted", "review",
                            f"Partly extracted: {chk['missing']} of {chk['members']} file(s) in this zip are "
                            f"missing or a different size in \"{match}\" (e.g. {chk['example']}). Keep the zip "
                            "unless you removed those on purpose.", related=dpath)
                    else:
                        add(f, "archive_extracted", "likely",
                            f"A folder \"{match}\" next to it holds {info['files']} file(s) "
                            f"({human(info['size'])}); contents not verified for this archive type.",
                            related=dpath)
                    continue
            if DRIVER_RX.search(stem) and age >= s["driver_days"]:
                add(f, "driver_package", "likely", "Driver package archive.",
                    caution="Keep it if this is the only copy for old hardware.")
            elif age >= s["stale_days"] and (opened_days is None or opened_days > s["stale_days"]):
                add(f, "old_unopened", "review",
                    f"Archive added {int(age)} days ago and not opened since, as far as Windows records.")
            continue
        if ext in EXE_EXT or ext in INSTALLER_EXT:
            if DRIVER_RX.search(stem):
                if age >= s["driver_days"]:
                    add(f, "driver_package", "likely",
                        f"Driver installer, {int(age)} days old. The vendor site has current versions.",
                        caution="Keep it if this is the only copy for old or discontinued hardware.")
                continue
            if age < s["installer_days"]:
                continue
            installer = ext in INSTALLER_EXT or bool(INSTALLER_RX.search(stem)) or (
                not f["cloud"] and looks_like_installer_exe(Path(f["path"])))
            if installer:
                add(f, "installer", "likely",
                    f"Installer, {int(age)} days old. Once installed it isn't needed, and it can be downloaded again.")
            else:
                add(f, "executable", "review",
                    f"Program, {int(age)} days old. It may be a portable tool you run from here; "
                    "deleting it removes the tool.")
            continue
        # everything else: media, images, misc
        if age >= s["stale_days"] and (opened_days is None or opened_days > s["stale_days"]):
            add(f, "old_unopened", "review",
                f"Added {int(age)} days ago and not opened since, as far as Windows records.")

    for d in inbox_dirs:
        age = (now - added_time(d["st"])) / 86400
        info = _dir_summary(d["path"])
        if info["driver_files"] and age >= s["driver_days"]:
            add(d, "driver_package", "likely",
                f"Extracted driver package folder ({info['driver_files']} driver file(s), "
                f"{info['files']} file(s) in total).",
                size=info["size"], is_dir=True,
                caution="Keep it if this is the only copy for old hardware.")

    # ---------------- 3. summary
    out = sorted(items.values(), key=lambda r: (LEVELS.index(r["level"]), -r["size"]))
    by_level = {lv: {"count": 0, "bytes": 0} for lv in LEVELS}
    by_cat = defaultdict(lambda: {"count": 0, "bytes": 0})
    for r in out:
        by_level[r["level"]]["count"] += 1
        by_level[r["level"]]["bytes"] += r["size"]
        by_cat[r["category"]]["count"] += 1
        by_cat[r["category"]]["bytes"] += r["size"]
    report = {
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0, 1),
        "inbox": [str(p) for p in cfg["inbox_folders"]],
        "para_root": str(para_root),
        "settings": s,
        "counts": {
            "inbox_files": stats["files_inbox"], "para_files": stats["files_para"],
            "cloud_only_para": stats["cloud_only_para"], "cloud_only_inbox": stats["cloud_only_inbox"],
            "files_hashed": hashed, "unconfirmed_cloud_groups": unconfirmed_cloud,
        },
        "by_level": by_level,
        "by_category": dict(by_cat),
        "last_access": last_access_policy(),
        "recent_items_found": len(recent),
        "errors": errors[:50],
        "items": out,
        "para_duplicates": sorted(para_dup_groups, key=lambda g: -g["size"])[:200],
    }
    tmp = REPORT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    os.replace(tmp, REPORT_FILE)
    if log:
        log.info("CLEANUP scan: %d recommendation(s) in %.0fs; safe %d (%s), probably safe %d (%s), "
                 "review %d, keep %d", len(out), report["seconds"],
                 by_level["safe"]["count"], human(by_level["safe"]["bytes"]),
                 by_level["likely"]["count"], human(by_level["likely"]["bytes"]),
                 by_level["review"]["count"], by_level["keep"]["count"])
    return report


def load_report() -> dict | None:
    try:
        return json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def with_decisions(report: dict | None, db_path: Path) -> dict | None:
    """Attach your earlier agree/disagree/keep choices. A choice is dropped if the file changed size."""
    if not report:
        return report
    dec = load_decisions(db_path)
    for it in report["items"]:
        d = dec.get(it["path"])
        it["decision"] = d["decision"] if d and d["size"] == it["size"] else None
    return report


def to_csv(report: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["level", "category", "name", "size", "age_days", "last_opened", "reason", "caution",
            "related", "path", "decision"]
    w.writerow(cols)
    for it in report["items"]:
        w.writerow([LEVEL_TEXT.get(it["level"], it["level"]) if c == "level" else it.get(c) for c in cols])
    return buf.getvalue()


def as_text(report: dict) -> str:
    lines = [f"Cleanup scan {report['scanned_at']} ({report['seconds']}s)",
             f"Looked at {report['counts']['inbox_files']} file(s) in Downloads and "
             f"{report['counts']['para_files']} in {report['para_root']}"]
    if report["counts"]["cloud_only_para"]:
        lines.append(f"  {report['counts']['cloud_only_para']} PARA file(s) are cloud-only and were not opened")
    for lv in LEVELS:
        b = report["by_level"][lv]
        if b["count"]:
            lines.append(f"  {LEVEL_TEXT[lv]:<16} {b['count']:>5} file(s)  {human(b['bytes']):>10}")
    lines.append("")
    for it in report["items"]:
        lines.append(f"[{LEVEL_TEXT[it['level']]}] {human(it['size']):>9}  {it['path']}")
        lines.append(f"      {it['reason']}" + (f"  Same as: {it['related']}" if it.get("related") else ""))
        if it.get("caution"):
            lines.append(f"      Caution: {it['caution']}")
    for e in report["errors"]:
        lines.append(f"warning: {e}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- background runner
class Runner:
    """One scan at a time, in a background thread, with progress for the UI."""
    lock = threading.Lock()
    state = {"running": False, "started": None, "progress": None, "error": None, "finished": None}

    @classmethod
    def start(cls, cfg: dict, log=None) -> bool:
        with cls.lock:
            if cls.state["running"] or cls.state.get("running_delete"):
                return False
            cls.state.update(running=True, started=datetime.now().isoformat(timespec="seconds"),
                             progress="Starting", error=None)

        def work():
            try:
                scan(cfg, progress=lambda m: cls.state.update(progress=m), log=log)
            except Exception as e:  # never take the agent down
                cls.state["error"] = str(e)
                if log:
                    log.error("cleanup scan failed: %s", e)
            finally:
                cls.state.update(running=False, progress=None,
                                 finished=datetime.now().isoformat(timespec="seconds"))

        threading.Thread(target=work, daemon=True, name="cleanup-scan").start()
        return True

    @classmethod
    def due(cls, cfg: dict) -> bool:
        hours = settings(cfg)["scan_hours"]
        if not hours or cls.state["running"] or cls.state.get("running_delete"):
            return False
        rep_time = REPORT_FILE.stat().st_mtime if REPORT_FILE.exists() else 0
        return time.time() - rep_time > hours * 3600


# =========================================================================== deleting
# Only files you marked "Agree" in the last scan, inside your inbox folders.
# Every file is checked again right before it is deleted (still there, unchanged, and the reason
# still holds); anything that fails a check is skipped, not deleted.
# Default: Recycle Bin. Files too big for the Recycle Bin are never deleted permanently unless you
# confirm that separately for those exact files.

FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO = 0x4, 0x10, 0x40
FOF_NOERRORUI, FOF_WANTNUKEWARNING = 0x400, 0x4000
NEVER_DELETE = {"keep"}  # levels that can't be deleted from the UI at all


def _inside(path: str, roots: list) -> bool:
    try:
        p = Path(path).resolve()
    except OSError:
        return False
    for r in roots:
        try:
            p.relative_to(Path(r).resolve())
            if p != Path(r).resolve():
                return True
        except (ValueError, OSError):
            continue
    return False


def recycle_bin_limit(path: str) -> dict:
    """Max Recycle Bin size for the drive holding `path`, from the per-volume setting
    (HKCU\\...\\Explorer\\BitBucket\\Volume\\{GUID}). Files bigger than this are not recycled:
    Windows deletes them permanently instead, so we must know before asking it."""
    if os.name != "nt":
        return {"known": False, "nuke": False, "max_bytes": None, "drive": None}
    import ctypes
    import winreg
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    buf = ctypes.create_unicode_buffer(260)
    if not k32.GetVolumePathNameW(wintypes.LPCWSTR(path), buf, 260):
        return {"known": False, "nuke": False, "max_bytes": None, "drive": None}
    mount = buf.value
    vbuf = ctypes.create_unicode_buffer(64)
    guid = None
    if k32.GetVolumeNameForVolumeMountPointW(wintypes.LPCWSTR(mount), vbuf, 64):
        m = re.search(r"\{[0-9A-Fa-f-]+\}", vbuf.value)
        guid = m.group(0) if m else None
    total = ctypes.c_ulonglong(0)
    k32.GetDiskFreeSpaceExW(wintypes.LPCWSTR(mount), None, ctypes.byref(total), None)
    out = {"known": False, "nuke": False, "max_bytes": None, "drive": mount,
           "volume_bytes": total.value}
    if guid:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                rf"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume\{guid}") as k:
                try:
                    out["max_bytes"] = int(winreg.QueryValueEx(k, "MaxCapacity")[0]) * 1024 * 1024
                    out["known"] = True
                except OSError:
                    pass
                try:
                    out["nuke"] = bool(winreg.QueryValueEx(k, "NukeOnDelete")[0])
                except OSError:
                    pass
        except OSError:
            pass
    if out["max_bytes"] is None and total.value:
        out["max_bytes"] = int(total.value * 0.05)  # Windows' default is about 5% of the drive
    return out


def _to_recycle_bin(path: str) -> str | None:
    """Returns None on success, or an error text. Uses the same Shell call Explorer uses."""
    if os.name != "nt":
        return "Recycle Bin is only available on Windows"
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    ctypes.windll.ole32.CoInitialize(None)  # the shell may use COM in this worker thread; harmless if already done
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"  # ctypes adds the second NUL
    # WANTNUKEWARNING: if Windows would delete permanently after all, it asks instead of doing it
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
    before = recycle_bin_count(path)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        return f"Windows refused (code {rc:#x}); the file may be open in another program"
    if op.fAnyOperationsAborted:
        return "cancelled"
    if os.path.exists(path):
        return "still there after the request"
    after = recycle_bin_count(path)
    if before is not None and after is not None and after[0] <= before[0] and after[1] <= before[1]:
        # gone from disk but the bin didn't grow: Windows may have deleted it permanently
        return "UNVERIFIED: removed, but the Recycle Bin did not grow; check the Recycle Bin"
    return None


def recycle_bin_count(path: str):
    """(items, bytes) in the Recycle Bin of the drive holding `path`, or None."""
    if os.name != "nt":
        return None
    import ctypes

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint32), ("i64Size", ctypes.c_int64), ("i64NumItems", ctypes.c_int64)]

    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    drive = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    if ctypes.windll.shell32.SHQueryRecycleBinW(ctypes.c_wchar_p(drive), ctypes.byref(info)) != 0:
        return None
    return info.i64NumItems, info.i64Size


def selftest() -> dict:
    """Prove the Recycle Bin call works on this PC without touching your files: create a small
    file in the agent folder, recycle it, and check it left the disk and the Recycle Bin grew."""
    p = BASE / f"shadow-filer-recycle-test-{datetime.now():%Y%m%d-%H%M%S}.txt"
    p.write_text("Shadow Filer Recycle Bin self-test. Safe to delete or restore.\n", encoding="utf-8")
    before = recycle_bin_count(str(p))
    err = _to_recycle_bin(str(p))
    after = recycle_bin_count(str(p))
    still = p.exists()
    if still:
        try:
            p.unlink()
        except OSError:
            pass
    ok = err is None and not still
    return {"ok": ok, "error": err, "file": p.name, "bin_before": before, "bin_after": after,
            "message": f"Recycle Bin works: {p.name} is now in the Recycle Bin." if ok else
                       f"Recycle Bin test failed: {err or 'file still there'}"}


def _delete_permanently(path: str, is_dir: bool) -> str | None:
    import shutil
    try:
        if is_dir:
            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError as e:
        return f"could not delete: {e.strerror or e}"
    return None if not os.path.exists(path) else "still there"


def _full_hash(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def recheck(item: dict, cfg: dict) -> str | None:
    """Is the recommendation still true right now? Returns None if yes, else why not."""
    p = item["path"]
    if item["level"] in NEVER_DELETE:
        return "marked Keep / archive; not deletable from here"
    if not _inside(p, cfg["inbox_folders"]):
        return "not inside your inbox folders"
    try:
        st = os.stat(p, follow_symlinks=False)
    except OSError:
        return "no longer there"
    if attrs(st) & FA_REPARSE:
        return "is a link/junction"
    if "mtime_ns" not in item:
        return "scan is from an older version; run a new scan"
    if st.st_mtime_ns != item["mtime_ns"]:
        return "changed since the scan; run a new scan"
    if item["is_dir"]:
        if _dir_summary(p)["size"] != item["size"]:
            return "folder contents changed since the scan"
    elif st.st_size != item["size"]:
        return "size changed since the scan"
    if is_cloud_only(st):
        return "is cloud-only"
    cat = item["category"]
    rel = item.get("related")
    if cat in ("duplicate_of_filed", "duplicate_in_downloads"):
        if not rel or not os.path.isfile(rel):
            return "the copy we keep is gone, so this may be the last one"
        if os.path.samefile(p, rel):
            return "the kept copy is the same file"
        a, b = _full_hash(p), _full_hash(rel)
        if not a or a != b:
            return "the kept copy no longer has identical content"
    elif cat == "archive_extracted":
        if not rel or not os.path.isdir(rel):
            return "the extracted folder is gone"
        if full_ext(p) == ".zip":
            chk = verify_extracted(Path(p), Path(rel))
            if not chk or not chk["complete"]:
                return "the extracted folder no longer holds every file from the zip"
    return None


def plan(cfg: dict, report: dict, paths: list[str] | None = None) -> dict:
    """Which agreed items can go to the Recycle Bin, which are too big for it."""
    dec = load_decisions(cfg["database"])
    agreed = [it for it in report["items"]
              if (d := dec.get(it["path"])) and d["decision"] == "agree" and d["size"] == it["size"]
              and it["level"] not in NEVER_DELETE and (paths is None or it["path"] in paths)]
    limits: dict = {}
    recycle, too_big = [], []
    for it in agreed:
        drive_key = os.path.splitdrive(it["path"])[0].upper() or "/"
        if drive_key not in limits:
            limits[drive_key] = recycle_bin_limit(it["path"])
        lim = limits[drive_key]
        if lim["nuke"] or (lim["max_bytes"] and it["size"] > lim["max_bytes"] * 0.9):
            too_big.append(it)
        else:
            recycle.append(it)
    return {"recycle": recycle, "too_big": too_big,
            "limits": {k: {kk: v for kk, v in lim.items()} for k, lim in limits.items()}}


def _log_action(db_path: Path, item: dict, mode: str, result: str) -> None:
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS cleanup_action (
            ts TEXT, path TEXT, size INTEGER, category TEXT, mode TEXT, result TEXT)""")
        conn.execute("INSERT INTO cleanup_action VALUES (?, ?, ?, ?, ?, ?)",
                     (datetime.now().isoformat(timespec="seconds"), item["path"], item["size"],
                      item["category"], mode, result))
        conn.commit()
    finally:
        conn.close()


def history(db_path: Path, n: int = 200) -> list:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS cleanup_action (
            ts TEXT, path TEXT, size INTEGER, category TEXT, mode TEXT, result TEXT)""")
        return [dict(r) for r in conn.execute("SELECT * FROM cleanup_action ORDER BY ts DESC LIMIT ?", (n,))]
    finally:
        conn.close()


def delete_items(cfg: dict, items: list, mode: str, progress=None, log=None) -> dict:
    """mode: 'recycle' or 'permanent'. Returns per-file results. Keeps going after a failure."""
    say = progress or (lambda m: None)
    done, skipped, failed = [], [], []
    for i, it in enumerate(items):
        say(f"{i + 1} of {len(items)}: {it['name']}")
        why = recheck(it, cfg)
        if not why and any(it["path"] == d.get("related") or
                           (d.get("related") or "").startswith(it["path"] + os.sep) for d in done):
            why = "another file deleted in this run relied on this copy"
        if why:
            skipped.append({**it, "why": why})
            _log_action(cfg["database"], it, mode, "skipped: " + why)
            if log:
                log.info("CLEANUP skipped %s: %s", it["path"], why)
            continue
        if mode == "recycle":
            err = _to_recycle_bin(it["path"])
        else:
            err = _delete_permanently(it["path"], it["is_dir"])
        if err and err.startswith("UNVERIFIED"):
            done.append({**it, "why": err})
            _log_action(cfg["database"], it, mode, "deleted, " + err)
            set_decision(cfg["database"], it, "deleted")
            if log:
                log.warning("CLEANUP %s: %s", it["path"], err)
        elif err:
            failed.append({**it, "why": err})
            _log_action(cfg["database"], it, mode, "failed: " + err)
            if log:
                log.warning("CLEANUP failed %s: %s", it["path"], err)
        else:
            done.append(it)
            _log_action(cfg["database"], it, mode, "deleted")
            set_decision(cfg["database"], it, "deleted")
            if log:
                log.info("CLEANUP %s %s (%s)", "recycled" if mode == "recycle" else "DELETED permanently",
                         it["path"], human(it["size"]))
    # drop deleted items from the saved report so the page updates without a rescan
    rep = load_report()
    if rep and done:
        gone = {it["path"] for it in done}
        rep["items"] = [it for it in rep["items"] if it["path"] not in gone]
        for lv in LEVELS:
            rep["by_level"][lv] = {"count": sum(1 for it in rep["items"] if it["level"] == lv),
                                   "bytes": sum(it["size"] for it in rep["items"] if it["level"] == lv)}
        tmp = REPORT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
        os.replace(tmp, REPORT_FILE)
    slim = lambda xs: [{"path": x["path"], "name": x["name"], "size": x["size"], **({"why": x["why"]} if "why" in x else {})} for x in xs]
    return {"mode": mode, "finished": datetime.now().isoformat(timespec="seconds"),
            "deleted": slim(done), "deleted_bytes": sum(x["size"] for x in done),
            "skipped": slim(skipped), "failed": slim(failed)}


class Deleter:
    """One delete job at a time; shares Runner's lock so a scan and a delete never overlap."""
    state = {"running": False, "progress": None, "result": None, "error": None, "plan": None}

    @classmethod
    def start(cls, cfg: dict, mode: str, paths: list[str] | None, log=None) -> str | None:
        rep = load_report()
        if not rep:
            return "No scan yet."
        with Runner.lock:
            if Runner.state["running"]:
                return "A scan is running; wait for it to finish."
            if cls.state["running"]:
                return "A delete is already running."
            p = plan(cfg, rep, paths)
            if mode == "recycle":
                items = p["recycle"]
            else:
                # permanent only for files the last plan showed as too big for the Recycle Bin,
                # and only the exact paths the page sent
                items = [it for it in p["too_big"] if paths and it["path"] in paths]
            if not items:
                return "Nothing to delete: no agreed files qualify." if mode == "recycle" else \
                    "Nothing to delete permanently."
            relied = {it.get("related") for it in items}
            items.sort(key=lambda it: it["path"] in relied)  # copies others rely on go last
            cls.state.update(running=True, progress="Starting", error=None)
            Runner.state["running_delete"] = True

        def work():
            try:
                cls.state["result"] = delete_items(cfg, items, mode,
                                                   progress=lambda m: cls.state.update(progress=m), log=log)
            except Exception as e:
                cls.state["error"] = str(e)
                if log:
                    log.error("cleanup delete failed: %s", e)
            finally:
                cls.state.update(running=False, progress=None)
                Runner.state.pop("running_delete", None)

        threading.Thread(target=work, daemon=True, name="cleanup-delete").start()
        return None
