/* The single gateway to the Shadow Filer agent. Falls back to in-memory mock data when no token is present. */
import { adaptCleanup, adaptHistory, adaptLog, adaptMoves, adaptPredictions, adaptSearchStatus, adaptSystem } from "./adapt";
import type {
  AutofileResponse, DashboardResponse, Decision, NetworkResponse, LibraryKind, LibraryResponse, FsCheck, FsDirs, InboxResponse, JournalResponse, OkResponse,
  FileTicket, PreviewResponse, Raw, SaveResponse, RemedyResponse, SearchResponse, SecurityResponse, SettingsResponse, Stats, Status, WatchResponse,
} from "./types";

function readToken(): string | null {
  if (typeof document === "undefined") return null;
  const t = document.querySelector('meta[name="shadow-token"]')?.getAttribute("content");
  return t && t !== "__TOKEN__" ? t : null;
}

export const isMock = () => readToken() === null;

export class ApiError extends Error {
  constructor(message: string, public status: number, public kind: "stale" | "http" | "network") {
    super(message);
  }
}

type Listener = (state: { reachable: boolean; stale: boolean }) => void;
const listeners = new Set<Listener>();
const conn = { reachable: true, stale: false };
export function onConnection(l: Listener) {
  listeners.add(l);
  l(conn);
  return () => void listeners.delete(l);
}
function setConn(p: Partial<typeof conn>) {
  const next = { ...conn, ...p };
  if (next.reachable === conn.reachable && next.stale === conn.stale) return;
  Object.assign(conn, next);
  listeners.forEach((l) => l(conn));
}

async function request<T>(method: "GET" | "POST", url: string, body?: Raw): Promise<T> {
  if (isMock()) {
    const { mockFetch, MockHttpError } = await import("./mock");
    try {
      const r = (await mockFetch(method, url, body)) as T;
      setConn({ reachable: true });
      return r;
    } catch (e) {
      if (e instanceof MockHttpError) throw new ApiError(`Not found: ${url}`, e.status, "http");
      setConn({ reachable: false });
      throw new ApiError("Agent not reachable", 0, "network");
    }
  }
  let res: Response;
  try {
    res =
      method === "GET"
        ? await fetch(url, { cache: "no-store" })
        : await fetch(url, {
            method: "POST",
            cache: "no-store",
            headers: { "Content-Type": "application/json", "X-Shadow-Token": readToken() ?? "" },
            body: JSON.stringify(body ?? {}),
          });
  } catch {
    setConn({ reachable: false });
    throw new ApiError("Agent not reachable", 0, "network");
  }
  setConn({ reachable: true });
  if (res.status === 403) {
    setConn({ stale: true });
    throw new ApiError("This page is out of date. Reload.", 403, "stale");
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j?.error || j?.message) msg = j.error ?? j.message; // refusals arrive as {ok:false, message}
    } catch { /* ignore */ }
    throw new ApiError(msg, res.status, "http");
  }
  return (await res.json()) as T;
}

const qs = (o: Record<string, string | number | undefined>) =>
  "?" + Object.entries(o).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");

const g = <T,>(url: string) => request<T>("GET", url);
const p = <T = OkResponse,>(url: string, body: Raw = {}) => request<T>("POST", url, body);

export const api = {
  dashboard: () => g<DashboardResponse>("/api/dashboard"),
  network: (refresh = false) => g<NetworkResponse>("/api/network" + (refresh ? "?refresh=1" : "")),
  status: () => g<Status>("/api/status"),
  inbox: (offset = 0, limit = 25) => g<InboxResponse>("/api/inbox" + qs({ offset, limit })),
  fileIt: (path: string, folder: string, size: number) =>
    p<OkResponse & { id?: number; dest?: string; renamed?: boolean }>("/api/inbox/file", { path, folder, size }),
  mkdir: (parent: string, name: string) => p<OkResponse & { folder?: string }>("/api/inbox/mkdir", { parent, name }),
  dismiss: (path: string) => p("/api/inbox/dismiss", { path }),
  undo: (id: number) => p<OkResponse & { restored?: string }>("/api/moves/undo", { id }),
  moves: () => g<Raw>("/api/moves").then(adaptMoves),
  autofile: () => g<AutofileResponse>("/api/autofile"),
  settings: () => g<SettingsResponse>("/api/settings"),
  saveSettings: (raw: Raw) => p<SaveResponse>("/api/settings", { raw }),
  config: () => g<{ text: string }>("/api/config"),
  saveConfig: (text: string) => p<SaveResponse>("/api/config", { text }),
  restart: () => p("/api/restart", {}),
  search: (q: string, scope: string, types: string) => g<SearchResponse>("/api/search" + qs({ q, scope, types })),
  searchStatus: () => g<Raw>("/api/search/status").then(adaptSearchStatus),
  searchOpen: (path: string) => p("/api/search/open", { path }),
  preview: (path: string) => p<PreviewResponse>("/api/search/preview", { path }),
  fileTicket: (path: string) => p<FileTicket>("/api/file/ticket", { path }),
  searchReveal: (path: string) => p("/api/search/reveal", { path }),
  rebuildIndex: () => p("/api/search/rebuild", {}),
  cleanup: () => g<Raw>("/api/cleanup").then(adaptCleanup),
  cleanupHistory: () => g<Raw>("/api/cleanup/history").then(adaptHistory),
  scan: () => p("/api/cleanup/scan", {}),
  reveal: (path: string) => p("/api/cleanup/reveal", { path }),
  decide: (path: string, decision: Decision) => p("/api/cleanup/decision", { path, decision }),
  deleteRecycle: () => p("/api/cleanup/delete", { mode: "recycle" }),
  deletePermanent: (paths: string[]) => p("/api/cleanup/delete", { mode: "permanent", paths, confirm: "DELETE PERMANENTLY" }),
  openRecycleBin: () => p("/api/cleanup/recyclebin", {}),
  recycleSelftest: () => p("/api/cleanup/selftest", {}),
  ocrSelftest: () => p("/api/ocr/selftest", {}),
  stats: () => g<Stats>("/api/stats"),
  predictions: (view: string, q: string) => g<Raw>("/api/predictions" + qs({ view, q, limit: 500 })).then(adaptPredictions),
  log: () => g<Raw>("/api/log?lines=300").then(adaptLog),
  fsCheck: (path: string) => g<FsCheck>("/api/fs/check" + qs({ path })),
  fsDirs: (path: string) => g<FsDirs>("/api/fs/dirs" + qs({ path })),
  watch: (refresh = false) => g<WatchResponse>("/api/watch" + (refresh ? "?refresh=1" : "")),
  watchDismiss: (path: string, kind: "date" | "sensitive", key: string, undo = false) =>
    p("/api/watch/dismiss", undo ? { path, kind, key, undo: true } : { path, kind, key }),
  library: () => g<LibraryResponse>("/api/library"),
  libraryScan: () => p("/api/library/scan", {}),
  libraryCheckUpdates: () => p("/api/library/check-updates", {}),
  libraryDismiss: (kind: LibraryKind, key: string, undo = false) =>
    p("/api/library/dismiss", undo ? { kind, key, undo: true } : { kind, key }),
  libraryRestore: () => p("/api/library/restore", {}),
  libraryReveal: (path: string) => p("/api/library/reveal", { path }),
  security: (brief = false) => g<SecurityResponse>("/api/security" + (brief ? "?brief=1" : "")),
  securityCheck: () => p("/api/security/check", {}),
  securityHide: (kind: "app" | "service", key: string, undo = false) =>
    p("/api/security/hide", undo ? { kind, key, undo: true } : { kind, key }),
  securityRestore: () => p("/api/security/restore", {}),
  remedy: () => g<RemedyResponse>("/api/remedy"),
  remedyUpdate: (id: string) => p("/api/remedy/update", { id, terms_accepted: true }),
  remedyStop: (id: string) => p("/api/remedy/stop-service", { id }),
  journal: (days = 30) => g<JournalResponse>("/api/journal?days=" + days),
  system: (refresh = false) => g<Raw>("/api/system" + (refresh ? "?refresh=1" : "")).then(adaptSystem),
};

export const cleanupCsvUrl = "/api/cleanup.csv";
