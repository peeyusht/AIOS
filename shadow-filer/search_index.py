"""
Semantic + keyword search over the folders in config.yaml (inbox_folders and para_root).

How it works
- A background thread walks the folders, extracts text (PDF, Word, Excel, PowerPoint, text files),
  splits it into chunks, and stores an embedding for each chunk (Ollama, nomic-embed-text by default)
  plus a keyword index (SQLite FTS5) in search.db next to the agent.
- Files without extractable text (zips, images, executables, scanned PDFs) are indexed by name and
  folder only, so you can still find them by name.
- A query is embedded and compared with every chunk; the semantic ranking and the keyword ranking are
  combined (reciprocal rank fusion), so exact terms like "PVK-2026-TCS-001" and fuzzy questions like
  "posture audit findings for the bank" both work.

SAFETY: read-only. Files are only opened for reading. Cloud-only placeholders are never opened (no
downloads triggered). Nothing leaves this PC: text goes only to Ollama on localhost.
search.db contains text extracted from your documents; it is as sensitive as the documents themselves.
Delete it any time; it is rebuilt automatically.
"""
import json
import math
import os
import re
import sqlite3
import threading
import time
from array import array
from datetime import datetime
from operator import mul
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
DB_FILE = BASE / "search.db"

DEFAULTS = {
    "enabled": True,
    "model": "nomic-embed-text",
    "query_prefix": "search_query: ",       # nomic models need these task prefixes
    "document_prefix": "search_document: ",
    "chunk_chars": 1000,
    "chunk_overlap": 150,
    "max_chunks_per_file": 40,
    "max_chars_per_file": 40000,
    "max_pdf_pages": 40,
    "max_file_mb": 60,          # bigger files: name only
    "max_depth": 12,
    "sweep_minutes": 30,        # re-check folders for changes this often (events also trigger updates)
    "batch": 8,                 # small batches so a search never waits long behind indexing
    "min_similarity": 0.45,     # meaning-only matches below this are dropped (word matches always kept)
    "similarity_margin": 0.12,  # ...and so are ones far below the best match for the query
    "extra_folders": [],        # more folders to index, besides inbox_folders and para_root
    "exclude_globs": [],        # e.g. '*\\node_modules\\*'
}

DOC_TEXT_EXT = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm",
                ".log", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".py", ".ps1", ".sql", ".eml"}
SKIP_DIRS = {"$recycle.bin", "system volume information", "__pycache__", ".git", "node_modules", ".venv"}
FA_REPARSE, FA_OFFLINE, FA_RECALL_ON_OPEN, FA_RECALL_ON_DATA = 0x400, 0x1000, 0x40000, 0x400000
STOPWORDS = set("""a an the and or of for to in on at by with from about into as is are was were be
this that these those it its my our your their me we you he she they them i do does did not no all any
find show get where which what who when how file files document documents doc docs""".split())
TYPE_GROUPS = {
    "docs": {".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".odt", ".eml", ".msg"},
    "sheets": {".xlsx", ".xls", ".xlsm", ".csv", ".ods"},
    "slides": {".pptx", ".ppt", ".odp"},
    "pdf": {".pdf"},
}
OPENABLE = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".csv", ".pptx", ".ppt", ".txt", ".md",
            ".rtf", ".odt", ".ods", ".odp", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".eml", ".msg",
            ".vsdx", ".json", ".xml", ".log", ".yaml", ".yml"}


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("search") or {})}


def roots(cfg: dict) -> list[tuple[str, Path]]:
    s = settings(cfg)
    out = [("inbox", p) for p in cfg["inbox_folders"]] + [("para", cfg["para_root"])]
    out += [("extra", Path(os.path.expandvars(str(p)))) for p in s["extra_folders"]]
    seen, uniq = set(), []
    for src, p in out:
        k = str(p).lower().rstrip("\\/")
        if k not in seen:
            seen.add(k)
            uniq.append((src, p))
    return uniq


# --------------------------------------------------------------------------- storage
def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY, root TEXT, source TEXT, name TEXT, folder TEXT, ext TEXT,
            size INTEGER, mtime_ns INTEGER, status TEXT, chars INTEGER, chunks INTEGER,
            indexed_at TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, idx INTEGER, text TEXT, vec BLOB);
        CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
    """)
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(name, text, tokenize='unicode61')")
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('fts', '1')")
    except sqlite3.OperationalError:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('fts', '0')")  # no FTS5: keyword search falls back to LIKE
    conn.commit()
    return conn


def has_fts(conn) -> bool:
    r = conn.execute("SELECT v FROM meta WHERE k='fts'").fetchone()
    return bool(r and r[0] == "1")


# --------------------------------------------------------------------------- helpers
def is_cloud_only(st) -> bool:
    a = getattr(st, "st_file_attributes", 0) or 0
    return bool(a & (FA_OFFLINE | FA_RECALL_ON_OPEN | FA_RECALL_ON_DATA))


def normalize(v: list[float]) -> array:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return array("f", (x / n for x in v))


def chunk_text(text: str, size: int, overlap: int, limit: int) -> list[str]:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if not text:
        return []
    out, i = [], 0
    while i < len(text) and len(out) < limit:
        end = min(len(text), i + size)
        if end < len(text):  # prefer to cut at a paragraph, sentence or word boundary
            for sep in ("\n\n", ". ", "\n", " "):
                j = text.rfind(sep, i + size // 2, end)
                if j > 0:
                    end = j + len(sep)
                    break
        piece = text[i:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        i = max(end - overlap, i + 1)
    return out


def header(name: str, rel_folder: str) -> str:
    stem = re.sub(r"[_\-.]+", " ", os.path.splitext(name)[0])
    return f"File: {name} ({stem}) | Folder: {rel_folder}"


class Embedder:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def __call__(self, texts: list[str]) -> list[array]:
        s = settings(self.cfg)
        url = self.cfg["ollama"]["url"].rstrip("/")
        r = requests.post(url + "/api/embed", json={"model": s["model"], "input": texts, "truncate": True},
                          timeout=max(60, 10 * len(texts)))
        if r.status_code == 404 and "model" not in r.text.lower():  # very old Ollama: one at a time
            out = []
            for t in texts:
                r1 = requests.post(url + "/api/embeddings", json={"model": s["model"], "prompt": t}, timeout=60)
                r1.raise_for_status()
                out.append(normalize(r1.json()["embedding"]))
            return out
        if r.status_code != 200:
            try:
                detail = r.json().get("error", r.text)
            except ValueError:
                detail = r.text
            raise RuntimeError(f"Ollama embed HTTP {r.status_code}: {str(detail)[:200]}")
        return [normalize(v) for v in r.json()["embeddings"]]


# --------------------------------------------------------------------------- the index
class Index:
    """Background indexer + in-memory vectors for fast search. One per process."""

    def __init__(self, cfg: dict, log=None, embedder=None, extract=None):
        self.cfg, self.log = cfg, log
        self.embed = embedder or Embedder(cfg)
        self._extract = extract
        self.conn = connect()
        self.lock = threading.RLock()        # guards self.conn and the in-memory vectors
        self.queue: dict[str, float] = {}
        self.qlock = threading.Lock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.state = {"running": False, "phase": "idle", "current": None, "done": 0, "todo": 0,
                      "last_sweep": None, "last_error": None, "started": None, "model_ok": None}
        self.searching, self.last_query = 0, 0.0
        self.ids: list[int] = []
        self.paths: list[str] = []
        self.vecs: list[array] = []
        self._load_vectors()

    # ---------- memory
    def _load_vectors(self):
        with self.lock:
            rows = self.conn.execute("SELECT id, path, vec FROM chunks WHERE vec IS NOT NULL").fetchall()
            self.ids = [r["id"] for r in rows]
            self.paths = [r["path"] for r in rows]
            self.vecs = []
            for r in rows:
                a = array("f")
                a.frombytes(r["vec"])
                self.vecs.append(a)

    # ---------- public
    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="search-index").start()

    def enqueue(self, path: str):
        if not settings(self.cfg)["enabled"]:
            return
        with self.qlock:
            self.queue[str(path)] = time.time()
        self.wake.set()

    def rebuild(self):
        with self.lock:
            self.conn.execute("DELETE FROM chunks")
            if has_fts(self.conn):
                self.conn.execute("DELETE FROM chunks_fts")
            self.conn.execute("DELETE FROM files")
            self.conn.commit()
            self.ids, self.paths, self.vecs = [], [], []
        self.state["last_sweep"] = None
        self.wake.set()

    def stats(self) -> dict:
        with self.lock:
            c = self.conn
            by = {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM files GROUP BY status")}
            n_chunks = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            errs = [dict(r) for r in c.execute(
                "SELECT path, error FROM files WHERE status='error' ORDER BY indexed_at DESC LIMIT 20")]
            by_root = {r[0]: r[1] for r in c.execute("SELECT source, COUNT(*) FROM files GROUP BY source")}
        try:
            size = DB_FILE.stat().st_size + sum(p.stat().st_size for p in BASE.glob("search.db-*"))
        except OSError:
            size = None
        s = settings(self.cfg)
        return {**self.state, "files": sum(by.values()), "by_status": by, "by_source": by_root,
                "chunks": n_chunks, "vectors": len(self.vecs), "db_bytes": size, "errors": errs,
                "model": s["model"], "roots": [{"source": src, "path": str(p), "exists": p.is_dir()}
                                               for src, p in roots(self.cfg)],
                "fts": has_fts(self.conn), "queued": len(self.queue)}

    # ---------- loop
    def _loop(self):
        s = settings(self.cfg)
        self.state["started"] = datetime.now().isoformat(timespec="seconds")
        last = 0.0
        while not self.stop.is_set():
            try:
                s = settings(self.cfg)  # re-read: settings can change from the UI
                sig = (s["model"], tuple(str(p) for _, p in roots(self.cfg)), s["enabled"])
                due = (time.time() - last > s["sweep_minutes"] * 60 or self.state["last_sweep"] is None
                       or sig != getattr(self, "_sig", sig))
                self._sig = sig
                if due:
                    self._sweep()
                    last = time.time()
                    self.state["last_sweep"] = datetime.now().isoformat(timespec="seconds")
                self._drain_queue()
            except Exception as e:  # never take the agent down
                self.state["last_error"] = str(e)[:300]
                if self.log:
                    self.log.warning("search index: %s", e)
                time.sleep(60)
            self.state.update(running=False, phase="idle", current=None)
            with self.qlock:
                pending = bool(self.queue)
            self.wake.wait(timeout=2 if pending else 60)  # queued files become ready after ~3 s
            self.wake.clear()

    def _model_ok(self) -> bool:
        s = settings(self.cfg)
        try:
            r = requests.get(self.cfg["ollama"]["url"].rstrip("/") + "/api/tags", timeout=5)
            names = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            self.state["model_ok"] = None
            return False
        want = s["model"] if ":" in s["model"] else s["model"] + ":latest"
        ok = want in names
        self.state["model_ok"] = ok
        if not ok:
            self.state["last_error"] = f"embedding model '{s['model']}' is not installed: run  ollama pull {s['model']}"
        return ok

    def _walk(self):
        s = settings(self.cfg)
        import fnmatch
        excl = [g.lower() for g in s["exclude_globs"]]
        for src, root in roots(self.cfg):
            if not root.is_dir():
                continue
            stack = [(root, 0)]
            while stack:
                folder, depth = stack.pop()
                try:
                    entries = list(os.scandir(folder))
                except OSError:
                    continue
                for e in entries:
                    try:
                        if e.is_symlink():
                            continue
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if (getattr(st, "st_file_attributes", 0) or 0) & FA_REPARSE:
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if e.name.lower() in SKIP_DIRS or e.name.startswith("."):
                            continue
                        if depth < s["max_depth"]:
                            stack.append((Path(e.path), depth + 1))
                        continue
                    n = e.name.lower()
                    if n in ("desktop.ini", "thumbs.db") or n.startswith("~$") or n.endswith(
                            (".crdownload", ".part", ".partial", ".tmp", ".download")):
                        continue
                    if excl and any(fnmatch.fnmatch(e.path.lower(), g) for g in excl):
                        continue
                    yield src, root, e.path, st

    def _check_model(self):
        """Vectors from different embedding models can't be compared: rebuild after a model change."""
        model = settings(self.cfg)["model"]
        with self.lock:
            r = self.conn.execute("SELECT v FROM meta WHERE k='model'").fetchone()
            if r and r[0] != model:
                if self.log:
                    self.log.info("search index: embedding model changed (%s -> %s); rebuilding", r[0], model)
                self.conn.execute("DELETE FROM chunks")
                if has_fts(self.conn):
                    self.conn.execute("DELETE FROM chunks_fts")
                self.conn.execute("DELETE FROM files")
                self.ids, self.paths, self.vecs = [], [], []
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES ('model', ?)", (model,))
            self.conn.commit()

    def _sweep(self):
        if not settings(self.cfg)["enabled"]:
            return
        self._check_model()
        self.state.update(running=True, phase="checking folders", current=None)
        with self.lock:
            known = {r["path"]: (r["size"], r["mtime_ns"], r["status"])
                     for r in self.conn.execute("SELECT path, size, mtime_ns, status FROM files")}
        seen, todo = set(), []
        for src, root, path, st in self._walk():
            seen.add(path)
            k = known.get(path)
            if k is None or k[0] != st.st_size or k[1] != st.st_mtime_ns or k[2] in ("error", "pending"):
                todo.append((src, root, path, st))
        gone = [p for p in known if p not in seen]
        for p in gone:
            self._remove(p)
        if gone and self.log:
            self.log.info("search index: removed %d file(s) no longer present", len(gone))
        if not todo:
            return
        if not self._model_ok():
            return
        # small, recent documents first, so search becomes useful quickly
        todo.sort(key=lambda t: (os.path.splitext(t[2])[1].lower() not in DOC_TEXT_EXT, -t[3].st_mtime))
        self.state.update(phase="indexing", todo=len(todo), done=0)
        t0, n_chunks = time.time(), 0
        for i, (src, root, path, st) in enumerate(todo):
            if self.stop.is_set():
                return
            self.state.update(current=os.path.basename(path), done=i)
            n_chunks += self._index_file(src, root, path, st)
            self._drain_queue()
        self.state.update(done=len(todo))
        if self.log:
            self.log.info("search index: indexed %d file(s), %d chunk(s) in %.0fs",
                          len(todo), n_chunks, time.time() - t0)

    def _drain_queue(self):
        while True:
            with self.qlock:
                ready = [p for p, t in self.queue.items() if time.time() - t > 3]
                for p in ready:
                    self.queue.pop(p, None)
            if not ready:
                return
            for path in ready:
                p = Path(path)
                src_root = next(((src, r) for src, r in roots(self.cfg)
                                 if str(p).lower().startswith(str(r).lower().rstrip("\\/") + os.sep)), None)
                if src_root is None:
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    self._remove(path)
                    continue
                if os.path.isfile(path):
                    with self.lock:
                        k = self.conn.execute("SELECT size, mtime_ns FROM files WHERE path=?", (path,)).fetchone()
                    if k and k[0] == st.st_size and k[1] == st.st_mtime_ns:
                        continue
                    if self._model_ok():
                        self.state.update(running=True, phase="indexing new file", current=p.name)
                        self._index_file(src_root[0], src_root[1], path, st)

    def _remove(self, path: str):
        with self.lock:
            ids = [r[0] for r in self.conn.execute("SELECT id FROM chunks WHERE path=?", (path,))]
            self.conn.execute("DELETE FROM chunks WHERE path=?", (path,))
            if ids and has_fts(self.conn):
                self.conn.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
            self.conn.execute("DELETE FROM files WHERE path=?", (path,))
            self.conn.commit()
            if ids:
                drop = set(ids)
                keep = [k for k, i in enumerate(self.ids) if i not in drop]
                self.ids = [self.ids[k] for k in keep]
                self.paths = [self.paths[k] for k in keep]
                self.vecs = [self.vecs[k] for k in keep]

    def _text_of(self, path: str, st) -> tuple[str, str, str | None]:
        """(text, status, error)"""
        s = settings(self.cfg)
        ext = os.path.splitext(path)[1].lower()
        if is_cloud_only(st):
            return "", "cloud", None
        if ext not in DOC_TEXT_EXT:
            return "", "name_only", None
        if st.st_size > s["max_file_mb"] * 1024 * 1024:
            return "", "name_only", "too big to read"
        ecfg = {**self.cfg, "extraction": {"max_chars": s["max_chars_per_file"], "max_pdf_pages": s["max_pdf_pages"]}}
        try:
            if self._extract:
                text = self._extract(Path(path), ecfg)
            else:
                import shadow_agent
                text = shadow_agent.extract_text(Path(path), ecfg)
        except Exception as e:
            return "", "error", str(e)[:200]
        if not text.strip():
            # scanned PDF or empty doc: still findable by name
            return "", "no_text", None
        return text, "ok", None

    def _index_file(self, src: str, root: Path, path: str, st) -> int:
        s = settings(self.cfg)
        name = os.path.basename(path)
        try:
            rel = str(Path(path).parent.relative_to(root))
        except ValueError:
            rel = str(Path(path).parent)
        rel_folder = (root.name if rel == "." else f"{root.name}{os.sep}{rel}")
        text, status, err = self._text_of(path, st)
        hdr = header(name, rel_folder)
        pieces = chunk_text(text, s["chunk_chars"], s["chunk_overlap"], s["max_chunks_per_file"]) if text else []
        docs = [hdr] if not pieces else [f"{hdr}\n{p}" for p in pieces]
        vecs = []
        try:
            for i in range(0, len(docs), s["batch"]):
                self._yield_to_search()
                vecs += self.embed([s["document_prefix"] + d for d in docs[i:i + s["batch"]]])
        except Exception as e:
            self.state["last_error"] = str(e)[:300]
            with self.lock:
                self.conn.execute("""INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                  (path, str(root), src, name, rel_folder, os.path.splitext(name)[1].lower(),
                                   st.st_size, st.st_mtime_ns, "error", len(text), 0,
                                   datetime.now().isoformat(timespec="seconds"), str(e)[:300]))
                self.conn.commit()
            return 0
        self._remove(path)
        with self.lock:
            fts = has_fts(self.conn)
            new_ids = []
            for i, (d, v) in enumerate(zip(docs, vecs)):
                cur = self.conn.execute("INSERT INTO chunks (path, idx, text, vec) VALUES (?,?,?,?)",
                                        (path, i, d, v.tobytes()))
                new_ids.append(cur.lastrowid)
                if fts:
                    self.conn.execute("INSERT INTO chunks_fts (rowid, name, text) VALUES (?,?,?)",
                                      (cur.lastrowid, re.sub(r"[_\-.]+", " ", name), d))
            self.conn.execute("""INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                              (path, str(root), src, name, rel_folder, os.path.splitext(name)[1].lower(),
                               st.st_size, st.st_mtime_ns, status, len(text), len(docs),
                               datetime.now().isoformat(timespec="seconds"), err))
            self.conn.commit()
            self.ids += new_ids
            self.paths += [path] * len(new_ids)
            self.vecs += vecs
        return len(docs)

    def _yield_to_search(self):
        """Ollama handles one request at a time: pause indexing while someone is searching."""
        for _ in range(40):
            if self.searching <= 0 and time.time() - self.last_query > 2:
                return
            time.sleep(0.25)

    # ---------- search
    def search(self, q: str, scope: str = "all", types: str = "any", limit: int = 30) -> dict:
        q = q.strip()
        if not q:
            return {"results": [], "semantic": False}
        self.searching += 1
        self.last_query = time.time()
        try:
            return self._search(q, scope, types, limit)
        finally:
            self.searching -= 1
            self.last_query = time.time()

    def _search(self, q: str, scope: str, types: str, limit: int) -> dict:
        s = settings(self.cfg)
        t0 = time.time()
        allowed_ext = TYPE_GROUPS.get(types)
        with self.lock:
            meta = {r["path"]: dict(r) for r in self.conn.execute(
                "SELECT path, source, name, folder, ext, size, mtime_ns, status FROM files")}

        def ok(path):
            m = meta.get(path)
            if not m:
                return False
            if scope in ("inbox", "para", "extra") and m["source"] != scope:
                return False
            return not allowed_ext or m["ext"] in allowed_ext

        # semantic
        sem_rank, sem_best, sem_score, semantic, sem_error = {}, {}, {}, False, None
        try:
            qv = self.embed([s["query_prefix"] + q])[0]
            with self.lock:
                vecs, ids, paths = self.vecs, self.ids, self.paths
                scores = [sum(map(mul, qv, v)) for v in vecs]
            order = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
            for k in order:
                p = paths[k]
                if p in sem_best or not ok(p):
                    continue
                sem_best[p] = ids[k]
                sem_score[p] = scores[k]
                sem_rank[p] = len(sem_rank) + 1
                if len(sem_rank) >= 300:
                    break
            semantic = True
        except Exception as e:
            sem_error = str(e)[:200]

        # keyword
        kw_rank, kw_best = {}, {}
        words = [w for w in re.findall(r"[\w\-./]+", q.lower()) if len(w) > 1 and w not in STOPWORDS][:12]
        if words:
            with self.lock:
                if has_fts(self.conn):
                    def fts(op):
                        expr = f" {op} ".join('"' + w.replace('"', "") + '"' for w in words)
                        try:
                            return self.conn.execute(
                                "SELECT c.id, c.path FROM chunks_fts f JOIN chunks c ON c.id = f.rowid "
                                "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts, 4.0, 1.0) LIMIT 800",
                                (expr,)).fetchall()
                        except sqlite3.OperationalError:
                            return []
                    rows = fts("AND")          # passages containing every word
                    if len({r[1] for r in rows}) < 5 and len(words) > 1:
                        rows = rows + [r for r in fts("OR") if r not in rows]  # then any word
                else:
                    like = " OR ".join("LOWER(text) LIKE ?" for _ in words)
                    rows = self.conn.execute(f"SELECT id, path FROM chunks WHERE {like} LIMIT 800",
                                             [f"%{w}%" for w in words]).fetchall()
            for r in rows:
                p = r[1]
                if p in kw_best or not ok(p):
                    continue
                kw_best[p] = r[0]
                kw_rank[p] = len(kw_rank) + 1

        # drop weak meaning-only matches: every file has *some* similarity to any query
        if sem_score:
            best = max(sem_score.values())
            floor = max(s["min_similarity"], best - s["similarity_margin"])
            for p in [p for p in sem_rank if p not in kw_rank and sem_score[p] < floor]:
                del sem_rank[p]
        # fuse
        fused = {}
        for p in set(sem_rank) | set(kw_rank):
            sc = 0.0
            if p in sem_rank:
                sc += 1.0 / (60 + sem_rank[p])
            if p in kw_rank:
                sc += 1.0 / (60 + kw_rank[p])
            name = meta[p]["name"].lower()
            if words and all(w in name for w in words):
                sc += 0.01  # every query word in the file name
            fused[p] = sc
        top = sorted(fused, key=fused.get, reverse=True)[:limit]
        with self.lock:
            out = []
            for p in top:
                cid = kw_best.get(p) if (p in kw_rank and kw_rank[p] <= sem_rank.get(p, 1e9)) else sem_best.get(p)
                cid = cid or kw_best.get(p)
                row = self.conn.execute("SELECT text, idx FROM chunks WHERE id=?", (cid,)).fetchone()
                m = meta[p]
                snippet = row["text"].split("\n", 1)[1] if row and "\n" in row["text"] else ""
                out.append({
                    "path": p, "name": m["name"], "folder": m["folder"], "source": m["source"],
                    "ext": m["ext"], "size": m["size"], "status": m["status"],
                    "modified": datetime.fromtimestamp(m["mtime_ns"] / 1e9).isoformat(timespec="seconds"),
                    "score": round(fused[p], 5),
                    "similarity": round(sem_score[p], 3) if p in sem_score else None,
                    "keyword": p in kw_rank, "snippet": _snippet(snippet, words),
                    "part": (row["idx"] + 1) if row and snippet else None,
                    "openable": m["ext"] in OPENABLE,
                })
        return {"results": out, "semantic": semantic, "semantic_error": sem_error,
                "ms": int((time.time() - t0) * 1000), "searched_files": len(meta)}

    def is_indexed(self, path: str) -> dict | None:
        with self.lock:
            r = self.conn.execute("SELECT path, ext FROM files WHERE path=?", (path,)).fetchone()
        return dict(r) if r else None


def _snippet(text: str, words: list[str], width: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= width:
        return text
    low = text.lower()
    pos = min((low.find(w) for w in words if low.find(w) >= 0), default=0)
    start = max(0, pos - width // 3)
    s = text[start:start + width]
    return ("…" if start else "") + s + ("…" if start + width < len(text) else "")


# --------------------------------------------------------------------------- singleton
INDEX: Index | None = None


def get(cfg: dict | None = None, log=None) -> Index | None:
    global INDEX
    if INDEX is None and cfg is not None:
        INDEX = Index(cfg, log)
    return INDEX
