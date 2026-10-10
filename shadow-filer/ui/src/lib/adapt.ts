/* Turns the agent's real answers into the shapes the pages use (types.ts). Mock data already has those
   shapes, so api.ts applies these only to real responses. Each function tolerates either shape. */
import type {
  CleanupHistoryRow, CleanupResponse, LogResponse, MovesResponse, Prediction, Raw, SearchStatus, SystemInfo,
} from "./types";

const isObj = (v: unknown): v is Record<string, Raw> => typeof v === "object" && v !== null && !Array.isArray(v);

/** The agent answers some lists as a bare array. */
export function asRows<T>(r: Raw): { rows: T[] } {
  return Array.isArray(r) ? { rows: r as T[] } : { rows: (r?.rows ?? []) as T[] };
}
export const adaptHistory = (r: Raw) => asRows<CleanupHistoryRow>(r);
export const adaptPredictions = (r: Raw) => asRows<Prediction>(r);
export const adaptLog = (r: Raw): LogResponse => (Array.isArray(r) ? { lines: r as string[] } : { lines: r?.lines ?? [] });

export function adaptMoves(r: Raw): MovesResponse {
  const fb = r?.feedback ?? {};
  return {
    journal: r?.journal ?? [],
    feedback: { moves: 0, top_accepted: 0, auto_moves: 0, per_folder: [], ...fb, rate: fb.rate ?? 0 },
  };
}

const NO_PLAN = { recycle_count: 0, recycle_bytes: 0, too_big: [], limits: {} };

export function adaptCleanup(r: Raw): CleanupResponse {
  const rep = r?.report;
  const plan = isObj(r?.plan) && !r.plan.error ? { ...NO_PLAN, ...r.plan } : NO_PLAN;
  return {
    ...r,
    levels: r?.levels ?? {},
    plan,
    report: rep
      ? {
          ...rep,
          generated: rep.generated ?? rep.scanned_at ?? null,
          by_level: rep.by_level ?? {},
          items: rep.items ?? [],
          settings: rep.settings ?? {},
          errors: rep.errors ?? [],
          para_duplicates: rep.para_duplicates ?? [],
        }
      : null,
  };
}

export function adaptSearchStatus(r: Raw): SearchStatus {
  const off = !!r?.disabled;
  const o = r?.ocr ?? {};
  let message = typeof o.message === "string" ? o.message : "";
  if (!message) {
    if (o.windows === false) message = "Needs Windows";
    else if (o.enabled === false) message = "Off (Settings › OCR)";
    else if (o.available === false) message = `Unavailable: ${o.error ?? "unknown reason"}`;
    else if (o.engine) message = `Windows OCR (${o.engine}) · ${o.files ?? 0} file${o.files === 1 ? "" : "s"} read · ${Math.round(o.seconds ?? 0)} s`;
    else message = "Windows OCR · waiting for the first scanned file";
  }
  return {
    running: false, phase: off ? "Search is turned off in Settings" : null, done: 0, todo: 0, current: null,
    last_sweep: null, roots: [], by_status: {}, model: "", fts: false, db_bytes: 0, last_error: null, errors: [],
    ...r,
    model_ok: r?.model_ok !== false,
    ocr: { enabled: o.enabled !== false, available: o.available !== false && o.windows !== false, message },
  };
}

const join = (parts: unknown[], sep = " ") => parts.filter((p) => p !== null && p !== undefined && p !== "").join(sep);

export function adaptSystem(r: Raw): SystemInfo {
  if (typeof r?.os === "string") return r as SystemInfo; // already in page shape
  const os = r?.os ?? {}, pc = r?.computer ?? {}, cpu = r?.cpu ?? {}, mem = r?.memory ?? {}, ol = r?.ollama ?? {};
  return {
    os: join([os.name, os.version, os.build && `(build ${os.build})`]),
    computer: join([pc.manufacturer, pc.model, pc.name && `· ${pc.name}`]),
    cpu: join([cpu.name, cpu.cores && `· ${cpu.cores} cores`, cpu.threads && `/ ${cpu.threads} threads`]),
    memory: { installed: mem.installed_bytes ?? 0, free: mem.free_bytes ?? 0 },
    gpus: (r?.gpus ?? []).map((g: Raw) => ({
      name: g.name, vram_used: g.vram_used_bytes ?? 0, vram_total: g.vram_bytes ?? 0,
      temp: g.temp_c ?? null, util: g.util_pct ?? null,
    })),
    disks: (r?.volumes ?? []).map((v: Raw) => ({
      name: join([v.label, v.media && `(${v.media})`]) || v.letter, mount: v.letter, total: v.bytes ?? 0, free: v.free ?? 0,
    })),
    ollama: {
      reachable: !!ol.reachable, version: ol.version ?? null,
      loaded: (ol.loaded ?? []).map((m: Raw) => (typeof m === "string" ? m : join([m.name, m.gpu_pct != null && `(${m.gpu_pct}% on GPU)`]))),
    },
    notes: r?.notes ?? [],
  };
}
