import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, Copy, EyeOff, Network, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import type { SecApp, SecCve, SecService, SecurityResponse } from "@/lib/types";
import { Card, EmptyState, ListSkeleton, LoadError, Mono, Notice, PageHeader, Segmented, Spin, Tip, act } from "../ui";
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

  return (
    <div>
      <PageHeader
        title="Security"
        sub={
          <>
            Known vulnerabilities in the programs installed on this PC, and the background services that are not part of Windows.
            <span className="block">
              Compared on this PC. Nothing about what you have installed is sent anywhere; nothing is updated or stopped unless you click it.
            </span>
          </>
        }
        actions={
          d && d.enabled ? (
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">
                {isRunning
                  ? <span className="inline-flex items-center gap-1.5 [&_svg]:size-3.5"><Spin /> {d.runner.progress ?? "Checking…"}</span>
                  : d.scanned_at && <>Checked {when(d.scanned_at)}</>}
              </span>
              {checkBtn}
            </div>
          ) : undefined
        }
      />
      {q.error && !d && <LoadError error={q.error} onRetry={q.reload} />}
      {!d && !q.error && <ListSkeleton rows={4} />}
      {d && !d.enabled && (
        <EmptyState icon={<ShieldAlert />} title="The vulnerability check is switched off">
          It keeps a copy of the public CVE list on this PC, which means downloading it. Turn it on in{" "}
          <a href="#/settings" className="text-primary underline-offset-4 hover:underline">Settings › Security</a>.
        </EmptyState>
      )}
      {d && d.enabled && d.settings.remediate && <RemedyBar onDone={() => { void q.reload(); emitSecurityChanged(); }} />}
      {d && d.enabled && d.runner.error && <Notice tone="danger" className="mb-4">{d.runner.error}</Notice>}
      {d && d.enabled && db?.error && (
        <Notice tone="warn" className="mb-4">
          The last download of the CVE list had a problem: {db.error}
          {db.synced_at ? ` The list from ${when(db.synced_at)} is used.` : ""}
        </Notice>
      )}
      {d && d.enabled && !d.scanned_at && !isRunning && (
        <EmptyState icon={<ShieldAlert />} title="Nothing compared yet">
          The first check downloads the CVE list (about 300 MB) and takes several minutes.
          <div className="mt-3">{checkBtn}</div>
        </EmptyState>
      )}
      {d && d.enabled && d.scanned_at && s && (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-3 max-[1100px]:grid-cols-2">
            <Tile label="Used in real attacks" n={s.kev} tone={s.kev > 0 ? "text-destructive" : "text-foreground"} sub="on CISA's known-exploited list" />
            <Tile label="Critical" n={s.critical} tone={s.critical > 0 ? "text-warning" : "text-foreground"} sub="severity 9.0 or higher" />
            <Tile label="Programs with known flaws" n={s.apps_affected} tone="text-foreground" sub={`of ${d.recognised ?? 0} that could be compared`} />
            <Tile label="Services open to the network" n={s.services_exposed} tone={s.services_exposed > 0 ? "text-warning" : "text-foreground"} sub={`${s.services_running} of ${s.services} running`} />
          </div>
          <Notice>
            A program is listed only when its name, its maker and its installed version all match what a CVE states.
            {notJudged > 0 && <> {notJudged} of your {d.installed} programs match no product in the list: they are not judged, which is not the same as safe.</>}
            {" "}Windows itself and Store apps are not judged. A match can still be wrong; Hide removes it.
          </Notice>
          <Tabs defaultValue="programs">
            <TabsList className="mb-6">
              <TabsTrigger value="programs">Programs{s.apps_affected > 0 && <span className={cn("ml-1.5 tabular", s.kev > 0 ? "text-destructive" : "text-warning")}>{s.apps_affected}</span>}</TabsTrigger>
              <TabsTrigger value="services">Services<span className="ml-1.5 tabular text-muted-foreground">{s.services}</span></TabsTrigger>
            </TabsList>
            <TabsContent value="programs"><Programs apps={apps} remediate={!!d.settings.remediate} onHide={(a) => hide("app", a.key || a.id, a.name)} /></TabsContent>
            <TabsContent value="services">
              <Services services={services} read={d.services_read !== false} remediate={!!d.settings.remediate} onHide={(x) => hide("service", x.id, x.name)} />
            </TabsContent>
          </Tabs>
          <p className="text-sm text-muted-foreground">
            CVE list on this PC: {(db?.cves ?? 0).toLocaleString()} CVEs, {(db?.kev ?? 0).toLocaleString()} known exploited
            {db?.synced_at ? ` · updated ${when(db.synced_at)}` : " · not downloaded yet"} · refreshed every {d.settings.cve_hours} hours from nvd.nist.gov and cisa.gov
          </p>
        </div>
      )}
      {d && (d.hidden ?? 0) > 0 && (
        <p className="mt-6 text-sm text-muted-foreground">
          {d.hidden} hidden · <button className="text-primary underline-offset-4 hover:underline" onClick={restore}>Show them again</button>
        </p>
      )}
    </div>
  );
}

function Tile({ label, n, tone, sub }: { label: string; n: number; tone: string; sub?: string }) {
  return (
    <div className="rounded-xl border bg-card px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-2xl font-semibold tabular", tone)}>{n}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

const HideBtn = ({ onClick, tip }: { onClick: () => void; tip: string }) => (
  <Tip tip={tip}><Button variant="ghost" size="sm" onClick={onClick}><EyeOff /> Hide</Button></Tip>
);

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
