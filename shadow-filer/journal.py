"""
Phase 7: work journal. A dated record, day by day, of
  arrived    what landed in Downloads,
  filed      what was filed where (by you in the Inbox, by auto-filing, or by hand in Explorer), and undone,
  deleted    what Cleanup sent to the Recycle Bin,
  worked on  which of your folders had documents added or changed that day.

READ-ONLY for your files: it is put together from what the agent already records (predictions, the move
journal, Cleanup's history) plus file dates. The one thing it writes is its own table, `journal_touch`: a file
only remembers its LAST change, so each time the journal is built (and once a day by the running agent) the
day a file was added or changed is noted. Edit a document on Monday and again on Friday and both days stay
in the journal, provided the agent was running in between; days before the first build can only show the
last change. Nothing is opened: names, sizes and dates only.

Measured on the user's data (11 Oct 2026): 499 predictions for 497 files over 7 days, 418 of them made on
10 and 11 Oct by catch-up runs after reinstalling, not downloads on those days. So an arrival is dated by the
file's own arrival time while the file is still in Downloads, and by the day the agent noticed it only when
the file is gone.
"""
import os
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import cleanup

MAX_DAYS = 366
PER_DAY = 200          # entries listed per kind per day; the count is always the true one
_lock = threading.Lock()
_recorded = {"at": 0.0}


def _conn(db_path):
    c = sqlite3.connect(str(db_path), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS journal_touch (
        day TEXT, path TEXT, folder TEXT, name TEXT, kind TEXT, PRIMARY KEY (day, path))""")
    return c


def _has(c, table: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).date().isoformat()


def _folder(path: str, root: str, depth: int) -> str:
    """'1-Projects/Acme' for a file anywhere under D:/Organized/1-Projects/Acme/... ('' = directly in the root)."""
    rel = os.path.relpath(os.path.dirname(path), root).replace("\\", "/")
    return "" if rel == "." else "/".join(rel.split("/")[:depth])


def record_touches(cfg: dict, min_gap: float = 600.0, today: date | None = None) -> int:
    """Note, for every document in the PARA tree, the day it was added or last changed. Returns how many
    new notes were made. Cheap (file dates only), and skipped if done in the last `min_gap` seconds."""
    with _lock:
        if time.time() - _recorded["at"] < min_gap:
            return 0
        root = Path(cfg["para_root"])
        if not root.is_dir():
            return 0
        files, stats = [], {"files_para": 0, "cloud_only_para": 0}
        cleanup._walk(root, None, "para", files, [], [], stats, False)
        oldest = ((today or date.today()) - timedelta(days=MAX_DAYS)).isoformat()
        depth = int(cfg.get("destination_depth", 2))
        rows = []
        for f in files:
            day = _day(f["added"])
            if day < oldest:
                continue
            # 'added' = put or created here that day (a copy keeps its older modified date);
            # 'changed' = a file that was already here, edited that day
            kind = "added" if f["added"] > f["mtime"] + 1 or _born(f) >= day else "changed"
            rows.append((day, f["path"], _folder(f["path"], str(root), depth), f["name"], kind))
        c = _conn(cfg["database"])
        try:
            before = c.total_changes
            c.executemany("INSERT OR IGNORE INTO journal_touch VALUES (?,?,?,?,?)", rows)
            c.execute("DELETE FROM journal_touch WHERE day < ?", (oldest,))
            c.commit()
            n = c.total_changes - before
        finally:
            c.close()
        _recorded["at"] = time.time()
        return n


def _born(f: dict) -> str:
    try:
        st = os.stat(f["path"])
        b = getattr(st, "st_birthtime", None) or st.st_ctime
        return _day(b)
    except OSError:
        return _day(f["added"])


def _arrivals(c, cfg: dict, since: str) -> list:
    """One entry per file the agent has seen in a watched folder: (day, time, name, path, size, known)."""
    if not _has(c, "predictions"):
        return []
    out, seen = [], set()
    for r in c.execute("SELECT ts, path, filename, size, predicted, method FROM predictions ORDER BY id DESC"):
        key = os.path.normcase(r["path"])
        if key in seen:
            continue
        seen.add(key)
        when, exact = r["ts"], False
        try:   # still there: its own arrival time is better than the moment the agent noticed it
            st = os.stat(r["path"])
            when, exact = datetime.fromtimestamp(cleanup.added_time(st)).isoformat(timespec="seconds"), True
        except OSError:
            pass
        if when[:10] >= since:
            out.append({"ts": when, "name": r["filename"], "path": r["path"], "size": r["size"],
                        "still_there": exact, "suggested": r["predicted"] if r["method"] != "error" else None})
    return out


def build(cfg: dict, days: int = 30, today: date | None = None) -> dict:
    """The journal for the last `days` days, newest day first. Days on which nothing happened are left out."""
    days = max(1, min(int(days), MAX_DAYS))
    today = today or date.today()
    since = (today - timedelta(days=days - 1)).isoformat()
    record_touches(cfg, today=today)
    c = _conn(cfg["database"])
    try:
        arrived = _arrivals(c, cfg, since)
        filed, undone = [], []
        if _has(c, "moves"):
            for r in c.execute("SELECT ts, undone_ts, src, dest, size, folder, source, status FROM moves "
                               "WHERE status IN ('moved', 'undone')"):
                name = os.path.basename(r["dest"] or r["src"] or "")
                auto = (r["source"] or "").startswith("auto")
                if r["ts"][:10] >= since:
                    filed.append({"ts": r["ts"], "name": name, "path": r["dest"], "size": r["size"],
                                  "folder": r["folder"], "how": "auto" if auto else "inbox",
                                  "undone": r["status"] == "undone"})
                if r["status"] == "undone" and (r["undone_ts"] or "")[:10] >= since:
                    undone.append({"ts": r["undone_ts"], "name": name, "path": r["src"], "size": r["size"],
                                   "folder": r["folder"], "how": "auto" if auto else "inbox"})
        if _has(c, "predictions"):   # filed by hand in Explorer: the agent noticed the file in a folder later
            via_inbox = {(f["name"].lower(), f["ts"][:10]) for f in filed}
            for r in c.execute("SELECT actual_ts, filename, size, actual FROM predictions "
                               "WHERE actual IS NOT NULL AND actual_ts >= ?", (since,)):
                if (r["filename"].lower(), r["actual_ts"][:10]) not in via_inbox:
                    filed.append({"ts": r["actual_ts"], "name": r["filename"], "path": None, "size": r["size"],
                                  "folder": r["actual"], "how": "hand", "undone": False})
        deleted = []
        if _has(c, "cleanup_action"):
            for r in c.execute("SELECT ts, path, size, category, mode FROM cleanup_action "
                               "WHERE result='deleted' AND ts >= ?", (since,)):
                deleted.append({"ts": r["ts"], "name": os.path.basename(r["path"]), "path": r["path"],
                                "size": r["size"], "category": r["category"], "mode": r["mode"]})
        touches = [dict(r) for r in c.execute(
            "SELECT day, path, folder, name, kind FROM journal_touch WHERE day >= ? AND day <= ?",
            (since, today.isoformat()))]
    finally:
        c.close()

    # a file filed that day is 'filed', not also 'worked on'
    filed_paths = {(os.path.normcase(f["path"]), f["ts"][:10]) for f in filed if f["path"]}
    filed_names = {(f["name"].lower(), f["folder"], f["ts"][:10]) for f in filed}
    by_day: dict = {}

    def day_of(d: str) -> dict:
        return by_day.setdefault(d, {"date": d, "arrived": [], "filed": [], "undone": [], "deleted": [], "worked": {}})

    for kind, rows in (("arrived", arrived), ("filed", filed), ("undone", undone), ("deleted", deleted)):
        for r in rows:
            day_of(r["ts"][:10])[kind].append({**r, "time": r["ts"][11:16]})
    for t in touches:
        if (os.path.normcase(t["path"]), t["day"]) in filed_paths or (t["name"].lower(), t["folder"], t["day"]) in filed_names:
            continue
        day_of(t["day"])["worked"].setdefault(t["folder"], []).append({"name": t["name"], "path": t["path"], "kind": t["kind"]})

    out_days, folders = [], {}
    totals = {"arrived": 0, "filed": 0, "auto_filed": 0, "undone": 0, "deleted": 0, "deleted_bytes": 0,
              "worked_files": 0, "active_days": 0}
    for d in sorted(by_day, reverse=True):
        e = by_day[d]
        for k in ("arrived", "filed", "undone", "deleted"):
            e[k].sort(key=lambda r: r["ts"], reverse=True)
        worked = [{"folder": f, "count": len(v), "files": sorted(v, key=lambda x: x["name"].lower())[:PER_DAY]}
                  for f, v in e["worked"].items()]
        worked.sort(key=lambda w: (-w["count"], w["folder"]))
        counts = {"arrived": len(e["arrived"]), "filed": len(e["filed"]),
                  "auto_filed": sum(1 for f in e["filed"] if f["how"] == "auto"), "undone": len(e["undone"]),
                  "deleted": len(e["deleted"]), "deleted_bytes": sum(x["size"] or 0 for x in e["deleted"]),
                  "worked_files": sum(w["count"] for w in worked), "worked_folders": len(worked)}
        for k in totals:
            totals[k] += counts.get(k, 0)
        totals["active_days"] += 1
        for f in e["filed"]:
            if not f["undone"]:
                g = folders.setdefault(f["folder"], {"folder": f["folder"], "filed": 0, "worked": 0, "days": set()})
                g["filed"] += 1
                g["days"].add(d)
        for w in worked:
            g = folders.setdefault(w["folder"], {"folder": w["folder"], "filed": 0, "worked": 0, "days": set()})
            g["worked"] += w["count"]
            g["days"].add(d)
        dt = date.fromisoformat(d)
        out_days.append({"date": d, "weekday": dt.strftime("%A"), "counts": counts,
                         "arrived": e["arrived"][:PER_DAY], "filed": e["filed"][:PER_DAY],
                         "undone": e["undone"][:PER_DAY], "deleted": e["deleted"][:PER_DAY], "worked": worked})
    by_folder = [{"folder": g["folder"] or "(top of your folders)", "filed": g["filed"], "worked": g["worked"],
                  "days": len(g["days"])} for g in folders.values()]
    by_folder.sort(key=lambda g: (-(g["filed"] + g["worked"]), g["folder"]))
    rep = {"days_asked": days, "from": since, "to": today.isoformat(), "totals": totals, "folders": by_folder,
           "days": out_days}
    rep["text"] = as_text(rep)
    return rep


def as_text(rep: dict) -> str:
    """The same journal as plain text, for pasting into a status report or a timesheet."""
    t = rep["totals"]
    lines = [f"Work journal {rep['from']} to {rep['to']}",
             f"{t['arrived']} arrived, {t['filed']} filed ({t['auto_filed']} automatically), {t['deleted']} deleted "
             f"({cleanup.human(t['deleted_bytes'])}), {t['worked_files']} documents added or changed, "
             f"{t['active_days']} active day{'' if t['active_days'] == 1 else 's'}", ""]
    if rep["folders"]:
        lines.append("By folder:")
        for g in rep["folders"][:15]:
            bits = [f"{g['worked']} added or changed" if g["worked"] else "", f"{g['filed']} filed" if g["filed"] else ""]
            lines.append(f"  {g['folder']}: {', '.join(b for b in bits if b)} ({g['days']} day{'' if g['days'] == 1 else 's'})")
        lines.append("")
    for d in rep["days"]:
        lines.append(f"{d['weekday']} {d['date']}")
        for w in d["worked"]:
            names = ", ".join(f["name"] for f in w["files"][:6]) + (f" and {w['count'] - 6} more" if w["count"] > 6 else "")
            lines.append(f"  Worked on {w['folder'] or '(top of your folders)'}: {names}")
        for f in d["filed"]:
            how = {"auto": " (automatically)", "hand": " (by hand)"}.get(f["how"], "")
            lines.append(f"  Filed {f['name']} -> {f['folder']}{how}{' (undone later)' if f['undone'] else ''}")
        for u in d["undone"]:
            lines.append(f"  Undid the move of {u['name']} (back in Downloads)")
        c = d["counts"]
        if c["arrived"]:
            names = ", ".join(a["name"] for a in d["arrived"][:5]) + (f" and {c['arrived'] - 5} more" if c["arrived"] > 5 else "")
            lines.append(f"  Arrived in Downloads ({c['arrived']}): {names}")
        if c["deleted"]:
            lines.append(f"  Deleted {c['deleted']} file{'' if c['deleted'] == 1 else 's'} ({cleanup.human(c['deleted_bytes'])})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
