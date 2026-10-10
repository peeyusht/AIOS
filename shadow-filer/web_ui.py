"""
Local web UI for Shadow Filer. Standard library only.

Security:
- Listens on 127.0.0.1 only; never reachable from the network.
- Rejects requests whose Host header isn't 127.0.0.1/localhost (blocks DNS-rebinding attacks
  where a web page you visit tries to talk to this port).
- Every write (save settings, restart) needs a per-session token that only the served page knows.
- No CORS headers, so other sites cannot read the API from your browser.
"""
import json
from datetime import datetime
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

import shadow_agent as sa

BASE = Path(__file__).resolve().parent
DIST = BASE / "ui_dist"          # built front end (vite build output); ui.html is the fallback
MIME = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
        ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2", ".woff": "font/woff",
        ".json": "application/json", ".webp": "image/webp", ".txt": "text/plain", ".map": "application/json"}
TOKEN = secrets.token_urlsafe(24)
VIEWS = {"all", "pending", "match", "miss", "unsure", "error"}

# Settings that need a restart because watchers / files are already open.
RESTART_KEYS = ("inbox_folders", "para_root", "database", "log_file", "ui")


class Ctx:
    cfg: dict
    db: "sa.DB"
    dests: "sa.Destinations"
    config_path: Path
    status: dict
    log = None


def tail(path: Path, lines: int) -> list[str]:
    if not path.exists():
        return []
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 400_000))
        data = f.read().decode("utf-8", errors="replace")
    return data.splitlines()[-lines:]


def apply_config(text: str) -> dict:
    """Validate, back up, save and hot-reload. Returns {ok, message, restart_needed}."""
    try:
        raw = yaml.safe_load(text)
        if not isinstance(raw, dict):
            raise ValueError("the file must be a YAML mapping")
        for k in ("inbox_folders", "para_root", "ollama", "database", "log_file"):
            if k not in raw:
                raise ValueError(f"missing required setting '{k}'")
        if "model" not in (raw.get("ollama") or {}):
            raise ValueError("missing ollama.model")
        for i, rule in enumerate(raw.get("rules") or []):
            if "destination" not in rule:
                raise ValueError(f"rule #{i + 1} has no destination")
            if not rule.get("extensions") and not rule.get("name_regex"):
                raise ValueError(f"rule '{rule.get('name', i + 1)}' needs extensions or name_regex")
            if rule.get("name_regex"):
                import re
                re.compile(rule["name_regex"])
        tmp = Ctx.config_path.with_suffix(".yaml.tmp")
        tmp.write_text(text, encoding="utf-8")
        new = sa.load_config(tmp)
    except Exception as e:
        return {"ok": False, "message": f"Not saved: {e}"}
    finally:
        try:
            Ctx.config_path.with_suffix(".yaml.tmp").unlink()
        except OSError:
            pass

    warnings = [f"Folder not found: {p}" for p in new["inbox_folders"] if not p.is_dir()]
    if not new["para_root"].is_dir():
        warnings.append(f"PARA root not found: {new['para_root']}")

    backup = Ctx.config_path.with_suffix(".yaml.bak")
    if Ctx.config_path.exists():
        backup.write_text(Ctx.config_path.read_text(encoding="utf-8"), encoding="utf-8")
    Ctx.config_path.write_text(text, encoding="utf-8")

    restart = any(str(new[k]) != str(Ctx.cfg[k]) for k in RESTART_KEYS)
    for k, v in new.items():
        if k not in RESTART_KEYS:
            Ctx.cfg[k] = v  # in place: running threads see the new rules immediately
    Ctx.dests._at = 0  # refresh destination list
    if restart:
        Ctx.status["restart_needed"] = True
    Ctx.log.info("settings saved from UI%s", " (restart needed)" if restart else "")
    msg = "Saved. Rules and model settings are active now."
    if restart:
        msg = "Saved. Folder, file or UI changes take effect after you restart the agent."
    if warnings:
        msg += " Warning: " + "; ".join(warnings)
    return {"ok": True, "message": msg, "restart_needed": Ctx.status["restart_needed"]}


_SUG = {}


def _suggester():
    import search_index, suggest
    idx = search_index.get()
    if idx is None:
        return None
    if _SUG.get("idx") is not idx:
        _SUG.update(idx=idx, sg=suggest.Suggester(Ctx.cfg, idx, Ctx.dests, Ctx.db))
    return _SUG["sg"]


def _cleanup_hints() -> dict:
    try:
        import cleanup
        rep = cleanup.load_report() or {}
        return {it["path"]: {"level": it["level"], "category": it["category"], "reason": it["reason"]}
                for it in rep.get("items", []) if not it.get("is_dir")}
    except Exception:
        return {}


def _reindex(*paths: str) -> None:
    """Tell the search index a file moved, so suggestions stop counting the place it left. Without this
    a file you filed and then took back keeps voting for that folder (and shows as its own duplicate)
    until the next sweep."""
    try:
        import search_index
        idx = search_index.get()
        for p in paths:
            if idx and p:
                idx.enqueue(p)
    except Exception:
        pass


def _inbox_file(path: str):
    """A file directly inside a watched folder, or None. Lets Show work for any Inbox file."""
    try:
        p = Path(path)
        if any(p.parent.resolve() == Path(r).resolve() for r in Ctx.cfg["inbox_folders"]) and p.is_file():
            return {"path": str(p)}
    except OSError:
        pass
    return None


def _inbox_post(self, path: str, body: dict):
    import mover
    cfg = Ctx.cfg
    try:
        if path == "/api/inbox/file":
            p, folder = str(body.get("path", "")), str(body.get("folder", ""))
            # What was suggested, and where your choice ranked, is worked out here rather than taken from the
            # page: this record is the evidence auto-filing trusts.
            meta = {"size": body.get("size"), "source": "manual", "rank": 0}
            sg = _suggester()
            try:
                cands = (sg.suggest(p).get("candidates") or []) if sg else []
            except Exception as e:
                Ctx.log.warning("suggestion unavailable while filing %s: %s", os.path.basename(p), e)
                cands = []
            if cands:
                want = folder.strip().strip("/\\").replace("\\", "/")
                meta.update(top_folder=cands[0]["folder"], top_score=cands[0].get("score"),
                            top_source=cands[0].get("source"))
                hit = next((c for c in cands if c["folder"] == want), None)
                if hit:
                    meta.update(source=hit["source"], rank=hit["rank"])
            res = mover.move(cfg, p, folder, meta, Ctx.log)
            _reindex(res["src"], res["dest"])
            return self._send(200, res)
        if path == "/api/inbox/mkdir":
            res = mover.make_folder(cfg, str(body.get("parent", "")), str(body.get("name", "")), Ctx.log)
            Ctx.dests._at = 0  # the new folder is a destination straight away
            return self._send(200, res)
        if path == "/api/inbox/dismiss":
            p = str(body.get("path", ""))
            if not any(Path(p).parent == Path(r) for r in cfg["inbox_folders"]):
                return self._send(400, {"ok": False, "message": "Unknown file."})
            size = os.path.getsize(p) if os.path.exists(p) else 0
            mover.dismiss(cfg, p, size, undo_it=bool(body.get("undo")))
            return self._send(200, {"ok": True})
        if path == "/api/moves/undo":
            res = mover.undo(cfg, int(body.get("id", 0)), Ctx.log)
            try:
                Ctx.db.clear_actual(res["restored"])
            except Exception:
                pass
            _reindex(res["removed"], res["restored"])
            return self._send(200, res)
    except mover.MoveError as e:
        return self._send(200, {"ok": False, "message": str(e)})
    return self._send(404, {"error": "not found"})


def cfg_now():
    return Ctx.cfg


def restart_agent():
    """Exit with the restart code; the supervisor starts a fresh agent immediately."""
    Ctx.log.info("restart requested from UI")
    time.sleep(0.5)  # let the HTTP response reach the browser
    os._exit(sa.RESTART_CODE)


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind the same port, which would defeat the
    # single-instance check. Use SO_EXCLUSIVEADDRUSE there instead.
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server_version = "ShadowFiler"

    def log_message(self, *a):
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("127.0.0.1", "localhost")

    def _send(self, code: int, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (
            json.dumps(body, default=str).encode() if ctype == "application/json" else body.encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        cfg, db = Ctx.cfg, Ctx.db
        try:
            if u.path in ("/", "/index.html"):
                page = DIST / "index.html" if (DIST / "index.html").is_file() and q.get("classic") != "1" \
                    else BASE / "ui.html"
                html = page.read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
                return self._send(200, html, "text/html")
            if not u.path.startswith("/api/"):
                return self._static(u.path)
            if u.path == "/api/status":
                return self._send(200, {
                    **Ctx.status,
                    "model": cfg["ollama"]["model"],
                    "inbox": [str(p) for p in cfg["inbox_folders"]],
                    "para_root": str(cfg["para_root"]),
                    "log_file": str(cfg["log_file"]),
                })
            if u.path == "/api/stats":
                return self._send(200, sa.compute_stats(cfg, db.all()))
            if u.path == "/api/predictions":
                view = q.get("view", "all")
                view = view if view in VIEWS else "all"
                term = q.get("q", "").lower().strip()
                limit = min(int(q.get("limit", 500)), 5000)
                depth = cfg["destination_depth"]
                out = []
                for r in reversed(db.all()):
                    oc = sa.outcome(r, depth)
                    if view != "all" and oc != view:
                        continue
                    if term and term not in r["filename"].lower() and term not in (r["predicted"] or "").lower() \
                            and term not in (r["actual"] or "").lower():
                        continue
                    out.append({**dict(r), "outcome": oc})
                    if len(out) >= limit:
                        break
                return self._send(200, out)
            if u.path == "/api/log":
                return self._send(200, tail(cfg["log_file"], min(int(q.get("lines", 300)), 2000)))
            if u.path == "/api/config":
                return self._send(200, {"text": Ctx.config_path.read_text(encoding="utf-8")})
            if u.path == "/api/system":
                import sysinfo
                return self._send(200, sysinfo.cached(cfg, force=q.get("refresh") == "1"))
            if u.path == "/api/cleanup":
                import cleanup
                rep = cleanup.with_decisions(cleanup.load_report(), cfg["database"])
                pl = None
                if rep:
                    try:
                        p = cleanup.plan(cfg, rep)
                        pl = {"recycle_count": len(p["recycle"]),
                              "recycle_bytes": sum(i["size"] for i in p["recycle"]),
                              "too_big": [{"path": i["path"], "name": i["name"], "size": i["size"]}
                                          for i in p["too_big"]],
                              "limits": p["limits"]}
                    except Exception as e:
                        pl = {"error": str(e)}
                return self._send(200, {"runner": cleanup.Runner.state, "report": rep,
                                        "levels": cleanup.LEVEL_TEXT, "plan": pl,
                                        "deleter": cleanup.Deleter.state})
            if u.path == "/api/cleanup/history":
                import cleanup
                return self._send(200, cleanup.history(cfg["database"]))
            if u.path == "/api/cleanup.csv":
                import cleanup
                rep = cleanup.with_decisions(cleanup.load_report(), cfg["database"])
                if not rep:
                    return self._send(404, {"error": "no scan yet"})
                data = ("\ufeff" + cleanup.to_csv(rep)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="shadow-filer-cleanup.csv"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if u.path == "/api/settings":
                import cleanup, config_io, search_index
                raw = yaml.safe_load(Ctx.config_path.read_text(encoding="utf-8")) or {}
                return self._send(200, {
                    "raw": raw, "models": Ctx.status.get("installed_models") or [],
                    "destinations": Ctx.dests.get() if cfg["para_root"].is_dir() else [],
                    "defaults": {"cleanup": cleanup.DEFAULTS, "search": search_index.DEFAULTS,
                                 "ocr": __import__("ocr").DEFAULTS, "autofile": __import__("autofile").DEFAULTS,
                                 "watch": __import__("watch").DEFAULTS},
                    "restart_needed": Ctx.status.get("restart_needed", False),
                    "restart_keys": list(RESTART_KEYS), "config_path": str(Ctx.config_path),
                    "os": os.name})
            if u.path == "/api/fs/dirs":
                import config_io
                try:
                    return self._send(200, config_io.list_dirs(q.get("path", "")))
                except config_io.Invalid as e:
                    return self._send(400, {"error": str(e)})
            if u.path == "/api/fs/check":
                import config_io
                return self._send(200, config_io.check_path(q.get("path", "")))
            if u.path == "/api/search":
                import search_index
                idx = search_index.get()
                if idx is None:
                    return self._send(200, {"results": [], "semantic": False,
                                            "semantic_error": "search is turned off in config.yaml"})
                return self._send(200, idx.search(q.get("q", "")[:500], q.get("scope", "all"),
                                                  q.get("types", "any"), min(int(q.get("limit", 30)), 100)))
            if u.path == "/api/search/status":
                import search_index
                idx = search_index.get()
                return self._send(200, idx.stats() if idx else {"disabled": True})
            if u.path == "/api/inbox":
                import mover, suggest
                sg = _suggester()
                files = suggest.list_inbox(cfg, mover.dismissed(cfg), lambda p: sa.is_ignored(p, cfg))
                off, lim = max(0, int(q.get("offset", 0))), min(int(q.get("limit", 40)), 200)
                import autofile
                hints = _cleanup_hints()
                proven = autofile.trust(cfg)
                now = time.time()
                page = []
                for fi in files[off:off + lim]:
                    sug = sg.suggest(fi["path"]) if sg else {"candidates": [], "ready": False}
                    page.append({**fi, "modified": datetime.fromtimestamp(fi["mtime"]).isoformat(timespec="seconds"),
                                 **sug, "cleanup": hints.get(fi["path"]),
                                 "auto": autofile.decide(cfg, fi, sug, proven, hints, now)})
                return self._send(200, {"items": page, "total": len(files), "offset": off,
                                        "examples": sg.stats() if sg else None,
                                        "parents": mover.folder_parents(cfg),
                                        "destinations": Ctx.dests.get() if cfg["para_root"].is_dir() else []})
            if u.path == "/api/autofile":
                import autofile
                return self._send(200, {"settings": autofile.settings(cfg), "summary": autofile.summary(cfg),
                                        "folders": sorted(autofile.trust(cfg).values(),
                                                          key=lambda t: (-t["proven"], -t["decisions"],
                                                                         t["folder"], t["source"]))})
            if u.path == "/api/moves":
                import mover
                return self._send(200, {"journal": mover.journal(cfg, 100), "feedback": mover.feedback(cfg)})
            if u.path == "/api/watch":
                import search_index, watch
                return self._send(200, watch.report(cfg, search_index.DB_FILE, force=q.get("refresh") == "1"))
            if u.path == "/api/destinations":
                return self._send(200, Ctx.dests.get() if cfg["para_root"].is_dir() else [])
            return self._send(404, {"error": "not found"})
        except Exception as e:
            Ctx.log.error("UI GET %s failed: %s", u.path, e)
            return self._send(500, {"error": str(e)})

    def _static(self, path: str):
        """Files from ui_dist only; nothing outside it can be reached."""
        if not DIST.is_dir():
            return self._send(404, {"error": "not found"})
        try:
            target = (DIST / path.lstrip("/")).resolve()
            target.relative_to(DIST.resolve())
        except (ValueError, OSError):
            return self._send(404, {"error": "not found"})
        if not target.is_file() or target.suffix.lower() not in MIME:
            return self._send(404, {"error": "not found"})
        data = target.read_bytes()
        ctype = MIME[target.suffix.lower()]
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))
        # vite puts a content hash in asset names, so they can be cached; index.html is never cached
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if "/assets/" in path else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        if not secrets.compare_digest(self.headers.get("X-Shadow-Token", ""), TOKEN):
            return self._send(403, {"error": "missing or stale token - reload the page"})
        u = urlparse(self.path)
        length = min(int(self.headers.get("Content-Length", 0)), 1_000_000)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        if u.path == "/api/config":
            return self._send(200, apply_config(str(body.get("text", ""))))
        if u.path == "/api/settings":
            import config_io
            try:
                current = yaml.safe_load(Ctx.config_path.read_text(encoding="utf-8")) or {}
                new = config_io.normalize(body.get("raw"), current)
            except config_io.Invalid as e:
                return self._send(200, {"ok": False, "message": f"Not saved: {e}"})
            if new == current:
                return self._send(200, {"ok": True, "message": "Nothing changed.",
                                        "restart_needed": Ctx.status.get("restart_needed", False)})
            res = apply_config(config_io.dump(new))
            try:
                import search_index
                idx = search_index.get()
                if idx and res.get("ok"):
                    idx.wake.set()  # pick up folder / model changes on its next pass
            except Exception:
                pass
            return self._send(200, res)
        if u.path.startswith("/api/search/"):
            return self._search_post(u.path, body)
        if u.path.startswith("/api/cleanup/"):
            return self._cleanup_post(u.path, body)
        if u.path == "/api/watch/dismiss":
            import search_index, watch
            p, kind, key = str(body.get("path", "")), body.get("kind"), str(body.get("key", ""))[:80]
            idx = search_index.get()
            if kind not in ("date", "sensitive") or not p or (idx is not None and idx.is_indexed(p) is None):
                return self._send(400, {"ok": False, "message": "Unknown file."})
            watch.dismiss(cfg_now()["database"], p, kind, key, undo=bool(body.get("undo")))
            Ctx.log.info("WATCH %s %s: %s", "restored" if body.get("undo") else "dismissed", kind, os.path.basename(p))
            return self._send(200, {"ok": True})
        if u.path == "/api/ocr/selftest":
            import ocr
            if os.name != "nt":
                return self._send(200, {"ok": False, "message": "OCR needs Windows."})
            r = ocr.selftest(cfg_now())
            Ctx.log.info("OCR self-test: %s", r["message"])
            return self._send(200, r)
        if u.path in ("/api/inbox/file", "/api/inbox/mkdir", "/api/inbox/dismiss", "/api/moves/undo"):
            return self._inbox_post(u.path, body)
        if u.path == "/api/restart":
            if Ctx.status.get("mode") != "agent":
                return self._send(400, {"ok": False, "message": "Only the running agent can restart itself."})
            if not Ctx.status.get("supervised"):
                return self._send(400, {"ok": False, "message":
                    "This copy was started by hand, not by the scheduled task, so nothing would start it again. "
                    "Stop it (Ctrl+C) and start it again yourself, or run install_task.ps1."})
            self._send(200, {"ok": True, "message": "Restarting. The page will reconnect shortly."})
            threading.Thread(target=restart_agent, daemon=True).start()
            return
        return self._send(404, {"error": "not found"})


def _report_item(path: str):
    """Only paths from the last scan report are accepted, so the UI can't be used to point at
    arbitrary files. (Show also accepts files directly in a watched folder: see _inbox_file.)"""
    import cleanup
    rep = cleanup.load_report()
    return next((it for it in (rep or {}).get("items", []) if it["path"] == path), None)


def _cleanup_post(self, path: str, body: dict):
    import cleanup
    if path == "/api/cleanup/scan":
        started = cleanup.Runner.start(Ctx.cfg, Ctx.log)
        return self._send(200, {"ok": True, "message": "Scan started." if started else "A scan is already running."})
    if path == "/api/cleanup/decision":
        item = _report_item(str(body.get("path", "")))
        decision = body.get("decision")
        if item is None or decision not in ("agree", "disagree", "keep", None):
            return self._send(400, {"ok": False, "message": "Unknown file or decision."})
        cleanup.set_decision(Ctx.cfg["database"], item, decision)
        Ctx.log.info("CLEANUP %s %s", decision or "cleared", item["path"])
        return self._send(200, {"ok": True})
    if path == "/api/cleanup/delete":
        mode = body.get("mode")
        paths = body.get("paths")
        if mode not in ("recycle", "permanent") or (paths is not None and not isinstance(paths, list)):
            return self._send(400, {"ok": False, "message": "Bad request."})
        if mode == "permanent" and (not paths or body.get("confirm") != "DELETE PERMANENTLY"):
            return self._send(400, {"ok": False, "message": "Permanent delete needs the exact files and confirmation."})
        err = cleanup.Deleter.start(Ctx.cfg, mode, [str(p) for p in paths] if paths else None, Ctx.log)
        if err:
            return self._send(400, {"ok": False, "message": err})
        return self._send(200, {"ok": True, "message": "Deleting."})
    if path == "/api/cleanup/selftest":
        if os.name != "nt":
            return self._send(400, {"ok": False, "message": "Only available on Windows."})
        r = cleanup.selftest()
        Ctx.log.info("CLEANUP self-test: %s", r["message"])
        return self._send(200, r)
    if path == "/api/cleanup/recyclebin":
        if os.name != "nt":
            return self._send(400, {"ok": False, "message": "Only available on Windows."})
        import subprocess
        subprocess.Popen(["explorer.exe", "shell:RecycleBinFolder"])
        return self._send(200, {"ok": True})
    if path == "/api/cleanup/reveal":
        item = _report_item(str(body.get("path", ""))) or _inbox_file(str(body.get("path", "")))
        if item is None:
            return self._send(400, {"ok": False, "message": "Unknown file."})
        if os.name != "nt":
            return self._send(400, {"ok": False, "message": "Only available on Windows."})
        import subprocess
        target = item["path"]
        if not os.path.exists(target):
            return self._send(400, {"ok": False, "message": "That file is no longer there. Run a new scan."})
        subprocess.Popen(["explorer.exe", "/select,", target])  # opens Explorer with the file selected
        return self._send(200, {"ok": True})
    return self._send(404, {"error": "not found"})


Handler._cleanup_post = _cleanup_post


def _search_post(self, path: str, body: dict):
    import search_index
    idx = search_index.get()
    if idx is None:
        return self._send(400, {"ok": False, "message": "Search is turned off in config.yaml."})
    if path == "/api/search/rebuild":
        idx.rebuild()
        Ctx.log.info("search index: rebuild requested from UI")
        return self._send(200, {"ok": True, "message": "Rebuilding the index in the background."})
    if path in ("/api/search/reveal", "/api/search/open"):
        target = str(body.get("path", ""))
        rec = idx.is_indexed(target)  # only files in the index, never arbitrary paths
        if rec is None:
            return self._send(400, {"ok": False, "message": "Unknown file."})
        if os.name != "nt":
            return self._send(400, {"ok": False, "message": "Only available on Windows."})
        if not os.path.exists(target):
            return self._send(400, {"ok": False, "message": "That file is no longer there."})
        if path.endswith("reveal"):
            import subprocess
            subprocess.Popen(["explorer.exe", "/select,", target])
            return self._send(200, {"ok": True})
        if rec["ext"] not in search_index.OPENABLE:  # never launch programs or scripts from here
            return self._send(400, {"ok": False, "message": "This file type can't be opened from here; use Show."})
        os.startfile(target)
        return self._send(200, {"ok": True})
    return self._send(404, {"error": "not found"})


Handler._search_post = _search_post


def start(cfg, db, dests, config_path: Path, status: dict, log) -> bool:
    """Bind the UI port (retrying briefly, e.g. right after a restart) and serve in a thread.
    Returns False if the port stays busy, which means another instance is running."""
    Ctx.cfg, Ctx.db, Ctx.dests, Ctx.config_path, Ctx.status, Ctx.log = cfg, db, dests, config_path, status, log
    port = cfg["ui"]["port"]
    server = None
    for _ in range(15):
        try:
            server = Server(("127.0.0.1", port), Handler)
            break
        except OSError:
            time.sleep(1)
    if server is None:
        return False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("UI at http://127.0.0.1:%s", port)
    return True


Handler._inbox_post = _inbox_post
