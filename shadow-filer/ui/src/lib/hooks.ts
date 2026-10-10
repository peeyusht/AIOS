import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/** Fetch + optional polling. Keeps last good data on error. */
export function usePoll<T>(fn: () => Promise<T>, intervalMs: number | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const seq = useRef(0);

  const reload = useCallback(async () => {
    const my = ++seq.current;
    try {
      const d = await fnRef.current();
      if (my === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (my === seq.current) setError(e as Error);
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!intervalMs) return;
    const t = setInterval(reload, intervalMs);
    return () => clearInterval(t);
  }, [intervalMs, reload]);

  return { data, error, loading, reload, setData };
}

/* --- tiny hash router --- */
const subscribe = (cb: () => void) => {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
};
const getHash = () => window.location.hash.replace(/^#/, "") || "/inbox";

export function useHashPath() {
  return useSyncExternalStore(subscribe, getHash, () => "/inbox");
}

export let navigationGuard: (() => boolean) | null = null;
export function setNavigationGuard(g: (() => boolean) | null) { navigationGuard = g; }

export function navigate(path: string) {
  window.location.hash = path;
}

export function useDebounced<T>(v: T, ms: number) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}
