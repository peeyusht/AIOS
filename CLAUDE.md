# AIOS: notes for Claude Code

Owner: Peeyush Trivedi. Windows 11 PC (TRIVEDIDESKTOP2: Ryzen 7 5800X, 96 GB RAM, GTX 1650 + GTX 1050 Ti,
Ollama). Wants direct, skeptical engineering; push back when something is wrong. Do the git work yourself
(commit, push to github.com/peeyusht/AIOS, keep `main` clean).

## What's here
`shadow-filer/`: a local AI file assistant. Runs from **this folder** (`D:\Projects\AIOS\shadow-filer`) as a
Task Scheduler task "ShadowFiler" (supervisor → agent, `pythonw`, no console). Console: http://127.0.0.1:8765.
- Watches `%USERPROFILE%\Downloads`; PARA tree is `D:\Organized` (37 destinations at depth 2).
- Ollama: `qwen3:4b` (filing guesses), `nomic-embed-text` (search + suggestions).
- Console: **Inbox** (home; Waiting / Recent moves / Auto-filing), **Search**, **Cleanup**, **Activity**
  (Accuracy / Predictions / Log), **Settings** (form + System + Advanced YAML). Designed in Lovable.

| File | Role |
|---|---|
| `shadow_agent.py` | watcher, rules, model prediction, scoring, supervisor, CLI |
| `web_ui.py` | localhost-only HTTP server + JSON API (Host check, per-session token on every POST) |
| `search_index.py` | `search.db`: chunks + embeddings + FTS5; per-file fingerprints (`docvec`) for suggestions |
| `suggest.py` | suggestions: rule → same website (`origin.py`) → file-name-names-one-folder → kNN over filed docs → model |
| `origin.py` | Phase 4: where a download came from (Zone.Identifier mark) as a filing signal; in memory only |
| `mover.py` | the only code that moves files; journal + undo |
| `autofile.py` | Phase 3 auto-filing, per-folder trust from the user's Inbox decisions |
| `cleanup.py` | Cleanup recommendations + Recycle Bin delete of agreed files |
| `ocr.py` | Windows built-in OCR via Windows PowerShell 5.1 (WinRT), no install |
| `config_io.py` | Settings form ⇄ `config.yaml` (validation, commented dump) |
| `ui/` | console source: React + TS + Tailwind, designed in Lovable (`src/shadow`, `src/components/ui`, `src/lib`), plus our static Vite build and `src/lib/adapt.ts`. Read `ui/README.md` first |

## Rules that must hold (don't relax without asking)
- Nothing happens to files on its own except Phase 3 auto-filing, which is **off by default** and only for
  folders proven by the user's own decisions (20+ decisions, ≥90% agreement over the last 30). Those two
  numbers are floors enforced in `autofile.settings()` (`FLOORS`), whatever `config.yaml` says. Trust is per
  (folder, kind of suggestion); undoing an auto-move discards all of that folder's evidence; the evidence
  (first suggestion, rank) is computed server-side in `web_ui._inbox_post`, never taken from the page; the
  waiting time counts from arrival (`cleanup.added_time`), not mtime. Auto-filing accepts rule, file-name
  and similar-documents suggestions only: website (`origin`) matches are suggestions, not in
  `autofile.ALLOWED_SOURCES`, until the user asks for that.
- `mover.py`: only files directly in a watched folder → only existing folders inside PARA root; **never
  overwrite** (identical = refuse, different = "name (2)"); cross-drive = copy → SHA-256 verify → rename into
  place → remove original, roll back if the original is in use; journal every move (`pending` row before the
  file is touched, `moved` after; `mover.recover()` settles leftovers at start and never removes a user file);
  undo refuses if the filed copy changed. A cross-drive move carries the file's Zone.Identifier stream
  (Windows' "came from the internet" mark) to the copy; `shutil.copy2` alone drops it. `mover.make_folder` (Inbox › New folder…) creates one empty folder
  directly under an existing PARA folder above destination depth (`os.mkdir`, never `makedirs`, refuses any
  existing name); creating a folder never moves a file.
- Deletion only via Cleanup → **Recycle Bin**, only files the user marked Agree, each re-checked first. Files
  too big for the bin need a separate explicit confirmation. Keep/archive items (firmware, VM images) are never
  deletable from the UI.
- Password-protected PDFs are never opened or guessed. The one thing tried is the empty password, which is
  how every viewer opens a PDF that is only protected against editing (needs `cryptography` for AES). Cloud-only placeholders are never opened: any new code
  that reads a file must check `is_cloud_only` first (`shadow_agent`, `search_index`, `cleanup` each have one).
- File contents are untrusted data in model prompts.
- Never commit personal data: `*.db`, logs (including rotated `shadow.log.1`…), `cleanup_report.json`,
  `config.yaml` (see `.gitignore`).
  `search.db` holds extracted text from personal documents (PAN, insurance, contracts).

## Working on it
- Python 3.12 venv: `shadow-filer\.venv` (copied from an old location: use `.venv\Scripts\python -m pip`,
  not `pip.exe`). Dependencies: `requirements.txt`. No numpy in the runtime (pure-Python vectors are fast enough).
- UI: the user prefers to design in Lovable (project
  https://lovable.dev/projects/24a52f89-2976-48ff-9630-4d56617c2f80; each Lovable message spends their
  credits). Design changes go there, then the Lovable-owned files are copied into `ui/` unchanged (see
  `ui/README.md`); small wiring fixes can be made locally but must be sent back to Lovable or they are lost on
  the next copy. Build: `cd ui; npm run build` → `ui_dist/` (hashed asset names; no agent restart). Lovable only
  ever sees fictional demo data (`src/lib/mock.ts`): never send it real file names or screenshots of real data.
  When the agent's API changes shape, update `ui/src/lib/adapt.ts` and tell Lovable the new shape.
- Restart the agent after Python changes: console Settings › Restart agent, or POST `/api/restart` with the
  `X-Shadow-Token` from the page's `<meta name="shadow-token">`. Static UI files need no restart.
- Re-register the task (paths/flags changed): `powershell -ExecutionPolicy Bypass -File .\install_task.ps1`.
- Useful CLI: `shadow_agent.py check | report | cleanup | search "<q>" | sysinfo`.
- Self-tests worth running after related changes: Settings › OCR › Test OCR (`/api/ocr/selftest`); Recycle Bin
  self-test `/api/cleanup/selftest` (creates and recycles a tiny file in the agent folder).
- Tests: `.venv\Scripts\python -m unittest discover -s tests` (stdlib unittest, temp folders only). Run them
  after touching `mover.py`, `autofile.py`, `cleanup.py` or the cloud-only checks; add a test with any new rule.
- Test file moves on throwaway folders first; never experiment on `Downloads` or `D:\Organized`.
- To click through the console for real (File it, Undo, delete, save settings) use a throwaway agent, never the
  live one: `python tests\make_test_agent.py <temp folder> [--tiny-bin]` builds a copy of the code with made-up
  inbox/PARA files on port 8766 (its own `search.db`, cleanup report and logs, because those live next to the
  code), then run `shadow_agent.py --config config.yaml run` in `<temp folder>\agent`. Files it recycles do
  land in the real Recycle Bin. "Show"/"Open" launch Explorer or an app on the user's desktop: close them after.
  Screenshots of the tab sometimes stall; reading the page with JavaScript (`innerText`, clicking by text) works.

## Measured numbers (11 Oct 2026, leave-one-out on the user's filed documents)
- Similar-documents suggestion: top-1 72%, top-3 88% (909 docs with text). Shown 95%+ → right 94%;
  50–70% → 72%; under 50% → 33%. Fingerprints exclude the folder name on purpose (including it leaked the
  answer and inflated accuracy to ~84%/99%).
- File name naming exactly one folder (e.g. "pavak" → 1-Projects/Pavak-Incorporation): right 86.1% (259 of
  1,365 filed files get one; same figure leave-one-out). Words of 4+ letters only was 85.6% (236). Plain
  3-letter words dropped it to 75% ("nac" right 16%, "cbs" 33%), so a 3-letter word counts only while ≥80% of
  filed names containing it are in its folder (`suggest.name_owners`, `short_word_share`), or, with nothing
  filed yet, when it is the folder's whole name; never everyday words (`COMMON3`). 1–2 letter words count only
  joined to a neighbour ("GR-One" → "grone"). Re-measure before loosening any of this.
- The model's own confidence is useless (0.95 on almost everything); don't use it for decisions.
- Same website → same folder (`origin.py`): 596 of 1,368 filed files still carry a download address. A site
  with 3+ other filed files and 80%+ of them in one folder was right 84 times in 87 (97%, leave-one-out);
  webmail, chat and drive sites never qualify (claude.ai: 159 files in 22 folders). Coverage is small: 16 of
  the 483 waiting files on the day it shipped. The referring page is a weaker signal (90%) and is not used.
- Down-weighting Archive folders was measured and rejected: for filed files changed in the last year,
  similar-documents voting says "Archive" 18% of the time against 16% truly there, and any down-weight lowered
  accuracy (69% → 66%). The Finance → Frux-Technologies lean is specific to that folder's 413 old documents.

## Open items
- Finance-type spreadsheets lean to `4-Archives/Frux-Technologies` (413 similar old docs); improves as the
  user files into Finance. A general archive down-weight does not help (see Measured numbers).
- Nothing has been filed through the Inbox yet (0 moves, 11 Oct 2026), so auto-filing has no evidence and the
  first-suggestion accuracy has only been measured on already-filed files, not on real Inbox decisions.
- 15 PDFs in the index need a real password and stay "locked".
- C: has <10% free space; Ollama runs qwen3:4b ~94% on GPU (`LLAMA_ARG_FIT_TARGET` was tuned to 512 MB).
- Speed (11 Oct 2026, 1,365 filed examples, 17,710 chunks): comparisons use `math.sumprod` (~1.8x faster than
  `sum(map(mul))`); kNN votes are cached per file in `Suggester._knn` until a fingerprint or the examples
  change. A search is still seconds, mostly the Ollama embedding call.
- Proposed next phases (not started, order agreed with nobody yet): 5 document watch (expiry/deadline
  tracker, sensitive-data watch), 6 library and hygiene (firmware/VM library, version chains, near-duplicate
  images, Authenticode checks), 7 work journal.
