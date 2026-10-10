"""
Phase 3: auto-filing, earned folder by folder.

A folder becomes "proven" only from YOUR decisions on the Inbox page:
  - a decision counts as agreement when the folder was the first suggestion and you filed the file there;
  - it counts against when you filed somewhere else, or undid a move into that folder (including an
    auto-move: undoing what auto-filing did is the strongest "no");
  - a folder needs at least `min_decisions` decisions, and `min_rate` agreement over its last `window`.
When the switch is on, a file is auto-filed only if ALL hold:
  - its first suggestion's folder is proven,
  - that suggestion is a rule, a file-name match, or similar-documents at >= `min_score`,
  - the file has sat in Downloads for `delay_minutes` (time to open it, rename it or file it yourself),
  - Cleanup doesn't flag it (duplicate already filed, partial download, ...), it isn't password-protected,
  - the usual mover.py guarantees: never overwrite, verify cross-drive copies, journal, Undo.
Undo an auto-move and that folder loses trust immediately; drop below the rate and it's back to suggestions.
"""
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

DEFAULTS = {
    "enabled": False,       # master switch (Settings › Auto-filing)
    "min_decisions": 20,    # your Inbox decisions about a folder before it can be proven
    "min_rate": 0.9,        # share of those where you agreed with the first suggestion
    "window": 30,           # judge on the most recent N decisions per folder
    "min_score": 0.95,      # similar-documents suggestions must be at least this strong
    "delay_minutes": 15,    # leave new downloads alone this long
    "max_per_run": 20,
    "every_minutes": 5,
}
ALLOWED_SOURCES = ("rule", "name", "similar")
_lock = threading.Lock()
STATE = {"last_run": None, "last_moved": 0, "last_error": None}


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("autofile") or {})}


def _rows(cfg: dict):
    import mover
    c = mover._conn(cfg["database"])
    try:
        return [dict(r) for r in c.execute(
            "SELECT id, ts, folder, top_folder, rank, source, status FROM moves ORDER BY id")]
    finally:
        c.close()


def trust(cfg: dict) -> dict:
    """Per-folder evidence from your decisions. Returns {folder: {...}}."""
    s = settings(cfg)
    per: dict = {}

    def add(folder, ok, ts):
        d = per.setdefault(folder, {"folder": folder, "events": []})
        d["events"].append((ts, ok))

    for r in _rows(cfg):
        auto = (r["source"] or "").startswith("auto")
        if auto:
            if r["status"] == "undone":       # you reversed an auto-move: a clear "no" for that folder
                add(r["folder"], False, r["ts"])
            continue
        top = r["top_folder"]
        if not top:
            continue                           # filed with no suggestion: says nothing about any folder
        if r["status"] == "undone":
            add(top, False, r["ts"])           # moved then undone: the suggestion wasn't right
        elif r["folder"] == top and r["rank"] == 1:
            add(top, True, r["ts"])
        else:
            add(top, False, r["ts"])           # you chose another folder
    out = {}
    for folder, d in per.items():
        ev = d["events"][-s["window"]:]
        n = len(ev)
        agree = sum(1 for _, ok in ev if ok)
        rate = agree / n if n else 0.0
        proven = n >= s["min_decisions"] and rate >= s["min_rate"]
        out[folder] = {"folder": folder, "decisions": n, "agreed": agree, "rate": round(rate, 3),
                       "proven": proven, "needed": max(0, s["min_decisions"] - n)}
    return out


def decide(cfg: dict, item: dict, sug: dict, proven: dict, hints: dict, now: float) -> dict:
    """Would this file be auto-filed? Returns {"auto": bool, "folder", "why"}."""
    s = settings(cfg)
    cands = sug.get("candidates") or []
    if not cands:
        return {"auto": False, "why": "no suggestion"}
    top = cands[0]
    folder = top["folder"]
    if top.get("source") not in ALLOWED_SOURCES:
        return {"auto": False, "folder": folder, "why": "only the model's guess"}
    if top.get("exists") is False:
        return {"auto": False, "folder": folder, "why": "folder missing"}
    if top["source"] == "similar" and (top.get("score") or 0) < s["min_score"]:
        return {"auto": False, "folder": folder, "why": f"suggestion only {round((top.get('score') or 0) * 100)}%"}
    t = proven.get(folder)
    if not t or not t["proven"]:
        need = t["needed"] if t else s["min_decisions"]
        return {"auto": False, "folder": folder,
                "why": f"folder not proven yet ({need} more decision{'' if need == 1 else 's'})" if need
                else f"you agreed only {round((t or {}).get('rate', 0) * 100)}% of the time"}
    if item["path"] in hints:
        return {"auto": False, "folder": folder, "why": "flagged by Cleanup"}
    if sug.get("duplicate"):
        return {"auto": False, "folder": folder, "why": "identical file already filed"}
    if now - item["mtime"] < s["delay_minutes"] * 60:
        return {"auto": False, "folder": folder, "why": f"waiting {s['delay_minutes']} min after download",
                "soon": True}
    return {"auto": True, "folder": folder, "why": f"{top['source']} · folder proven ({t['agreed']}/{t['decisions']})"}


def preview(cfg: dict, items_with_sug: list, hints: dict) -> dict:
    proven = trust(cfg)
    now = time.time()
    out = {}
    for it, sug in items_with_sug:
        out[it["path"]] = decide(cfg, it, sug, proven, hints, now)
    return out


def run_once(cfg: dict, sg, db, log=None) -> int:
    """One pass: auto-file eligible files. Returns how many were moved."""
    import mover
    import suggest
    import shadow_agent as sa
    s = settings(cfg)
    if not s["enabled"] or sg is None:
        return 0
    with _lock:
        proven = trust(cfg)
        if not any(t["proven"] for t in proven.values()):
            STATE.update(last_run=datetime.now().isoformat(timespec="seconds"), last_moved=0)
            return 0
        hints = _cleanup_paths()
        files = suggest.list_inbox(cfg, mover.dismissed(cfg), lambda p: sa.is_ignored(p, cfg))
        now, moved = time.time(), 0
        for it in files:
            if moved >= s["max_per_run"]:
                break
            if now - it["mtime"] < s["delay_minutes"] * 60:
                continue
            sug = sg.suggest(it["path"])
            d = decide(cfg, it, sug, proven, hints, now)
            if not d["auto"]:
                continue
            if it["ext"] == ".pdf" and sa.is_encrypted_pdf(__import__("pathlib").Path(it["path"])):
                continue
            top = sug["candidates"][0]
            try:
                mover.move(cfg, it["path"], d["folder"],
                           {"size": it["size"], "source": "auto:" + top["source"], "rank": 1,
                            "top_folder": d["folder"], "top_score": top.get("score")}, None)
                moved += 1
                if log:
                    log.info("AUTO-FILED %s -> %s (%s)", it["name"], d["folder"], d["why"])
            except mover.MoveError as e:
                if log:
                    log.info("auto-file skipped %s: %s", it["name"], e)
        STATE.update(last_run=datetime.now().isoformat(timespec="seconds"), last_moved=moved, last_error=None)
        return moved


def _cleanup_paths() -> dict:
    try:
        import cleanup
        rep = cleanup.load_report() or {}
        return {it["path"]: it["category"] for it in rep.get("items", []) if not it.get("is_dir")}
    except Exception:
        return {}


def summary(cfg: dict) -> dict:
    """Auto-moves in the last 24 hours (for the Inbox page)."""
    import mover
    since = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    rows = [r for r in mover.journal(cfg, 500) if (r["source"] or "").startswith("auto") and r["ts"] >= since]
    return {"last24h": len(rows), "undone": sum(1 for r in rows if r["status"] == "undone"), **STATE}


def start(cfg: dict, get_suggester, db, log=None):
    """Background loop inside the agent. Does nothing while the switch is off."""
    def loop():
        while True:
            try:
                if settings(cfg)["enabled"]:
                    run_once(cfg, get_suggester(), db, log)
            except Exception as e:  # never take the agent down
                STATE["last_error"] = str(e)[:300]
                if log:
                    log.warning("auto-filing: %s", e)
            time.sleep(max(60, settings(cfg)["every_minutes"] * 60))
    threading.Thread(target=loop, daemon=True, name="autofile").start()
