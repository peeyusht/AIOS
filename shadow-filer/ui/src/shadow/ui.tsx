import { useState, type ReactNode } from "react";
import { AlertTriangle, Info, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import type { OkResponse } from "@/lib/types";

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {sub && <div className="mt-1 text-sm text-muted-foreground">{sub}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** The bar under the top bar on the workspace pages (Inbox, Security, Compliance): the title, then filters and views. */
export function WorkBar({ title, sub, children, className }: { title: string; sub?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-6", sub ? "py-3.5" : "min-h-[52px] py-2", className)}>
      <div className={cn("mr-2 min-w-0", sub && "flex-[1_1_360px]")}>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </div>
      {children}
    </div>
  );
}

/** A filter button with a count, as in the workspace bars. */
export function Chip({ on, danger, n, children, ...rest }: { on: boolean; danger?: boolean; n?: number } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" aria-pressed={on} {...rest}
      className={cn("h-[30px] rounded-md border px-2.5 text-xs transition-colors disabled:opacity-50",
        on ? "border-input bg-accent text-foreground" : danger && n ? "border-destructive/40 text-destructive hover:bg-danger-soft" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
      {children}{n != null && <span className={cn("ml-1.5 font-mono tabular", on && "text-muted-foreground")}>{n}</span>}
    </button>
  );
}

/** Small segmented tabs (Flaws / Programs / Services). */
export function SegTabs<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[]; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-0.5 rounded-lg border bg-card p-0.5 text-xs">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)}
          className={cn("h-7 rounded-md px-2.5 transition-colors", value === o.value ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Underlined tabs inside a WorkBar (Inbox views). */
export function BarTabs<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[]; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="-my-2 flex flex-wrap self-stretch">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)}
          className={cn("min-h-[50px] border-b-2 px-3 text-[13px] transition-colors", value === o.value ? "border-primary font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded-xl border bg-card text-card-foreground shadow-[0_1px_2px_0_oklch(0_0_0/0.04)]", className)} {...rest}>
      {children}
    </div>
  );
}

export function Notice({ tone = "info", icon, children, className }: { tone?: "info" | "warn" | "danger" | "success"; icon?: ReactNode; children: ReactNode; className?: string }) {
  const tones = {
    info: "bg-info-soft text-foreground border-transparent",
    warn: "bg-warning-soft text-foreground border-warning/30",
    danger: "bg-danger-soft text-foreground border-destructive/30",
    success: "bg-success-soft text-foreground border-success/30",
  };
  const iconTone = { info: "text-primary", warn: "text-warning", danger: "text-destructive", success: "text-success" };
  return (
    <div className={cn("flex items-start gap-3 rounded-lg border px-4 py-3 text-sm", tones[tone], className)} role={tone === "danger" ? "alert" : undefined}>
      <span className={cn("mt-0.5 shrink-0 [&_svg]:size-4", iconTone[tone])}>{icon ?? (tone === "info" ? <Info /> : <AlertTriangle />)}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-16 text-center">
      <div className="mb-3 rounded-full bg-muted p-3 text-muted-foreground [&_svg]:size-6">{icon}</div>
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-muted-foreground">{children}</div>}
    </div>
  );
}

export function ListSkeleton({ rows = 4, h = "h-24" }: { rows?: number; h?: string }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className={cn("w-full rounded-xl", h)} />)}
    </div>
  );
}

export function LoadError({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <Notice tone="warn">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>Couldn't load this: {error.message}</span>
        {onRetry && <Button size="sm" variant="outline" onClick={onRetry}>Try again</Button>}
      </div>
    </Notice>
  );
}

export function Mono({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return <span className={cn("path break-all", className)} title={title}>{children}</span>;
}

export function Tip({ tip, children }: { tip: ReactNode; children: ReactNode }) {
  if (!tip) return <>{children}</>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent className="max-w-sm break-all">{tip}</TooltipContent>
    </Tooltip>
  );
}

export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border bg-muted/60 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-md px-3 py-1 text-sm transition-colors",
            value === o.value ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Bar({ value, tone = "primary", className, label }: { value: number; tone?: "primary" | "success" | "warning" | "destructive"; className?: string; label?: string }) {
  const tones = { primary: "bg-primary", success: "bg-success", warning: "bg-warning", destructive: "bg-destructive" };
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-muted", className)} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v * 100)} aria-label={label}>
      <div className={cn("h-full rounded-full transition-[width] duration-500", tones[tone])} style={{ width: `${v * 100}%` }} />
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular">{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

export function Confirm({
  open, onOpenChange, title, children, confirmLabel, onConfirm, danger,
}: { open: boolean; onOpenChange: (o: boolean) => void; title: string; children: ReactNode; confirmLabel: string; onConfirm: () => void | Promise<void>; danger?: boolean }) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription asChild><div className="space-y-2 text-sm text-muted-foreground">{children}</div></AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className={danger ? "bg-destructive text-destructive-foreground hover:bg-destructive/90" : undefined}
            onClick={() => void onConfirm()}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** Runs a mutating call; toasts message on failure. Returns the response or null. */
export async function act<T extends OkResponse>(fn: () => Promise<T>, okMsg?: string): Promise<T | null> {
  try {
    const r = await fn();
    if (!r.ok) { toast.error(r.message ?? "That didn't work."); return null; }
    if (okMsg || r.message) toast.success(okMsg ?? r.message);
    return r;
  } catch (e) {
    if (e instanceof ApiError && e.kind === "stale") return null;
    toast.error((e as Error).message);
    return null;
  }
}

export function useBusy() {
  const [busy, setBusy] = useState<string | null>(null);
  const run = async <T,>(key: string, fn: () => Promise<T>) => {
    setBusy(key);
    try { return await fn(); } finally { setBusy(null); }
  };
  return { busy, run };
}

export const Spin = () => <Loader2 className="animate-spin" aria-hidden />;

export function Highlight({ text, query }: { text: string; query: string }) {
  const words = query.split(/\s+/).filter((w) => w.length > 1).map((w) => w.replace(/[.*+?^${}()|[\]\\"]/g, "\\$&"));
  if (!words.length) return <>{text}</>;
  const re = new RegExp(`(${words.join("|")})`, "gi");
  return (
    <>
      {text.split(re).map((part, i) =>
        i % 2 ? <mark key={i} className="rounded-sm bg-warning-soft px-0.5 text-foreground">{part}</mark> : <span key={i}>{part}</span>,
      )}
    </>
  );
}
