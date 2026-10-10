# Shadow Filer — Phase 1 (Windows)

Watches your Downloads folder, predicts where each new file belongs in your PARA tree, and records the prediction.
When you file the file yourself, it records where it actually went. After 2–3 weeks the Overview page shows how
accurate rules and the model are, per category and per confidence level.

**It never moves, renames or copies anything.** It only reads files, except on the Cleanup page, where it sends
files you marked Agree to the Recycle Bin after you confirm.

Pages in the console (http://127.0.0.1:8765): Overview, **Search** (meaning + keyword search over your folders),
Predictions, **Cleanup** (duplicates, extracted archives, old installers), Log, System, **Settings** (a form; YAML under Advanced).

## 1. Install (one time)

1. **Python 3.11+** from python.org (tick "Add python.exe to PATH").
2. **Ollama for Windows** from ollama.com, then in a terminal:
   ```
   ollama pull qwen3:4b
   ollama pull nomic-embed-text
   ```
   (`nomic-embed-text` powers the Search page.)
   Ollama starts at login by default; confirm it's enabled under Task Manager > Startup apps.
3. Copy this folder somewhere permanent, e.g. `C:\Tools\shadow-filer`, then:
   ```
   cd C:\Tools\shadow-filer
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

## 2. Configure

Copy `config.example.yaml` to `config.yaml` (your copy is not committed to git), then edit it, or later use the
**Settings** page in the web UI:
- `para_root` — your PARA folder (e.g. `G:\My Drive\PARA`).
- `rules` — the sample rules point at example folders; change them to your real ones or delete them.
- Then check:
  ```
  .venv\Scripts\python shadow_agent.py check
  .venv\Scripts\python shadow_agent.py destinations
  ```
  Aim for under ~80 destinations; use `destination_depth` or `exclude_destinations` to trim.

Try one file: `.venv\Scripts\python shadow_agent.py test "%USERPROFILE%\Downloads\some.pdf"`

## 3. Start it, and keep it running across reboots

```
powershell -ExecutionPolicy Bypass -File .\install_task.ps1
```
This registers a Task Scheduler task that:
- starts 30 seconds after you log in (every boot),
- has **no time limit** (Task Scheduler's default would kill it after 3 days),
- runs a small supervisor that runs the agent and restarts it when you click **Restart agent**
  or if it crashes (backing off up to 5 minutes if it keeps crashing; see `supervisor.log`),
- runs as you with normal rights (no admin).

If you update `install_task.ps1`, run it again; it replaces the existing task.

**Moving an existing install** (e.g. from `D:\Tools\shadow-filer` to this folder): run, from the new folder,
```
powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -MigrateFrom D:\Tools\shadow-filer
```
It stops the running agent, copies `config.yaml`, the databases, logs and `.venv`, and starts the agent from the
new folder. The old folder is left as it was. Note: `pip.exe` inside a copied `.venv` still points at the old
folder; use `.venv\Scripts\python -m pip ...` instead.

Remove it with `install_task.ps1 -Remove`. Your data is kept.

**What happens around a reboot**
| Situation | What the agent does |
|---|---|
| Ollama starts later than the agent | Waits up to 5 minutes for it instead of logging errors |
| Files downloaded while the agent was off | Predicted at startup (`catch_up_days`, default last 7 days) |
| PC slept or hibernated | The sweep every 30 minutes catches files whose events were missed |
| You filed files while the agent was off | The same sweep matches them, including renamed ones |
| A prediction failed (Ollama down) | Retried on the next sweep |
| Two copies started by accident | The second one exits; only one can hold the UI port |
| A configured folder is missing | Stays up, shows the problem in the UI, waits for you to fix it |

Logged out entirely (e.g. Windows Update reboot overnight)? Nothing runs until you log in, then catch-up covers it.
Downloads only change while you're logged in anyway.

## 4. The web UI

Open **http://127.0.0.1:8765** (or double-click `open_ui.url`).

- **Overview** — accuracy so far, accuracy by method and by the model's stated confidence, most common misses.
- **Predictions** — every file with what it predicted and where you filed it. Filter by matched, missed,
  not filed yet, unsure or errors; search by file or folder.
- **Log** — live log, errors highlighted.
- **System** — hardware, OS, disks, GPUs (real VRAM and UUIDs from `nvidia-smi`), the `CUDA_VISIBLE_DEVICES`
  Ollama will see, and how much of the currently loaded model sits in GPU memory. Problems worth acting on are listed
  at the top. A one-line summary is also written to the log each time the agent starts.
- **Settings** — edit `config.yaml` in place. Rules, ignore patterns and model settings apply immediately on save;
  folder changes need a restart (there's a button). Invalid YAML or broken rules are rejected before saving, and the
  previous version is kept as `config.yaml.bak`.

UI security: it listens on 127.0.0.1 only, rejects requests not addressed to localhost (blocks DNS-rebinding from
web pages you visit), and every change requires a per-session token only the served page has.

UI only, without the agent (e.g. to look at results): `.venv\Scripts\python shadow_agent.py ui`

## 5. Command line (optional)
```
shadow_agent.py report [--csv results.csv]   same numbers as the Overview page
shadow_agent.py reconcile                    match filings now instead of waiting for the sweep
shadow_agent.py scan                         predict everything currently in the inbox (ignores catch_up_days)
shadow_agent.py sysinfo [--json]             same information as the System page
```

## Reading the results
- **exact** — same folder at your chosen depth. **category** — same PARA top level.
- **by confidence** — if 95%+ isn't clearly more accurate than 50–80%, the model's confidence can't be used as an
  auto-move threshold in Phase 2. Small models are often poorly calibrated; this is how you find out.
- Gate to Phase 2 (suggest mode): a few hundred scored files and per-category accuracy you'd trust.

## Known limitations
- **Google Drive streamed mode:** change events from the virtual `G:` drive may be unreliable; the 30-minute sweep is the
  safety net. The sweep reads files whose size equals a pending prediction's size (to match renames), which on a
  streamed drive can trigger a download of that file. Rare.
- **Restart button** only works when started by the scheduled task (the supervisor). A copy you started by hand
  says so instead of restarting.
- **No OCR yet:** scanned PDFs and images are classified by file name only.
- **Files you delete or leave in Downloads** stay "not filed yet" and aren't scored.
- **Your filing history is fed to the model** (`history_examples`), so accuracy should improve over time.
  Set it to 0 to measure the raw model.
- **Privacy:** everything runs locally; file text only goes to Ollama on localhost.

## Cleanup recommendations (Cleanup page)
Recommends files in Downloads that could be deleted. Mark **Agree / Disagree** on each (this also teaches which
rules can be trusted). **Move to Recycle Bin** then deletes only the files you agreed to, after a confirm, and only
after re-checking each one (unchanged since the scan, the kept copy still identical, the zip still fully extracted).
Files too big for the Recycle Bin are listed separately and need a second, explicit confirmation to delete
permanently. Firmware / VM images (Keep) can't be deleted from here. Every action is logged.

- **Safe to delete:** identical content (SHA-256) already in your PARA tree or elsewhere in Downloads
  (names can differ), partial downloads, archives already extracted next to themselves.
- **Probably safe:** installers and driver packages older than 30 days.
- **Review:** other programs (may be portable tools), and old files with no Recent Items entry.
  Documents, scripts and keys/certificates are never flagged on age, only as duplicates.
- **Keep / archive:** firmware, OS and VM images (.out .bin .img .iso .ova .vmdk ...).
- Files are opened only when another file has the same size. Cloud-only files are never opened.
- Runs automatically every 24 h inside the agent, or on demand: **Scan now**, or
  `shadow_agent.py cleanup [--csv out.csv]`. Results: `cleanup_report.json`; your choices: `shadow.db`.
- Tune in config.yaml (optional):
  ```
  cleanup:
    scan_hours: 24
    installer_days: 30
    driver_days: 30
    stale_days: 180
  ```

## Search (Search page)
Finds files in your inbox folders and PARA root by meaning and by exact words.
- Text from PDF, Word, Excel, PowerPoint and text files is split into passages and embedded locally with
  `nomic-embed-text` (Ollama). Other files (zips, images, executables, scanned PDFs) are findable by name.
- The index (`search.db`) builds in the background after the agent starts and stays current: new or changed
  files are picked up within seconds, and a sweep every 30 minutes catches anything missed.
- `search.db` contains text from your documents. It never leaves this PC. Delete it to wipe it; it is rebuilt.
- CLI: `shadow_agent.py search "posture audit findings"`
- Optional settings in config.yaml:
  ```
  search:
    enabled: true
    model: nomic-embed-text
    extra_folders: []        # e.g. ['%USERPROFILE%\Documents']
    exclude_globs: []        # e.g. ['*\node_modules\*']
    min_similarity: 0.45     # raise if you see weak matches, lower if good ones are missing
  ```

## Working on the UI
The console is the original Vite build in `ui_src/base/` plus three pages written against its components
(`ui_src/cleanup_page.js`, `search_page.js`, `settings_page.js`). After editing them, rebuild with
`python ui_src/build_ui.py`, which writes `ui_dist/`.

## Your data (never committed)
`shadow.db` (predictions, cleanup choices), `search.db` (text extracted from your documents), `cleanup_report.json`,
logs and `config.yaml` are listed in `.gitignore`. Keep it that way: they contain file names and document contents.

## OCR (scanned files)
Scanned PDFs, images (screenshots, photos of documents) and Word files that contain only screenshots are read with
the OCR engine built into Windows 10/11, so they become searchable and get better filing predictions. Nothing to
install: `ocr.py` drives Windows' own OCR and PDF renderer through Windows PowerShell (no console window).
- Password-protected PDFs are never opened; Search shows them as "Password-protected".
- Settings › OCR: turn it on/off, pages read per scanned PDF (default 10), minimum image size (default 15 KB,
  to skip icons and logos), and a **Test OCR** button.
- OCR uses the Windows display language's OCR pack (English is installed by default on English Windows).
- OCR text lands in `search.db` like any other document text: same sensitivity, same "never leaves this PC".
