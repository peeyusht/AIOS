"""
Document watch (Phase 5): two things worth knowing about, found in text the search index already holds.

1. Dates that matter: an expiry, renewal, due or "valid until" date written in a document (insurance,
   contracts, licences, IDs), so you hear about it before it passes rather than after.
2. Sensitive files left in Downloads: files whose text holds a PAN, an Aadhaar number, a payment card
   number, bank account details, a passport number or a private key.

How it works: it reads the passages search.db already stored (search_index.py); no file is opened again.
A date counts only when it stands next to a phrase that says what it is ("valid till", "expiry date",
"due date"...). Numbers count only when they pass the check real ones pass (Verhoeff for Aadhaar, Luhn for
cards) AND look the part: written in the usual groups, or with a word nearby that says what they are. The
check alone is not enough: one random 12-digit number in ten passes it, and logs and spreadsheets are full
of long numbers. A PAN counts only if it is a person's (4th letter P); company PANs are printed on every
invoice.

Measured on the index (11 Oct 2026, 2,256 files): 41 dates within 90 days past or still ahead, in 36 files
(quotes and purchase orders with a validity, invoices with a due date, a passport, a certificate), and 52
older ones that are counted but not listed. A sample of 28 had one wrong ("Validity: from <date>" is a
start, since fixed). Sensitive: see the Watch page; the first version flagged 67 files, of which the
Aadhaar and card hits in logs and spreadsheets were chance matches, hence the rule above.

SAFETY: read-only. Nothing is moved, changed or deleted. Nothing leaves this PC. The numbers themselves
are never stored or sent to the console: a finding says "1 PAN, 2 card numbers", not which. search.db
already holds the text; this adds no new copy of it.
"""
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULTS = {
    "enabled": True,
    "soon_days": 60,           # a date this close is "coming up"
    "keep_expired_days": 90,   # dates that passed longer ago than this are counted but not listed
    "years_ahead": 15,         # further away than this is more likely a misread than a deadline
}

# --------------------------------------------------------------------------- dates
MONTHS = {m: i for i, names in enumerate(
    ["jan january", "feb february", "mar march", "apr april", "may", "jun june", "jul july", "aug august",
     "sep sept september", "oct october", "nov november", "dec december"], 1) for m in names.split()}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_D = r"(?:0?[1-9]|[12]\d|3[01])"
_DATE = (rf"(?:(?P<d1>{_D})\s?[/.\-]\s?(?P<m1>0?[1-9]|1[0-2])\s?[/.\-]\s?(?P<y1>(?:19|20)\d\d|\d\d)(?!\d)"   # 31/12/2026
         rf"|(?P<y2>(?:19|20)\d\d)-(?P<m2>0[1-9]|1[0-2])-(?P<d2>0[1-9]|[12]\d|3[01])(?!\d)"                    # 2026-12-31
         rf"|(?P<d3>{_D})(?:st|nd|rd|th)?[\s\-.,]{{0,3}}(?P<m3>{_MON})[a-z]*[\s\-.,]{{0,3}}(?P<y3>(?:19|20)\d\d)"  # 31 Dec 2026
         rf"|(?P<m4>{_MON})[a-z]*[\s.]{{0,2}}(?P<d4>{_D})(?:st|nd|rd|th)?[\s,]{{1,3}}(?P<y4>(?:19|20)\d\d))")  # Dec 31, 2026
DATE_RX = re.compile(_DATE, re.I)
# phrase -> what kind of date follows it
PHRASES = [
    ("expires", r"expir(?:y|es|ation|ing)(?:\s+date)?|date\s+of\s+expiry|exp\.?\s*date"),
    ("valid until", r"valid\s+(?:till|until|up\s?to|upto|thru|through|from)|validity(?:\s+(?:date|period|upto|up\s?to|till))?"),
    ("due", r"(?:payment\s+)?due\s+(?:date|on|by)|last\s+date|pay\s+by|deadline"),
    ("renewal", r"renew(?:al)?(?:\s+(?:date|due|on|by))?|next\s+due"),
    ("ends", r"(?:policy|cover|coverage|contract|agreement|lease|licen[cs]e|subscription|term|warranty)\s+"
             r"(?:end(?:s|ing)?|expir\w+|period\s+to|to\s+date)|end\s+date|period\s+of\s+insurance.{0,40}?\bto\b|maturity(?:\s+date)?"),
]
PHRASE_RX = re.compile("|".join(f"(?P<p{i}>{rx})" for i, (_, rx) in enumerate(PHRASES)), re.I)
GAP = 40  # how far after the phrase the date may start


def _as_date(m) -> date | None:
    g = m.groupdict()
    for n in "1234":
        if g.get("d" + n):
            d, mo, y = g["d" + n], g["m" + n], g["y" + n]
            break
    else:
        return None
    try:
        month = int(mo) if mo.isdigit() else MONTHS[mo.lower()]
        year = int(y)
        if year < 100:
            year += 2000
        return date(year, month, int(d))
    except (ValueError, KeyError):
        return None


def find_dates(text: str, today: date | None = None, years_ahead: int = 15) -> list[dict]:
    """Dates that follow a phrase saying what they are. [{date, kind, context}] in text order."""
    today = today or date.today()
    out, seen = [], set()
    for pm in PHRASE_RX.finditer(text):
        kind = next(PHRASES[int(k[1:])][0] for k, v in pm.groupdict().items() if v)
        window = text[pm.end(): pm.end() + GAP + 24]
        dm = DATE_RX.search(window)
        if not dm or dm.start() > GAP or "\n\n" in window[:dm.start()]:
            continue
        if re.search(r"\b(?:from|since|w\.?e\.?f\.?|starting|effective)\W*$", pm.group() + window[:dm.start()], re.I):
            # "valid from 1 Jan 2026 to 31 Dec 2026": the first date is the start; take the one after "to"
            rest = window[dm.end():] + text[pm.end() + len(window): pm.end() + len(window) + 40]
            to = re.match(r"\s*(?:to|till|until|upto|up to|through|-|–)\s*", rest, re.I)
            dm = DATE_RX.match(rest, to.end()) if to else None
            if not dm:
                continue
        d = _as_date(dm)
        if d is None or not (today - timedelta(days=366 * 3) <= d <= today + timedelta(days=366 * years_ahead)):
            continue
        if (d, kind) in seen:
            continue
        seen.add((d, kind))
        a, b = max(0, pm.start() - 50), min(len(text), pm.end() + dm.end() + 20)
        out.append({"date": d.isoformat(), "kind": kind, "context": re.sub(r"\s+", " ", text[a:b]).strip()})
    return out


# --------------------------------------------------------------------------- sensitive data
def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        n = ord(ch) - 48
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
       [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
       [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
       [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
       [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
       [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def _verhoeff(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VD[c][_VP[i % 8][ord(ch) - 48]]
    return c == 0


PAN_RX = re.compile(r"(?<![A-Z0-9])[A-Z]{3}P[A-Z]\d{4}[A-Z](?![A-Z0-9])")  # 4th letter P = a person
AADHAAR_WORD = re.compile(r"aadha?ar|uidai|\buid\b", re.I)
CARD_WORD = re.compile(r"\b(?:card|visa|master\s?card|rupay|amex|american express|credit|debit)\b", re.I)
GROUPED_12 = re.compile(r"\d{4}[ -]\d{4}[ -]\d{4}")
GROUPED_CARD = re.compile(r"\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,4}|\d{4}[ -]\d{6}[ -]\d{5}")
AADHAAR_RX = re.compile(r"(?<![\d.])(?<!\d[ -])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![ -]?\d)(?!\.)")  # not part of a longer number
CARD_RX = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d.])")
IFSC_RX = re.compile(r"(?<![A-Z0-9])[A-Z]{4}0[A-Z0-9]{6}(?![A-Z0-9])")
ACCOUNT_RX = re.compile(r"(?:a/?c|acct|account)\s*(?:no\.?|number|num|#)?\s*[:\-]?\s*(\d{9,18})(?!\d)", re.I)
PASSPORT_RX = re.compile(r"passport\s*(?:no\.?|number|num|#)?\s*[:\-]?\s*([A-Z][ -]?\d{7})(?!\d)", re.I)
KEY_RX = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY")
HIGH = {"aadhaar", "card", "passport", "key"}   # identity or money on its own; a PAN or account number less so
KINDS = {"pan": "PAN", "aadhaar": "Aadhaar number", "card": "payment card number", "bank": "bank account details",
         "passport": "passport number", "key": "private key"}


def find_sensitive(text: str) -> dict:
    """{kind: how many different ones} for one piece of text. The values themselves are not returned."""
    found: dict[str, set] = {}
    for m in PAN_RX.finditer(text):
        found.setdefault("pan", set()).add(m.group())
    aadhaar_named, card_named = bool(AADHAAR_WORD.search(text)), bool(CARD_WORD.search(text))
    for m in AADHAAR_RX.finditer(text):
        d = re.sub(r"\D", "", m.group())
        if _verhoeff(d) and len(set(d)) > 2 and (aadhaar_named or GROUPED_12.fullmatch(m.group())):
            found.setdefault("aadhaar", set()).add(d)
    for m in CARD_RX.finditer(text):
        raw = m.group().strip()
        d = re.sub(r"\D", "", raw)
        if 13 <= len(d) <= 19 and d[0] in "3456" and _luhn(d) and len(set(d)) > 3 and (
                card_named or GROUPED_CARD.fullmatch(raw)):
            found.setdefault("card", set()).add(d)
    accounts = {m.group(1) for m in ACCOUNT_RX.finditer(text)}
    if accounts and (IFSC_RX.search(text) or re.search(r"\bbank\b", text, re.I)):
        found.setdefault("bank", set()).update(accounts)
    for m in PASSPORT_RX.finditer(text):
        found.setdefault("passport", set()).add(re.sub(r"[ -]", "", m.group(1)).upper())
    if KEY_RX.search(text):
        found.setdefault("key", set()).add("key")
    return {k: len(v) for k, v in found.items()}


# --------------------------------------------------------------------------- the report
def settings(cfg: dict) -> dict:
    raw = cfg.get("watch")
    return {**DEFAULTS, **(raw if isinstance(raw, dict) else {})}


_cache = {"key": None, "at": 0.0, "report": None}
_lock = threading.Lock()


def _dismissed(db_path: Path) -> set:
    c = sqlite3.connect(str(db_path), timeout=30)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS watch_dismissed (path TEXT, kind TEXT, key TEXT, ts TEXT, "
                  "PRIMARY KEY (path, kind, key))")
        return {(r[0], r[1], r[2]) for r in c.execute("SELECT path, kind, key FROM watch_dismissed")}
    finally:
        c.close()


def dismiss(db_path: Path, path: str, kind: str, key: str, undo: bool = False) -> None:
    """Hide one finding ('date' with key '<date>|<kind>', or 'sensitive' with key ''), or bring it back."""
    c = sqlite3.connect(str(db_path), timeout=30)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS watch_dismissed (path TEXT, kind TEXT, key TEXT, ts TEXT, "
                  "PRIMARY KEY (path, kind, key))")
        if undo:
            c.execute("DELETE FROM watch_dismissed WHERE path=? AND kind=? AND key=?", (path, kind, key))
        else:
            c.execute("INSERT OR REPLACE INTO watch_dismissed VALUES (?,?,?,?)",
                      (path, kind, key, datetime.now().isoformat(timespec="seconds")))
        c.commit()
    finally:
        c.close()
    _cache["key"] = None


def scan(search_db: Path, today: date | None = None, s: dict | None = None) -> dict:
    """Read every stored passage once. Returns {"dates": [...], "sensitive": [...], counts}; no dismissals applied."""
    s = {**DEFAULTS, **(s or {})}
    today = today or date.today()
    conn = sqlite3.connect(f"file:{Path(search_db).as_posix()}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        files = {r["path"]: dict(r) for r in conn.execute(
            "SELECT path, source, name, folder, ext, size, mtime_ns FROM files")}
        dates, per_file_sens = {}, {}
        for r in conn.execute("SELECT path, text FROM chunks ORDER BY path, idx"):
            f = files.get(r["path"])
            if not f or not r["text"]:
                continue
            body = r["text"].split("\n", 1)[1] if "\n" in r["text"] else ""  # first line is the name/folder header
            if not body:
                continue
            for d in find_dates(body, today, s["years_ahead"]):
                dates.setdefault((r["path"], d["date"], d["kind"]), d)
            if f["source"] == "inbox":
                for k, n in find_sensitive(body).items():
                    cur = per_file_sens.setdefault(r["path"], {})
                    cur[k] = max(cur.get(k, 0), n)
    finally:
        conn.close()

    def meta(path):
        f = files[path]
        return {"path": path, "name": f["name"], "folder": f["folder"], "source": f["source"], "size": f["size"],
                "modified": datetime.fromtimestamp(f["mtime_ns"] / 1e9).isoformat(timespec="seconds")}

    # the same document often sits in several places (a download and its filed copy, "name (1).pdf"):
    # one entry per date and wording, the filed copy first, the others listed under it
    groups: dict = {}
    for (path, iso, kind), d in dates.items():
        wording = re.sub(r"\W+", "", d["context"].lower())[-60:]
        groups.setdefault((iso, kind, wording), []).append((path, d))
    out_dates, old = [], 0
    for (iso, kind, _), members in groups.items():
        days = (date.fromisoformat(iso) - today).days
        if days < -s["keep_expired_days"]:
            old += 1
            continue
        members.sort(key=lambda m: (files[m[0]]["source"] != "para", len(m[0]), m[0]))
        path, d = members[0]
        status = "passed" if days < 0 else "soon" if days <= s["soon_days"] else "later"
        out_dates.append({**meta(path), "date": iso, "kind": kind, "days": days, "status": status,
                          "context": d["context"][:220], "key": f"{iso}|{kind}",
                          "copies": [m[0] for m in members[1:]]})
    out_dates.sort(key=lambda x: (x["days"] < 0, abs(x["days"]) if x["days"] < 0 else x["days"]))
    out_sens = [{**meta(p), "found": [{"kind": k, "label": KINDS[k], "count": n} for k, n in sorted(kinds.items())],
                 "level": "high" if HIGH & set(kinds) else "medium", "key": ""}
                for p, kinds in per_file_sens.items()]
    out_sens.sort(key=lambda x: (x["level"] != "high", -len(x["found"]), x["name"].lower()))
    return {"scanned_at": datetime.now().isoformat(timespec="seconds"), "files_read": len(files),
            "dates": out_dates, "older_passed": old, "sensitive": out_sens}


def report(cfg: dict, search_db: Path, force: bool = False) -> dict:
    """What the Watch page shows: scan results minus what you dismissed. Cached for 10 minutes or until
    the index changes."""
    s = settings(cfg)
    if not s["enabled"]:
        return {"enabled": False, "dates": [], "sensitive": [], "counts": {"soon": 0, "passed": 0, "later": 0, "sensitive": 0}}
    try:
        st = Path(search_db).stat()
        key = (st.st_size, st.st_mtime_ns, date.today().isoformat(), tuple(sorted(s.items())))
    except OSError:
        return {"enabled": True, "dates": [], "sensitive": [], "error": "The search index isn't built yet.",
                "counts": {"soon": 0, "passed": 0, "later": 0, "sensitive": 0}}
    with _lock:
        if force or _cache["key"] != key or time.time() - _cache["at"] > 600:
            _cache.update(key=key, at=time.time(), report=scan(search_db, None, s))
        rep = _cache["report"]
    gone = _dismissed(cfg["database"])
    dates = [d for d in rep["dates"] if (d["path"], "date", d["key"]) not in gone]
    sens = [x for x in rep["sensitive"] if (x["path"], "sensitive", "") not in gone]
    counts = {k: sum(1 for d in dates if d["status"] == k) for k in ("soon", "passed", "later")}
    counts["sensitive"] = len(sens)
    return {"enabled": True, "scanned_at": rep["scanned_at"], "files_read": rep["files_read"],
            "settings": {k: s[k] for k in ("soon_days", "keep_expired_days")},
            "dates": dates, "older_passed": rep["older_passed"], "sensitive": sens, "counts": counts,
            "dismissed": len(gone)}
