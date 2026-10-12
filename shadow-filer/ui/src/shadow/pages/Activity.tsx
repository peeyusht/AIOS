import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, ArrowRight, BookOpen, ChevronDown, Copy } from "lucide-react";
import { toast } from "sonner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useDebounced, usePoll } from "@/lib/hooks";
import { bytes, dateTime, pct } from "@/lib/format";
import type { JournalDay, Prediction, StatsBucket } from "@/lib/types";
import { Card, EmptyState, ListSkeleton, LoadError, Mono, PageHeader, Segmented, Stat } from "../ui";

export function ActivityPage() {
  return (
    <>
      <PageHeader title="Activity" sub="What happened day by day, and how well suggestions match where you file things." />
      <Tabs defaultValue="journal">
        <TabsList className="mb-6">
          <TabsTrigger value="journal">Journal</TabsTrigger>
          <TabsTrigger value="accuracy">Accuracy</TabsTrigger>
          <TabsTrigger value="predictions">Predictions</TabsTrigger>
          <TabsTrigger value="log">Log</TabsTrigger>
        </TabsList>
        <TabsContent value="journal"><Journal /></TabsContent>
        <TabsContent value="accuracy"><Accuracy /></TabsContent>
        <TabsContent value="predictions"><Predictions /></TabsContent>
        <TabsContent value="log"><Log /></TabsContent>
      </Tabs>
    </>
  );
}

type Range = "7" | "30" | "90";

function Journal() {
  const [range, setRange] = useState<Range>("30");
  const q = usePoll(() => api.journal(Number(range)), 60_000, [range]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(q.data?.text ?? ""); toast.success("Copied the journal as text"); }
    catch { toast.error("Could not copy"); }
  };
  const d = q.data;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented label="Period" value={range} onChange={setRange}
          options={[{ value: "7", label: "Last 7 days" }, { value: "30", label: "30 days" }, { value: "90", label: "90 days" }]} />
        <Button variant="outline" size="sm" className="ml-auto" onClick={copy} disabled={!d}><Copy /> Copy as text</Button>
      </div>
      {q.error && !d && <LoadError error={q.error} onRetry={q.reload} />}
      {!d && !q.error && <ListSkeleton rows={4} h="h-24" />}
      {d && (
        <>
          <Card className="grid grid-cols-5 gap-4 p-5 max-[1100px]:grid-cols-3">
            <Stat label="Arrived" value={d.totals.arrived.toLocaleString()} />
            <Stat label="Filed" value={d.totals.filed.toLocaleString()} sub={d.totals.auto_filed > 0 ? `${d.totals.auto_filed} automatically` : undefined} />
            <Stat label="Deleted" value={d.totals.deleted.toLocaleString()} sub={d.totals.deleted ? `${bytes(d.totals.deleted_bytes)} freed` : undefined} />
            <Stat label="Documents added or changed" value={d.totals.worked_files.toLocaleString()} />
            <Stat label="Active days" value={d.totals.active_days.toLocaleString()} />
          </Card>
          {(d.totals.apps ?? 0) > 0 && <p className="-mt-3 text-sm text-muted-foreground tabular">{d.totals.apps} application {d.totals.apps === 1 ? "change" : "changes"}</p>}
          {d.folders.length > 0 && (
            <Card className="overflow-x-auto p-5">
              <h3 className="mb-3 text-sm font-medium">By folder</h3>
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr><th className="pb-2 font-medium">Folder</th><th className="pb-2 text-right font-medium">Added or changed</th><th className="pb-2 text-right font-medium">Filed</th><th className="pb-2 text-right font-medium">Days</th></tr>
                </thead>
                <tbody>
                  {d.folders.slice(0, 10).map((f) => (
                    <tr key={f.folder} className="border-t">
                      <td className="py-1.5"><Mono className="text-xs">{folderName(f.folder)}</Mono></td>
                      <td className="text-right tabular">{f.worked}</td><td className="text-right tabular">{f.filed}</td><td className="text-right tabular">{f.days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {d.folders.length > 10 && <p className="mt-2 text-xs text-muted-foreground">and {d.folders.length - 10} more folders</p>}
            </Card>
          )}
          {d.days.length === 0 ? (
            <EmptyState icon={<BookOpen />} title="Nothing recorded in this period.">The journal fills in as files arrive, get filed and change.</EmptyState>
          ) : d.days.map((day) => <DayCard key={day.date} day={day} />)}
          <p className="text-xs text-muted-foreground">Built from what the agent already records, plus file dates. A day's 'worked on' list is complete only for days the agent was running.</p>
        </>
      )}
    </div>
  );
}

const folderName = (f: string) => f || "(top of your folders)";

function dayLabel(date: string) {
  const [y = 0, m = 1, dd = 1] = date.split("-").map(Number);
  const d = new Date(y, m - 1, dd);
  const t = new Date(); t.setHours(0, 0, 0, 0);
  const diff = Math.round((t.getTime() - d.getTime()) / 86400000);
  const full = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  return { rel: diff === 0 ? "Today" : diff === 1 ? "Yesterday" : null, full };
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className="space-y-1 text-sm">{children}</div>
    </div>
  );
}

const Time = ({ t }: { t: string }) => <span className="w-12 shrink-0 text-xs text-muted-foreground tabular">{t}</span>;

function DayCard({ day }: { day: JournalDay }) {
  const [showDel, setShowDel] = useState(false);
  const [allArr, setAllArr] = useState(false);
  const { rel, full } = dayLabel(day.date);
  const c = day.counts;
  const chips = [[c.arrived, "arrived"], [c.filed, "filed"], [c.deleted, "deleted"], [c.worked_files, "worked on"]] as const;
  const arr = allArr ? day.arrived : day.arrived.slice(0, 5);
  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-medium">{rel ?? day.weekday} <span className={cn(rel ? "font-normal text-muted-foreground" : "")}>{rel ? `${day.weekday} ${full}` : full}</span></h3>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {chips.filter(([n]) => n > 0).map(([n, l]) => <Badge key={l} variant="muted" className="tabular">{n} {l}</Badge>)}
        </div>
      </div>
      {day.worked.length > 0 && (
        <Section title="Worked on">
          {day.worked.map((w) => (
            <div key={w.folder} className="flex flex-wrap items-center gap-2">
              <Mono className="text-xs">{folderName(w.folder)}</Mono>
              <span className="text-xs text-muted-foreground tabular">{w.count} {w.count === 1 ? "document" : "documents"}</span>
              {w.files.slice(0, 4).map((f) => (
                <span key={f.path} className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-xs text-muted-foreground" title={f.kind === "changed" ? "edited" : "added"}>
                  {f.kind === "changed" && <span className="size-1.5 rounded-full bg-primary" aria-label="edited" />}{f.name}
                </span>
              ))}
              {w.count > 4 && <span className="text-xs text-muted-foreground">+{w.count - 4} more</span>}
            </div>
          ))}
        </Section>
      )}
      {day.filed.length > 0 && (
        <Section title="Filed">
          {day.filed.map((f, i) => (
            <div key={i} className={cn("flex items-center gap-2", f.undone && "line-through decoration-muted-foreground/60 opacity-70")}>
              <Time t={f.time} />
              <Mono className="min-w-0 truncate text-xs" title={f.path ?? ""}>{f.name}</Mono>
              <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
              <Mono className="min-w-0 truncate text-xs">{folderName(f.folder)}</Mono>
              {f.how === "hand" && <Badge variant="muted">by hand</Badge>}
              {f.how === "auto" && <Badge variant="info">auto</Badge>}
              {f.undone && <Badge variant="muted">undone</Badge>}
            </div>
          ))}
        </Section>
      )}
      {day.undone.length > 0 && (
        <Section title="Undone">
          {day.undone.map((u, i) => (
            <div key={i} className="flex items-center gap-2"><Time t={u.time} /><Mono className="min-w-0 truncate text-xs">{u.name}</Mono><span className="text-xs text-muted-foreground">moved back to Downloads</span></div>
          ))}
        </Section>
      )}
      {(day.apps ?? []).length > 0 && (
        <Section title="Applications">
          {(day.apps ?? []).map((a, i) => (
            <div key={i} className="flex items-center gap-2">
              <Time t={a.time} />
              <Badge variant={a.event === "installed" ? "success" : a.event === "updated" ? "info" : "muted"}>{a.event === "installed" ? "Installed" : a.event === "updated" ? "Updated" : "Removed"}</Badge>
              <span className="min-w-0 truncate">
                {a.event === "updated" ? <>{a.name}: <span className="tabular">{a.old_version} → {a.new_version}</span></> : <>{a.name} <span className="tabular">{a.event === "installed" ? a.new_version : a.old_version}</span></>}
              </span>
            </div>
          ))}
        </Section>
      )}
      {c.deleted > 0 && (
        <Section title="Deleted">
          <button className="flex items-center gap-1 text-left" aria-expanded={showDel} onClick={() => setShowDel(!showDel)}>
            <ChevronDown className={cn("size-3.5 text-muted-foreground transition-transform", showDel && "rotate-180")} />
            {c.deleted} {c.deleted === 1 ? "file" : "files"} · {bytes(c.deleted_bytes)} to the Recycle Bin
          </button>
          {showDel && day.deleted.map((x, i) => (
            <div key={i} className="flex items-center gap-2 pl-5"><Time t={x.time} /><Mono className="min-w-0 truncate text-xs" title={x.path}>{x.name}</Mono><span className="ml-auto text-xs text-muted-foreground tabular">{bytes(x.size)}</span></div>
          ))}
        </Section>
      )}
      {day.arrived.length > 0 && (
        <Section title="Arrived">
          {arr.map((a, i) => (
            <div key={i} className="flex items-center gap-2">
              <Time t={a.time} />
              <Mono className="min-w-0 truncate text-xs" title={a.path}>{a.name}</Mono>
              <span className="text-xs text-muted-foreground tabular">{bytes(a.size)}</span>
              {a.suggested && <span className="min-w-0 truncate text-xs text-muted-foreground">→ <span className="path">{a.suggested}</span></span>}
              {!a.still_there && <span className="ml-auto shrink-0 text-xs text-muted-foreground">no longer in Downloads</span>}
            </div>
          ))}
          {day.arrived.length > 5 && !allArr && <Button variant="ghost" size="sm" onClick={() => setAllArr(true)}>Show all {c.arrived}</Button>}
        </Section>
      )}
    </Card>
  );
}

function Accuracy() {
  const q = usePoll(api.stats, 60_000);
  if (q.error && !q.data) return <LoadError error={q.error} onRetry={q.reload} />;
  if (!q.data) return <ListSkeleton rows={3} h="h-28" />;
  const s = q.data;
  return (
    <div className="space-y-6">
      <Card className="grid grid-cols-6 gap-4 p-5 max-[1100px]:grid-cols-3">
        <Stat label="Predictions" value={s.total.toLocaleString()} />
        <Stat label="Filed & scored" value={s.filed.toLocaleString()} />
        <Stat label="Still unfiled" value={s.unfiled.toLocaleString()} />
        <Stat label="Model unsure" value={s.unsure.toLocaleString()} />
        <Stat label="Errors" value={s.errors.toLocaleString()} />
        <Stat label="Period" value={<span className="text-sm font-medium">{s.period ? `${dateTime(s.period[0])} – ${dateTime(s.period[1])}` : "—"}</span>} />
      </Card>
      {s.overall && (
        <div className="grid grid-cols-2 gap-4">
          <Card className="p-6">
            <div className="text-sm text-muted-foreground">Exact folder</div>
            <div className="mt-1 text-5xl font-semibold tracking-tight tabular">{pct(s.overall.exact)}</div>
            <div className="mt-1 text-xs text-muted-foreground">of {s.overall.n.toLocaleString()} filed documents, compared {s.depth} levels deep</div>
          </Card>
          <Card className="p-6">
            <div className="text-sm text-muted-foreground">Same category</div>
            <div className="mt-1 text-5xl font-semibold tracking-tight tabular">{pct(s.overall.top)}</div>
            <div className="mt-1 text-xs text-muted-foreground">right top-level folder (Projects, Areas, …)</div>
          </Card>
        </div>
      )}
      <div className="grid grid-cols-2 gap-4 max-[1100px]:grid-cols-1">
        <Bars title="By method" rows={s.by_method} />
        <Bars title="By the model's stated confidence" rows={s.by_conf} />
      </div>
      <Card className="p-5">
        <h3 className="mb-3 text-sm font-medium">Most common misses</h3>
        {s.misses.length === 0 ? <p className="text-sm text-muted-foreground">No misses yet.</p> : (
          <ul className="space-y-2 text-sm">
            {s.misses.map((m, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <Mono className="text-xs text-muted-foreground">{m.predicted}</Mono><ArrowRight className="size-3.5 text-muted-foreground" /><Mono className="text-xs">{m.actual}</Mono>
                <Badge variant="muted" className="ml-auto tabular">× {m.n}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Bars({ title, rows }: { title: string; rows: StatsBucket[] }) {
  return (
    <Card className="p-5">
      <h3 className="mb-4 text-sm font-medium">{title}</h3>
      <div className="space-y-4">
        {rows.map((r) => (
          <div key={r.label}>
            <div className="mb-1 flex justify-between text-sm"><span className="font-mono text-xs">{r.label}</span><span className="text-xs text-muted-foreground tabular">n = {r.n}</span></div>
            <div className="relative h-5 overflow-hidden rounded bg-muted" role="img" aria-label={`${r.label}: exact ${pct(r.exact)}, same category ${pct(r.top)}`}>
              <div className="absolute inset-y-0 left-0 bg-primary/25" style={{ width: `${r.top * 100}%` }} />
              <div className="absolute inset-y-0 left-0 bg-primary" style={{ width: `${r.exact * 100}%` }} />
              <span className="absolute inset-y-0 right-2 flex items-center text-xs font-medium tabular">{pct(r.exact)} · {pct(r.top)}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 flex gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-primary" />Exact folder</span>
        <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-primary/25" />Same category</span>
      </div>
    </Card>
  );
}

const OUTCOME: Record<Prediction["outcome"], { label: string; v: "success" | "danger" | "muted" | "warning" }> = {
  match: { label: "Match", v: "success" }, miss: { label: "Miss", v: "danger" }, pending: { label: "Pending", v: "muted" }, unsure: { label: "Unsure", v: "warning" }, error: { label: "Error", v: "danger" },
};

function Predictions() {
  const [view, setView] = useState("all");
  const [text, setText] = useState("");
  const dq = useDebounced(text, 300);
  const q = usePoll(() => api.predictions(view, dq), null, [view, dq]);
  const [open, setOpen] = useState<number | null>(null);
  const views = ["all", "pending", "match", "miss", "unsure", "error"];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {views.map((v) => (
          <button key={v} onClick={() => setView(v)} aria-pressed={view === v}
            className={cn("rounded-full border px-3 py-1 text-sm capitalize transition-colors", view === v ? "border-primary bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted")}>
            {v}
          </button>
        ))}
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Search file or folder" aria-label="Search predictions" className="ml-auto h-8 w-64" />
      </div>
      {q.error && !q.data && <LoadError error={q.error} onRetry={q.reload} />}
      {!q.data && !q.error ? <ListSkeleton rows={6} h="h-10" /> : q.data && (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs text-muted-foreground">
              <tr><th className="px-4 py-2 font-medium">Time</th><th className="px-3 font-medium">File</th><th className="px-3 font-medium">Method</th><th className="px-3 font-medium">Predicted</th><th className="px-3 font-medium">Confidence</th><th className="px-3 font-medium">Actually filed</th><th className="px-4 font-medium">Outcome</th></tr>
            </thead>
            <tbody>
              {q.data.rows.length === 0 && <tr><td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">No predictions match.</td></tr>}
              {q.data.rows.map((p) => (
                <Fragment key={p.id}>
                  <tr className="cursor-pointer border-t hover:bg-muted/40" onClick={() => setOpen(open === p.id ? null : p.id)}>
                    <td className="px-4 py-2 whitespace-nowrap text-xs text-muted-foreground tabular">{dateTime(p.ts)}</td>
                    <td className="max-w-56 truncate px-3 py-2">
                      <button className="flex items-center gap-1 text-left" aria-expanded={open === p.id} onClick={(e) => { e.stopPropagation(); setOpen(open === p.id ? null : p.id); }}>
                        <ChevronDown className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open === p.id && "rotate-180")} />
                        <span className="truncate" title={p.path}>{p.filename}</span>
                      </button>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{p.method}</td>
                    <td className="px-3 py-2"><Mono className="text-xs">{p.predicted ?? "—"}</Mono></td>
                    <td className="px-3 py-2 text-xs">{p.confidence ?? "—"}</td>
                    <td className="px-3 py-2"><Mono className="text-xs">{p.actual ?? "—"}</Mono></td>
                    <td className="px-4 py-2"><Badge variant={OUTCOME[p.outcome].v}>{OUTCOME[p.outcome].label}</Badge></td>
                  </tr>
                  {open === p.id && <tr className="bg-muted/30"><td /><td colSpan={6} className="px-3 py-2 text-xs text-muted-foreground">{p.reason}</td></tr>}
                </Fragment>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function Log() {
  const [auto, setAuto] = useState(true);
  const q = usePoll(api.log, auto ? 5_000 : null, [auto]);
  const [filter, setFilter] = useState("");
  const box = useRef<HTMLDivElement>(null);
  const lines = useMemo(() => (q.data?.lines ?? []).filter((l) => !filter || l.toLowerCase().includes(filter.toLowerCase())), [q.data, filter]);
  const jump = () => box.current?.scrollTo({ top: box.current.scrollHeight });
  useEffect(() => { if (auto) jump(); }, [lines, auto]);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter log lines" aria-label="Filter log" className="h-8 w-72" />
        <div className="flex items-center gap-2"><Switch id="log-auto" checked={auto} onCheckedChange={setAuto} /><Label htmlFor="log-auto" className="font-normal">Auto-refresh</Label></div>
        <Button variant="outline" size="sm" className="ml-auto" onClick={jump}><ArrowDownToLine /> Jump to latest</Button>
      </div>
      {q.error && !q.data && <LoadError error={q.error} onRetry={q.reload} />}
      <div ref={box} tabIndex={0} aria-label="Agent log" className="h-[60vh] overflow-auto rounded-xl border bg-card p-4 font-mono text-xs leading-relaxed">
        {!q.data && <span className="text-muted-foreground">Loading…</span>}
        {lines.map((l, i) => (
          <div key={i} className={cn("whitespace-pre-wrap", l.includes(" ERROR ") ? "text-destructive" : l.includes(" WARNING ") ? "text-warning" : "text-foreground/80")}>{l}</div>
        ))}
      </div>
    </div>
  );
}
