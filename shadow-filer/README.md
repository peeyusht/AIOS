# Shadow Filer — Phase 1 (Windows)

Watches your Downloads folder, predicts where each new file belongs in your PARA tree, and records the prediction.
When you file the file yourself, it records where it actually went. After 2–3 weeks the Overview page shows how
accurate rules and the model are, per category and per confidence level.

**Nothing happens to your files on its own.** It moves a file only when you click **File it** on the Inbox page
(never overwriting, journaled, undoable), and sends files to the Recycle Bin only when you confirm on Cleanup.
The one exception is auto-filing (Phase 3, below), which is off until you switch it on.

The console (http://127.0.0.1:8765) has seven places: **Inbox** (the home page: files waiting, File it / Undo,
recent moves, auto-filing), **Search** (meaning + keyword search over your folders), **Cleanup** (duplicates,
extracted archives, old installers), **Watch** (dates coming up in your documents, sensitive files left in
Downloads), **Library** (firmware and VM images, versions of a document, look-alike pictures, who signed your
installers), **Activity** (accuracy, predictions, log) and **Settings** (a form, system information, and the raw
YAML under Advanced).

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
The console is designed in Lovable and built from `ui/` into `ui_dist/` (`cd ui`, `npm install`, `npm run build`).
See `ui/README.md` for what comes from Lovable, what is ours, and how to bring a new design version in.

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

## Inbox: suggest mode (Phase 2)
Every file waiting in Downloads gets up to three destination suggestions. **File it** moves it; **Undo** moves it back.
- **Where suggestions come from:** your already-filed documents. Each file has a fingerprint (name + start of its
  text, embedded locally with `nomic-embed-text`, never its folder). A new file's 10 most similar filed documents
  vote for their folders; the share of the vote is the percentage shown. A matching rule is always listed first.
  Next, the website the file was downloaded from: if at least three files you've already filed came from the
  same site and 80% or more of them are in one folder (a payroll portal, a vendor's support site), that folder
  is suggested. Sites whose files go everywhere (webmail, chat) suggest nothing. The Inbox shows "from
  <site>" under each file that carries a download address. Like the other kinds, it can auto-file only
  after 20 of your own decisions have proven that folder for website matches.
  Next, if the file name mentions a word that names exactly one folder (e.g. "Pavak", "Muthoot", "Shivalik";
  short names work too: "GR-One" matches GR-One, GR_One or GROne in a file name, and a 3-letter word such as
  "HCL" counts as long as the files you've already filed with it in their names are in that folder),
  that folder: right 86% of the time on 236 filed documents, and it works for new folders with few files, where
  similar-document voting can't. The local model's pick is listed too when it differs.
- **Measured accuracy** (leave-one-out on 909 filed documents with text, 11 Oct 2026): first suggestion right
  72%, right folder in the top three 88%. Shown at 95%+: right 94%; 50–70%: 72%; under 50%: 33%.
- **Moving safely (`mover.py`):** only files directly in a watched folder, only into existing folders inside the
  PARA root; never overwrites (identical copy already there = not moved; different file with the same name =
  saved as "name (2)"); across drives it copies, verifies the SHA-256, then removes the original, and if the
  original is open in another program nothing changes. Every move is journaled in `shadow.db` and undoable unless
  the filed copy was edited afterwards.
- **New folder…** creates an empty folder for files that fit none of the existing ones: pick the folder it
  goes in (one that already exists in your PARA tree, e.g. `1-Projects`) and type a name. Creating it moves
  nothing; the new folder is selected and the file goes there when you click **File it**. It never touches a
  folder or file that already exists, and from then on the folder is suggested like any other.
- **Leave it** hides a file from the Inbox without touching it.
- "Your filing so far" shows how often the first suggestion was what you chose, per folder: the evidence for
  Phase 3 (auto-filing proven folders).

## Auto-filing (Phase 3)
Off until you switch it on (Inbox page › Auto-filing › Turn on, or Settings). Even then, a file is moved
automatically only when **all** of these hold:
- its first suggestion's folder is **proven**: at least 20 of your Inbox decisions about that folder, agreeing with
  its suggestion at least 90% of the time over the last 30 (filing elsewhere, or undoing a move, counts against).
  This is counted separately for each kind of suggestion (rule, file name, similar documents): a folder proven
  by similar-document suggestions is not thereby trusted for file-name matches. Settings can make the bar
  stricter; 20 decisions and 90% are floors that the program enforces whatever `config.yaml` says;
- the suggestion is a rule, a same-website match, a file-name match, or similar-documents at 95%+ (never the
  model's guess alone);
- the file has been in Downloads for 15 minutes (counted from when it arrived, not from a modified date it kept
  from elsewhere), Cleanup doesn't flag it, and it isn't password-protected;
- the same `mover.py` guarantees as File it: never overwrite, verified cross-drive copies, journal, **Undo**.
Undoing an auto-move wipes everything that folder had earned, for every kind of suggestion: it goes back to
suggestions only until it is proven again from zero. Below the bar, likewise.
What "the first suggestion" was is worked out by the agent when you file, not reported by the page.

## Document watch
The Watch page reads the text the search index already holds; it opens no file again and changes nothing.
- **Dates**: an expiry, renewal, due or "valid until" date is listed when the document itself says what the
  date is. Dates within 60 days are "coming up" (the sidebar shows how many); dates that passed more than 90
  days ago are counted but not listed. Copies of the same document appear once. Each entry quotes the line it
  was read from so you can judge it, and **Dismiss** hides one that is wrong or dealt with.
- **Sensitive files**: files in Downloads whose text holds a PAN (a person's, not a company's), an Aadhaar
  number, a payment card number, bank account details, a passport number or a private key. The page says what
  kind and how many, never the numbers themselves, and nothing about them is stored. Long numbers in logs and
  spreadsheets are not flagged unless they are written like the real thing or named as such.
Both are in Settings › Document watch (on/off, days ahead, how long passed dates stay listed).

## Preview before filing
**Preview** on an Inbox file (and on a search result) opens a side panel with the document's text as the agent
read it, so you can check what a file is before filing it. It uses what the search index already holds, so no
file is opened again; scans say they were read by OCR, long documents show their start, and files with no
text (archives, images of firmware, password-protected PDFs) say why. **Open** in the panel launches the file
in its normal app when you need the real layout.

## Work journal
Activity › Journal is a dated record, newest day first: what arrived in Downloads, what was filed where (through
the Inbox, automatically, or by hand in Explorer) and what was undone, what Cleanup sent to the Recycle Bin, and
which of your folders had documents added or changed. Pick 7, 30 or 90 days; **Copy as text** gives the same
record as plain text for a status report or a timesheet. It is put together from what the agent already
records plus file dates; no file is opened. A file only remembers its last change, so the agent notes once a
day which documents were added or changed: the "worked on" list is complete for days the agent was running.

## Library
The Library page lists what you already hold. It is read-only: nothing is moved, renamed or deleted from it.
- **Images**: firmware, OS and VM images grouped by product, with the versions you have, their size and where
  they are. A folder an appliance was unpacked into counts as one item.
- **Versions**: documents that are versions of one another ("_v2", "_Final", "_R1", a date in the name), newest
  first, flagged when the copy you filed is older than one still in Downloads. Files that differ only by
  "(1)" are listed separately as "same name": they are often different documents.
- **Pictures**: pictures that look the same (resized, re-saved, downloaded twice), compared by a small
  fingerprint of the picture rather than by name.
- **Installers**: programs and installers, and whether Windows accepts the publisher's signature: signed, not
  signed, not trusted, or changed after signing.
A scan runs once a day (Settings › Library) or when you click Scan now; the first one takes a few seconds.
**Hide** removes an entry from the list (not from disk); **Show** opens its folder.

## Tests
`.venv\Scripts\python -m unittest discover -s tests` (from this folder). They run on throwaway folders and
cover the mover (no overwrite, verified cross-drive copy, rollback, journal, undo), the auto-filing rules,
the last check before a delete, and the cloud-only rule. Nothing in Downloads or your PARA tree is touched.
The Inbox page shows each folder's progress and marks files that would be auto-filed, so you can see what it
would do before turning it on. Thresholds are in Settings › Auto-filing (Phase 3).
