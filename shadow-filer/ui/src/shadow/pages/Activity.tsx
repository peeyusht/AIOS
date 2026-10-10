import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, ArrowRight, ChevronDown } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useDebounced, usePoll } from "@/lib/hooks";
import { dateTime, pct } from "@/lib/format";
import type { Prediction, StatsBucket } from "@/lib/types";
import { Card, ListSkeleton, LoadError, Mono, PageHeader, Stat } from "../ui";

export function ActivityPage() {
  return (
    <>
      <PageHeader title="Activity" sub="How well suggestions match where you actually file things." />
      <Tabs defaultValue="accuracy">
        <TabsList className="mb-6">
          <TabsTrigger value="accuracy">Accuracy</TabsTrigger>
          <TabsTrigger value="predictions">Predictions</TabsTrigger>
          <TabsTrigger value="log">Log</TabsTrigger>
        </TabsList>
        <TabsContent value="accuracy"><Accuracy /></TabsContent>
        <TabsContent value="predictions"><Predictions /></TabsContent>
        <TabsContent value="log"><Log /></TabsContent>
      </Tabs>
    </>
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
