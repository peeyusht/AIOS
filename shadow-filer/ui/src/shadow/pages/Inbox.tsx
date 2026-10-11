import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  ArrowRight, Check, ChevronDown, ChevronLeft, ChevronRight, CircleCheck, Copy, FolderPlus, FolderSearch, Inbox as InboxIcon,
  RefreshCw, ShieldCheck, Undo2, Zap,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes, dateTime, pct, when, baseName } from "@/lib/format";
import type { AutofileFolder, Candidate, InboxItem, InboxResponse } from "@/lib/types";
import { Bar, Card, Confirm, EmptyState, ListSkeleton, LoadError, Mono, Notice, PageHeader, Spin, Tip, act } from "../ui";
import { emitInboxChanged } from "../App";

const PAGE = 25;

export function InboxPage() {
  return (
    <>
      <PageHeader title="Inbox" sub="New downloads, with a suggested home for each." />
      <Tabs defaultValue="waiting">
        <TabsList className="mb-6">
          <TabsTrigger value="waiting">Waiting</TabsTrigger>
          <TabsTrigger value="moves">Recent moves</TabsTrigger>
          <TabsTrigger value="auto">Auto-filing</TabsTrigger>
        </TabsList>
        <TabsContent value="waiting"><Waiting /></TabsContent>
        <TabsContent value="moves"><RecentMoves /></TabsContent>
        <TabsContent value="auto"><AutoFiling /></TabsContent>
      </Tabs>
    </>
  );
}

export async function undoMove(id: number, after?: () => void) {
  const r = await act(() => api.undo(id));
  if (r) {
    toast.success(r.restored ? `${baseName(r.restored)} is back where it was` : "Move undone");
    emitInboxChanged();
    after?.();
  }
}

function Waiting() {
  const [offset, setOffset] = useState(0);
  const q = usePoll(() => api.inbox(offset, PAGE), 30_000, [offset]);
  const [autoOn, setAutoOn] = useState(false);
  useEffect(() => { api.autofile().then((a) => setAutoOn(a.settings.enabled)).catch(() => {}); }, []);
  useEffect(() => {
    const h = () => q.reload();
    window.addEventListener("sf-inbox-changed", h);
    return () => window.removeEventListener("sf-inbox-changed", h);
  }, [q]);

  const d = q.data;
  const removeLocal = (path: string) => q.setData((cur) => cur && { ...cur, items: cur.items.filter((i) => i.path !== path), total: cur.total - 1 });

  return (
    <div className="space-y-5">
      <Notice tone="success" icon={<ShieldCheck />}>
        {autoOn ? (
          <><span className="font-medium">Folders you have proven are filed for you after the waiting time.</span> Everything else moves only when you click File it. Every move can be undone.</>
        ) : (
          <><span className="font-medium">Files move only when you click File it.</span> Every move can be undone.</>
        )}
      </Notice>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {d ? (
            <>
              <span className="font-medium text-foreground tabular">{d.total}</span> files waiting in Downloads
              {d.examples && <> · suggestions learned from <span className="tabular">{d.examples.examples.toLocaleString()}</span> filed documents in <span className="tabular">{d.examples.folders}</span> folders</>}
            </>
          ) : " "}
        </p>
        <Button variant="outline" size="sm" onClick={() => q.reload()} disabled={q.loading}>
          <RefreshCw className={cn(q.loading && "animate-spin")} /> Refresh
        </Button>
      </div>

      <details className="group rounded-lg border bg-card px-4 py-2.5 text-sm">
        <summary className="flex cursor-pointer list-none items-center gap-2 text-muted-foreground marker:hidden">
          <ChevronDown className="size-4 transition-transform group-open:rotate-180" /> What does the percentage mean?
        </summary>
        <p className="mt-2 leading-relaxed text-muted-foreground">
          It's how strongly your already-filed documents point to that folder. Tested on your own files:{" "}
          <span className="text-success font-medium">95% and up was right 94 times in 100</span>, 50–70% about 7 in 10, and{" "}
          <span className="text-warning font-medium">under 50% only 1 in 3</span> — so check those.
        </p>
      </details>

      {q.error && !d && <LoadError error={q.error} onRetry={q.reload} />}
      {!d && !q.error && <ListSkeleton rows={4} h="h-36" />}
      {d && d.items.length === 0 && (
        <EmptyState icon={<InboxIcon />} title="Nothing waiting">
          Downloads is tidy. New files will show up here with a suggested folder.
        </EmptyState>
      )}
      {d && d.items.length > 0 && (
        <ul className="space-y-3" aria-label="Files waiting">
          {d.items.map((it) => (
            <InboxCard key={it.path} item={it} data={d} autoOn={autoOn} onGone={() => removeLocal(it.path)} />
          ))}
        </ul>
      )}

      {d && d.total > PAGE && (
        <div className="flex items-center justify-between pt-2 text-sm text-muted-foreground">
          <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            <ChevronLeft /> Newer
          </Button>
          <span className="tabular">{offset + 1}–{Math.min(offset + PAGE, d.total)} of {d.total}</span>
          <Button variant="outline" size="sm" disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)}>
            Older <ChevronRight />
          </Button>
        </div>
      )}
    </div>
  );
}

const SOURCE_WORDS: Record<string, string> = { rule: "rule", origin: "same website as files filed here", name: "name matches folder", similar: "like your filed docs", model: "model's guess" };
const scoreTone = (s: number) => (s >= 0.95 ? "success" : s >= 0.7 ? "info" : "warning") as "success" | "info" | "warning";

function cleanupLabel(c: NonNullable<InboxItem["cleanup"]>) {
  if (c.category === "duplicate_of_filed") return "Already filed (duplicate)";
  if (c.category === "partial_download") return "Partial download";
  return `Cleanup: ${c.level}`;
}

function InboxCard({ item, data, autoOn, onGone }: { item: InboxItem; data: InboxResponse; autoOn: boolean; onGone: () => void }) {
  const chips = item.candidates.slice(0, 4);
  const firstOk = chips.find((c) => c.exists)?.folder ?? null;
  const [folder, setFolderRaw] = useState<string | null>(firstOk);
  // Until you pick a folder yourself, the selection follows the first suggestion (which can change when
  // the list refreshes); once you pick, your choice stays.
  const [picked, setPicked] = useState(false);
  useEffect(() => { if (!picked) setFolderRaw(firstOk); }, [firstOk, picked]);
  const setFolder = (f: string | null) => { setPicked(true); setFolderRaw(f); };
  const [extra, setExtra] = useState<string | null>(null); // chosen via Other/New
  const [mk, setMk] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const selectedMissing = chips.find((c) => c.folder === folder)?.exists === false;

  const choose = (f: string) => { setFolder(f); if (!chips.some((c) => c.folder === f)) setExtra(f); };

  const file = async () => {
    if (!folder) return;
    setBusy("file");
    const r = await act(() => api.fileIt(item.path, folder, item.size));
    setBusy(null);
    if (!r) return;
    onGone();
    emitInboxChanged();
    toast.success(`Filed ${item.name} → ${folder}`, {
      description: r.renamed ? `Saved as ${baseName(r.dest ?? "")} (a file with that name already existed)` : undefined,
      action: r.id != null ? { label: "Undo", onClick: () => undoMove(r.id!) } : undefined,
      duration: 10_000,
    });
  };
  const dismiss = async () => {
    setBusy("dismiss");
    const r = await act(() => api.dismiss(item.path));
    setBusy(null);
    if (r) { onGone(); emitInboxChanged(); toast("Left in Downloads", { description: item.name }); }
  };

  return (
    <li>
      <Card className="p-4 transition-shadow hover:shadow-sm">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <Tip tip={item.path}><h3 className="min-w-0 truncate font-medium" tabIndex={0}>{item.name}</h3></Tip>
          <span className="text-xs text-muted-foreground tabular">{bytes(item.size)} · modified {when(item.modified)}{item.origin?.host ? <> · from <span className="path">{item.origin.host}</span></> : null}</span>
        </div>

        {(item.cleanup || item.duplicate || item.auto.auto || !item.ready) && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {item.cleanup && <Badge variant={item.cleanup.level === "safe" ? "success" : "warning"} title={item.cleanup.reason}>{cleanupLabel(item.cleanup)}</Badge>}
            {item.duplicate && <Badge variant="muted"><Copy className="size-3" /> Same as a file in <span className="path text-xs">{item.duplicate.folder}</span></Badge>}
            {item.auto.auto && (
              <Badge variant="info" title={item.auto.why}>
                <Zap className="size-3" /> {autoOn ? "Auto-files on next run" : "Would auto-file"}{item.auto.soon && " · after the waiting time"}
              </Badge>
            )}
            {!item.ready && <span className="text-xs text-muted-foreground italic">Still being read; suggestions from similar files appear once it's indexed.</span>}
          </div>
        )}

        <div className="mt-3 flex flex-wrap gap-2" role="radiogroup" aria-label={`Destination for ${item.name}`}>
          {chips.map((c) => <Chip key={c.folder} c={c} selected={folder === c.folder} onSelect={() => setFolder(c.folder)} />)}
          {extra && (
            <button role="radio" aria-checked={folder === extra} onClick={() => setFolder(extra)}
              className={cn("rounded-lg border px-3 py-1.5 text-left text-sm", folder === extra ? "border-primary bg-accent ring-1 ring-primary" : "hover:bg-muted")}>
              <Mono>{extra}</Mono> <span className="text-xs text-muted-foreground">· your choice</span>
            </button>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <FolderPicker destinations={data.destinations} onPick={choose} />
          <Button variant="ghost" size="sm" onClick={() => setMk((v) => !v)} aria-expanded={mk}><FolderPlus /> New folder…</Button>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => act(() => api.reveal(item.path))}><FolderSearch /> Show</Button>
            <Button variant="ghost" size="sm" onClick={dismiss} disabled={!!busy}>{busy === "dismiss" ? <Spin /> : null} Leave it</Button>
            <Button onClick={file} disabled={!folder || selectedMissing || !!busy} className="max-w-md">
              {busy === "file" ? <Spin /> : <ArrowRight />}
              <span className="truncate">File it {folder && <>→ <span className="path">{folder}</span></>}</span>
            </Button>
          </div>
        </div>

        {mk && (
          <NewFolderForm
            parents={data.parents}
            current={folder}
            onCancel={() => setMk(false)}
            onCreated={(f) => { setMk(false); choose(f); setExtra(f); setFolder(f); }}
          />
        )}
      </Card>
    </li>
  );
}

function Chip({ c, selected, onSelect }: { c: Candidate; selected: boolean; onSelect: () => void }) {
  return (
    <Tip tip={c.why}>
      <button
        role="radio"
        aria-checked={selected}
        disabled={!c.exists}
        onClick={onSelect}
        className={cn(
          "flex max-w-full items-center gap-2 rounded-lg border px-3 py-1.5 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60",
          selected ? "border-primary bg-accent ring-1 ring-primary" : "bg-card hover:bg-muted",
        )}
      >
        {selected && <Check className="size-3.5 shrink-0 text-primary" aria-hidden />}
        <Mono>{c.folder}</Mono>
        {c.score !== null && <Badge variant={scoreTone(c.score)} className="tabular">{pct(c.score)}</Badge>}
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          {SOURCE_WORDS[c.source]}{c.model_agrees && " · model agrees"}{!c.exists && " (folder missing)"}
        </span>
      </button>
    </Tip>
  );
}

export function FolderPicker({ destinations, onPick, label = "Other folder…" }: { destinations: string[]; onPick: (f: string) => void; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" aria-expanded={open}><ChevronDown /> {label}</Button>
      </PopoverTrigger>
      <PopoverContent className="w-96 p-0" align="start">
        <Command>
          <CommandInput placeholder="Search folders…" />
          <CommandList>
            <CommandEmpty>No folder matches.</CommandEmpty>
            <CommandGroup>
              {destinations.map((d) => (
                <CommandItem key={d} value={d} onSelect={() => { onPick(d); setOpen(false); }}>
                  <span className="path">{d}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function NewFolderForm({ parents, current, onCancel, onCreated }: { parents: string[]; current: string | null; onCancel: () => void; onCreated: (f: string) => void }) {
  const def = useMemo(() => {
    if (current) {
      const p = current.split("/").slice(0, -1).join("/");
      if (parents.includes(p)) return p;
    }
    return parents[0] ?? "";
  }, [current, parents]);
  const [parent, setParent] = useState(def);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    const r = await act(() => api.mkdir(parent, name.trim()));
    setBusy(false);
    if (r?.folder) { toast.success(`Created ${r.folder}`, { description: "Selected for this file." }); onCreated(r.folder); }
  };
  return (
    <form onSubmit={submit} className="mt-3 rounded-lg border bg-muted/40 p-3 fade-in">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="nf-parent" className="text-xs">Inside</Label>
          <Select value={parent} onValueChange={setParent}>
            <SelectTrigger id="nf-parent" className="w-64 font-mono text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>{parents.map((p) => <SelectItem key={p} value={p} className="font-mono text-xs">{p}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="min-w-48 flex-1 space-y-1">
          <Label htmlFor="nf-name" className="text-xs">Folder name</Label>
          <Input id="nf-name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} autoFocus className="font-mono text-sm" />
        </div>
        <Button type="submit" size="sm" disabled={!name.trim() || busy}>{busy && <Spin />} Create folder</Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">Creates an empty folder only. The file moves when you click File it.</p>
    </form>
  );
}

/* ---------------- Recent moves ---------------- */
function RecentMoves() {
  const q = usePoll(api.moves, 30_000);
  if (q.error && !q.data) return <LoadError error={q.error} onRetry={q.reload} />;
  if (!q.data) return <ListSkeleton rows={5} h="h-12" />;
  const { journal, feedback: f } = q.data;
  const rows = [...journal].sort((a, b) => b.ts.localeCompare(a.ts));
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <Card className="overflow-hidden">
        {rows.length === 0 ? (
          <div className="p-6"><EmptyState icon={<Undo2 />} title="No moves yet">Files you file will be listed here, each with an Undo.</EmptyState></div>
        ) : (
          <ul className="divide-y">
            {rows.map((j) => (
              <li key={j.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <span className="w-24 shrink-0 text-xs text-muted-foreground tabular">{dateTime(j.ts)}</span>
                <div className="min-w-0 flex-1">
                  <Tip tip={j.dest}><div className="truncate font-medium" tabIndex={0}>{baseName(j.src)}</div></Tip>
                  <div className="truncate text-xs text-muted-foreground">→ <Mono className="text-xs">{j.folder}</Mono>{j.note && <> · {j.note}</>}</div>
                </div>
                {j.source.startsWith("auto") && <Badge variant="info"><Zap className="size-3" /> auto</Badge>}
                {j.status === "moved" ? (
                  <Button variant="outline" size="sm" onClick={() => undoMove(j.id, q.reload)}><Undo2 /> Undo</Button>
                ) : (
                  <Badge variant={j.status === "interrupted" ? "warning" : "muted"}>{j.status}</Badge>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <div className="space-y-4">
        <Card className="p-4">
          <p className="text-sm leading-relaxed">
            <span className="font-semibold tabular">{f.moves}</span> files filed by you · the first suggestion was right{" "}
            <span className="font-semibold tabular">{f.top_accepted}</span> times ({pct(f.rate)})
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{f.auto_moves} more were filed automatically.</p>
        </Card>
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <caption className="px-4 pt-3 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">By suggested folder</caption>
            <thead><tr className="text-left text-xs text-muted-foreground"><th className="px-4 py-2 font-normal">Folder</th><th className="py-2 font-normal text-right">n</th><th className="px-4 py-2 font-normal text-right">Accepted</th></tr></thead>
            <tbody className="divide-y">
              {f.per_folder.map((p) => (
                <tr key={p.folder}><td className="px-4 py-2"><Mono className="text-xs">{p.folder}</Mono></td><td className="py-2 text-right tabular">{p.n}</td><td className="px-4 py-2 text-right tabular">{p.accepted}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}

/* ---------------- Auto-filing ---------------- */
const SRC_LABEL: Record<string, string> = { rule: "rule", origin: "website", name: "file name", similar: "similar documents" };

function AutoFiling() {
  const q = usePoll(api.autofile, 30_000);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  if (q.error && !q.data) return <LoadError error={q.error} onRetry={q.reload} />;
  if (!q.data) return <ListSkeleton rows={3} h="h-20" />;
  const { settings: s, summary, folders } = q.data;

  const setEnabled = async (on: boolean) => {
    setBusy(true);
    try {
      const cur = await api.settings();
      const raw = structuredClone(cur.raw);
      raw.autofile = { ...(raw.autofile ?? {}), enabled: on };
      const r = await act(() => api.saveSettings(raw), on ? "Auto-filing is on" : "Auto-filing is off");
      if (r) q.reload();
    } catch (e) { toast.error((e as Error).message); }
    setBusy(false);
  };

  const status = (f: AutofileFolder) => {
    if (f.revoked) return <Badge variant="warning">Auto-move undone · {f.needed} more</Badge>;
    if (f.proven) return <Badge variant="success"><CircleCheck className="size-3" /> {s.enabled ? "Auto-filing" : "Proven"}</Badge>;
    if (f.needed > 0) return <Badge variant="muted">Learning · {f.needed} more</Badge>;
    return <Badge variant="danger">Not trusted</Badge>;
  };

  return (
    <div className="space-y-6">
      <Card className="flex flex-wrap items-center gap-4 p-5">
        <div className={cn("rounded-full p-2.5", s.enabled ? "bg-success-soft text-success" : "bg-muted text-muted-foreground")}><Zap className="size-5" /></div>
        <div className="flex-1">
          <div className="font-semibold">Auto-filing is {s.enabled ? "on" : "off"}</div>
          <div className="text-sm text-muted-foreground">{s.enabled ? "Proven folders are filed for you after the waiting time." : "Nothing moves unless you click File it."}</div>
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor="af-switch" className="text-sm">{s.enabled ? "On" : "Off"}</Label>
          <Switch id="af-switch" checked={s.enabled} disabled={busy} onCheckedChange={(v) => (v ? setConfirm(true) : setEnabled(false))} />
        </div>
      </Card>

      <Confirm open={confirm} onOpenChange={setConfirm} title="Turn on auto-filing?" confirmLabel="Turn on" onConfirm={() => setEnabled(true)}>
        <p>Only folders your own decisions have proven will be filed automatically, after the waiting time. Every auto-move can be undone, and undoing one makes that folder start again from zero.</p>
      </Confirm>

      <Notice tone="info">
        A folder is filed automatically only after <b>{s.min_decisions}</b> decisions where you agreed with its suggestion at least <b>{pct(s.min_rate)}</b> of the time,
        counted separately for each kind of suggestion. Similar-document suggestions must also score <b>{pct(s.min_score)}</b> or more.
        New downloads are left alone for <b>{s.delay_minutes}</b> {s.delay_minutes === 1 ? "minute" : "minutes"} first.
      </Notice>

      {s.enabled && (
        <div className="grid grid-cols-3 gap-4">
          <Card className="p-4"><StatBlock label="Auto-filed, last 24 h" value={summary.last24h} /></Card>
          <Card className="p-4"><StatBlock label="Undone" value={summary.undone} /></Card>
          <Card className="p-4"><StatBlock label="Last check" value={when(summary.last_run)} />{summary.last_error && <p className="mt-1 text-xs text-destructive">{summary.last_error}</p>}</Card>
        </div>
      )}

      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b text-left text-xs text-muted-foreground">
            <tr><th className="px-4 py-2.5 font-medium">Folder</th><th className="px-3 font-medium">Suggested by</th><th className="px-3 font-medium w-48">Decisions</th><th className="px-3 font-medium text-right">Agreed</th><th className="px-4 font-medium">Status</th></tr>
          </thead>
          <tbody className="divide-y">
            {folders.map((f) => (
              <tr key={f.folder + f.source}>
                <td className="px-4 py-3"><Mono className="text-xs">{f.folder}</Mono></td>
                <td className="px-3 text-muted-foreground">{SRC_LABEL[f.source] ?? f.source}</td>
                <td className="px-3">
                  <div className="flex items-center gap-2">
                    <Bar value={f.decisions / s.min_decisions} tone={f.proven ? "success" : "primary"} className="w-24" label={`${f.decisions} of ${s.min_decisions} decisions`} />
                    <span className="text-xs tabular text-muted-foreground">{f.decisions}/{s.min_decisions}</span>
                  </div>
                </td>
                <td className={cn("px-3 text-right tabular", f.rate < s.min_rate && "text-warning")}>{pct(f.rate)}</td>
                <td className="px-4">{status(f)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function StatBlock({ label, value }: { label: string; value: React.ReactNode }) {
  return (<><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 text-xl font-semibold tabular">{value}</div></>);
}
