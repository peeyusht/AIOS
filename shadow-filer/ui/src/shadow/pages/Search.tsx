import { useEffect, useRef, useState } from "react";
import { Eye, ChevronDown, Database, ExternalLink, FolderSearch, RotateCcw, Search as SearchIcon } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { api } from "@/lib/api";
import { useDebounced, usePoll } from "@/lib/hooks";
import { bytes, when } from "@/lib/format";
import type { SearchResponse } from "@/lib/types";
import { Bar, Card, Confirm, EmptyState, Highlight, ListSkeleton, Mono, Notice, PageHeader, Segmented, act } from "../ui";
import { cn } from "@/lib/utils";
import { FilePreview } from "../FilePreview";

const STATUS: Record<string, string> = {
  ocr: "Text from OCR", ocr_empty: "OCR found no text", locked: "Password-protected", name_only: "Name only",
  no_text: "No text (scanned?)", cloud: "Cloud-only, name only", error: "Error",
};

export function SearchPage() {
  const [q, setQ] = useState(() => sessionStorage.getItem("sf-q") ?? "");
  const [scope, setScope] = useState<"all" | "para" | "inbox">("all");
  const [types, setTypes] = useState<"any" | "docs" | "pdf" | "sheets" | "slides">("any");
  const dq = useDebounced(q, 350);
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => { sessionStorage.setItem("sf-q", q); }, [q]);
  useEffect(() => {
    if (!dq.trim()) { setRes(null); return; }
    const my = ++seq.current;
    setLoading(true);
    api.search(dq.trim(), scope, types)
      .then((r) => { if (my === seq.current) { setRes(r); setErr(null); } })
      .catch((e) => { if (my === seq.current) setErr(e.message); })
      .finally(() => { if (my === seq.current) setLoading(false); });
  }, [dq, scope, types]);

  return (
    <>
      <PageHeader title="Search" sub="Find files by what they're about, not just their name." />
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input
          autoFocus
          aria-label="Search your files"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={'Describe what you\'re looking for, e.g. "posture audit findings for the bank" or "PVK-2026-TCS-001"'}
          className="h-14 rounded-xl pl-12 text-base shadow-sm"
        />
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Segmented label="Where" value={scope} onChange={setScope} options={[{ value: "all", label: "Everywhere" }, { value: "para", label: "Organized" }, { value: "inbox", label: "Downloads" }]} />
        <Segmented label="Type" value={types} onChange={setTypes} options={[{ value: "any", label: "Any" }, { value: "docs", label: "Documents" }, { value: "pdf", label: "PDF" }, { value: "sheets", label: "Sheets" }, { value: "slides", label: "Slides" }]} />
        {res && <span className="ml-auto text-sm text-muted-foreground tabular" aria-live="polite">{res.results.length} results · {res.ms} ms</span>}
      </div>

      <div className="mt-6 space-y-3">
        {res && !res.semantic && (
          <Notice tone="warn">Meaning-based search is unavailable right now, so these are keyword matches only: {res.semantic_error}</Notice>
        )}
        {err && <Notice tone="warn">Search failed: {err}</Notice>}
        {loading && !res && <ListSkeleton rows={3} h="h-24" />}
        {!dq.trim() && <EmptyState icon={<SearchIcon />} title="Search everything you've filed">Type a phrase, a code or a name. Results combine exact words and meaning.</EmptyState>}
        {res && res.results.length === 0 && <EmptyState icon={<SearchIcon />} title="No matches">Try different words, or widen the filters. Searched {res.searched_files.toLocaleString()} files.</EmptyState>}
        <ul className={cn("space-y-3", loading && "opacity-60 transition-opacity")}>
          {res?.results.map((r) => (
            <li key={r.path + (r.part ?? "")}>
              <Card className="p-4">
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-medium" title={r.path}><Highlight text={r.name} query={dq} /></h3>
                      {r.keyword && <Badge variant="muted">words</Badge>}
                      {r.similarity !== null && <Badge variant="info" className="tabular">meaning {Math.round(r.similarity * 100)}%</Badge>}
                      {r.status !== "ok" && <Badge variant={r.status === "error" ? "danger" : "warning"}>{STATUS[r.status] ?? r.status}</Badge>}
                    </div>
                    {r.snippet && <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-muted-foreground"><Highlight text={r.snippet} query={dq} /></p>}
                    <div className="mt-2 text-xs text-muted-foreground">
                      <Mono className="text-xs">{r.folder}</Mono> · {bytes(r.size)} · {when(r.modified)}{r.part != null && <> · part {r.part}</>}
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setPreviewPath(r.path)}><Eye /> Preview</Button>
                    {r.openable && <Button size="sm" variant="outline" onClick={() => act(() => api.searchOpen(r.path))}><ExternalLink /> Open</Button>}
                    <Button size="sm" variant="ghost" onClick={() => act(() => api.searchReveal(r.path))}><FolderSearch /> Show</Button>
                  </div>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      </div>
      <IndexPanel />
      <FilePreview path={previewPath} onClose={() => setPreviewPath(null)} />
    </>
  );
}

function IndexPanel() {
  const [open, setOpen] = useState(false);
  const s = usePoll(api.searchStatus, 5_000);
  const [confirm, setConfirm] = useState(false);
  const d = s.data;
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mt-10">
      <Card>
        <CollapsibleTrigger className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left">
          <Database className="size-4 text-muted-foreground" />
          <span className="font-medium">Index</span>
          <span className="text-sm text-muted-foreground">
            {d ? (d.running ? `${d.phase ?? "Indexing"} · ${d.done.toLocaleString()} of ${d.todo.toLocaleString()}` : `Up to date · last checked ${when(d.last_sweep)}`) : "…"}
          </span>
          <ChevronDown className={cn("ml-auto size-4 transition-transform", open && "rotate-180")} />
        </CollapsibleTrigger>
        <CollapsibleContent>
          {d && (
            <div className="space-y-5 border-t px-4 py-4 text-sm">
              {d.running && (
                <div className="space-y-1.5">
                  <Bar value={d.todo ? d.done / d.todo : 0} label="Indexing progress" />
                  {d.current && <Mono className="text-xs text-muted-foreground">{d.current}</Mono>}
                </div>
              )}
              <div className="grid gap-6 md:grid-cols-2">
                <div>
                  <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Folders</h4>
                  <ul className="space-y-1">{d.roots.map((r) => (
                    <li key={r.path} className="flex items-center gap-2"><Mono className="text-xs">{r.path}</Mono>{!r.exists && <Badge variant="warning">missing</Badge>}</li>
                  ))}</ul>
                  <h4 className="mb-2 mt-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">Files by status</h4>
                  <ul className="grid grid-cols-2 gap-x-4 gap-y-1">{Object.entries(d.by_status).map(([k, v]) => (
                    <li key={k} className="flex justify-between"><span className="text-muted-foreground">{k === "ok" ? "Text read" : STATUS[k] ?? k}</span><span className="tabular">{v.toLocaleString()}</span></li>
                  ))}</ul>
                </div>
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
                  <dt className="text-muted-foreground">Model</dt><dd><Mono className="text-xs">{d.model}</Mono> <Badge variant={d.model_ok ? "success" : "warning"}>{d.model_ok ? "ready" : "unavailable"}</Badge></dd>
                  <dt className="text-muted-foreground">OCR</dt><dd>{d.ocr.enabled ? (d.ocr.available ? d.ocr.message : `Unavailable: ${d.ocr.message}`) : "Off"}</dd>
                  <dt className="text-muted-foreground">Keyword index</dt><dd>{d.fts ? "Ready" : "Not available"}</dd>
                  <dt className="text-muted-foreground">Index size</dt><dd className="tabular">{bytes(d.db_bytes)}</dd>
                  {d.last_error && (<><dt className="text-muted-foreground">Last error</dt><dd className="text-destructive">{d.last_error}</dd></>)}
                </dl>
              </div>
              {d.errors.length > 0 && (
                <div>
                  <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Failed files</h4>
                  <ul className="space-y-1">{d.errors.map((e) => <li key={e.path}><Mono className="text-xs">{e.path}</Mono> <span className="text-muted-foreground">— {e.error}</span></li>)}</ul>
                </div>
              )}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
                <p className="text-xs text-muted-foreground">Runs only on this PC. search.db holds text from your documents; delete it any time and it is rebuilt.</p>
                <Button variant="outline" size="sm" onClick={() => setConfirm(true)} disabled={d.running}><RotateCcw /> Rebuild index</Button>
              </div>
            </div>
          )}
        </CollapsibleContent>
      </Card>
      <Confirm open={confirm} onOpenChange={setConfirm} title="Rebuild the search index?" confirmLabel="Rebuild" onConfirm={async () => { await act(() => api.rebuildIndex()); s.reload(); }}>
        <p>All documents are read again. Search keeps working on keywords meanwhile, but this can take a while and uses the CPU and GPU.</p>
      </Confirm>
    </Collapsible>
  );
}
