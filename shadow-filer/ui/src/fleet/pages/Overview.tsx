import { Flame, MonitorSmartphone, WifiOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Card, EmptyState, ListSkeleton, LoadError, Notice, PageHeader, Stat } from "@/shadow/ui";
import { api, type AreaStatus, type Fleet } from "../api";
import { DeviceLink, HistoryGrid, Mark, ReferenceLine, Section, SQUARE } from "../parts";

const worst = (a: Record<AreaStatus, number>): AreaStatus => (a.fail ? "fail" : a.warn ? "warn" : a.unknown ? "unknown" : "pass");

function Areas({ d }: { d: Fleet }) {
  const n = Math.max(d.judged, 1);
  return (
    <Card className="divide-y rounded-lg">
      {d.areas.map((a) => (
        <div key={a.key} className="grid items-center gap-x-4 gap-y-2 px-5 py-3.5 min-[900px]:grid-cols-[minmax(0,1fr)_220px_170px]">
          <div className="flex min-w-0 items-start gap-3">
            <Mark status={worst(a)} />
            <div className="min-w-0"><div className="font-medium">{a.title}</div><p className="text-sm text-muted-foreground">{a.about}</p></div>
          </div>
          <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted" role="img"
            aria-label={`${a.pass} passing, ${a.fail} failing, ${a.warn} worth a look, ${a.unknown} could not be checked`}>
            {(["pass", "warn", "fail", "unknown"] as const).map((s) => a[s] > 0 && <div key={s} className={SQUARE[s]} style={{ width: `${(a[s] / n) * 100}%` }} />)}
          </div>
          <div className="text-sm tabular text-muted-foreground">
            <span className="font-medium text-foreground">{a.pass} of {d.judged}</span> pass
            {a.fail > 0 && <> · <span className="text-destructive">{a.fail} failing</span></>}
            {a.warn > 0 && <> · {a.warn} to look at</>}
          </div>
        </div>
      ))}
    </Card>
  );
}

export function OverviewPage() {
  const q = usePoll<Fleet>(api.fleet, 60_000);
  const d = q.data;
  if (!d) return <><PageHeader title="Overview" />{q.error ? <LoadError error={q.error} onRetry={q.reload} /> : <ListSkeleton rows={4} />}</>;
  const t = d.totals;
  const days = d.history.map((h) => h.day);
  return (
    <>
      <PageHeader
        title="Overview"
        sub="Every enrolled PC against the five Cyber Essentials control areas, judged on the server from what each PC reports."
        actions={<span className="text-xs text-muted-foreground">Updated {when(d.generated_at)}</span>}
      />
      {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
      {d.devices === 0 ? (
        <EmptyState icon={<MonitorSmartphone />} title="No device has enrolled yet">
          Create an enrolment token on the server (<span className="path">docker compose run --rm manage token "{d.organisation}"</span>), then on each PC run{" "}
          <span className="path">shadow_agent.py fleet enrol &lt;server&gt; &lt;token&gt;</span>.
        </EmptyState>
      ) : (
        <div className="space-y-8">
          <Card className="rounded-lg p-5">
            <div className="flex flex-wrap items-center justify-between gap-6">
              <div>
                <div className="text-xl font-semibold tabular">{d.all_passing} of {d.devices} device{d.devices === 1 ? "" : "s"} pass{d.all_passing === 1 ? "es" : ""} all five control areas</div>
                {d.judged < d.devices && <div className="text-sm text-muted-foreground">{d.devices - d.judged} not judged yet (no report so far, or the server has not got to it).</div>}
              </div>
              <div className="grid grid-cols-4 gap-8">
                <Stat label="Flaws used in attacks" value={<span className={t.exploited ? "text-destructive" : undefined}>{t.exploited}</span>} />
                <Stat label="Critical flaws" value={<span className={t.critical ? "text-warning" : undefined}>{t.critical}</span>} />
                <Stat label="Newer versions waiting" value={t.updates} />
                <Stat label="Not reporting" value={<span className={d.silent.length ? "text-warning" : undefined}>{d.silent.length}</span>} />
              </div>
            </div>
            <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">This follows the Cyber Essentials control areas. It is not the scheme's own tool and passing here is not a certificate.</p>
          </Card>

          {(d.exploited.length > 0 || d.silent.length > 0 || d.unsupported.length > 0) && (
            <Section title="Needs attention">
              <div className="space-y-2">
                {d.exploited.map((e, i) => (
                  <Notice key={"e" + i} tone="danger" icon={<Flame />}>
                    <DeviceLink id={e.device_id} name={e.device} tab="security" />: {e.program}{e.version && !e.program.includes(e.version) ? ` ${e.version}` : ""} has a flaw that is being used in real attacks (<span className="path">{e.cve}</span>).
                    {e.fix ? <> Update it to {e.fix}.</> : " Update it."}
                  </Notice>
                ))}
                {d.unsupported.map((u, i) => (
                  <Notice key={"u" + i} tone="warn">
                    <DeviceLink id={u.device_id} name={u.device} tab="programs" />:{" "}
                    {u.windows && <>its Windows version no longer gets security updates{u.windows_until ? ` (since ${u.windows_until})` : ""}. </>}
                    {u.programs.length > 0 && <>{u.programs.join(", ")} {u.programs.length === 1 ? "is a release line that no longer gets" : "are release lines that no longer get"} security updates.</>}
                  </Notice>
                ))}
                {d.silent.map((s) => (
                  <Notice key={s.id} tone="warn" icon={<WifiOff />}>
                    <DeviceLink id={s.id} name={s.name} /> has not reported for more than {d.silent_hours} hours{s.last_seen ? ` (last ${when(s.last_seen)})` : " (never since it enrolled)"}. What is shown for it may be out of date.
                  </Notice>
                ))}
              </div>
            </Section>
          )}

          <Section title="Control areas" sub="How many devices pass each one.">
            <Areas d={d} />
          </Section>

          <Section title="Failing checks" sub="Most widespread first. Accepted exceptions are not counted.">
            {d.failing.length === 0 ? <Card className="rounded-lg px-5 py-4 text-sm text-muted-foreground">No check is failing on any judged device.</Card> : (
              <Card className="divide-y rounded-lg">
                {d.failing.map((f) => (
                  <div key={f.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-5 py-3">
                    <div className="min-w-0 flex-1">
                      <span className="font-medium">{f.title}</span>
                      <Badge variant="muted" className="ml-2">{d.areas.find((a) => a.key === f.control)?.title ?? f.control}</Badge>
                    </div>
                    <div className="text-sm">
                      <span className="mr-2 tabular text-muted-foreground">{f.devices.length} of {d.judged}</span>
                      {f.devices.slice(0, 6).map((x, i) => <span key={x.id}>{i > 0 && ", "}<DeviceLink id={x.id} name={x.name} /></span>)}
                      {f.devices.length > 6 && <span className="text-muted-foreground"> and {f.devices.length - 6} more</span>}
                    </div>
                  </div>
                ))}
              </Card>
            )}
          </Section>

          <Section title="Last 90 days" sub="One square per day: green when every device passed the control area that day, red when none did.">
            <Card className="rounded-lg">
              <HistoryGrid days={days} rows={d.areas} cell={(key, i) => {
                const h = d.history[i]!, n = h.areas[key] ?? 0;
                return { tone: n === h.devices ? SQUARE.pass : n === 0 ? SQUARE.fail : SQUARE.warn, tip: `${n} of ${h.devices} device${h.devices === 1 ? "" : "s"} passed` };
              }} />
              {days.length >= 2 && (
                <div className="flex flex-wrap gap-4 px-5 pb-4 text-xs text-muted-foreground">
                  {([["pass", "Every device passed"], ["warn", "Some passed"], ["fail", "None passed"]] as const).map(([s, l]) => (
                    <span key={s} className="flex items-center gap-1.5"><span className={cn("size-2.5 rounded-[2px]", SQUARE[s])} />{l}</span>
                  ))}
                </div>
              )}
            </Card>
          </Section>

          <ReferenceLine r={d.reference} />
        </div>
      )}
    </>
  );
}
