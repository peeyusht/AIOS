import { useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Check, Copy, HelpCircle, Info, ListChecks, Printer, RefreshCw, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CheckStatus, ComplianceCheck, ComplianceControl, ComplianceFramework, ComplianceResponse, DeclaredAnswer } from "@/lib/types";
import { act, Card, Confirm, ListSkeleton, LoadError, Segmented, WorkBar, Spin, Tip, useBusy } from "../ui";

const ORDER: Record<CheckStatus, number> = { fail: 0, warn: 1, unknown: 2, info: 3, pass: 4 };
const LABEL: Record<CheckStatus, string> = { pass: "Passed", fail: "Failing", warn: "Worth a look", unknown: "Could not be checked", info: "Note" };
const PAGE: Record<string, string> = { "/network": "Network", "/security": "Security", "/library": "Library", "/watch": "Watch", "/settings": "Settings" };
const SQUARE = { pass: "bg-success", fail: "bg-destructive", warn: "bg-warning", unknown: "bg-muted-foreground/30", info: "bg-muted" };

function Mark({ status, quiet }: { status: CheckStatus; quiet?: boolean }) {
  const map = {
    pass: [Check, "text-success bg-success-soft"], fail: [X, "text-destructive bg-danger-soft"], warn: [AlertTriangle, "text-warning bg-warning-soft"],
    unknown: [HelpCircle, "text-muted-foreground bg-muted"], info: [Info, "text-muted-foreground bg-muted"],
  } as const;
  const [Icon, tone] = map[status];
  return <span role="img" aria-label={LABEL[status]} title={LABEL[status]} className={cn("inline-flex size-6 shrink-0 items-center justify-center rounded-full", tone, quiet && "opacity-60")}><Icon className="size-3.5" /></span>;
}

function CheckRow({ c, onAccept, onWithdraw }: { c: ComplianceCheck; onAccept: () => void; onWithdraw: () => void }) {
  const [all, setAll] = useState(false);
  const shown = all ? c.evidence : c.evidence.slice(0, 4);
  const hidden = c.evidence.slice(4);
  return (
    <div data-print-row className={cn("flex gap-3 px-5 py-3.5", c.accepted && "bg-muted/30")}>
      <Mark status={c.status} quiet={!!c.accepted || c.status === "info"} />
      <div className={cn("min-w-0 flex-1 space-y-1.5", c.accepted && "text-muted-foreground")}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{c.title}</span>
          {c.status === "info" && <Badge variant="muted">Note</Badge>}
          {c.accepted && <Badge variant="muted">Accepted</Badge>}
        </div>
        <p className="text-sm leading-relaxed">{c.detail}</p>
        {c.evidence.length > 0 && (
          <ul className="space-y-0.5 text-muted-foreground">
            {shown.map((e, i) => <li key={i} className="path break-all">{e}</li>)}
            {!all && hidden.map((e, i) => <li key={"h" + i} data-print-collapsed className="path hidden break-all">{e}</li>)}
          </ul>
        )}
        {c.evidence.length > 4 && <button className="text-xs text-primary hover:underline" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${c.evidence.length}`}</button>}
        {c.fix && c.status !== "pass" && (
          <p className="text-sm"><span className="text-muted-foreground">What to do: </span>{c.fix}{c.to && <> <a href={"#" + c.to} data-print-hide className="ml-1 text-xs text-primary hover:underline">Open {PAGE[c.to] ?? c.to.slice(1)}</a></>}</p>
        )}
        {!c.fix && c.to && <a href={"#" + c.to} data-print-hide className="inline-block text-xs text-primary hover:underline">Open {PAGE[c.to] ?? c.to.slice(1)}</a>}
        {c.accepted && (
          <div className="rounded-md border border-dashed px-3 py-2 text-sm">
            Accepted {when(c.accepted.ts)}: {c.accepted.reason}
            <button className="ml-2 text-xs text-primary hover:underline" onClick={onWithdraw}>Withdraw</button>
          </div>
        )}
        {(c.status === "fail" || c.status === "warn") && !c.accepted && (
          <Button variant="ghost" size="sm" className="-ml-2 h-7 text-muted-foreground" onClick={onAccept}>Accept with a reason…</Button>
        )}
      </div>
    </div>
  );
}

function ControlCard({ ctl, onAccept, onWithdraw }: { ctl: ComplianceControl; onAccept: (c: ComplianceCheck) => void; onWithdraw: (c: ComplianceCheck) => void }) {
  const sorted = [...ctl.checks].sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  const rest = sorted.filter((c) => c.status !== "pass");
  const passed = sorted.filter((c) => c.status === "pass");
  const [open, setOpen] = useState(rest.length === 0);
  const counts = [
    ctl.counts.pass && `${ctl.counts.pass} passed`, ctl.counts.fail && `${ctl.counts.fail} failing`, ctl.counts.warn && `${ctl.counts.warn} worth a look`,
    ctl.counts.unknown && `${ctl.counts.unknown} could not be checked`, ctl.accepted && `${ctl.accepted} accepted`,
  ].filter(Boolean).join(" · ");
  const row = (c: ComplianceCheck) => <CheckRow key={c.id} c={c} onAccept={() => onAccept(c)} onWithdraw={() => onWithdraw(c)} />;
  return (
    <Card data-print-card className="overflow-hidden rounded-lg">
      <div data-print-row className="flex items-start gap-3 border-b px-5 py-4">
        <Mark status={ctl.status} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 className="font-semibold">{ctl.title} <span className="ml-1 text-sm font-normal text-muted-foreground">{LABEL[ctl.status].toLowerCase()}</span></h2>
            <span className="text-xs text-muted-foreground tabular">{counts}</span>
          </div>
          <p className="mt-0.5 text-sm text-muted-foreground">{ctl.about}</p>
        </div>
      </div>
      <div className="divide-y">
        {rest.map(row)}
        {passed.length > 0 && (open
          ? passed.map(row)
          : <>
              <button data-print-hide className="flex w-full items-center gap-2 px-5 py-2.5 text-left text-sm text-muted-foreground hover:bg-muted/40" onClick={() => setOpen(true)}>
                <Check className="size-4 text-success" />{passed.length} passed · show
              </button>
              <div data-print-collapsed className="hidden divide-y">{passed.map(row)}</div>
            </>)}
        {open && rest.length > 0 && passed.length > 0 && <button className="w-full px-5 py-2 text-left text-xs text-muted-foreground hover:bg-muted/40" onClick={() => setOpen(false)}>Hide passed</button>}
      </div>
    </Card>
  );
}

function Declared({ d, onSave }: { d: ComplianceResponse["declared"][number]; onSave: (a: DeclaredAnswer, note: string, dated: string) => void }) {
  const [note, setNote] = useState(d.note);
  const [dated, setDated] = useState(d.dated ?? "");
  const opts = [{ value: "yes", label: "Yes" }, { value: "no", label: "No" }, { value: "na", label: "Does not apply" }] as const;
  const pick = (v: "yes" | "no" | "na") => onSave(d.answer === v ? null : v, note, dated);
  return (
    <div data-print-row className="grid gap-3 px-5 py-4 min-[1000px]:grid-cols-[1fr_auto]">
      <div className="min-w-0">
        <div className="font-medium">{d.title}</div>
        <p className="text-sm text-muted-foreground">{d.about}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Input value={note} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== d.note && onSave(d.answer, note, dated)} placeholder="Note (optional)" className="h-8 max-w-md text-sm" aria-label={`Note for: ${d.title}`} />
          <Input type="date" value={dated} max={new Date().toISOString().slice(0, 10)} disabled={!d.answer} onChange={(e) => setDated(e.target.value)}
            onBlur={() => dated !== (d.dated ?? "") && d.answer && onSave(d.answer, note, dated)} className="h-8 w-40 text-sm" aria-label={`Date for: ${d.title}`} title="The day this is about (the last test, drill or assessment); optional" />
        </div>
        {d.note && <p className="hidden text-sm print:block">Note: {d.note}</p>}
        {d.dated && <p className="hidden text-sm print:block">Dated: {d.dated}</p>}
      </div>
      <div className="flex flex-col items-start gap-1.5 min-[1000px]:items-end">
        <div data-print-hide className="flex items-center gap-2">
          <Segmented label={d.title} value={(d.answer ?? "") as "yes"} onChange={(v) => pick(v)} options={opts as unknown as { value: "yes"; label: string }[]} />
          {d.answer && <button className="text-xs text-muted-foreground hover:text-foreground hover:underline" onClick={() => onSave(null, note, "")}>Clear</button>}
        </div>
        <span className="hidden text-sm font-medium print:inline">Declared: {d.answer ? opts.find((o) => o.value === d.answer)?.label : "not answered"}</span>
        <span className="text-xs text-muted-foreground">{d.ts ? `answered ${when(d.ts)}` : "not answered"}</span>
      </div>
    </div>
  );
}

function History({ data }: { data: ComplianceResponse }) {
  const h = data.history;
  if (h.length < 2) return <p className="px-5 py-4 text-sm text-muted-foreground">History builds up from today: one line is kept per day.</p>;
  const months = h.map((x, i) => {
    const m = new Date(x.day + "T12:00:00").toLocaleDateString(undefined, { month: "short" });
    const change = i > 0 && x.day.slice(5, 7) !== h[i - 1]!.day.slice(5, 7);
    const soon = i === 0 && h.slice(1, 5).some((y) => y.day.slice(5, 7) !== x.day.slice(5, 7));
    return (i === 0 && !soon) || change ? m : "";
  });
  return (
    <div className="overflow-x-auto px-5 py-4">
      <div className="inline-grid items-center gap-x-3 gap-y-1.5" style={{ gridTemplateColumns: "max-content max-content" }}>
        <span />
        <div className="flex gap-[3px] text-[11px] text-muted-foreground">{months.map((m, i) => <span key={i} className="w-2.5 overflow-visible whitespace-nowrap">{m}</span>)}</div>
        {data.controls.map((ctl) => <div key={ctl.key} className="contents">
          <span className="text-xs text-muted-foreground">{ctl.title}</span>
          <div className="flex gap-[3px]">
            {h.map((x) => {
              const s = x.controls[ctl.key] ?? "unknown";
              return <Tip key={x.day} tip={`${x.day}: ${LABEL[s].toLowerCase()}`}><span tabIndex={0} aria-label={`${ctl.title} ${x.day}: ${LABEL[s]}`} className={cn("block size-2.5 rounded-[2px]", SQUARE[s])} /></Tip>;
            })}
          </div>
        </div>)}
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
        {(["pass", "fail", "warn", "unknown"] as const).map((s) => <span key={s} className="flex items-center gap-1.5"><span className={cn("size-2.5 rounded-[2px]", SQUARE[s])} />{LABEL[s]}</span>)}
      </div>
    </div>
  );
}

const ACTION = { update: "Update", stop: "Stopped", firewall: "Firewall" } as const;

function Section({ title, sub, children }: { title: string; sub?: ReactNode; children: ReactNode }) {
  return <section className="space-y-3"><div><h2 className="text-sm font-semibold">{title}</h2>{sub && <p className="text-sm text-muted-foreground">{sub}</p>}</div>{children}</section>;
}

const CODE: Record<CheckStatus, { glyph: string; label: string; cls: string }> = {
  fail: { glyph: "✕", label: "FAIL", cls: "bg-danger-soft text-destructive" },
  warn: { glyph: "▲", label: "LOOK", cls: "bg-warning-soft text-warning" },
  unknown: { glyph: "?", label: "UNKNOWN", cls: "bg-muted text-muted-foreground" },
  info: { glyph: "○", label: "NOTE", cls: "bg-muted text-muted-foreground" },
  pass: { glyph: "✓", label: "PASS", cls: "bg-success-soft text-success" },
};
function Code({ status, accepted }: { status: CheckStatus; accepted?: boolean }) {
  const c = CODE[status];
  return <span className={cn("inline-flex min-w-[76px] items-center gap-1.5 rounded px-1.5 font-mono text-[11px] font-semibold leading-5", c.cls, accepted && "opacity-60")} title={LABEL[status]}><span aria-hidden>{c.glyph}</span>{c.label}{accepted && <span className="font-normal"> · acc.</span>}</span>;
}
const AREA_STATE: Record<string, string> = { pass: "Met", fail: "Not met", warn: "Look at", unknown: "Not judged", info: "Notes only" };

/** Which frameworks the page offers. Every one is judged from the same measurement; this only chooses what is shown. */
function FrameworkPicker({ all, onSaved }: { all: ComplianceFramework[]; onSaved: (first: string) => void }) {
  const [open, setOpen] = useState(false);
  const [on, setOn] = useState<string[]>([]);
  const start = () => { setOn(all.filter((f) => f.shown).map((f) => f.key)); setOpen(true); };
  const save = async () => {
    if (!on.length) { toast.error("Choose at least one."); return; }
    if (await act(() => api.complianceFrameworks(on))) onSaved(all.find((f) => on.includes(f.key))!.key);
  };
  return <>
    <Button variant="outline" size="sm" onClick={start}><ListChecks />Frameworks</Button>
    <Confirm open={open} onOpenChange={setOpen} title="Frameworks shown on this page" confirmLabel="Save" onConfirm={save}>
      <div className="space-y-2 text-foreground">
        {all.map((f) => (
          <label key={f.key} className="flex items-start gap-2.5 rounded-md border px-3 py-2">
            <input type="checkbox" className="mt-1" checked={on.includes(f.key)} onChange={(e) => setOn(e.target.checked ? [...on, f.key] : on.filter((k) => k !== f.key))} />
            <span><span className="block text-sm font-medium">{f.title}</span><span className="block text-xs text-muted-foreground">{f.scheme}</span></span>
          </label>
        ))}
      </div>
      <p>The same measurements are judged by each framework's own rules. Nothing is sent anywhere.</p>
    </Confirm>
  </>;
}

type Pick = { kind: "check"; id: string } | { kind: "declared"; key: string };

export function CompliancePage() {
  const [fw, setFw] = useState<string | undefined>(undefined);
  const q = usePoll<ComplianceResponse>(() => api.compliance(false, fw), 300_000, [fw]);
  const { busy, run } = useBusy();
  const [accepting, setAccepting] = useState<ComplianceCheck | null>(null);
  const [reason, setReason] = useState("");
  const keep = useRef(false);
  const [area, setArea] = useState<string | "all" | "declared">("all");
  const [pick, setPick] = useState<Pick | null>(null);
  const d = q.data;

  const refresh = () => run("refresh", async () => { try { q.setData(await api.compliance(true, fw)); } catch (e) { toast.error((e as Error).message); } });
  const switchTo = (k: string) => { setArea("all"); setPick(null); setFw(k); };
  const frameworks = d?.frameworks ?? [];
  const shown = frameworks.filter((f) => f.shown);
  const copy = async () => { try { await navigator.clipboard.writeText(d?.text ?? ""); toast.success("Copied"); } catch { toast.error("Could not copy to the clipboard."); } };
  const accept = async () => {
    if (!accepting) return;
    if (!reason.trim()) { keep.current = true; toast.error("Write why this is acceptable."); return; }
    if (await act(() => api.complianceAccept(accepting.id, reason.trim()))) q.reload();
  };
  const withdraw = async (c: ComplianceCheck) => { if (await act(() => api.complianceAccept(c.id, ""))) q.reload(); };
  const declare = async (key: string, a: DeclaredAnswer, note: string, dated = "") => { if (await act(() => api.complianceDeclare(key, a, note, dated))) q.reload(); };
  const startAccept = (c: ComplianceCheck) => { setReason(""); setAccepting(c); };

  const dev = d?.device ?? {};
  const deviceLine = [dev.name, [dev.manufacturer, dev.model].filter(Boolean).join(" "), dev.serial && `serial ${dev.serial}`, dev.windows && `${dev.windows}${dev.build ? `, build ${dev.build}` : ""}`].filter(Boolean).join(" · ");
  const s = d?.summary ?? {};
  const assessedDate = d?.assessed_at ? new Date(d.assessed_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : "";

  const controls = d?.controls ?? [];
  const all = controls.flatMap((ctl) => ctl.checks.map((c) => ({ c, ctl })));
  const firstBad = all.find((x) => x.c.status === "fail" && !x.c.accepted) ?? all.find((x) => x.c.status === "warn" && !x.c.accepted) ?? all[0];
  const chosen: Pick | null = pick ?? (firstBad ? { kind: "check", id: firstBad.c.id } : null);
  const shownControls = area === "all" ? controls : controls.filter((c) => c.key === area);
  const showDeclared = area === "all" || area === "declared";
  const answered = d?.declared.filter((x) => x.answer).length ?? 0;
  const hist = (d?.history ?? []).slice(-30);

  return <div className="flex flex-1 flex-col text-[13px]">
    {d?.assessed_at && <p data-print="only" className="mb-4 hidden text-lg font-semibold">Security posture of {dev.name ?? "this PC"}, assessed {assessedDate}</p>}
    <WorkBar
      title="Compliance evidence"
      sub={<>{d?.title ?? "Cyber Essentials"}, measured on this PC and declared by you. Evidence, not a certificate; nothing is sent anywhere.
        {d?.scheme && <> Judged against {d.scheme}.</>}
        {deviceLine && <span className="block font-mono text-[11px]">{deviceLine}</span>}</>}
    >
      <div data-print-hide className="flex flex-wrap items-center gap-2">
        {shown.length > 1 && <Segmented label="Framework" value={d?.framework ?? shown[0]!.key} onChange={switchTo} options={shown.map((f) => ({ value: f.key, label: f.title }))} />}
        {frameworks.length > 0 && <FrameworkPicker all={frameworks} onSaved={switchTo} />}
        {d?.assessed_at && <span className="font-mono text-[11px] text-muted-foreground">assessed {when(d.assessed_at)}</span>}
        <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={busy === "refresh"}>{busy === "refresh" ? <Spin /> : <RefreshCw />}Check again</Button>
        <Button variant="outline" size="sm" onClick={() => void copy()} disabled={!d?.text}><Copy />Copy as text</Button>
        <Button size="sm" onClick={() => window.print()} disabled={!d}><Printer />Print evidence</Button>
      </div>
    </WorkBar>
    {q.error && <div className="px-6 pt-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
    {d && !d.assessed_at && <div className="px-6 pt-4"><LoadError error={new Error(d.error ?? "The assessment has not run yet.")} onRetry={() => void refresh()} /></div>}
    {!d ? (!q.error && <div className="px-6 pt-4"><ListSkeleton rows={5} /></div>) : d.assessed_at && <div className="flex flex-1 flex-col">
      <div className="hidden grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-px overflow-hidden rounded-lg border bg-border print:grid" data-print-card>
        {[
          ["Control areas met", `${s.controls_passing ?? "—"}/${s.controls ?? controls.length}`, s.controls_passing != null && s.controls_passing < (s.controls ?? controls.length) ? "text-warning" : ""],
          ["Failing checks", s.fail ?? "—", s.fail ? "text-destructive" : ""],
          ["To look at", s.warn ?? "—", s.warn ? "text-warning" : ""],
          ["Not judged", s.unknown ?? "—", ""],
          ["Accepted", s.accepted ?? "—", ""],
          ["Declared", `${answered}/${d.declared.length}`, ""],
        ].map(([label, value, tone]) => (
          <div key={label as string} className="bg-card px-4 py-3"><div className="label-caps text-muted-foreground">{label}</div><div className={cn("mt-1 font-mono text-2xl font-semibold tabular", tone as string)}>{value}</div></div>
        ))}
      </div>

      <div data-print-hide className="flex flex-1 flex-wrap items-stretch border-b">
        <div className="min-w-0 flex-[1_1_240px] border-r bg-sidebar px-3 py-4 min-[1100px]:max-w-[300px]">
         <div className="space-y-1 min-[900px]:sticky min-[900px]:top-[72px]">
          <div className="flex items-baseline gap-2 px-2 pb-2.5">
            <span className={cn("font-mono text-[26px] font-semibold leading-none tabular", s.controls_passing != null && s.controls_passing < (s.controls ?? controls.length) && "text-warning")}>{s.controls_passing ?? "—"}/{s.controls ?? controls.length}</span>
            <span className="text-xs text-muted-foreground">control areas met</span>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 px-2 pb-3 font-mono text-[11px] text-muted-foreground">
            <span className={cn(s.fail ? "text-destructive" : "")}>{s.fail ?? 0} fail</span><span className={cn(s.warn ? "text-warning" : "")}>{s.warn ?? 0} look</span><span>{s.unknown ?? 0} unknown</span><span>{s.accepted ?? 0} accepted</span>
          </div>
          <nav aria-label="Control areas" className="space-y-1">
            {[{ key: "all", title: "All areas", status: null as null | CheckStatus, sub: `${all.length} checks` },
              ...controls.map((c) => ({ key: c.key as string, title: c.title, status: c.status as CheckStatus, sub: [AREA_STATE[c.status], c.counts.fail && `${c.counts.fail} fail`, c.counts.warn && `${c.counts.warn} look`].filter(Boolean).join(" · ") })),
            ].map((x) => (
              <button key={x.key} aria-pressed={area === x.key} onClick={() => setArea(x.key)}
                className={cn("flex min-h-11 w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-colors", area === x.key ? "bg-accent" : "hover:bg-muted/60")}>
                <span aria-hidden className={cn("w-4 shrink-0 text-center font-mono text-sm font-bold", x.status ? CODE[x.status].cls.split(" ").find((k) => k.startsWith("text-")) : "text-muted-foreground")}>{x.status ? CODE[x.status].glyph : "≡"}</span>
                <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{x.title}</span><span className="block truncate text-[11px] text-muted-foreground">{x.sub}</span></span>
              </button>
            ))}
            <div aria-hidden className="mx-2 my-1 h-px bg-border" />
            <button aria-pressed={area === "declared"} onClick={() => setArea("declared")}
              className={cn("flex min-h-11 w-full items-center gap-2.5 rounded-lg border border-dashed px-2.5 py-1.5 text-left", area === "declared" ? "bg-accent" : "hover:bg-muted/60")}>
              <span aria-hidden className="w-4 shrink-0 text-center font-mono text-sm text-muted-foreground">✎</span>
              <span className="min-w-0 flex-1"><span className="block text-sm font-medium">Declared by you</span><span className="block text-[11px] text-muted-foreground">{answered} of {d.declared.length} answered</span></span>
            </button>
          </nav>
          {hist.length > 1 && (
            <div className="space-y-1.5 px-2.5 pb-1 pt-3">
              <div className="label-caps text-muted-foreground">Areas met, last {hist.length} days</div>
              <div role="img" aria-label={`Control areas met per day: ${hist.map((h) => h.summary.controls_passing).join(", ")}`} className="flex h-9 items-end gap-0.5">
                {hist.map((h, i) => <span key={h.day} className={cn("flex-1", i === hist.length - 1 ? "bg-primary" : "bg-primary/40")} style={{ height: `${Math.max(1, h.summary.controls_passing) / Math.max(1, controls.length) * 100}%` }} title={`${h.day}: ${h.summary.controls_passing}`} />)}
              </div>
              <div className="flex justify-between font-mono text-[10px] text-muted-foreground"><span>{hist[0]!.day.slice(5)}</span><span>today</span></div>
            </div>
          )}
         </div>
        </div>

        <section aria-label="Checks" className="min-w-0 flex-[999_1_520px]">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px]">
              <thead><tr className="label-caps bg-sidebar text-left text-muted-foreground"><th className="py-2.5 pl-5 pr-2 font-medium">Status</th><th className="px-2 py-2.5 font-medium">Check</th><th className="py-2.5 pl-2 pr-5 font-medium">Found</th></tr></thead>
              {shownControls.map((ctl) => (
                <tbody key={ctl.key}>
                  <tr><th scope="rowgroup" colSpan={3} className="label-caps border-t px-5 pb-1.5 pt-3.5 text-left font-medium text-muted-foreground">{ctl.title}</th></tr>
                  {[...ctl.checks].sort((a, b) => ORDER[a.status] - ORDER[b.status]).map((c) => {
                    const on = chosen?.kind === "check" && chosen.id === c.id;
                    return (
                      <tr key={c.id} onClick={() => setPick({ kind: "check", id: c.id })} className={cn("cursor-pointer align-top", on ? "bg-accent shadow-[inset_2px_0_0_var(--color-primary)]" : "hover:bg-muted/40")}>
                        <td className="whitespace-nowrap py-2 pl-5 pr-2"><Code status={c.status} accepted={!!c.accepted} /></td>
                        <td className="px-2 py-2"><button className="text-left font-medium hover:underline" aria-pressed={on} onClick={(e) => { e.stopPropagation(); setPick({ kind: "check", id: c.id }); }}>{c.title}</button></td>
                        <td className="py-2 pl-2 pr-5 text-muted-foreground"><span className="line-clamp-2">{c.detail}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              ))}
              {showDeclared && (
                <tbody>
                  <tr><th scope="rowgroup" colSpan={3} className="label-caps border-t px-5 pb-1.5 pt-3.5 text-left font-medium text-muted-foreground">Declared by you · never measured</th></tr>
                  {d.declared.map((x) => {
                    const on = chosen?.kind === "declared" && chosen.key === x.key;
                    return (
                      <tr key={x.key} onClick={() => setPick({ kind: "declared", key: x.key })} className={cn("cursor-pointer align-top", on ? "bg-accent shadow-[inset_2px_0_0_var(--color-primary)]" : "hover:bg-muted/40")}>
                        <td className="whitespace-nowrap py-2 pl-5 pr-2"><span className="inline-flex min-w-[76px] items-center gap-1.5 rounded border border-dashed px-1.5 font-mono text-[11px] font-semibold leading-5 text-muted-foreground"><span aria-hidden>✎</span>{x.answer === "yes" ? "YES" : x.answer === "no" ? "NO" : x.answer === "na" ? "N/A" : "—"}</span></td>
                        <td className="px-2 py-2"><button className="text-left font-medium hover:underline" aria-pressed={on} onClick={(e) => { e.stopPropagation(); setPick({ kind: "declared", key: x.key }); }}>{x.title}</button></td>
                        <td className="py-2 pl-2 pr-5 text-muted-foreground">{x.answer ? [x.dated && `dated ${x.dated}`, x.note || `declared ${when(x.ts)}`].filter(Boolean).join(" · ") : "not answered"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              )}
            </table>
          </div>
        </section>

        <aside aria-label="Evidence" className="min-w-0 flex-[1_1_340px] border-l bg-sidebar max-[1000px]:border-l-0 max-[1000px]:border-t">
         <div className="min-[1000px]:sticky min-[1000px]:top-[72px]">
          {chosen?.kind === "check" && (() => {
            const hit = all.find((x) => x.c.id === chosen.id);
            if (!hit) return null;
            const { c, ctl } = hit;
            return (
              <div className="space-y-3.5 p-5">
                <div className="flex flex-wrap items-center gap-2"><Code status={c.status} accepted={!!c.accepted} /><span className="text-xs text-muted-foreground">{ctl.title}</span></div>
                <h2 className="text-base font-semibold leading-snug">{c.title}</h2>
                <p className="text-sm leading-relaxed">{c.detail}</p>
                {c.evidence.length > 0 && (
                  <div className="rounded-lg border bg-background px-3.5 py-3 font-mono text-xs leading-7">
                    <div className="text-muted-foreground">$ evidence {c.id}{d.assessed_at && ` · ${d.assessed_at.slice(0, 16).replace("T", " ")}`}</div>
                    {c.evidence.map((e, i) => <div key={i} className="break-all">{e}</div>)}
                  </div>
                )}
                {c.fix && c.status !== "pass" && <p className="text-sm"><span className="text-muted-foreground">What to do: </span>{c.fix}</p>}
                {c.accepted && (
                  <div className="rounded-md border border-dashed px-3 py-2 text-sm">
                    Accepted {when(c.accepted.ts)}: {c.accepted.reason}
                    <button className="ml-2 text-xs text-primary hover:underline" onClick={() => void withdraw(c)}>Withdraw</button>
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  {c.to && <Button asChild size="sm" variant={c.status === "fail" ? "default" : "outline"}><a href={"#" + c.to}>Open {PAGE[c.to] ?? c.to.slice(1)}</a></Button>}
                  {(c.status === "fail" || c.status === "warn") && !c.accepted && <Button variant="outline" size="sm" onClick={() => startAccept(c)}>Accept with a reason…</Button>}
                </div>
                {(c.status === "fail" || c.status === "warn") && <p className="text-xs text-muted-foreground">An accepted exception keeps its failing mark in the evidence; it only stops counting against its area.</p>}
              </div>
            );
          })()}
          {chosen?.kind === "declared" && (() => {
            const x = d.declared.find((y) => y.key === chosen.key);
            if (!x) return null;
            return (
              <div>
                <div className="px-5 pt-5"><span className="inline-flex items-center gap-1.5 rounded border border-dashed px-1.5 font-mono text-[11px] font-semibold leading-5 text-muted-foreground">✎ DECLARED</span></div>
                <Declared key={x.key + (x.ts ?? "")} d={x} onSave={(a, n, dt) => void declare(x.key, a, n, dt)} />
                <p className="px-5 pb-4 text-xs text-muted-foreground">Your own statement. It is shown as declared in the evidence, never as measured.</p>
              </div>
            );
          })()}
         </div>
        </aside>
      </div>

      <div className="space-y-6 px-6 py-6">

      <div data-print-hide>
        <Section title="History" sub="One line per control area, one square per day.">
          <Card className="rounded-lg"><History data={d} /></Card>
        </Section>
      </div>

      <div className="hidden space-y-8 print:block">
        <Section title="Control areas">
          <div className="space-y-4">{controls.map((ctl) => <ControlCard key={ctl.key} ctl={ctl} onAccept={startAccept} onWithdraw={(c) => void withdraw(c)} />)}</div>
        </Section>
        <Section title="Declared by you" sub="Things a program on the PC cannot measure.">
          <Card data-print-card className="divide-y rounded-lg">{d.declared.map((x) => <Declared key={x.key + (x.ts ?? "")} d={x} onSave={(a, n, dt) => void declare(x.key, a, n, dt)} />)}</Card>
        </Section>
        <Section title="History" sub="One line per control area, one square per day.">
          <Card data-print-card className="rounded-lg"><History data={d} /></Card>
        </Section>
      </div>

      <Section title="Updates and changes made from the console" sub="The record of patches and changes an insurer asks for.">
        <Card data-print-card className="overflow-hidden rounded-lg">
          {d.patch_log.length ? (
            <table className="w-full text-sm">
              <thead className="label-caps border-b bg-muted/40 text-left text-muted-foreground">
                <tr><th className="px-4 py-2 font-medium">When</th><th className="px-4 py-2 font-medium">What</th><th className="px-4 py-2 font-medium">Result</th></tr>
              </thead>
              <tbody className="divide-y">
                {d.patch_log.map((r, i) => (
                  <tr key={i} data-print-row className="align-top">
                    <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{when(r.ts)}</td>
                    <td className="px-4 py-3"><div className="flex flex-wrap items-center gap-2"><Badge variant={r.action === "update" ? "info" : r.action === "firewall" ? "success" : "muted"}>{ACTION[r.action]}</Badge><span className="font-medium">{r.name}</span></div></td>
                    <td className="px-4 py-3"><div className="flex items-start gap-2">{r.ok ? <Check className="mt-0.5 size-4 shrink-0 text-success" aria-label="Succeeded" /> : <X className="mt-0.5 size-4 shrink-0 text-destructive" aria-label="Failed" />}<span className="leading-relaxed">{r.message}</span></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="px-5 py-4 text-sm text-muted-foreground">Nothing has been changed from the console yet.</p>}
        </Card>
      </Section>
      <p className="text-xs text-muted-foreground">{d.footer ?? "Follows the Cyber Essentials control areas. It is not the scheme's own tool and passing here is not a certificate."}</p>
      <p data-print="only" className="hidden text-sm">Measured on the PC by Shadow Filer. {d.footer ?? "Follows the Cyber Essentials control areas; not a certificate."}</p>
      </div>
    </div>}

    <Confirm
      open={!!accepting}
      onOpenChange={(o) => { if (!o && keep.current) { keep.current = false; return; } if (!o) setAccepting(null); }}
      title={`Accept: ${accepting?.title ?? ""}`}
      confirmLabel="Accept"
      onConfirm={accept}
    >
      <label className="block space-y-1.5 text-foreground">
        <span className="text-sm font-medium">Why is this acceptable?</span>
        <Textarea value={reason} onChange={(e) => setReason(e.target.value)} required rows={3} autoFocus />
      </label>
      <p>It stays listed as failing, marked as accepted, and no longer counts against the control area.</p>
    </Confirm>
  </div>;
}
