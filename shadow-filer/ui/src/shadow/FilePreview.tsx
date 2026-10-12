import { useCallback, useEffect, useState } from "react";
import { Copy, ExternalLink, FileText, FolderSearch } from "lucide-react";
import { toast } from "sonner";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { bytes, dateTime, when } from "@/lib/format";
import type { PreviewResponse } from "@/lib/types";
import { EmptyState, Notice, act } from "./ui";

const fmt = (n: number) => n.toLocaleString();

/** Read-only side panel showing the text the agent holds for a file. */
export function FilePreview({ path, onClose }: { path: string | null; onClose: () => void }) {
  const [data, setData] = useState<PreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (p: string) => {
    setLoading(true); setError(null); setData(null);
    try {
      const r = await api.preview(p);
      if (!r.ok) setError(r.message ?? "Couldn't load the preview.");
      else setData(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (path) void load(path); }, [path, load]);

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
      <SheetContent side="right" className="flex w-full flex-col gap-4 sm:max-w-[640px]">
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

        {data && (
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
