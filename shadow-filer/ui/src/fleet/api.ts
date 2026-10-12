/* The single gateway to the fleet server. Every call carries the organisation's console key; the key is kept
   for this browser tab only (sessionStorage) and never written anywhere else. */

const KEY = "sf-fleet-key";
let memory: string | null = null; // used when the browser refuses sessionStorage

export function getKey(): string | null {
  try { return sessionStorage.getItem(KEY) ?? memory; } catch { return memory; }
}
export function setKey(k: string | null) {
  memory = k;
  try { if (k) sessionStorage.setItem(KEY, k); else sessionStorage.removeItem(KEY); } catch { /* memory only */ }
  window.dispatchEvent(new Event("sf-fleet-key"));
}

export class FleetError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(method: "GET" | "POST", url: string, body?: unknown, key = getKey()): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method, cache: "no-store",
      headers: { Authorization: `Bearer ${key ?? ""}`, ...(method === "POST" ? { "Content-Type": "application/json" } : {}) },
      body: method === "POST" ? JSON.stringify(body ?? {}) : undefined,
    });
  } catch {
    throw new FleetError("The server is not reachable.", 0);
  }
  if (res.status === 401 && key === getKey()) setKey(null); // the key was withdrawn: back to the sign-in page
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail ?? ""; } catch { /* not JSON */ }
    throw new FleetError(detail || `The server answered ${res.status}.`, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  /** Tries a key before it is kept. */
  check: (key: string) => request<Devices>("GET", "/api/v1/devices", undefined, key),
  devices: () => request<Devices>("GET", "/api/v1/devices"),
  fleet: () => request<Fleet>("GET", "/api/v1/fleet"),
  device: (id: string) => request<DeviceDetail>("GET", `/api/v1/devices/${encodeURIComponent(id)}`),
  software: () => request<Software>("GET", "/api/v1/software"),
  report: (id?: string) => request<{ text: string; generated_at: string }>("GET", id ? `/api/v1/devices/${encodeURIComponent(id)}/report` : "/api/v1/report"),
  audit: () => request<{ entries: AuditEntry[] }>("GET", "/api/v1/audit"),
  declare: (key: string, answer: Answer, note: string) => request<{ ok: boolean }>("POST", "/api/v1/declarations", { key, answer, note }),
  accept: (id: string, check_id: string, reason: string) =>
    request<{ ok: boolean }>("POST", `/api/v1/devices/${encodeURIComponent(id)}/exceptions`, { check_id, reason }),
};

/* ---- what the server answers ---- */
export type CheckStatus = "pass" | "fail" | "warn" | "unknown" | "info";
export type AreaStatus = Exclude<CheckStatus, "info">;
export type Answer = "yes" | "no" | "na" | null;

export interface Check {
  id: string; title: string; status: CheckStatus; detail: string; evidence: string[]; fix: string | null; to: string | null;
  accepted: { reason: string; ts: string; actor?: string } | null;
}
export interface Control {
  key: string; title: string; about: string; status: AreaStatus; checks: Check[];
  counts: Record<AreaStatus, number>; accepted: number;
}
export interface ComplianceSummary { controls_passing: number; controls: number; fail: number; warn: number; unknown: number; passed: number; accepted: number }
export interface Compliance { controls: Control[]; summary: ComplianceSummary; thresholds: Record<string, number> }

export interface Cve {
  id: string; published: string; score: number | null; severity: string; summary: string; fixed_in: string | null;
  kev: boolean; kev_added: string | null; ransomware: boolean;
}
export interface FlawApp {
  name: string; version: string | null; judged_version: string | null; publisher: string | null; available: string | null;
  update_to: string | null; products: string[]; cves: Cve[]; unversioned: number;
}
export interface FlawService {
  name: string; service: string | null; running: boolean; start: string | null; account: string | null; product: string | null;
  version: string | null; exposed: boolean; app_name: string | null; ports: { port: number; network: boolean }[];
  products: string[]; cves: Cve[]; unversioned: number;
}
export interface SecuritySummary {
  apps_affected: number; cves: number; kev: number; critical: number; fix_available: number;
  services: number; services_exposed: number; services_affected: number;
}
export interface Flaws { installed: number; recognised: number; apps: FlawApp[]; services: FlawService[]; summary: SecuritySummary }
export interface SupportProgram { name: string; version: string | null; product: string; line: string | null; state: "ended" | "soon" | "supported" | "unknown"; until: string | null; latest: string | null }
export interface Support { programs: SupportProgram[] | null; installed: number; windows: { state: string; line: string | null; until: string | null } | null }

export interface Judgement {
  compliance: ComplianceSummary & { areas: Record<string, AreaStatus> };
  failing: { id: string; title: string; control: string }[];
  security: (SecuritySummary & { installed: number; recognised: number; exploited: { program: string; version: string | null; cve: string; fix: string | null }[] }) | null;
  support: { windows: string | null; windows_until: string | null; ended: string[]; soon: string[] } | null;
}
export interface DeviceSummary {
  windows?: string; model?: string; programs?: number; updates?: number; services?: number; services_exposed?: number;
  firewall?: "on" | "off" | "partly" | null; ports_open?: number; antivirus?: boolean | null; encrypted?: boolean | null; daily_admin?: boolean | null;
}
export interface DeviceRow {
  id: string; name: string; enrolled_at: string; last_seen: string | null; silent_seconds: number | null; agent_version: string;
  summary: DeviceSummary; judged_at: string | null; judgement: Judgement | null;
}
export interface Devices { organisation: string; generated_at: string; checkin_seconds: number; devices: DeviceRow[] }

export interface Reference {
  cve_synced_at: string | null; complete: boolean; cves: number; kev: number; eol_synced_at: string | null; eol_products: number;
  syncing: boolean; error: string | null;
}
export interface Declared { key: string; title: string; about: string; answer: Answer; note: string; ts: string | null }
export interface FleetDay { day: string; devices: number; all_passing: number; areas: Record<string, number> }
export interface Fleet {
  organisation: string; generated_at: string; devices: number; judged: number; all_passing: number; silent_hours: number;
  silent: { id: string; name: string; last_seen: string | null }[];
  areas: ({ key: string; title: string; about: string } & Record<AreaStatus, number>)[];
  failing: { id: string; title: string; control: string; devices: { id: string; name: string }[] }[];
  exploited: { device_id: string; device: string; program: string; version: string | null; cve: string; fix: string | null }[];
  unsupported: { device_id: string; device: string; windows: boolean; windows_until: string | null; programs: string[] }[];
  totals: { with_flaws: number; programs_with_flaws: number; exploited: number; critical: number; updates: number; accepted: number };
  history: FleetDay[]; reference: Reference; declared: Declared[]; thresholds: Record<string, number>; device_list: DeviceRow[];
}

export interface AppFact {
  name: string; version: string | null; publisher: string | null; kind: "desktop" | "packaged"; from_store?: boolean; scope?: string; arch?: string;
  installed: string | null; date_is?: string; size: number | null; available: string | null; update_to: string | null;
}
export interface NetworkFact {
  firewall: { name: string; enabled: boolean; inbound: string | null; outbound: string | null }[]; other_firewalls: string[];
  interfaces: { kind: string | null; up: boolean; internet: boolean | null; category: string | null }[];
  listening: { proto: string; port: number; process: string | null; reach: string; windows: boolean }[];
  shared_folders: number; rules: { total: number; windows: number; programs: number; left_over: number; any_program_any_port: number } | null;
}
export interface DeviceDetail extends DeviceRow {
  snapshots: {
    device?: { received_at: string; payload: Record<string, string> };
    apps?: { received_at: string; payload: { apps: AppFact[] } };
    services?: { received_at: string; payload: { services: unknown[] } };
    network?: { received_at: string; payload: NetworkFact };
    posture?: { received_at: string; payload: Record<string, unknown> };
  };
  history: { kind: string; versions: number; first: string; last: string }[];
  compliance: Compliance | null; flaws: Flaws | null; support: Support | null;
  compliance_history: { day: string; controls: Record<string, AreaStatus>; checks: Record<string, string> }[];
  reference: Reference;
}

export interface SoftwareItem {
  name: string; publisher: string; kind: string; devices: number; cves: number; exploited: number; ended: boolean; newer: string | null;
  versions: { version: string; devices: { id: string; name: string }[] }[];
}
export interface Software { devices: number; programs: SoftwareItem[] }
export interface AuditEntry { at: string; actor: string; action: string; detail: Record<string, unknown> }
