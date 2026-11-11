"""
CERT-In vulnerability notes (spec F-9; the owner's yes of 11 Nov 2026). CERT-In publishes no feed: its notes are HTML
pages, one per note (CIVN-yyyy-nnnn), with the issue date, severity, "Software Affected" and the CVE ids. The
worker reads them once a day, keeps them in its reference file next to the CVE list (table `certin_note`), and a
device's judgement lists the notes that cover a flaw found on it ("CERT-In CIVN-2026-0544 covers 3 flaws in Google
Chrome").

Online: plain GETs of public pages on www.cert-in.org.in. A request names a year or a note id, nothing about a
customer or a device. Polite: the 20 newest notes once a day; the first time, this year's notes by number, one a
second, stopping after a run of numbers that do not exist. A page whose layout changed gives no note (logged),
never a wrong one.
"""
import html
import json
import re
import sqlite3
import time
import urllib.request
from datetime import date, datetime, timezone

BASE = "https://www.cert-in.org.in/s2cMainServlet"
AGENT = "ShadowFiler-fleet/1 (CERT-In vulnerability notes)"
PAUSE = 1.0
MISSES = 15
CODE = re.compile(r"CIVN-(\d{4})-(\d{4})")


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("latin-1")


def note_url(code: str) -> str:
    return f"{BASE}?pageid=PUBVLNOTES01&VLCODE={code}"


def list_codes(page: str, year: int) -> list:
    return sorted({m.group(0) for m in CODE.finditer(page) if int(m.group(1)) == year})


def _lines(page: str) -> list:
    text = html.unescape(re.sub(r"<[^>]+>", "\n", page))
    return [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]


def parse_note(page: str, code: str) -> dict | None:
    """The note on its page, or None when the page holds no such note (or its layout is not the known one)."""
    lines = _lines(page)
    at = [i for i, x in enumerate(lines) if x == code]
    if not at:
        return None
    rest = lines[at[-1]:]
    try:
        title = rest[1]
        issued = next(x for x in rest if x.startswith("Original Issue Date:")).split(":", 1)[1].strip()
        issued = datetime.strptime(issued, "%B %d, %Y").date().isoformat()
    except (IndexError, StopIteration, ValueError):
        return None
    sev = next((x.split(":", 1)[1].strip().upper() for x in rest if x.startswith("Severity Rating:")), "")
    def section(start, stop):
        try:
            i = rest.index(start)
        except ValueError:
            return []
        out = []
        for x in rest[i + 1:]:
            if x in stop:
                break
            out.append(x)
        return out
    affected = section("Software Affected", {"Overview", "Description", "Solution"})
    cves = sorted(set(re.findall(r"CVE-\d{4}-\d{4,}", " ".join(section("CVE Name", {"Disclaimer"})))))
    if not cves:
        cves = sorted(set(re.findall(r"CVE-\d{4}-\d{4,}", " ".join(rest))))
    return {"id": code, "title": title, "issued": issued, "severity": sev, "affected": affected[:20], "cves": cves}


def _conn(cfg: dict):
    import cve
    c = sqlite3.connect(str(cve.db_path(cfg)), timeout=60)
    c.execute("""CREATE TABLE IF NOT EXISTS certin_note (id TEXT PRIMARY KEY, title TEXT, issued TEXT, severity TEXT,
                 affected TEXT, cves TEXT, fetched_at TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS certin_meta (k TEXT PRIMARY KEY, v TEXT)")
    return c


def sync(cfg: dict, get=fetch, today: date | None = None, log=None, pause: float = PAUSE) -> dict:
    """Bring the notes up to date. Returns how many were added and any error."""
    today = today or datetime.now(timezone.utc).date()
    c = _conn(cfg)
    added, err = 0, None
    try:
        known = {r[0] for r in c.execute("SELECT id FROM certin_note")}
        try:
            codes = list_codes(get(f"{BASE}?pageid=VLNLIST02&year={today.year}"), today.year)
        except Exception as e:                    # the list could not be had: nothing changes
            return {"added": 0, "error": f"list: {e.__class__.__name__}"}
        if not any(k.startswith(f"CIVN-{today.year}-") for k in known):
            # first time this year: every note of the year by number, up to the newest listed
            top = max((int(x[-4:]) for x in codes), default=0)
            misses, n, todo = 0, 0, []
            while misses < MISSES and n < 9999:
                n += 1
                code = f"CIVN-{today.year}-{n:04d}"
                if code in known:
                    continue
                todo.append(code)
                if n >= top:
                    misses += 1
            codes = sorted(set(codes) | set(todo))
        for code in [x for x in codes if x not in known]:
            try:
                note = parse_note(get(note_url(code)), code)
            except Exception as e:
                err = f"{code}: {e.__class__.__name__}"
                note = None
            if note:
                c.execute("INSERT OR REPLACE INTO certin_note VALUES (?,?,?,?,?,?,?)",
                          (note["id"], note["title"], note["issued"], note["severity"], json.dumps(note["affected"]),
                           json.dumps(note["cves"]), datetime.now(timezone.utc).isoformat(timespec="seconds")))
                c.commit()
                added += 1
            if pause:
                time.sleep(pause)
        c.execute("INSERT OR REPLACE INTO certin_meta VALUES ('synced_at', ?)", (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
        c.commit()
    finally:
        c.close()
    if log:
        log.info("CERT-In notes: %d added%s", added, f" ({err})" if err else "")
    return {"added": added, "error": err}


def status(cfg: dict) -> dict:
    import cve
    if not cve.db_path(cfg).exists():
        return {"notes": 0, "synced_at": None}
    c = _conn(cfg)
    try:
        n = c.execute("SELECT count(*) FROM certin_note").fetchone()[0]
        r = c.execute("SELECT v FROM certin_meta WHERE k = 'synced_at'").fetchone()
    finally:
        c.close()
    return {"notes": n, "synced_at": r[0] if r else None}


def covering(cfg: dict, vul: dict | None) -> list:
    """The CERT-In notes that name a CVE found on the device, newest first, with which programs and flaws."""
    import cve
    if not vul or not cve.db_path(cfg).exists():
        return []
    found = {}
    for a in vul.get("apps") or []:
        for x in a.get("cves") or []:
            found.setdefault(x["id"], set()).add(a["name"])
    if not found:
        return []
    c = _conn(cfg)
    try:
        rows = c.execute("SELECT id, title, issued, severity, cves FROM certin_note").fetchall()
    finally:
        c.close()
    out = []
    for nid, title, issued, sev, cves in rows:
        hit = sorted(set(json.loads(cves)) & set(found))
        if hit:
            out.append({"id": nid, "title": title, "issued": issued, "severity": sev, "url": note_url(nid), "cves": hit,
                        "programs": sorted({p for h in hit for p in found[h]})})
    out.sort(key=lambda n: (n["issued"], n["id"]), reverse=True)
    return out[:50]
