export type Source = "rule" | "origin" | "name" | "similar" | "model";

export type Part<T> = T | { error: string };
export interface DashboardResponse {
  generated_at: string;
  attention: { level: "danger" | "warning" | "info"; text: string; to: string }[];
  agent: Part<{ watching: boolean; model: string | null; model_ok: boolean; problem: string | null; restart_needed: boolean; started: string | null;
    search: { files: number; queued: number; running: boolean; last_sweep: string | null; locked: number } | null }>;
  inbox: Part<{ waiting: number; bytes: number; oldest_days: number | null; added_7d: number; auto_filing: boolean; auto_filed_24h: number }>;
  cleanup: Part<{ scanned_at: string | null; safe: { count: number; bytes: number }; review: { count: number; bytes: number }; keep: { count: number; bytes: number } }>;
  watch: Part<{ enabled: boolean; counts?: { soon: number; later: number; passed: number; sensitive: number }; scanned_at?: string;
    next?: { name: string; date: string; days: number; kind: string }[] }>;
  security: Part<{ enabled: boolean; scanned_at?: string | null; recognised?: number; installed?: number;
    summary?: { apps_affected: number; cves: number; kev: number; critical: number; fix_available: number; services: number; services_running: number; services_exposed: number; services_affected: number };
    top?: { name: string; version: string; cves: number; kev: number; critical: number; update_to: string | null }[];
    exposed?: { name: string; ports: number[]; cves: number }[];
    database?: { synced_at: string | null; cves: number; kev: number; error: string | null } }>;
  apps: Part<{ enabled: boolean; scanned_at?: string | null; programs?: number; packaged?: number; updates_checked?: boolean; updates?: number;
    updates_checked_at?: string | null; changes_7d?: number;
    recent?: { ts: string; event: "installed" | "updated" | "removed"; name: string; old_version: string; new_version: string }[] }>;
  activity: Part<{ days: { date: string; arrived: number; filed: number; deleted: number; worked_files: number; apps: number }[];
    totals: { arrived: number; filed: number; deleted: number; worked_files: number; apps: number; auto_filed: number; deleted_bytes: number; active_days: number } }>;
  storage: Part<{ collected: string | null; volumes: { letter: string; label: string; bytes: number; free: number }[] }>;
  /** What the Network page last found (absent on older agents). read_at null = not read yet. */
  network?: Part<{ read_at: string | null; findings: { level: "danger" | "warning" | "info"; text: string; tab: string }[];
    counts: { listening_network_other?: number; listening_network?: number; connections?: number; programs_connected?: number; devices?: number };
    firewall: { state: "on" | "off" | "partly" | null; off: string[]; other: string[] } | null; virtual_up?: number;
    interfaces: { name: string; kind: "ethernet" | "wifi" | "vpn"; speed: number; address: string | null; gateway: string | null; network: string | null;
      category: "public" | "private" | "domainauthenticated" | null; internet: boolean; ssid?: string | null }[] }>;
  remedy: Part<{ enabled: boolean; running: boolean; recent: { ts: string; action: "update" | "stop" | "firewall"; name: string; target: string; ok: number; message: string }[] }>;
}

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

export type LibraryKind = "images" | "versions" | "similar" | "installers";
export type LibrarySrc = "inbox" | "para";
export interface LibraryImageItem { path: string; name: string; is_dir: boolean; size: number; files: number; source: LibrarySrc; folder: string; modified: string | null; version: string | null; build: string | null; }
export interface LibraryProduct { key: string; product: string; versions: string[]; items: LibraryImageItem[]; size: number; in_downloads: number; }
export interface LibraryChainMember { path: string; name: string; size: number; source: LibrarySrc; folder: string; modified: string | null; label: string; newest: boolean; }
export interface LibraryChain { key: string; title: string; ext: string; kind: "versions" | "same-name"; filed_is_older: boolean; members: LibraryChainMember[]; }
export interface LibraryPicture { path: string; name: string; size: number; source: LibrarySrc; folder: string; modified: string | null; w: number; h: number; distance?: number; }
export interface LibraryPictureGroup { key: string; identical: boolean; members: LibraryPicture[]; }
export interface LibraryInstaller { path: string; name: string; size: number; source: LibrarySrc; folder: string; modified: string | null; level: "signed" | "unsigned" | "untrusted" | "tampered" | "unknown"; text: string; status: string; publisher: string; expires: string; host: string | null; product?: string; version?: string; installed_name?: string; installed_version?: string; file_is?: "older" | "same" | "newer" | null; }
export interface InstalledApp {
  id: string; key: string; name: string; version: string; publisher: string;
  kind: "desktop" | "packaged"; from_store: boolean; scope: "machine" | "user"; arch: string;
  installed: string | null; date_is: "installed" | "changed"; size: number | null; location: string | null;
  /** Newer version winget lists, or null (absent on older agents). */
  available?: string | null; update_id?: string | null;
  /** What the Update button would do, or why not (absent on older agents). */
  update?: UpdatePlan | null;
}
export interface AppUpdates {
  enabled: boolean; hours: number; checked_at: string | null; listed_at: string | null; ok: boolean; error: string | null; count: number;
  unmatched: { name: string; id: string; version: string; available: string }[];
}
export interface AppChange {
  ts: string; event: "installed" | "updated" | "removed";
  key: string; name: string; publisher: string; kind: "desktop" | "packaged";
  old_version: string; new_version: string;
}
export interface LibraryApplications {
  scanned_at: string | null; apps: InstalledApp[]; changes: AppChange[]; changes_days: number; history_since: string | null;
  desktop_read: boolean; packaged_read: boolean;
  counts: { desktop: number; packaged: number; store: number; no_version: number; date_is_a_guess: number };
  total_bytes: number; sized: number;
  updates?: AppUpdates | null;
}
export interface LibraryResponse {
  applications: LibraryApplications | null;
  /** Update from the console is switched on in Settings. */
  remediate?: boolean;
  enabled: boolean;
  runner: { running: boolean; started: string | null; progress: string | null; error: string | null; finished: string | null };
  settings: { scan_hours: number };
  scanned_at: string | null; seconds?: number; files?: number; signatures_checked?: boolean;
  images: LibraryProduct[]; versions: LibraryChain[]; similar: LibraryPictureGroup[]; installers: LibraryInstaller[];
  counts: Record<LibraryKind, number>;
  dismissed: number;
  summary: { images_bytes: number; images_in_downloads_bytes: number; filed_is_older: number; not_signed: number };
}

export interface JournalArrived { ts: string; time: string; name: string; path: string; size: number | null; still_there: boolean; suggested: string | null; }
export interface JournalFiled { ts: string; time: string; name: string; path: string | null; size: number | null; folder: string; how: "inbox" | "auto" | "hand"; undone: boolean; }
export interface JournalUndone { ts: string; time: string; name: string; path: string | null; size: number | null; folder: string; how: "inbox" | "auto"; }
export interface JournalDeleted { ts: string; time: string; name: string; path: string; size: number | null; category: string; mode: string; }
export interface JournalWorked { folder: string; count: number; files: { name: string; path: string; kind: "added" | "changed" }[]; }
export interface JournalDay {
  date: string;
  weekday: string;
  counts: { arrived: number; filed: number; auto_filed: number; undone: number; deleted: number; deleted_bytes: number; worked_files: number; worked_folders: number; apps?: number };
  apps?: (AppChange & { time: string })[];
  arrived: JournalArrived[]; filed: JournalFiled[]; undone: JournalUndone[]; deleted: JournalDeleted[]; worked: JournalWorked[];
}
export interface JournalResponse {
  days_asked: number; from: string; to: string;
  totals: { arrived: number; filed: number; auto_filed: number; undone: number; deleted: number; deleted_bytes: number; worked_files: number; active_days: number; apps?: number };
  folders: { folder: string; filed: number; worked: number; days: number }[];
  days: JournalDay[];
  text: string;
}

export interface PreviewResponse {
  ok: boolean; message?: string;
  view: "pdf" | "docx" | "image" | null;
  path: string; name: string; ext?: string; size?: number;
  status: "ok" | "ocr" | "locked" | "name_only" | "no_text" | "ocr_empty" | "pending";
  modified?: string; read_at?: string | null;
  text: string; chars: number; truncated: boolean; openable: boolean; note: string;
}

export interface FileTicket {
  ok: boolean; message?: string; url: string; kind: "pdf" | "docx" | "image"; size: number; expires_in: number;
}

/* --- Security: known vulnerabilities and third-party Windows services --- */
export interface SecCve { id: string; published: string; score: number | null; severity: string; summary: string; fixed_in: string | null; kev: boolean; kev_added: string | null; ransomware: boolean; }
export interface SecApp {
  id: string; key: string; name: string; version: string; judged_version: string; publisher: string; kind: "desktop" | "packaged";
  available: string | null; update_id: string | null; update?: UpdatePlan | null; products: string[]; cves: SecCve[]; unversioned: number;
}
export interface SecService {
  id: string; name: string; service: string; running: boolean; start: string; account: "system" | "limited" | "user";
  exe: string; publisher: string; product: string; version: string; app_id: string | null; app_name: string | null;
  ports: { port: number; network: boolean }[]; exposed: boolean; products: string[]; cves: SecCve[]; unversioned: number;
}
export interface SecuritySummary {
  apps_affected: number; cves: number; kev: number; critical: number; fix_available: number;
  services: number; services_running: number; services_exposed: number; services_affected: number;
}
export interface SecurityResponse {
  enabled: boolean;
  runner: { running: boolean; started: string | null; progress: string | null; error: string | null; finished: string | null };
  settings: { cve_hours: number; check_updates: boolean; remediate?: boolean };
  scanned_at?: string | null; services_read?: boolean; installed?: number; recognised?: number;
  summary?: SecuritySummary;
  database?: { synced_at: string | null; tried_at: string | null; complete: boolean; cves: number; kev: number; bytes: number; error: string | null };
  hidden?: number;
  apps?: SecApp[]; services?: SecService[];
}

/* --- Remediation: update an application, stop a service --- */
export interface UpdatePlan { id: string; to: string; kind: "latest" | "same_line"; latest: string; blocked: string | null; }
export interface RemedyJob { running: boolean; action: "update" | "stop" | "firewall" | null; name: string | null; target: string | null; started: string | null; finished: string | null; ok: boolean | null; message: string | null; }
export interface RemedyResponse {
  enabled: boolean; job: RemedyJob;
  history: { ts: string; action: "update" | "stop" | "firewall"; name: string; target: string; before: string; after: string; ok: number; message: string }[];
}

/* --- Network: interfaces, routes, exposure, connections, devices --- */
export interface NetAddress { address: string; prefix: number | null; family: "IPv4" | "IPv6"; origin: string; scope: "this PC" | "local network" | "internet" | "all" | "unknown"; }
export interface NetAdapter {
  index: number; name: string; description: string;
  kind: "ethernet" | "wifi" | "vpn" | "virtual" | "bluetooth";
  up: boolean; status: string; speed: number;
  mac: string; addresses: NetAddress[]; gateways: string[]; dns: string[];
  dhcp: boolean; metric: number | null; mtu: number | null;
  network: string | null;
  category: "public" | "private" | "domainauthenticated" | null;
  internet: boolean;
  wifi: { ssid?: string; signal?: string; authentication?: string; radio_type?: string; channel?: string; band?: string } | null;
}
export interface NetRoute { destination: string; next: string; on_link: boolean; interface: string; metric: number | null; family: "IPv4" | "IPv6"; protocol: string;
  kind: "default" | "network" | "host" | "link" | "multicast" | "loopback"; }
export interface NetListener { proto: "TCP" | "UDP"; port: number; process: string; path: string; pid: number; addresses: string[]; reach: "network" | "this PC"; windows: boolean; }
export interface NetConnectionGroup { process: string; count: number; internet: number; local: number; remotes: { address: string; port: number; count: number; scope: string }[]; }
export interface NetDevice { address: string; mac: string; state: string; interface: string; gateway: boolean; family: "IPv4" | "IPv6"; }
export interface NetworkResponse {
  read_at: string | null; error?: string; seconds?: number; computer?: string;
  /** Turning the firewall on from the console is switched on in Settings. */
  remediate?: boolean;
  adapters: NetAdapter[]; routes: NetRoute[];
  firewall: { name: string; enabled: boolean; inbound: string; outbound: string }[];
  other_firewalls?: string[];
  /** Enabled rules that let connections in, grouped by program (absent on older agents, null if unreadable). */
  rules?: { total: number; windows: number; missing: number; wide_open: { name: string; profiles: string[]; any_address: boolean }[];
    programs: { program: string; path: string; rules: number; ports: string[]; more_ports: number; any_port: boolean; profiles: string[];
      any_address: boolean; public: boolean; missing: boolean }[] } | null;
  shares: { name: string; path: string; description: string; builtin: boolean; printer: boolean }[];
  listening: NetListener[]; connections: NetConnectionGroup[]; devices: NetDevice[];
  dns: { suffixes: string[]; servers: string[] };
  proxy: { enabled: boolean; server: string; script: string; bypass: string };
  hosts: { address: string; names: string[] }[];
  findings: { level: "danger" | "warning" | "info"; text: string; tab: "exposure" | "interfaces" | "routes" | "dns" }[];
  counts: { adapters_up?: number; adapters?: number; routes?: number; listening?: number; listening_network?: number; listening_network_other?: number;
    connections?: number; programs_connected?: number; devices?: number; shares?: number; hosts?: number };
}

/* --- Compliance: the five control areas, declarations, history --- */
export type CheckStatus = "pass" | "fail" | "warn" | "unknown" | "info";
export type DeclaredAnswer = "yes" | "no" | "na" | null;
export interface ComplianceCheck {
  id: string; title: string; status: CheckStatus; detail: string; evidence: string[]; fix: string | null; to: string | null;
  accepted: { reason: string; ts: string } | null;
}
export interface ComplianceControl {
  key: "firewalls" | "configuration" | "updates" | "access" | "malware";
  title: string; about: string; status: "pass" | "fail" | "warn" | "unknown";
  checks: ComplianceCheck[]; counts: { pass: number; fail: number; warn: number; unknown: number }; accepted: number;
}
export interface ComplianceResponse {
  assessed_at: string | null; error?: string;
  device: { name?: string; manufacturer?: string; model?: string; serial?: string; windows?: string; build?: string; user?: string };
  controls: ComplianceControl[];
  declared: { key: string; title: string; about: string; answer: DeclaredAnswer; note: string; ts: string | null }[];
  thresholds: Record<string, number>;
  summary: { controls_passing?: number; controls?: number; fail?: number; warn?: number; unknown?: number; passed?: number; accepted?: number;
    declared_yes?: number; declared_no?: number; declared_open?: number };
  history: { day: string; controls: Record<string, "pass" | "fail" | "warn" | "unknown">; checks: Record<string, string>;
    summary: { controls_passing: number; fail: number; warn: number; unknown: number } }[];
  patch_log: { ts: string; action: "update" | "stop" | "firewall"; name: string; target: string; before: string; after: string; ok: number; message: string }[];
  text?: string;
}
