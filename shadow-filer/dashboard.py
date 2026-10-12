"""
Dashboard: one screen of what needs attention and what happened, put together from what the other pages
already know. READ-ONLY and local: it asks no question of Windows or the internet itself, it only reads the
last results the other modules keep (the Inbox list, the Cleanup report, Watch, the applications list, the
vulnerability comparison, the work journal, the system summary). Each part is gathered on its own: one part
failing leaves an `error` in its place and the rest still shows.

It follows the other pages' rules about what may be shown: Watch's sensitive files are a count here, never
names of what was found; a vulnerable program is named with its counts, as on the Security page.
"""
import time
from datetime import date, datetime, timedelta

TOP = 5


def _part(fn):
    try:
        return fn()
    except Exception as e:  # one broken part must not blank the dashboard
        return {"error": str(e)[:200]}


def _inbox(cfg: dict, files: list | None) -> dict:
    import autofile
    files = files or []
    oldest = min((f.get("added") or f.get("mtime") or time.time() for f in files), default=None)
    s = autofile.summary(cfg)
    return {"waiting": len(files), "bytes": sum(f.get("size") or 0 for f in files),
            "oldest_days": int((time.time() - oldest) // 86400) if oldest else None,
            "added_7d": sum(1 for f in files if (f.get("added") or 0) > time.time() - 7 * 86400),
            "auto_filing": autofile.settings(cfg)["enabled"], "auto_filed_24h": s.get("last24h", 0)}


def _cleanup(cfg: dict) -> dict:
    import cleanup
    rep = cleanup.load_report()
    if not rep:
        return {"scanned_at": None, "safe": {"count": 0, "bytes": 0}, "review": {"count": 0, "bytes": 0},
                "keep": {"count": 0, "bytes": 0}}
    lv = rep.get("by_level") or {}
    both = lambda *names: {"count": sum((lv.get(n) or {}).get("count", 0) for n in names),
                           "bytes": sum((lv.get(n) or {}).get("bytes", 0) for n in names)}
    return {"scanned_at": rep.get("scanned_at"), "safe": both("safe", "likely"), "review": both("review"),
            "keep": both("keep")}


def _watch(cfg: dict) -> dict:
    import search_index
    import watch
    rep = watch.report(cfg, search_index.DB_FILE)
    if not rep.get("enabled", True):
        return {"enabled": False}
    soon = sorted((d for d in rep.get("dates", []) if d.get("status") == "soon"), key=lambda d: d["days"])
    return {"enabled": rep.get("enabled", True), "counts": rep.get("counts", {}), "scanned_at": rep.get("scanned_at"),
            "next": [{"name": d["name"], "date": d["date"], "days": d["days"], "kind": d["kind"]} for d in soon[:TOP]]}


def _security(cfg: dict, s: dict) -> dict:
    if not (s["enabled"] and s["applications"] and s["vulnerabilities"]):
        return {"enabled": False}
    import cve
    v = cve.view(cfg)
    hit = [a for a in v["apps"] if a["cves"]]
    top = [{"name": a["name"], "version": a.get("judged_version") or a.get("version") or "", "cves": len(a["cves"]),
            "kev": sum(1 for x in a["cves"] if x["kev"]), "critical": sum(1 for x in a["cves"] if (x["score"] or 0) >= 9),
            "update_to": (a.get("update") or {}).get("to") if not (a.get("update") or {}).get("blocked") else None}
           for a in hit[:TOP]]
    exposed = [{"name": x["name"], "ports": [p["port"] for p in x["ports"] if p["network"]], "cves": len(x["cves"])}
               for x in v["services"] if x["exposed"]][:TOP]
    return {"enabled": True, "scanned_at": v["scanned_at"], "summary": v["summary"], "recognised": v["recognised"],
            "installed": v["installed"], "top": top, "exposed": exposed,
            "database": {k: v["database"][k] for k in ("synced_at", "cves", "kev", "error")}}


def _apps(cfg: dict, s: dict, today: date) -> dict:
    if not (s["enabled"] and s["applications"]):
        return {"enabled": False}
    import apps
    v = apps.with_updates(cfg, apps.view(cfg, days=7, today=today), s["check_updates"], s["update_hours"])
    return {"enabled": True, "scanned_at": v["scanned_at"], "programs": v["counts"]["desktop"],
            "packaged": v["counts"]["packaged"], "updates_checked": v["updates"]["enabled"],
            "updates": v["updates"]["count"], "updates_checked_at": v["updates"]["checked_at"],
            "changes_7d": len(v["changes"]),
            "recent": [{"ts": c["ts"], "event": c["event"], "name": c["name"], "old_version": c["old_version"],
                        "new_version": c["new_version"]} for c in v["changes"][:TOP]]}


def _activity(cfg: dict, today: date) -> dict:
    import journal
    j = journal.build(cfg, 7, today=today)
    by = {d["date"]: d["counts"] for d in j["days"]}
    keys = ("arrived", "filed", "deleted", "worked_files", "apps")
    days = []
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        days.append({"date": d, **{k: (by.get(d) or {}).get(k, 0) for k in keys}})
    return {"days": days, "totals": {k: j["totals"].get(k, 0) for k in (*keys, "auto_filed", "deleted_bytes", "active_days")}}


def _storage(cfg: dict) -> dict:
    import sysinfo
    info = sysinfo.cached(cfg, max_age=3600)       # free space by the hour is enough here; collecting takes seconds
    return {"collected": info.get("collected"),
            "volumes": [{"letter": v.get("letter"), "label": v.get("label") or "", "bytes": v.get("bytes") or 0,
                         "free": v.get("free") or 0} for v in info.get("volumes") or [] if v.get("bytes")]}


def _agent(status: dict, search: dict | None) -> dict:
    s = search or {}
    return {"watching": bool(status.get("watching")), "model": status.get("model"), "model_ok": bool(status.get("ollama"))
            and not status.get("model_missing"), "problem": status.get("problem"),
            "restart_needed": bool(status.get("restart_needed")), "started": status.get("started"),
            "search": None if not search or search.get("disabled") else
            {"files": s.get("files", 0), "queued": s.get("queued", 0), "running": bool(s.get("running")),
             "last_sweep": s.get("last_sweep"), "locked": (s.get("by_status") or {}).get("locked", 0)}}


def _remedy(cfg: dict) -> dict:
    import remedy
    v = remedy.view(cfg)
    return {"enabled": v["enabled"], "running": v["job"]["running"],
            "recent": [{k: h[k] for k in ("ts", "action", "name", "target", "ok", "message")} for h in v["history"][:3]]}


def attention(d: dict) -> list:
    """The few lines at the top: what deserves a look first, most serious first. Each has a page to go to."""
    out = []

    def add(level, text, to):
        out.append({"level": level, "text": text, "to": to})

    ag, sec, wa, ib, ap, st, cl = (d.get(k) or {} for k in ("agent", "security", "watch", "inbox", "apps", "storage", "cleanup"))
    if ag.get("problem"):
        add("danger", f"The agent reports a problem: {ag['problem']}", "/settings")
    elif ag and not ag.get("watching", True):
        add("danger", "The agent is not watching your Downloads folder.", "/settings")
    if ag and not ag.get("model_ok", True):
        add("warning", "The filing model is not available: suggestions fall back to rules and similar documents.", "/settings")
    sm = sec.get("summary") or {}
    if sm.get("kev"):
        n = sm["kev"]
        add("danger", f"{n} known {'flaw is' if n == 1 else 'flaws are'} being used in real attacks on software you have installed.", "/security")
    if sm.get("services_exposed") and sm.get("services_affected"):
        hit = [x for x in sec.get("exposed") or [] if x.get("cves")]
        if hit:
            add("danger", f"{hit[0]['name']} has known flaws and accepts connections from the network.", "/security")
    if sm.get("critical"):
        add("warning", f"{sm['critical']} critical {'flaw' if sm['critical'] == 1 else 'flaws'} in {sm.get('apps_affected', 0)} installed programs.", "/security")
    soon = (wa.get("counts") or {}).get("soon", 0)
    if soon:
        nxt = (wa.get("next") or [{}])[0]
        when = "today" if nxt.get("days") == 0 else f"in {nxt.get('days')} days" if nxt.get("days") is not None else ""
        add("warning", f"{soon} {'date is' if soon == 1 else 'dates are'} coming up in your documents" + (f"; the next is {when}." if when else "."), "/watch")
    for v in st.get("volumes") or []:
        if v["bytes"] and v["free"] / v["bytes"] < 0.10:
            add("warning", f"Drive {v['letter']} has {v['free'] / v['bytes']:.0%} free.", "/cleanup")
    sens = (wa.get("counts") or {}).get("sensitive", 0)
    if sens:
        add("info", f"{sens} {'file' if sens == 1 else 'files'} with personal or financial details {'is' if sens == 1 else 'are'} sitting in Downloads.", "/watch")
    if ib.get("waiting"):
        add("info", f"{ib['waiting']} {'file is' if ib['waiting'] == 1 else 'files are'} waiting in the Inbox.", "/inbox")
    if ap.get("updates"):
        add("info", f"{ap['updates']} installed {'application has' if ap['updates'] == 1 else 'applications have'} a newer version.", "/library")
    if (cl.get("safe") or {}).get("count"):
        add("info", f"{cl['safe']['count']} files in Downloads look safe to remove.", "/cleanup")
    return out


def build(cfg: dict, status: dict | None = None, inbox_files: list | None = None, search: dict | None = None,
          today: date | None = None) -> dict:
    import library
    s = library.settings(cfg)
    today = today or date.today()
    d = {"generated_at": datetime.now().isoformat(timespec="seconds"),
         "agent": _part(lambda: _agent(status or {}, search)),
         "inbox": _part(lambda: _inbox(cfg, inbox_files)),
         "cleanup": _part(lambda: _cleanup(cfg)),
         "watch": _part(lambda: _watch(cfg)),
         "security": _part(lambda: _security(cfg, s)),
         "apps": _part(lambda: _apps(cfg, s, today)),
         "activity": _part(lambda: _activity(cfg, today)),
         "storage": _part(lambda: _storage(cfg)),
         "remedy": _part(lambda: _remedy(cfg))}
    d["attention"] = attention(d)
    return d
