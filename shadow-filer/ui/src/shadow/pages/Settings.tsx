import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowDown, ArrowUp, Check, CircleAlert, Folder, FolderOpen, HardDrive, Plus, RefreshCw, RotateCcw, Trash2, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { setNavigationGuard, useDebounced, usePoll } from "@/lib/hooks";
import { bytes, pct } from "@/lib/format";
import type { FsDirs, Raw, Rule, SettingsResponse, Status } from "@/lib/types";
import { Bar, Card, Confirm, ListSkeleton, LoadError, Mono, Notice, PageHeader, Spin, act } from "../ui";
import { FolderPicker } from "./Inbox";

const SECTIONS = ["Folders", "Filing rules", "Model", "Watching", "Cleanup", "Search", "Auto-filing", "OCR", "Interface", "System", "Advanced"];
const sid = (s: string) => "set-" + s.toLowerCase().replace(/[^a-z]+/g, "-");

function getPath(o: Raw, path: string) { return path.split(".").reduce<unknown>((a, k) => (a == null ? undefined : (a as Raw)[k]), o); }
function setPath(o: Raw, path: string, v: unknown): Raw {
  const next = structuredClone(o);
  const ks = path.split(".");
  let cur: Raw = next;
  ks.slice(0, -1).forEach((k) => { if (typeof cur[k] !== "object" || cur[k] === null) cur[k] = {}; cur = cur[k]; });
  cur[ks[ks.length - 1]!] = v;
  return next;
}

type Ctx = { raw: Raw; set: (p: string, v: unknown) => void; get: <T = unknown>(p: string) => T; meta: SettingsResponse };

export function SettingsPage({ status }: { status: Status | null }) {
  const q = usePoll(api.settings, null);
  const [raw, setRaw] = useState<Raw | null>(null);
  const [saving, setSaving] = useState(false);
  const [restartNeeded, setRestartNeeded] = useState(false);
  const [restartOpen, setRestartOpen] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [leaveTo, setLeaveTo] = useState<string | null>(null);

  useEffect(() => { if (q.data && !raw) { setRaw(structuredClone(q.data.raw)); setRestartNeeded(q.data.restart_needed); } }, [q.data, raw]);
  const dirty = useMemo(() => !!raw && !!q.data && JSON.stringify(raw) !== JSON.stringify(q.data.raw), [raw, q.data]);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  useEffect(() => {
    setNavigationGuard(() => {
      if (!dirtyRef.current) return true;
      return false;
    });
    const onClick = (e: MouseEvent) => {
      const a = (e.target as HTMLElement).closest("a[href^='#/']") as HTMLAnchorElement | null;
      if (a && dirtyRef.current && !a.getAttribute("href")!.startsWith("#/settings")) setLeaveTo(a.getAttribute("href"));
    };
    const onUnload = (e: BeforeUnloadEvent) => { if (dirtyRef.current) { e.preventDefault(); e.returnValue = ""; } };
    document.addEventListener("click", onClick, true);
    window.addEventListener("beforeunload", onUnload);
    return () => { setNavigationGuard(null); document.removeEventListener("click", onClick, true); window.removeEventListener("beforeunload", onUnload); };
  }, []);

  if (q.error && !q.data) return <><PageHeader title="Settings" /><LoadError error={q.error} onRetry={q.reload} /></>;
  if (!q.data || !raw) return <><PageHeader title="Settings" /><ListSkeleton rows={4} h="h-40" /></>;
  const meta = q.data;
  const get = <T,>(p: string) => (getPath(raw, p) ?? getPath(meta.defaults, p)) as T;
  const ctx: Ctx = { raw, meta, get, set: (p, v) => setRaw((r: Raw) => setPath(r!, p, v)) };

  const save = async () => {
    setSaving(true);
    const r = await act(() => api.saveSettings(raw));
    setSaving(false);
    if (r) {
      if (r.restart_needed) setRestartNeeded(true);
      q.setData({ ...meta, raw: structuredClone(raw), restart_needed: !!r.restart_needed });
    }
  };
  const restart = async () => {
    setRestarting(true);
    await act(() => api.restart());
    const start = Date.now();
    await new Promise((r) => setTimeout(r, 1500));
    while (Date.now() - start < 120_000) {
      try { await api.status(); location.reload(); return; } catch { await new Promise((r) => setTimeout(r, 1500)); }
    }
    setRestarting(false);
    toast.error("The agent didn't come back within 2 minutes. Check the log on this PC.");
  };

  return (
    <div className="pb-24">
      <PageHeader title="Settings" sub={<>Saved to <Mono className="text-xs">{meta.config_path}</Mono></>} />
      {(restartNeeded || status?.restart_needed) && (
        <Notice tone="warn" className="mb-6">
          <div className="flex flex-wrap items-center gap-3">
            <span>Some changes take effect after the agent restarts.</span>
            <Button size="sm" variant="danger" className="ml-auto" onClick={() => setRestartOpen(true)} disabled={restarting}>
              {restarting ? <Spin /> : <RotateCcw />} {restarting ? "Restarting…" : "Restart agent now"}
            </Button>
          </div>
        </Notice>
      )}
      <div className="grid grid-cols-[180px_1fr] gap-8 max-[1100px]:grid-cols-[150px_1fr]">
        <nav aria-label="Settings sections" className="sticky top-20 self-start">
          <ul className="space-y-0.5 text-sm">
            {SECTIONS.map((s) => (
              <li key={s}><button className="w-full rounded-md px-2.5 py-1.5 text-left text-muted-foreground hover:bg-muted hover:text-foreground" onClick={() => document.getElementById(sid(s))?.scrollIntoView({ behavior: "smooth", block: "start" })}>{s}</button></li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 space-y-6">
          <FoldersSection c={ctx} />
          <RulesSection c={ctx} />
          <ModelSection c={ctx} />
          <Section title="Watching">
            <Num c={ctx} p="settle_seconds" label="Wait before reading a new file" unit="seconds" min={1} max={600} />
            <Num c={ctx} p="catch_up_days" label="On start, catch up on downloads from the last" unit="days" min={0} max={365} />
            <Num c={ctx} p="reconcile_minutes" label="Re-check folders every" unit="minutes" min={1} max={1440} />
            <Lines c={ctx} p="ignore_patterns" label="Ignore files matching" hint="One pattern per line, e.g. *.tmp" />
          </Section>
          <Section title="Cleanup">
            <Num c={ctx} p="cleanup.scan_hours" label="Scan automatically every" unit="hours" hint="0 = only when you click Scan now" min={0} max={720} />
            <Num c={ctx} p="cleanup.installer_days" label="Suggest removing installers older than" unit="days" min={1} max={3650} />
            <Num c={ctx} p="cleanup.driver_days" label="Suggest removing driver packages older than" unit="days" min={1} max={3650} />
            <Num c={ctx} p="cleanup.stale_days" label="Treat files as old after" unit="days" min={1} max={3650} />
            <Sw c={ctx} p="cleanup.para_duplicates" label="Also report duplicates inside organised folders" />
          </Section>
          <SearchSection c={ctx} />
          <Section title="Auto-filing" note="Can be made stricter, never looser than 20 decisions at 90%.">
            <Sw c={ctx} p="autofile.enabled" label="Auto-file proven folders" />
            <Num c={ctx} p="autofile.min_decisions" label="Decisions needed per folder" min={20} max={500} />
            <Num c={ctx} p="autofile.min_rate" label="Agreement needed" min={0.9} max={1} step={0.01} fmt={pct} />
            <Num c={ctx} p="autofile.min_score" label="Minimum similarity score" min={0.5} max={1} step={0.01} fmt={pct} />
            <Num c={ctx} p="autofile.delay_minutes" label="Leave new downloads alone for" unit="minutes" min={1} max={1440} />
          </Section>
          <Section title="OCR">
            <Sw c={ctx} p="ocr.enabled" label="Read text from scans and images" />
            <Num c={ctx} p="ocr.max_pdf_pages" label="OCR at most" unit="PDF pages" min={1} max={200} />
            <Num c={ctx} p="ocr.min_image_kb" label="Skip images smaller than" unit="KB" min={0} max={10000} />
            <TestButton label="Test OCR" fn={api.ocrSelftest} />
          </Section>
          <Section title="Interface">
            <Num c={ctx} p="ui.port" label="Port" min={1024} max={65535} restart />
            <Field label="Config file"><Mono className="text-sm">{meta.config_path}</Mono></Field>
            <Field label="Theme"><span className="text-sm text-muted-foreground">Use the sun / moon button in the top bar. Saved in this browser.</span></Field>
          </Section>
          <SystemSection />
          <AdvancedSection onSaved={(rn) => { if (rn) setRestartNeeded(true); }} />
        </div>
      </div>

      {dirty && (
        <div className="fixed inset-x-0 bottom-4 z-30 flex justify-center px-4 fade-in" role="region" aria-label="Unsaved changes">
          <div className="flex items-center gap-3 rounded-xl border bg-popover px-4 py-2.5 shadow-lg">
            <CircleAlert className="size-4 text-warning" /><span className="text-sm">You have unsaved changes</span>
            <Button variant="ghost" size="sm" onClick={() => setRaw(structuredClone(meta.raw))}>Discard</Button>
            <Button size="sm" onClick={save} disabled={saving}>{saving && <Spin />} Save</Button>
          </div>
        </div>
      )}

      <Confirm open={restartOpen} onOpenChange={setRestartOpen} title="Restart the agent?" confirmLabel="Restart" danger onConfirm={restart}>
        <p>Watching and indexing pause for a few seconds. Nothing is moved or deleted by restarting. This page reloads when the agent is back.</p>
      </Confirm>
      <Confirm open={!!leaveTo} onOpenChange={(o) => !o && setLeaveTo(null)} title="Leave without saving?" confirmLabel="Discard changes" onConfirm={() => { const to = leaveTo!; dirtyRef.current = false; setRaw(structuredClone(meta.raw)); setLeaveTo(null); setTimeout(() => (location.hash = to.slice(1)), 0); }}>
        <p>Your changes to the settings will be lost.</p>
      </Confirm>
    </div>
  );
}

/* ---------- layout helpers ---------- */
function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section id={sid(title)} aria-labelledby={sid(title) + "-h"} className="scroll-mt-20">
      <Card className="p-6">
        <h2 id={sid(title) + "-h"} className="text-base font-semibold">{title}</h2>
        {note && <p className="mt-1 text-sm text-muted-foreground">{note}</p>}
        <div className="mt-5 space-y-5">{children}</div>
      </Card>
    </section>
  );
}
function Field({ label, hint, htmlFor, restart, children }: { label: string; hint?: ReactNode; htmlFor?: string; restart?: boolean | undefined; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(180px,260px)_1fr] items-start gap-4 max-[1100px]:grid-cols-1 max-[1100px]:gap-1.5">
      <div className="pt-2">
        <Label htmlFor={htmlFor} className="text-sm">{label}</Label>
        {restart && <Badge variant="muted" className="ml-2">needs restart</Badge>}
      </div>
      <div className="min-w-0">{children}{hint && <p className="mt-1.5 text-xs text-muted-foreground">{hint}</p>}</div>
    </div>
  );
}
let uid = 0;
const useId = () => useMemo(() => `f${++uid}`, []);

function Num({ c, p, label, unit, hint, min, max, step = 1, fmt, restart }: { c: Ctx; p: string; label: string; unit?: string; hint?: string; min: number; max: number; step?: number; fmt?: (v: number) => string; restart?: boolean | undefined }) {
  const id = useId();
  const v = c.get<number>(p);
  const bad = typeof v !== "number" || isNaN(v) || v < min || v > max;
  return (
    <Field label={label} htmlFor={id} restart={restart} hint={<>{hint && <>{hint} · </>}Allowed {fmt ? fmt(min) : min}–{fmt ? fmt(max) : max}{fmt && typeof v === "number" ? ` · now ${fmt(v)}` : ""}</>}>
      <div className="flex items-center gap-2">
        <Input id={id} type="number" min={min} max={max} step={step} value={v ?? ""} aria-invalid={bad}
          onChange={(e) => c.set(p, e.target.value === "" ? null : Number(e.target.value))}
          className={cn("w-32 tabular", bad && "border-destructive")} />
        {unit && <span className="text-sm text-muted-foreground">{unit}</span>}
        {bad && <span className="text-xs text-destructive">Out of range</span>}
      </div>
    </Field>
  );
}
function Sw({ c, p, label, hint }: { c: Ctx; p: string; label: string; hint?: string }) {
  const id = useId();
  return <Field label={label} htmlFor={id} hint={hint}><Switch id={id} checked={!!c.get(p)} onCheckedChange={(v) => c.set(p, v)} className="mt-2" /></Field>;
}
function Lines({ c, p, label, hint }: { c: Ctx; p: string; label: string; hint?: string }) {
  const id = useId();
  const v = c.get<string[]>(p) ?? [];
  const [text, setText] = useState(v.join("\n"));
  useEffect(() => { if (text.split("\n").filter(Boolean).join("\n") !== v.join("\n")) setText(v.join("\n")); /* eslint-disable-next-line */ }, [JSON.stringify(v)]);
  return (
    <Field label={label} htmlFor={id} hint={hint}>
      <Textarea id={id} rows={4} value={text} className="font-mono text-sm"
        onChange={(e) => { setText(e.target.value); c.set(p, e.target.value.split("\n").map((s) => s.trim()).filter(Boolean)); }} />
    </Field>
  );
}
function TestButton({ label, fn }: { label: string; fn: () => Promise<{ ok: boolean; message?: string }> }) {
  const [res, setRes] = useState<{ ok: boolean; message?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="outline" size="sm" disabled={busy} onClick={async () => { setBusy(true); try { setRes(await fn()); } catch (e) { setRes({ ok: false, message: (e as Error).message }); } setBusy(false); }}>{busy && <Spin />}{label}</Button>
      {res && <span className={cn("flex items-center gap-1.5 text-sm", res.ok ? "text-success" : "text-destructive")}>{res.ok ? <Check className="size-4" /> : <X className="size-4" />}{res.message}</span>}
    </div>
  );
}

/* ---------- paths ---------- */
function PathInput({ value, onChange, id, restart }: { value: string; onChange: (v: string) => void; id?: string; restart?: boolean | undefined }) {
  const dv = useDebounced(value, 400);
  const [chk, setChk] = useState<{ expanded: string; exists: boolean } | null>(null);
  const [browse, setBrowse] = useState(false);
  useEffect(() => { if (!dv) { setChk(null); return; } api.fsCheck(dv).then(setChk).catch(() => setChk(null)); }, [dv]);
  return (
    <div>
      <div className="flex gap-2">
        <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} className="font-mono text-sm" aria-invalid={chk ? !chk.exists : undefined} />
        <Button variant="outline" type="button" onClick={() => setBrowse(true)}><FolderOpen /> Browse…</Button>
      </div>
      {chk && (
        <p className={cn("mt-1 flex items-center gap-1 text-xs", chk.exists ? "text-success" : "text-warning")}>
          {chk.exists ? <Check className="size-3" /> : <AlertTriangle className="size-3" />}
          {chk.exists ? "Folder found" : "Folder not found"}{chk.expanded !== value && <> · <Mono className="text-xs">{chk.expanded}</Mono></>}
          {restart && <span className="text-muted-foreground"> · applies after restart</span>}
        </p>
      )}
      <BrowseDialog open={browse} onOpenChange={setBrowse} start={value} onPick={onChange} />
    </div>
  );
}

function BrowseDialog({ open, onOpenChange, start, onPick }: { open: boolean; onOpenChange: (o: boolean) => void; start: string; onPick: (p: string) => void }) {
  const [path, setPath] = useState(start);
  const [d, setD] = useState<FsDirs | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (open) setPath(start); }, [open, start]);
  useEffect(() => { if (!open) return; setD(null); api.fsDirs(path).then((r) => { setD(r); setErr(null); }).catch((e) => setErr(e.message)); }, [open, path]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader><DialogTitle>Choose a folder</DialogTitle></DialogHeader>
        <div className="flex items-center gap-2 text-sm">
          <Button variant="outline" size="sm" disabled={!d || d.parent === null} onClick={() => d && setPath(d.parent ?? "")}><ArrowUp /> Up</Button>
          <Mono className="text-xs">{d?.path || "This PC"}</Mono>
        </div>
        {d?.quick && d.quick.length > 0 && (
          <div className="flex flex-wrap gap-1.5">{d.quick.map((q) => <Button key={q.path} variant="secondary" size="sm" onClick={() => setPath(q.path)}><Folder /> {q.name}</Button>)}</div>
        )}
        <div className="h-72 overflow-auto rounded-lg border">
          {err && <p className="p-4 text-sm text-destructive">{err}</p>}
          {!d && !err && <p className="p-4 text-sm text-muted-foreground">Loading…</p>}
          {d?.dirs.length === 0 && <p className="p-4 text-sm text-muted-foreground">No subfolders.</p>}
          <ul>{d?.dirs.map((x) => (
            <li key={x.path}><button className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted" onClick={() => setPath(x.path)}>
              {d.path ? <Folder className="size-4 text-muted-foreground" /> : <HardDrive className="size-4 text-muted-foreground" />}<span className="path">{x.name}</span>
            </button></li>
          ))}</ul>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!d?.path} onClick={() => { onPick(d!.path); onOpenChange(false); }}>Use this folder</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PathList({ c, p, label, restart }: { c: Ctx; p: string; label: string; restart?: boolean | undefined }) {
  const list = c.get<string[]>(p) ?? [];
  const upd = (l: string[]) => c.set(p, l);
  return (
    <Field label={label} restart={restart}>
      <div className="space-y-2">
        {list.map((v, i) => (
          <div key={i} className="flex gap-2">
            <div className="flex-1"><PathInput value={v} restart={restart} onChange={(nv) => upd(list.map((x, j) => (j === i ? nv : x)))} /></div>
            <Button variant="ghost" size="icon" aria-label="Remove folder" onClick={() => upd(list.filter((_, j) => j !== i))}><Trash2 /></Button>
          </div>
        ))}
        <Button variant="outline" size="sm" onClick={() => upd([...list, ""])}><Plus /> Add folder</Button>
      </div>
    </Field>
  );
}

function FoldersSection({ c }: { c: Ctx }) {
  const excl = c.get<string[]>("exclude_destinations") ?? [];
  return (
    <Section title="Folders">
      <PathList c={c} p="inbox_folders" label="Watched folders" restart />
      <Field label="Organised folder root" restart><PathInput value={c.get<string>("para_root") ?? ""} onChange={(v) => c.set("para_root", v)} restart /></Field>
      <Num c={c} p="destination_depth" label="Suggest folders up to" unit="levels deep" min={1} max={5} />
      <Field label="Never suggest" hint="These folders are left out of suggestions.">
        <div className="flex flex-wrap items-center gap-1.5">
          {excl.map((e) => (
            <Badge key={e} variant="muted" className="gap-1 py-1"><span className="path text-xs">{e}</span>
              <button aria-label={`Remove ${e}`} onClick={() => c.set("exclude_destinations", excl.filter((x) => x !== e))}><X className="size-3" /></button>
            </Badge>
          ))}
          <FolderPicker label="Add…" destinations={c.meta.destinations.filter((d) => !excl.includes(d))} onPick={(d) => c.set("exclude_destinations", [...excl, d])} />
        </div>
      </Field>
    </Section>
  );
}

function validRegex(r?: string) {
  if (!r) return true;
  try { new RegExp(r.replace(/^\(\?i\)/, "")); return true; } catch { return false; }
}

function RulesSection({ c }: { c: Ctx }) {
  const rules = c.get<Rule[]>("rules") ?? [];
  const upd = (l: Rule[]) => c.set("rules", l);
  const patch = (i: number, r: Partial<Rule>) => upd(rules.map((x, j) => (j === i ? { ...x, ...r } : x)));
  const move = (i: number, d: -1 | 1) => { const l = [...rules]; [l[i], l[i + d]] = [l[i + d]!, l[i]!]; upd(l); };
  return (
    <Section title="Filing rules" note="Checked top to bottom before the model. The first matching rule decides.">
      {rules.length === 0 && <p className="text-sm text-muted-foreground">No rules yet.</p>}
      <ol className="space-y-3">
        {rules.map((r, i) => {
          const destOk = c.meta.destinations.includes(r.destination);
          const reOk = validRegex(r.name_regex);
          return (
            <li key={i} className="rounded-lg border p-4">
              <div className="grid grid-cols-[2rem_1fr_1fr_auto] items-start gap-3 max-[1100px]:grid-cols-[2rem_1fr_auto]">
                <span className="pt-2 text-sm text-muted-foreground tabular">{i + 1}.</span>
                <div className="space-y-1"><Label className="text-xs" htmlFor={`r${i}n`}>Name</Label><Input id={`r${i}n`} value={r.name} onChange={(e) => patch(i, { name: e.target.value })} /></div>
                <div className="space-y-1 max-[1100px]:col-start-2"><Label className="text-xs" htmlFor={`r${i}e`}>Extensions</Label><Input id={`r${i}e`} className="font-mono text-sm" placeholder="pdf, docx" value={(r.extensions ?? []).join(", ")} onChange={(e) => patch(i, { extensions: e.target.value.split(/[,\s]+/).map((s) => s.replace(/^\./, "").trim()).filter(Boolean) })} /></div>
                <div className="flex gap-1 pt-6 max-[1100px]:row-start-1 max-[1100px]:col-start-3">
                  <Button variant="ghost" size="icon" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp /></Button>
                  <Button variant="ghost" size="icon" aria-label="Move down" disabled={i === rules.length - 1} onClick={() => move(i, 1)}><ArrowDown /></Button>
                  <Button variant="ghost" size="icon" aria-label="Delete rule" onClick={() => upd(rules.filter((_, j) => j !== i))}><Trash2 /></Button>
                </div>
                <div className="col-start-2 space-y-1">
                  <Label className="text-xs" htmlFor={`r${i}x`}>File name pattern (optional)</Label>
                  <Input id={`r${i}x`} className={cn("font-mono text-sm", !reOk && "border-destructive")} aria-invalid={!reOk} value={r.name_regex ?? ""} onChange={(e) => patch(i, { name_regex: e.target.value || undefined })} />
                  {!reOk && <p className="text-xs text-destructive">This pattern isn't valid.</p>}
                </div>
                <div className="space-y-1 max-[1100px]:col-start-2">
                  <Label className="text-xs">Destination</Label>
                  <div className="flex items-center gap-1"><Mono className="flex-1 truncate rounded-md border px-3 py-2 text-xs">{r.destination || "—"}</Mono><FolderPicker label="Pick" destinations={c.meta.destinations} onPick={(d) => patch(i, { destination: d })} /></div>
                  {r.destination && !destOk && <p className="text-xs text-warning">This folder isn't in your organised tree.</p>}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      <Button variant="outline" size="sm" onClick={() => upd([...rules, { name: "New rule", extensions: [], destination: "" }])}><Plus /> Add rule</Button>
    </Section>
  );
}

function ModelSection({ c }: { c: Ctx }) {
  const model = c.get<string>("ollama.model");
  const installed = c.meta.models.includes(model);
  return (
    <Section title="Model">
      <Field label="Model" hint={!installed ? <span className="text-warning">Not installed. Run <span className="path">ollama pull {model}</span> on this PC.</span> : undefined}>
        <Select value={model} onValueChange={(v) => c.set("ollama.model", v)}>
          <SelectTrigger className="w-72 font-mono text-sm"><SelectValue /></SelectTrigger>
          <SelectContent>{[...new Set([model, ...c.meta.models])].map((m) => <SelectItem key={m} value={m} className="font-mono text-sm">{m}</SelectItem>)}</SelectContent>
        </Select>
      </Field>
      <Field label="Ollama address"><Input value={c.get<string>("ollama.url") ?? ""} onChange={(e) => c.set("ollama.url", e.target.value)} className="w-80 font-mono text-sm" /></Field>
      <Sw c={c} p="ollama.think" label="Let the model think step by step" hint="Slower, sometimes more accurate." />
      <Num c={c} p="history_examples" label="Past decisions shown to the model" min={0} max={100} />
      <Num c={c} p="ollama.timeout_seconds" label="Give up on a suggestion after" unit="seconds" min={10} max={1800} />
      <Num c={c} p="ollama.startup_wait_seconds" label="Wait for Ollama at startup up to" unit="seconds" min={0} max={7200} />
    </Section>
  );
}

function SearchSection({ c }: { c: Ctx }) {
  const orig = c.meta.raw?.search?.model;
  const model = c.get<string>("search.model");
  return (
    <Section title="Search">
      <Sw c={c} p="search.enabled" label="Search by meaning" />
      <Field label="Embedding model" hint={model !== orig ? <span className="text-warning">Changing the model rebuilds the whole index.</span> : undefined}>
        <Select value={model} onValueChange={(v) => c.set("search.model", v)}>
          <SelectTrigger className="w-72 font-mono text-sm"><SelectValue /></SelectTrigger>
          <SelectContent>{[...new Set([model, ...c.meta.models])].map((m) => <SelectItem key={m} value={m} className="font-mono text-sm">{m}</SelectItem>)}</SelectContent>
        </Select>
      </Field>
      <PathList c={c} p="search.extra_folders" label="Also search these folders" />
      <Lines c={c} p="search.exclude_globs" label="Skip paths matching" hint="One pattern per line." />
      <Num c={c} p="search.min_similarity" label="Minimum meaning match" min={0} max={1} step={0.01} fmt={pct} />
      <Num c={c} p="search.sweep_minutes" label="Look for changed files every" unit="minutes" min={1} max={1440} />
    </Section>
  );
}

function SystemSection() {
  const [refresh, setRefresh] = useState(0);
  const q = usePoll(() => api.system(refresh > 0), null, [refresh]);
  const s = q.data;
  return (
    <Section title="System">
      <div className="flex justify-end -mt-12"><Button variant="ghost" size="sm" onClick={() => setRefresh((n) => n + 1)} disabled={q.loading}><RefreshCw className={cn(q.loading && "animate-spin")} /> Refresh</Button></div>
      {q.error && !s && <LoadError error={q.error} onRetry={q.reload} />}
      {!s && !q.error && <ListSkeleton rows={2} h="h-16" />}
      {s && (
        <>
          {s.notes.map((n, i) => <Notice key={i} tone={n.level === "warn" ? "warn" : "info"}>{n.text}</Notice>)}
          <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Windows</dt><dd>{s.os}</dd>
            <dt className="text-muted-foreground">Computer</dt><dd>{s.computer}</dd>
            <dt className="text-muted-foreground">CPU</dt><dd>{s.cpu}</dd>
            <dt className="text-muted-foreground">Memory</dt><dd className="tabular">{bytes(s.memory.installed)} installed · {bytes(s.memory.free)} free</dd>
            <dt className="text-muted-foreground">Ollama</dt>
            <dd>{s.ollama.reachable ? <>Reachable · version {s.ollama.version} · loaded: <Mono className="text-xs">{s.ollama.loaded.join(", ") || "none"}</Mono></> : <span className="text-warning">Not reachable</span>}</dd>
          </dl>
          {s.gpus.map((g) => (
            <div key={g.name} className="rounded-lg border p-3 text-sm">
              <div className="font-medium">{g.name}</div>
              <div className="mt-2 flex items-center gap-3"><Bar value={g.vram_used / g.vram_total} className="w-48" label="GPU memory used" /><span className="text-xs text-muted-foreground tabular">{bytes(g.vram_used)} of {bytes(g.vram_total)} · {g.temp ?? "—"}°C · {g.util ?? "—"}% busy</span></div>
            </div>
          ))}
          <div className="space-y-2">
            {s.disks.map((d) => {
              const free = d.free / d.total;
              return (
                <div key={d.mount} className="flex items-center gap-3 text-sm">
                  <span className="w-28 font-mono text-xs">{d.mount} {d.name}</span>
                  <Bar value={1 - free} tone={free < 0.1 ? "warning" : "primary"} className="flex-1" label={`${d.mount} used space`} />
                  <span className={cn("w-40 text-right text-xs tabular", free < 0.1 ? "text-warning font-medium" : "text-muted-foreground")}>{bytes(d.free)} free of {bytes(d.total)}</span>
                </div>
              );
            })}
          </div>
          <TestButton label="Test Recycle Bin" fn={api.recycleSelftest} />
        </>
      )}
    </Section>
  );
}

function AdvancedSection({ onSaved }: { onSaved: (restart: boolean) => void }) {
  const q = usePoll(api.config, null);
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (q.data && text === null) setText(q.data.text); }, [q.data, text]);
  return (
    <Section title="Advanced">
      <Notice tone="warn">Editing the raw file is for experts. The form above checks your values; this editor does not. Saving here replaces the whole config file.</Notice>
      <Textarea aria-label="Raw configuration (YAML)" value={text ?? ""} onChange={(e) => setText(e.target.value)} rows={18} spellCheck={false} className="font-mono text-xs leading-relaxed" />
      <div className="flex gap-2">
        <Button variant="outline" disabled={busy || text === null} onClick={async () => { setBusy(true); const r = await act(() => api.saveConfig(text!)); setBusy(false); if (r) onSaved(!!r.restart_needed); }}>{busy && <Spin />} Save YAML</Button>
        <Button variant="ghost" onClick={() => setText(q.data?.text ?? "")}>Revert</Button>
      </div>
    </Section>
  );
}
