"""
Known vulnerabilities: a copy of the public CVE database kept on this PC, and which of your installed
applications and Windows services it names. READ-ONLY for your PC: it lists, it never updates or removes.

What goes online (only while `library.vulnerabilities` is on): plain downloads of public files from two fixed
addresses, with nothing about this PC in the request:
  nvd.nist.gov   the National Vulnerability Database's yearly files (about 300 MB compressed for 2002 to today,
                 once), then its small "modified in the last 8 days" file on later runs;
  www.cisa.gov   CISA's list of vulnerabilities known to be used in real attacks (KEV), under 2 MB.
The comparison with what is installed happens here, against the local copy (`cve.db`, next to the code). The
list of your applications is never sent anywhere.

What is kept per CVE: id, dates, severity, the first 400 characters of the description, and every
"this product, these versions" statement: NVD's own (CPE names with version ranges) where NVD has analysed
the CVE, otherwise the one the reporting organisation filed (free-text vendor and product). On 12 Oct 2026
only 397 of the 3,334 most recently changed CVEs had NVD's statement, 3,302 had the reporter's.

Matching is the weak part and is deliberately strict. A CVE names software as vendor:product, Windows shows
a display name and a publisher. An application matches a product only when the product is its WHOLE name
(without the version, filler words and the maker's name in front) AND the vendor agrees with the publisher
(or is the maker's name in front, or the vendor part of its winget id). Then the installed version must fall
inside the stated range. Statements with no version at all ("all versions") are kept apart as `unversioned`:
they are often old or sloppy entries, not proof. Store and packaged apps are not judged.

Measured on the user's PC (12 Oct 2026): matching any part of the name called 33 applications affected by
2,712 CVEs, mostly wrongly. With the rules here: 36 of 85 programs recognised, 15 with CVEs for the installed
version (337 CVEs, 1 known exploited); by hand 12 of the 15 are right, 1 partly, 2 wrong (CVEs of another
program filed under the same product name). A program that matches nothing is unknown, not safe.
"""
import codecs
import gzip
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_FILE = BASE / "cve.db"
NVD = "https://nvd.nist.gov/feeds/json/cve/2.0/nvdcve-2.0-{name}.{ext}"
KEV = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
AGENT = "ShadowFiler/1.0 (local file assistant; public feed download)"
FIRST_YEAR = 2002
MODIFIED_COVERS_DAYS = 7        # NVD's "modified" file holds 8 days of changes; older than this, compare every year
SUMMARY_CHARS = 400
_WS = re.compile(r"[\s,]*")


def db_path(cfg: dict) -> Path:
    return Path(cfg.get("cve_database") or DB_FILE)


def _conn(path):
    c = sqlite3.connect(str(path), timeout=60)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE IF NOT EXISTS cve (id TEXT PRIMARY KEY, published TEXT, modified TEXT, status TEXT,
            score REAL, severity TEXT, summary TEXT);
        CREATE TABLE IF NOT EXISTS aff (cve TEXT, src TEXT, vendor TEXT, product TEXT, version TEXT,
            vsi TEXT, vse TEXT, vei TEXT, vee TEXT);
        CREATE INDEX IF NOT EXISTS aff_product ON aff (product, vendor);
        CREATE INDEX IF NOT EXISTS aff_cve ON aff (cve);
        CREATE TABLE IF NOT EXISTS kev (cve TEXT PRIMARY KEY, vendor TEXT, product TEXT, name TEXT, added TEXT,
            ransomware TEXT);
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    if "key" not in [r[1] for r in c.execute("PRAGMA table_info(prod)")]:
        c.execute("DROP TABLE IF EXISTS prod")
    c.execute("CREATE TABLE IF NOT EXISTS prod (key TEXT, product TEXT, vendor TEXT, PRIMARY KEY (product, vendor))")
    c.execute("CREATE INDEX IF NOT EXISTS prod_key ON prod (key)")
    return c


def _meta(c, k, default=None):
    r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def _set(c, k, v):
    c.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, str(v)))


# --------------------------------------------------------------------------- reading a feed
def norm(s: str) -> str:
    """'Igor Pavlov' and 'igor_pavlov' -> 'igor_pavlov': one spelling for names from both kinds of statement."""
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def cpe_parts(criteria: str) -> list:
    """'cpe:2.3:a:vendor:product:version:...' split on unescaped colons."""
    return [_unescape(p) for p in re.split(r"(?<!\\):", criteria)]


def _no(v) -> bool:
    return v is None or str(v).strip().lower() in ("", "*", "-", "n/a", "unspecified", "unknown", "0", "all")


def statements(cve: dict) -> set:
    """Every (src, vendor, product, version, start incl., start excl., end incl., end excl.) a CVE states.
    NVD's analysis where there is one (applications only), otherwise the reporter's."""
    out = set()
    for conf in cve.get("configurations") or []:
        for node in conf.get("nodes") or []:
            for m in node.get("cpeMatch") or []:
                p = cpe_parts(m.get("criteria") or "")
                if not m.get("vulnerable") or len(p) < 6 or p[2] != "a":
                    continue
                version = "*" if p[5] in ("*", "-", "") else p[5]
                out.add(("nvd", norm(p[3]), norm(p[4]), version, m.get("versionStartIncluding") or "",
                         m.get("versionStartExcluding") or "", m.get("versionEndIncluding") or "",
                         m.get("versionEndExcluding") or ""))
    if out:
        return out
    for a in cve.get("affected") or []:
        for d in a.get("affectedData") or []:
            vendor, product = norm(d.get("vendor")), norm(d.get("product"))
            if not product or product in ("n_a", "unknown"):
                continue
            if vendor in ("n_a", "unknown", "unspecified"):
                vendor = ""
            versions = [v for v in d.get("versions") or [] if (v.get("status") or "affected") == "affected"]
            if not versions and d.get("defaultStatus") == "affected":
                out.add(("cna", vendor, product, "*", "", "", "", ""))
            for v in versions:
                start, lt, le = v.get("version"), v.get("lessThan"), v.get("lessThanOrEqual")
                if _no(lt) and _no(le):
                    if lt == "*" or le == "*":          # "from this version on"
                        out.add(("cna", vendor, product, "*", "" if _no(start) else str(start), "", "", ""))
                    else:                               # one version, or "all"
                        out.add(("cna", vendor, product, "*" if _no(start) else str(start), "", "", "", ""))
                else:
                    out.add(("cna", vendor, product, "*", "" if _no(start) else str(start), "",
                             "" if _no(le) else str(le), "" if _no(lt) else str(lt)))
    return out


def _score(cve: dict) -> tuple:
    m = cve.get("metrics") or {}
    for key in ("cvssMetricV31", "cvssMetricV40", "cvssMetricV30", "cvssMetricV2"):
        rows = m.get(key) or []
        rows = [r for r in rows if r.get("type") == "Primary"] or rows
        if rows:
            d = rows[0].get("cvssData") or {}
            sev = d.get("baseSeverity") or rows[0].get("baseSeverity") or ""
            return d.get("baseScore"), sev.upper()
    return None, ""


def items(stream, chunk: int = 1 << 20):
    """The entries of a feed's "vulnerabilities" list, one at a time, without holding the file in memory
    (a year is up to 400 MB of JSON)."""
    dec, utf8 = json.JSONDecoder(), codecs.getincrementaldecoder("utf-8")("replace")
    buf, started = "", False
    while True:
        data = stream.read(chunk)
        buf += utf8.decode(data, final=not data)
        if not started:
            i = buf.find('"vulnerabilities"')
            j = buf.find("[", i) if i >= 0 else -1
            if j < 0:
                if not data:
                    return
                continue
            buf, started = buf[j + 1:], True
        pos = 0
        while True:
            pos = _WS.match(buf, pos).end()
            if pos >= len(buf) or buf[pos] == "]":
                break
            try:
                obj, pos = dec.raw_decode(buf, pos)
            except json.JSONDecodeError:
                break                       # the entry continues in the next piece
            yield obj
        buf = buf[pos:]
        if not data or buf.startswith("]"):
            return


class _Hashing:
    def __init__(self, f):
        self.f, self.sha = f, hashlib.sha256()

    def read(self, n):
        b = self.f.read(n)
        self.sha.update(b)
        return b


def load_feed(c, gz_path, want_sha: str | None = None) -> dict:
    """Put one downloaded feed file into the database. All or nothing: a file that does not match NVD's
    checksum changes nothing."""
    n = dropped = rows = 0
    with gzip.open(gz_path, "rb") as f:
        h = _Hashing(f)
        try:
            for it in items(h):
                cve = it.get("cve") or {}
                cid = cve.get("id")
                if not cid:
                    continue
                c.execute("DELETE FROM aff WHERE cve=?", (cid,))
                if cve.get("vulnStatus") == "Rejected":
                    c.execute("DELETE FROM cve WHERE id=?", (cid,))
                    dropped += 1
                    continue
                score, sev = _score(cve)
                text = next((d.get("value") or "" for d in cve.get("descriptions") or [] if d.get("lang") == "en"), "")
                c.execute("INSERT OR REPLACE INTO cve VALUES (?,?,?,?,?,?,?)",
                          (cid, (cve.get("published") or "")[:10], (cve.get("lastModified") or "")[:10],
                           cve.get("vulnStatus") or "", score, sev, " ".join(text.split())[:SUMMARY_CHARS]))
                st = statements(cve)
                c.executemany("INSERT INTO aff VALUES (?,?,?,?,?,?,?,?,?)", [(cid, *s) for s in st])
                n += 1
                rows += len(st)
            while h.read(1 << 20):          # whatever follows the list still counts for the checksum
                pass
        except (OSError, EOFError, ValueError) as e:
            c.rollback()
            raise ValueError(f"the file could not be read ({type(e).__name__})")
    if want_sha and h.sha.hexdigest().upper() != want_sha.upper():
        c.rollback()
        raise ValueError("the file does not match NVD's checksum")
    c.commit()
    return {"cves": n, "rejected": dropped, "statements": rows}


def load_kev(c, data: dict) -> int:
    rows = [(v.get("cveID"), v.get("vendorProject") or "", v.get("product") or "", v.get("vulnerabilityName") or "",
             v.get("dateAdded") or "", v.get("knownRansomwareCampaignUse") or "")
            for v in data.get("vulnerabilities") or [] if v.get("cveID")]
    if not rows:
        raise ValueError("CISA's list came back empty")
    c.execute("DELETE FROM kev")
    c.executemany("INSERT OR REPLACE INTO kev VALUES (?,?,?,?,?,?)", rows)
    c.commit()
    return len(rows)


# --------------------------------------------------------------------------- downloading (the online part)
def fetch(url: str, dest: Path | None = None, timeout: int = 120):
    """GET a public file. Returns the text, or writes it to `dest`. Nothing about this PC is sent."""
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if dest is None:
            return r.read().decode("utf-8", "replace")
        with open(dest, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
    return None


def _sha_of(meta_text: str) -> str:
    m = re.search(r"sha256:([0-9A-Fa-f]{64})", meta_text or "")
    return m.group(1).upper() if m else ""


def sync(cfg: dict, progress=None, log=None, get=fetch, now: datetime | None = None) -> dict:
    """Bring the local copy up to date. The first run (and any run after more than a week away) compares
    every year's checksum and downloads the years that changed; otherwise only NVD's "modified" file."""
    say = progress or (lambda m: None)
    now = now or datetime.now()
    path = db_path(cfg)
    tmp = path.with_suffix(".download")
    c = _conn(path)
    out = {"feeds": [], "errors": [], "cves": 0}
    try:
        c.execute("PRAGMA synchronous=OFF")
        last = _meta(c, "synced_at")
        whole = _meta(c, "complete") != "1" or not last or \
            now - datetime.fromisoformat(last) > timedelta(days=MODIFIED_COVERS_DAYS)
        names = [str(y) for y in range(FIRST_YEAR, now.year + 1)] if whole else ["modified"]
        failed = False
        for i, name in enumerate(names):
            try:
                sha = _sha_of(get(NVD.format(name=name, ext="meta")))
                if not sha:
                    raise ValueError("no checksum from NVD")
                if sha == _meta(c, "sha:" + name):
                    continue
                say(f"Downloading the CVE list: {name}" + (f" ({i + 1} of {len(names)})" if whole else ""))
                get(NVD.format(name=name, ext="json.gz"), tmp)
                got = load_feed(c, tmp, sha)
                _set(c, "sha:" + name, sha)
                c.commit()
                out["feeds"].append(name)
                out["cves"] += got["cves"]
            except Exception as e:      # one bad year must not lose the others; it is tried again next time
                failed = True
                out["errors"].append(f"{name}: {str(e)[:160]}")
                if log:
                    log.warning("cve sync: %s failed: %s", name, e)
        try:
            say("Downloading CISA's known-exploited list")
            out["kev"] = load_kev(c, json.loads(get(KEV)))
        except Exception as e:
            out["errors"].append(f"CISA list: {str(e)[:160]}")
        if out["feeds"]:
            say("Indexing product names")
            index_products(c)
        if whole and not failed:
            _set(c, "complete", "1")
        if not failed:
            _set(c, "synced_at", now.isoformat(timespec="seconds"))
        _set(c, "tried_at", now.isoformat(timespec="seconds"))
        _set(c, "last_error", "; ".join(out["errors"])[:500])
        c.commit()
        out["status"] = status(cfg, c)
    finally:
        c.close()
        try:
            tmp.unlink()
        except OSError:
            pass
    if log:
        log.info("cve sync: %d feed file(s), %d CVE(s) read, %d error(s)", len(out["feeds"]), out["cves"],
                 len(out["errors"]))
    return out


def status(cfg: dict, c=None) -> dict:
    path = db_path(cfg)
    if c is None and not path.exists():
        return {"synced_at": None, "tried_at": None, "complete": False, "cves": 0, "kev": 0, "bytes": 0, "error": None}
    own = c is None
    c = c or _conn(path)
    try:
        return {"synced_at": _meta(c, "synced_at"), "tried_at": _meta(c, "tried_at"),
                "complete": _meta(c, "complete") == "1",
                "cves": c.execute("SELECT COUNT(*) FROM cve").fetchone()[0],
                "kev": c.execute("SELECT COUNT(*) FROM kev").fetchone()[0],
                "bytes": path.stat().st_size if path.exists() else 0, "error": _meta(c, "last_error") or None}
    finally:
        if own:
            c.close()


def due(cfg: dict, hours: int, now: datetime | None = None) -> bool:
    last = status(cfg)["tried_at"]
    try:
        return not last or (now or datetime.now()) - datetime.fromisoformat(last) >= timedelta(hours=hours)
    except ValueError:
        return True


# --------------------------------------------------------------------------- which product is this?
NOISE = {"x64", "x86", "amd64", "arm64", "win64", "win32", "64", "32", "bit", "en", "us", "gb", "the", "for", "and",
         "of", "version", "edition", "user", "machine", "wide", "release"}
COMPANY = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "gmbh", "ag",
           "sa", "srl", "bv", "pty", "plc", "the", "and", "software", "technologies", "technology", "systems",
           "foundation", "project", "team", "developers", "contributors", "international", "group", "labs"}
VERSION_RX = re.compile(r"(?<![A-Za-z0-9.])v?(\d+(?:\.\d+)+)(?![A-Za-z0-9])")
# NVD files today's Edge under its own product name; 'microsoft:edge' is the old, pre-Chromium browser
ALSO = {("microsoft", "edge"): ("microsoft", "edge_chromium")}
TRAILING = {"vpn", "client"}     # 'FortiClient VPN' is the product 'forticlient'; measured, keep this short


def words(name: str, version: str = "", cut: bool = True) -> list:
    """'7-Zip 24.08 (x64)' -> ['7', 'zip']: the words of a display name, without version and filler."""
    s = name or ""
    if version and len(version) > 1:
        s = s.replace(version, " ")
    s = VERSION_RX.sub(" ", s)
    w = [x for x in re.findall(r"[a-z0-9]+", s.lower()) if x not in NOISE]
    for i, x in enumerate(w[1:] if cut else [], 1):     # 'MongoDB 7.0.5 2008R2Plus SSL': a build label ends the name
        if re.search(r"\d", x) and re.search(r"[a-z]", x) and len(x) > 4:
            return w[:i]
    return w


def product_key(product: str) -> str:
    """'windows_subsystem_for_linux' -> 'windowssubsystemlinux': how a product name is looked up."""
    return "".join(words(product.replace("_", " "), cut=False))


def index_products(c) -> int:
    c.execute("DELETE FROM prod")
    rows = [(product_key(r[0]), r[0], r[1]) for r in c.execute("SELECT DISTINCT product, vendor FROM aff")]
    c.executemany("INSERT OR IGNORE INTO prod VALUES (?,?,?)", [r for r in rows if len(r[0]) >= 3])
    return len(rows)


def version_of(item: dict) -> str:
    """The version to judge by: the one in the display name when there is one ('Python 3.11.1 (64-bit)' is
    registered as 3.11.1150.0, which no CVE range understands), else the registered one."""
    m = VERSION_RX.search(item.get("name") or "")
    return m.group(1) if m else (item.get("version") or "")


def vendor_agrees(vendor: str, item: dict, name_words: list, lead: list | None = None) -> bool:
    """Does this vendor make the application? `lead` is the maker's name taken off the front of the display
    name ('GitHub' of 'GitHub CLI'): then the vendor has to be that maker or the publisher, not a word of
    the product itself (a vendor called 'cli' files a product called 'cli')."""
    if not vendor:
        return False
    v = vendor.replace("_", "")
    if lead is not None:
        name_words = lead
    pub = [w for w in re.findall(r"[a-z0-9]+", (item.get("publisher") or "").lower())]
    core = "".join(w for w in pub if w not in COMPANY)
    wid = norm((item.get("update_id") or "").split(".")[0]).replace("_", "")
    if v in (core, "".join(pub), wid) or vendor in pub or vendor in name_words:
        return True
    if len(v) >= 5 and core and (core.startswith(v) or v.startswith(core) and len(core) >= 5):
        return True
    return v == "".join(name_words[:len(vendor.split("_"))])      # 'igor_pavlov' never, '7_zip' for 7-Zip


def products_for(c, item: dict) -> list:
    """[(vendor, product)] this application is. The product has to be the WHOLE display name (without the
    version, filler words and the maker's name in front), never a part of it: a part matched 'MongoDB Shell'
    to the MongoDB server and anything called 'Windows ...' to Windows. And the vendor has to agree."""
    if not c.execute("SELECT 1 FROM prod LIMIT 1").fetchone():
        index_products(c)
        c.commit()
    w = words(item.get("name") or "", item.get("version") or "")
    runs = [(w, None), (w[1:], w[:1])]                  # with and without the maker's name in front
    runs += [(r[:-1], lead) for r, lead in runs if len(r) > 1 and r[-1] in TRAILING]
    found = set()
    for run, lead in runs:
        key = "".join(run)
        if len(key) < 3:
            continue
        for r in c.execute("SELECT vendor, product FROM prod WHERE key=?", (key,)):
            if vendor_agrees(r[0], item, w, lead):
                found.add((r[0], r[1]))
    found |= {ALSO[f] for f in found if f in ALSO}
    return sorted(found)


# --------------------------------------------------------------------------- is this version affected?
BOUND_RX = re.compile(r"v?\d+(?:\.\d+)+|\d{1,6}$")


def vt(v: str) -> tuple:
    """'24.08.0.0' -> (24, 8). () for anything that does not start like a version (a commit id)."""
    if not BOUND_RX.match(v or ""):
        return ()
    t = [int(x) for x in re.findall(r"\d+", v)[:8]]
    while len(t) > 1 and t[-1] == 0:
        t.pop()
    return tuple(t)


def affected(row, version: str) -> str | None:
    """'yes' when the installed version is inside what the statement says, 'unversioned' when the statement
    names no version at all, None when it is outside or cannot be compared."""
    exact, vsi, vse, vei, vee = row["version"], row["vsi"], row["vse"], row["vei"], row["vee"]
    if exact == "*" and not (vsi or vse or vei or vee):
        return "unversioned"
    mine = vt(version)
    if not mine:
        return None
    if exact != "*":
        theirs = vt(exact)
        return "yes" if theirs and theirs == mine else None
    bounds = [vt(x) for x in (vsi, vse, vei, vee)]
    if any(x and not b for x, b in zip((vsi, vse, vei, vee), bounds)):
        return None                         # a bound that is not a number (a commit id): cannot be compared
    si, se, ei, ee = bounds
    if (si and mine < si) or (se and mine <= se) or (ei and mine > ei) or (ee and mine >= ee):
        return None
    return "yes"


# One product name often covers several programs: 'canva:canva' is the Android app and the desktop one.
OTHER_PLATFORM = re.compile(r"\b(android|ios|ipados|iphone|ipad)\b", re.I)
THIS_PLATFORM = re.compile(r"\b(windows|desktop)\b", re.I)


def match(cfg: dict, things: list) -> list:
    """For each {'name', 'publisher', 'version', ...}: the products it was recognised as and the CVEs whose
    stated versions include the installed one. Things that match no product are returned with empty lists."""
    path = db_path(cfg)
    if not path.exists():
        return [{**t, "products": [], "cves": [], "unversioned": 0} for t in things]
    c = _conn(path)
    try:
        out = []
        for t in things:
            prods = products_for(c, t)
            version = version_of(t)
            hits, loose = {}, set()
            for vendor, product in prods:
                for r in c.execute("SELECT * FROM aff WHERE product=? AND vendor=?", (product, vendor)):
                    a = affected(r, version)
                    if a == "unversioned":
                        loose.add(r["cve"])
                    elif a:
                        fixed = r["vee"] if r["version"] == "*" else ""
                        if r["cve"] not in hits or (fixed and vt(fixed) > vt(hits[r["cve"]])):
                            hits[r["cve"]] = fixed
            cves = []
            for cid, fixed in hits.items():
                r = c.execute("SELECT c.*, k.added AS kev_added, k.ransomware FROM cve c LEFT JOIN kev k ON k.cve=c.id "
                              "WHERE c.id=?", (cid,)).fetchone()
                if r and OTHER_PLATFORM.search(r["summary"] or "") and not THIS_PLATFORM.search(r["summary"]):
                    continue
                if r:
                    cves.append({"id": cid, "published": r["published"], "score": r["score"], "severity": r["severity"],
                                 "summary": r["summary"], "fixed_in": fixed or None, "kev": bool(r["kev_added"]),
                                 "kev_added": r["kev_added"],
                                 "ransomware": (r["ransomware"] or "").lower() == "known"})
            cves.sort(key=lambda x: (not x["kev"], -(x["score"] or 0), x["id"]))
            out.append({**t, "judged_version": version, "products": [f"{v}:{p}" for v, p in prods], "cves": cves,
                        "unversioned": len(loose - set(hits))})
        return out
    finally:
        c.close()


# --------------------------------------------------------------------------- what is installed here
def _state(db_path):
    c = sqlite3.connect(str(db_path), timeout=30)
    c.execute("CREATE TABLE IF NOT EXISTS vuln_state (k TEXT PRIMARY KEY, value TEXT)")
    return c


def scan(cfg: dict, updates: bool = False, hours: int = 24, read_services=None, log=None,
         now: datetime | None = None) -> dict:
    """Compare the installed applications and the third-party Windows services with the local CVE copy and
    keep the result. Nothing goes online here."""
    import apps
    import services
    # Store and packaged apps are left out: the Store updates them, and a package's version is often not the
    # product's (a "Visual Studio Code" helper package at 1.0.140 matched 72 old CVEs)
    installed = [a for a in apps.with_updates(cfg, apps.view(cfg), updates, hours)["apps"] if a["kind"] == "desktop"]
    raw = (read_services or services.read_services)()
    svcs = services.tidy(raw or [], installed)
    judged = {a["id"]: a for a in match(cfg, installed)}
    own = match(cfg, [{**s, "name": s["product"] or s["name"]} for s in svcs if not s["app_id"]])
    own = {s["id"]: s for s in own}
    out_apps = [{k: a.get(k) for k in ("id", "name", "version", "judged_version", "publisher", "kind", "available",
                                       "update_id", "products", "cves", "unversioned")}
                for a in judged.values() if a["products"]]
    out_svcs = []
    for s in svcs:
        src = judged.get(s["app_id"]) if s["app_id"] else own.get(s["id"])
        out_svcs.append({**s, "products": (src or {}).get("products", []), "cves": (src or {}).get("cves", []),
                         "unversioned": (src or {}).get("unversioned", 0)})
    out_apps.sort(key=lambda a: (-sum(1 for x in a["cves"] if x["kev"]), -len(a["cves"]), a["name"].lower()))
    rep = {"scanned_at": (now or datetime.now()).isoformat(timespec="seconds"),
           "services_read": raw is not None, "installed": len(installed), "recognised": len(out_apps),
           "apps": out_apps, "services": out_svcs}
    c = _state(cfg["database"])
    try:
        c.execute("INSERT OR REPLACE INTO vuln_state VALUES ('report', ?)", (json.dumps(rep),))
        c.commit()
    finally:
        c.close()
    if log:
        s = summary(rep)
        log.info("vulnerabilities: %d of %d applications recognised, %d with CVEs (%d known exploited), "
                 "%d service(s), %d exposed to the network", rep["recognised"], rep["installed"], s["apps_affected"],
                 s["kev"], len(out_svcs), s["services_exposed"])
    return rep


def summary(rep: dict) -> dict:
    hit = [a for a in rep["apps"] if a["cves"]]
    ids = {x["id"] for a in hit for x in a["cves"]}
    return {"apps_affected": len(hit), "cves": len(ids),
            "kev": len({x["id"] for a in hit for x in a["cves"] if x["kev"]}),
            "critical": len({x["id"] for a in hit for x in a["cves"] if (x["score"] or 0) >= 9}),
            "fix_available": sum(1 for a in hit if a.get("available")),
            "services": len(rep["services"]), "services_running": sum(1 for s in rep["services"] if s["running"]),
            "services_exposed": sum(1 for s in rep["services"] if s["exposed"]),
            "services_affected": sum(1 for s in rep["services"] if s["cves"])}


def view(cfg: dict) -> dict:
    """The last comparison, its counts, and how fresh the local CVE copy is."""
    c = _state(cfg["database"])
    try:
        r = c.execute("SELECT value FROM vuln_state WHERE k='report'").fetchone()
    finally:
        c.close()
    try:
        rep = json.loads(r[0]) if r else None
    except ValueError:
        rep = None
    rep = rep or {"scanned_at": None, "services_read": False, "installed": 0, "recognised": 0, "apps": [],
                  "services": []}
    return {**rep, "summary": summary(rep), "database": status(cfg)}


def as_text(v: dict, everything: bool = False) -> str:
    d, s = v["database"], v["summary"]
    lines = [f"CVE copy: {d['cves']:,} CVEs, {d['kev']:,} known exploited, {d['bytes'] / 2**20:.0f} MB, "
             f"updated {(d['synced_at'] or 'never').replace('T', ' ')}" + ("" if d["complete"] else " (incomplete)")]
    if d["error"]:
        lines.append("  Last download had errors: " + d["error"])
    if not v["scanned_at"]:
        return "\n".join(lines + ["No comparison yet."]) + "\n"
    lines += [f"{v['recognised']} of {v['installed']} applications recognised as a product the database knows; "
              f"{s['apps_affected']} have CVEs for the installed version ({s['cves']} CVEs, {s['kev']} known "
              f"exploited, {s['critical']} critical); {s['fix_available']} of them have a newer version available", ""]
    for a in v["apps"]:
        if not a["cves"] and not everything:
            continue
        top = a["cves"][0] if a["cves"] else None
        lines.append(f"{a['name']}  [{a['judged_version'] or '?'}]  {', '.join(a['products'])}  "
                     f"{len(a['cves'])} CVE(s)" + (f", newer version {a['available']}" if a.get("available") else "")
                     + (f", {a['unversioned']} without version information" if everything and a["unversioned"] else ""))
        for x in a["cves"][:None if everything else 3]:
            lines.append(f"    {x['id']}  {x['score'] or '-':>4}  {'EXPLOITED  ' if x['kev'] else ''}"
                         f"{'fixed in ' + x['fixed_in'] + '  ' if x['fixed_in'] else ''}{x['summary'][:110]}")
        if top and len(a["cves"]) > 3 and not everything:
            lines.append(f"    ... and {len(a['cves']) - 3} more")
    lines += ["", f"Services not part of Windows: {s['services']} ({s['services_running']} running, "
                  f"{s['services_exposed']} listening to the network, {s['services_affected']} with CVEs)"]
    for x in v["services"]:
        if x["exposed"] or x["cves"] or everything:
            ports = ", ".join(str(p["port"]) + ("" if p["network"] else " (this PC only)") for p in x["ports"])
            lines.append(f"  {x['name']}  {'running' if x['running'] else 'stopped'}  as {x['account']}"
                         + (f"  ports {ports}" if ports else "") + (f"  {len(x['cves'])} CVE(s)" if x["cves"] else "")
                         + (f"  ({x['app_name']})" if x["app_name"] else ""))
    return "\n".join(lines) + "\n"
