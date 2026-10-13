/* The single gateway to the fleet server. A signed-in person is known by a cookie the page itself cannot read
   (HttpOnly); nothing that opens a door is kept in the page or in browser storage. A request that changes
   something also carries the console's own header, which a page on another site cannot add. */

export class FleetError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

/** Fired when the server no longer knows this browser (signed out, idle too long, switched off). */
export const SESSION_ENDED = "sf-fleet-session-ended";

async function request<T>(method: "GET" | "POST", url: string, body?: unknown, opts: { share?: string; quiet?: boolean } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, {
      method, cache: "no-store", credentials: "same-origin",
      headers: {
        ...(method === "POST" ? { "Content-Type": "application/json", "X-Fleet-Console": "1" } : {}),
        ...(opts.share ? { Authorization: `Share ${opts.share}` } : {}),
      },
      body: method === "POST" ? JSON.stringify(body ?? {}) : undefined,
    });
  } catch {
    throw new FleetError("The server is not reachable.", 0);
  }
  if (res.status === 401 && !opts.share && !opts.quiet) window.dispatchEvent(new Event(SESSION_ENDED));
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail ?? ""; } catch { /* not JSON */ }
    throw new FleetError(detail || `The server answered ${res.status}.`, res.status);
  }
  return (await res.json()) as T;
}

const id = encodeURIComponent;
const quiet = { quiet: true };

export const api = {
  // signing in
  me: () => request<Me>("GET", "/api/v1/auth/me", undefined, quiet),
  login: (email: string, password: string) => request<{ stage: Stage }>("POST", "/api/v1/auth/login", { email, password }, quiet),
  code: (code: string) => request<{ stage: Stage; recovery_left?: number }>("POST", "/api/v1/auth/mfa", { code }, quiet),
  secondFactor: () => request<{ secret: string; uri: string; qr: string; email: string }>("GET", "/api/v1/auth/mfa/setup", undefined, quiet),
  confirmSecondFactor: (code: string) => request<{ stage: Stage; recovery_codes: string[] }>("POST", "/api/v1/auth/mfa/setup", { code }, quiet),
  logout: () => request<{ ok: boolean }>("POST", "/api/v1/auth/logout", {}, quiet),
  setupCheck: (token: string) => request<{ email: string; min_password: number }>("POST", "/api/v1/auth/setup/check", { token }, quiet),
  setup: (token: string, password: string) => request<{ ok: boolean; email: string }>("POST", "/api/v1/auth/setup", { token, password }, quiet),
  changePassword: (current: string, next: string) => request<{ ok: boolean }>("POST", "/api/v1/auth/password", { current, new: next }),
  // the fleet
  devices: () => request<Devices>("GET", "/api/v1/devices"),
  fleet: () => request<Fleet>("GET", "/api/v1/fleet"),
  device: (d: string) => request<DeviceDetail>("GET", `/api/v1/devices/${id(d)}`),
  software: () => request<Software>("GET", "/api/v1/software"),
  report: (d?: string) => request<{ text: string; generated_at: string }>("GET", d ? `/api/v1/devices/${id(d)}/report` : "/api/v1/report"),
  audit: () => request<{ entries: AuditEntry[] }>("GET", "/api/v1/audit"),
  declare: (key: string, answer: Answer, note: string) => request<{ ok: boolean }>("POST", "/api/v1/declarations", { key, answer, note }),
  accept: (d: string, check_id: string, reason: string) => request<{ ok: boolean }>("POST", `/api/v1/devices/${id(d)}/exceptions`, { check_id, reason }),
  removeDevice: (d: string) => request<{ ok: boolean }>("POST", `/api/v1/devices/${id(d)}/remove`),
  // who has access
  access: () => request<Access>("GET", "/api/v1/access"),
  addUser: (email: string, name: string, role: Role) => request<{ ok: boolean; setup_token: string; valid_days: number }>("POST", "/api/v1/users", { email, name, role }),
  changeUser: (u: string, action: UserAction, role?: Role) => request<{ ok: boolean; setup_token?: string; valid_days?: number }>("POST", `/api/v1/users/${id(u)}`, { action, role }),
  addShareLink: (label: string, days: number) => request<{ ok: boolean; share_token: string; days: number }>("POST", "/api/v1/share-links", { label, days }),
  revokeShareLink: (l: string) => request<{ ok: boolean }>("POST", `/api/v1/share-links/${id(l)}/revoke`),
  addEnrolmentToken: (label: string, uses: number, days: number) => request<{ ok: boolean; enrolment_token: string; uses: number; days: number }>("POST", "/api/v1/tokens", { label, uses, days }),
  // what a share link shows
  shared: (token: string) => request<Shared>("GET", "/api/v1/shared", undefined, { share: token }),
};

export type Stage = "ok" | "mfa" | "mfa_setup";
export type Role = "auditor" | "admin" | "owner";
export type UserAction = "role" | "disable" | "enable" | "reset_password" | "reset_second_factor";
export interface Me { stage: Stage; email: string; name?: string; role?: Role; organisation?: string }
export interface Person {
  id: string; email: string; name: string; role: Role; disabled: boolean; second_factor: boolean; has_password: boolean; locked: boolean;
  created_at: string; last_login: string | null;
}
export interface ShareLink {
  id: string; label: string; created_by: string; created_at: string; expires_at: string; opened: number; last_opened: string | null;
  state: "active" | "expired" | "withdrawn";
}
export interface Access {
  me: { email: string | null; name: string; role: Role; id: string | null };
  users: Person[]; share_links: ShareLink[];
  enrolment_tokens: { id: string; label: string; uses_left: number; expires_at: string }[];
  organisation_keys: number; agent_release: string | null; roles: Role[]; setup_days: number; session_hours: number;
}
export interface Shared {
  organisation: string; label: string; expires_at: string; generated_at: string; devices: number; judged: number; all_passing: number;
  areas: ({ key: string; title: string; about: string } & Record<AreaStatus, number>)[];
  device_list: { id: string; name: string; windows: string | null; model: string; last_seen: string | null; judged_at: string | null;
    compliance: Compliance | null; security: Judgement["security"] }[];
  declared: Declared[]; text: string;
}

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
