import { useRef, useState } from "react";
import { ArrowLeft, Copy, Flame, Printer } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePoll } from "@/lib/hooks";
import { bytes, when } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Card, Confirm, ListSkeleton, LoadError, Notice, PageHeader, Segmented, Stat } from "@/shadow/ui";
import { api, type AppFact, type AreaStatus, type Check, type Cve, type DeviceDetail, type FlawApp, type FlawService, type SupportProgram } from "../api";
import { ControlCard, HistoryGrid, LABEL, ReferenceLine, Section, silentFor, SQUARE, Tile } from "../parts";

const TABS = ["compliance", "security", "programs", "network", "reported"] as const;
type TabKey = (typeof TABS)[number];
const KIND: Record<string, string> = { device: "The PC itself", apps: "Installed programs", services: "Services", network: "Network", posture: "Security settings" };

function CveList({ cves }: { cves: Cve[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? cves : cves.slice(0, 3);
  return (
    <div className="mt-2 space-y-1.5">
      {shown.map((c) => (
        <div key={c.id} className="flex gap-3 text-sm">
          <span className="path w-36 shrink-0">{c.id}</span>
          <span className={cn("w-9 shrink-0 tabular", (c.score ?? 0) >= 9 ? "font-medium text-destructive" : (c.score ?? 0) >= 7 ? "text-warning" : "text-muted-foreground")}>{c.score ?? "—"}</span>
          <span className="min-w-0 flex-1 text-muted-foreground">
            {c.kev && <Badge variant="danger" className="mr-1.5"><Flame className="size-3" />Used in attacks</Badge>}
            {c.fixed_in && <span className="mr-1.5 text-foreground">Fixed in {c.fixed_in}.</span>}
            {c.summary}
          </span>
        </div>
      ))}
      {cves.length > 3 && <button className="text-xs text-primary hover:underline" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${cves.length}`}</button>}
    </div>
  );
}

function FlawRow({ a }: { a: FlawApp }) {
  const kev = a.cves.filter((c) => c.kev).length;
  return (
    <div className="px-5 py-3.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-medium">{a.name}</span>
        {!(a.judged_version && a.name.includes(a.judged_version)) && <span className="path text-muted-foreground">{a.judged_version || a.version || "version not known"}</span>}
        {kev > 0 && <Badge variant="danger">{kev} used in attacks</Badge>}
        <span className="text-sm text-muted-foreground">{a.cves.length} known flaw{a.cves.length === 1 ? "" : "s"}</span>
        {a.update_to ? <Badge variant="info">Update to {a.update_to} is available</Badge> : a.available && <Badge variant="muted">Newer version {a.available}</Badge>}
        <span className="ml-auto text-xs text-muted-foreground">matched as {a.products.join(", ")}</span>
      </div>
      {a.cves.length > 0 && <CveList cves={a.cves} />}
    </div>
  );
}

function ServiceRow({ s }: { s: FlawService }) {
  const ports = s.ports.map((p) => `${p.port}${p.network ? "" : " (this PC only)"}`).join(", ");
  return (
    <div className="px-5 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-medium">{s.name}</span>
        <Badge variant={s.running ? "success" : "muted"}>{s.running ? "Running" : "Stopped"}</Badge>
        {s.exposed && <Badge variant="warning">Listens from the network</Badge>}
        {s.cves.length > 0 && <Badge variant="danger">{s.cves.length} known flaw{s.cves.length === 1 ? "" : "s"}</Badge>}
        <span className="text-sm text-muted-foreground">
          {[s.account && `runs as ${s.account}`, ports && `port${s.ports.length === 1 ? "" : "s"} ${ports}`, s.app_name && `part of ${s.app_name}`, s.version && `version ${s.version}`].filter(Boolean).join(" · ")}
        </span>
      </div>
    </div>
  );
}

function SecurityTab({ d }: { d: DeviceDetail }) {
  const [show, setShow] = useState<"flaws" | "all">("flaws");
  const f = d.flaws;
  if (!f) return <div className="space-y-4"><Notice>This device's programs have not been compared with the CVE list yet.</Notice><ReferenceLine r={d.reference} /></div>;
  const s = f.summary, apps = show === "flaws" ? f.apps.filter((a) => a.cves.length) : f.apps;
  const services = f.services.filter((x) => x.exposed || x.cves.length || x.running);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-4 gap-3 max-[1100px]:grid-cols-2">
        <Tile label="Used in real attacks" n={s.kev} tone={s.kev ? "text-destructive" : undefined} sub="on CISA's known-exploited list" />
        <Tile label="Critical" n={s.critical} tone={s.critical ? "text-warning" : undefined} sub="severity 9.0 or higher" />
        <Tile label="Programs with known flaws" n={s.apps_affected} sub={`of ${f.recognised} that could be compared`} />
        <Tile label="Services open to the network" n={s.services_exposed} tone={s.services_exposed ? "text-warning" : undefined} sub={`of ${s.services} not part of Windows`} />
      </div>
      <Notice>
        A program is listed only when its name, its maker and its installed version all match what a CVE states.
        {f.installed - f.recognised > 0 && <> {f.installed - f.recognised} of the {f.installed} programs match no product in the list: they are not judged, which is not the same as safe.</>}
        {" "}Windows itself and Store apps are not judged. A match can still be wrong.
      </Notice>
      <Section title="Programs" actions={<Segmented label="Which programs" value={show} onChange={setShow} options={[{ value: "flaws", label: `With flaws (${s.apps_affected})` }, { value: "all", label: `All compared (${f.recognised})` }]} />}>
        <Card className="divide-y rounded-lg">
          {apps.length ? apps.map((a) => <FlawRow key={a.name + a.version} a={a} />) : <p className="px-5 py-4 text-sm text-muted-foreground">No known flaw for the installed version of any program that could be compared.</p>}
        </Card>
      </Section>
      <Section title="Services" sub="Background services that are not part of Windows: running, listening or with known flaws.">
        <Card className="divide-y rounded-lg">
          {services.length ? services.map((x) => <ServiceRow key={x.service ?? x.name} s={x} />) : <p className="px-5 py-4 text-sm text-muted-foreground">None reported.</p>}
        </Card>
      </Section>
      <ReferenceLine r={d.reference} />
    </div>
  );
}

function ProgramsTab({ d }: { d: DeviceDetail }) {
  const [q, setQ] = useState("");
  const [show, setShow] = useState<"all" | "newer" | "support">("all");
  const apps = d.snapshots.apps?.payload.apps ?? [];
  const sup = new Map<string, SupportProgram>((d.support?.programs ?? []).map((p) => [p.name + "|" + (p.version ?? ""), p]));
  const of = (a: AppFact) => sup.get(a.name + "|" + (a.version ?? ""));
  const needle = q.trim().toLowerCase();
  const rows = apps.filter((a) => (!needle || `${a.name} ${a.publisher ?? ""}`.toLowerCase().includes(needle))
    && (show === "all" || (show === "newer" ? !!a.available : ["ended", "soon"].includes(of(a)?.state ?? ""))));
  const newer = apps.filter((a) => a.available).length, ending = apps.filter((a) => ["ended", "soon"].includes(of(a)?.state ?? "")).length;
  if (!d.snapshots.apps) return <Notice>This device has not reported its programs. On the PC, Library › Applications has to be switched on.</Notice>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a program or maker" className="h-9 max-w-xs" aria-label="Find a program" />
        <Segmented label="Which programs" value={show} onChange={setShow}
          options={[{ value: "all", label: `All (${apps.length})` }, { value: "newer", label: `Newer version (${newer})` }, { value: "support", label: `Support ended or ending (${ending})` }]} />
        <span className="ml-auto text-xs text-muted-foreground">Reported {when(d.snapshots.apps.received_at)}</span>
      </div>
      <Card className="overflow-x-auto rounded-lg">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
            <tr><th className="px-4 py-2 font-medium">Program</th><th className="px-4 py-2 font-medium">Version</th><th className="px-4 py-2 font-medium">Newer</th>
              <th className="px-4 py-2 font-medium">Support</th><th className="px-4 py-2 font-medium">Installed</th><th className="px-4 py-2 text-right font-medium">Size</th></tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((a, i) => {
              const s = of(a);
              return (
                <tr key={a.name + a.version + i} className="align-top">
                  <td className="px-4 py-2.5"><div className="font-medium">{a.name}{a.kind === "packaged" && <Badge variant="muted" className="ml-2">{a.from_store ? "Store" : "Packaged"}</Badge>}</div><div className="text-xs text-muted-foreground">{a.publisher}</div></td>
                  <td className="path px-4 py-2.5">{a.version || "—"}</td>
                  <td className="path px-4 py-2.5">{a.available ? <span className="text-foreground">{a.available}</span> : <span className="text-muted-foreground">—</span>}</td>
                  <td className="px-4 py-2.5">
                    {s ? <Badge variant={s.state === "ended" ? "danger" : s.state === "soon" ? "warning" : s.state === "supported" ? "success" : "muted"}>
                      {s.state === "ended" ? `Ended${s.until ? " " + s.until : ""}` : s.state === "soon" ? `Ends ${s.until}` : s.state === "supported" ? (s.until ? `Until ${s.until}` : "Supported") : "Line not listed"}
                    </Badge> : <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-muted-foreground">{a.installed ?? "—"}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right tabular text-muted-foreground">{a.size ? bytes(a.size) : "—"}</td>
                </tr>
              );
            })}
            {rows.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-muted-foreground">Nothing matches.</td></tr>}
          </tbody>
        </table>
      </Card>
      <p className="text-sm text-muted-foreground">Support is known only for programs in the public end-of-life list ({d.support?.programs?.length ?? 0} of this device's). A dash means not judged, not supported.</p>
    </div>
  );
}

function NetworkTab({ d }: { d: DeviceDetail }) {
  const n = d.snapshots.network?.payload;
  if (!n) return <Notice>This device has not reported its network settings yet.</Notice>;
  const up = n.interfaces.filter((i) => i.up);
  const ports = n.listening.filter((e) => !e.windows);
  return (
    <div className="space-y-6">
      <Section title="Windows Firewall" sub={n.other_firewalls.length ? `Also registered with Windows: ${n.other_firewalls.join(", ")}.` : undefined}>
        <div className="grid grid-cols-3 gap-3 max-[900px]:grid-cols-1">
          {n.firewall.map((f) => (
            <Card key={f.name} className="rounded-lg p-4">
              <div className="flex items-center justify-between"><span className="font-medium">{f.name}</span><Badge variant={f.enabled ? "success" : "danger"}>{f.enabled ? "On" : "Off"}</Badge></div>
              <div className="mt-1 text-sm text-muted-foreground">Incoming: {(f.inbound ?? "not reported").toLowerCase()} · outgoing: {(f.outbound ?? "not reported").toLowerCase()}</div>
            </Card>
          ))}
        </div>
      </Section>
      <Card className="grid grid-cols-4 gap-6 rounded-lg p-5 max-[900px]:grid-cols-2">
        <Stat label="Connected interfaces" value={up.length} sub={[...new Set(up.map((i) => i.category).filter(Boolean))].join(", ") || undefined} />
        <Stat label="Shared folders" value={n.shared_folders} />
        <Stat label="Rules letting connections in" value={n.rules?.total ?? "—"} sub={n.rules ? `${n.rules.windows} Windows' own, ${n.rules.programs} programs` : "not readable on the device"} />
        <Stat label="Left-over rule sets" value={n.rules?.left_over ?? "—"} sub="for programs no longer installed" />
      </Card>
      <Section title="Programs that accept connections from the network" sub="Not part of Windows. Short-lived ports and discovery chatter are left out by the device.">
        <Card className="overflow-x-auto rounded-lg">
          {ports.length ? (
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground"><tr><th className="px-4 py-2 font-medium">Program</th><th className="px-4 py-2 font-medium">Port</th></tr></thead>
              <tbody className="divide-y">{ports.map((e, i) => <tr key={i}><td className="px-4 py-2 font-medium">{e.process || "not known"}</td><td className="path px-4 py-2">{e.proto} {e.port}</td></tr>)}</tbody>
            </table>
          ) : <p className="px-5 py-4 text-sm text-muted-foreground">None.</p>}
        </Card>
      </Section>
      <p className="text-sm text-muted-foreground">Addresses, open connections, nearby devices, routes and DNS never leave the PC; its own console shows them.</p>
    </div>
  );
}

function ReportedTab({ d }: { d: DeviceDetail }) {
  return (
    <div className="space-y-4">
      <Notice>A PC sends five kinds of facts and the server keeps a kind only when it changed. Never sent: anything about files, account names, folders and program paths, addresses, open connections, nearby devices.</Notice>
      <Card className="overflow-x-auto rounded-lg">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground"><tr><th className="px-4 py-2 font-medium">Kind</th><th className="px-4 py-2 font-medium">Versions kept</th><th className="px-4 py-2 font-medium">First</th><th className="px-4 py-2 font-medium">Last change</th></tr></thead>
          <tbody className="divide-y">
            {d.history.map((h) => <tr key={h.kind}><td className="px-4 py-2.5 font-medium">{KIND[h.kind] ?? h.kind}</td><td className="px-4 py-2.5 tabular">{h.versions}</td><td className="px-4 py-2.5 text-muted-foreground">{when(h.first)}</td><td className="px-4 py-2.5 text-muted-foreground">{when(h.last)}</td></tr>)}
            {d.history.length === 0 && <tr><td colSpan={4} className="px-4 py-6 text-center text-muted-foreground">Nothing reported yet.</td></tr>}
          </tbody>
        </table>
      </Card>
      <p className="text-sm text-muted-foreground">Enrolled {when(d.enrolled_at)} · agent version {d.agent_version || "not reported"} · judged {when(d.judged_at)}</p>
    </div>
  );
}

export function DevicePage({ id, tab }: { id: string; tab?: string }) {
  const q = usePoll<DeviceDetail>(() => api.device(id), 60_000, [id]);
  const [accepting, setAccepting] = useState<Check | null>(null);
  const [reason, setReason] = useState("");
  const keep = useRef(false);
  const d = q.data;
  const current: TabKey = (TABS as readonly string[]).includes(tab ?? "") ? (tab as TabKey) : "compliance";
  const back = <a href="#/devices" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground" data-print-hide><ArrowLeft className="size-3.5" />Devices</a>;
  if (!d) return <>{back}<PageHeader title="Device" />{q.error ? <LoadError error={q.error} onRetry={q.reload} /> : <ListSkeleton rows={4} />}</>;

  const save = async (check: Check, why: string) => {
    try { await api.accept(id, check.id, why); await q.reload(); return true; } catch (e) { toast.error((e as Error).message); return false; }
  };
  const accept = async () => {
    if (!accepting) return;
    if (!reason.trim()) { keep.current = true; toast.error("Write why this is acceptable."); return; }
    await save(accepting, reason.trim());
  };
  const copy = async () => { try { await navigator.clipboard.writeText((await api.report(id)).text); toast.success("Copied"); } catch (e) { toast.error((e as Error).message || "Could not copy."); } };

  const dev = d.snapshots.device?.payload ?? {};
  const line = [[dev.manufacturer, dev.model].filter(Boolean).join(" "), dev.serial && `serial ${dev.serial}`, dev.windows && `${dev.windows}${dev.build ? `, build ${dev.build}` : ""}`].filter(Boolean).join(" · ");
  const c = d.compliance, s = c?.summary;
  const silent = d.silent_seconds == null || d.silent_seconds > 86400;
  const days = d.compliance_history.map((h) => h.day);
  return (
    <>
      {back}
      <p data-print="only" className="mb-4 hidden text-lg font-semibold">Security posture of {d.name}, judged {d.judged_at ? new Date(d.judged_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : "not yet"}</p>
      <PageHeader
        title={d.name}
        sub={<><div>{line || "Nothing reported yet."}</div><div className="mt-1 text-xs">Last report {when(d.last_seen)} · judged {when(d.judged_at)}</div></>}
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void copy()} disabled={!c}><Copy />Copy as text</Button>
          <Button variant="outline" size="sm" onClick={() => window.print()} disabled={!c}><Printer />Print</Button>
        </>}
      />
      {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
      {silent && <Notice tone="warn" className="mb-4">This PC has {d.last_seen ? `not reported since ${when(d.last_seen)}` : "never reported"} ({silentFor(d.silent_seconds)}). What is shown may be out of date.</Notice>}
      <Tabs value={current} onValueChange={(v) => { window.location.hash = `/devices/${id}/${v}`; }}>
        <TabsList className="mb-6" data-print-hide>
          <TabsTrigger value="compliance">Compliance{s && s.fail > 0 && <span className="ml-1.5 tabular text-destructive">{s.fail}</span>}</TabsTrigger>
          <TabsTrigger value="security">Security{d.flaws && d.flaws.summary.apps_affected > 0 && <span className={cn("ml-1.5 tabular", d.flaws.summary.kev ? "text-destructive" : "text-warning")}>{d.flaws.summary.apps_affected}</span>}</TabsTrigger>
          <TabsTrigger value="programs">Programs<span className="ml-1.5 tabular text-muted-foreground">{d.snapshots.apps?.payload.apps.length ?? 0}</span></TabsTrigger>
          <TabsTrigger value="network">Network</TabsTrigger>
          <TabsTrigger value="reported">Reported</TabsTrigger>
        </TabsList>
        <TabsContent value="compliance">
          {!c || !s ? <Notice>This device has not been judged yet. That happens within a minute of its first report.</Notice> : (
            <div className="space-y-8">
              <Card data-print-card className="rounded-lg p-5">
                <div className="flex flex-wrap items-center justify-between gap-6">
                  <div className="text-xl font-semibold tabular">{s.controls_passing} of {s.controls} control areas pass</div>
                  <div className="grid grid-cols-4 gap-8">
                    <Stat label="Failing checks" value={<span className={s.fail ? "text-destructive" : undefined}>{s.fail}</span>} />
                    <Stat label="Worth a look" value={<span className={s.warn ? "text-warning" : undefined}>{s.warn}</span>} />
                    <Stat label="Could not be checked" value={s.unknown} />
                    <Stat label="Accepted with a reason" value={s.accepted} />
                  </div>
                </div>
                <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">
                  Judged on the server from what the PC reported: counts and settings, never account names or paths, so some lines say how many and not which. The PC's own console names them.
                  This follows the Cyber Essentials control areas; it is not a certificate.
                </p>
              </Card>
              <Section title="Control areas">
                <div className="space-y-4">{c.controls.map((ctl) => <ControlCard key={ctl.key} ctl={ctl} deviceId={id} onAccept={(ch) => { setReason(""); setAccepting(ch); }} onWithdraw={(ch) => void save(ch, "")} />)}</div>
              </Section>
              <Section title="History" sub="One line per control area, one square per day.">
                <Card data-print-card className="rounded-lg">
                  <HistoryGrid days={days} rows={c.controls} cell={(key, i) => { const st: AreaStatus = d.compliance_history[i]!.controls[key] ?? "unknown"; return { tone: SQUARE[st], tip: LABEL[st].toLowerCase() }; }} />
                </Card>
              </Section>
              <p data-print="only" className="hidden text-sm">Judged by the Shadow Filer fleet server from what the PC's agent reported. Follows the Cyber Essentials control areas; not a certificate.</p>
            </div>
          )}
        </TabsContent>
        <TabsContent value="security"><SecurityTab d={d} /></TabsContent>
        <TabsContent value="programs"><ProgramsTab d={d} /></TabsContent>
        <TabsContent value="network"><NetworkTab d={d} /></TabsContent>
        <TabsContent value="reported"><ReportedTab d={d} /></TabsContent>
      </Tabs>

      <Confirm
        open={!!accepting}
        onOpenChange={(o) => { if (!o && keep.current) { keep.current = false; return; } if (!o) setAccepting(null); }}
        title={`Accept: ${accepting?.title ?? ""}`}
        confirmLabel="Accept"
        onConfirm={accept}
      >
        <label className="block space-y-1.5 text-foreground">
          <span className="text-sm font-medium">Why is this acceptable on {d.name}?</span>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} required rows={3} autoFocus />
        </label>
        <p>It stays listed as failing, marked as accepted, and no longer counts against the control area. The acceptance is written to the audit log.</p>
      </Confirm>
    </>
  );
}
