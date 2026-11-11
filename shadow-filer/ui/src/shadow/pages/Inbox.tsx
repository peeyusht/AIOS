import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ArrowRight, Check, ChevronDown, ChevronLeft, ChevronRight, CircleCheck, Copy, FolderPlus, FolderSearch, Inbox as InboxIcon,
  RefreshCw, Undo2, Zap,
  Eye,
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
import type { AutofileFolder, AutofileResponse, Candidate, InboxItem, InboxResponse } from "@/lib/types";
import { Bar, Card, Confirm, EmptyState, ListSkeleton, LoadError, Mono, Notice, PageHeader, Spin, Tip, act } from "../ui";
import { emitInboxChanged } from "../App";
import { FilePreview } from "../FilePreview";

const PAGE = 25;

export function InboxPage() {
  return (
    <>
      <PageHeader title="Inbox" sub="New downloads, each with where it probably belongs. Nothing moves until you say so." />
      <Tabs defaultValue="waiting">
        <TabsList className="mb-4">
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
  const [preview, setPreview] = useState<string | null>(null);
  const q = usePoll(() => api.inbox(offset, PAGE), 30_000, [offset]);
  const [auto, setAuto] = useState<AutofileResponse | null>(null);
  const loadAuto = () => { api.autofile().then(setAuto).catch(() => {}); };
  useEffect(loadAuto, []);
  useEffect(() => {
    const h = () => { q.reload(); loadAuto(); };
    window.addEventListener("sf-inbox-changed", h);
    return () => window.removeEventListener("sf-inbox-changed", h);
  }, [q]);
  const autoOn = !!auto?.settings.enabled;

  const d = q.data;
  const items = d?.items ?? [];
  const [sel, setSel] = useState<string | null>(null);
  const current = items.find((i) => i.path === sel) ?? items[0] ?? null;
  const removeLocal = (path: string) => {
    const at = items.findIndex((i) => i.path === path);
    const next = items[at + 1] ?? items[at - 1] ?? null;
    setSel(next?.path ?? null);
    q.setData((cur) => cur && { ...cur, items: cur.items.filter((i) => i.path !== path), total: cur.total - 1 });
  };

  // Keyboard: J/K or arrows move, 1-4 pick a folder, Enter files, S skips to the next one. Never while typing.
  const actions = useRef<{ file: () => void; pick: (i: number) => void } | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.ctrlKey || e.metaKey || e.altKey || !current) return;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.closest("[role=dialog],[role=alertdialog],[data-radix-popper-content-wrapper]"))) return;
      const at = items.findIndex((i) => i.path === current.path);
      const move = (n: number) => { const it = items[Math.max(0, Math.min(items.length - 1, at + n))]; if (it) { setSel(it.path); listRef.current?.querySelector<HTMLElement>(`[data-path="${CSS.escape(it.path)}"]`)?.scrollIntoView({ block: "nearest" }); } };
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "s") { e.preventDefault(); move(1); }
      else if (/^[1-4]$/.test(e.key)) { e.preventDefault(); actions.current?.pick(Number(e.key) - 1); }
      else if (e.key === "Enter" && (!t || t === document.body || t.closest("[data-inbox-list]"))) { e.preventDefault(); actions.current?.file(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, current]);

  const counts = { strong: 0, likely: 0, unsure: 0 };
  for (const it of items) counts[strength(it)]++;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {d ? (
            <>
              <span className="font-medium text-foreground tabular">{d.total}</span> files waiting in Downloads
              {items.length > 0 && <> · <span className="tabular">{counts.strong}</span> strong · <span className="tabular">{counts.likely}</span> likely · <span className="tabular">{counts.unsure}</span> unsure</>}
              {d.examples && <> · learned from <span className="tabular">{d.examples.examples.toLocaleString()}</span> filed documents</>}
            </>
          ) : " "}
        </p>
        <div className="flex items-center gap-2">
          <Badge variant={autoOn ? "info" : "muted"}><Zap className="size-3" /> Auto-filing {autoOn ? "on" : "off"}</Badge>
          <Button variant="outline" size="sm" onClick={() => q.reload()} disabled={q.loading}>
            <RefreshCw className={cn(q.loading && "animate-spin")} /> Refresh
          </Button>
        </div>
      </div>

      {q.error && !d && <LoadError error={q.error} onRetry={q.reload} />}
      {!d && !q.error && <ListSkeleton rows={4} h="h-24" />}
      {d && items.length === 0 && (
        <EmptyState icon={<InboxIcon />} title="Nothing waiting">
          Downloads is tidy. New files will show up here with a suggested folder.
        </EmptyState>
      )}
      {d && items.length > 0 && current && (
        <div className="grid items-start gap-4 min-[1000px]:grid-cols-[minmax(300px,380px)_minmax(0,1fr)]">
          <Card className="overflow-hidden rounded-lg min-[1000px]:sticky min-[1000px]:top-16">
            <ul ref={listRef} data-inbox-list aria-label="Files waiting" className="max-h-[calc(100vh-11rem)] divide-y overflow-y-auto">
              {items.map((it) => {
                const top = it.candidates.find((c) => c.exists);
                const st = strength(it);
                const on = it.path === current.path;
                return (
                  <li key={it.path}>
                    <button data-path={it.path} aria-current={on ? "true" : undefined} onClick={() => setSel(it.path)}
                      className={cn("flex w-full gap-3 px-3.5 py-2.5 text-left transition-colors", on ? "bg-accent shadow-[inset_2px_0_0_var(--color-primary)]" : "hover:bg-muted/50")}>
                      <span className="mt-0.5 flex h-5 w-11 shrink-0 items-center justify-center rounded border font-mono text-[10px] uppercase text-muted-foreground">{(it.ext || "file").slice(0, 5)}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{it.name}</span>
                        <span className="block truncate font-mono text-[11px] text-muted-foreground">→ {top ? top.folder : it.ready ? "no suggestion" : "being read"}</span>
                      </span>
                      <span className="flex shrink-0 flex-col items-end gap-1">
                        <Strength level={st} />
                        <span className="font-mono text-[10px] text-muted-foreground">{when(it.added)}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {d.total > PAGE && (
              <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted-foreground">
                <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}><ChevronLeft /> Newer</Button>
                <span className="tabular">{offset + 1}–{Math.min(offset + PAGE, d.total)} of {d.total}</span>
                <Button variant="ghost" size="sm" disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)}>Older <ChevronRight /></Button>
              </div>
            )}
          </Card>
          <DecisionPane key={current.path} item={current} data={d} auto={auto} onGone={() => removeLocal(current.path)} onPreview={setPreview} bind={(a) => { actions.current = a; }} />
        </div>
      )}
      <FilePreview path={preview} onClose={() => setPreview(null)} />
    </div>
  );
}

type Strength = "strong" | "likely" | "unsure";
/** How much to trust the first suggestion, from the measured accuracy of each kind (see the percentage note). */
function strength(it: InboxItem): Strength {
  const c = it.candidates.find((x) => x.exists);
  if (!c) return "unsure";
  if (c.source === "rule" || c.source === "origin") return "strong";
  if (c.source === "similar") return (c.score ?? 0) >= 0.95 ? "strong" : (c.score ?? 0) >= 0.5 ? "likely" : "unsure";
  if (c.source === "name") return "likely";
  return "unsure";
}
function Strength({ level }: { level: Strength }) {
  const n = level === "strong" ? 3 : level === "likely" ? 2 : 1;
  return (
    <span role="img" aria-label={level} title={level} className="flex gap-0.5">
      {[0, 1, 2].map((i) => <span key={i} className={cn("h-2.5 w-1", i < n ? (level === "unsure" ? "bg-warning" : "bg-primary") : "bg-border")} />)}
    </span>
  );
}

const SOURCE_WORDS: Record<string, string> = { rule: "Your rule", origin: "Same website", name: "File name", similar: "Similar documents", model: "Model's guess" };

function cleanupLabel(c: NonNullable<InboxItem["cleanup"]>) {
  if (c.category === "duplicate_of_filed") return "Already filed (duplicate)";
  if (c.category === "partial_download") return "Partial download";
  return `Cleanup: ${c.level}`;
}

function DecisionPane({ item, data, auto, onGone, onPreview, bind }: {
  item: InboxItem; data: InboxResponse; auto: AutofileResponse | null; onGone: () => void; onPreview: (path: string) => void;
  bind: (a: { file: () => void; pick: (i: number) => void }) => void;
}) {
  // One option per folder: when several kinds of suggestion name the same folder, their evidence is shown together.
  const chips = useMemo(() => {
    const out: (Candidate & { evidence: Candidate[] })[] = [];
    for (const c of item.candidates) {
      const hit = out.find((o) => o.folder === c.folder);
      if (hit) hit.evidence.push(c); else out.push({ ...c, evidence: [c] });
    }
    return out.slice(0, 4);
  }, [item.candidates]);
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
    if (!folder || selectedMissing || busy) return;
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
  bind({ file: () => void file(), pick: (i) => { const c = chips[i]; if (c?.exists) setFolder(c.folder); } });

  const chosen = chips.find((c) => c.folder === folder);
  const trust = chosen && auto ? auto.folders.find((f) => f.folder === chosen.folder && f.source === chosen.source) : undefined;
  const need = auto?.settings.min_decisions ?? 20;

  return (
    <Card className="min-w-0 rounded-lg">
      <div className="space-y-2 border-b p-5">
        <Tip tip={item.path}><h2 className="break-words text-lg font-semibold leading-snug" tabIndex={0}>{item.name}</h2></Tip>
        <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-muted-foreground">
          <span>{(item.ext || "file").toUpperCase()} · {bytes(item.size)}</span>
          <span>arrived {when(item.added)}</span>
          {item.origin?.host && <span>from {item.origin.host}</span>}
        </div>
        {(item.cleanup || item.duplicate || item.auto.auto || !item.ready) && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {item.cleanup && <Badge variant={item.cleanup.level === "safe" ? "success" : "warning"} title={item.cleanup.reason}>{cleanupLabel(item.cleanup)}</Badge>}
            {item.duplicate && <Badge variant="muted"><Copy className="size-3" /> Same as a file in <span className="path text-xs">{item.duplicate.folder}</span></Badge>}
            {item.auto.auto && (
              <Badge variant="info" title={item.auto.why}>
                <Zap className="size-3" /> {auto?.settings.enabled ? "Auto-files on next run" : "Would auto-file"}{item.auto.soon && " · after the waiting time"}
              </Badge>
            )}
            {!item.ready && <span className="text-xs italic text-muted-foreground">Still being read; suggestions from similar files appear once it's indexed.</span>}
          </div>
        )}
        <div className="flex flex-wrap gap-2 pt-1">
          <Button variant="outline" size="sm" onClick={() => onPreview(item.path)}><Eye /> Preview</Button>
          <Button variant="outline" size="sm" onClick={() => act(() => api.reveal(item.path))}><FolderSearch /> Show in Explorer</Button>
        </div>
      </div>

      <div className="space-y-3 p-5">
        <h3 className="label-caps text-muted-foreground">Where should it go?</h3>
        {chips.length === 0 && <p className="text-sm text-muted-foreground">No suggestion for this file. Pick a folder below.</p>}
        <div className="space-y-2" role="radiogroup" aria-label={`Destination for ${item.name}`}>
          {chips.map((c, i) => {
            const on = folder === c.folder;
            return (
              <button key={c.folder} role="radio" aria-checked={on} disabled={!c.exists} onClick={() => setFolder(c.folder)}
                className={cn("flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                  on ? "border-primary bg-accent ring-1 ring-primary" : "hover:bg-muted/50")}>
                <span className={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border", on && "border-primary bg-primary")}>{on && <Check className="size-3 text-primary-foreground" aria-hidden />}</span>
                <span className="min-w-0 flex-1 space-y-1.5">
                  <span className="block break-all font-mono text-[13px] font-medium">{c.folder}{!c.exists && <span className="font-sans text-xs font-normal text-muted-foreground"> (folder missing)</span>}</span>
                  {c.evidence.map((e) => (
                    <span key={e.source} className="block space-y-0.5">
                      <span className="flex items-center gap-2 text-xs">
                        <span className="w-32 shrink-0 text-muted-foreground">{SOURCE_WORDS[e.source] ?? e.source}</span>
                        {e.score != null ? <>
                          <span className="h-1 max-w-40 flex-1 overflow-hidden rounded-full bg-border"><span className="block h-full bg-primary" style={{ width: `${Math.round(e.score * 100)}%` }} /></span>
                          <span className="font-mono tabular">{pct(e.score)}</span>
                        </> : null}
                      </span>
                      <span className="block text-xs text-muted-foreground">{e.why}{e.model_agrees && " · the model agrees"}</span>
                    </span>
                  ))}
                </span>
                <kbd className="shrink-0 rounded border px-1.5 font-mono text-[11px] text-muted-foreground">{i + 1}</kbd>
              </button>
            );
          })}
          {extra && (
            <button role="radio" aria-checked={folder === extra} onClick={() => setFolder(extra)}
              className={cn("flex w-full items-center gap-3 rounded-lg border p-3 text-left", folder === extra ? "border-primary bg-accent ring-1 ring-primary" : "hover:bg-muted/50")}>
              <span className="min-w-0 flex-1 break-all font-mono text-[13px]">{extra}</span><span className="text-xs text-muted-foreground">your choice</span>
            </button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <FolderPicker destinations={data.destinations} onPick={choose} />
          <Button variant="ghost" size="sm" onClick={() => setMk((v) => !v)} aria-expanded={mk}><FolderPlus /> New folder…</Button>
        </div>
        {mk && (
          <NewFolderForm
            parents={data.parents}
            current={folder}
            onCancel={() => setMk(false)}
            onCreated={(f) => { setMk(false); choose(f); setExtra(f); setFolder(f); }}
          />
        )}

        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          <Button onClick={() => void file()} disabled={!folder || selectedMissing || !!busy} className="h-10 max-w-full">
            {busy === "file" ? <Spin /> : <ArrowRight />}
            <span className="truncate">File it {folder && <>→ <span className="font-mono text-xs">{folder.split("/").pop()}</span></>}</span>
            <kbd className="ml-1 rounded border border-primary-foreground/30 px-1 font-mono text-[10px] opacity-80">Enter</kbd>
          </Button>
          <Button variant="outline" onClick={dismiss} disabled={!!busy} className="h-10">{busy === "dismiss" ? <Spin /> : null} Leave it in Downloads</Button>
          <span className="ml-auto text-xs text-muted-foreground">Every move can be undone from Recent moves.</span>
        </div>

        {chosen && chosen.source !== "model" && auto && (
          <div className="space-y-2 rounded-lg border bg-muted/40 p-3">
            <div className="flex flex-wrap justify-between gap-2 text-xs">
              <span className="font-medium">Auto-filing trust for {chosen.folder.split("/").pop()} ({SOURCE_WORDS[chosen.source]?.toLowerCase()})</span>
              <span className="font-mono tabular text-muted-foreground">{trust ? `${trust.decisions}/${need} · ${pct(trust.rate)}` : `0/${need}`}</span>
            </div>
            <div role="img" aria-label={`${trust?.decisions ?? 0} of ${need} decisions`} className="grid gap-0.5" style={{ gridTemplateColumns: `repeat(${need}, minmax(0, 1fr))` }}>
              {Array.from({ length: need }).map((_, i) => <span key={i} className={cn("h-2 rounded-[1px]", i < (trust?.agreed ?? 0) ? "bg-primary" : i < (trust?.decisions ?? 0) ? "bg-warning" : "bg-border")} />)}
            </div>
            <p className="text-xs text-muted-foreground">
              {trust?.proven ? (auto.settings.enabled ? "Proven: files like this are filed for you after the waiting time." : "Proven. Files like this would be filed for you if auto-filing were on.")
                : `Needs ${need} decisions with ${pct(auto.settings.min_rate)} agreement${trust?.revoked ? " (an auto-move was undone, so it starts again)" : ""}. Auto-filing stays off until you switch it on.`}
            </p>
          </div>
        )}

        <p className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-muted-foreground"><span>J/K next, previous</span><span>1–{Math.max(1, chips.length)} choose</span><span>Enter file it</span><span>S skip</span></p>
      </div>
    </Card>
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
