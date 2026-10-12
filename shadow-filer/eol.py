"""
End of support: which installed programs (and which Windows) are a release line that no longer gets
security updates. Judged on this PC against a local copy of the public endoflife.date list.

What goes online (only while `library.vulnerabilities` is on, with the CVE copy): one plain download of one
public file, https://endoflife.date/api/v1/products/full (about 3 MB, 484 products on 12 Oct 2026), with
nothing about this PC in the request. Allowed by the user on 12 Oct 2026, who chose a local copy over a
built-in table. The comparison happens here; what is installed is never sent.

Matching is strict, like the CVE matching, and the list knows no vendors, so a program matches only when its
WHOLE display name (without version, filler words and the maker's name in front) is the product's name, label
or alias. Then the installed version picks its release line ("3.11" for 3.11.1). A program the list does not
know, or whose line it does not list, is not judged: unknown, not supported.
"""
import json
import re
import sqlite3
from datetime import date, datetime, timedelta

import cve

URL = "https://endoflife.date/api/v1/products/full"
SOON_DAYS = 90
SOFTWARE = {"app", "lang", "server-app", "database", "framework", "os"}


def _conn(cfg: dict):
    c = sqlite3.connect(str(cve.db_path(cfg)), timeout=60)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS eol_product (name TEXT PRIMARY KEY, label TEXT, releases TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS eol_key (key TEXT, name TEXT, PRIMARY KEY (key, name))")
    c.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    return c


def load(c, data: dict) -> int:
    """Replace the local copy with a downloaded list. All or nothing."""
    rows = [p for p in data.get("result") or [] if p.get("name") and p.get("category") in SOFTWARE and p.get("releases")]
    if len(rows) < 50:
        raise ValueError("the end-of-life list came back nearly empty")
    c.execute("DELETE FROM eol_product")
    c.execute("DELETE FROM eol_key")
    for p in rows:
        rel = [{"name": str(r.get("name") or ""), "eol": bool(r.get("isEol")), "from": r.get("eolFrom"),
                "latest": (r.get("latest") or {}).get("name")} for r in p["releases"] if r.get("name")]
        c.execute("INSERT OR REPLACE INTO eol_product VALUES (?,?,?)", (p["name"], p.get("label") or p["name"], json.dumps(rel)))
        if p.get("category") == "os":       # "Grammarly for Windows" is not Windows: an OS is looked up by windows()
            continue
        for k in {cve.product_key(x) for x in (p["name"], p.get("label") or "", *(p.get("aliases") or []))}:
            if len(k) >= 3:
                c.execute("INSERT OR IGNORE INTO eol_key VALUES (?,?)", (k, p["name"]))
    return len(rows)


def sync(cfg: dict, get=cve.fetch, now: datetime | None = None, log=None) -> dict:
    """Download the list and replace the local copy. A failed download keeps the copy there is."""
    now = now or datetime.now()
    c = _conn(cfg)
    try:
        try:
            n = load(c, json.loads(get(URL)))
            c.execute("INSERT OR REPLACE INTO meta VALUES ('eol_synced_at', ?)", (now.isoformat(timespec="seconds"),))
            c.execute("INSERT OR REPLACE INTO meta VALUES ('eol_error', '')")
            c.commit()
            out = {"ok": True, "products": n}
        except Exception as e:
            c.rollback()
            c.execute("INSERT OR REPLACE INTO meta VALUES ('eol_error', ?)", (str(e)[:200],))
            c.commit()
            out = {"ok": False, "error": str(e)[:200]}
    finally:
        c.close()
    if log:
        log.info("end-of-life list: %s", f"{out['products']} products" if out["ok"] else "download failed: " + out["error"])
    return out


def status(cfg: dict) -> dict:
    if not cve.db_path(cfg).exists():
        return {"synced_at": None, "products": 0, "error": None}
    c = _conn(cfg)
    try:
        m = {r[0]: r[1] for r in c.execute("SELECT k, v FROM meta WHERE k IN ('eol_synced_at', 'eol_error')")}
        return {"synced_at": m.get("eol_synced_at"), "products": c.execute("SELECT COUNT(*) FROM eol_product").fetchone()[0],
                "error": m.get("eol_error") or None}
    finally:
        c.close()


def _nums(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4])


def line_of(version: str, releases: list) -> dict | None:
    """The release line a version belongs to: the longest line name that the version starts with
    ('3.11' for 3.11.1, '22' for 22.12.0). None when no listed line fits."""
    mine = _nums(version)
    best = None
    for r in releases:
        if not re.fullmatch(r"\d+(\.\d+)*", r["name"]):
            continue
        n = _nums(r["name"])
        if n and mine[:len(n)] == n and (best is None or len(n) > len(_nums(best["name"]))):
            best = r
    return best


def judge(release: dict | None, today: date) -> tuple:
    """('ended' | 'soon' | 'supported' | 'unknown', the date support ends or ended)."""
    if release is None:
        return "unknown", None
    until = release.get("from") if isinstance(release.get("from"), str) else None
    if release.get("eol"):
        return "ended", until
    try:
        if until and date.fromisoformat(until) - today <= timedelta(days=SOON_DAYS):
            return "soon", until
    except ValueError:
        pass
    return "supported", until


def match(cfg: dict, things: list, today: date | None = None) -> list:
    """For each {'name', 'version', ...}: the product and release line it is, and whether that line still
    gets security updates. Things the list does not know come back with product None."""
    today = today or date.today()
    if not cve.db_path(cfg).exists():
        return [{**t, "product": None, "state": "unknown"} for t in things]
    c = _conn(cfg)
    try:
        out = []
        for t in things:
            w = cve.words(t.get("name") or "", t.get("version") or "")
            runs = [w, w[1:]]
            runs += [r[:-1] for r in runs if len(r) > 1 and r[-1] in cve.TRAILING]
            row = None
            for run in runs:
                key = "".join(run)
                if len(key) < 3:
                    continue
                hits = c.execute("SELECT p.* FROM eol_key k JOIN eol_product p ON p.name = k.name WHERE k.key = ?", (key,)).fetchall()
                if len(hits) == 1:          # two products under one name: not sure which, so neither
                    row = hits[0]
                    break
            if row is None:
                out.append({**t, "product": None, "state": "unknown"})
                continue
            version = cve.version_of(t)
            rel = line_of(version, json.loads(row["releases"]))
            state, until = judge(rel, today)
            out.append({**t, "product": row["label"], "line": rel["name"] if rel else None, "state": state, "until": until,
                        "latest": rel.get("latest") if rel else None, "judged_version": version})
        return out
    finally:
        c.close()


def windows(cfg: dict, build: int, display_version: str, edition: str, today: date | None = None) -> dict:
    """Is this Windows release still supported? Lines are named like '11-25h2-w' (Home, Pro) and '11-25h2-e'
    (Enterprise, Education)."""
    today = today or date.today()
    if not build or not cve.db_path(cfg).exists():
        return {"state": "unknown", "line": None, "until": None}
    c = _conn(cfg)
    try:
        r = c.execute("SELECT releases FROM eol_product WHERE name='windows'").fetchone()
    finally:
        c.close()
    if not r:
        return {"state": "unknown", "line": None, "until": None}
    gen = "11" if build >= 22000 else "10"
    ver = (display_version or "").lower()
    kind = "e" if re.search(r"enterprise|education", edition or "", re.I) else "w"
    by = {x["name"]: x for x in json.loads(r["releases"])}
    rel = by.get(f"{gen}-{ver}-{kind}") or by.get(f"{gen}-{ver}")
    state, until = judge(rel, today)
    return {"state": state, "line": rel["name"] if rel else None, "until": until}
