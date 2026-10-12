import type { ReactNode } from "react";
import { ArrowUpRight, Check, Circle, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes, when } from "@/lib/format";
import type { DashboardResponse, Part } from "@/lib/types";
import { Bar, Card, ListSkeleton, LoadError, Notice, PageHeader, Stat, Tip } from "../ui";

const number = (n: number | undefined) => n == null ? "—" : n.toLocaleString();
const quiet = (text: string) => <p className="text-sm text-muted-foreground">{text}</p>;
const off = () => quiet("Off · Turn on in Settings");
function read<T extends object>(part: Part<T>, children: (value: T) => ReactNode) {
  return "error" in part ? quiet(`Could not be read: ${part.error}`) : children(part);
}
function Panel({ title, to, children }: { title: string; to: string; children: ReactNode }) {
  return <Card className="min-w-0 overflow-hidden rounded-lg"><a href={"#" + to} className="block h-full p-5 transition-colors hover:bg-muted/30 focus-visible:outline-2 focus-visible:outline-ring"><div className="mb-4 flex items-center justify-between gap-3"><h2 className="text-sm font-semibold">{title}</h2><ArrowUpRight className="size-4 text-muted-foreground" aria-hidden /></div>{children}</a></Card>;
}
function Tile<T extends object>({ title, to, part, children }: { title: string; to: string; part: Part<T>; children: (p: T) => ReactNode }) {
  return <Card className="min-w-0 rounded-lg"><a href={"#" + to} className="block h-full p-4 transition-colors hover:bg-muted/30 focus-visible:outline-2 focus-visible:outline-ring"><div className="mb-2 text-xs font-medium text-muted-foreground">{title}</div>{read(part, children)}</a></Card>;
}
const tileValue = (value: ReactNode, sub: ReactNode) => <><div className="text-2xl font-semibold tabular">{value}</div><div className="mt-1 text-xs leading-relaxed text-muted-foreground">{sub}</div></>;

export function DashboardPage() {
  const q = usePoll<DashboardResponse>(api.dashboard, 60_000);
  const d = q.data;
  return <>
    <PageHeader title="Dashboard" sub="What needs attention on this PC, and what happened this week." actions={<><span className="text-xs text-muted-foreground">{d ? `Updated ${when(d.generated_at)}` : ""}</span><Button variant="outline" size="sm" onClick={() => void q.reload()}><RefreshCw className="size-4" />Refresh</Button></>} />
    {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
    {!d ? (!q.error && <ListSkeleton rows={5} />) : <div className="space-y-6">
      <section aria-labelledby="attention-title">
        <h2 id="attention-title" className="mb-3 text-sm font-semibold">Needs attention</h2>
        {d.attention.length ? <div className="divide-y rounded-lg border bg-card">{d.attention.map((a, i) => <a key={i} href={"#" + a.to} className="flex items-start gap-3 px-4 py-2.5 text-sm transition-colors hover:bg-muted/40 focus-visible:outline-2 focus-visible:outline-ring"><Circle aria-label={a.level} className={`mt-1 size-2 shrink-0 fill-current ${a.level === "danger" ? "text-destructive" : a.level === "warning" ? "text-warning" : "text-primary"}`} /><span className="min-w-0 flex-1">{a.text}</span><ArrowUpRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden /></a>)}</div> : <Notice tone="success" icon={<Check />}>Nothing needs your attention.</Notice>}
      </section>
      <div className="grid grid-cols-1 gap-3 min-[1000px]:grid-cols-5">
        <Tile title="Inbox waiting" to="/inbox" part={d.inbox}>{p => tileValue(number(p.waiting), `${p.added_7d} new this week · oldest ${p.oldest_days == null ? "—" : p.oldest_days} days`)}</Tile>
        <Tile title="Flaws in installed software" to="/security" part={d.security}>{p => !p.enabled ? tileValue("Off", "Turn on in Settings") : tileValue(<span className={p.summary?.kev ? "text-destructive" : undefined}>{number(p.summary?.kev)} <span className="text-sm font-normal text-muted-foreground">/ {number(p.summary?.critical)}</span></span>, "used in real attacks / critical")}</Tile>
        <Tile title="Newer versions available" to="/library" part={d.apps}>{p => !p.enabled ? tileValue("Off", "Turn on in Settings") : tileValue(p.updates_checked ? number(p.updates) : "—", <>of {number(p.programs)} programs{!p.updates_checked && " · not checked"}</>)}</Tile>
        <Tile title="Dates coming up" to="/watch" part={d.watch}>{p => !p.enabled ? tileValue("Off", "Turn on in Settings") : tileValue(number(p.counts?.soon), "in your documents")}</Tile>
        <Tile title="Safe to remove" to="/cleanup" part={d.cleanup}>{p => tileValue(number(p.safe.count), `${bytes(p.safe.bytes)} in Downloads`)}</Tile>
      </div>
      <Panel title="This week" to="/activity">{read(d.activity, p => <div className="grid gap-6 min-[1000px]:grid-cols-2">
        <div><div className="flex h-32 items-end justify-between gap-2">{p.days.map(day => { const max = Math.max(1, ...p.days.flatMap(x => [x.arrived, x.filed, x.deleted])); return <Tip key={day.date} tip={`${day.date}: ${day.arrived} arrived · ${day.filed} filed · ${day.deleted} deleted`}><div tabIndex={0} className="flex h-full min-w-0 flex-1 flex-col justify-end"><div className="flex h-24 items-end justify-center gap-1">{(["arrived", "filed", "deleted"] as const).map((key, i) => <div key={key} className={`w-3 rounded-t-sm ${["bg-primary", "bg-success", "bg-warning"][i]}`} style={{ height: `${day[key] / max * 100}%` }} />)}</div><div className="mt-2 text-center text-xs text-muted-foreground">{new Date(day.date + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" })}</div></div></Tip>; })}</div><div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">{[["Arrived", "bg-primary"], ["Filed", "bg-success"], ["Deleted", "bg-warning"]].map(([label, color]) => <span key={label} className="flex items-center gap-1.5"><span className={`size-2 rounded-sm ${color}`} />{label}</span>)}</div></div>
        <div className="grid grid-cols-2 gap-4"><Stat label="Arrived" value={number(p.totals.arrived)} sub="in Downloads" /><Stat label="Filed" value={number(p.totals.filed)} sub={`${p.totals.auto_filed} automatically`} /><Stat label="Deleted" value={number(p.totals.deleted)} sub={bytes(p.totals.deleted_bytes)} /><Stat label="Application changes" value={number(p.totals.apps)} sub={`${p.totals.active_days} active days`} /></div>
      </div>)}</Panel>
      <div className="grid grid-cols-1 items-start gap-6 min-[1000px]:grid-cols-2">
        <Panel title="Security" to="/security">{read(d.security, p => !p.enabled ? off() : <div className="space-y-4">
          {(p.top ?? []).length ? <div className="divide-y">{p.top?.map(app => <div key={app.name} className="space-y-2 py-3 first:pt-0"><div className="flex flex-wrap items-baseline justify-between gap-2"><span className="text-sm font-medium">{app.name}</span><span className="path text-xs text-muted-foreground">{app.version}</span></div><div className="flex flex-wrap items-center gap-2"><span className="text-xs text-muted-foreground tabular">{app.cves} known flaws</span>{app.kev > 0 && <Badge variant="danger">{app.kev} used in real attacks</Badge>}{app.critical > 0 && <Badge variant="warning">{app.critical} critical</Badge>}{app.update_to && <span className="path text-xs text-success">fix: {app.update_to}</span>}</div></div>)}</div> : quiet("No affected programs reported.")}
          <div className="border-t pt-4"><h3 className="mb-2 text-xs font-medium text-muted-foreground">Open to the network</h3>{(p.exposed ?? []).length ? <div className="space-y-2">{p.exposed?.map(s => <div key={s.name} className="flex flex-wrap items-center gap-2 text-sm"><span className="flex-1">{s.name}</span><span className="path text-xs text-muted-foreground">{s.ports.join(", ")}</span>{s.cves > 0 && <Badge variant="danger">{s.cves} known flaws</Badge>}</div>)}</div> : quiet("No services open to the network reported.")}</div>
          <p className="border-t pt-3 text-xs leading-relaxed text-muted-foreground">{number(p.recognised)} of {number(p.installed)} programs could be compared · CVE list updated {when(p.database?.synced_at)}</p>{p.database?.error && quiet(`Could not be read: ${p.database.error}`)}
        </div>)}</Panel>
        <div className="space-y-6">
          <Panel title="Dates coming up" to="/watch">{read(d.watch, p => !p.enabled ? off() : <><div className="divide-y">{(p.next ?? []).length ? p.next?.map((date, i) => <div key={i} className="py-3 first:pt-0"><div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs"><span className="tabular font-medium">{date.date}</span><span className="text-muted-foreground">{date.days === 0 ? "today" : date.days > 0 ? `in ${date.days} days` : `${Math.abs(date.days)} days ago`}</span><Badge variant="muted">{date.kind}</Badge></div><p className="path truncate text-sm" title={date.name}>{date.name}</p></div>) : quiet("No dates coming up.")}</div><p className="mt-3 border-t pt-3 text-xs text-muted-foreground tabular">{number(p.counts?.sensitive)} sensitive files in Downloads</p></>)}</Panel>
          <Panel title="Storage" to="/cleanup">{read(d.storage, p => p.volumes.length ? <div className="space-y-4">{p.volumes.map(v => { const free = v.bytes > 0 ? v.free / v.bytes : 1; return <div key={v.letter}><div className="mb-2 flex flex-wrap justify-between gap-2 text-xs"><span className="font-medium">{v.letter} {v.label}</span><span className="tabular text-muted-foreground">{bytes(v.free)} free of {bytes(v.bytes)}</span></div><Bar value={1 - free} tone={free < .1 ? "destructive" : free < .15 ? "warning" : "primary"} label={`${v.letter} used space`} /></div>; })}</div> : quiet("No volumes reported."))}</Panel>
        </div>
        <Panel title="Applications" to="/library">
          {read(d.apps, p => !p.enabled ? off() : (p.recent ?? []).length ? <div className="divide-y">{p.recent?.map((app, i) => <div key={i} className="space-y-1.5 py-3 first:pt-0"><div className="flex flex-wrap items-center gap-2"><Badge variant={app.event === "installed" ? "success" : app.event === "updated" ? "info" : "muted"}>{app.event === "installed" ? "Installed" : app.event === "updated" ? "Updated" : "Removed"}</Badge><span className="text-xs text-muted-foreground">{when(app.ts)}</span></div><div className="break-words text-sm font-medium">{app.name}</div><div className="path text-xs text-muted-foreground">{app.event === "updated" ? `${app.old_version || "—"} → ${app.new_version || "—"}` : (app.event === "removed" ? app.old_version : app.new_version) || "—"}</div></div>)}</div> : quiet("No recent application changes."))}
          <div className="mt-4 border-t pt-4"><h3 className="mb-3 text-xs font-medium text-muted-foreground">Recent updates and stops</h3>{read(d.remedy, p => !p.enabled ? off() : <>{p.running && quiet("Updates or stops are running…")}{p.recent.length ? <div className="space-y-3">{p.recent.map((r, i) => <div key={i} className="flex items-start gap-2">{r.ok ? <Check className="mt-0.5 size-4 shrink-0 text-success" aria-label="Succeeded" /> : <X className="mt-0.5 size-4 shrink-0 text-destructive" aria-label="Failed" />}<div><p className="text-sm leading-relaxed">{r.message}</p><p className="mt-1 text-xs text-muted-foreground">{when(r.ts)}</p></div></div>)}</div> : quiet("No recent updates or stops.")}</>)}</div>
        </Panel>
        <Panel title="Agent" to="/settings">{read(d.agent, p => <div className="space-y-3 text-sm"><div className="flex flex-wrap items-center gap-2"><span className={`size-2 rounded-full ${p.watching ? "bg-success" : "bg-warning"}`} /><span className="font-medium">{p.watching ? "Watching Downloads" : "Not watching Downloads"}</span>{p.restart_needed && <Badge variant="warning">Restart needed</Badge>}</div><div className="flex flex-wrap items-center gap-2"><span className="path">{p.model || "—"}</span><Badge variant={p.model_ok ? "success" : "warning"}>{p.model_ok ? "available" : "unavailable"}</Badge></div>{p.problem && <p className="text-destructive">{p.problem}</p>}{p.search ? <p className="text-muted-foreground tabular">{number(p.search.files)} files indexed{p.search.queued > 0 && ` · ${number(p.search.queued)} queued`}{p.search.running && " · indexing…"}</p> : quiet("Search index not reported.")}<p className="text-xs text-muted-foreground">{p.started ? `Running since ${when(p.started)}` : "Start time not reported."}</p></div>)}</Panel>
      </div>
    </div>}
  </>;
}
