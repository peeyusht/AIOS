"""
Phase 6: library and hygiene. Four lists about what you already hold, from one walk of your Downloads and
PARA folders. READ-ONLY: nothing is moved, renamed or deleted from here (deleting stays with Cleanup).

  images      firmware, OS and VM images, grouped by product with the versions you hold. A folder an
              appliance was unpacked into (.ovf + .vmdk) counts as one item.
  versions    documents that are versions of one another ("_v2", "_Final", "_R1", a date in the name), newest
              first, and whether the copy you filed is older than one still in Downloads.
  similar     pictures that look the same (resized, re-saved, re-downloaded), compared by a small
              fingerprint of the picture, not by name.
  installers  programs and installers, and whether Windows accepts the publisher's signature on them.

What is opened: a picture (to fingerprint it) and an installer (Windows reads it to check the signature).
Documents and images of firmware/VMs are never opened: names, sizes and dates only. Cloud-only placeholders
are skipped everywhere. Fingerprints and signature results are kept per file (path, size, modified time) in
the agent's database, so a second scan only looks at what changed.

Measured on the user's folders (11 Oct 2026, 862 files in Downloads, 1,368 filed; a first scan took 3 s,
a repeat 0.1 s):
  - 45 firmware/VM files, 33.6 GB, all in Downloads, make 8 products (32 of the files are small .ovf
    descriptors inside unpacked folders, which is why a folder counts as one item);
  - 59 version chains: 43 where the names say so, 16 "(1)", "(2)" re-downloads with different content. Those
    are mostly different documents with one name (monthly statements, receipts), so they are a separate kind
    ("same name"), listed after real versions. In 2 chains the filed copy is older than one in Downloads;
  - pictures (255 fingerprinted): an 8x8 fingerprint with chained matching put 19 unrelated screenshots in
    one group and mixed logos with a signature (mostly-blank pictures all look alike at that size). Hence
    16x16, pictures with almost no detail left out, and every member must match the group's first picture,
    not just a neighbour. Real resizes and re-saves measured 0-9 bits apart, different screenshots of one
    window 10-17: at 8 there are 30 groups (11 of them same-size copies), at 12 seven screenshot groups join;
  - programs: none in Downloads, 2 filed (1 not signed, 1 where Windows found no readable signature).
"""
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import cleanup

BASE = Path(__file__).resolve().parent
REPORT_FILE = BASE / "library_report.json"

DEFAULTS = {
    "enabled": True,
    "scan_hours": 24,          # the running agent rescans this often (0 = only when you click Scan)
    "image_distance": 8,       # of 256 fingerprint bits; how different two pictures may be and still match
    "check_signatures": True,  # ask Windows about the publisher signature of programs and installers
}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
OFFICE_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".xlsb", ".ppt", ".pptx", ".odt", ".ods",
              ".odp", ".rtf", ".vsd", ".vsdx"}
PROGRAM_EXT = {".exe", ".msi", ".msp", ".msu", ".msix", ".msixbundle", ".appx", ".appxbundle"}
MAX_IMAGE_BYTES = 60 * 1024 * 1024
CREATE_NO_WINDOW = 0x08000000


def settings(cfg: dict) -> dict:
    raw = cfg.get("library")
    s = {**DEFAULTS, **(raw if isinstance(raw, dict) else {})}
    for k, d in DEFAULTS.items():      # a hand-edited config.yaml can hold anything
        if isinstance(d, bool):
            s[k] = s[k] is True
        else:
            try:
                s[k] = int(s[k])
            except (TypeError, ValueError):
                s[k] = d
    s["scan_hours"] = max(0, s["scan_hours"])
    s["image_distance"] = min(40, max(0, s["image_distance"]))
    return s


# --------------------------------------------------------------------------- firmware, OS and VM images
FORTINET = {"FGT": "FortiGate", "FAZ": "FortiAnalyzer", "FMG": "FortiManager", "FNC": "FortiNAC",
            "FSW": "FortiSwitch", "FAP": "FortiAP", "FWB": "FortiWeb", "FML": "FortiMail", "FAC": "FortiAuthenticator",
            "FPX": "FortiProxy", "FSA": "FortiSandbox", "FCT": "FortiClient", "FOS": "FortiOS"}
FORTINET_RX = re.compile(r"^(F[A-Z]{2})_([A-Za-z0-9]+)-v(\d+(?:\.\d+)+)(?:\.[A-Z])?-build(\d+)", re.I)
VERSION_RX = re.compile(r"(?<![A-Za-z0-9])v?(\d+(?:\.\d+){1,3}(?:U\d+[a-z]?)?)(?![0-9])", re.I)
BUILD_RX = re.compile(r"(?:build[\s._-]?|[-_])(\d{3,})(?!\d)", re.I)


def looks_like_image(name: str) -> bool:
    """A firmware/OS/VM image, or an archive of one ('FGT_VM64-...-FORTINET.out.ovf.zip')."""
    ext = cleanup.full_ext(name)
    if ext in cleanup.KEEP_EXT:
        return True
    return ext in cleanup.ARCHIVE_EXT and cleanup.full_ext(cleanup.stem_of(name)) in cleanup.KEEP_EXT


def parse_image(name: str) -> dict:
    """{'product', 'version', 'build'} from a vendor file or folder name. Version and build may be None."""
    stem = name
    for _ in range(3):   # 'x.out.ovf.zip' -> 'x'
        ext = cleanup.full_ext(stem)
        if ext in cleanup.KEEP_EXT or ext in cleanup.ARCHIVE_EXT:
            stem = cleanup.stem_of(stem)
    m = FORTINET_RX.match(stem)
    if m:
        family = FORTINET.get(m.group(1).upper(), m.group(1).upper())
        return {"product": f"{family} {m.group(2).upper().replace('_', ' ')}", "version": m.group(3), "build": m.group(4)}
    m = VERSION_RX.search(stem)
    if not m or m.start() < 2:
        return {"product": re.sub(r"[\s._-]+", " ", stem).strip() or name, "version": None, "build": None}
    product = re.sub(r"[\s._-]+", " ", stem[: m.start()]).strip()
    b = BUILD_RX.search(stem, m.end())
    return {"product": product or stem, "version": m.group(1), "build": b.group(1) if b else None}


def _version_key(v: str | None) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")) or (-1,)


def catalogue(files: list, roots: dict) -> list:
    """Group image files into products. `roots` maps each walked root to its source ('inbox' or 'para').
    Files in a subfolder of a root in Downloads belong to that subfolder (one unpacked appliance)."""
    items: dict = {}
    for f in files:
        if not looks_like_image(f["name"]):
            continue
        root = next((r for r in roots if _under(f["path"], r)), None)
        rel = os.path.relpath(f["path"], root).split(os.sep) if root else [f["name"]]
        if f["source"] == "inbox" and len(rel) > 1:      # inside an unpacked folder: the folder is the item
            key = os.path.join(root, rel[0])
            it = items.setdefault(key, {"path": key, "name": rel[0], "is_dir": True, "size": 0, "files": 0,
                                        "source": f["source"], "modified": 0.0})
        else:
            it = items.setdefault(f["path"], {"path": f["path"], "name": f["name"], "is_dir": False, "size": 0,
                                              "files": 0, "source": f["source"], "modified": 0.0})
        it["size"] += f["size"]
        it["files"] += 1
        it["modified"] = max(it["modified"], f["mtime"])
    products: dict = {}
    for it in items.values():
        p = parse_image(it["name"])
        g = products.setdefault(p["product"].lower(), {"product": p["product"], "items": []})
        g["items"].append({**it, "version": p["version"], "build": p["build"],
                           "folder": os.path.dirname(it["path"]), "modified": cleanup.iso(it["modified"])})
    out = []
    for key, g in products.items():
        g["items"].sort(key=lambda i: (_version_key(i["version"]), int(i["build"] or 0), i["name"]), reverse=True)
        versions = sorted({i["version"] for i in g["items"] if i["version"]}, key=_version_key, reverse=True)
        out.append({"key": key, "product": g["product"], "versions": versions, "items": g["items"],
                    "size": sum(i["size"] for i in g["items"]),
                    "in_downloads": sum(1 for i in g["items"] if i["source"] == "inbox")})
    out.sort(key=lambda g: -g["size"])
    return out


def _under(path: str, root: str) -> bool:
    p, r = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    return p.startswith(r.rstrip("\\/") + os.sep)


# --------------------------------------------------------------------------- versions of one document
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
SEP = r"[\s._-]"
COPY_RX = re.compile(rf"{SEP}*\(\d+\)$|{SEP}*-\s*copy(?:\s*\(\d+\))?$|{SEP}+copy\d*$", re.I)
MARK_RX = re.compile(rf"""(?ix)
    {SEP}+(?:v|ver|version|rev|r)[\s._-]?\d+(?:\.\d+)*[a-z]?(?=$|{SEP}|\() |
    {SEP}+(?:final|draft|signed|updated|revised|latest|old|clean|edited|reviewed)\d*(?=$|{SEP}|\() |
    {SEP}+(?:[0-3]?\d){SEP}?{MONTH}{SEP}?(?:19|20)?\d\d(?=$|{SEP}|\() |
    {SEP}+(?:19|20)\d\d[-._]?(?:0[1-9]|1[0-2])[-._]?(?:[0-2]\d|3[01])(?=$|{SEP}|\() |
    {SEP}+(?:[0-2]\d|3[01])[-._](?:0[1-9]|1[0-2])[-._](?:19|20)\d\d(?=$|{SEP}|\()
""")


def split_version(stem: str) -> tuple:
    """('report', ['v2', 'final'], copy?) from 'Report_v2_Final (1)'. The base is lower-cased, markers in order."""
    s, marks, copy = stem.strip(), [], False
    while True:
        m = COPY_RX.search(s)
        if m:
            s, copy = s[: m.start()], True
            continue
        found = [m for m in MARK_RX.finditer(s)]
        if not found:
            break
        m = found[-1]   # a marker in the middle ("Plan_v2_customer") goes too; the rest stays in the name
        marks.insert(0, re.sub(rf"^{SEP}+", "", m.group()).lower())
        s = s[: m.start()] + s[m.end():]
    return re.sub(r"[\s._-]+", " ", s).strip().lower(), marks, copy


def version_chains(files: list) -> list:
    """Documents with one base name and extension but different content. kind 'versions' when the names say
    so (v2, final, a date...), 'same-name' when they differ only by '(1)'-style suffixes."""
    groups: dict = {}
    for f in files:
        ext = cleanup.full_ext(f["name"])
        if ext not in OFFICE_EXT:
            continue
        base, marks, copy = split_version(f["name"][: len(f["name"]) - len(ext)])
        if len(base) < 6 or not re.search(r"[a-z]{3}", base):
            continue
        groups.setdefault((base, ext), []).append({**f, "marks": marks, "copy": copy})
    out = []
    for (base, ext), members in groups.items():
        if len({m["size"] for m in members}) < 2 or len({m["name"].lower() for m in members}) < 2:
            continue      # one file, or byte-for-byte copies (Cleanup's subject)
        members.sort(key=lambda m: -m["mtime"])
        newest = members[0]
        marked = len({tuple(m["marks"]) for m in members}) > 1
        filed = [m for m in members if m["source"] == "para"]
        out.append({
            "key": f"{base}|{ext}", "title": base, "ext": ext, "kind": "versions" if marked else "same-name",
            # the filed copy is not the newest one: the thing worth knowing about a chain
            "filed_is_older": bool(filed) and newest["source"] == "inbox",
            "members": [{"path": m["path"], "name": m["name"], "size": m["size"], "source": m["source"],
                         "folder": os.path.dirname(m["path"]), "modified": cleanup.iso(m["mtime"]),
                         "label": " ".join(m["marks"]) or ("copy" if m["copy"] else ""), "newest": m is newest}
                        for m in members]})
    out.sort(key=lambda c: (c["kind"] != "versions", not c["filed_is_older"], -len(c["members"]), c["title"]))
    return out


# --------------------------------------------------------------------------- pictures that look the same
HASH_SIDE = 16
MIN_DETAIL = 24     # of 256 bits: fewer set (or unset) means a near-blank picture; those all look alike


def picture_hash(path: str) -> dict | None:
    """{'hash': hex of a 256-bit difference fingerprint, 'w', 'h'}, or None if it can't be read."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
            if w * h > 120_000_000:
                return None
            im.draft("L", (64, 64))          # JPEG: decode small
            if im.mode in ("P", "PA"):
                im = im.convert("RGBA")
            if im.mode in ("RGBA", "LA"):    # transparent logos: put them on white, or the hidden colour decides
                bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
                bg.alpha_composite(im.convert("RGBA"))
                im = bg
            px = im.convert("L").resize((HASH_SIDE + 1, HASH_SIDE), Image.LANCZOS).tobytes()
    except Exception:
        return None
    bits = 0
    for y in range(HASH_SIDE):
        row = y * (HASH_SIDE + 1)
        for x in range(HASH_SIDE):
            bits = (bits << 1) | (px[row + x] > px[row + x + 1])
    return {"hash": f"{bits:064x}", "w": w, "h": h}


def similar_groups(pictures: list, distance: int) -> list:
    """pictures: [{'path', 'hash', 'size', ...}]. A picture joins a group only if it is within `distance`
    of the group's first member, so a chain of small differences can't join unrelated pictures."""
    todo = []
    for p in pictures:
        v = int(p["hash"], 16)
        if MIN_DETAIL <= v.bit_count() <= HASH_SIDE * HASH_SIDE - MIN_DETAIL:
            todo.append((v, p))
    todo.sort(key=lambda t: (t[1].get("source") != "para", -t[1]["size"], t[1]["path"]))  # filed, biggest first
    groups, used = [], set()
    for i, (v, p) in enumerate(todo):
        if i in used:
            continue
        members = [p]
        for j in range(i + 1, len(todo)):
            if j not in used and (v ^ todo[j][0]).bit_count() <= distance:
                used.add(j)
                members.append({**todo[j][1], "distance": (v ^ todo[j][0]).bit_count()})
        if len(members) > 1:
            groups.append(members)
    return groups


# --------------------------------------------------------------------------- publisher signatures
SIGN_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$paths = [Console]::In.ReadToEnd() | ConvertFrom-Json
$out = foreach ($p in @($paths)) {
  $s = Get-AuthenticodeSignature -LiteralPath $p
  [pscustomobject]@{ path = $p; status = "$($s.Status)"; subject = "$($s.SignerCertificate.Subject)";
                     expires = if ($s.SignerCertificate) { $s.SignerCertificate.NotAfter.ToString('yyyy-MM-dd') } else { '' } }
}
ConvertTo-Json -InputObject @($out) -Compress
"""
SIGN_TEXT = {
    "Valid": ("signed", "Signed, and Windows trusts the publisher"),
    "NotSigned": ("unsigned", "Not signed: nothing says who made it"),
    "HashMismatch": ("tampered", "The file was changed after it was signed"),
    "NotTrusted": ("untrusted", "Signed, but Windows does not trust the publisher"),
    "UnknownError": ("untrusted", "Signed, but Windows could not verify the signature"),
    "NotSupportedFileFormat": ("unknown", "Windows cannot check this kind of file"),
    "Incompatible": ("unknown", "Windows cannot check this kind of file"),
}


def _powershell() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    p = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return p if os.path.exists(p) else "powershell.exe"


def check_signatures(paths: list) -> dict:
    """{path: {'status', 'subject', 'expires'}} from Windows (Get-AuthenticodeSignature). {} if unavailable.
    The paths go in on standard input as JSON, never on the command line."""
    if os.name != "nt" or not paths:
        return {}
    try:
        r = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", SIGN_PS],
                           input=json.dumps(paths), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60 + 20 * len(paths),
                           creationflags=CREATE_NO_WINDOW)
        rows = json.loads(r.stdout.strip() or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    return {x["path"]: x for x in (rows if isinstance(rows, list) else [rows]) if isinstance(x, dict) and x.get("path")}


def publisher(subject: str) -> str:
    """'CN=Fortinet Technologies (Canada) ULC, O=...' -> 'Fortinet Technologies (Canada) ULC'."""
    m = re.search(r'(?:^|,\s*)CN=("([^"]+)"|[^,]+)', subject or "")
    return (m.group(2) or m.group(1)).strip() if m else ""


def signature_view(status: str, subject: str = "") -> dict:
    level, text = SIGN_TEXT.get(status or "", ("unknown", "Could not be checked"))
    if status == "UnknownError" and not subject:   # no certificate came back: damaged, or not a signature at all
        level, text = "unknown", "Windows could not read a signature in this file"
    return {"level": level, "text": text}


# --------------------------------------------------------------------------- per-file results kept between scans
class Cache:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(str(db_path), timeout=30)
        self.conn.execute("""CREATE TABLE IF NOT EXISTS library_cache (
            path TEXT, kind TEXT, size INTEGER, mtime_ns INTEGER, value TEXT, PRIMARY KEY (path, kind))""")
        self.conn.commit()

    def get(self, f: dict, kind: str):
        r = self.conn.execute("SELECT size, mtime_ns, value FROM library_cache WHERE path=? AND kind=?",
                              (f["path"], kind)).fetchone()
        return json.loads(r[2]) if r and r[0] == f["size"] and r[1] == f["mtime_ns"] else None

    def put(self, f: dict, kind: str, value) -> None:
        self.conn.execute("INSERT OR REPLACE INTO library_cache VALUES (?,?,?,?,?)",
                          (f["path"], kind, f["size"], f["mtime_ns"], json.dumps(value)))

    def close(self, seen: set) -> None:
        gone = [r[0] for r in self.conn.execute("SELECT DISTINCT path FROM library_cache") if r[0] not in seen]
        self.conn.executemany("DELETE FROM library_cache WHERE path=?", [(p,) for p in gone])
        self.conn.commit()
        self.conn.close()


# --------------------------------------------------------------------------- the scan
def scan(cfg: dict, progress=None, log=None, save: bool = True) -> dict:
    say = progress or (lambda m: None)
    s = settings(cfg)
    t0 = time.time()
    files, errors, stats = [], [], {"files_inbox": 0, "files_para": 0, "cloud_only_inbox": 0, "cloud_only_para": 0}
    roots = {}
    depth = cleanup.settings(cfg)["max_depth"]
    say("Listing your folders")
    for r in cfg["inbox_folders"]:
        if Path(r).is_dir():
            roots[str(r)] = "inbox"
            cleanup._walk(Path(r), depth, "inbox", files, [], errors, stats, False)
    if Path(cfg["para_root"]).is_dir():
        roots[str(cfg["para_root"])] = "para"
        cleanup._walk(Path(cfg["para_root"]), None, "para", files, [], errors, stats, False)

    def meta(f):
        return {"path": f["path"], "name": f["name"], "size": f["size"], "source": f["source"],
                "folder": os.path.dirname(f["path"]), "modified": cleanup.iso(f["mtime"])}

    cache = Cache(cfg["database"])
    try:
        pics = [f for f in files if cleanup.full_ext(f["name"]) in IMAGE_EXT and not f["cloud"]
                and 4096 < f["size"] <= MAX_IMAGE_BYTES]
        hashed, fresh = [], 0
        for i, f in enumerate(pics):
            h = cache.get(f, "picture")
            if h is None:
                if fresh % 25 == 0:
                    say(f"Looking at pictures: {i + 1} of {len(pics)}")
                h = picture_hash(f["path"]) or {}
                cache.put(f, "picture", h)
                fresh += 1
            if h.get("hash"):
                hashed.append({**meta(f), **h})
        groups = similar_groups(hashed, s["image_distance"])
        similar = [{"key": hashlib.sha1(g[0]["path"].encode("utf-8", "replace")).hexdigest()[:16],
                    "identical": len({m["size"] for m in g}) == 1,
                    "members": [{k: v for k, v in m.items() if k != "hash"} for m in g]} for g in groups]
        similar.sort(key=lambda g: (g["identical"], -len(g["members"])))

        progs = [f for f in files if cleanup.full_ext(f["name"]) in PROGRAM_EXT and not f["cloud"]]
        installers = []
        if s["check_signatures"] and progs:
            need = [f for f in progs if cache.get(f, "signature") is None]
            if need:
                say(f"Checking the publisher of {len(need)} program{'s' if len(need) != 1 else ''}")
                got = check_signatures([f["path"] for f in need])
                for f in need:
                    if f["path"] in got:
                        x = got[f["path"]]
                        cache.put(f, "signature", {"status": x.get("status") or "", "subject": x.get("subject") or "",
                                                   "expires": x.get("expires") or ""})
            import origin
            for f in progs:
                sig = cache.get(f, "signature") or {}
                site = origin.read(f["path"]) or {}
                installers.append({**meta(f), **signature_view(sig.get("status"), sig.get("subject", "")), "status": sig.get("status") or "",
                                   "publisher": publisher(sig.get("subject", "")), "expires": sig.get("expires") or "",
                                   "host": site.get("host")})
            order = {"tampered": 0, "unsigned": 1, "untrusted": 2, "unknown": 3, "signed": 4}
            installers.sort(key=lambda x: (order.get(x["level"], 3), x["source"] != "inbox", x["name"].lower()))
    finally:
        cache.close({f["path"] for f in files})

    say("Grouping")
    images = catalogue(files, roots)
    chains = version_chains(files)
    rep = {
        "scanned_at": datetime.now().isoformat(timespec="seconds"), "seconds": round(time.time() - t0, 1),
        "files": stats["files_inbox"] + stats["files_para"], "errors": errors[:20],
        "signatures_checked": bool(s["check_signatures"]) and os.name == "nt",
        "images": images, "versions": chains, "similar": similar, "installers": installers,
    }
    if save:
        tmp = REPORT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(rep), encoding="utf-8")
        os.replace(tmp, REPORT_FILE)
    if log:
        log.info("library scan: %d image product(s), %d version chain(s), %d picture group(s), %d program(s), %.1fs",
                 len(images), len(chains), len(similar), len(installers), rep["seconds"])
    return rep


def load_report() -> dict | None:
    try:
        return json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def paths_in(rep: dict | None) -> set:
    """Every path the last report mentions: the only paths 'Show' will open."""
    out = set()
    for g in (rep or {}).get("images", []):
        out.update(i["path"] for i in g["items"])
    for kind in ("versions", "similar"):
        for g in (rep or {}).get(kind, []):
            out.update(m["path"] for m in g["members"])
    out.update(i["path"] for i in (rep or {}).get("installers", []))
    return out


# --------------------------------------------------------------------------- what the page shows
KINDS = ("images", "versions", "similar", "installers")


def _dismissed(db_path) -> set:
    c = sqlite3.connect(str(db_path), timeout=30)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS library_dismissed (kind TEXT, key TEXT, ts TEXT, PRIMARY KEY (kind, key))")
        return {(r[0], r[1]) for r in c.execute("SELECT kind, key FROM library_dismissed")}
    finally:
        c.close()


def dismiss(db_path, kind: str, key: str, undo: bool = False) -> None:
    c = sqlite3.connect(str(db_path), timeout=30)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS library_dismissed (kind TEXT, key TEXT, ts TEXT, PRIMARY KEY (kind, key))")
        if undo:
            c.execute("DELETE FROM library_dismissed WHERE kind=? AND key=?", (kind, key))
        else:
            c.execute("INSERT OR REPLACE INTO library_dismissed VALUES (?,?,?)",
                      (kind, key, datetime.now().isoformat(timespec="seconds")))
        c.commit()
    finally:
        c.close()


def restore_all(db_path) -> None:
    c = sqlite3.connect(str(db_path), timeout=30)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS library_dismissed (kind TEXT, key TEXT, ts TEXT, PRIMARY KEY (kind, key))")
        c.execute("DELETE FROM library_dismissed")
        c.commit()
    finally:
        c.close()


def key_of(kind: str, entry: dict) -> str:
    return entry["path"] if kind == "installers" else entry["key"]


def view(cfg: dict) -> dict:
    """The last report minus what you dismissed, with the counts the page shows."""
    s = settings(cfg)
    empty = {k: [] for k in KINDS}
    base = {"enabled": s["enabled"], "runner": Runner.state, "settings": {"scan_hours": s["scan_hours"]}}
    rep = load_report() if s["enabled"] else None
    if not rep:
        return {**base, "scanned_at": None, **empty, "counts": {k: 0 for k in KINDS}, "dismissed": 0,
                "summary": {"images_bytes": 0, "images_in_downloads_bytes": 0, "filed_is_older": 0, "not_signed": 0}}
    gone = _dismissed(cfg["database"])
    out = {k: [e for e in rep.get(k, []) if (k, key_of(k, e)) not in gone] for k in KINDS}
    hidden = sum(len(rep.get(k, [])) - len(out[k]) for k in KINDS)
    return {**base, "scanned_at": rep.get("scanned_at"), "seconds": rep.get("seconds"), "files": rep.get("files"),
            "signatures_checked": rep.get("signatures_checked", False), **out,
            "counts": {k: len(out[k]) for k in KINDS}, "dismissed": hidden,
            "summary": {
                "images_bytes": sum(g["size"] for g in out["images"]),
                "images_in_downloads_bytes": sum(i["size"] for g in out["images"] for i in g["items"]
                                                 if i["source"] == "inbox"),
                "filed_is_older": sum(1 for c in out["versions"] if c["filed_is_older"]),
                "not_signed": sum(1 for i in out["installers"] if i["level"] in ("unsigned", "tampered", "untrusted")),
            }}


class Runner:
    """One scan at a time, in a background thread, with progress for the page."""
    lock = threading.Lock()
    state = {"running": False, "started": None, "progress": None, "error": None, "finished": None}

    @classmethod
    def start(cls, cfg: dict, log=None) -> bool:
        with cls.lock:
            if cls.state["running"]:
                return False
            cls.state.update(running=True, started=datetime.now().isoformat(timespec="seconds"),
                             progress="Starting", error=None)

        def work():
            try:
                scan(cfg, progress=lambda m: cls.state.update(progress=m), log=log)
            except Exception as e:  # never take the agent down
                cls.state["error"] = str(e)[:300]
                if log:
                    log.error("library scan failed: %s", e)
            finally:
                cls.state.update(running=False, progress=None,
                                 finished=datetime.now().isoformat(timespec="seconds"))

        threading.Thread(target=work, daemon=True, name="library-scan").start()
        return True

    @classmethod
    def due(cls, cfg: dict) -> bool:
        s = settings(cfg)
        if not s["enabled"] or not s["scan_hours"] or cls.state["running"]:
            return False
        rep_time = REPORT_FILE.stat().st_mtime if REPORT_FILE.exists() else 0
        return time.time() - rep_time > s["scan_hours"] * 3600
