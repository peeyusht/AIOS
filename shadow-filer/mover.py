"""
Moves a file from an inbox folder into the PARA tree when you click "File it", and back on Undo.

Guarantees:
- Only files directly inside your inbox folders, only into existing folders inside the PARA root.
- Never overwrites: if the name is taken, an identical file is reported (not moved) and a different file
  gets " (2)" etc. Same-drive moves are a rename that fails rather than replace; cross-drive moves copy to
  a temporary name, verify the copy byte-for-byte (SHA-256), rename it into place, and only then remove the
  original. If the original can't be removed (open in another program), the copy is removed and nothing
  has changed.
- Every move is journaled (from, to, size, hash) and can be undone the same safe way. The journal entry is
  written BEFORE the file is touched ("pending") and completed afterwards, so a crash or a locked database
  can't leave a filed file with no record; recover() settles interrupted entries when the agent starts.
"""
import hashlib
import os
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

FA_REPARSE, FA_OFFLINE, FA_RECALL_ON_OPEN, FA_RECALL_ON_DATA = 0x400, 0x1000, 0x40000, 0x400000
_lock = threading.Lock()


class MoveError(Exception):
    pass


def _conn(db_path: Path):
    c = sqlite3.connect(str(db_path), timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS moves (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, src TEXT, dest TEXT, size INTEGER, sha256 TEXT,
        folder TEXT, source TEXT, rank INTEGER, top_folder TEXT, top_score REAL,
        status TEXT, undone_ts TEXT, note TEXT)""")
    if "top_source" not in {r[1] for r in c.execute("PRAGMA table_info(moves)")}:
        c.execute("ALTER TABLE moves ADD COLUMN top_source TEXT")  # which kind of suggestion came first
    c.execute("""CREATE TABLE IF NOT EXISTS inbox_dismissed (path TEXT PRIMARY KEY, size INTEGER, ts TEXT)""")
    return c


def sha256_of(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _inside(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _check_source(path: str, cfg: dict) -> os.stat_result:
    p = Path(path)
    if not any(p.parent.resolve() == Path(r).resolve() for r in cfg["inbox_folders"]):
        raise MoveError("Only files directly in a watched folder can be filed from here.")
    try:
        st = os.stat(path, follow_symlinks=False)
    except OSError:
        raise MoveError("The file is no longer there.")
    a = getattr(st, "st_file_attributes", 0) or 0
    if a & FA_REPARSE or os.path.islink(path):
        raise MoveError("That's a link, not a file.")
    if a & (FA_OFFLINE | FA_RECALL_ON_OPEN | FA_RECALL_ON_DATA):
        raise MoveError("The file is cloud-only; open it once so it's on this PC, then try again.")
    if not os.path.isfile(path):
        raise MoveError("Only files can be filed, not folders.")
    return st


def _dest_folder(folder: str, cfg: dict) -> Path:
    folder = (folder or "").strip().strip("/\\").replace("\\", "/")
    if not folder or ".." in folder.split("/"):
        raise MoveError("Choose a destination folder.")
    d = cfg["para_root"] / folder
    if not _inside(d, cfg["para_root"]):
        raise MoveError("Destination must be inside your PARA folder.")
    if not d.is_dir():
        raise MoveError(f"Folder not found: {folder}")
    return d


def _free_name(folder: Path, name: str) -> Path:
    t = folder / name
    if not t.exists():
        return t
    stem, ext = os.path.splitext(name)
    for i in range(2, 1000):
        t = folder / f"{stem} ({i}){ext}"
        if not t.exists():
            return t
    raise MoveError("Too many files with that name in the destination.")


def _no_replace_rename(a: str, b: str):
    """Rename a -> b, failing (never replacing) if b exists."""
    if os.name == "nt":
        os.rename(a, b)  # Windows: fails if b exists
    else:
        os.link(a, b)    # POSIX: link fails if b exists; then drop the old name
        os.unlink(a)


def _transfer(src: str, dest: Path, digest: str) -> None:
    """Move src to dest (dest must not exist) without ever losing or replacing data."""
    try:
        _no_replace_rename(src, str(dest))
        return
    except OSError as e:
        if dest.exists():
            raise MoveError("A file with that name appeared in the destination; try again.")
        cross = getattr(e, "errno", None) == 18 or getattr(e, "winerror", None) == 17  # EXDEV / not same device
        if not cross:
            if getattr(e, "winerror", None) in (32, 33):
                raise MoveError("The file is open in another program. Close it and try again.")
            raise MoveError(f"Couldn't move the file: {e.strerror or e}")
    # different drive: copy -> verify -> rename into place -> remove original
    tmp = dest.with_name(dest.name + ".shadowfiler-partial")
    if tmp.exists():
        raise MoveError("A leftover temporary file is in the way; try again later.")
    try:
        shutil.copy2(src, tmp)
        if sha256_of(str(tmp)) != digest:
            raise MoveError("The copy didn't match the original; nothing was moved.")
        _no_replace_rename(str(tmp), str(dest))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    try:
        os.remove(src)
    except OSError as e:
        try:
            os.remove(dest)  # roll back: the original is still where it was
        except OSError:
            raise MoveError(f"Couldn't remove the original ({e.strerror or e}) or the new copy: the file is now "
                            f"in both places. Nothing was lost; delete {dest} by hand.")
        if getattr(e, "winerror", None) in (32, 33):
            raise MoveError("The file is open in another program. Close it and try again.")
        raise MoveError(f"Couldn't remove the original ({e.strerror or e}); nothing was moved.")


def move(cfg: dict, path: str, folder: str, meta: dict | None = None, log=None) -> dict:
    meta = meta or {}
    with _lock:
        st = _check_source(path, cfg)
        if meta.get("size") is not None and int(meta["size"]) != st.st_size:
            raise MoveError("The file changed since the suggestion was made; reload the page.")
        dest_dir = _dest_folder(folder, cfg)
        digest = sha256_of(path)
        same = dest_dir / os.path.basename(path)
        if same.exists() and same.is_file() and same.stat().st_size == st.st_size and sha256_of(str(same)) == digest:
            raise MoveError(f"An identical copy is already in {folder}. Nothing was moved; "
                            "the Cleanup page can send this one to the Recycle Bin.")
        target = _free_name(dest_dir, os.path.basename(path))
        c = _conn(cfg["database"])
        try:
            _recover(c, log)
            cur = c.execute("INSERT INTO moves (ts, src, dest, size, sha256, folder, source, rank, top_folder, "
                            "top_score, top_source, status) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'pending')",
                            (datetime.now().isoformat(timespec="seconds"), path, str(target), st.st_size, digest,
                             folder, meta.get("source") or "manual", int(meta.get("rank") or 0),
                             meta.get("top_folder"), meta.get("top_score"), meta.get("top_source")))
            c.commit()   # journal first: if this fails, the file hasn't been touched
            mid = cur.lastrowid
            try:
                _transfer(path, target, digest)
            except MoveError:
                c.execute("DELETE FROM moves WHERE id=?", (mid,))  # refused: nothing changed, nothing to record
                c.commit()
                raise
            try:
                c.execute("UPDATE moves SET status='moved' WHERE id=?", (mid,))
                c.commit()
            except sqlite3.Error as e:  # the file is filed; recover() completes the entry
                if log:
                    log.warning("journal entry %s left pending (%s); it is completed on the next start or Undo", mid, e)
        finally:
            c.close()
        if log:
            log.info("FILED BY YOU %s -> %s", path, target)
        return {"ok": True, "id": mid, "dest": str(target), "renamed": target.name != os.path.basename(path)}


def undo(cfg: dict, move_id: int, log=None) -> dict:
    with _lock:
        c = _conn(cfg["database"])
        try:
            _recover(c, log)
            r = c.execute("SELECT * FROM moves WHERE id=?", (move_id,)).fetchone()
            if not r or r["status"] != "moved":
                raise MoveError("Nothing to undo for that entry.")
            dest = r["dest"]
            if not os.path.isfile(dest):
                raise MoveError("The filed copy is no longer where it was put; nothing to undo.")
            if os.path.getsize(dest) != r["size"] or sha256_of(dest) != r["sha256"]:
                raise MoveError("The filed copy has changed since it was moved; undo it by hand if you're sure.")
            src = Path(r["src"])
            if not any(src.parent.resolve() == Path(x).resolve() for x in cfg["inbox_folders"]):
                raise MoveError("The original folder is no longer a watched folder.")
            if not src.parent.is_dir():
                raise MoveError("The original folder no longer exists.")
            back = _free_name(src.parent, src.name)
            _transfer(dest, back, r["sha256"])
            c.execute("UPDATE moves SET status='undone', undone_ts=?, note=? WHERE id=?",
                      (datetime.now().isoformat(timespec="seconds"),
                       None if back == src else f"restored as {back.name}", move_id))
            c.commit()
        finally:
            c.close()
        if log:
            log.info("UNDO %s -> %s", dest, back)
        return {"ok": True, "restored": str(back)}


def _recover(c, log=None) -> int:
    """Settle journal entries left 'pending' by a crash or a failed write. Never removes one of your files:
    the only thing deleted is our own unfinished temporary copy, and only while the original is still there."""
    n = 0
    for r in c.execute("SELECT * FROM moves WHERE status='pending'").fetchall():
        src_ok, dest_ok = os.path.isfile(r["src"]), os.path.isfile(r["dest"])
        if dest_ok and not src_ok and os.path.getsize(r["dest"]) == r["size"]:
            c.execute("UPDATE moves SET status='moved', note=? WHERE id=?",
                      ("journal completed after an interruption", r["id"]))
            what = "the file had been moved; entry completed"
        elif src_ok and not dest_ok:
            partial = r["dest"] + ".shadowfiler-partial"
            try:
                if os.path.isfile(partial):
                    os.remove(partial)
            except OSError:
                pass
            c.execute("DELETE FROM moves WHERE id=?", (r["id"],))
            what = "the file had not been moved; entry dropped"
        else:
            note = ("the original and the filed copy both exist; nothing was removed" if src_ok
                    else "neither the original nor the filed copy was found")
            c.execute("UPDATE moves SET status='interrupted', note=? WHERE id=?", (note, r["id"]))
            what = note
        n += 1
        if log:
            log.warning("interrupted move %s -> %s: %s", r["src"], r["dest"], what)
    if n:
        c.commit()
    return n


def recover(cfg: dict, log=None) -> int:
    with _lock:
        c = _conn(cfg["database"])
        try:
            return _recover(c, log)
        finally:
            c.close()


def journal(cfg: dict, n: int = 100) -> list[dict]:
    c = _conn(cfg["database"])
    try:
        return [dict(r) for r in c.execute("SELECT * FROM moves ORDER BY id DESC LIMIT ?", (n,))]
    finally:
        c.close()


def feedback(cfg: dict) -> dict:
    """How often the top suggestion was what you chose, per suggested folder (moves you didn't undo)."""
    c = _conn(cfg["database"])
    try:
        rows = c.execute("SELECT top_folder, folder, rank, source FROM moves WHERE status='moved' "
                         "AND (source IS NULL OR source NOT LIKE 'auto%')").fetchall()
        auto = c.execute("SELECT COUNT(*) FROM moves WHERE source LIKE 'auto%'").fetchone()[0]
    finally:
        c.close()
    per = {}
    for r in rows:
        k = r["top_folder"] or "(no suggestion)"
        d = per.setdefault(k, {"folder": k, "n": 0, "accepted": 0})
        d["n"] += 1
        d["accepted"] += 1 if (r["rank"] == 1 and r["folder"] == r["top_folder"]) else 0
    total = len(rows)
    acc = sum(d["accepted"] for d in per.values())
    return {"moves": total, "top_accepted": acc, "rate": (acc / total) if total else None, "auto_moves": auto,
            "per_folder": sorted(per.values(), key=lambda d: -d["n"])}


def dismiss(cfg: dict, path: str, size: int, undo_it: bool = False):
    c = _conn(cfg["database"])
    try:
        if undo_it:
            c.execute("DELETE FROM inbox_dismissed WHERE path=?", (path,))
        else:
            c.execute("INSERT OR REPLACE INTO inbox_dismissed VALUES (?,?,?)",
                      (path, size, datetime.now().isoformat(timespec="seconds")))
        c.commit()
    finally:
        c.close()


def dismissed(cfg: dict) -> dict:
    c = _conn(cfg["database"])
    try:
        return {r["path"]: r["size"] for r in c.execute("SELECT path, size FROM inbox_dismissed")}
    finally:
        c.close()
