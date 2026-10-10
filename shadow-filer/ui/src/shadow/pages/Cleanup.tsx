import { useMemo, useState } from "react";
import {
  AlertTriangle, Check, ChevronDown, Download, FolderSearch, History, Loader2, Play, ShieldCheck, Trash2, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { api, cleanupCsvUrl } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes, dateTime, when, baseName } from "@/lib/format";
import type { CleanupItem, CleanupResponse, Decision } from "@/lib/types";
import { Card, Confirm, EmptyState, ListSkeleton, LoadError, Mono, Notice, PageHeader, Spin, act } from "../ui";

const CATEGORY: Record<string, string> = {
  duplicate_of_filed: "Duplicate of a filed copy", duplicate_in_downloads: "Duplicate in Downloads", partial_download: "Partial download",
  archive_extracted: "Archive already extracted", installer: "Installer", driver_package: "Driver package", executable: "Program",
  old_unopened: "Old, not opened", firmware_or_image: "Firmware / image",
};
const LEVELS = [
  { key: "safe", label: "Safe to delete", tone: "success" },
  { key: "likely", label: "Probably safe", tone: "info" },
  { key: "review", label: "Review", tone: "warning" },
  { key: "keep", label: "Keep / archive", tone: "muted" },
] as const;
const levelTone = (l: string) => (LEVELS.find((x) => x.key === l)?.tone ?? "muted");

export function CleanupPage() {
  const [fast, setFast] = useState(false);
  const q = usePoll(async () => {
    const r = await api.cleanup();
    setFast(r.runner.running || r.deleter.running);
    return r;
  }, fast ? 2_000 : 15_000);
  const [level, setLevel] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [hide, setHide] = useState(false);
  const [hist, setHist] = useState(false);

  if (q.error && !q.data) return <><PageHeader title="Cleanup" /><LoadError error={q.error} onRetry={q.reload} /></>;
  if (!q.data) return <><PageHeader title="Cleanup" /><ListSkeleton rows={5} h="h-16" /></>;
  const d = q.data;
  const rep = d.report;
  const items = rep?.items ?? [];
  const agreed = items.filter((i) => i.decision === "agree");

  const scan = async () => { const r = await act(() => api.scan()); if (r) { setFast(true); q.reload(); } };

  const filtered = items.filter((i) =>
    (agreedFilter(level) ? i.decision === "agree" : !level || i.level === level) &&
    (!text || (i.name + i.folder).toLowerCase().includes(text.toLowerCase())) &&
    (!hide || (i.decision !== "keep" && i.decision !== "disagree")),
  );

  const setDecision = async (path: string, decision: Decision) => {
    q.setData((cur) => cur && cur.report ? { ...cur, report: { ...cur.report, items: cur.report.items.map((i) => (i.path === path ? { ...i, decision } : i)) } } : cur);
    const r = await act(() => api.decide(path, decision));
    q.reload();
    if (!r) q.reload();
  };

  return (
    <>
      <PageHeader
        title="Cleanup"
        sub={rep ? <>Last scan {when(rep.generated)} · <span className="tabular">{rep.counts.inbox_files.toLocaleString()}</span> files in Downloads compared with <span className="tabular">{rep.counts.para_files.toLocaleString()}</span> in your organised folders</> : "No scan yet."}
        actions={<>
          <Button variant="ghost" size="sm" onClick={() => setHist(true)}><History /> History</Button>
          <Button variant="outline" size="sm" asChild><a href={cleanupCsvUrl} download><Download /> Export CSV</a></Button>
          <Button size="sm" onClick={scan} disabled={d.runner.running}>{d.runner.running ? <Spin /> : <Play />} Scan now</Button>
        </>}
      />

      <div className="space-y-6">
        <Notice tone="success" icon={<ShieldCheck />}>
          <span className="font-medium">Nothing is deleted until you mark it Agree and then confirm.</span> Each file is checked again right before deleting; anything that changed is skipped.
        </Notice>

        {d.runner.running && (
          <Card className="flex items-center gap-3 p-4 text-sm" aria-live="polite">
            <Loader2 className="size-4 animate-spin text-primary" /> <span className="font-medium">Scanning…</span> <span className="text-muted-foreground">{d.runner.progress}</span>
          </Card>
        )}
        {d.runner.error && <Notice tone="warn">The last scan failed: {d.runner.error}</Notice>}

        {rep && (
          <div className="grid grid-cols-5 gap-3 max-[1100px]:grid-cols-3">
            {LEVELS.map((l) => {
              const v = rep.by_level[l.key] ?? { count: 0, bytes: 0 };
              return <Tile key={l.key} active={level === l.key} onClick={() => setLevel(level === l.key ? null : l.key)} label={d.levels[l.key] ?? l.label} bytes={v.bytes} count={v.count} tone={l.tone} />;
            })}
            <Tile active={agreedFilter(level)} onClick={() => setLevel(agreedFilter(level) ? null : "__agreed")} label="You agreed to delete" bytes={agreed.reduce((a, b) => a + b.size, 0)} count={agreed.length} tone="primary" />
          </div>
        )}

        {agreed.length > 0 && <DeletePanel d={d} reload={() => { setFast(true); q.reload(); }} />}
        {!agreed.length && d.deleter.result && <DeleteResult r={d.deleter.result} />}

        {rep && (
          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
              <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Filter by name or folder" aria-label="Filter items" className="h-8 w-64" />
              {level && <Button variant="ghost" size="sm" onClick={() => setLevel(null)}><X /> Clear filter</Button>}
              <div className="ml-auto flex items-center gap-2">
                <Switch id="hide-kd" checked={hide} onCheckedChange={setHide} />
                <Label htmlFor="hide-kd" className="text-sm font-normal">Hide ones I marked Keep or Disagree</Label>
              </div>
            </div>
            {filtered.length === 0 ? (
              <div className="p-6"><EmptyState icon={<Check />} title="Nothing here">No recommendations match these filters.</EmptyState></div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr className="border-b"><th className="px-4 py-2 font-medium">File</th><th className="px-2 font-medium text-right">Size</th><th className="px-3 font-medium">Added</th><th className="px-3 font-medium">Last opened</th><th className="px-3 font-medium">Recommendation</th><th className="px-4 font-medium text-right">Your call</th></tr>
                  </thead>
                  <tbody className="divide-y">
                    {filtered.map((i) => <Row key={i.path} i={i} onDecide={setDecision} />)}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {rep && <HowItWorked d={d} />}
        {rep && rep.para_duplicates.length > 0 && (
          <Section title={`Duplicates inside your organised folders (information only) · ${rep.para_duplicates.length}`}>
            <ul className="space-y-3">
              {rep.para_duplicates.map((g, i) => (
                <li key={i} className="rounded-lg border p-3">
                  <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">{bytes(g.size)} each {g.confirmed ? <Badge variant="muted">content confirmed</Badge> : <Badge variant="warning">same size, not confirmed</Badge>}</div>
                  {g.paths.map((p) => <div key={p}><Mono className="text-xs">{p}</Mono></div>)}
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>
      <HistorySheet open={hist} onOpenChange={setHist} />
    </>
  );
}
const agreedFilter = (l: string | null) => l === "__agreed";

function Tile({ label, bytes: b, count, tone, active, onClick }: { label: string; bytes: number; count: number; tone: string; active: boolean; onClick: () => void }) {
  const dot = { success: "bg-success", info: "bg-primary", warning: "bg-warning", muted: "bg-muted-foreground", primary: "bg-primary" }[tone];
  return (
    <button onClick={onClick} aria-pressed={active}
      className={cn("rounded-xl border bg-card p-4 text-left transition-colors hover:bg-muted/50", active && "border-primary ring-1 ring-primary")}>
      <div className="flex items-center gap-2 text-xs text-muted-foreground"><span className={cn("size-2 rounded-full", dot)} />{label}</div>
      <div className="mt-2 text-xl font-semibold tabular">{bytes(b)}</div>
      <div className="text-xs text-muted-foreground tabular">{count} {count === 1 ? "item" : "items"}</div>
    </button>
  );
}

function Row({ i, onDecide }: { i: CleanupItem; onDecide: (p: string, d: Decision) => void }) {
  const toggle = (d: Exclude<Decision, null>) => onDecide(i.path, i.decision === d ? null : d);
  return (
    <tr className={cn("align-top", i.decision === "agree" && "bg-success-soft/40")}>
      <td className="max-w-72 px-4 py-3">
        <div className="truncate font-medium" title={i.path}>{i.name}</div>
        <Mono className="text-xs text-muted-foreground">{i.folder}</Mono>
      </td>
      <td className="px-2 py-3 text-right tabular whitespace-nowrap">{bytes(i.size)}</td>
      <td className="px-3 py-3 whitespace-nowrap text-muted-foreground tabular">{i.age_days} d ago</td>
      <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">{i.last_opened ? when(i.last_opened) : "no record"}</td>
      <td className="max-w-80 px-3 py-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={levelTone(i.level) as "success"}>{LEVELS.find((l) => l.key === i.level)?.label ?? i.level}</Badge>
          <span className="text-xs text-muted-foreground">{CATEGORY[i.category] ?? i.category}</span>
        </div>
        <p className="mt-1 text-xs leading-relaxed">{i.reason}{i.related && <> · Same as: <Mono className="text-xs">{i.related}</Mono></>}</p>
        {i.caution && <p className="mt-1 flex items-start gap-1 text-xs text-warning"><AlertTriangle className="mt-0.5 size-3 shrink-0" />{i.caution}</p>}
      </td>
      <td className="px-4 py-3">
        <div className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" onClick={() => act(() => api.reveal(i.path))} aria-label={`Show ${i.name} in Explorer`}><FolderSearch /></Button>
          {i.level === "keep" ? (
            <Button size="sm" variant={i.decision === "keep" ? "secondary" : "outline"} aria-pressed={i.decision === "keep"} onClick={() => toggle("keep")}>Keep</Button>
          ) : (
            <>
              <Button size="sm" variant={i.decision === "agree" ? "default" : "outline"} aria-pressed={i.decision === "agree"} onClick={() => toggle("agree")}>{i.decision === "agree" && <Check />}Agree</Button>
              <Button size="sm" variant={i.decision === "disagree" ? "secondary" : "outline"} aria-pressed={i.decision === "disagree"} onClick={() => toggle("disagree")}>Disagree</Button>
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

function DeletePanel({ d, reload }: { d: CleanupResponse; reload: () => void }) {
  const [step, setStep] = useState(false);
  const [permOpen, setPermOpen] = useState(false);
  const [ack, setAck] = useState(false);
  const { plan, deleter } = d;
  const recycle = async () => { setStep(false); const r = await act(() => api.deleteRecycle()); if (r) reload(); };
  const permanent = async () => { setPermOpen(false); setAck(false); const r = await act(() => api.deletePermanent(plan.too_big.map((t) => t.path))); if (r) reload(); };

  return (
    <Card className="space-y-4 p-5">
      <div className="flex items-center gap-2"><Trash2 className="size-4 text-muted-foreground" /><h2 className="font-semibold">Delete agreed files</h2></div>
      {deleter.running ? (
        <div className="flex items-center gap-2 text-sm" aria-live="polite"><Spin /> {deleter.progress}</div>
      ) : (
        <>
          {plan.recycle_count > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm"><span className="font-semibold tabular">{plan.recycle_count}</span> {plan.recycle_count === 1 ? "file" : "files"} · <span className="tabular">{bytes(plan.recycle_bytes)}</span> can go to the Recycle Bin (restorable)</p>
              <div className="ml-auto flex items-center gap-2">
                {step ? (
                  <>
                    <span className="text-sm text-muted-foreground">Move {plan.recycle_count} files?</span>
                    <Button variant="ghost" size="sm" onClick={() => setStep(false)}>Cancel</Button>
                    <Button size="sm" onClick={recycle} autoFocus>Yes, move to Recycle Bin</Button>
                  </>
                ) : (
                  <Button variant="outline" onClick={() => setStep(true)}><Trash2 /> Move to Recycle Bin</Button>
                )}
              </div>
            </div>
          )}
          {plan.too_big.length > 0 && (
            <div className="rounded-lg border border-warning/40 bg-warning-soft p-4 text-sm">
              <p className="flex items-start gap-2 font-medium"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />Too big for the Recycle Bin</p>
              <p className="mt-1 text-muted-foreground">Windows would delete these permanently, so they are not included above.</p>
              <ul className="mt-2 space-y-0.5">{plan.too_big.map((t) => <li key={t.path} className="flex justify-between gap-3"><Mono className="text-xs">{t.name}</Mono><span className="tabular text-xs">{bytes(t.size)}</span></li>)}</ul>
              <Button variant="danger" size="sm" className="mt-3" onClick={() => setPermOpen(true)}><AlertTriangle /> Delete permanently…</Button>
            </div>
          )}
        </>
      )}
      {d.deleter.result && <DeleteResult r={d.deleter.result} />}

      <Confirm open={permOpen} onOpenChange={(o) => { setPermOpen(o); if (!o) setAck(false); }} title="Delete permanently?" confirmLabel="Delete permanently" danger onConfirm={() => (ack ? permanent() : undefined)}>
        <p>{plan.too_big.length === 1 ? "This file" : `These ${plan.too_big.length} files`} ({bytes(plan.too_big.reduce((a, b) => a + b.size, 0))}) will be erased and cannot be restored from the Recycle Bin.</p>
        <label className="flex items-center gap-2 pt-2 text-foreground">
          <Checkbox checked={ack} onCheckedChange={(v) => setAck(!!v)} /> I understand these cannot be restored
        </label>
        {!ack && <p className="text-xs">Tick the box to enable the button.</p>}
      </Confirm>
    </Card>
  );
}

function DeleteResult({ r }: { r: NonNullable<CleanupResponse["deleter"]["result"]> }) {
  return (
    <div className="rounded-lg border bg-muted/40 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <Check className="size-4 text-success" />
        <span><b className="tabular">{r.deleted.length}</b> {r.mode === "permanent" ? "deleted permanently" : "moved to the Recycle Bin"} · {bytes(r.deleted_bytes)}</span>
        <span className="text-xs text-muted-foreground">{dateTime(r.finished)}</span>
        {r.mode === "recycle" && <Button size="sm" variant="outline" className="ml-auto" onClick={() => act(() => api.openRecycleBin())}>Open Recycle Bin</Button>}
      </div>
      {r.skipped.length > 0 && <RefList title="Skipped" items={r.skipped} />}
      {r.failed.length > 0 && <RefList title="Failed" items={r.failed} danger />}
    </div>
  );
}
function RefList({ title, items, danger }: { title: string; items: { path: string; name: string; why?: string }[]; danger?: boolean }) {
  return (
    <div className="mt-3">
      <div className={cn("text-xs font-medium", danger ? "text-destructive" : "text-warning")}>{title} ({items.length})</div>
      <ul className="mt-1 space-y-0.5">{items.map((s) => <li key={s.path} className="text-xs"><Mono className="text-xs">{s.name}</Mono> — {s.why}</li>)}</ul>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card>
        <CollapsibleTrigger className="flex w-full items-center rounded-xl px-4 py-3 text-left text-sm font-medium">
          {title}<ChevronDown className={cn("ml-auto size-4 transition-transform", open && "rotate-180")} />
        </CollapsibleTrigger>
        <CollapsibleContent className="border-t px-4 py-4 text-sm">{children}</CollapsibleContent>
      </Card>
    </Collapsible>
  );
}

function HowItWorked({ d }: { d: CleanupResponse }) {
  const rep = d.report!;
  return (
    <Section title="How this scan worked">
      <ul className="list-disc space-y-1.5 pl-5 text-muted-foreground">
        <li>Files were compared by their content, not their names.</li>
        <li>Cloud-only files were never opened or downloaded ({rep.counts.cloud_only_para} in organised folders, {rep.counts.cloud_only_inbox} in Downloads). {rep.counts.unconfirmed_cloud_groups} possible duplicate groups could not be confirmed because of this.</li>
        <li>{rep.counts.files_hashed.toLocaleString()} files were hashed to check for exact copies.</li>
        <li>Thresholds: {Object.entries(rep.settings).map(([k, v]) => `${k.replace(/_/g, " ")} ${String(v)}`).join(" · ")}</li>
      </ul>
      {rep.errors.length > 0 && <div className="mt-3"><div className="text-xs font-medium text-warning">Couldn't check</div><ul className="mt-1 space-y-0.5 text-xs">{rep.errors.map((e) => <li key={e}>{e}</li>)}</ul></div>}
    </Section>
  );
}

function HistorySheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const h = usePoll(api.cleanupHistory, null, [open]);
  const rows = useMemo(() => h.data?.rows ?? [], [h.data]);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[480px] sm:max-w-[480px] overflow-y-auto">
        <SheetHeader><SheetTitle>Cleanup history</SheetTitle></SheetHeader>
        <ul className="mt-4 divide-y text-sm">
          {rows.length === 0 && <li className="py-6 text-muted-foreground">Nothing deleted yet.</li>}
          {rows.map((r, i) => (
            <li key={i} className="py-2.5">
              <div className="flex justify-between gap-2"><Mono className="text-xs">{baseName(r.path)}</Mono><span className="text-xs tabular text-muted-foreground">{bytes(r.size)}</span></div>
              <div className="mt-0.5 flex gap-2 text-xs text-muted-foreground">
                <span>{dateTime(r.ts)}</span>·<span>{r.mode === "permanent" ? "permanent" : "Recycle Bin"}</span>·
                <span className={r.result === "deleted" ? "text-success" : "text-warning"}>{r.result}</span>
              </div>
            </li>
          ))}
        </ul>
      </SheetContent>
    </Sheet>
  );
}
