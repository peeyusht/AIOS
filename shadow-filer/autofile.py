"""
Phase 3: auto-filing, earned folder by folder.

A folder becomes "proven" only from YOUR decisions on the Inbox page, separately for each kind of
suggestion (rule, file-name match, similar documents): being right about a folder one way says nothing
about another way.
  - a decision counts as agreement when the folder was the first suggestion and you filed the file there;
  - it counts against when you filed somewhere else, or undid a move into that folder;
  - a folder needs at least `min_decisions` decisions (never fewer than 20), and `min_rate` agreement
    (never under 90%) over its last `window`, for that kind of suggestion;
  - undoing an AUTO-move is the strongest "no": everything that folder had earned is discarded, for every
    kind of suggestion, and it has to be proven again from zero.
What the first suggestion was is worked out on the server when you file (web_ui.py), not taken from the page.
When the switch is on, a file is auto-filed only if ALL hold:
  - its first suggestion's folder is proven for that kind of suggestion,
  - that suggestion is a rule, a file-name match, or similar-documents at >= `min_score`,
  - the file has been in Downloads for `delay_minutes` (time to open it, rename it or file it yourself),
    counted from when it arrived, not from a modified date it kept from somewhere else,
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
# The bar a folder must clear can be raised in Settings, never lowered below this.
FLOORS = {"min_decisions": 20, "min_rate": 0.9}
_lock = threading.Lock()
STATE = {"last_run": None, "last_moved": 0, "last_error": None}


def settings(cfg: dict) -> dict:
    raw = cfg.get("autofile")
    s = {**DEFAULTS, **(raw if isinstance(raw, dict) else {})}
    for k, d in DEFAULTS.items():      # a hand-edited config.yaml can hold anything
        if isinstance(d, bool):
            s[k] = s[k] is True
        else:
            try:
                s[k] = type(d)(s[k])
            except (TypeError, ValueError):
                s[k] = d
    s["min_decisions"] = max(FLOORS["min_decisions"], s["min_decisions"])
    s["min_rate"] = min(1.0, max(FLOORS["min_rate"], s["min_rate"]))
    s["window"] = max(s["window"], s["min_decisions"])
    s["min_score"] = min(1.0, max(0.5, s["min_score"]))
    for k in ("delay_minutes", "max_per_run", "every_minutes"):
        s[k] = max(1, s[k])
    return s


def _rows(cfg: dict):
    import mover
    c = mover._conn(cfg["database"])
    try:
        return [dict(r) for r in c.execute(
            "SELECT id, ts, undone_ts, folder, top_folder, top_source, rank, source, status "
            "FROM moves ORDER BY id")]
    finally:
        c.close()


def trust(cfg: dict) -> dict:
    """Evidence from your decisions. Returns {(folder, kind of suggestion): {...}}."""
    s = settings(cfg)
    events: dict = {}    # (folder, kind) -> [(ts, agreed, is the undo of an auto-move)]
    revoked: dict = {}   # folder -> when you last undid an auto-move into it

    for r in _rows(cfg):
        if r["status"] not in ("moved", "undone"):
            continue                           # interrupted move: not a decision
        src = r["source"] or ""
        if src.startswith("auto"):
            if r["status"] == "undone":        # you reversed an auto-move: that folder starts again
                ts = r["undone_ts"] or r["ts"]
                revoked[r["folder"]] = max(revoked.get(r["folder"], ""), ts)
                events.setdefault((r["folder"], src[5:] or "unknown"), []).append((ts, False, True))
            continue
        top = r["top_folder"]
        if not top:
            continue                           # filed with no suggestion: says nothing about any folder
        agreed = r["status"] == "moved" and r["folder"] == top and r["rank"] == 1
        kind = r["top_source"] or (src if agreed else None) or "unknown"
        events.setdefault((top, kind), []).append((r["ts"], agreed, False))
    out = {}
    for (folder, kind), ev in events.items():
        since = revoked.get(folder)
        if since:
            ev = [e for e in ev if e[0] > since or (e[2] and e[0] == since)]
        ev = sorted(ev, key=lambda e: e[0])[-s["window"]:]
        n = len(ev)
        agree = sum(1 for e in ev if e[1])
        rate = agree / n if n else 0.0
        proven = n >= s["min_decisions"] and rate >= s["min_rate"]
        out[(folder, kind)] = {"folder": folder, "source": kind, "decisions": n, "agreed": agree,
                               "rate": round(rate, 3), "proven": proven,
                               "needed": max(0, s["min_decisions"] - n), "revoked": since}
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
    t = proven.get((folder, top["source"]))
    if not t or not t["proven"]:
        need = t["needed"] if t else s["min_decisions"]
        more = f"{need} more decision{'' if need == 1 else 's'}"
        if need and t and t.get("revoked"):
            why = f"you undid an auto-move into this folder ({more} to prove it again)"
        elif need:
            why = f"folder not proven yet for this kind of suggestion ({more})"
        else:
            why = f"you agreed only {round(t['rate'] * 100)}% of the time"
        return {"auto": False, "folder": folder, "why": why}
    if item["path"] in hints:
        return {"auto": False, "folder": folder, "why": "flagged by Cleanup"}
    if sug.get("duplicate"):
        return {"auto": False, "folder": folder, "why": "identical file already filed"}
    if now - (item.get("added") or item["mtime"]) < s["delay_minutes"] * 60:
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
        if not any(t["proven"] and t["source"] in ALLOWED_SOURCES for t in proven.values()):
            STATE.update(last_run=datetime.now().isoformat(timespec="seconds"), last_moved=0)
            return 0
        hints = _cleanup_paths()
        files = suggest.list_inbox(cfg, mover.dismissed(cfg), lambda p: sa.is_ignored(p, cfg))
        now, moved = time.time(), 0
        for it in files:
            if moved >= s["max_per_run"]:
                break
            if now - (it.get("added") or it["mtime"]) < s["delay_minutes"] * 60:
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
                            "top_folder": d["folder"], "top_score": top.get("score"),
                            "top_source": top["source"]}, None)
                moved += 1
                try:
                    import web_ui
                    web_ui._reindex(it["path"])  # the copy in PARA is picked up by the folder watcher
                except Exception:
                    pass
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
