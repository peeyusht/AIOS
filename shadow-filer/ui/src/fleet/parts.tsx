/* Pieces the fleet pages share: the pass/fail mark, a control area with its checks, the history squares. */
import { useState, type ReactNode } from "react";
import { AlertTriangle, Check as CheckIcon, HelpCircle, Info, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { when } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Card, Tip } from "@/shadow/ui";
import type { AreaStatus, Check, CheckStatus, Control, Reference } from "./api";

export const LABEL: Record<CheckStatus, string> = { pass: "Passed", fail: "Failing", warn: "Worth a look", unknown: "Could not be checked", info: "Note" };
export const ORDER: Record<CheckStatus, number> = { fail: 0, warn: 1, unknown: 2, info: 3, pass: 4 };
export const SQUARE: Record<AreaStatus, string> = { pass: "bg-success", fail: "bg-destructive", warn: "bg-warning", unknown: "bg-muted-foreground/30" };
const TAB: Record<string, string> = { security: "Security", network: "Network", programs: "Programs" };

export function Mark({ status, quiet, small }: { status: CheckStatus; quiet?: boolean; small?: boolean }) {
  const map = {
    pass: [CheckIcon, "text-success bg-success-soft"], fail: [X, "text-destructive bg-danger-soft"], warn: [AlertTriangle, "text-warning bg-warning-soft"],
    unknown: [HelpCircle, "text-muted-foreground bg-muted"], info: [Info, "text-muted-foreground bg-muted"],
  } as const;
  const [Icon, tone] = map[status];
  return (
    <span role="img" aria-label={LABEL[status]} title={LABEL[status]}
      className={cn("inline-flex shrink-0 items-center justify-center rounded-full", small ? "size-5" : "size-6", tone, quiet && "opacity-60")}>
      <Icon className={small ? "size-3" : "size-3.5"} />
    </span>
  );
}

export function Section({ title, sub, children, actions }: { title: string; sub?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="text-sm font-semibold">{title}</h2>{sub && <p className="text-sm text-muted-foreground">{sub}</p>}</div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Tile({ label, n, tone = "text-foreground", sub }: { label: string; n: ReactNode; tone?: string; sub?: ReactNode }) {
  return (
    <div className="rounded-xl border bg-card px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-2xl font-semibold tabular", tone)}>{n}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

export const DeviceLink = ({ id, name, tab }: { id: string; name: string; tab?: string }) => (
  <a href={`#/devices/${id}${tab ? `/${tab}` : ""}`} className="font-medium text-primary underline-offset-4 hover:underline">{name}</a>
);

/** "the lists" line under a page: how fresh the server's copy of the public lists is. */
export function ReferenceLine({ r }: { r: Reference }) {
  if (!r.complete) {
    return (
      <p className="text-sm text-muted-foreground">
        {r.syncing ? "The server is downloading the public CVE list for the first time (about 300 MB; several minutes). " : "The server has no complete copy of the CVE list yet. "}
        Until then known flaws and end of support are not judged; the settings checks are.
        {r.error && <span className="block text-warning">Last download: {r.error}</span>}
      </p>
    );
  }
  return (
    <p className="text-sm text-muted-foreground">
      Lists on the server: {r.cves.toLocaleString()} CVEs, {r.kev.toLocaleString()} known exploited, updated {when(r.cve_synced_at)}
      {r.eol_products > 0 && <> · end-of-life list of {r.eol_products} products, updated {when(r.eol_synced_at)}</>} · from nvd.nist.gov, cisa.gov and endoflife.date
      {r.error && <span className="block text-warning">Last download had a problem: {r.error}</span>}
    </p>
  );
}

function CheckRow({ c, deviceId, onAccept, onWithdraw }: { c: Check; deviceId: string; onAccept?: () => void; onWithdraw?: () => void }) {
  const [all, setAll] = useState(false);
  const shown = all ? c.evidence : c.evidence.slice(0, 4);
  const hidden = c.evidence.slice(4);
  const link = c.to && TAB[c.to] ? <a href={`#/devices/${deviceId}/${c.to}`} data-print-hide className="ml-1 text-xs text-primary hover:underline">Open {TAB[c.to]}</a> : null;
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
        {c.fix && c.status !== "pass" && <p className="text-sm"><span className="text-muted-foreground">What to do: </span>{c.fix}{link}</p>}
        {!(c.fix && c.status !== "pass") && link && <div>{link}</div>}
        {c.accepted && (
          <div className="rounded-md border border-dashed px-3 py-2 text-sm">
            Accepted {when(c.accepted.ts)}: {c.accepted.reason}
            {onWithdraw && <button className="ml-2 text-xs text-primary hover:underline" onClick={onWithdraw}>Withdraw</button>}
          </div>
        )}
        {(c.status === "fail" || c.status === "warn") && !c.accepted && onAccept && (
          <Button variant="ghost" size="sm" className="-ml-2 h-7 text-muted-foreground" onClick={onAccept}>Accept with a reason…</Button>
        )}
      </div>
    </div>
  );
}

export function ControlCard({ ctl, deviceId, onAccept, onWithdraw }: { ctl: Control; deviceId: string; onAccept: (c: Check) => void; onWithdraw: (c: Check) => void }) {
  const sorted = [...ctl.checks].sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  const rest = sorted.filter((c) => c.status !== "pass");
  const passed = sorted.filter((c) => c.status === "pass");
  const [open, setOpen] = useState(rest.length === 0);
  const counts = [
    ctl.counts.pass && `${ctl.counts.pass} passed`, ctl.counts.fail && `${ctl.counts.fail} failing`, ctl.counts.warn && `${ctl.counts.warn} worth a look`,
    ctl.counts.unknown && `${ctl.counts.unknown} could not be checked`, ctl.accepted && `${ctl.accepted} accepted`,
  ].filter(Boolean).join(" · ");
  const row = (c: Check) => <CheckRow key={c.id} c={c} deviceId={deviceId} onAccept={() => onAccept(c)} onWithdraw={() => onWithdraw(c)} />;
  return (
    <Card data-print-card className="overflow-hidden rounded-lg">
      <div data-print-row className="flex items-start gap-3 border-b px-5 py-4">
        <Mark status={ctl.status} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h3 className="font-semibold">{ctl.title} <span className="ml-1 text-sm font-normal text-muted-foreground">{LABEL[ctl.status].toLowerCase()}</span></h3>
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
                <CheckIcon className="size-4 text-success" />{passed.length} passed · show
              </button>
              <div data-print-collapsed className="hidden divide-y">{passed.map(row)}</div>
            </>)}
        {open && rest.length > 0 && passed.length > 0 && <button data-print-hide className="w-full px-5 py-2 text-left text-xs text-muted-foreground hover:bg-muted/40" onClick={() => setOpen(false)}>Hide passed</button>}
      </div>
    </Card>
  );
}

/** One row of squares per control area, one square per day. `cell` says how a day looked for an area. */
export function HistoryGrid({ days, rows, cell }: { days: string[]; rows: { key: string; title: string }[]; cell: (key: string, i: number) => { tone: string; tip: string } }) {
  if (days.length < 2) return <p className="px-5 py-4 text-sm text-muted-foreground">History builds up from the first day a device was judged: one line is kept per device per day.</p>;
  const months = days.map((d, i) => {
    const m = new Date(d + "T12:00:00").toLocaleDateString(undefined, { month: "short" });
    return i === 0 || d.slice(5, 7) !== days[i - 1]!.slice(5, 7) ? m : "";
  });
  return (
    <div className="overflow-x-auto px-5 py-4">
      <div className="inline-grid items-center gap-x-3 gap-y-1.5" style={{ gridTemplateColumns: "max-content max-content" }}>
        <span />
        <div className="flex gap-[3px] text-[11px] text-muted-foreground">{months.map((m, i) => <span key={i} className="w-2.5 overflow-visible whitespace-nowrap">{m}</span>)}</div>
        {rows.map((r) => (
          <div key={r.key} className="contents">
            <span className="text-xs text-muted-foreground">{r.title}</span>
            <div className="flex gap-[3px]">
              {days.map((d, i) => {
                const c = cell(r.key, i);
                return <Tip key={d} tip={`${d}: ${c.tip}`}><span tabIndex={0} aria-label={`${r.title} ${d}: ${c.tip}`} className={cn("block size-2.5 rounded-[2px]", c.tone)} /></Tip>;
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export const silentFor = (seconds: number | null) =>
  seconds == null ? "never reported" : seconds < 5400 ? "reporting" : seconds < 172800 ? `silent for ${Math.round(seconds / 3600)} h` : `silent for ${Math.round(seconds / 86400)} days`;
