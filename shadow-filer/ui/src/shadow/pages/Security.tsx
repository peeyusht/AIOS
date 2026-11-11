import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, Copy, EyeOff, Network, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import type { SecApp, SecCve, SecService, SecurityResponse } from "@/lib/types";
import { Card, EmptyState, ListSkeleton, LoadError, Mono, Notice, Segmented, SegTabs, Chip, Spin, Tip, WorkBar, act } from "../ui";
import { emitSecurityChanged } from "../App";
import { RemedyBar, StopButton, UpdateButton } from "../remedy";

const FIRST = 3; // CVEs shown per program before "Show all"

function cmpVersion(a: string, b: string) {
  const pa = a.split(/[^0-9]+/).filter(Boolean).map(Number), pb = b.split(/[^0-9]+/).filter(Boolean).map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const c = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (c) return c;
  }
  return 0;
}
function day(s: string | null | undefined) {
  if (!s) return "";
  const d = new Date(s.length === 10 ? s + "T00:00:00" : s);
  return isNaN(d.getTime()) ? s : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
const scoreTone = (n: number | null) => (n == null ? "muted" : n >= 9 ? "danger" : n >= 7 ? "warning" : "muted") as "muted" | "danger" | "warning";

function copyUpgrade(id: string) {
  try {
    void navigator.clipboard?.writeText(`winget upgrade --id ${id}`).then(() => toast.success("Command copied. Paste it into a terminal to update."), () => {});
  } catch { /* fall back silently */ }
}

export function SecurityPage() {
  const [running, setRunning] = useState(false);
  const q = usePoll<SecurityResponse>(() => api.security(), running ? 2000 : 300_000);
  const d = q.data;
  const wasRunning = useRef(false);
  useEffect(() => {
    const r = !!d?.runner.running;
    setRunning(r);
    if (wasRunning.current && !r) { void q.reload(); emitSecurityChanged(); }
    wasRunning.current = r;
  }, [d?.runner.running]); // eslint-disable-line react-hooks/exhaustive-deps

  const check = async () => {
    if (await act(() => api.securityCheck())) { setRunning(true); await q.reload(); }
  };
  const hide = async (kind: "app" | "service", key: string, name: string) => {
    if (!(await act(() => api.securityHide(kind, key)))) return;
    await q.reload(); emitSecurityChanged();
    toast(`Hidden ${name}`, {
      action: {
        label: "Undo",
        onClick: async () => { if (await act(() => api.securityHide(kind, key, true))) { await q.reload(); emitSecurityChanged(); } },
      },
    });
  };
  const restore = async () => { if (await act(() => api.securityRestore())) { await q.reload(); emitSecurityChanged(); } };

  const isRunning = !!d?.runner.running;
  const checkBtn = (
    <Button variant="outline" onClick={check} disabled={isRunning}>{isRunning ? <Spin /> : <RefreshCw />} Check now</Button>
  );
  const db = d?.database, s = d?.summary;
  const apps = d?.apps ?? [], services = d?.services ?? [];
  const notJudged = (d?.installed ?? 0) - (d?.recognised ?? 0);

  const [view, setView] = useState<"flaws" | "programs" | "services">("flaws");
  const [filter, setFilter] = useState<Filter>("all");
  const rows = useMemo<Row[]>(() => apps.flatMap((app) => {
    const exposed = services.filter((x) => x.app_id === app.id && x.exposed);
    return app.cves.map((cve) => ({ cve, app, exposed }));
  }).sort((a, b) => Number(b.cve.kev) - Number(a.cve.kev) || (b.cve.score ?? 0) - (a.cve.score ?? 0) || a.cve.id.localeCompare(b.cve.id)), [apps, services]);
  const ready = !!(d && d.enabled && d.scanned_at && s);
  const remediate = !!d?.settings.remediate;
  const notes = !d || !d.enabled || !d.scanned_at || remediate || !!d.runner.error || !!db?.error;

  return (
    <div className="flex flex-1 flex-col text-[13px]">
      <WorkBar title="Security">
        {ready && view === "flaws" && rows.length > 0 && (
          <div role="group" aria-label="Filter flaws" className="flex flex-wrap gap-1.5">
            {(Object.keys(TEST) as Filter[]).map((f) => {
              const n = rows.filter(TEST[f]).length;
              return <Chip key={f} on={filter === f} danger={f === "kev"} n={n} disabled={n === 0 && f !== "all"} onClick={() => setFilter(f)}>{FILTER_LABEL[f]}</Chip>;
            })}
          </div>
        )}
        <span className="flex-1" />
        {d && d.enabled && (
          <span className="inline-flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
            {isRunning
              ? <span className="inline-flex items-center gap-1.5 [&_svg]:size-3.5"><Spin /> {d.runner.progress ?? "Checking…"}</span>
              : d.scanned_at && <>checked {when(d.scanned_at)}</>}
            <Button variant="outline" size="sm" onClick={check} disabled={isRunning}>{isRunning ? <Spin /> : <RefreshCw />} Check now</Button>
          </span>
        )}
        {ready && s && (
          <SegTabs label="View" value={view} onChange={setView} options={[
            { value: "flaws", label: <>Flaws <span className="font-mono text-muted-foreground">{s.cves}</span></> },
            { value: "programs", label: <>Programs <span className={cn("font-mono", s.kev > 0 ? "text-destructive" : s.apps_affected > 0 ? "text-warning" : "text-muted-foreground")}>{s.apps_affected}</span></> },
            { value: "services", label: <>Services <span className={cn("font-mono", s.services_exposed > 0 ? "text-warning" : "text-muted-foreground")}>{s.services}</span></> },
          ]} />
        )}
      </WorkBar>

      {notes && (
        <div className="space-y-3 px-6 pt-4 empty:hidden">
          {q.error && !d && <LoadError error={q.error} onRetry={q.reload} />}
          {!d && !q.error && <ListSkeleton rows={4} />}
          {d && !d.enabled && (
            <EmptyState icon={<ShieldAlert />} title="The vulnerability check is switched off">
              It keeps a copy of the public CVE list on this PC, which means downloading it. Turn it on in{" "}
              <a href="#/settings" className="text-primary underline-offset-4 hover:underline">Settings › Security</a>.
            </EmptyState>
          )}
          {d && d.enabled && remediate && <RemedyBar onDone={() => { void q.reload(); emitSecurityChanged(); }} />}
          {d && d.enabled && d.runner.error && <Notice tone="danger">{d.runner.error}</Notice>}
          {d && d.enabled && db?.error && (
            <Notice tone="warn">
              The last download of the CVE list had a problem: {db.error}
              {db.synced_at ? ` The list from ${when(db.synced_at)} is used.` : ""}
            </Notice>
          )}
          {d && d.enabled && !d.scanned_at && !isRunning && (
            <EmptyState icon={<ShieldAlert />} title="Nothing compared yet">
              The first check downloads the CVE list (about 300 MB) and takes several minutes. Use Check now above.
            </EmptyState>
          )}
        </div>
      )}

      {ready && d && view === "flaws" && (
        <Flaws rows={rows} filter={filter} remediate={remediate} onHide={(a) => hide("app", a.key || a.id, a.name)}
          footer={
            <>
              <span className="font-mono">coverage {d.recognised ?? 0}/{d.installed ?? 0} programs</span>
              <span role="img" aria-label={`${d.recognised ?? 0} of ${d.installed ?? 0} programs compared`} className="h-1.5 w-40 overflow-hidden rounded-full bg-border">
                <span className="block h-full bg-primary" style={{ width: `${d.installed ? Math.round(((d.recognised ?? 0) / d.installed) * 100) : 0}%` }} />
              </span>
              <span className="min-w-0 flex-[1_1_320px]">
                {notJudged > 0 ? `The other ${notJudged} match no product in the list: unknown, not safe. ` : ""}
                Windows itself and Store apps are not judged. A match can still be wrong; Hide removes it.
              </span>
              <span className="w-full font-mono text-[11px]">
                {(db?.cves ?? 0).toLocaleString()} CVEs, {(db?.kev ?? 0).toLocaleString()} known exploited
                {db?.synced_at ? ` · list updated ${when(db.synced_at)}` : " · not downloaded yet"} · every {d.settings.cve_hours} h from nvd.nist.gov and cisa.gov · compared on this PC, nothing sent
                {(d.hidden ?? 0) > 0 && <> · {d.hidden} hidden, <button className="text-primary underline-offset-4 hover:underline" onClick={restore}>show them again</button></>}
              </span>
            </>
          } />
      )}
      {ready && d && view !== "flaws" && (
        <div className="space-y-4 px-6 py-5">
          {view === "programs" && <Programs apps={apps} remediate={remediate} onHide={(a) => hide("app", a.key || a.id, a.name)} />}
          {view === "services" && <Services services={services} read={d.services_read !== false} remediate={remediate} onHide={(x) => hide("service", x.id, x.name)} />}
          {(d.hidden ?? 0) > 0 && (
            <p className="text-sm text-muted-foreground">{d.hidden} hidden · <button className="text-primary underline-offset-4 hover:underline" onClick={restore}>Show them again</button></p>
          )}
        </div>
      )}
    </div>
  );
}

const HideBtn = ({ onClick, tip }: { onClick: () => void; tip: string }) => (
  <Tip tip={tip}><Button variant="ghost" size="sm" onClick={onClick}><EyeOff /> Hide</Button></Tip>
);

type Row = { cve: SecCve; app: SecApp; exposed: SecService[] };
type Filter = "all" | "kev" | "critical" | "network" | "update";
const TEST: Record<Filter, (r: Row) => boolean> = {
  all: () => true, kev: (r) => r.cve.kev, critical: (r) => (r.cve.score ?? 0) >= 9,
  network: (r) => r.exposed.length > 0, update: (r) => !!r.app.available,
};
const FILTER_LABEL: Record<Filter, string> = { all: "All", kev: "Exploited", critical: "Critical", network: "Open to network", update: "Has an update" };

/** Every known flaw across the compared programs in one table, worst first, with the selected one explained beside it. */
function Flaws({ rows, filter, remediate, onHide, footer }: { rows: Row[]; filter: Filter; remediate: boolean; onHide: (a: SecApp) => void; footer: ReactNode }) {
  const list = rows.filter(TEST[filter]);
  const [sel, setSel] = useState<string | null>(null);
  const cur = list.find((r) => r.cve.id + r.app.id === sel) ?? list[0] ?? null;
  return (
    <div className="flex flex-1 flex-wrap items-stretch">
      <section aria-label="Flaws" className="flex min-w-0 flex-[999_1_600px] flex-col">
        {rows.length === 0 ? (
          <div className="p-6"><EmptyState icon={<ShieldCheck />} title="No known flaws in the installed versions">The programs that could be compared have nothing known for their versions.</EmptyState></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px]">
              <thead><tr className="label-caps bg-sidebar text-left text-muted-foreground">
                <th className="py-2.5 pl-6 pr-2 font-medium">CVSS</th><th className="px-2 py-2.5 font-medium">CVE</th><th className="px-2 py-2.5 font-medium">Program</th>
                <th className="px-2 py-2.5 font-medium">Signals</th><th className="px-2 py-2.5 font-medium">Published</th><th className="py-2.5 pl-2 pr-6 font-medium">Fixed in</th>
              </tr></thead>
              <tbody>
                {list.map((r) => {
                  const on = cur === r;
                  return (
                    <tr key={r.cve.id + r.app.id} onClick={() => setSel(r.cve.id + r.app.id)}
                      className={cn("cursor-pointer border-t", on ? "bg-accent shadow-[inset_2px_0_0_var(--color-primary)]" : "hover:bg-muted/40")}>
                      <td className="py-2 pl-6 pr-2"><ScoreBox n={r.cve.score} /></td>
                      <td className="whitespace-nowrap px-2 py-2">
                        <button className="font-mono text-xs underline-offset-2 hover:underline" aria-pressed={on} onClick={(e) => { e.stopPropagation(); setSel(r.cve.id + r.app.id); }}>{r.cve.id}</button>
                      </td>
                      <td className="px-2 py-2"><span className="font-medium">{r.app.name}</span> <span className="font-mono text-[11px] text-muted-foreground">{r.app.judged_version}</span></td>
                      <td className="whitespace-nowrap px-2 py-2 font-mono text-[11px]">
                        {r.cve.kev && <span className="mr-1.5 text-destructive">KEV</span>}
                        {r.cve.ransomware && <span className="mr-1.5 text-destructive">RANSOM</span>}
                        {r.exposed.length > 0 && <span className="text-warning">NET</span>}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 font-mono text-xs text-muted-foreground">{r.cve.published ? r.cve.published.slice(0, 10) : "—"}</td>
                      <td className="whitespace-nowrap py-2 pl-2 pr-6 font-mono text-xs">{r.cve.fixed_in ? <span className="text-success">{r.cve.fixed_in}</span> : <span className="text-muted-foreground">—</span>}{r.app.available && <span className="ml-1.5 text-muted-foreground" title={`Version ${r.app.available} is available`}>↑ {r.app.available}</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-auto flex flex-wrap items-center gap-x-5 gap-y-2 border-t px-6 py-3.5 text-xs text-muted-foreground">{footer}</div>
      </section>
      {cur && <FlawDetail r={cur} remediate={remediate} onHide={() => onHide(cur.app)} />}
    </div>
  );
}

function ScoreBox({ n }: { n: number | null }) {
  const tone = n == null ? "bg-muted text-muted-foreground" : n >= 9 ? "bg-danger-soft text-destructive" : n >= 7 ? "bg-warning-soft text-warning" : "bg-muted text-muted-foreground";
  return <span className={cn("inline-block min-w-10 rounded px-1.5 text-center font-mono text-xs font-semibold leading-5 tabular", tone)}>{n != null ? n.toFixed(1) : "—"}</span>;
}

function FlawDetail({ r, remediate, onHide }: { r: Row; remediate: boolean; onHide: () => void }) {
  const { cve, app, exposed } = r;
  return (
    <aside aria-label="Selected flaw" className="min-w-0 flex-[1_1_360px] border-l bg-sidebar p-5 max-[1000px]:border-l-0 max-[1000px]:border-t">
      <div className="space-y-3.5 min-[1000px]:sticky min-[1000px]:top-[72px]">
      <div className="flex flex-wrap gap-1.5">
        {cve.kev && <Badge variant="danger">Used in real attacks{cve.kev_added ? ` · listed ${day(cve.kev_added)}` : ""}</Badge>}
        {cve.ransomware && <Badge variant="danger">Used by ransomware</Badge>}
        <Badge variant={scoreTone(cve.score)}>{cve.severity ? cve.severity.toLowerCase() : "no score"}{cve.score != null && ` ${cve.score.toFixed(1)}`}</Badge>
      </div>
      <h3 className="select-all font-mono text-base font-semibold">{cve.id}</h3>
      <p className="text-sm leading-relaxed">{cve.summary || "No description."}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-muted-foreground">Program</dt><dd>{app.name} <span className="font-mono text-xs text-muted-foreground">{app.judged_version}</span></dd>
        {app.publisher && <><dt className="text-muted-foreground">Publisher</dt><dd>{app.publisher}</dd></>}
        <dt className="text-muted-foreground">Published</dt><dd className="font-mono text-xs leading-5">{cve.published ? cve.published.slice(0, 10) : "—"}</dd>
        <dt className="text-muted-foreground">Fixed in</dt><dd className="font-mono text-xs leading-5">{cve.fixed_in ?? "not stated"}</dd>
        <dt className="text-muted-foreground">Update</dt><dd>{app.available ? <>Version <span className="font-mono text-xs">{app.available}</span> is available{app.update_id ? " (winget)" : ""}</> : "No newer version listed"}</dd>
        {exposed.length > 0 && <><dt className="text-muted-foreground">Exposure</dt><dd>{exposed.map((s) => <span key={s.id} className="block">Service <b className="font-medium">{s.name}</b>{s.running ? ", running," : ""} open to the network on <span className="font-mono text-xs">{s.ports.filter((p) => p.network).map((p) => p.port).join(", ")}</span></span>)}</dd></>}
        <dt className="text-muted-foreground">Matched as</dt><dd className="font-mono text-xs leading-5">{app.products.join(", ")}</dd>
      </dl>
      <div className="flex flex-wrap items-center gap-2 border-t pt-4">
        {remediate && app.available && <UpdateButton app={app} />}
        {remediate && exposed.filter((s) => s.running).map((s) => <StopButton key={s.id} svc={s} />)}
        {app.update_id && <Button variant="outline" size="sm" onClick={() => copyUpgrade(app.update_id!)}><Copy /> Copy update command</Button>}
        <Tip tip="Not this product, or already dealt with"><Button variant="ghost" size="sm" onClick={onHide}><EyeOff /> Hide program</Button></Tip>
      </div>
      {!remediate && (app.available || exposed.length > 0) && <p className="text-xs text-muted-foreground">Update and Stop buttons appear when changes from the console are switched on in Settings.</p>}
      <p className="font-mono text-[11px] text-muted-foreground">Matched by product, maker and version range against the local copy of NVD and CISA's list.</p>
      </div>
    </aside>
  );
}

function Programs({ apps, onHide, remediate }: { apps: SecApp[]; onHide: (a: SecApp) => void; remediate: boolean }) {
  const [show, setShow] = useState<"flaws" | "all">("flaws");
  const list = useMemo(() => apps.filter((a) => show === "all" || a.cves.length > 0), [apps, show]);
  const clean = apps.filter((a) => a.cves.length === 0).length;
  return (
    <div className="space-y-4">
      <Segmented label="Show" value={show} onChange={setShow}
        options={[{ value: "flaws", label: "With known flaws" }, { value: "all", label: `All compared (${apps.length})` }]} />
      {list.length === 0 ? (
        <EmptyState icon={<ShieldCheck />} title="No known flaws in the installed versions">
          {clean > 0 ? `${clean} programs were compared and nothing matched their versions.` : "No program could be compared yet."}
        </EmptyState>
      ) : (
        <div className="space-y-3">{list.map((a) => <ProgramCard key={a.id} a={a} remediate={remediate} onHide={() => onHide(a)} />)}</div>
      )}
    </div>
  );
}

function ProgramCard({ a, onHide, remediate }: { a: SecApp; onHide: () => void; remediate: boolean }) {
  const kev = a.cves.filter((x) => x.kev).length;
  const critical = a.cves.filter((x) => (x.score ?? 0) >= 9).length;
  const fixes = a.cves.map((x) => x.fixed_in).filter((x): x is string => !!x);
  const top = fixes.length ? [...fixes].sort(cmpVersion).pop()! : null;
  const rest = a.cves.slice(FIRST);
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{a.name}</span>
        {a.judged_version && <Badge variant="muted" className="tabular">{a.judged_version}</Badge>}
        {kev > 0 && <Badge variant="danger">{kev} used in real attacks</Badge>}
        {critical > 0 && <Badge variant="warning">{critical} critical</Badge>}
        {a.cves.length === 0 && <Badge variant="success">Nothing known for this version</Badge>}
        <span className="ml-auto text-sm text-muted-foreground tabular">{a.cves.length > 0 && `${a.cves.length} ${a.cves.length === 1 ? "CVE" : "CVEs"}`}</span>
        <HideBtn onClick={onHide} tip="Not this product, or already dealt with" />
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {a.publisher && <span>{a.publisher}</span>}
        <Tip tip="The product name the CVE list uses"><span><Mono className="text-xs">{a.products.join(", ")}</Mono></span></Tip>
        {a.available ? (
          <span className="inline-flex items-center gap-1 text-foreground">
            Newer version available <Badge variant="info" className="tabular">{a.available}</Badge>
            {a.update_id && (
              <Button variant="ghost" size="icon" className="size-7 [&_svg]:size-3.5" aria-label="Copy the update command" title={`winget upgrade --id ${a.update_id}`} onClick={() => copyUpgrade(a.update_id!)}><Copy /></Button>
            )}
            {remediate && <UpdateButton app={a} />}
          </span>
        ) : top && a.cves.length > 0 ? (
          <span>Version {top} or later fixes {fixes.length} of {a.cves.length}</span>
        ) : null}
      </div>
      {a.cves.length > 0 && (
        <div className="mt-3">
          {a.cves.slice(0, FIRST).map((x) => <CveRow key={x.id} x={x} />)}
          {rest.length > 0 && (
            <Collapsible>
              <CollapsibleContent className="border-t">{rest.map((x) => <CveRow key={x.id} x={x} />)}</CollapsibleContent>
              <CollapsibleTrigger className="group mt-1 flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline">
                <span className="group-data-[state=open]:hidden">Show all {a.cves.length}</span>
                <span className="hidden group-data-[state=open]:inline">Show fewer</span>
                <ChevronDown className="size-3.5 transition-transform group-data-[state=open]:rotate-180" />
              </CollapsibleTrigger>
            </Collapsible>
          )}
        </div>
      )}
      {a.unversioned > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          {a.unversioned} more {a.unversioned === 1 ? "CVE names" : "CVEs name"} this product without saying which versions. They are not counted.
        </p>
      )}
    </Card>
  );
}

function CveRow({ x }: { x: SecCve }) {
  return (
    <div className="flex items-start gap-3 border-t py-2 text-sm first:border-t-0">
      <Mono className="w-36 shrink-0 select-all pt-0.5 text-xs">{x.id}</Mono>
      <span className="w-12 shrink-0">
        <Tip tip={x.severity ? `Severity: ${x.severity.toLowerCase()}` : "No severity score yet"}>
          <span><Badge variant={scoreTone(x.score)} className="tabular">{x.score != null ? x.score.toFixed(1) : "—"}</Badge></span>
        </Tip>
      </span>
      <div className="min-w-0 flex-1">
        <div>{x.summary || "No description."}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {x.kev && <Badge variant="danger">Used in real attacks{x.kev_added ? ` · listed ${day(x.kev_added)}` : ""}</Badge>}
          {x.ransomware && <Badge variant="danger">Used by ransomware</Badge>}
          {x.fixed_in && <span>Fixed in {x.fixed_in}</span>}
          {x.published && <span>Published {day(x.published)}</span>}
        </div>
      </div>
    </div>
  );
}

const ACCOUNT: Record<SecService["account"], { label: string; v: "warning" | "muted"; tip: string }> = {
  system: { label: "System", v: "warning", tip: "Runs with full control of this PC" },
  limited: { label: "Limited account", v: "muted", tip: "Runs as a restricted service account" },
  user: { label: "User account", v: "muted", tip: "Runs as a person's account" },
};

function Services({ services, read, onHide, remediate }: { services: SecService[]; read: boolean; onHide: (s: SecService) => void; remediate: boolean }) {
  const look = (s: SecService) => s.exposed || s.cves.length > 0;
  const [show, setShow] = useState<"look" | "running" | "all">(services.some(look) ? "look" : "running");
  const list = services.filter((s) => (show === "all" ? true : show === "running" ? s.running : look(s)));
  const Th = ({ children, className }: { children?: ReactNode; className?: string }) => (
    <th className={cn("px-2 py-2 font-medium first:px-4 last:px-4", className)}>{children}</th>
  );
  return (
    <div className="space-y-4">
      {!read && <Notice tone="warn">Windows could not be asked for the list of services this time.</Notice>}
      <Segmented label="Show" value={show} onChange={setShow}
        options={[{ value: "look", label: "Worth a look" }, { value: "running", label: "Running" }, { value: "all", label: `All (${services.length})` }]} />
      {show === "look" && <p className="text-sm text-muted-foreground">Services that accept connections from the network, or belong to a program with known flaws.</p>}
      {list.length === 0 ? (
        <EmptyState icon={<Network />} title={show === "look" ? "No service is open to the network or has known flaws." : "No services to show."} />
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b">
                <Th>Service</Th><Th>State</Th><Th>Runs as</Th><Th>Listens on</Th><Th>Belongs to</Th><Th>Known flaws</Th><Th><span className="sr-only">Actions</span></Th>
              </tr>
            </thead>
            <tbody>
              {list.map((x) => {
                const kev = x.cves.filter((c) => c.kev).length;
                const acc = ACCOUNT[x.account] ?? ACCOUNT.user;
                return (
                  <tr key={x.id} className="border-b align-top last:border-b-0">
                    <td className="max-w-[18rem] px-4 py-3">
                      <div className="truncate font-medium" title={x.service}>{x.name}</div>
                      <div className="path truncate text-xs text-muted-foreground" title={x.exe}>{x.exe}</div>
                      {(x.product || x.version) && <div className="text-xs text-muted-foreground">{[x.product, x.version].filter(Boolean).join(" ")}</div>}
                    </td>
                    <td className="px-2 py-3">
                      <Badge variant={x.running ? "success" : "muted"}>{x.running ? "Running" : "Stopped"}</Badge>
                      {x.start && <div className="mt-1 text-xs text-muted-foreground">Starts: {x.start}</div>}
                    </td>
                    <td className="px-2 py-3"><Tip tip={acc.tip}><span><Badge variant={acc.v}>{acc.label}</Badge></span></Tip></td>
                    <td className="px-2 py-3">
                      {x.ports.length === 0 ? <span className="text-muted-foreground">—</span> : (
                        <div className="flex flex-wrap gap-1.5">
                          {x.ports.map((p) => (
                            <Badge key={p.port} variant={p.network ? "warning" : "muted"} className="tabular">{p.port} · {p.network ? "network" : "this PC only"}</Badge>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="max-w-[14rem] px-2 py-3">{x.app_name ? <span className="line-clamp-2">{x.app_name}</span> : <span className="text-muted-foreground">—</span>}</td>
                    <td className="whitespace-nowrap px-2 py-3">
                      {x.cves.length === 0 ? <span className="text-muted-foreground">—</span> : (
                        <div className="flex flex-wrap gap-1.5">
                          <Badge variant={kev > 0 ? "danger" : "warning"} className="tabular">{x.cves.length} {x.cves.length === 1 ? "CVE" : "CVEs"}</Badge>
                          {kev > 0 && <Badge variant="danger">{kev} used in attacks</Badge>}
                        </div>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-right">
                      {remediate && <StopButton svc={x} />}
                      <HideBtn onClick={() => onHide(x)} tip="I know about this one" />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
