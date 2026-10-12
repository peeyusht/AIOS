import { useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Check, Copy, HelpCircle, Info, Printer, RefreshCw, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CheckStatus, ComplianceCheck, ComplianceControl, ComplianceResponse, DeclaredAnswer } from "@/lib/types";
import { act, Card, Confirm, ListSkeleton, LoadError, Notice, PageHeader, Segmented, Spin, Stat, Tip, useBusy } from "../ui";

const ORDER: Record<CheckStatus, number> = { fail: 0, warn: 1, unknown: 2, info: 3, pass: 4 };
const LABEL: Record<CheckStatus, string> = { pass: "Passed", fail: "Failing", warn: "Worth a look", unknown: "Could not be checked", info: "Note" };
const PAGE: Record<string, string> = { "/network": "Network", "/security": "Security", "/library": "Library", "/watch": "Watch", "/settings": "Settings" };
const SQUARE = { pass: "bg-success", fail: "bg-destructive", warn: "bg-warning", unknown: "bg-muted-foreground/30" };

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

function Declared({ d, onSave }: { d: ComplianceResponse["declared"][number]; onSave: (a: DeclaredAnswer, note: string) => void }) {
  const [note, setNote] = useState(d.note);
  const opts = [{ value: "yes", label: "Yes" }, { value: "no", label: "No" }, { value: "na", label: "Does not apply" }] as const;
  const pick = (v: "yes" | "no" | "na") => onSave(d.answer === v ? null : v, note);
  return (
    <div data-print-row className="grid gap-3 px-5 py-4 min-[1000px]:grid-cols-[1fr_auto]">
      <div className="min-w-0">
        <div className="font-medium">{d.title}</div>
        <p className="text-sm text-muted-foreground">{d.about}</p>
        <Input value={note} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== d.note && onSave(d.answer, note)} placeholder="Note (optional)" className="mt-2 h-8 max-w-md text-sm" aria-label={`Note for: ${d.title}`} />
        {d.note && <p className="hidden text-sm print:block">Note: {d.note}</p>}
      </div>
      <div className="flex flex-col items-start gap-1.5 min-[1000px]:items-end">
        <div data-print-hide className="flex items-center gap-2">
          <Segmented label={d.title} value={(d.answer ?? "") as "yes"} onChange={(v) => pick(v)} options={opts as unknown as { value: "yes"; label: string }[]} />
          {d.answer && <button className="text-xs text-muted-foreground hover:text-foreground hover:underline" onClick={() => onSave(null, note)}>Clear</button>}
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

export function CompliancePage() {
  const q = usePoll<ComplianceResponse>(() => api.compliance(), 300_000);
  const { busy, run } = useBusy();
  const [accepting, setAccepting] = useState<ComplianceCheck | null>(null);
  const [reason, setReason] = useState("");
  const keep = useRef(false);
  const d = q.data;

  const refresh = () => run("refresh", async () => { try { q.setData(await api.compliance(true)); } catch (e) { toast.error((e as Error).message); } });
  const copy = async () => { try { await navigator.clipboard.writeText(d?.text ?? ""); toast.success("Copied"); } catch { toast.error("Could not copy to the clipboard."); } };
  const accept = async () => {
    if (!accepting) return;
    if (!reason.trim()) { keep.current = true; toast.error("Write why this is acceptable."); return; }
    if (await act(() => api.complianceAccept(accepting.id, reason.trim()))) q.reload();
  };
  const withdraw = async (c: ComplianceCheck) => { if (await act(() => api.complianceAccept(c.id, ""))) q.reload(); };
  const declare = async (key: string, a: DeclaredAnswer, note: string) => { if (await act(() => api.complianceDeclare(key, a, note))) q.reload(); };

  const dev = d?.device ?? {};
  const deviceLine = [dev.name, [dev.manufacturer, dev.model].filter(Boolean).join(" "), dev.serial && `serial ${dev.serial}`, dev.windows && `${dev.windows}${dev.build ? `, build ${dev.build}` : ""}`].filter(Boolean).join(" · ");
  const s = d?.summary ?? {};
  const assessedDate = d?.assessed_at ? new Date(d.assessed_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }) : "";

  return <>
    {d?.assessed_at && <p data-print="only" className="mb-4 hidden text-lg font-semibold">Security posture of {dev.name ?? "this PC"}, assessed {assessedDate}</p>}
    <PageHeader
      title="Compliance"
      sub={<><div>Whether this PC meets what insurers and Cyber Essentials ask for. Measured on this PC; nothing is sent anywhere.</div>{deviceLine && <div className="mt-1 text-xs">{deviceLine}</div>}</>}
      actions={<>
        {d?.assessed_at && <span className="text-xs text-muted-foreground">Assessed {when(d.assessed_at)}</span>}
        <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={busy === "refresh"}>{busy === "refresh" ? <Spin /> : <RefreshCw />}Refresh</Button>
        <Button variant="outline" size="sm" onClick={() => void copy()} disabled={!d?.text}><Copy />Copy as text</Button>
        <Button variant="outline" size="sm" onClick={() => window.print()} disabled={!d}><Printer />Print</Button>
      </>}
    />
    {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
    {d && !d.assessed_at && <div className="mb-4"><LoadError error={new Error(d.error ?? "The assessment has not run yet.")} onRetry={() => void refresh()} /></div>}
    {!d ? (!q.error && <ListSkeleton rows={5} />) : d.assessed_at && <div className="space-y-8">
      <Card data-print-card className="rounded-lg p-5">
        <div className="flex flex-wrap items-center justify-between gap-6">
          <div className="text-xl font-semibold tabular">{s.controls_passing ?? "—"} of {s.controls ?? d.controls.length} control areas pass</div>
          <div className="grid grid-cols-4 gap-8">
            <Stat label="Failing checks" value={<span className={s.fail ? "text-destructive" : undefined}>{s.fail ?? "—"}</span>} />
            <Stat label="Worth a look" value={<span className={s.warn ? "text-warning" : undefined}>{s.warn ?? "—"}</span>} />
            <Stat label="Could not be checked" value={s.unknown ?? "—"} />
            <Stat label="Accepted with a reason" value={s.accepted ?? "—"} />
          </div>
        </div>
        <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">This follows the Cyber Essentials control areas. It is not the scheme's own tool and passing here is not a certificate.</p>
      </Card>

      <Section title="Control areas">
        <div className="space-y-4">{d.controls.map((ctl) => <ControlCard key={ctl.key} ctl={ctl} onAccept={(c) => { setReason(""); setAccepting(c); }} onWithdraw={(c) => void withdraw(c)} />)}</div>
      </Section>

      <Section title="Declared by you" sub="Things a program on the PC cannot measure.">
        <Notice>These are your own statements. They are always shown as declared, never as measured.</Notice>
        <Card data-print-card className="divide-y rounded-lg">{d.declared.map((x) => <Declared key={x.key + (x.ts ?? "")} d={x} onSave={(a, n) => void declare(x.key, a, n)} />)}</Card>
      </Section>

      <Section title="History" sub="One line per control area, one square per day.">
        <Card data-print-card className="rounded-lg"><History data={d} /></Card>
      </Section>

      <Section title="Updates and changes made from the console" sub="The record of patches and changes an insurer asks for.">
        <Card data-print-card className="overflow-hidden rounded-lg">
          {d.patch_log.length ? (
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
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
      <p data-print="only" className="hidden text-sm">Measured on the PC by Shadow Filer. Follows the Cyber Essentials control areas; not a certificate.</p>
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
  </>;
}
