import { useMemo, useState, type ReactNode } from "react";
import { ArrowUpRight, ChevronDown, ChevronRight, Circle, MonitorSmartphone, RefreshCw } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import type { NetAdapter, NetRoute, NetworkResponse } from "@/lib/types";
import { Card, EmptyState, ListSkeleton, LoadError, Mono, Notice, PageHeader, Segmented, Spin, Stat, Tip } from "../ui";
import { FirewallButton, RemedyBar } from "../remedy";

type Tab = "interfaces" | "routes" | "exposure" | "connections" | "devices" | "dns";

const KIND: Record<NetAdapter["kind"], string> = { ethernet: "Ethernet", wifi: "Wi-Fi", vpn: "VPN", virtual: "Virtual", bluetooth: "Bluetooth" };
const CAT: Record<string, string> = { public: "Public", private: "Private", domainauthenticated: "Domain" };

export function speed(bps: number) {
  if (!bps) return "—";
  if (bps >= 1e9) return `${+(bps / 1e9).toFixed(1)} Gbit/s`;
  if (bps >= 1e6) return `${Math.round(bps / 1e6)} Mbit/s`;
  return `${Math.round(bps / 1e3)} kbit/s`;
}
const n = (v: number | undefined) => (v == null ? "—" : v.toLocaleString());
const quiet = (t: ReactNode) => <p className="text-sm text-muted-foreground">{t}</p>;
const th = "px-2 py-2 font-medium first:pl-4 last:pr-4";
const td = "px-2 py-2.5 first:pl-4 last:pr-4";

export function NetworkPage() {
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<Tab>("interfaces");
  const q = usePoll<NetworkResponse>(() => api.network(), 60_000);
  const refresh = async () => {
    setRefreshing(true);
    try { q.setData(await api.network(true)); } catch { void q.reload(); } finally { setRefreshing(false); }
  };
  const d = q.data;
  const c = d?.counts ?? {};
  const fwOff = d ? d.firewall.filter((f) => !f.enabled).length : 0;
  const fwLabel = !d?.firewall.length ? "—" : fwOff === 0 ? "On" : fwOff === d.firewall.length ? "Off" : "Partly";

  return (
    <>
      <PageHeader
        title="Network"
        sub="How this PC is connected and what it exposes. Read from Windows on this PC; nothing is scanned, and nothing is changed unless you click it."
        actions={<>
          {d?.read_at && <span className="text-xs text-muted-foreground tabular">Read {when(d.read_at)}{d.seconds != null && ` · ${d.seconds} s`}</span>}
          <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing}>{refreshing ? <Spin /> : <RefreshCw />}Refresh</Button>
        </>}
      />
      {d?.remediate && <RemedyBar onDone={() => void refresh()} />}
      {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
      {!d ? (!q.error && <ListSkeleton rows={5} />) : !d.read_at ? (
        <LoadError error={new Error(d.error ?? "The network could not be read.")} onRetry={refresh} />
      ) : (
        <div className="space-y-6">
          {d.findings.length > 0 && (
            <section aria-label="Findings" className="divide-y rounded-lg border bg-card">
              {d.findings.map((f, i) => (
                <button key={i} onClick={() => setTab(f.tab)} className="flex w-full items-start gap-3 px-4 py-2.5 text-left text-sm transition-colors hover:bg-muted/40 focus-visible:outline-2 focus-visible:outline-ring">
                  <Circle aria-label={f.level} className={cn("mt-1 size-2 shrink-0 fill-current", f.level === "danger" ? "text-destructive" : f.level === "warning" ? "text-warning" : "text-primary")} />
                  <span className="min-w-0 flex-1">{f.text}</span>
                  <ArrowUpRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                </button>
              ))}
            </section>
          )}

          <Card className="grid grid-cols-2 gap-5 p-5 min-[1000px]:grid-cols-5">
            <Stat label="Interfaces connected" value={<>{n(c.adapters_up)} <span className="text-sm font-normal text-muted-foreground">of {n(c.adapters)}</span></>} />
            <Stat label="Open to the network" value={n(c.listening_network)} sub={`${n(c.listening_network_other)} by programs that are not part of Windows`} />
            <Stat label="Connections now" value={n(c.connections)} sub={`${n(c.programs_connected)} programs`} />
            <Stat label="Devices seen" value={n(c.devices)} />
            <Stat label="Firewall" value={<span className={fwOff ? "text-destructive" : "text-success"}>{fwLabel}</span>} sub={fwOff ? `${fwOff} of ${d.firewall.length} profiles off` : undefined} />
          </Card>

          <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
            <TabsList className="mb-5 h-auto flex-wrap">
              <TabsTrigger value="interfaces">Interfaces</TabsTrigger>
              <TabsTrigger value="routes">Routes<Count v={c.routes} /></TabsTrigger>
              <TabsTrigger value="exposure">Exposure<Count v={c.listening} /></TabsTrigger>
              <TabsTrigger value="connections">Connections<Count v={c.connections} /></TabsTrigger>
              <TabsTrigger value="devices">Devices<Count v={c.devices} /></TabsTrigger>
              <TabsTrigger value="dns">DNS &amp; proxy</TabsTrigger>
            </TabsList>
            <TabsContent value="interfaces"><Interfaces d={d} /></TabsContent>
            <TabsContent value="routes"><Routes d={d} /></TabsContent>
            <TabsContent value="exposure"><Exposure d={d} remediate={!!d.remediate} /></TabsContent>
            <TabsContent value="connections"><Connections d={d} /></TabsContent>
            <TabsContent value="devices"><Devices d={d} /></TabsContent>
            <TabsContent value="dns"><Dns d={d} /></TabsContent>
          </Tabs>
        </div>
      )}
    </>
  );
}

const Count = ({ v }: { v?: number | undefined }) => (v == null ? null : <span className="ml-1.5 tabular text-muted-foreground">{v}</span>);

function Toggle({ open, onClick, children }: { open: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} aria-expanded={open} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}{children}
    </button>
  );
}

/* ---------- Interfaces ---------- */
function Interfaces({ d }: { d: NetworkResponse }) {
  const [more, setMore] = useState(false);
  const up = d.adapters.filter((a) => a.up);
  const down = d.adapters.filter((a) => !a.up);
  return (
    <div className="space-y-4">
      {up.length ? <div className="grid gap-4 min-[1200px]:grid-cols-2">{up.map((a) => <AdapterCard key={a.index} a={a} />)}</div> : <Notice tone="warn">No interface is connected.</Notice>}
      {down.length > 0 && (
        <div className="rounded-lg border px-4 py-3">
          <Toggle open={more} onClick={() => setMore(!more)}>{down.length} more {down.length === 1 ? "is" : "are"} not connected</Toggle>
          {more && (
            <div className="mt-3 divide-y">
              {down.map((a) => (
                <div key={a.index} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                  <span className="font-medium">{a.name}</span><Badge variant="muted">{KIND[a.kind]}</Badge>
                  <span className="text-muted-foreground">{a.status}</span>
                  <span className="ml-auto text-xs text-muted-foreground">{a.description}</span>
                  {a.mac && <Mono className="text-xs text-muted-foreground">{a.mac}</Mono>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AdapterCard({ a }: { a: NetAdapter }) {
  const [v6open, setV6] = useState(false);
  const v4 = a.addresses.filter((x) => x.family === "IPv4");
  const v6 = a.addresses.filter((x) => x.family === "IPv6");
  const v6shown = v6open || v6.length <= 2 ? v6 : v6.slice(0, 2);
  const rows: [string, ReactNode][] = [
    ["IPv4", v4.length ? v4.map((x) => <div key={x.address}>{x.address}{x.prefix != null && `/${x.prefix}`} <span className="text-muted-foreground">{a.dhcp ? "DHCP" : "manual"}</span></div>) : "—"],
    ["IPv6", v6.length ? <>{v6shown.map((x) => <div key={x.address}>{x.address}{x.prefix != null && `/${x.prefix}`}</div>)}{v6.length > 2 && <button className="text-xs text-primary hover:underline" onClick={() => setV6(!v6open)}>{v6open ? "Show fewer" : `${v6.length - 2} more`}</button>}</> : "—"],
    ["Gateway", a.gateways.length ? a.gateways.join(", ") : "—"],
    ["DNS", a.dns.length ? a.dns.map((s) => <div key={s}>{s}</div>) : "—"],
    ["MAC", a.mac || "—"],
    ["MTU", a.mtu ?? "—"],
    ["Metric", a.metric ?? "—"],
  ];
  if (a.wifi) {
    const w = a.wifi;
    if (w.ssid) rows.unshift(["SSID", w.ssid]);
    if (w.signal) rows.push(["Signal", <>{w.signal}{w.band && ` · ${w.band}`}{w.channel && ` · channel ${w.channel}`}</>]);
    if (w.authentication) rows.push(["Security", <>{w.authentication}{w.radio_type && ` · ${w.radio_type}`}</>]);
  }
  return (
    <Card className="min-w-0 p-5">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{a.name}</h3>
        <Badge variant="muted">{KIND[a.kind]}</Badge>
        {a.internet && <Badge variant="success">Internet</Badge>}
        <span className="ml-auto text-sm tabular text-muted-foreground">{a.status} · {speed(a.speed)}</span>
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        {a.network ? <>{a.network}{a.category && <Badge variant={a.category === "public" ? "info" : "warning"}>{CAT[a.category]}</Badge>}</> : "No network"}
        {a.description && <span className="text-xs">· {a.description}</span>}
      </div>
      <dl className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
        {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted-foreground">{k}</dt><dd className="path min-w-0 break-all tabular">{v}</dd></div>)}
      </dl>
    </Card>
  );
}

/* ---------- Routes ---------- */
const KIND_LABEL: Record<NetRoute["kind"], string> = { default: "Default", network: "Network", host: "Host", link: "Link", multicast: "Multicast", loopback: "Loopback" };
function Routes({ d }: { d: NetworkResponse }) {
  const [f, setF] = useState<"main" | "IPv4" | "IPv6" | "all">("main");
  const rows = useMemo(() => {
    if (f === "all") return d.routes;
    if (f !== "main") return d.routes.filter((r) => r.family === f);
    return d.routes.filter((r) => ["default", "network", "host"].includes(r.kind)).sort((a, b) => (a.family === b.family ? 0 : a.family === "IPv4" ? -1 : 1));
  }, [d.routes, f]);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented label="Routes shown" value={f} onChange={setF} options={[{ value: "main", label: "Main" }, { value: "IPv4", label: "IPv4" }, { value: "IPv6", label: "IPv6" }, { value: "all", label: "All" }]} />
        {quiet("The most specific destination wins; between equal ones, the lowest metric.")}
      </div>
      {rows.length === 0 ? quiet("No routes in this view.") : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
              <th className={th}>Destination</th><th className={th}>Via</th><th className={th}>Interface</th><th className={cn(th, "text-right")}>Metric</th><th className={th}>Kind</th>
            </tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i} className={cn("border-b last:border-b-0", r.kind === "default" && "bg-primary/5")}>
                <td className={td}><Mono>{r.destination}</Mono></td>
                <td className={td}>{r.on_link ? <span className="text-muted-foreground">on-link</span> : <Mono>{r.next}</Mono>}</td>
                <td className={td}>{r.interface}</td>
                <td className={cn(td, "text-right tabular")}>{r.metric ?? "—"}</td>
                <td className={td}><span className="flex flex-wrap items-center gap-1.5"><Badge variant={r.kind === "default" ? "info" : "muted"}>{KIND_LABEL[r.kind]}</Badge>{r.protocol && !["Local", "Dhcp", "RouterDiscovery"].includes(r.protocol) && <span className="text-xs text-muted-foreground">{r.protocol}</span>}</span></td>
              </tr>
            ))}</tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

/* ---------- Exposure ---------- */
function Exposure({ d, remediate }: { d: NetworkResponse; remediate: boolean }) {
  const [f, setF] = useState<"other" | "network" | "all">("other");
  const [builtinOpen, setBuiltin] = useState(false);
  const [allRules, setAllRules] = useState(false);
  const ru = d.rules ?? null;
  const look = ru ? ru.programs.filter((g) => g.missing) : [];
  const ruleRows = ru ? (allRules ? ru.programs : look) : [];
  const active = new Set(d.adapters.filter((a) => a.up && a.category).map((a) => CAT[a.category!]));
  const shares = d.shares.filter((s) => !s.builtin);
  const builtin = d.shares.filter((s) => s.builtin);
  const ports = d.listening.filter((l) => f === "all" || (l.reach === "network" && (f === "network" || !l.windows)));
  return (
    <div className="space-y-8">
      <section>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">Firewall</h2>
          {remediate && d.firewall.filter((p) => !p.enabled).length > 1 && <FirewallButton profile="all" primary />}
        </div>
        <div className="grid grid-cols-1 gap-3 min-[1000px]:grid-cols-3">
          {d.firewall.map((p) => (
            <Card key={p.name} className={cn("p-4", !p.enabled && "border-destructive/40 bg-danger-soft")}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{p.name}</span>
                <Badge variant={p.enabled ? "success" : "danger"}>{p.enabled ? "On" : "Off"}</Badge>
                {active.has(p.name) && <Badge variant="info">Your network</Badge>}
                {remediate && !p.enabled && ["Domain", "Private", "Public"].includes(p.name) && (
                  <span className="ml-auto"><FirewallButton profile={p.name as "Domain" | "Private" | "Public"} /></span>
                )}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {p.enabled
                  ? <>Incoming: {p.inbound.toLowerCase() === "block" ? "blocked unless a rule allows it" : "allowed"} · Outgoing: {p.outbound.toLowerCase() === "block" ? "blocked unless a rule allows it" : "allowed"}</>
                  : <>When on: incoming {p.inbound.toLowerCase() === "block" ? "blocked unless a rule allows it" : "allowed"}, outgoing {p.outbound.toLowerCase() === "block" ? "blocked unless a rule allows it" : "allowed"}</>}
              </p>
            </Card>
          ))}
        </div>
        {!!d.other_firewalls?.length && <Notice className="mt-3">Also registered as a firewall: {d.other_firewalls.join(", ")}.</Notice>}
      </section>

      {ru && (
        <section>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Rules that let connections in</h2>
            <Segmented label="Rules shown" value={allRules ? "all" : "look"} onChange={(v) => setAllRules(v === "all")}
              options={[{ value: "look", label: `Left over (${look.length})` }, { value: "all", label: `All programs (${ru.programs.length})` }]} />
          </div>
          <p className="mb-3 text-sm text-muted-foreground">
            {ru.total} rules let connections in: {ru.windows} are Windows' own, the rest cover {ru.programs.length} programs.
            {ru.missing > 0 && <> {ru.missing} of those programs {ru.missing === 1 ? "is" : "are"} no longer on this PC; their rules are left over and can be deleted in Windows Security › Firewall › Advanced settings.</>}
          </p>
          {ru.wide_open.length > 0 && (
            <Notice tone="warn" className="mb-3">
              {ru.wide_open.length === 1 ? "One rule lets" : `${ru.wide_open.length} rules let`} any program accept connections on any port: {ru.wide_open.map((w) => w.name).join(", ")}.
            </Notice>
          )}
          {ruleRows.length === 0 ? quiet(allRules ? "No rules for programs outside Windows." : "No left-over rules.") : (
            <Card className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
                  <th className={th}>Program</th><th className={th}>Ports</th><th className={th}>Profiles</th><th className={th}>From</th><th className={cn(th, "text-right")}>Rules</th>
                </tr></thead>
                <tbody>{ruleRows.map((g) => (
                  <tr key={g.program + g.path + (g.missing ? "!" : "")} className="border-b last:border-b-0">
                    <td className={td}><span className="flex flex-wrap items-center gap-1.5"><Tip tip={g.path || undefined}><span tabIndex={g.path ? 0 : undefined}>{g.program}</span></Tip>{g.missing && <Badge variant="warning">No longer here</Badge>}</span></td>
                    <td className={cn(td, "path tabular")}>{g.any_port ? <span className="text-muted-foreground">any</span> : <>{g.ports.join(", ")}{g.more_ports > 0 && ` +${g.more_ports}`}</>}</td>
                    <td className={td}>{g.profiles.includes("all") ? "All" : g.profiles.join(", ")}</td>
                    <td className={td}>{g.any_address ? <Badge variant={g.public ? "warning" : "muted"}>Any address</Badge> : <Badge variant="muted">Listed addresses</Badge>}</td>
                    <td className={cn(td, "text-right tabular")}>{g.rules}</td>
                  </tr>
                ))}</tbody>
              </table>
            </Card>
          )}
        </section>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold">Shared folders</h2>
        {shares.length ? (
          <Card className="divide-y">{shares.map((s) => (
            <div key={s.name} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm">
              <span className="font-medium">{s.name}</span><Mono className="text-muted-foreground">{s.path}</Mono>
              {s.printer && <Badge variant="muted">Printer</Badge>}
              {s.description && <span className="ml-auto text-xs text-muted-foreground">{s.description}</span>}
            </div>
          ))}</Card>
        ) : quiet("No folders are shared from this PC.")}
        {builtin.length > 0 && (
          <div className="mt-2">
            <Toggle open={builtinOpen} onClick={() => setBuiltin(!builtinOpen)}>{builtin.length} built-in administrative share{builtin.length === 1 ? "" : "s"}</Toggle>
            {builtinOpen && <p className="mt-1 pl-5 text-sm text-muted-foreground">{builtin.map((s) => <Mono key={s.name} className="mr-3">{s.name}{s.path && ` → ${s.path}`}</Mono>)}</p>}
          </div>
        )}
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">Listening ports</h2>
          <Segmented label="Ports shown" value={f} onChange={setF} options={[{ value: "other", label: "From the network, not Windows" }, { value: "network", label: "From the network" }, { value: "all", label: "All" }]} />
        </div>
        {ports.length === 0 ? quiet("No ports in this view.") : (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
                <th className={th}>Port</th><th className={th}>Program</th><th className={th}>Reachable from</th><th className={th}>Addresses</th>
              </tr></thead>
              <tbody>{ports.map((l) => (
                <tr key={`${l.proto}${l.port}${l.pid}`} className="border-b last:border-b-0">
                  <td className={cn(td, "path whitespace-nowrap tabular")}><span className="text-muted-foreground">{l.proto}</span> {l.port}</td>
                  <td className={td}><span className="flex flex-wrap items-center gap-1.5"><Tip tip={l.path || undefined}><span tabIndex={l.path ? 0 : undefined}>{l.process}</span></Tip>{l.windows && <Badge variant="muted">Windows</Badge>}</span></td>
                  <td className={td}>{l.reach === "network" ? <Badge variant="warning">Network</Badge> : <Badge variant="muted">This PC only</Badge>}</td>
                  <td className={cn(td, "max-w-[14rem]")}><div className="path truncate text-muted-foreground" title={l.addresses.join(", ")}>{l.addresses.join(", ")}</div></td>
                </tr>
              ))}</tbody>
            </table>
          </Card>
        )}
      </section>
    </div>
  );
}

/* ---------- Connections ---------- */
function Connections({ d }: { d: NetworkResponse }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const flip = (p: string) => setOpen((s) => { const x = new Set(s); x.has(p) ? x.delete(p) : x.add(p); return x; });
  if (!d.connections.length) return <EmptyState icon={<MonitorSmartphone />} title="No open connections">No program has a connection open right now.</EmptyState>;
  return (
    <div className="space-y-3">
      {quiet("Connections open right now; they change by the second.")}
      <Card className="divide-y">
        {d.connections.map((g) => (
          <div key={g.process}>
            <button onClick={() => flip(g.process)} aria-expanded={open.has(g.process)} className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left text-sm hover:bg-muted/40">
              {open.has(g.process) ? <ChevronDown className="size-4 text-muted-foreground" /> : <ChevronRight className="size-4 text-muted-foreground" />}
              <span className="font-medium">{g.process}</span>
              <span className="tabular text-muted-foreground">{g.count} connection{g.count === 1 ? "" : "s"}</span>
              <span className="ml-auto flex gap-2 tabular text-xs">
                {g.internet > 0 && <Badge variant="info">{g.internet} internet</Badge>}
                {g.local > 0 && <Badge variant="muted">{g.local} local network</Badge>}
              </span>
            </button>
            {open.has(g.process) && (
              <div className="space-y-1 px-11 pb-3">
                {g.remotes.map((r) => (
                  <div key={`${r.address}:${r.port}`} className="flex flex-wrap items-center gap-3 text-sm">
                    <Mono className="tabular">{r.address.includes(":") ? `[${r.address}]` : r.address}:{r.port}</Mono>
                    <span className="tabular text-muted-foreground">×{r.count}</span>
                    <Badge variant={r.scope === "internet" ? "info" : "muted"}>{r.scope}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </Card>
    </div>
  );
}

/* ---------- Devices ---------- */
function Devices({ d }: { d: NetworkResponse }) {
  const note = quiet("Devices this PC has talked to recently. This is Windows' own list; the network is not scanned.");
  if (!d.devices.length) return <div className="space-y-3">{note}<EmptyState icon={<MonitorSmartphone />} title="No devices known">Windows has not talked to other devices on the local network recently.</EmptyState></div>;
  return (
    <div className="space-y-3">
      {note}
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
            <th className={th}>IP address</th><th className={th}>MAC</th><th className={th}>Interface</th><th className={th}>State</th>
          </tr></thead>
          <tbody>{d.devices.map((v) => (
            <tr key={v.address + v.interface} className="border-b last:border-b-0">
              <td className={td}><span className="flex flex-wrap items-center gap-2"><Mono className="tabular">{v.address}</Mono>{v.gateway && <Badge variant="info">Gateway</Badge>}</span></td>
              <td className={td}><Mono className="tabular text-muted-foreground">{v.mac || "—"}</Mono></td>
              <td className={td}>{v.interface}</td>
              <td className={td}><Badge variant={v.state.toLowerCase() === "reachable" ? "success" : "muted"}>{v.state}</Badge></td>
            </tr>
          ))}</tbody>
        </table>
      </Card>
    </div>
  );
}

/* ---------- DNS & proxy ---------- */
function Dns({ d }: { d: NetworkResponse }) {
  const p = d.proxy;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 min-[1000px]:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-semibold">DNS</h2>
          <dl className="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">Servers</dt><dd className="path tabular">{d.dns.servers.length ? d.dns.servers.map((s) => <div key={s}>{s}</div>) : "—"}</dd>
            <dt className="text-muted-foreground">Search suffixes</dt><dd className="path">{d.dns.suffixes.length ? d.dns.suffixes.join(", ") : "—"}</dd>
          </dl>
        </Card>
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-semibold">Proxy</h2>
          {!p.enabled && !p.script ? quiet("Off · programs connect directly.") : (
            <dl className="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
              {p.server && <><dt className="text-muted-foreground">Server</dt><dd><Mono>{p.server}</Mono></dd></>}
              {p.script && <><dt className="text-muted-foreground">Script</dt><dd><Mono>{p.script}</Mono></dd></>}
              <dt className="text-muted-foreground">Bypass</dt><dd><Mono>{p.bypass || "—"}</Mono></dd>
            </dl>
          )}
        </Card>
      </div>
      <section>
        <h2 className="mb-3 text-sm font-semibold">Hosts file</h2>
        {d.hosts.length === 0 ? quiet("The hosts file has no entries.") : (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr className="border-b"><th className={th}>Address</th><th className={th}>Names</th></tr></thead>
              <tbody>{d.hosts.map((h) => (
                <tr key={h.address} className="border-b last:border-b-0">
                  <td className={cn(td, "w-48")}><Mono className="tabular">{h.address}</Mono></td>
                  <td className={td}><Mono>{h.names.join("  ")}</Mono></td>
                </tr>
              ))}</tbody>
            </table>
          </Card>
        )}
      </section>
    </div>
  );
}
