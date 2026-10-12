/* Entirely fictional demo data with in-memory mutations, used when no agent token is present. */
import type { SecApp, SecCve, SecService, SecurityResponse, AppChange, InstalledApp, LibraryApplications, JournalDay, JournalResponse, WatchDate, WatchSensitive, LibraryChain, LibraryInstaller, LibraryPictureGroup, LibraryProduct, LibraryPicture,
  AutofileResponse, DashboardResponse,
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
      ["1-Projects/Acme-Rollout/Contracts", "origin", null, "6 of your 6 files from portal.acme.example are filed here"],
      ["1-Projects/Acme-Rollout/Contracts", "similar", 0.97, "9 of your filed SOWs live here", true],
      ["1-Projects/Acme-Rollout", "name", 0.71, "File name contains 'Acme'"],
      ["2-Areas/Finance", "model", null, "Model: looks like a contract with payment terms"],
    ], { auto: { auto: true, folder: "1-Projects/Acme-Rollout/Contracts", why: "Proven folder", soon: true }, origin: { host: "portal.acme.example", referrer: "portal.acme.example" } }),
    item("Invoice-NW-2026-0412.pdf", 184_000, 38, [
      ["2-Areas/Finance/Invoices", "rule", null, "Rule 'Invoices' matched name pattern"],
      ["1-Projects/Northwind-Audit", "similar", 0.62, "Similar to 3 audit documents"],
    ], { auto: { auto: true, folder: "2-Areas/Finance/Invoices", why: "Rule-based, proven" }, origin: { host: "mail.example.com", referrer: "mail.example.com" } }),
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
  watch: { enabled: true, soon_days: 30, keep_expired_days: 60 },
  library: { enabled: true, scan_hours: 24, image_distance: 8, check_signatures: true, applications: true, check_updates: true, update_hours: 24, vulnerabilities: true, cve_hours: 24, remediate: true },
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


/* --- document watch --- */
const dayIso = (days: number) => iso(new Date(Date.now() + days * 86400000)).slice(0, 10);
const P = "C:\\Users\\alex\\Documents\\PARA\\", WDL = "C:\\Users\\alex\\Downloads\\";
const wd = (name: string, folder: string, source: "para" | "inbox" | "extra", days: number, kind: WatchDate["kind"], context: string, copies: string[] = []): WatchDate => ({
  path: (source === "inbox" ? WDL : P + folder.replace(/\//g, "\\") + "\\") + name, name, folder, source, size: 80_000 + name.length * 9_311,
  modified: ago(60 * 24 * (40 + name.length)), date: dayIso(days), kind, days,
  status: days < 0 ? "passed" : days <= 30 ? "soon" : "later", context, key: `${name}|${kind}|${days}`, copies,
});
const watchDates: WatchDate[] = [
  wd("Northwind-Fleet-Insurance-2025.pdf", "2-Areas/Insurance", "para", 9, "expires", "Policy period: 21 Oct 2025 to 20 Oct 2026. This policy expires on the date shown unless renewed.", [P + "4-Archives\\Old-Policies\\Northwind-Fleet-Insurance-2025.pdf"]),
  wd("Globex-Quote-Q-4471.pdf", "3-Resources/Vendor-Research", "para", 0, "valid until", "This quotation is valid until the date below. Prices exclude GST."),
  wd("Invoice-INV-20931.pdf", "Downloads", "inbox", 4, "due", "Payment due date: please remit within 30 days of the invoice date."),
  wd("Acme-MSA-Signed.pdf", "1-Projects/Acme-Rollout", "para", 74, "ends", "The initial term of this Agreement ends on the date stated in Schedule A."),
  wd("Initech-Support-Renewal.docx", "2-Areas/Subscriptions", "para", 133, "renewal", "Annual support renewal date. Auto-renews unless cancelled 30 days before."),
  wd("Passport-Scan-Alex.pdf", "2-Areas/Identity", "para", 412, "expires", "Date of expiry"),
  wd("Umbrella-NDA.pdf", "4-Archives/Globex-Completed", "para", -12, "ends", "This NDA ends two years after the effective date."),
  wd("Gym-Membership.pdf", "2-Areas/Health", "para", -41, "valid until", "Membership valid until"),
];
const watchSensitive: WatchSensitive[] = [
  { path: WDL + "KYC-Form-Filled.pdf", name: "KYC-Form-Filled.pdf", folder: "Downloads", source: "inbox", size: 412_000, modified: ago(60 * 26), level: "high", key: "",
    found: [{ kind: "pan", label: "PAN", count: 1 }, { kind: "aadhaar", label: "Aadhaar number", count: 2 }] },
  { path: WDL + "statement_sep.pdf", name: "statement_sep.pdf", folder: "Downloads", source: "inbox", size: 238_000, modified: ago(60 * 70), level: "medium", key: "",
    found: [{ kind: "bank", label: "Bank account details", count: 1 }] },
  { path: WDL + "deploy_key.txt", name: "deploy_key.txt", folder: "Downloads", source: "inbox", size: 3_400, modified: ago(60 * 24 * 9), level: "high", key: "",
    found: [{ kind: "key", label: "Private key", count: 1 }] },
];
const watchHidden = new Set<string>();
const watchId = (path: string, kind: string, key: string) => `${kind}|${path}|${key}`;
let watchScanned = ago(95);

/* --- library --- */
const GB = 1024 * MB;
const lf = (src: "inbox" | "para", folder: string, name: string) => ({ path: src === "inbox" ? `${DL}\\${name}` : `${PARA}\\${folder.replace(/\//g, "\\")}\\${name}`, name, source: src, folder: src === "inbox" ? "Downloads" : folder });
const libProducts: LibraryProduct[] = [
  { key: "fortigate-100f", product: "FortiGate 100F", versions: ["7.6.2", "7.4.8"], size: 2 * 98 * MB, in_downloads: 2 * 98 * MB, items: [
    { ...lf("inbox", "", "FGT_100F-v7.6.2-build3462-FORTINET.out"), is_dir: false, size: 98 * MB, files: 0, modified: ago(4 * 1440), version: "7.6.2", build: "3462" },
    { ...lf("inbox", "", "FGT_100F-v7.4.8-build2795-FORTINET.out"), is_dir: false, size: 98 * MB, files: 0, modified: ago(60 * 1440), version: "7.4.8", build: "2795" },
  ] },
  { key: "northwind-nac", product: "Northwind NAC", versions: ["9.2.1", "9.1.0"], size: 3.1 * GB, in_downloads: 1.4 * GB, items: [
    { ...lf("inbox", "", "northwind-nac-9.2.1"), is_dir: true, size: 1.4 * GB, files: 7, modified: ago(10 * 1440), version: "9.2.1", build: null },
    { ...lf("para", "3-Resources/Vendor-Research", "northwind-nac-9.1.0.iso"), is_dir: false, size: 1.7 * GB, files: 0, modified: ago(120 * 1440), version: "9.1.0", build: null },
  ] },
  { key: "ubuntu", product: "ubuntu", versions: ["26.04"], size: 5.8 * GB, in_downloads: 0, items: [
    { ...lf("para", "3-Resources/Images", "ubuntu-26.04-desktop-amd64.iso"), is_dir: false, size: 5.8 * GB, files: 0, modified: ago(170 * 1440), version: "26.04", build: null },
  ] },
  { key: "lab-vm", product: "Lab VM", versions: [], size: 12.4 * GB, in_downloads: 0, items: [
    { ...lf("para", "1-Projects/Acme-Rollout/lab", "lab-vm.vhdx"), is_dir: false, size: 12.4 * GB, files: 0, modified: ago(30 * 1440), version: null, build: null },
  ] },
];
const libChains: LibraryChain[] = [
  { key: "acme-rollout-proposal", title: "acme rollout proposal", ext: ".docx", kind: "versions", filed_is_older: true, members: [
    { ...lf("inbox", "", "Acme rollout proposal v3.docx"), size: 412_000, modified: ago(2 * 1440), label: "v3", newest: true },
    { ...lf("inbox", "", "Acme rollout proposal v2.docx"), size: 398_000, modified: ago(9 * 1440), label: "v2", newest: false },
    { ...lf("para", "1-Projects/Acme-Rollout", "Acme rollout proposal v1.docx"), size: 351_000, modified: ago(30 * 1440), label: "v1", newest: false },
  ] },
  { key: "northwind-quote", title: "northwind quote", ext: ".pdf", kind: "versions", filed_is_older: false, members: [
    { ...lf("para", "2-Areas/Finance", "Northwind quote (final).pdf"), size: 220_000, modified: ago(12 * 1440), label: "final", newest: true },
    { ...lf("para", "2-Areas/Finance", "Northwind quote (draft).pdf"), size: 205_000, modified: ago(20 * 1440), label: "draft", newest: false },
  ] },
  { key: "contoso-network-diagram", title: "contoso network diagram", ext: ".vsdx", kind: "versions", filed_is_older: false, members: [
    { ...lf("para", "1-Projects/Acme-Rollout", "Contoso network diagram 2026-09-30.vsdx"), size: 1.1 * MB, modified: ago(11 * 1440), label: "2026-09-30", newest: true },
    { ...lf("para", "1-Projects/Acme-Rollout", "Contoso network diagram 2026-08-14.vsdx"), size: 0.9 * MB, modified: ago(58 * 1440), label: "2026-08-14", newest: false },
  ] },
  { key: "statement", title: "statement", ext: ".pdf", kind: "same-name", filed_is_older: false, members: [
    { ...lf("inbox", "", "statement.pdf"), size: 88_000, modified: ago(3 * 1440), label: "", newest: true },
    { ...lf("para", "2-Areas/Finance", "statement.pdf"), size: 91_000, modified: ago(40 * 1440), label: "", newest: false },
  ] },
  { key: "invoice", title: "invoice", ext: ".pdf", kind: "same-name", filed_is_older: false, members: [
    { ...lf("inbox", "", "invoice.pdf"), size: 64_000, modified: ago(6 * 1440), label: "", newest: true },
    { ...lf("para", "4-Archives/Globex-Completed", "invoice.pdf"), size: 70_000, modified: ago(200 * 1440), label: "", newest: false },
  ] },
];
const pic = (src: "inbox" | "para", folder: string, name: string, size: number, w: number, h: number, days: number): LibraryPicture => ({ ...lf(src, folder, name), size, w, h, modified: ago(days * 1440) });
const libPictures: LibraryPictureGroup[] = [
  { key: "team-photo", identical: false, members: [pic("para", "2-Areas/Team", "team-photo.jpg", 4.2 * MB, 4032, 3024, 50), pic("inbox", "", "team-photo-small.jpg", 0.6 * MB, 1600, 1200, 5)] },
  { key: "acme-logo", identical: true, members: [pic("inbox", "", "acme-logo.png", 48_000, 800, 400, 7), pic("para", "1-Projects/Acme-Rollout/brand", "acme-logo.png", 48_000, 800, 400, 90)] },
  { key: "whiteboard", identical: true, members: [pic("inbox", "", "IMG_2041.jpg", 3.1 * MB, 4000, 3000, 1), pic("inbox", "", "IMG_2041 (1).jpg", 3.1 * MB, 4000, 3000, 1)] },
  { key: "office-floorplan", identical: false, members: [pic("para", "3-Resources/Office", "floorplan.png", 2.2 * MB, 2400, 1800, 120), pic("inbox", "", "floorplan-edited.jpg", 0.9 * MB, 1920, 1440, 8)] },
];
const libInstallers: LibraryInstaller[] = [
  { ...lf("inbox", "", "ContosoSync-Setup-4.2.exe"), size: 84 * MB, modified: ago(3 * 1440), level: "signed", text: "Signed by Contoso Software Ltd and the signature is valid.", status: "Valid", publisher: "Contoso Software Ltd", expires: "2028-03-01", host: "downloads.contoso.example" },
  { ...lf("inbox", "", "kettle-archive-2301-x64.exe"), size: 1.5 * MB, modified: ago(6 * 1440), level: "signed", text: "Signed by Kettle Software and the signature is valid.", status: "Valid", publisher: "Kettle Software", expires: "2027-11-30", host: "downloads.kettle.example", product: "Kettle Archive", version: "23.01", installed_name: "Kettle Archive 24.08 (x64)", installed_version: "24.08", file_is: "older" },
  { ...lf("inbox", "", "chart-tool-portable.exe"), size: 12 * MB, modified: ago(15 * 1440), level: "unsigned", text: "Not signed, so Windows cannot say who made it.", status: "NotSigned", publisher: "", expires: "", host: "files.example.net" },
  { ...lf("para", "3-Resources/Tools", "northwind-agent-installer.msi"), size: 33 * MB, modified: ago(80 * 1440), level: "tampered", text: "The file was changed after it was signed.", status: "HashMismatch", publisher: "Northwind Networks", expires: "2027-06-30", host: null },
  { ...lf("inbox", "", "driver-pack.zip"), size: 210 * MB, modified: ago(22 * 1440), level: "unknown", text: "Could not check this file.", status: "UnknownError", publisher: "", expires: "", host: null },
];
const app = (name: string, version: string, publisher: string, kind: "desktop" | "packaged", scope: "machine" | "user", arch: string, installed: string, date_is: "installed" | "changed", mb: number | null, from_store = false): InstalledApp => {
  const key = name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return { id: key, key, name, version, publisher, kind, from_store, scope, arch, installed, date_is, size: mb == null ? null : Math.round(mb * MB),
    location: kind === "desktop" ? `C:\\Program Files${arch === "32-bit" ? " (x86)" : ""}\\${name.split(" ")[0]}` : null };
};
const libApps: InstalledApp[] = [
  app("Brightpad Notes", "4.12.1", "Brightpad Labs", "desktop", "machine", "64-bit", "2026-08-14", "installed", 212),
  app("Kettle Archive 24.08 (x64)", "24.08", "Kettle Software", "desktop", "machine", "64-bit", "2026-01-10", "installed", 6),
  app("Northwind VPN Client", "7.4.3.4726", "Northwind Networks Inc", "desktop", "machine", "64-bit", "2026-03-26", "installed", 310),
  app("Quillmark PDF Reader", "26.002.21931", "Quillmark", "desktop", "machine", "64-bit", "2026-09-20", "installed", 1480),
  app("Larkspur Browser (x64 en-US)", "158.0", "Larkspur Foundation", "desktop", "machine", "64-bit", "2026-10-09", "changed", null),
  app("Tessellate Containers", "4.94.0", "Tessellate Inc.", "desktop", "machine", "64-bit", "2026-10-09", "changed", 2890),
  app("Pine Runtime 3.12.4 (64-bit)", "3.12.4150.0", "Pine Project", "desktop", "user", "", "2026-02-02", "installed", 142),
  app("Pine Runtime 3.13.0 (64-bit)", "3.13.150.0", "Pine Project", "desktop", "user", "", "2026-09-30", "installed", 150),
  app("Harbor Remote", "9.0.14", "Harbor Software GmbH", "desktop", "machine", "32-bit", "2026-06-26", "changed", null),
  app("Old Label Printer Suite", "", "", "desktop", "machine", "32-bit", "2022-08-05", "changed", null),
  app("Sketch Pad", "2.1.0.0", "Vendor Ltd", "packaged", "user", "64-bit", "2026-07-01", "changed", null, true),
  app("Calculator", "11.2607.0.0", "Contoso Corporation", "packaged", "user", "64-bit", "2026-09-12", "changed", null, true),
  app("Field Notes Sideloaded", "1.0.3.0", "", "packaged", "user", "", "2026-05-20", "changed", null),
].sort((a, b) => a.name.localeCompare(b.name));
const chg = (days: number, event: AppChange["event"], name: string, old_version: string, new_version: string, publisher = "", kind: AppChange["kind"] = "desktop"): AppChange =>
  ({ ts: ago(days * 1440 + 90), event, key: name.toLowerCase().replace(/[^a-z0-9]+/g, "-"), name, publisher, kind, old_version, new_version });
const libChanges = (): AppChange[] => [
  chg(2, "updated", "Larkspur Browser (x64 en-US)", "157.0", "158.0", "Larkspur Foundation"),
  chg(2, "updated", "Tessellate Containers", "4.93.1", "4.94.0", "Tessellate Inc."),
  chg(12, "installed", "Pine Runtime 3.13.0 (64-bit)", "", "3.13.150.0", "Pine Project"),
  chg(20, "removed", "Gridline Spreadsheet Viewer", "2.3", ""),
  chg(22, "updated", "Quillmark PDF Reader", "26.001.20110", "26.002.21931", "Quillmark"),
];
const libAvail: Record<string, [string, string]> = {
  "Brightpad Notes": ["4.13.0", "Brightpad.Notes"],
  "Northwind VPN Client": ["7.4.4.4801", "Northwind.VPNClient"],
  "Pine Runtime 3.12.4 (64-bit)": ["3.12.10", "Pine.Runtime.3.12"],
  "Sketch Pad": ["2.2.0.0", "Vendor.SketchPad"],
};
let libUpdChecked = ago(5 * 60);
function libApplications(): LibraryApplications {
  const ls = settingsRaw.library ?? {};
  const on = !!ls.check_updates;
  const apps = libApps.map((a) => { const u = on ? libAvail[a.name] : undefined; return { ...a, available: u?.[0] ?? null, update_id: u?.[1] ?? null, update: u ? { id: u[1], to: u[0], kind: "latest" as const, latest: u[0], blocked: null } : null }; });
  const sized = libApps.filter((a) => a.size != null);
  return {
    scanned_at: libScanned, apps, changes: libChanges(), changes_days: 90, history_since: ago(60 * 1440),
    desktop_read: true, packaged_read: true,
    counts: { desktop: libApps.filter((a) => a.kind === "desktop").length, packaged: libApps.filter((a) => a.kind === "packaged").length,
      store: libApps.filter((a) => a.from_store).length, no_version: libApps.filter((a) => !a.version).length,
      date_is_a_guess: libApps.filter((a) => a.kind === "desktop" && a.date_is === "changed").length },
    total_bytes: sized.reduce((s, a) => s + (a.size ?? 0), 0), sized: sized.length,
    updates: { enabled: on, hours: Number(ls.update_hours ?? 24), checked_at: libUpdChecked, listed_at: libUpdChecked, ok: true, error: null,
      count: apps.filter((a) => a.available).length,
      unmatched: on ? [{ name: "Gridline Terminal", id: "Gridline.Terminal", version: "1.24.1", available: "1.25.0" }] : [] },
  };
}
const libHidden = new Set<string>();
const libRunner = { running: false, started: null as string | null, progress: null as string | null, error: null as string | null, finished: ago(180) as string | null };
let libScanned: string | null = ago(180);

/* ---------- Journal ---------- */
const WD = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
function jDay(back: number, spec: {
  arrived?: [string, string, number, number, string | null, boolean][]; // hh:mm, name, MB, _, suggested, still
  filed?: [string, string, string, "inbox" | "auto" | "hand", boolean][];
  undone?: [string, string, string][];
  deleted?: [string, string, number][];
  worked?: [string, [string, "added" | "changed"][], number?][];
  apps?: [string, AppChange["event"], string, string, string][];
}): JournalDay {
  const d = new Date(); d.setDate(d.getDate() - back);
  const date = iso(d).slice(0, 10);
  const ts = (t: string) => `${date}T${t}:00`;
  const arrived = (spec.arrived ?? []).map(([t, n, mb, , sg, st]) => ({ ts: ts(t), time: t, name: n, path: `${DL}\\${n}`, size: Math.round(mb * MB), still_there: st, suggested: sg }));
  const filed = (spec.filed ?? []).map(([t, n, f, how, u]) => ({ ts: ts(t), time: t, name: n, path: `${PARA}\\${f.replace(/\//g, "\\")}\\${n}`, size: 2 * MB, folder: f, how, undone: u }));
  const undone = (spec.undone ?? []).map(([t, n, f]) => ({ ts: ts(t), time: t, name: n, path: `${DL}\\${n}`, size: MB, folder: f, how: "inbox" as const }));
  const deleted = (spec.deleted ?? []).map(([t, n, mb]) => ({ ts: ts(t), time: t, name: n, path: `${DL}\\${n}`, size: Math.round(mb * MB), category: "installer", mode: "recycle" }));
  const worked = (spec.worked ?? []).map(([f, files, extra]) => ({ folder: f, count: files.length + (extra ?? 0), files: files.map(([n, kind]) => ({ name: n, path: `${PARA}\\${f.replace(/\//g, "\\")}\\${n}`, kind })) }));
  const apps = (spec.apps ?? []).map(([t, event, name, old_version, new_version]) => ({ ts: ts(t), time: t, event, key: name, name, publisher: "", kind: "desktop" as const, old_version, new_version }));
  const wf = worked.reduce((a, w) => a + w.count, 0);
  return {
    date, weekday: WD[d.getDay()] ?? "", arrived, filed, undone, deleted, worked, apps,
    counts: { arrived: arrived.length, filed: filed.length, auto_filed: filed.filter((f) => f.how === "auto").length, undone: undone.length, deleted: deleted.length, deleted_bytes: deleted.reduce((a, x) => a + (x.size ?? 0), 0), worked_files: wf, worked_folders: worked.length, apps: apps.length },
  };
}
const bigDel: [string, string, number][] = Array.from({ length: 21 }, (_, i) => [`14:${String(10 + i).padStart(2, "0")}`, i === 0 ? "vm-image-old.iso" : `setup-tool-${i}.exe`, i === 0 ? 18000 : 6.5 * 1024 / 20 + i * 3]);
const journalDays: JournalDay[] = [
  jDay(0, {
    arrived: [["09:12", "Acme-SOW-v3.pdf", 1.2, 0, "1-Projects/Acme-Rollout/Contracts", false], ["10:40", "northwind-findings.xlsx", 0.4, 0, "1-Projects/Northwind-Audit/Findings", false], ["11:05", "screenshot-2026.png", 0.8, 0, null, true]],
    filed: [["09:20", "Acme-SOW-v3.pdf", "1-Projects/Acme-Rollout/Contracts", "inbox", false], ["10:52", "northwind-findings.xlsx", "1-Projects/Northwind-Audit/Findings", "auto", false]],
    worked: [["1-Projects/Acme-Rollout", [["rollout-plan.docx", "changed"], ["site-list.xlsx", "added"], ["kickoff-notes.md", "added"]]]],
  }),
  jDay(1, {
    arrived: [["08:30", "invoice-contoso-0912.pdf", 0.2, 0, "2-Areas/Finance", true], ["09:01", "globex-closeout.pdf", 3, 0, "4-Archives/Globex-Completed", false], ["11:15", "vendor-brochure.pdf", 5, 0, "3-Resources/Vendor-Research", true], ["13:44", "meeting.ics", 0.01, 0, null, false], ["15:02", "photo-001.jpg", 2.4, 0, null, true], ["16:30", "report (1).pdf", 1.1, 0, null, true]],
    filed: [["09:10", "globex-closeout.pdf", "4-Archives/Globex-Completed", "hand", false], ["13:50", "meeting.ics", "2-Areas/Finance", "inbox", true]],
    undone: [["13:55", "meeting.ics", "2-Areas/Finance"]],
  }),
  jDay(2, { apps: [["08:14", "updated", "Larkspur Browser (x64 en-US)", "157.0", "158.0"], ["08:15", "updated", "Tessellate Containers", "4.93.1", "4.94.0"]] }),
  jDay(3, {
    arrived: [["10:00", "contoso-quote.pdf", 0.6, 0, "3-Resources/Vendor-Research", false]],
    filed: [["10:15", "contoso-quote.pdf", "3-Resources/Vendor-Research", "inbox", false]],
    worked: [["2-Areas/Finance", [["budget-2026.xlsx", "changed"]]]],
  }),
  jDay(5, { deleted: bigDel }),
  jDay(8, {
    worked: [["1-Projects/Northwind-Audit", [["scope.docx", "changed"], ["interview-notes.docx", "added"], ["evidence-01.pdf", "added"], ["evidence-02.pdf", "added"], ["evidence-03.pdf", "added"]], 2], ["", [["readme.txt", "changed"]]]],
  }),
  jDay(11, {
    arrived: [["09:30", "acme-invoice-0042.pdf", 0.3, 0, "2-Areas/Finance", false], ["12:10", "northwind-agent-installer.msi", 33, 0, "3-Resources/Tools", false]],
    filed: [["09:35", "acme-invoice-0042.pdf", "2-Areas/Finance", "auto", false], ["12:20", "northwind-agent-installer.msi", "3-Resources/Tools", "hand", false]],
  }),
  jDay(12, { apps: [["17:40", "installed", "Pine Runtime 3.13.0 (64-bit)", "", "3.13.150.0"]] }),
  jDay(15, {
    arrived: [["14:00", "globex-final-report.pdf", 4, 0, "4-Archives/Globex-Completed", false]],
    filed: [["14:05", "globex-final-report.pdf", "4-Archives/Globex-Completed", "inbox", false]],
    worked: [["4-Archives/Globex-Completed", [["handover.docx", "added"]]]],
  }),
  jDay(19, {
    arrived: [["11:11", "contoso-pricing.xlsx", 0.5, 0, "3-Resources/Vendor-Research", true]],
    worked: [["1-Projects/Acme-Rollout", [["risks.xlsx", "changed"], ["timeline.pptx", "changed"]]]],
  }),
];
function journalFor(days: number): JournalResponse {
  const to = new Date(), from = new Date(); from.setDate(from.getDate() - (days - 1));
  const fromS = iso(from).slice(0, 10), toS = iso(to).slice(0, 10);
  const ds = journalDays.filter((d) => d.date >= fromS);
  const sum = (k: keyof JournalDay["counts"]) => ds.reduce((a, d) => a + (d.counts[k] ?? 0), 0);
  const fm = new Map<string, { folder: string; filed: number; worked: number; days: Set<string> }>();
  const fe = (f: string) => fm.get(f) ?? (fm.set(f, { folder: f, filed: 0, worked: 0, days: new Set() }), fm.get(f)!);
  for (const d of ds) {
    for (const f of d.filed) { const e = fe(f.folder); e.filed++; e.days.add(d.date); }
    for (const w of d.worked) { const e = fe(w.folder); e.worked += w.count; e.days.add(d.date); }
  }
  const folders = [...fm.values()].map((e) => ({ folder: e.folder, filed: e.filed, worked: e.worked, days: e.days.size })).sort((a, b) => b.worked + b.filed - (a.worked + a.filed));
  const text = [`Work journal ${fromS} to ${toS}`, "", ...ds.flatMap((d) => [
    `${d.weekday} ${d.date}`,
    ...d.worked.map((w) => `  Worked on ${w.folder || "(top of your folders)"}: ${w.count} documents`),
    ...d.filed.map((f) => `  ${f.time} filed ${f.name} -> ${f.folder}${f.undone ? " (undone)" : ""}`),
    ...d.undone.map((u) => `  ${u.time} undone ${u.name}`),
    ...(d.counts.deleted ? [`  Deleted ${d.counts.deleted} files to the Recycle Bin`] : []),
    ...(d.apps ?? []).map((a) => `  ${a.time} ${a.event} ${a.name} ${a.event === "updated" ? `${a.old_version} -> ${a.new_version}` : a.new_version || a.old_version}`),
    ...(d.counts.arrived ? [`  ${d.counts.arrived} files arrived in Downloads`] : []),
    "",
  ])].join("\n");
  return {
    days_asked: days, from: fromS, to: toS,
    totals: { arrived: sum("arrived"), filed: sum("filed"), auto_filed: sum("auto_filed"), undone: sum("undone"), deleted: sum("deleted"), deleted_bytes: sum("deleted_bytes"), worked_files: sum("worked_files"), active_days: ds.length, apps: sum("apps") },
    folders, days: ds, text,
  };
}

/* --- security (fictional) --- */
const cveRow = (id: string, score: number, summary: string, fixed_in: string | null, days: number, kev = false): SecCve =>
  ({ id, published: ago(days * 1440).slice(0, 10), score, severity: score >= 9 ? "CRITICAL" : score >= 7 ? "HIGH" : score >= 4 ? "MEDIUM" : "LOW",
    summary, fixed_in, kev, kev_added: kev ? ago((days - 6) * 1440).slice(0, 10) : null, ransomware: false });
const tessCves: SecCve[] = [
  cveRow("CVE-2026-90412", 9.8, "Mismatched length fields in Tessellate's compressed protocol headers may allow an unauthenticated client to read uninitialised memory.", "4.96.0", 40, true),
  cveRow("CVE-2026-88120", 8.1, "Tessellate Containers before 4.95.2 does not check the owner of a mounted socket, allowing a local user to gain the service's rights.", "4.95.2", 75),
  cveRow("CVE-2026-71554", 7.5, "A crafted image manifest can make the Tessellate engine use all available memory.", "4.95.0", 120),
  cveRow("CVE-2026-60031", 5.3, "Log files written by Tessellate Containers can contain registry credentials.", "4.94.3", 160),
];
const secApps: SecApp[] = [
  { id: "tessellate", key: "desktop:tessellatecontainers", name: "Tessellate Containers", version: "4.94.0", judged_version: "4.94.0", publisher: "Tessellate Inc.", kind: "desktop",
    available: null, update_id: null, products: ["tessellate:containers"], cves: tessCves, unversioned: 2 },
  { id: "pine312", key: "desktop:pineruntime", name: "Pine Runtime 3.12.4 (64-bit)", version: "3.12.4150.0", judged_version: "3.12.4", publisher: "Pine Project", kind: "desktop",
    available: "3.12.10", update_id: "Pine.Runtime.3.12", products: ["pine:runtime", "pine_project:runtime"], unversioned: 0, cves: [
      cveRow("CVE-2026-55210", 9.1, "The archive module of Pine Runtime follows links when unpacking, so a crafted archive can write outside the target folder.", "3.12.9", 60),
      cveRow("CVE-2026-41877", 7.5, "Pine Runtime's e-mail parser can be made to loop for a very long time by a crafted header.", "3.12.8", 110),
      cveRow("CVE-2026-30096", 6.5, "The bundled HTTP client of Pine Runtime 3.12 before 3.12.7 accepts control characters in a URL path.", "3.12.7", 150),
      cveRow("CVE-2026-22841", 5.9, "A timing difference in Pine Runtime's comparison helper leaks the length of a secret.", "3.12.6", 200),
      cveRow("CVE-2025-91533", 4.3, "Pine Runtime's temporary-folder helper creates folders other local users can read.", "3.12.5", 320),
    ] },
  { id: "northwind", key: "desktop:northwindvpnclient", name: "Northwind VPN Client", version: "7.4.3.4726", judged_version: "7.4.3.4726", publisher: "Northwind Networks Inc", kind: "desktop",
    available: "7.4.4.4801", update_id: "Northwind.VPNClient", products: ["northwind:vpn_client"], unversioned: 1, cves: [
      cveRow("CVE-2026-70465", 7.8, "An unquoted search path in the Northwind VPN Client scheduler lets a local user run a program as SYSTEM.", "7.4.4", 30),
      cveRow("CVE-2026-24018", 7.1, "Northwind VPN Client 7.4.0 through 7.4.4 does not validate the certificate of the update server in one code path.", "7.4.5", 90),
    ] },
  { id: "brightpad", key: "desktop:brightpadnotes", name: "Brightpad Notes", version: "4.12.1", judged_version: "4.12.1", publisher: "Brightpad Labs", kind: "desktop",
    available: "4.13.0", update_id: "Brightpad.Notes", products: ["brightpad:notes"], cves: [], unversioned: 0 },
  { id: "kettle", key: "desktop:kettlearchive", name: "Kettle Archive 24.08 (x64)", version: "24.08", judged_version: "24.08", publisher: "Kettle Software", kind: "desktop",
    available: null, update_id: null, products: ["kettle:archive"], cves: [], unversioned: 0 },
];
const svc = (id: string, name: string, exe: string, running: boolean, account: SecService["account"], ports: [number, boolean][], app: SecApp | null, product = "", version = ""): SecService =>
  ({ id, name, service: id, running, start: running ? "auto" : "manual", account, exe, publisher: app?.publisher ?? "", product: product || (app?.name ?? ""), version: version || (app?.judged_version ?? ""),
    app_id: app?.id ?? null, app_name: app?.name ?? null, ports: ports.map(([port, network]) => ({ port, network })), exposed: ports.some(([, n]) => n),
    products: app?.products ?? [], cves: app?.cves ?? [], unversioned: app?.unversioned ?? 0 });
const secServices: SecService[] = [
  svc("TessEngine", "Tessellate Engine", "C:\\Program Files\\Tessellate\\engine.exe", true, "limited", [[27017, true]], secApps[0]!),
  svc("HarborSvc", "Harbor Remote Service", "C:\\Program Files (x86)\\Harbor\\harbor.exe", true, "system", [[7070, true]], null, "Harbor Remote", "9.0.14"),
  svc("NorthwindSched", "Northwind VPN Service Scheduler", "C:\\Program Files\\Northwind\\scheduler.exe", true, "system", [], secApps[2]!),
  svc("QuillmarkUpd", "Quillmark Update Service", "C:\\Program Files\\Quillmark\\updater.exe", true, "system", [], null, "Quillmark Updater", "1.8.2"),
  svc("LarkspurMaint", "Larkspur Maintenance Service", "C:\\Program Files\\Larkspur\\maintenance.exe", false, "system", [], null, "Larkspur Maintenance", "158.0"),
  svc("BrightSync", "Brightpad Sync", "C:\\Program Files\\Brightpad\\sync.exe", true, "user", [[9000, false]], secApps[3]!),
];
const secHidden = new Set<string>();
const remedyJob = { running: false, action: null as string | null, name: null as string | null, target: null as string | null, started: null as string | null, finished: null as string | null, ok: null as boolean | null, message: null as string | null };
let secScanned = ago(95);
function securityAnswer(brief: boolean): SecurityResponse {
  const ls = settingsRaw.library ?? {};
  const base = { enabled: ls.vulnerabilities !== false, runner: { ...libRunner }, settings: { cve_hours: Number(ls.cve_hours ?? 24), check_updates: !!ls.check_updates, remediate: !!ls.remediate } };
  if (!base.enabled) return base;
  const apps = secApps.filter((a) => !secHidden.has("app|" + a.key)).map((a) => ({ ...a, update: a.available && a.update_id ? { id: a.update_id, to: a.available, kind: "latest" as const, latest: a.available, blocked: null } : null }));
  const quiet = new Set(secApps.filter((a) => secHidden.has("app|" + a.key)).map((a) => a.id));
  const services = secServices.filter((s) => !secHidden.has("service|" + s.id)).map((s) => (s.app_id && quiet.has(s.app_id) ? { ...s, cves: [], unversioned: 0 } : s));
  const hit = apps.filter((a) => a.cves.length > 0), all = hit.flatMap((a) => a.cves);
  const out: SecurityResponse = {
    ...base, scanned_at: secScanned, services_read: true, installed: 10, recognised: secApps.length,
    summary: { apps_affected: hit.length, cves: all.length, kev: all.filter((c) => c.kev).length, critical: all.filter((c) => (c.score ?? 0) >= 9).length,
      fix_available: hit.filter((a) => a.available).length, services: services.length, services_running: services.filter((s) => s.running).length,
      services_exposed: services.filter((s) => s.exposed).length, services_affected: services.filter((s) => s.cves.length > 0).length },
    database: { synced_at: ago(180), tried_at: ago(180), complete: true, cves: 385_946, kev: 1_739, bytes: 401 * MB, error: null },
    hidden: secApps.length - apps.length + secServices.length - services.length,
  };
  return brief ? out : { ...out, apps, services };
}

function mockDashboard(): DashboardResponse {
  const GB = MB * 1024;
  const activity = [[3,1,0], [5,4,0], [0,0,0], [2,2,21], [6,3,0], [1,0,0], [4,2,1]].map(([arrived, filed, deleted], i) => {
    const d = new Date(); d.setDate(d.getDate() - (6 - i));
    return { date: iso(d).slice(0,10), arrived: arrived ?? 0, filed: filed ?? 0, deleted: deleted ?? 0, worked_files: [2,4,0,3,5,1,2][i] ?? 0, apps: i === 4 ? 2 : i === 1 ? 1 : 0 };
  });
  const sum = (key: "arrived" | "filed" | "deleted" | "worked_files" | "apps") => activity.reduce((n, d) => n + d[key], 0);
  return {
    generated_at: iso(now()),
    attention: [
      { level: "danger", text: "1 known flaw is being used in real attacks on software you have installed.", to: "/security" },
      { level: "danger", text: "Tessellate Engine has known flaws and accepts connections from the network.", to: "/security" },
      { level: "warning", text: "3 critical flaws in 3 installed programs.", to: "/security" },
      { level: "warning", text: "2 dates are coming up in your documents; the next is in 4 days.", to: "/watch" },
      { level: "info", text: "5 files with personal or financial details are sitting in Downloads.", to: "/watch" },
      { level: "info", text: "18 files are waiting in the Inbox.", to: "/inbox" },
      { level: "info", text: "4 installed applications have a newer version.", to: "/library" },
      { level: "info", text: "12 files in Downloads look safe to remove.", to: "/cleanup" },
    ],
    agent: { watching: true, model: "demo-model:4b", model_ok: true, problem: null, restart_needed: false, started: ago(600), search: { files: 17389, queued: 0, running: false, last_sweep: ago(20), locked: 3 } },
    inbox: { waiting: 18, bytes: 412 * MB, oldest_days: 41, added_7d: 6, auto_filing: false, auto_filed_24h: 0 },
    cleanup: { scanned_at: ago(300), safe: { count: 12, bytes: 96 * MB }, review: { count: 2, bytes: 61 * MB }, keep: { count: 6, bytes: 9.3 * GB } },
    watch: { enabled: true, scanned_at: ago(300), counts: { soon: 2, later: 4, passed: 3, sensitive: 5 }, next: [
      { name: "Contoso-insurance-policy.pdf", date: iso(new Date(Date.now() + 4 * 86400000)).slice(0,10), days: 4, kind: "valid until" },
      { name: "Northwind-support-renewal.pdf", date: iso(new Date(Date.now() + 19 * 86400000)).slice(0,10), days: 19, kind: "renewal" },
    ] },
    security: { enabled: true, scanned_at: ago(95), recognised: 5, installed: 10, summary: { apps_affected: 3, cves: 11, kev: 1, critical: 3, fix_available: 2, services: 6, services_running: 5, services_exposed: 2, services_affected: 2 },
      top: [{ name: "Tessellate Containers", version: "4.94.0", cves: 4, kev: 1, critical: 1, update_to: null }, { name: "Pine Runtime", version: "3.12.4", cves: 5, kev: 0, critical: 1, update_to: "3.12.10" }, { name: "Northwind VPN Client", version: "7.4.3.4726", cves: 2, kev: 0, critical: 0, update_to: "7.4.4.4801" }],
      exposed: [{ name: "Tessellate Engine", ports: [27017], cves: 4 }, { name: "Harbor Remote Service", ports: [7070], cves: 0 }], database: { synced_at: ago(180), cves: 385946, kev: 1739, error: null } },
    apps: { enabled: true, scanned_at: ago(180), programs: 10, packaged: 3, updates_checked: true, updates: 4, updates_checked_at: ago(300), changes_7d: 3, recent: [
      { ts: ago(2880), event: "updated", name: "Larkspur Browser (x64 en-US)", old_version: "157.0", new_version: "158.0" },
      { ts: ago(2880), event: "updated", name: "Tessellate Containers", old_version: "4.93.1", new_version: "4.94.0" },
      { ts: ago(7200), event: "installed", name: "Pine Runtime 3.13.0 (64-bit)", old_version: "", new_version: "3.13.150.0" },
    ] },
    activity: { days: activity, totals: { arrived: sum("arrived"), filed: sum("filed"), deleted: sum("deleted"), worked_files: sum("worked_files"), apps: sum("apps"), auto_filed: 2, deleted_bytes: 6.8 * GB, active_days: 6 } },
    storage: { collected: ago(5), volumes: [{ letter: "C:", label: "", bytes: 500 * GB, free: 62 * GB }, { letter: "D:", label: "Data", bytes: 1024 * GB, free: 633 * GB }] },
    remedy: { enabled: true, running: false, recent: [
      { ts: ago(40), action: "update", name: "Harbor Remote", target: "9.8.1", ok: 1, message: "Updated Harbor Remote from 9.0.14 to 9.8.1." },
      { ts: ago(1440), action: "update", name: "Kettle Archive", target: "25.01", ok: 0, message: "Not updated: You declined the Windows permission prompt. The installer needs administrator rights." },
    ] },
  };
}

const get: Record<string, Handler> = {
  "/api/dashboard": () => mockDashboard(),
  "/api/security": (q) => securityAnswer(q.get("brief") === "1"),
  "/api/remedy": () => ({ enabled: !!(settingsRaw.library ?? {}).remediate, job: { ...remedyJob }, history: [] }),
  "/api/journal": (q) => journalFor(Math.max(1, Number(q.get("days")) || 30)),
  "/api/library": () => {
    const ls = settingsRaw.library ?? { enabled: true, scan_hours: 24 };
    const vis = <T,>(k: string, a: T[], key: (x: T) => string) => a.filter((x) => !libHidden.has(`${k}|${key(x)}`));
    const images = vis("images", libProducts, (x) => x.key), versions = vis("versions", libChains, (x) => x.key);
    const similar = vis("similar", libPictures, (x) => x.key), installers = vis("installers", libInstallers, (x) => x.path);
    return {
      enabled: ls.enabled !== false, runner: { ...libRunner }, settings: { scan_hours: ls.scan_hours ?? 24 },
      scanned_at: libScanned, seconds: 42, files: 18_204, signatures_checked: ls.check_signatures !== false,
      images, versions, similar, installers,
      applications: ls.applications === false ? null : libApplications(),
      remediate: ls.applications !== false && !!ls.remediate,
      counts: { images: images.length, versions: versions.length, similar: similar.length, installers: installers.length },
      dismissed: libHidden.size,
      summary: {
        images_bytes: images.reduce((s, x) => s + x.size, 0), images_in_downloads_bytes: images.reduce((s, x) => s + x.in_downloads, 0),
        filed_is_older: versions.filter((x) => x.filed_is_older).length, not_signed: installers.filter((x) => x.level !== "signed").length,
      },
    };
  },
  "/api/watch": (q) => {
    if (q.get("refresh")) watchScanned = iso(now());
    const ws = settingsRaw.watch ?? { enabled: true, soon_days: 30, keep_expired_days: 60 };
    const all = watchDates.filter((d) => d.days >= -ws.keep_expired_days);
    const dates = all.filter((d) => !watchHidden.has(watchId(d.path, "date", d.key)));
    const sensitive = watchSensitive.filter((x) => !watchHidden.has(watchId(x.path, "sensitive", x.key)));
    const c = (st: string) => dates.filter((d) => d.status === st).length;
    if (!ws.enabled) return { enabled: false, dates: [], sensitive: [], counts: { soon: 0, passed: 0, later: 0, sensitive: 0 } };
    return { enabled: true, scanned_at: watchScanned, files_read: 17_389, settings: { soon_days: ws.soon_days, keep_expired_days: ws.keep_expired_days },
      dates, older_passed: watchDates.length - all.length + 3, sensitive, counts: { soon: c("soon"), passed: c("passed"), later: c("later"), sensitive: sensitive.length }, dismissed: watchHidden.size };
  },
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
  "/api/system": (): SystemInfo => {
    const GB = 1024 * MB;
    const g0 = "GPU-3f1a9c2e-0000-4a11-9b7e-acme00000001", g1 = "GPU-7b20d4f1-0000-4c22-8e1d-acme00000002";
    return {
      collected: iso(now()), seconds: 1.8,
      os: { name: "Windows 11 Pro", version: "24H2", build: "26100.2314", arch: "64-bit", installed: ago(60 * 24 * 410), last_boot: ago(60 * 27) },
      computer: { name: "ALEX-WORKSTATION", manufacturer: "Northwind Systems", model: "NW Studio 7", board: "Globex B650M Pro", bios: "1.14.2", bios_date: "2026-03-18" },
      secure_boot: true,
      cpu: { name: "AMD Ryzen 7 7840HS", cores: 8, threads: 16, mhz: 3801 },
      memory: {
        installed_bytes: 64 * GB, usable_bytes: 63.2 * GB, free_bytes: 27.4 * GB,
        modules: [
          { slot: "DIMM A1", bytes: 16 * GB, mhz: 5200, rated_mhz: 5600, maker: "Initech Memory", part: "IM5-16G56C40" },
          { slot: "DIMM A2", bytes: 16 * GB, mhz: 5200, rated_mhz: 5600, maker: "Initech Memory", part: "IM5-16G56C40" },
          { slot: "DIMM B1", bytes: 16 * GB, mhz: 5200, rated_mhz: 5600, maker: "Initech Memory", part: "IM5-16G56C40" },
          { slot: "DIMM B2", bytes: 16 * GB, mhz: 5200, rated_mhz: null, maker: null, part: null },
        ],
      },
      gpus: [
        { index: 0, uuid: g0, name: "NVIDIA GeForce RTX 4070", vram_bytes: 12 * GB, vram_used_bytes: 6.3 * GB, driver: "566.14", temp_c: 58, util_pct: 21, pci: "00000000:01:00.0", compute_cap: "8.9", display: "Monitor 1 (2560×1440)" },
        { index: 1, uuid: g1, name: "NVIDIA RTX A2000", vram_bytes: 6 * GB, vram_used_bytes: 0.2 * GB, driver: "566.14", temp_c: 41, util_pct: 0, pci: "00000000:05:00.0", compute_cap: "8.6", display: null },
      ],
      gpu_processes: [{ name: "ollama.exe", pid: 14820, gpu_uuid: g0 }],
      disks: [
        { number: "0", model: "Umbrella NVMe 990 1TB", media: "SSD", bus: "NVMe", bytes: 1000 * GB, health: "Healthy", letters: ["C:"] },
        { number: "1", model: "Acme Barracuda 4TB", media: "HDD", bus: "SATA", bytes: 4000 * GB, health: "Warning", letters: ["D:", "E:"] },
      ],
      volumes: [
        { letter: "C:", label: "System", fs: "NTFS", bytes: 930 * GB, free: 72 * GB, disk: "0", media: "SSD" },
        { letter: "D:", label: "Data", fs: "NTFS", bytes: 2000 * GB, free: 940 * GB, disk: "1", media: "HDD" },
        { letter: "E:", label: null, fs: "exFAT", bytes: 1700 * GB, free: 1210 * GB, disk: "1", media: "HDD" },
      ],
      ollama: {
        url: "http://127.0.0.1:11434", reachable: !demo.modelMissing, version: "0.6.2",
        loaded: demo.modelMissing ? [] : [{ name: "qwen3:8b", bytes: 6.1 * GB, vram_bytes: 5.6 * GB, gpu_pct: 92, params: "8.2B", quant: "Q4_K_M", context: 8192, expires: ago(-4) }],
      },
      cuda_visible_devices: { this_process: "0", user: null, machine: null },
      agent: { folder: "C:\\Users\\alex\\ShadowFiler", drive: "C:", python: "3.12.7 · C:\\Users\\alex\\ShadowFiler\\.venv\\Scripts\\python.exe" },
      notes: [
        { level: "warn", text: "Drive C: has less than 10% free space. The Recycle Bin limit may be lower than usual." },
        { level: "info", text: "8% of the model runs on the CPU; suggestions take about 3 seconds each." },
      ],
    };
  },
};

const post: Record<string, Handler> = {
  "/api/security/check": () => {
    if (libRunner.running) return { ok: false, message: "A check is already running." };
    Object.assign(libRunner, { running: true, started: iso(now()), progress: "Comparing with known vulnerabilities", error: null });
    setTimeout(() => { Object.assign(libRunner, { running: false, progress: null, finished: iso(now()) }); secScanned = iso(now()); }, 2000);
    return { ok: true, started: true };
  },
  "/api/security/hide": (_q, b) => {
    const id = `${b.kind}|${b.key}`;
    if (b.undo) secHidden.delete(id); else secHidden.add(id);
    return { ok: true };
  },
  "/api/security/restore": () => { secHidden.clear(); return { ok: true }; },
  "/api/remedy/update": (_q, b) => {
    if (remedyJob.running) return { ok: false, message: "Another update or stop is still running." };
    const a = libApps.find((x) => x.id === b.id) ?? secApps.find((x) => x.id === b.id);
    const to = a ? (libAvail[a.name]?.[0] ?? (a as SecApp).available ?? "") : "";
    Object.assign(remedyJob, { running: true, action: "update", name: a?.name ?? "the application", target: to, ok: null, message: null });
    setTimeout(() => Object.assign(remedyJob, { running: false, ok: true, message: `Updated ${a?.name ?? "the application"} from ${a?.version ?? "?"} to ${to}.` }), 3000);
    return { ok: true, started: true };
  },
  "/api/remedy/stop-service": (_q, b) => {
    if (remedyJob.running) return { ok: false, message: "Another update or stop is still running." };
    const s = secServices.find((x) => x.id === b.id);
    Object.assign(remedyJob, { running: true, action: "stop", name: s?.name ?? "the service", target: String(b.id), ok: null, message: null });
    setTimeout(() => { if (s) s.running = false; Object.assign(remedyJob, { running: false, ok: true, message: "Stopped. Windows starts it again at the next boot if it is set to start automatically." }); }, 2500);
    return { ok: true, started: true };
  },
  "/api/library/scan": () => {
    if (libRunner.running) return { ok: false, message: "A scan is already running." };
    Object.assign(libRunner, { running: true, started: iso(now()), progress: "Looking at pictures: 40 of 120", error: null });
    setTimeout(() => { Object.assign(libRunner, { running: false, progress: null, finished: iso(now()) }); libScanned = iso(now()); }, 2000);
    return { ok: true };
  },
  "/api/library/check-updates": () => {
    if (libRunner.running) return { ok: false, message: "The library is already being scanned." };
    Object.assign(libRunner, { running: true, started: iso(now()), progress: "Asking winget for newer versions…", error: null });
    setTimeout(() => { Object.assign(libRunner, { running: false, progress: null, finished: iso(now()) }); libUpdChecked = iso(now()); }, 2000);
    return { ok: true, started: true, runner: { ...libRunner } };
  },
  "/api/library/dismiss": (_q, b) => {
    const id = `${b.kind}|${b.key}`;
    if (b.undo) libHidden.delete(id); else libHidden.add(id);
    return { ok: true };
  },
  "/api/library/restore": () => { libHidden.clear(); return { ok: true }; },
  "/api/library/reveal": () => ({ ok: true }),
  "/api/watch/dismiss": (_q, b) => {
    const id = watchId(b.path, b.kind, b.key ?? "");
    if (b.undo) watchHidden.delete(id); else watchHidden.add(id);
    return { ok: true };
  },
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
  "/api/search/preview": (_q, b) => mockPreview(String(b?.path ?? "")),
  "/api/file/ticket": (_q, b) => mockFileTicket(String(b?.path ?? "")),
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
  return JSON.parse(JSON.stringify(await h(u.searchParams, body ?? {})));
}

/* ---------- File preview (fictional text) ---------- */
const SOW_TEXT = `Statement of Work: Acme Rollout, Phase 3

Purpose
This statement of work describes the third phase of the Acme branch rollout, covering the remaining forty-two sites in the northern region. Work begins on 3 November and is expected to finish by the end of January.

Scope
The supplier installs and configures the standard branch kit at each site, migrates local file shares to the central store, and trains two staff members per branch. Network cabling and building works are out of scope and remain with Acme Facilities.

Acceptance
Each site is accepted when the checklist in Appendix B is signed by the branch manager. Defects found within ten working days are fixed at no extra cost.

Fees and payment
The fixed fee is invoiced in three equal parts: at kick-off, after twenty sites are accepted, and at final acceptance. Payment terms are thirty days from invoice.`;

const AUDIT_TEXT = `Northwind Traders: Security Posture Audit, Draft Findings

Summary
The review covered identity, endpoint and backup controls across the head office and two warehouses. Overall the posture is reasonable, with three findings that need attention before the year-end board review.

Finding 1: Shared administrator accounts
Two warehouse servers are still managed through a single shared administrator login. We recommend named accounts with multi-factor sign-in.

Finding 2: Backup restore tests
Backups run nightly, but no restore has been tested since March. A quarterly restore test should be scheduled and recorded.

Finding 3: Unpatched laptops
Eleven laptops are more than sixty days behind on updates. Most belong to the field sales team, who rarely connect to the office network.`;

const LONG_TEXT = Array.from({ length: 30 }, (_, i) =>
  `Section ${i + 1}: Globex closing activities\n\nThe project team confirmed that all deliverables for work package ${i + 1} were handed over, signed off by the Globex steering group and archived in the shared project library. Outstanding risks were transferred to the operations owner, and the remaining budget was reconciled against the final purchase order. Lessons learned were captured in the retrospective and are summarised in the appendix.`,
).join("\n\n");

function mockPreview(path: string) {
  const name = path.split(/[\\/]/).pop() ?? path;
  const ext = (name.split(".").pop() ?? "").toLowerCase();
  const view = ext === "pdf" ? "pdf" : ext === "docx" ? "docx" : ["png", "jpg", "jpeg", "gif", "webp"].includes(ext) ? "image" : null;
  const base = { ok: true, path, name, ext, view, size: 240_000 + name.length * 7_000, modified: ago(name.length * 40), read_at: ago(name.length * 30), truncated: false, openable: true, note: "" };
  const withText = (text: string, extra: Record<string, unknown> = {}) => ({ ...base, status: "ok", text, chars: text.length, ...extra });
  if (/payslip/i.test(name)) return { ...base, view: null, status: "locked", text: "", chars: 0, note: "Password-protected: the agent does not open it." };
  if (/globex_closing_report/i.test(name)) {
    const text = LONG_TEXT.slice(0, 4000);
    return { ...base, status: "ok", text, chars: 48_512, truncated: true };
  }
  if (/^scan|\.(png|jpe?g|tiff?|heic)$/i.test(name))
    return withText(`ACME CORPORATION\nDelivery note no. 88213\n\nReceived 14 boxes of branch kit in good condition.\nSigned: J. Mor1and, Site lead\nDate: 02/1O/2026`, { status: "ocr", note: "This is a scan or a picture: the text was read by OCR and may have mistakes." });
  if (["zip", "iso", "exe", "msi", "crdownload", "7z"].includes(ext))
    return { ...base, status: "name_only", text: "", chars: 0, openable: false, read_at: null, note: "Not a kind of file the agent reads (or too big): only its name is known." };
  if (/northwind|nw_/i.test(name) || ext === "docx") return withText(AUDIT_TEXT);
  return withText(SOW_TEXT);
}

// Small, self-contained fictional assets: no file or network access in demo mode.
const DEMO_PDF_STREAM = "BT /F1 20 Tf 50 750 Td (Demo document \\(fictional\\)) Tj ET";
const DEMO_PDF_OBJECTS = [
  "<< /Type /Catalog /Pages 2 0 R >>",
  "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
  "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
  "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  `<< /Length ${DEMO_PDF_STREAM.length} >>\nstream\n${DEMO_PDF_STREAM}\nendstream`,
];
function demoPdf() {
  let text = "%PDF-1.4\n";
  const offsets = [0];
  DEMO_PDF_OBJECTS.forEach((object, i) => { offsets.push(text.length); text += `${i + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = text.length;
  text += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new Blob([text], { type: "application/pdf" });
}
async function mockFileTicket(path: string) {
  const preview = mockPreview(path);
  if (preview.status === "locked") return { ok: false, message: "Password-protected: the agent does not open it. Use Open." };
  if (preview.view === "docx") return { ok: false, message: "Word files are drawn from the real file; the demo has none. Switch to Text." };
  if (!preview.view) return { ok: false, message: "Only the text is available for this file." };
  let blob = demoPdf();
  if (preview.view === "image") {
    let picture: Blob | null = null;
    if (typeof document !== "undefined") {
      const canvas = document.createElement("canvas");
      canvas.width = 640; canvas.height = 480;
      const context = canvas.getContext("2d");
      if (context) {
        context.fillStyle = "#e5e7eb"; context.fillRect(0, 0, 640, 480);
        context.fillStyle = "#4b5563"; context.font = "28px sans-serif"; context.textAlign = "center";
        context.fillText("Demo picture", 320, 240);
        picture = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
      }
    }
    const fallback = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=";
    blob = picture ?? new Blob([Uint8Array.from(atob(fallback), (c) => c.charCodeAt(0))], { type: "image/png" });
  }
  return { ok: true, kind: preview.view, size: blob.size, expires_in: 300, url: URL.createObjectURL(blob) };
}
