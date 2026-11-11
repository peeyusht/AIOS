import type { ReactNode } from "react";
import { ArrowUpRight, Check, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes, when } from "@/lib/format";
import { cn } from "@/lib/utils";
import { speed } from "./Network";
import type { ComplianceResponse, DashboardResponse, Part } from "@/lib/types";
import { Bar, Card, ListSkeleton, LoadError, Notice, PageHeader, Stat, Tip } from "../ui";

const number = (n: number | undefined | null) => n == null ? "—" : n.toLocaleString();
const quiet = (text: string) => <p className="text-sm text-muted-foreground">{text}</p>;
const off = () => quiet("Off · Turn on in Settings");
function read<T extends object>(part: Part<T> | undefined, children: (value: T) => ReactNode) {
  if (!part) return quiet("Not reported by this agent.");
  return "error" in part ? quiet(`Could not be read: ${part.error}`) : children(part);
}
const ok = <T extends object>(part: Part<T> | undefined): T | null => (part && !("error" in part) ? part : null);

/** A titled block that links to the page it summarises. */
function Panel({ title, to, children, className }: { title: string; to?: string; children: ReactNode; className?: string }) {
  return (
    <Card className={cn("min-w-0 overflow-hidden rounded-lg", className)}>
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {to && <a href={"#" + to} className="inline-flex items-center gap-1 text-xs text-primary hover:underline">Open <ArrowUpRight className="size-3.5" aria-hidden /></a>}
      </div>
      <div className="p-4">{children}</div>
    </Card>
  );
}

type Tone = "danger" | "warning" | null;
/** One cell of the key-numbers strip. */
function Kpi({ label, to, value, sub, tone }: { label: string; to: string; value: ReactNode; sub: ReactNode; tone?: Tone }) {
  return (
    <a href={"#" + to} className={cn("flex min-w-0 flex-col gap-1 bg-card px-4 py-3.5 transition-colors hover:bg-muted/50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
      tone === "danger" && "shadow-[inset_0_-2px_0_var(--color-destructive)]", tone === "warning" && "shadow-[inset_0_-2px_0_var(--color-warning)]")}>
      <span className="label-caps text-muted-foreground">{label}</span>
      <span className={cn("font-mono text-[26px] font-semibold leading-tight tabular", tone === "danger" && "text-destructive", tone === "warning" && "text-warning")}>{value}</span>
      <span className="truncate text-xs text-muted-foreground">{sub}</span>
    </a>
  );
}

const AREA: Record<string, string> = {
  "/inbox": "Inbox", "/security": "Security", "/network": "Network", "/compliance": "Compliance", "/watch": "Watch", "/cleanup": "Cleanup",
  "/library": "Library", "/activity": "Activity", "/settings": "Settings", "/search": "Search",
};
const PRIORITY = {
  danger: { label: "P1", glyph: "■", cls: "bg-danger-soft text-destructive" },
  warning: { label: "P2", glyph: "▲", cls: "bg-warning-soft text-warning" },
  info: { label: "P3", glyph: "○", cls: "bg-muted text-muted-foreground" },
} as const;

type LogRow = { ts: string; kind: string; tone: string; text: string };

export function DashboardPage() {
  const q = usePoll<DashboardResponse>(api.dashboard, 60_000);
  const comp = usePoll<ComplianceResponse>(() => api.compliance(), 300_000);
  const d = q.data;

  const inbox = ok(d?.inbox), sec = ok(d?.security), apps = ok(d?.apps), watch = ok(d?.watch), net = ok(d?.network), store = ok(d?.storage), remedy = ok(d?.remedy);
  const fw = net?.firewall?.state;
  const low = store?.volumes.filter((v) => v.bytes > 0).map((v) => ({ ...v, share: v.free / v.bytes })).sort((a, b) => a.share - b.share)[0];
  const cs = comp.data?.assessed_at ? comp.data.summary : null;

  const log: LogRow[] = [
    ...(apps?.enabled ? apps.recent ?? [] : []).map((a) => ({
      ts: a.ts, kind: a.event, tone: a.event === "removed" ? "text-muted-foreground" : a.event === "installed" ? "text-success" : "text-primary",
      text: a.event === "updated" ? `${a.name} ${a.old_version || "?"} → ${a.new_version || "?"}` : `${a.name} ${(a.event === "removed" ? a.old_version : a.new_version) || ""}`.trim(),
    })),
    ...(remedy?.enabled ? remedy.recent : []).map((r) => ({ ts: r.ts, kind: r.action, tone: r.ok ? "text-success" : "text-destructive", text: r.message })),
  ].sort((a, b) => b.ts.localeCompare(a.ts)).slice(0, 8);

  return <>
    <PageHeader
      title="Today"
      sub={<span className="font-mono text-xs">{new Date().toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" })}{d && <> · updated {when(d.generated_at)}</>}</span>}
      actions={<Button variant="outline" size="sm" onClick={() => { void q.reload(); void comp.reload(); }}><RefreshCw className="size-4" />Refresh</Button>}
    />
    {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
    {!d ? (!q.error && <ListSkeleton rows={5} />) : <div className="space-y-4">

      <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-px overflow-hidden rounded-lg border bg-border">
        <Kpi label="Inbox" to="/inbox" value={inbox ? number(inbox.waiting) : "—"} sub={inbox ? `${inbox.added_7d} new this week · oldest ${inbox.oldest_days ?? "—"} d` : "not read"} />
        <Kpi label="Exploited" to="/security" tone={sec?.summary?.kev ? "danger" : null}
          value={sec?.enabled ? number(sec.summary?.kev) : "off"} sub={sec?.enabled ? "flaws used in real attacks" : "turn on in Settings"} />
        <Kpi label="Critical" to="/security" tone={sec?.summary?.critical ? "warning" : null}
          value={sec?.enabled ? number(sec.summary?.critical) : "off"} sub={sec?.enabled ? `in ${number(sec.summary?.apps_affected)} programs with flaws` : "turn on in Settings"} />
        <Kpi label="Firewall" to="/network" tone={fw === "off" || fw === "partly" ? "danger" : null}
          value={fw === "on" ? "on" : fw === "off" ? "off" : fw === "partly" ? `${net?.firewall?.off.length ?? "?"}/3 off` : "—"}
          sub={fw === "partly" ? `off for ${net?.firewall?.off.join(", ")}` : fw ? "Windows Firewall" : "being read"} />
        <Kpi label="Cyber Essentials" to="/compliance" tone={cs && (cs.controls_passing ?? 0) < (cs.controls ?? 5) ? "warning" : null}
          value={cs ? `${cs.controls_passing ?? "—"}/${cs.controls ?? 5}` : "—"} sub={cs ? "control areas met" : comp.error ? "could not be read" : "being assessed"} />
        <Kpi label="Updates" to="/library" value={apps?.enabled && apps.updates_checked ? number(apps.updates) : "—"}
          sub={apps?.enabled ? apps.updates_checked ? `newer versions of ${number(apps.programs)} programs` : "check is off" : "turn on in Settings"} />
        <Kpi label={low ? `Disk ${low.letter}` : "Disk"} to="/cleanup" tone={low ? (low.share < .1 ? "danger" : low.share < .15 ? "warning" : null) : null}
          value={low ? `${Math.round(low.share * 100)}%` : "—"} sub={low ? `free · ${bytes(low.free)} of ${bytes(low.bytes)}` : "not read"} />
      </div>

      <div className="grid items-start gap-4 min-[1100px]:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-4">
          <Card className="overflow-hidden rounded-lg">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-3">
              <h2 className="flex-1 text-sm font-semibold">Action queue</h2>
              <span className="font-mono text-[11px] text-muted-foreground">{d.attention.length} open · most urgent first</span>
            </div>
            {d.attention.length === 0 ? <div className="p-4"><Notice tone="success" icon={<Check />}>Nothing needs your attention.</Notice></div> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-sm">
                  <thead><tr className="label-caps text-left text-muted-foreground">
                    <th className="px-4 py-2 font-medium">Priority</th><th className="px-2 py-2 font-medium">Area</th><th className="px-2 py-2 font-medium">Item</th><th className="px-4 py-2"><span className="sr-only">Open</span></th>
                  </tr></thead>
                  <tbody>
                    {[...d.attention].sort((a, b) => ["danger", "warning", "info"].indexOf(a.level) - ["danger", "warning", "info"].indexOf(b.level)).map((a, i) => {
                      const p = PRIORITY[a.level];
                      return (
                        <tr key={i} className="border-t align-top">
                          <td className="whitespace-nowrap px-4 py-2.5"><span className={cn("inline-flex items-center gap-1.5 rounded px-2 font-mono text-[11px] font-semibold leading-5", p.cls)}><span aria-hidden>{p.glyph}</span>{p.label}<span className="sr-only">{a.level === "danger" ? " urgent" : a.level === "warning" ? " soon" : " when you can"}</span></span></td>
                          <td className="whitespace-nowrap px-2 py-2.5 text-muted-foreground">{AREA[a.to] ?? a.to.slice(1)}</td>
                          <td className="px-2 py-2.5">{a.text}</td>
                          <td className="whitespace-nowrap px-4 py-2 text-right"><a href={"#" + a.to} className="inline-flex h-7 items-center rounded-md border px-2.5 text-xs font-medium hover:bg-muted">Open</a></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card className="overflow-hidden rounded-lg">
            <div className="flex items-center gap-3 border-b px-4 py-3"><h2 className="flex-1 text-sm font-semibold">Recent changes</h2><a href="#/activity" className="text-xs text-primary hover:underline">Open Activity</a></div>
            {log.length === 0 ? <div className="p-4">{quiet("No program installed, updated or removed recently, and nothing changed from the console.")}</div> : (
              <ul className="px-4 py-2.5 font-mono text-xs leading-7">
                {log.map((r, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="w-24 shrink-0 text-muted-foreground tabular">{when(r.ts)}</span>
                    <span className={cn("w-16 shrink-0", r.tone)}>{r.kind}</span>
                    <span className="min-w-0 truncate" title={r.text}>{r.text}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <div className="grid items-start gap-4 min-[1300px]:grid-cols-2">
            <Panel title="Security" to="/security">{read(d.security, p => !p.enabled ? off() : <div className="space-y-4">
              {(p.top ?? []).length ? <div className="divide-y">{p.top?.map(app => <div key={app.name} className="space-y-1.5 py-2.5 first:pt-0"><div className="flex flex-wrap items-baseline justify-between gap-2"><span className="text-sm font-medium">{app.name}</span><span className="path text-xs text-muted-foreground">{app.version}</span></div><div className="flex flex-wrap items-center gap-2"><span className="text-xs text-muted-foreground tabular">{app.cves} known flaws</span>{app.kev > 0 && <Badge variant="danger">{app.kev} used in real attacks</Badge>}{app.critical > 0 && <Badge variant="warning">{app.critical} critical</Badge>}{app.update_to && <span className="path text-xs text-success">fix: {app.update_to}</span>}</div></div>)}</div> : quiet("No affected programs reported.")}
              <div className="border-t pt-3"><h3 className="label-caps mb-2 text-muted-foreground">Open to the network</h3>{(p.exposed ?? []).length ? <div className="space-y-1.5">{p.exposed?.map(s => <div key={s.name} className="flex flex-wrap items-center gap-2 text-sm"><span className="flex-1">{s.name}</span><span className="path text-xs text-muted-foreground">{s.ports.join(", ")}</span>{s.cves > 0 && <Badge variant="danger">{s.cves} known flaws</Badge>}</div>)}</div> : quiet("No services open to the network reported.")}</div>
              <p className="border-t pt-3 text-xs text-muted-foreground">{number(p.recognised)} of {number(p.installed)} programs could be compared · CVE list updated {when(p.database?.synced_at)}</p>{p.database?.error && quiet(`Could not be read: ${p.database.error}`)}
            </div>)}</Panel>
            {d.network && <Panel title="Network" to="/network">{read(d.network, p => !p.read_at ? quiet("Being read… this takes a few seconds after a restart.") : <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-sm"><span className="font-medium">Windows Firewall</span>{p.firewall?.state == null ? <Badge variant="muted">Unknown</Badge> : <Badge variant={p.firewall.state === "on" ? "success" : "danger"}>{p.firewall.state === "on" ? "On" : p.firewall.state === "off" ? "Off" : "Partly off"}</Badge>}{!!p.firewall?.off.length && p.firewall.state === "partly" && <span className="text-xs text-muted-foreground">off for {p.firewall.off.join(", ")}</span>}</div>
              {p.interfaces.length ? <div className="divide-y border-t">{p.interfaces.map(a => <div key={a.name} className="space-y-1 py-2.5"><div className="flex flex-wrap items-center gap-2"><span className="text-sm font-medium">{a.name}</span><Badge variant="muted">{a.kind === "wifi" ? "Wi-Fi" : a.kind === "vpn" ? "VPN" : "Ethernet"}</Badge>{a.internet && <Badge variant="success">Internet</Badge>}{a.category && <Badge variant={a.category === "public" ? "info" : "warning"}>{a.category === "public" ? "Public" : a.category === "private" ? "Private" : "Domain"}</Badge>}<span className="ml-auto text-xs tabular text-muted-foreground">{speed(a.speed)}</span></div><div className="path text-xs text-muted-foreground tabular">{a.address ?? "no address"}{a.gateway && ` · gateway ${a.gateway}`}{a.ssid && ` · ${a.ssid}`}</div></div>)}</div> : quiet("No network interface is connected.")}
              <div className="grid grid-cols-3 gap-4 border-t pt-3"><Stat label="Open to network" value={number(p.counts.listening_network_other)} sub="ports, not Windows'" /><Stat label="Connections" value={number(p.counts.connections)} sub={`${number(p.counts.programs_connected)} programs`} /><Stat label="Devices seen" value={number(p.counts.devices)} /></div>
            </div>)}</Panel>}
          </div>
        </div>

        <div className="min-w-0 space-y-4">
          <Panel title="Files, last 7 days" to="/activity">{read(d.activity, p => {
            const max = Math.max(1, ...p.days.flatMap(x => [x.arrived, x.filed, x.deleted]));
            return <div className="space-y-3">
              <div className="flex h-28 items-end gap-2">{p.days.map(day => <Tip key={day.date} tip={`${day.date}: ${day.arrived} arrived · ${day.filed} filed · ${day.deleted} deleted`}><div tabIndex={0} className="flex h-full min-w-0 flex-1 flex-col justify-end"><div className="flex h-24 items-end justify-center gap-0.5">{(["arrived", "filed", "deleted"] as const).map((key, i) => <div key={key} className={cn("w-2", ["bg-primary", "bg-primary/45", "bg-warning"][i])} style={{ height: `${day[key] / max * 100}%` }} />)}</div><div className="mt-1.5 text-center font-mono text-[10px] text-muted-foreground">{new Date(day.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" }).slice(0, 2)}</div></div></Tip>)}</div>
              <div className="grid grid-cols-3 gap-2 font-mono"><div><div className="text-lg font-semibold text-primary tabular">{number(p.totals.arrived)}</div><div className="text-[11px] text-muted-foreground">arrived</div></div><div><div className="text-lg font-semibold tabular">{number(p.totals.filed)}</div><div className="text-[11px] text-muted-foreground">filed{p.totals.auto_filed ? `, ${p.totals.auto_filed} auto` : ""}</div></div><div><div className="text-lg font-semibold text-warning tabular">{number(p.totals.deleted)}</div><div className="text-[11px] text-muted-foreground">deleted · {bytes(p.totals.deleted_bytes)}</div></div></div>
            </div>;
          })}</Panel>

          <Panel title="Dates coming up" to="/watch">{read(d.watch, p => !p.enabled ? off() : <><div className="divide-y">{(p.next ?? []).length ? p.next?.map((date, i) => <div key={i} className="py-2.5 first:pt-0"><div className="mb-1 flex flex-wrap items-center gap-2 text-xs"><span className="font-mono font-medium tabular">{date.date}</span><span className="text-muted-foreground">{date.days === 0 ? "today" : date.days > 0 ? `in ${date.days} days` : `${Math.abs(date.days)} days ago`}</span><Badge variant="muted">{date.kind}</Badge></div><p className="path truncate text-sm" title={date.name}>{date.name}</p></div>) : quiet("No dates coming up.")}</div><p className="mt-3 border-t pt-3 text-xs text-muted-foreground tabular">{number(p.counts?.sensitive)} sensitive files in Downloads</p></>)}</Panel>

          <Panel title="System" to="/settings">
            {read(d.storage, p => p.volumes.length ? <div className="space-y-3">{p.volumes.map(v => { const free = v.bytes > 0 ? v.free / v.bytes : 1; return <div key={v.letter}><div className="mb-1.5 flex flex-wrap justify-between gap-2 font-mono text-xs"><span>{v.letter} {v.label}</span><span className={cn("tabular", free < .1 ? "text-destructive" : free < .15 ? "text-warning" : "text-muted-foreground")}>{Math.round((1 - free) * 100)}% used</span></div><Bar value={1 - free} tone={free < .1 ? "destructive" : free < .15 ? "warning" : "primary"} label={`${v.letter} used space`} /></div>; })}</div> : quiet("No volumes reported."))}
            {read(d.agent, p => <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 border-t pt-3 font-mono text-xs">
              <dt className="text-muted-foreground">agent</dt><dd className="flex flex-wrap items-center gap-1.5">{p.watching ? "watching Downloads" : "not watching"}{p.restart_needed && <Badge variant="warning">restart needed</Badge>}</dd>
              <dt className="text-muted-foreground">since</dt><dd>{p.started ? when(p.started) : "—"}</dd>
              <dt className="text-muted-foreground">model</dt><dd>{p.model || "—"} {p.model_ok ? "" : <span className="text-warning">unavailable</span>}</dd>
              <dt className="text-muted-foreground">index</dt><dd>{p.search ? `${number(p.search.files)} files${p.search.queued ? ` · ${number(p.search.queued)} queued` : ""}${p.search.running ? " · indexing" : ""}` : "—"}</dd>
              {sec?.database && <><dt className="text-muted-foreground">cve list</dt><dd>{number(sec.database.cves)} CVEs · {when(sec.database.synced_at)}</dd></>}
              {p.problem && <><dt className="text-muted-foreground">problem</dt><dd className="text-destructive">{p.problem}</dd></>}
            </dl>)}
          </Panel>

          <Panel title="Applications" to="/library">
            {read(d.apps, p => !p.enabled ? off() : (p.recent ?? []).length ? <div className="divide-y">{p.recent?.slice(0, 5).map((app, i) => <div key={i} className="space-y-1 py-2 first:pt-0"><div className="flex flex-wrap items-center gap-2"><Badge variant={app.event === "installed" ? "success" : app.event === "updated" ? "info" : "muted"}>{app.event === "installed" ? "Installed" : app.event === "updated" ? "Updated" : "Removed"}</Badge><span className="text-xs text-muted-foreground">{when(app.ts)}</span></div><div className="break-words text-sm font-medium">{app.name}</div></div>)}</div> : quiet("No recent application changes."))}
            {read(d.remedy, p => !p.enabled || !p.recent.length ? null : <div className="mt-3 space-y-2 border-t pt-3">{p.recent.slice(0, 3).map((r, i) => <div key={i} className="flex items-start gap-2 text-sm">{r.ok ? <Check className="mt-0.5 size-4 shrink-0 text-success" aria-label="Succeeded" /> : <X className="mt-0.5 size-4 shrink-0 text-destructive" aria-label="Failed" />}<span>{r.message}</span></div>)}</div>)}
          </Panel>
        </div>
      </div>
    </div>}
  </>;
}
