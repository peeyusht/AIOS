export function bytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB", "TB"];
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
}

export function when(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  const diff = (Date.now() - d.getTime()) / 60000;
  if (diff < 1) return "just now";
  if (diff < 60) return `${Math.round(diff)} min ago`;
  if (diff < 60 * 24) return `${Math.round(diff / 60)} h ago`;
  if (diff < 60 * 24 * 7) return `${Math.round(diff / 1440)} d ago`;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function dateTime(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  // a date from another year needs its year (BIOS date, Windows install date), and then the time is noise
  if (d.getFullYear() !== new Date().getFullYear()) return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const pct = (r: number | null | undefined, digits = 0) => (r == null ? "—" : `${(r * 100).toFixed(digits)}%`);

export const baseName = (p: string) => p.split(/[\\/]/).pop() ?? p;
