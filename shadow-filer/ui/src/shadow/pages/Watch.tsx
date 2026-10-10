import { useMemo, useState } from "react";
import { BellRing, CalendarClock, ChevronDown, FolderSearch, Inbox as InboxIcon, RefreshCw, ShieldCheck, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes, dateTime, when } from "@/lib/format";
import type { WatchDate, WatchResponse, WatchSensitive } from "@/lib/types";
import { Card, EmptyState, ListSkeleton, LoadError, Mono, Notice, PageHeader, Spin, Tip, act } from "../ui";
import { emitWatchChanged } from "../App";

const KIND: Record<WatchDate["kind"], string> = {
  expires: "Expires", "valid until": "Valid until", due: "Due", renewal: "Renewal", ends: "Ends",
};

function longDate(s: string) {
  const [y, m, d] = s.split("-").map(Number);
  const dt = new Date(y ?? 0, (m ?? 1) - 1, d ?? 1);
  if (isNaN(dt.getTime())) return s;
  return dt.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
function relDays(n: number) {
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  return n > 0 ? `in ${n} days` : `${-n} days ago`;
}

export function WatchPage() {
  const q = usePoll<WatchResponse>(() => api.watch(), 300_000);
  const [refreshing, setRefreshing] = useState(false);
  const d = q.data;

  const refresh = async () => {
    setRefreshing(true);
    try { q.setData(await api.watch(true)); emitWatchChanged(); }
    catch (e) { toast.error((e as Error).message); }
    finally { setRefreshing(false); }
  };

  const dismiss = async (path: string, name: string, kind: "date" | "sensitive", key: string) => {
    const r = await act(() => api.watchDismiss(path, kind, key));
    if (!r) return;
    await q.reload(); emitWatchChanged();
    toast(`Dismissed ${name}`, {
      action: {
        label: "Undo",
        onClick: async () => {
          if (await act(() => api.watchDismiss(path, kind, key, true))) { await q.reload(); emitWatchChanged(); }
        },
      },
    });
  };
  const reveal = (path: string) => void act(() => api.searchReveal(path));

  return (
    <div>
      <PageHeader
        title="Watch"
        sub={
          <>
            Dates coming up in your documents, and sensitive files left in Downloads.
            {d?.scanned_at && <span className="block">Checked {when(d.scanned_at)} · {(d.files_read ?? 0).toLocaleString()} files</span>}
          </>
        }
        actions={<Button variant="outline" onClick={refresh} disabled={refreshing}>{refreshing ? <Spin /> : <RefreshCw />} Refresh</Button>}
      />
      {q.error && !d && <LoadError error={q.error} onRetry={q.reload} />}
      {!d && !q.error && <ListSkeleton rows={4} />}
      {d && !d.enabled && (
        <EmptyState icon={<BellRing />} title="Document watch is turned off">
          Turn it on in <a href="#/settings" className="text-primary underline-offset-4 hover:underline">Settings › Document watch</a>.
        </EmptyState>
      )}
      {d && d.enabled && (
        <>
          {d.error && <Notice tone="warn" className="mb-4">{d.error}</Notice>}
          <Tabs defaultValue="dates">
            <TabsList className="mb-6">
              <TabsTrigger value="dates">Dates{d.counts.soon > 0 && <span className="ml-1.5 tabular text-warning">{d.counts.soon}</span>}</TabsTrigger>
              <TabsTrigger value="sensitive">Sensitive files{d.counts.sensitive > 0 && <span className="ml-1.5 tabular text-muted-foreground">{d.counts.sensitive}</span>}</TabsTrigger>
            </TabsList>
            <TabsContent value="dates"><Dates d={d} onReveal={reveal} onDismiss={(x) => dismiss(x.path, x.name, "date", x.key)} /></TabsContent>
            <TabsContent value="sensitive"><Sensitive d={d} onReveal={reveal} onDismiss={(x) => dismiss(x.path, x.name, "sensitive", x.key)} /></TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}

type View = "upcoming" | "soon" | "later" | "passed";

function Dates({ d, onReveal, onDismiss }: { d: WatchResponse; onReveal: (p: string) => void; onDismiss: (x: WatchDate) => void }) {
  const [view, setView] = useState<View>("upcoming");
  const rows = useMemo(() => {
    const list = d.dates.filter((x) => (view === "upcoming" ? x.status !== "passed" : x.status === view));
    return [...list].sort((a, b) => (view === "passed" ? b.days - a.days : a.days - b.days));
  }, [d.dates, view]);
  const soonDays = d.settings?.soon_days;
  const tiles = [
    { key: "soon" as const, label: "Coming up", n: d.counts.soon, sub: soonDays != null ? `within ${soonDays} days` : undefined, tone: "text-warning" },
    { key: "later" as const, label: "Later", n: d.counts.later, sub: undefined, tone: "text-foreground" },
    { key: "passed" as const, label: "Recently passed", n: d.counts.passed, sub: undefined, tone: "text-muted-foreground" },
  ];

  return (
    <div className="space-y-4">
      <Notice>A date is listed only when the document says what it is, for example 'valid until' or 'due date'. It can still be wrong: check the quoted line.</Notice>
      <div className="grid grid-cols-3 gap-3">
        {tiles.map((t) => {
          const active = view === t.key || (view === "upcoming" && t.key !== "passed");
          return (
            <button
              key={t.key}
              onClick={() => setView(view === t.key ? "upcoming" : t.key)}
              aria-pressed={view === t.key}
              className={cn("rounded-xl border bg-card px-4 py-3 text-left transition-colors hover:bg-accent/40", active ? "border-primary/40 ring-1 ring-primary/20" : "opacity-70")}
            >
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t.label}</div>
              <div className={cn("mt-1 text-2xl font-semibold tabular", t.tone)}>{t.n}</div>
              {t.sub && <div className="text-xs text-muted-foreground">{t.sub}</div>}
            </button>
          );
        })}
      </div>
      {view !== "upcoming" && (
        <button className="text-sm text-primary underline-offset-4 hover:underline" onClick={() => setView("upcoming")}>Show coming up and later</button>
      )}
      {rows.length === 0 ? (
        <EmptyState icon={<CalendarClock />} title="No dates coming up">Nothing found in your documents yet.</EmptyState>
      ) : (
        <div className="space-y-3">{rows.map((x) => <DateRow key={x.path + x.key} x={x} onReveal={onReveal} onDismiss={onDismiss} />)}</div>
      )}
      {(d.older_passed ?? 0) > 0 && (
        <p className="text-sm text-muted-foreground">
          {d.older_passed} older dates that passed more than {d.settings?.keep_expired_days ?? "—"} days ago are not listed.
        </p>
      )}
    </div>
  );
}

function DateRow({ x, onReveal, onDismiss }: { x: WatchDate; onReveal: (p: string) => void; onDismiss: (x: WatchDate) => void }) {
  const tone = x.status === "soon" ? "text-warning" : x.status === "passed" ? "text-muted-foreground" : "text-foreground";
  return (
    <Card className="flex gap-5 p-4">
      <div className="w-36 shrink-0">
        <div className={cn("text-lg font-semibold tabular", tone)}>{longDate(x.date)}</div>
        <div className="text-sm text-muted-foreground">{relDays(x.days)}</div>
        <Badge variant={x.status === "soon" ? "warning" : "muted"} className="mt-1.5">{KIND[x.kind] ?? x.kind}</Badge>
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <Tip tip={x.path}><div className="truncate font-medium">{x.name}</div></Tip>
        <Mono className="text-xs text-muted-foreground">{x.folder}</Mono>
        {x.context && <blockquote className="border-l-2 pl-3 text-sm italic text-muted-foreground">“{x.context}”</blockquote>}
        {x.copies.length > 0 && (
          <Collapsible>
            <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
              also in {x.copies.length} other {x.copies.length === 1 ? "place" : "places"}
              <ChevronDown className="size-3 transition-transform group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <ul className="mt-1 space-y-0.5">{x.copies.map((c) => <li key={c}><Mono className="text-xs text-muted-foreground">{c}</Mono></li>)}</ul>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
      <div className="flex shrink-0 items-start gap-2">
        <Button size="sm" variant="outline" onClick={() => onReveal(x.path)}><FolderSearch /> Show</Button>
        <Tip tip="Not a deadline, or already dealt with">
          <Button size="sm" variant="ghost" onClick={() => onDismiss(x)}><X /> Dismiss</Button>
        </Tip>
      </div>
    </Card>
  );
}

function Sensitive({ d, onReveal, onDismiss }: { d: WatchResponse; onReveal: (p: string) => void; onDismiss: (x: WatchSensitive) => void }) {
  return (
    <div className="space-y-4">
      <Notice icon={<ShieldCheck />}>
        These files in Downloads contain personal or financial details. File them or delete them rather than leaving them here. The numbers themselves are never shown or stored by this page.
      </Notice>
      {d.sensitive.length === 0 ? (
        <EmptyState icon={<ShieldCheck />} title="No sensitive files found in Downloads." />
      ) : (
        <div className="space-y-3">
          {d.sensitive.map((x) => (
            <Card key={x.path} className="flex items-start gap-4 p-4">
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Tip tip={x.path}><span className="truncate font-medium">{x.name}</span></Tip>
                  <Badge variant={x.level === "high" ? "danger" : "warning"}>{x.level === "high" ? "Identity or card data" : "Personal details"}</Badge>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                  <Mono>{x.folder}</Mono><span>{bytes(x.size)}</span><span>Modified {dateTime(x.modified)}</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {x.found.map((f) => (
                    <Badge key={f.kind} variant="muted">{f.label}{f.count > 1 && ` ×${f.count}`}</Badge>
                  ))}
                </div>
              </div>
              <div className="flex shrink-0 items-start gap-2">
                <Button size="sm" variant="outline" onClick={() => onReveal(x.path)}><FolderSearch /> Show</Button>
                <Button size="sm" variant="outline" asChild><a href="#/inbox"><InboxIcon /> Go to Inbox</a></Button>
                <Button size="sm" variant="ghost" onClick={() => onDismiss(x)}><X /> It's fine here</Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
