export type Source = "rule" | "origin" | "name" | "similar" | "model";

export interface Candidate {
  folder: string;
  source: Source;
  score: number | null;
  why: string;
  exists: boolean;
  model_agrees?: boolean | undefined;
  rank: number;
}

export interface InboxItem {
  path: string;
  name: string;
  size: number;
  mtime: number;
  added: string;
  ext: string;
  modified: string;
  candidates: Candidate[];
  ready: boolean;
  duplicate: { folder: string; path: string; similarity: number } | null;
  confidence: number | null;
  cleanup: { level: string; category: string; reason: string } | null;
  auto: { auto: boolean; folder?: string; why: string; soon?: boolean };
  /** Website the file was downloaded from (and the page that linked to it), when Windows recorded one. */
  origin?: { host: string | null; referrer: string | null } | null;
}

export interface InboxResponse {
  items: InboxItem[];
  total: number;
  offset: number;
  examples: { examples: number; folders: number } | null;
  parents: string[];
  destinations: string[];
}

export interface OkResponse {
  ok: boolean;
  message?: string;
}

export interface JournalRow {
  id: number;
  ts: string;
  src: string;
  dest: string;
  size: number;
  folder: string;
  source: string;
  rank: number;
  top_folder: string;
  top_score: number | null;
  top_source: string;
  status: "moved" | "undone" | "pending" | "interrupted";
  undone_ts: string | null;
  note: string | null;
}

export interface Feedback {
  moves: number;
  top_accepted: number;
  rate: number;
  auto_moves: number;
  per_folder: { folder: string; n: number; accepted: number }[];
}

export interface MovesResponse {
  journal: JournalRow[];
  feedback: Feedback;
}

export interface AutofileSettings {
  enabled: boolean;
  min_decisions: number;
  min_rate: number;
  window: number;
  min_score: number;
  delay_minutes: number;
}
export interface AutofileFolder {
  folder: string;
  source: string;
  decisions: number;
  agreed: number;
  rate: number;
  proven: boolean;
  needed: number;
  revoked: string | null;
}
export interface AutofileResponse {
  settings: AutofileSettings;
  summary: {
    last24h: number;
    undone: number;
    last_run: string | null;
    last_moved: string | null;
    last_error: string | null;
  };
  folders: AutofileFolder[];
}

export type Level = "safe" | "likely" | "review" | "keep" | "info";
export type Decision = "agree" | "disagree" | "keep" | null;

export interface CleanupItem {
  path: string;
  name: string;
  is_dir: boolean;
  folder: string;
  size: number;
  category: string;
  level: Level;
  reason: string;
  related: string | null;
  caution: string | null;
  added: string;
  age_days: number;
  last_opened: string | null;
  decision: Decision;
}

export interface CleanupFileRef {
  path: string;
  name: string;
  size: number;
  why?: string;
}

export interface CleanupResponse {
  runner: {
    running: boolean;
    started: string | null;
    progress: string | null;
    error: string | null;
    finished: string | null;
  };
  report: {
    generated: string | null;
    counts: {
      inbox_files: number;
      para_files: number;
      cloud_only_para: number;
      cloud_only_inbox: number;
      files_hashed: number;
      unconfirmed_cloud_groups: number;
    };
    by_level: Record<string, { count: number; bytes: number }>;
    items: CleanupItem[];
    settings: Record<string, number | boolean>;
    errors: string[];
    para_duplicates: { size: number; confirmed: boolean; paths: string[] }[];
  } | null;
  levels: Record<string, string>;
  plan: {
    recycle_count: number;
    recycle_bytes: number;
    too_big: { path: string; name: string; size: number }[];
    limits: Record<string, { known: boolean; nuke: boolean; max_bytes: number; drive: string }>;
  };
  deleter: {
    running: boolean;
    progress: string | null;
    error: string | null;
    result: {
      mode: string;
      finished: string;
      deleted: CleanupFileRef[];
      deleted_bytes: number;
      skipped: CleanupFileRef[];
      failed: CleanupFileRef[];
    } | null;
  };
}

export interface CleanupHistoryRow {
  ts: string;
  path: string;
  size: number;
  category: string;
  mode: string;
  result: string;
}

export interface SearchResult {
  path: string;
  name: string;
  folder: string;
  source: string;
  ext: string;
  size: number;
  status: string;
  modified: string;
  score: number;
  similarity: number | null;
  keyword: boolean;
  snippet: string;
  part: number | null;
  openable: boolean;
}
export interface SearchResponse {
  results: SearchResult[];
  semantic: boolean;
  semantic_error: string | null;
  ms: number;
  searched_files: number;
}
export interface SearchStatus {
  running: boolean;
  phase: string | null;
  done: number;
  todo: number;
  current: string | null;
  last_sweep: string | null;
  roots: { path: string; exists: boolean }[];
  by_status: Record<string, number>;
  model: string;
  model_ok: boolean;
  ocr: { enabled: boolean; available: boolean; message: string };
  fts: boolean;
  db_bytes: number;
  last_error: string | null;
  errors: { path: string; error: string }[];
}

export interface StatsBucket {
  label: string;
  n: number;
  exact: number;
  top: number;
}
export interface Stats {
  depth: number;
  total: number;
  period: [string, string] | null;
  filed: number;
  unfiled: number;
  unsure: number;
  errors: number;
  overall: StatsBucket | null;
  by_method: StatsBucket[];
  by_conf: StatsBucket[];
  misses: { predicted: string; actual: string; n: number }[];
}

export interface Prediction {
  id: number;
  ts: string;
  path: string;
  filename: string;
  size: number;
  method: string;
  predicted: string | null;
  confidence: string | number | null;
  reason: string;
  actual: string | null;
  actual_ts: string | null;
  outcome: "match" | "miss" | "pending" | "unsure" | "error";
}

export interface Status {
  mode: string;
  started: string;
  ollama: boolean;
  watching: boolean;
  last_prediction: string | null;
  restart_needed: boolean;
  problem: string | null;
  model_missing: boolean;
  installed_models: string[];
  supervised: boolean;
  model: string;
  inbox: string[];
  para_root: string;
  log_file: string;
}

export interface Rule {
  name: string;
  extensions: string[];
  name_regex?: string | undefined;
  destination: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Raw = any;

export interface SettingsResponse {
  raw: Raw;
  models: string[];
  destinations: string[];
  defaults: Raw;
  restart_needed: boolean;
  restart_keys: string[];
  config_path: string;
}
export interface SaveResponse extends OkResponse {
  restart_needed?: boolean;
}

export interface FsCheck {
  input: string;
  expanded: string;
  exists: boolean;
}
export interface FsDirs {
  path: string;
  parent: string | null;
  dirs: { name: string; path: string }[];
  quick?: { name: string; path: string }[];
}

export interface SystemInfo {
  collected: string;
  seconds: number;
  os: { name: string; version: string; build: string; arch: string; installed: string | null; last_boot: string | null };
  computer: { name: string; manufacturer: string; model: string; board: string | null; bios: string | null; bios_date: string | null };
  secure_boot: boolean | null;
  cpu: { name: string; cores: number; threads: number; mhz: number | null };
  memory: {
    installed_bytes: number; usable_bytes: number; free_bytes: number;
    modules: { slot: string; bytes: number; mhz: number | null; rated_mhz: number | null; maker: string | null; part: string | null }[];
  };
  gpus: {
    index: number; uuid: string; name: string; vram_bytes: number; vram_used_bytes: number; driver: string | null;
    temp_c: number | null; util_pct: number | null; pci: string | null; compute_cap: string | null; display: string | null;
  }[];
  gpu_processes: { name: string; pid: number; gpu_uuid: string }[];
  disks: { number: string; model: string; media: string; bus: string; bytes: number; health: string; letters: string[] }[];
  volumes: { letter: string; label: string | null; fs: string; bytes: number; free: number; disk: string | null; media: string | null }[];
  ollama: {
    url: string; reachable: boolean; version: string | null;
    loaded: { name: string; bytes: number; vram_bytes: number; gpu_pct: number | null; params: string | null; quant: string | null; context: number | null; expires: string | null }[];
  };
  cuda_visible_devices: { this_process: string | null; user: string | null; machine: string | null };
  agent: { folder: string; drive: string; python: string };
  notes: { level: "info" | "warn"; text: string }[];
}

export interface LogResponse {
  lines: string[];
}

export interface WatchDate {
  path: string; name: string; folder: string; source: "para" | "inbox" | "extra"; size: number; modified: string;
  date: string;
  kind: "expires" | "valid until" | "due" | "renewal" | "ends";
  days: number;
  status: "soon" | "later" | "passed";
  context: string;
  key: string;
  copies: string[];
}
export interface WatchSensitive {
  path: string; name: string; folder: string; source: "inbox"; size: number; modified: string;
  found: { kind: "pan" | "aadhaar" | "card" | "bank" | "passport" | "key"; label: string; count: number }[];
  level: "high" | "medium";
  key: string;
}
export interface WatchResponse {
  enabled: boolean;
  scanned_at?: string; files_read?: number;
  settings?: { soon_days: number; keep_expired_days: number };
  dates: WatchDate[]; older_passed?: number;
  sensitive: WatchSensitive[];
  counts: { soon: number; passed: number; later: number; sensitive: number };
  dismissed?: number;
  error?: string;
}
