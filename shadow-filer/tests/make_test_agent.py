"""Build a throwaway Shadow Filer for clicking through the console without touching real files.

It copies the code and the built UI into <target>/agent (so its search.db, cleanup report and logs are its
own: they live next to the code), creates made-up inbox and PARA folders with fictional files, some carrying
a "downloaded from" mark, and writes a config.yaml on port 8766.

    python tests/make_test_agent.py <target folder> [--tiny-bin]
    cd <target folder>/agent
    <venv python> shadow_agent.py --config config.yaml run        -> http://127.0.0.1:8766

--tiny-bin makes the copy pretend the Recycle Bin holds 1 KB, to exercise "too big, delete permanently".
Files it recycles land in the real Recycle Bin; Show and Open launch Explorer / an app on the desktop.
Stop it with Ctrl+C (or end the process on port 8766) and delete the target folder afterwards.
"""
import os
import shutil
import sys
import textwrap
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if len(args) != 1:
    sys.exit(__doc__)
T = Path(args[0]).resolve()
if T == SRC or SRC in T.parents:
    sys.exit("Choose a target outside the shadow-filer folder.")
if T.exists():
    shutil.rmtree(T)
agent, inbox, para = T / "agent", T / "inbox", T / "para"
agent.mkdir(parents=True)
for f in list(SRC.glob("*.py")) + [SRC / "ui.html"]:
    shutil.copy2(f, agent / f.name)
shutil.copytree(SRC / "ui_dist", agent / "ui_dist")

if "--tiny-bin" in sys.argv:  # only in the copy: pretend the Recycle Bin holds at most 1 KB
    code = (agent / "cleanup.py").read_text(encoding="utf-8")
    needle = "def recycle_bin_limit(path: str) -> dict:\n"
    assert code.count(needle) == 1
    code = code.replace(needle, needle + '    return {"known": True, "nuke": False, "max_bytes": 1024, '
                                         '"drive": "TEST", "volume_bytes": 0}\n')
    (agent / "cleanup.py").write_text(code, encoding="utf-8")


def w(p: Path, text: str, site: str | None = None):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")
    if site and os.name == "nt":  # the mark browsers leave on downloads (origin.py reads it)
        with open(str(p) + ":Zone.Identifier", "w", encoding="utf-8", newline="") as f:
            f.write(f"[ZoneTransfer]\r\nZoneId=3\r\nReferrerUrl=https://{site}/\r\nHostUrl=https://{site}/download/file\r\n")


topics = {
    "1-Projects/Acme-Rollout": ("Acme rollout", "The Acme network rollout covers site surveys, switch staging, "
                                "cutover rehearsal and sign-off. Milestone {i}: wave {i} migrated.", "mail.example.com"),
    "2-Areas/Finance": ("Invoice", "Tax invoice INV-2026-{i:03d} from Northwind Supplies. Amount due 4,{i}50.00, "
                        "net 30, GST included.", "mail.example.com"),
    "2-Areas/Payroll": ("Payslip", "Payslip for month {i}: basic pay, allowances, deductions, net pay credited "
                        "to bank account.", "portal.payroll.example"),
    "3-Resources/Manuals": ("Manual", "User manual chapter {i}: installing the router, firmware upgrade, factory "
                            "reset, LED status table.", None),
}
for folder, (title, body, site) in topics.items():
    for i in range(1, 7):
        w(para / folder / f"{title.replace(' ', '_')}_{i}.txt", f"{title} {i}\n\n" + body.format(i=i), site)
w(inbox / "statement-october.txt", "Monthly statement: pay, allowances, deductions and net pay for October.",
  "portal.payroll.example")
w(inbox / "Acme_status_report.txt", "Acme rollout weekly status. Wave 12 migrated, cutover rehearsal passed.",
  "mail.example.com")
w(inbox / "GR-One kickoff notes.txt", "Kickoff notes for the new GR One engagement: stakeholders and timeline.")
w(inbox / "sf_open_test_9f3.txt", "File used to test the Show and Open buttons.")
w(inbox / "big_report.txt", "Quarterly report draft, version A. " * 400)
(inbox / "big_report (1).txt").write_bytes((inbox / "big_report.txt").read_bytes())      # duplicate, over 1 KB
w(inbox / "small_note.txt", "tiny " * 20)
(inbox / "small_note (1).txt").write_bytes((inbox / "small_note.txt").read_bytes())      # duplicate, under 1 KB
old = time.time() - 40 * 86400   # Cleanup skips files changed in the last 10 minutes
for p in list(inbox.rglob("*")) + list(para.rglob("*")):
    if p.is_file():
        os.utime(p, (old, old))
(agent / "config.yaml").write_text(textwrap.dedent(f"""
    inbox_folders:
    - {inbox}
    para_root: {para}
    destination_depth: 2
    exclude_destinations: []
    ollama:
      url: http://localhost:11434
      model: qwen3:4b
      timeout_seconds: 120
      think: false
      startup_wait_seconds: 5
    extraction:
      max_chars: 4000
      max_pdf_pages: 5
    settle_seconds: 2
    hash_max_mb: 200
    reconcile_minutes: 30
    history_examples: 15
    catch_up_days: 0
    ui:
      enabled: true
      port: 8766
    database: shadow.db
    log_file: shadow.log
    ignore_patterns:
    - '*.tmp'
    rules: []
    cleanup:
      scan_hours: 0
    """).lstrip(), encoding="utf-8")
print(f"ready: {T}\nrun:   cd {agent}  &&  python shadow_agent.py --config config.yaml run   (http://127.0.0.1:8766)")
