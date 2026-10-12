import { useCallback, useEffect, useRef, useState } from "react";
import { Copy, ExternalLink, FileText, FolderSearch } from "lucide-react";
import { toast } from "sonner";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { bytes, dateTime, when } from "@/lib/format";
import type { FileTicket, PreviewResponse } from "@/lib/types";
import { EmptyState, Notice, Segmented, Spin, act } from "./ui";

const fmt = (n: number) => n.toLocaleString();

/** Read-only side panel showing the text the agent holds for a file. */
export function FilePreview({ path, onClose }: { path: string | null; onClose: () => void }) {
  const [data, setData] = useState<PreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"document" | "text">("text");
  const requestId = useRef(0);

  const load = useCallback(async (p: string) => {
    const id = ++requestId.current;
    setLoading(true); setError(null); setData(null);
    try {
      const r = await api.preview(p);
      if (id !== requestId.current) return;
      setMode(r.view ? "document" : "text");
      if (!r.ok) setError(r.message ?? "Couldn't load the preview.");
      else setData(r);
    } catch (e) {
      if (id === requestId.current) setError((e as Error).message);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (path) void load(path);
    else { setData(null); setError(null); setLoading(false); }
    return () => { requestId.current++; };
  }, [path, load]);

  const name = data?.name ?? (path ? path.split(/[\\/]/).pop() : "") ?? "";
  const copy = async () => {
    try { await navigator.clipboard.writeText(data?.text ?? ""); toast.success("Copied"); }
    catch { toast.error("Couldn't copy the text."); }
  };
  const openBtn = data?.openable ? (
    <Button variant="outline" size="sm" onClick={() => act(() => api.searchOpen(data.path))}><ExternalLink /> Open</Button>
  ) : null;

  return (
    <Sheet open={!!path} onOpenChange={(o) => { if (!o) onClose(); }}>
      <SheetContent side="right" className="flex w-full flex-col gap-4 h-full min-h-0 sm:max-w-[min(960px,92vw)]">
        <SheetHeader className="pr-6 text-left">
          <SheetTitle className="path break-all text-base font-medium">{name}</SheetTitle>
          <SheetDescription>
            {data ? (
              <>
                {bytes(data.size)} · modified {dateTime(data.modified)}
                {data.read_at ? <> · read by the agent {when(data.read_at)}</> : null}
              </>
            ) : "Preview"}
          </SheetDescription>
        </SheetHeader>

        {path && (
          <div className="flex flex-wrap gap-2">
            {openBtn}
            <Button variant="ghost" size="sm" onClick={() => act(() => api.reveal(path))}><FolderSearch /> Show</Button>
          </div>
        )}

        {loading && (
          <div className="space-y-2.5" aria-busy="true" aria-label="Loading">
            {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-4" style={{ width: `${70 + ((i * 37) % 30)}%` }} />)}
          </div>
        )}

        {error && path && (
          <Notice tone="danger">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>{error}</span>
              <Button size="sm" variant="outline" onClick={() => load(path)}>Retry</Button>
            </div>
          </Notice>
        )}

        {data?.view && (
          <div><Segmented value={mode} onChange={setMode} label="Preview view" options={[{ value: "document", label: "Document" }, { value: "text", label: "Text" }]} /></div>
        )}
        {path && data?.view && mode === "document" && (
          <DocumentView key={path} data={data} openBtn={openBtn} onText={() => setMode("text")} />
        )}

        {data && (!data.view || mode === "text") && (
          <>
            {data.note && data.text && <Notice tone={data.status === "ocr" ? "info" : "warn"}>{data.note}</Notice>}
            {data.text ? (
              <div className="flex min-h-0 flex-1 flex-col gap-2">
                {data.truncated && (
                  <p className="text-xs text-muted-foreground">Long document: this is the start of it ({fmt(data.chars)} characters). Open it to see everything.</p>
                )}
                <div className="flex items-center justify-end gap-2 text-xs text-muted-foreground">
                  <span className="tabular">{fmt(data.chars)} characters</span>
                  <Button variant="ghost" size="sm" onClick={copy}><Copy /> Copy</Button>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border bg-muted/30 p-4 text-sm leading-relaxed select-text" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }} tabIndex={0}>
                  {data.text}
                </div>
              </div>
            ) : (
              <EmptyState icon={<FileText />} title="Nothing to preview">
                <p>{data.note || "The agent holds no text for this file."}</p>
                {openBtn && <div className="mt-3">{openBtn}</div>}
              </EmptyState>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}


/** Tickets and document bytes live only as long as this view is mounted. */
function DocumentView({ data, openBtn, onText }: { data: PreviewResponse; openBtn: React.ReactNode; onText: () => void }) {
  const [ticket, setTicket] = useState<FileTicket | null>(null);
  const [phase, setPhase] = useState<"loading" | "drawing" | null>("loading");
  const [error, setError] = useState<string | null>(null);
  const [drawingFailed, setDrawingFailed] = useState(false);
  const [pixels, setPixels] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const frame = useRef<HTMLIFrameElement | null>(null);
  const retried = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let ownedUrl: string | null = null;
    const documentFrame = frame.current;
    setTicket(null); setPhase("loading"); setError(null); setDrawingFailed(false); setPixels(null);
    const release = () => {
      if (ownedUrl?.startsWith("blob:")) URL.revokeObjectURL(ownedUrl);
      ownedUrl = null;
    };
    const getTicket = async () => {
      const next = await api.fileTicket(data.path);
      if (!active) {
        if (next.url?.startsWith("blob:")) URL.revokeObjectURL(next.url);
        return null;
      }
      ownedUrl = next.url;
      if (!next.ok) throw new Error(next.message ?? "Couldn't load the document.");
      return next;
    };
    const run = async () => {
      try {
        let next = await getTicket();
        if (!next) return;
        // Check the HTTP status ourselves: iframe/img load events don't expose a 404.
        let response = await fetch(next.url, { signal: controller.signal, cache: "no-store" });
        if (response.status === 404 && !retried.current) {
          retried.current = true;
          release();
          next = await getTicket();
          if (!next) return;
          response = await fetch(next.url, { signal: controller.signal, cache: "no-store" });
        }
        if (!response.ok) throw new Error(`Couldn't load the document (HTTP ${response.status}).`);
        const blob = await response.blob();
        if (!active) return;
        setTicket(next);
        if (next.kind !== "docx") {
          if (next.kind === "pdf") setPhase(null);
          return;
        }
        setPhase("drawing");
        try {
          const { renderAsync } = await import("docx-preview");
          if (!active) return;
          const doc = documentFrame?.contentDocument;
          if (!doc) throw new Error("The document frame is unavailable.");
          doc.head.replaceChildren(); doc.body.replaceChildren();
          // Packaged pictures can render, but nothing in the Word file can contact a website.
          const policy = doc.createElement("meta");
          policy.httpEquiv = "Content-Security-Policy";
          policy.content = "default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; font-src 'none'; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'";
          doc.head.append(policy);
          await renderAsync(blob, doc.body, doc.head, { inWrapper: true, ignoreFonts: true, useBase64URL: true, renderHeaders: true, renderFooters: true, renderFootnotes: true, breakPages: true, experimental: false, className: "docx" });
          if (!active) { doc.body.replaceChildren(); return; }
          doc.querySelectorAll("a[href]").forEach((link) => link.removeAttribute("href"));
          doc.head.prepend(policy);
          const style = doc.createElement("style");
          style.textContent = "body{margin:0;background:#f3f4f6} .docx-wrapper{background:#f3f4f6;padding:16px} .docx-wrapper>section.docx{box-shadow:0 1px 4px rgba(0,0,0,.15);margin-bottom:16px}";
          doc.head.append(style);
          setPhase(null);
        } catch {
          if (active) { setDrawingFailed(true); setError("This Word file could not be drawn here."); setPhase(null); }
        }
      } catch (e) {
        if (active) { setError((e as Error).message); setPhase(null); }
      }
    };
    void run();
    return () => {
      active = false; controller.abort(); release();
      const doc = documentFrame?.contentDocument;
      doc?.body.replaceChildren(); doc?.head.replaceChildren();
    };
  }, [data.path, retry]);

  const mediaError = async () => {
    if (!ticket) return;
    try {
      const response = await fetch(ticket.url, { cache: "no-store" });
      if (response.status === 404 && !retried.current) {
        retried.current = true; setRetry((n) => n + 1); return;
      }
    } catch { /* The failure is shown below. */ }
    setPhase(null); setError("Couldn't load the document.");
  };

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border bg-muted/40">
      {error ? (
        <div className="p-4"><Notice tone="warn">
          <p>{error}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {(data.text || drawingFailed) && <Button variant="outline" size="sm" onClick={onText}>Show the text</Button>}
            {openBtn}
          </div>
        </Notice></div>
      ) : (
        <>
          {data.view === "docx" && <iframe ref={frame} sandbox="allow-same-origin" title={data.name} className="h-full min-h-0 w-full flex-1 rounded-lg border [background:Canvas] [color-scheme:light]" />}
          {ticket?.kind === "pdf" && <iframe src={ticket.url} title={data.name} className="h-full min-h-0 w-full flex-1 rounded-lg border [background:Canvas] [color-scheme:light]" onLoad={() => setPhase(null)} onError={() => void mediaError()} />}
          {ticket?.kind === "image" && (
            <div className="flex min-h-0 flex-1 flex-col p-4">
              <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto">
                <img src={ticket.url} alt={data.name} className="max-h-full max-w-full object-contain" onLoad={(event) => { const image = event.currentTarget; setPixels(`${image.naturalWidth} × ${image.naturalHeight}`); setPhase(null); }} onError={() => void mediaError()} />
              </div>
              {pixels && <p className="mt-2 text-center text-xs text-muted-foreground tabular">{pixels}</p>}
            </div>
          )}
          {phase && <div className="absolute inset-0 flex items-center justify-center gap-2 bg-muted/40 text-sm text-muted-foreground" role="status"><Spin />{phase === "drawing" ? "Drawing the document…" : "Loading the document…"}</div>}
        </>
      )}
    </div>
  );
}
