"""
The worker (phase 2): keeps one copy of the public reference lists and judges every device against them.

Two jobs, in one process:
  lists    Once a day it downloads the CVE list (nvd.nist.gov), the known-exploited list (www.cisa.gov) and the
           end-of-life list (endoflife.date) into a SQLite file on its own volume. These are plain downloads
           of fixed public files: nothing about any customer or device is in a request. The first run reads
           about 300 MB and takes some minutes; later runs read one small file.
  judging  It asks the database which devices are waiting (new facts, newer lists, or a new day), and for
           each one compares its programs with the lists, runs the compliance checks, and stores the result
           and one history line for the day.

It is under the same row-level security as the API: the queue gives it ids only, and it then works inside one
organisation at a time. It never talks to a device.

  python -m app.worker            run for ever
  python -m app.worker --once     judge whatever is waiting with the lists as they are, then stop (no download)
"""
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from . import db, judge

log = logging.getLogger("worker")
REF = Path(os.environ.get("REFERENCE_DIR", "/data/ref"))
CFG = {"cve_database": REF / "cve.db"}
SYNC_HOURS = int(os.environ.get("REFERENCE_HOURS", "24"))
IDLE_SECONDS = 10
BATCH = 20
_sync = {"thread": None, "had_lists": False}


# --------------------------------------------------------------------------- the reference lists
def ref_version(cfg: dict = CFG) -> str:
    """Changes whenever a list changed, which is what sends every device round again."""
    import cve
    import eol
    if not cve.db_path(cfg).exists():
        return "none"
    s = cve.status(cfg)
    return f"cve:{s['synced_at'] if s['complete'] else 'incomplete'}|eol:{eol.status(cfg)['synced_at']}"


def publish_status(cfg: dict = CFG, syncing: bool = False) -> None:
    """Tell the console how fresh the lists are (a small shared table; no customer data)."""
    import cve
    import eol
    s = cve.status(cfg)
    e = eol.status(cfg) if cve.db_path(cfg).exists() else {"synced_at": None, "products": 0, "error": None}
    rows = {"cve_synced_at": s["synced_at"], "cve_tried_at": s["tried_at"], "cve_complete": "1" if s["complete"] else "0",
            "cves": s["cves"], "kev": s["kev"], "cve_error": s["error"], "eol_synced_at": e["synced_at"],
            "eol_products": e["products"], "eol_error": e["error"], "syncing": "1" if syncing else "0"}
    with db.anon() as c:
        for k, v in rows.items():
            c.execute("INSERT INTO reference_status (k, v, at) VALUES (%s,%s, now()) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v, at = now()",
                      (k, "" if v is None else str(v)))


def sync(cfg: dict = CFG) -> None:
    import cve
    import eol
    try:
        publish_status(cfg, syncing=True)
        got = cve.sync(cfg, progress=lambda m: log.info("%s", m), log=log)
        eol.sync(cfg, log=log)
        log.info("lists: %d feed file(s) read, %d error(s)", len(got["feeds"]), len(got["errors"]))
    except Exception:
        log.exception("the reference lists could not be updated")
    finally:
        try:
            publish_status(cfg)
        except Exception:
            log.exception("the list status could not be published")


def sync_if_due(cfg: dict = CFG) -> None:
    import cve
    t = _sync["thread"]
    if t and t.is_alive():
        return
    had = cve.db_path(cfg).exists() and judge.ref_ready(cfg)
    if not cve.due(cfg, SYNC_HOURS if had else 1):      # an unfinished first download is tried again within the hour
        return
    _sync["had_lists"] = had
    cve.db_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    _sync["thread"] = threading.Thread(target=sync, args=(cfg,), name="lists", daemon=True)
    _sync["thread"].start()


def syncing() -> bool:
    t = _sync["thread"]
    return bool(t and t.is_alive())


# --------------------------------------------------------------------------- judging
def judge_device(device_id, org_id, cfg: dict, ref: str, today, use_lists: bool = True) -> dict | None:
    """Judge one device inside its own organisation and store the result. Returns its summary."""
    with db.org(org_id) as c:
        dev = c.execute("SELECT facts_at FROM devices WHERE id = %s", (device_id,)).fetchone()
        if not dev:
            return None
        snaps = {r["kind"]: r["payload"] for r in c.execute(
            "SELECT DISTINCT ON (kind) kind, payload FROM snapshots WHERE device_id=%s ORDER BY kind, received_at DESC, id DESC", (device_id,))}
        accepted = {r["check_id"]: {"reason": r["reason"], "ts": r["at"].isoformat(timespec="seconds"), "actor": r["actor"]}
                    for r in c.execute("SELECT check_id, reason, at, actor FROM exceptions WHERE device_id = %s", (device_id,))}
    # the comparison takes a few seconds and needs no database connection
    vul = judge.flaws(cfg, snaps) if use_lists else None
    sup = judge.support(cfg, snaps, today) if use_lists else None
    comp = judge.assess(snaps, vul, sup, accepted, today)
    summ = judge.summary(comp, vul, sup)
    with db.org(org_id) as c:
        c.execute("""INSERT INTO judgements (device_id, org_id, judged_at, ref, summary, security, compliance)
                     VALUES (%s,%s, now(), %s,%s,%s,%s)
                     ON CONFLICT (device_id) DO UPDATE SET judged_at = now(), ref = EXCLUDED.ref, summary = EXCLUDED.summary,
                       security = EXCLUDED.security, compliance = EXCLUDED.compliance""",
                  (device_id, org_id, ref, Jsonb(summ), Jsonb({"flaws": vul, "support": sup}), Jsonb(comp)))
        c.execute("""INSERT INTO compliance_history (org_id, device_id, day, line) VALUES (%s,%s,%s,%s)
                     ON CONFLICT (device_id, day) DO UPDATE SET line = EXCLUDED.line""",
                  (org_id, device_id, today, Jsonb(judge.history_line(comp))))
        # the facts this judgement was made for: a check-in that landed meanwhile has a later facts_at and queues it again
        c.execute("UPDATE devices SET judged_facts_at = %s, judged_ref = %s, judged_day = %s WHERE id = %s",
                  (dev["facts_at"], ref, today, device_id))
    return summ


def round_(cfg: dict = CFG, today=None) -> int:
    """Judge what is waiting. Returns how many devices were judged. During the first download of the lists
    devices are judged without them (the settings checks still count), and again once the lists are there."""
    today = today or datetime.now(timezone.utc).date()
    busy = syncing()                # while the lists are being written they are not read at all
    if busy and _sync["had_lists"]:
        return 0                    # a short daily refresh: wait for it
    ref = "none" if busy else ref_version(cfg)
    done = 0
    while True:
        with db.anon() as c:
            waiting = c.execute("SELECT * FROM judge_queue(%s,%s,%s)", (ref, today, BATCH)).fetchall()
        if not waiting:
            return done
        for w in waiting:
            try:
                t0 = time.time()
                s = judge_device(w["device_id"], w["org_id"], cfg, ref, today, use_lists=not busy)
                if s:           # ids and counts only: nothing a device reported is repeated in the log
                    log.info("judged device %s in %.1f s: %d of %d control areas pass", w["device_id"], time.time() - t0,
                             s["compliance"]["controls_passing"], s["compliance"]["controls"])
                done += 1
            except Exception:
                log.exception("device %s could not be judged", w["device_id"])
                return done         # it stays in the queue; try again next round instead of spinning on it
        if len(waiting) < BATCH:
            return done


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    once = "--once" in sys.argv[1:]
    log.info("worker started; reference lists in %s", REF)
    while True:
        try:
            if not once:
                sync_if_due()
            n = round_()
            if once:
                log.info("judged %d device(s)", n)
                return
        except Exception:
            log.exception("round failed")
            if once:
                raise
        time.sleep(IDLE_SECONDS)


if __name__ == "__main__":
    main()
