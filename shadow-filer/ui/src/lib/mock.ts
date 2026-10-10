/* Entirely fictional demo data with in-memory mutations, used when no agent token is present. */
import type {
  AutofileResponse,
  CleanupHistoryRow,
  CleanupItem,
  CleanupResponse,
  InboxItem,
  JournalRow,
  Prediction,
  Raw,
  SearchResult,
  SearchStatus,
  Stats,
  Status,
  SystemInfo,
} from "./types";

const DL = "C:\\Users\\alex\\Downloads";
const PARA = "D:\\PARA";
const MB = 1024 * 1024;

export const demo = {
  unreachable: false,
  emptyInbox: false,
  problem: false,
  modelMissing: false,
};

const now = () => new Date();
const iso = (d: Date) => {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};
const ago = (min: number): string => iso(new Date(Date.now() - min * 60000));

export const destinations = [
  "1-Projects/Acme-Rollout",
  "1-Projects/Acme-Rollout/Contracts",
  "1-Projects/Northwind-Audit",
  "1-Projects/Northwind-Audit/Findings",
  "1-Projects/Initech-Migration",
  "2-Areas/Finance",
  "2-Areas/Finance/Invoices",
  "2-Areas/Finance/Tax-2026",
  "2-Areas/HR",
  "2-Areas/Health",
  "2-Areas/Home",
  "3-Resources/Vendor-Research",
  "3-Resources/Templates",
  "3-Resources/Training",
  "3-Resources/Manuals",
  "4-Archives/Globex-Completed",
  "4-Archives/Umbrella-2025",
];
let dests = [...destinations];
const parents = ["1-Projects", "2-Areas", "3-Resources", "4-Archives", "1-Projects/Acme-Rollout", "2-Areas/Finance"];

function item(
  name: string,
  size: number,
  minutesAgo: number,
  cands: [string, InboxItem["candidates"][number]["source"], number | null, string, boolean?][],
  extra: Partial<InboxItem> = {},
): InboxItem {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return {
    path: `${DL}\\${name}`,
    name,
    size,
    mtime: Date.now() / 1000 - minutesAgo * 60,
    added: ago(minutesAgo),
    ext,
    modified: ago(minutesAgo + 3),
    candidates: cands.map(([folder, source, score, why, agrees], i) => ({
      folder,
      source,
      score,
      why,
      exists: folder !== "1-Projects/Hooli-Pilot",
      model_agrees: agrees,
      rank: i + 1,
    })),
    ready: true,
    duplicate: null,
    confidence: cands[0]?.[2] ?? null,
    cleanup: null,
    auto: { auto: false, why: "" },
    ...extra,
  };
}

function seedInbox(): InboxItem[] {
  const list: InboxItem[] = [
    item("Acme_SOW_v3_signed.pdf", 2.4 * MB, 12, [
      ["1-Projects/Acme-Rollout/Contracts", "similar", 0.97, "9 of your filed SOWs live here", true],
      ["1-Projects/Acme-Rollout", "name", 0.71, "File name contains 'Acme'"],
      ["2-Areas/Finance", "model", null, "Model: looks like a contract with payment terms"],
    ], { auto: { auto: true, folder: "1-Projects/Acme-Rollout/Contracts", why: "Proven folder", soon: true } }),
    item("Invoice-NW-2026-0412.pdf", 184_000, 38, [
      ["2-Areas/Finance/Invoices", "rule", null, "Rule 'Invoices' matched name pattern"],
      ["1-Projects/Northwind-Audit", "similar", 0.62, "Similar to 3 audit documents"],
    ], { auto: { auto: true, folder: "2-Areas/Finance/Invoices", why: "Rule-based, proven" } }),
    item("Northwind posture audit - draft findings.docx", 812_000, 64, [
      ["1-Projects/Northwind-Audit/Findings", "similar", 0.88, "Close to 14 findings documents", true],
      ["1-Projects/Northwind-Audit", "name", 0.74, "Name contains 'Northwind'"],
      ["3-Resources/Templates", "similar", 0.41, "Shares headings with a template"],
      ["1-Projects/Hooli-Pilot", "model", null, "Model's guess based on content"],
    ]),
    item("vendor-comparison-Q3.xlsx", 96_000, 140, [
      ["3-Resources/Vendor-Research", "similar", 0.58, "Like 4 spreadsheets you filed", false],
      ["2-Areas/Finance", "model", null, "Model: budget-like table"],
    ]),
    item("scan_0093.pdf", 5.1 * MB, 220, [
      ["2-Areas/Home", "model", null, "Model's guess; text was thin"],
      ["2-Areas/Health", "similar", 0.33, "Weak match to 1 document"],
    ], { cleanup: { level: "review", category: "old_unopened", reason: "Not opened" } }),
    item("Globex_closing_report_final.pdf", 1.2 * MB, 300, [
      ["4-Archives/Globex-Completed", "name", 0.96, "Name matches folder 'Globex'", true],
    ], {
      duplicate: { folder: "4-Archives/Globex-Completed", path: `${PARA}\\4-Archives\\Globex-Completed\\Globex_closing_report_final.pdf`, similarity: 1 },
      cleanup: { level: "safe", category: "duplicate_of_filed", reason: "Identical copy already filed" },
    }),
    item("Initech_cutover_plan.pptx", 7.8 * MB, 3, [
      ["1-Projects/Initech-Migration", "name", 0.8, "Name contains 'Initech'"],
    ], { ready: false }),
    item("payslip_september.pdf", 88_000, 900, [
      ["2-Areas/HR", "rule", null, "Rule 'Payslips'"],
      ["2-Areas/Finance", "similar", 0.52, "Similar to tax documents"],
    ]),
    item("setup-chart-tool.crdownload", 41 * MB, 1500, [
      ["3-Resources/Manuals", "model", null, "Model unsure"],
    ], { cleanup: { level: "safe", category: "partial_download", reason: "Download never finished" } }),
  ];
  for (let i = 1; i <= 23; i++) {
    list.push(
      item(`meeting-notes-${String(i).padStart(2, "0")}.md`, 4000 + i * 900, 1600 + i * 60, [
        [i % 2 ? "1-Projects/Acme-Rollout" : "1-Projects/Northwind-Audit", "similar", 0.5 + (i % 5) * 0.1, "Like your notes", i % 3 === 0],
        ["3-Resources/Templates", "model", null, "Model's guess"],
      ]),
    );
  }
  return list;
}

let inbox = seedInbox();
let dismissed: InboxItem[] = [];
let journalSeq = 200;
const journalItems = new Map<number, InboxItem>();
let journal: JournalRow[] = [
  jr(198, "Acme_kickoff_deck.pptx", "1-Projects/Acme-Rollout", "manual", "moved", 90),
  jr(197, "W-2_2025.pdf", "2-Areas/Finance/Tax-2026", "auto:rule", "moved", 300),
  jr(196, "router_manual.pdf", "3-Resources/Manuals", "manual", "undone", 1400, "Undone by you"),
  jr(195, "Umbrella_timesheet.xlsx", "4-Archives/Umbrella-2025", "manual", "interrupted", 3000, "Agent stopped mid-move; source still present"),
  jr(194, "NW_scope.docx", "1-Projects/Northwind-Audit", "auto:similar", "moved", 4200),
];
function jr(id: number, name: string, folder: string, source: string, status: JournalRow["status"], minAgo: number, note: string | null = null): JournalRow {
  return {
    id, ts: ago(minAgo), src: `${DL}\\${name}`, dest: `${PARA}\\${folder.replace(/\//g, "\\")}\\${name}`,
    size: 200_000, folder, source, rank: 1, top_folder: folder, top_score: 0.9, top_source: "similar",
    status, undone_ts: status === "undone" ? ago(minAgo - 5) : null, note,
  };
}

const settingsRaw: Raw = {
  inbox_folders: [DL],
  para_root: PARA,
  destination_depth: 3,
  exclude_destinations: ["4-Archives/Umbrella-2025"],
  rules: [
    { name: "Invoices", extensions: ["pdf"], name_regex: "(?i)invoice", destination: "2-Areas/Finance/Invoices" },
    { name: "Payslips", extensions: ["pdf"], name_regex: "(?i)payslip", destination: "2-Areas/HR" },
  ],
  ollama: { model: "qwen3:8b", url: "http://127.0.0.1:11434", think: false, timeout_seconds: 120, startup_wait_seconds: 600 },
  history_examples: 40,
  settle_seconds: 10,
  catch_up_days: 14,
  reconcile_minutes: 30,
  ignore_patterns: ["*.tmp", "desktop.ini"],
  cleanup: { scan_hours: 24, installer_days: 30, driver_days: 60, stale_days: 180, para_duplicates: true },
  search: { enabled: true, model: "nomic-embed-text", extra_folders: [], exclude_globs: ["**/node_modules/**"], min_similarity: 0.35, sweep_minutes: 60 },
  autofile: { enabled: false, min_decisions: 20, min_rate: 0.95, window: 30, min_score: 0.9, delay_minutes: 30 },
  ocr: { enabled: true, max_pdf_pages: 20, min_image_kb: 50 },
  ui: { port: 8765 },
  telemetry_note: "kept untouched",
};
const defaults: Raw = JSON.parse(JSON.stringify(settingsRaw));
let restartNeeded = false;
const restartKeys = ["inbox_folders", "para_root", "ui.port"];

/* ---------- cleanup ---------- */
const cItem = (name: string, size: number, level: CleanupItem["level"], category: string, reason: string, age: number, extra: Partial<CleanupItem> = {}): CleanupItem => ({
  path: `${DL}\\${name}`, name, is_dir: false, folder: "Downloads", size, category, level, reason, related: null, caution: null,
  added: ago(age * 1440), age_days: age, last_opened: null, decision: null, ...extra,
});
let cleanupItems: CleanupItem[] = [
  cItem("Globex_closing_report_final.pdf", 1.2 * MB, "safe", "duplicate_of_filed", "Identical content already filed", 2, { related: "4-Archives/Globex-Completed/Globex_closing_report_final.pdf" }),
  cItem("setup-chart-tool.crdownload", 41 * MB, "safe", "partial_download", "Download never finished", 9),
  cItem("vm-image-ubuntu-24.04.iso", 6.2 * 1024 * MB, "likely", "firmware_or_image", "Large disk image, not opened in 120 days", 120, { caution: "Make sure you have no running VM using it" }),
  cItem("NorthwindSetup-4.2.exe", 88 * MB, "likely", "installer", "Installer older than 30 days", 44, { last_opened: ago(44 * 1440) }),
  cItem("photos_2025.zip", 1.4 * 1024 * MB, "likely", "archive_extracted", "Contents already extracted next to it", 70, { related: "Downloads/photos_2025/" }),
  cItem("nvidia-driver-560.94.exe", 690 * MB, "likely", "driver_package", "Driver package older than 60 days", 90),
  cItem("report (1).pdf", 310_000, "safe", "duplicate_in_downloads", "Same content as another download", 15, { related: "Downloads/report.pdf" }),
  cItem("old-budget-2023.xlsx", 120_000, "review", "old_unopened", "Not opened for 400 days", 400),
  cItem("tool-portable.exe", 14 * MB, "review", "executable", "A program you may still use", 200, { caution: "Portable programs have no installer" }),
  cItem("router-fw-v2.bin", 22 * MB, "review", "firmware_or_image", "Firmware file", 260),
  cItem("Acme_SOW_v3_signed.pdf", 2.4 * MB, "keep", "old_unopened", "Recent document, likely needed", 0),
];
const cleanupState: { running: boolean; started: string | null; progress: string | null; finished: string | null; step: number } = {
  running: false, started: null, progress: null, finished: ago(180), step: 0,
};
let generated = ago(180);
const deleterState: CleanupResponse["deleter"] & { step: number } = { running: false, progress: null, error: null, result: null, step: 0 };
const history: CleanupHistoryRow[] = [
  { ts: ago(8000), path: `${DL}\\zoom_installer.exe`, size: 12 * MB, category: "installer", mode: "recycle", result: "deleted" },
  { ts: ago(8000), path: `${DL}\\notes (2).txt`, size: 3000, category: "duplicate_in_downloads", mode: "recycle", result: "skipped: changed since scan" },
];
const RECYCLE_MAX = 1024 * MB;

function cleanupSnapshot(): CleanupResponse {
  if (cleanupState.running) {
    cleanupState.step++;
    const steps = ["Listing Downloads…", "Listing organised folders…", "Hashing 112 of 640 files…", "Hashing 418 of 640 files…", "Comparing duplicates…", "Writing report…"];
    cleanupState.progress = steps[Math.min(cleanupState.step, steps.length - 1)] ?? null;
    if (cleanupState.step > steps.length) {
      cleanupState.running = false;
      cleanupState.finished = iso(now());
      cleanupState.progress = null;
      generated = iso(now());
    }
  }
  if (deleterState.running) {
    deleterState.step++;
    deleterState.progress = `Re-checking and deleting… ${deleterState.step} of 3`;
    if (deleterState.step >= 3) finishDelete();
  }
  const by_level: Record<string, { count: number; bytes: number }> = {};
  for (const l of ["safe", "likely", "review", "keep"]) by_level[l] = { count: 0, bytes: 0 };
  for (const i of cleanupItems) {
    by_level[i.level] ??= { count: 0, bytes: 0 };
    by_level[i.level]!.count++;
    by_level[i.level]!.bytes += i.size;
  }
  const agreed = cleanupItems.filter((i) => i.decision === "agree");
  const small = agreed.filter((i) => i.size <= RECYCLE_MAX);
  return {
    runner: { running: cleanupState.running, started: cleanupState.started, progress: cleanupState.progress, error: null, finished: cleanupState.finished },
    report: {
      generated,
      counts: { inbox_files: 640, para_files: 18_422, cloud_only_para: 311, cloud_only_inbox: 2, files_hashed: 1_904, unconfirmed_cloud_groups: 3 },
      by_level,
      items: cleanupItems,
      settings: { installer_days: 30, driver_days: 60, stale_days: 180, para_duplicates: true },
      errors: ["Could not read Downloads\\locked-by-excel.xlsx (in use)"],
      para_duplicates: [
        { size: 2.1 * MB, confirmed: true, paths: ["1-Projects/Acme-Rollout/Brand_Guide.pdf", "3-Resources/Templates/Brand_Guide.pdf"] },
        { size: 540_000, confirmed: false, paths: ["2-Areas/Finance/Tax-2026/receipt.jpg", "2-Areas/Home/receipt.jpg"] },
      ],
    },
    levels: { safe: "Safe to delete", likely: "Probably safe", review: "Review", keep: "Keep / archive" },
    plan: {
      recycle_count: small.length,
      recycle_bytes: small.reduce((a, b) => a + b.size, 0),
      too_big: agreed.filter((i) => i.size > RECYCLE_MAX).map(({ path, name, size }) => ({ path, name, size })),
      limits: { "C:": { known: true, nuke: false, max_bytes: RECYCLE_MAX, drive: "C:" } },
    },
    deleter: { running: deleterState.running, progress: deleterState.progress, error: null, result: deleterState.result },
  };
}

let pendingDelete: { mode: string; paths: string[] } | null = null;
function finishDelete() {
  if (!pendingDelete) return;
  const targets = cleanupItems.filter((i) => pendingDelete!.paths.includes(i.path));
  const skipped = targets.filter((i) => i.category === "duplicate_in_downloads").map(({ path, name, size }) => ({ path, name, size, why: "Changed since the scan" }));
  const deleted = targets.filter((i) => i.category !== "duplicate_in_downloads").map(({ path, name, size }) => ({ path, name, size }));
  cleanupItems = cleanupItems.filter((i) => !deleted.some((d) => d.path === i.path));
  for (const d of deleted) history.unshift({ ts: iso(now()), path: d.path, size: d.size, category: "", mode: pendingDelete.mode, result: "deleted" });
  deleterState.running = false;
  deleterState.progress = null;
  deleterState.result = {
    mode: pendingDelete.mode, finished: iso(now()), deleted, deleted_bytes: deleted.reduce((a, b) => a + b.size, 0), skipped, failed: [],
  };
  pendingDelete = null;
}

/* ---------- search ---------- */
const docs: SearchResult[] = [
  sr("Northwind_Posture_Audit_Findings.docx", "1-Projects/Northwind-Audit/Findings", "Key findings of the posture audit for Northwind Bank: privileged access reviews were incomplete and MFA coverage at 82%.", "ok", 0.91, true, 1),
  sr("PVK-2026-TCS-001_test_plan.pdf", "1-Projects/Acme-Rollout", "Test plan PVK-2026-TCS-001 covers cutover rehearsal, rollback and sign-off steps.", "ok", 0.77, true, 2),
  sr("bank_security_review_scan.pdf", "4-Archives/Globex-Completed", "Security review for the bank, scanned. Network segmentation findings and audit trail gaps.", "ocr", 0.69, false, null),
  sr("Vendor_shortlist.xlsx", "3-Resources/Vendor-Research", "Shortlist of vendors: Contoso, Fabrikam, Initech. Weighted scoring of audit tools.", "ok", 0.48, false, null),
  sr("HR_contract_signed.pdf", "2-Areas/HR", "", "locked", null, true, null),
  sr("Budget_FY26.xlsx", "2-Areas/Finance", "Budget for audit and posture improvements, FY26.", "cloud", null, true, null),
  sr("Scan_receipt_0091.jpg", "Downloads", "", "ocr_empty", 0.31, false, null),
];
function sr(name: string, folder: string, snippet: string, status: string, similarity: number | null, keyword: boolean, part: number | null): SearchResult {
  return {
    path: `${PARA}\\${folder.replace(/\//g, "\\")}\\${name}`, name, folder, source: folder === "Downloads" ? "inbox" : "para",
    ext: name.split(".").pop() ?? "", size: 120_000 + name.length * 9000, status, modified: ago(name.length * 700),
    score: similarity ?? 0.4, similarity, keyword, snippet, part, openable: status !== "cloud",
  };
}
const searchState = { running: false, done: 0, todo: 0, rebuildStep: 0 };

/* ---------- predictions / stats ---------- */
const outcomes: Prediction["outcome"][] = ["match", "match", "match", "miss", "pending", "match", "unsure", "match", "error", "match"];
const predictions: Prediction[] = Array.from({ length: 60 }, (_, i) => {
  const o = outcomes[i % outcomes.length]!;
  const pred = destinations[i % destinations.length]!;
  return {
    id: 1000 - i, ts: ago(i * 95), path: `${DL}\\doc_${i}.pdf`, filename: ["Acme_status_", "NW_findings_", "invoice_", "Globex_", "notes_"][i % 5]! + i + ".pdf",
    size: 50_000 + i * 3000, method: i % 4 === 0 ? "rule:Invoices" : "model", predicted: o === "error" ? null : pred,
    confidence: o === "unsure" ? "low" : ["high", "medium", "high"][i % 3]!, reason: "Mentions project code and a matching client name in the first page.",
    actual: o === "match" ? pred : o === "miss" ? destinations[(i + 3) % destinations.length]! : null, actual_ts: o === "match" || o === "miss" ? ago(i * 95 - 30) : null, outcome: o,
  };
});

const logLines = (): string[] => {
  const out: string[] = [];
  const msgs = [
    ["INFO", "watcher: new file Acme_SOW_v3_signed.pdf"],
    ["INFO", "index: extracted 12 pages from Acme_SOW_v3_signed.pdf"],
    ["INFO", "predict: qwen3:8b -> 1-Projects/Acme-Rollout/Contracts (high)"],
    ["WARNING", "ocr: scan_0093.pdf has little text, OCR used"],
    ["INFO", "cleanup: scan finished, 11 recommendations"],
    ["ERROR", "index: locked-by-excel.xlsx is in use, will retry"],
    ["INFO", "autofile: check complete, 0 eligible"],
  ];
  for (let i = 0; i < 80; i++) {
    const [lvl, m] = msgs[i % msgs.length]!;
    out.push(`${ago(80 - i).replace("T", " ")} ${lvl!.padEnd(7)} ${m}`);
  }
  return out;
};

/* ---------- router ---------- */
type Handler = (q: URLSearchParams, body: Raw) => unknown;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const get: Record<string, Handler> = {
  "/api/status": (): Status => ({
    mode: "demo", started: ago(600), ollama: !demo.modelMissing, watching: !demo.problem, last_prediction: ago(12),
    restart_needed: restartNeeded, problem: demo.problem ? "Downloads folder is on a drive that is not connected (E:)." : null,
    model_missing: demo.modelMissing, installed_models: ["qwen3:8b", "llama3.2:3b", "nomic-embed-text"], supervised: true,
    model: settingsRaw.ollama.model, inbox: settingsRaw.inbox_folders, para_root: settingsRaw.para_root, log_file: "C:\\ShadowFiler\\agent.log",
  }),
  "/api/inbox": (q) => {
    const offset = Number(q.get("offset") ?? 0), limit = Number(q.get("limit") ?? 25);
    const all = demo.emptyInbox ? [] : inbox;
    return { items: all.slice(offset, offset + limit), total: all.length, offset, examples: { examples: 1_284, folders: 41 }, parents, destinations: dests };
  },
  "/api/moves": () => ({
    journal,
    feedback: {
      moves: 212, top_accepted: 181, rate: 0.854, auto_moves: 19,
      per_folder: [
        { folder: "1-Projects/Acme-Rollout", n: 48, accepted: 44 },
        { folder: "2-Areas/Finance/Invoices", n: 37, accepted: 37 },
        { folder: "1-Projects/Northwind-Audit", n: 29, accepted: 23 },
        { folder: "3-Resources/Vendor-Research", n: 14, accepted: 9 },
      ],
    },
  }),
  "/api/autofile": (): AutofileResponse => {
    const a = settingsRaw.autofile;
    return {
      settings: { enabled: a.enabled, min_decisions: a.min_decisions, min_rate: a.min_rate, window: a.window, min_score: a.min_score, delay_minutes: a.delay_minutes },
      summary: { last24h: 4, undone: 1, last_run: ago(6), last_moved: ago(70), last_error: null },
      folders: [
        { folder: "2-Areas/Finance/Invoices", source: "rule", decisions: 37, agreed: 37, rate: 1, proven: true, needed: 0, revoked: null },
        { folder: "1-Projects/Acme-Rollout/Contracts", source: "similar", decisions: 24, agreed: 23, rate: 0.958, proven: true, needed: 0, revoked: null },
        { folder: "1-Projects/Northwind-Audit", source: "name", decisions: 12, agreed: 12, rate: 1, proven: false, needed: 8, revoked: null },
        { folder: "3-Resources/Vendor-Research", source: "similar", decisions: 14, agreed: 9, rate: 0.64, proven: false, needed: 0, revoked: null },
        { folder: "2-Areas/HR", source: "rule", decisions: 3, agreed: 3, rate: 1, proven: false, needed: 17, revoked: ago(2000) },
      ],
    };
  },
  "/api/settings": () => ({
    raw: JSON.parse(JSON.stringify(settingsRaw)), models: ["qwen3:8b", "llama3.2:3b", "mistral:7b", "nomic-embed-text", "bge-m3"],
    destinations: dests, defaults, restart_needed: restartNeeded, restart_keys: restartKeys, config_path: "C:\\ShadowFiler\\config.yaml",
  }),
  "/api/config": () => ({ text: toYaml(settingsRaw) }),
  "/api/cleanup": () => cleanupSnapshot(),
  "/api/cleanup/history": () => ({ rows: history }),
  "/api/search": (q) => {
    const query = (q.get("q") ?? "").toLowerCase().trim();
    const scope = q.get("scope") ?? "all";
    const types = q.get("types") ?? "any";
    if (!query) return { results: [], semantic: true, semantic_error: null, ms: 0, searched_files: 18_422 };
    const words = query.split(/\s+/);
    let res = docs.filter((d) => d.similarity !== null || words.some((w) => (d.name + d.snippet).toLowerCase().includes(w)));
    if (scope === "para") res = res.filter((d) => d.source === "para");
    if (scope === "inbox") res = res.filter((d) => d.source === "inbox");
    const typeMap: Record<string, string[]> = { pdf: ["pdf"], sheets: ["xlsx", "csv"], slides: ["pptx"], docs: ["docx", "pdf", "md", "txt"] };
    if (types !== "any") res = res.filter((d) => typeMap[types]?.includes(d.ext));
    res = res.map((d) => ({ ...d, keyword: words.some((w) => (d.name + d.snippet).toLowerCase().includes(w)) }));
    const semantic = !query.includes("offline");
    return { results: semantic ? res : res.filter((r) => r.keyword).map((r) => ({ ...r, similarity: null })), semantic, semantic_error: semantic ? null : "embedding model not loaded", ms: 40 + query.length * 3, searched_files: 18_422 };
  },
  "/api/search/status": (): SearchStatus => {
    if (searchState.running) {
      searchState.done = Math.min(searchState.todo, searchState.done + 2300);
      if (searchState.done >= searchState.todo) searchState.running = false;
    }
    return {
      running: searchState.running, phase: searchState.running ? "Extracting text" : null, done: searchState.done, todo: searchState.todo,
      current: searchState.running ? "D:\\PARA\\1-Projects\\Acme-Rollout\\Kickoff.pptx" : null, last_sweep: ago(14),
      roots: [{ path: PARA, exists: true }, { path: DL, exists: true }, { path: "E:\\Shared", exists: false }],
      by_status: { ok: 16_904, ocr: 611, name_only: 402, locked: 18, no_text: 77, cloud: 311, error: 4 },
      model: settingsRaw.search.model, model_ok: true, ocr: { enabled: true, available: true, message: "Tesseract 5.3 ready" },
      fts: true, db_bytes: 412 * MB, last_error: null,
      errors: [{ path: "D:\\PARA\\2-Areas\\Finance\\broken.xlsx", error: "File is corrupt" }],
    };
  },
  "/api/stats": (): Stats => ({
    depth: 3, total: 1_412, period: [ago(60 * 24 * 120), ago(12)], filed: 1_210, unfiled: 140, unsure: 45, errors: 17,
    overall: { label: "All", n: 1_210, exact: 0.83, top: 0.94 },
    by_method: [
      { label: "rule", n: 302, exact: 0.99, top: 1 },
      { label: "model", n: 908, exact: 0.78, top: 0.92 },
    ],
    by_conf: [
      { label: "high", n: 640, exact: 0.92, top: 0.98 },
      { label: "medium", n: 410, exact: 0.74, top: 0.9 },
      { label: "low", n: 160, exact: 0.48, top: 0.8 },
    ],
    misses: [
      { predicted: "2-Areas/Finance", actual: "2-Areas/Finance/Invoices", n: 22 },
      { predicted: "1-Projects/Acme-Rollout", actual: "1-Projects/Acme-Rollout/Contracts", n: 15 },
      { predicted: "3-Resources/Templates", actual: "3-Resources/Training", n: 7 },
    ],
  }),
  "/api/predictions": (q) => {
    const view = q.get("view") ?? "all", s = (q.get("q") ?? "").toLowerCase();
    return { rows: predictions.filter((p) => (view === "all" || p.outcome === view) && (!s || p.filename.toLowerCase().includes(s) || (p.predicted ?? "").toLowerCase().includes(s))) };
  },
  "/api/log": () => ({ lines: logLines() }),
  "/api/fs/check": (q) => {
    const p = q.get("path") ?? "";
    const expanded = p.replace("%USERPROFILE%", "C:\\Users\\alex").replace(/^~/, "C:\\Users\\alex");
    return { input: p, expanded, exists: /^[CD]:\\/i.test(expanded) && !/missing|nope/i.test(expanded) };
  },
  "/api/fs/dirs": (q) => {
    const p = q.get("path") ?? "";
    if (!p) return { path: "", parent: null, dirs: [{ name: "C:\\", path: "C:\\" }, { name: "D:\\", path: "D:\\" }], quick: [{ name: "Downloads", path: DL }, { name: "PARA", path: PARA }, { name: "Documents", path: "C:\\Users\\alex\\Documents" }] };
    const names = p === "D:\\" ? ["PARA", "Backups"] : p.endsWith("PARA") ? ["1-Projects", "2-Areas", "3-Resources", "4-Archives"] : p === "C:\\" ? ["Users", "Program Files"] : ["Projects", "Archive", "Shared"];
    const parent = p.length <= 3 ? "" : p.replace(/\\[^\\]+\\?$/, "") || "";
    return { path: p, parent: parent.length === 2 ? parent + "\\" : parent, dirs: names.map((n) => ({ name: n, path: `${p.replace(/\\$/, "")}\\${n}` })) };
  },
  "/api/system": (): SystemInfo => ({
    os: "Windows 11 Pro 24H2", computer: "ALEX-WORKSTATION", cpu: "AMD Ryzen 7 7840HS (16 threads)",
    memory: { installed: 32 * 1024 * MB, free: 11.4 * 1024 * MB },
    gpus: [{ name: "NVIDIA GeForce RTX 4060 Laptop", vram_used: 5.1 * 1024 * MB, vram_total: 8 * 1024 * MB, temp: 61, util: 24 }],
    disks: [
      { name: "System", mount: "C:", total: 1000 * 1024 * MB, free: 72 * 1024 * MB },
      { name: "Data", mount: "D:", total: 2000 * 1024 * MB, free: 940 * 1024 * MB },
    ],
    ollama: { reachable: !demo.modelMissing, version: "0.6.2", loaded: ["qwen3:8b"] },
    notes: [
      { level: "warn", text: "Drive C: has less than 10% free space. The Recycle Bin limit may be lower than usual." },
      { level: "info", text: "The model fits in GPU memory; suggestions take about 2 seconds each." },
    ],
  }),
};

const post: Record<string, Handler> = {
  "/api/inbox/file": (_q, b) => {
    const it = inbox.find((i) => i.path === b.path);
    if (!it) return { ok: false, message: "That file is no longer in Downloads." };
    inbox = inbox.filter((i) => i !== it);
    const id = ++journalSeq;
    journalItems.set(id, it);
    const row = jr(id, it.name, b.folder, "manual", "moved", 0);
    journal = [row, ...journal];
    return { ok: true, id, dest: row.dest, renamed: false };
  },
  "/api/moves/undo": (_q, b) => {
    const row = journal.find((j) => j.id === b.id);
    if (!row || row.status !== "moved") return { ok: false, message: "This move can't be undone any more." };
    row.status = "undone";
    row.undone_ts = iso(now());
    row.note = "Undone by you";
    const it = journalItems.get(row.id);
    if (it) inbox = [it, ...inbox];
    return { ok: true, restored: row.src };
  },
  "/api/inbox/dismiss": (_q, b) => {
    const it = inbox.find((i) => i.path === b.path);
    if (it) { inbox = inbox.filter((i) => i !== it); dismissed.push(it); }
    return { ok: true };
  },
  "/api/inbox/mkdir": (_q, b) => {
    const name = String(b.name ?? "").trim();
    if (!name || /[<>:"/\\|?*]/.test(name)) return { ok: false, message: "Folder names can't contain < > : \" / \\ | ? *" };
    const folder = `${b.parent}/${name}`;
    if (dests.includes(folder)) return { ok: false, message: "That folder already exists." };
    dests = [...dests, folder].sort();
    return { ok: true, folder };
  },
  "/api/cleanup/reveal": () => ({ ok: true }),
  "/api/search/open": () => ({ ok: true }),
  "/api/search/reveal": () => ({ ok: true }),
  "/api/search/rebuild": () => { searchState.running = true; searchState.done = 0; searchState.todo = 18_422; return { ok: true, message: "Rebuilding the index." }; },
  "/api/cleanup/scan": () => {
    if (cleanupState.running) return { ok: false, message: "A scan is already running." };
    Object.assign(cleanupState, { running: true, started: iso(now()), step: 0, progress: "Starting…" });
    return { ok: true };
  },
  "/api/cleanup/decision": (_q, b) => {
    const it = cleanupItems.find((i) => i.path === b.path);
    if (it) it.decision = b.decision ?? null;
    return { ok: true };
  },
  "/api/cleanup/delete": (_q, b) => {
    const agreed = cleanupItems.filter((i) => i.decision === "agree");
    if (b.mode === "permanent") {
      if (b.confirm !== "DELETE PERMANENTLY") return { ok: false, message: "Confirmation text missing." };
      pendingDelete = { mode: "permanent", paths: b.paths };
    } else {
      pendingDelete = { mode: "recycle", paths: agreed.filter((i) => i.size <= RECYCLE_MAX).map((i) => i.path) };
    }
    Object.assign(deleterState, { running: true, step: 0, progress: "Starting…", result: null });
    return { ok: true };
  },
  "/api/cleanup/recyclebin": () => ({ ok: true }),
  "/api/cleanup/selftest": () => ({ ok: true, message: "Recycle Bin works on C: and D: (test file sent and restored)." }),
  "/api/ocr/selftest": () => ({ ok: true, message: "OCR works: read 'Shadow Filer test 123' from a generated image in 0.8 s." }),
  "/api/settings": (_q, b) => {
    const before = JSON.stringify([settingsRaw.inbox_folders, settingsRaw.para_root, settingsRaw.ui?.port]);
    for (const k of Object.keys(settingsRaw)) delete settingsRaw[k];
    Object.assign(settingsRaw, JSON.parse(JSON.stringify(b.raw)));
    const after = JSON.stringify([settingsRaw.inbox_folders, settingsRaw.para_root, settingsRaw.ui?.port]);
    if (before !== after) restartNeeded = true;
    return { ok: true, message: "Settings saved to config.yaml.", restart_needed: restartNeeded };
  },
  "/api/config": (_q, b) => {
    if (!String(b.text).includes(":")) return { ok: false, message: "That doesn't look like valid YAML." };
    return { ok: true, message: "config.yaml saved (demo: the form values were not changed).", restart_needed: restartNeeded };
  },
  "/api/restart": () => {
    restartNeeded = false;
    demo.unreachable = true;
    setTimeout(() => (demo.unreachable = false), 4000);
    return { ok: true, message: "Restarting…" };
  },
};

function toYaml(v: unknown, indent = 0): string {
  const pad = " ".repeat(indent);
  if (Array.isArray(v)) {
    if (!v.length) return " []";
    return "\n" + v.map((x) => (typeof x === "object" && x ? `${pad}- ${toYaml(x, indent + 2).trimStart()}` : `${pad}- ${JSON.stringify(x)}`)).join("\n");
  }
  if (v && typeof v === "object") {
    return (indent ? "\n" : "") + Object.entries(v).map(([k, x]) => (typeof x === "object" && x !== null ? `${pad}${k}:${toYaml(x, indent + 2)}` : `${pad}${k}: ${JSON.stringify(x)}`)).join("\n");
  }
  return " " + JSON.stringify(v);
}

export class MockHttpError extends Error {
  constructor(public status: number) { super(`HTTP ${status}`); }
}

export async function mockFetch(method: "GET" | "POST", url: string, body?: Raw): Promise<unknown> {
  await sleep(method === "GET" ? 120 + Math.random() * 180 : 250 + Math.random() * 250);
  if (demo.unreachable) throw new TypeError("Failed to fetch");
  const u = new URL(url, "http://mock.local");
  const h = (method === "GET" ? get : post)[u.pathname];
  if (!h) throw new MockHttpError(404);
  return JSON.parse(JSON.stringify(h(u.searchParams, body ?? {})));
}
