import { MonitorSmartphone } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import { Card, EmptyState, ListSkeleton, LoadError, PageHeader, Tip } from "@/shadow/ui";
import { api, type Devices } from "../api";
import { DeviceLink, LABEL, Mark, silentFor } from "../parts";

const AREAS = [["firewalls", "Firewalls"], ["configuration", "Secure configuration"], ["updates", "Security update management"], ["access", "User access control"], ["malware", "Malware protection"]] as const;

export function DevicesPage() {
  const q = usePoll<Devices>(api.devices, 60_000);
  const d = q.data;
  return (
    <>
      <PageHeader title="Devices" sub="Every PC enrolled in this organisation. A PC reports every 15 minutes while its agent runs." />
      {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
      {!d ? !q.error && <ListSkeleton rows={3} h="h-14" /> : d.devices.length === 0 ? (
        <EmptyState icon={<MonitorSmartphone />} title="No device has enrolled yet">On a PC: <span className="path">shadow_agent.py fleet enrol &lt;server&gt; &lt;token&gt;</span></EmptyState>
      ) : (
        <Card className="overflow-x-auto rounded-lg">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Device</th><th className="px-4 py-2 font-medium">Last report</th>
                <th className="px-4 py-2 font-medium">Control areas</th><th className="px-4 py-2 font-medium">Failing checks</th>
                <th className="px-4 py-2 font-medium">Known flaws</th><th className="px-4 py-2 font-medium">Newer versions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {d.devices.map((x) => {
                const j = x.judgement, silent = x.silent_seconds == null || x.silent_seconds > 86400;
                return (
                  <tr key={x.id} className="align-top">
                    <td className="px-4 py-3">
                      <DeviceLink id={x.id} name={x.name} />
                      <div className="text-xs text-muted-foreground">{[x.summary.windows, x.summary.model?.trim()].filter(Boolean).join(" · ") || "nothing reported yet"}</div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {when(x.last_seen)}
                      {silent && <div><Badge variant="warning">{silentFor(x.silent_seconds)}</Badge></div>}
                    </td>
                    <td className="px-4 py-3">
                      {j ? (
                        <div className="flex items-center gap-1">
                          {AREAS.map(([k, title]) => { const s = j.compliance.areas[k] ?? "unknown"; return <Tip key={k} tip={`${title}: ${LABEL[s].toLowerCase()}`}><span tabIndex={0}><Mark status={s} small /></span></Tip>; })}
                          <span className="ml-2 tabular text-muted-foreground">{j.compliance.controls_passing} of {j.compliance.controls}</span>
                        </div>
                      ) : <span className="text-muted-foreground">not judged yet</span>}
                    </td>
                    <td className="px-4 py-3 tabular">
                      {j ? <><span className={j.compliance.fail ? "font-medium text-destructive" : undefined}>{j.compliance.fail}</span>
                        {j.compliance.accepted > 0 && <span className="text-muted-foreground"> · {j.compliance.accepted} accepted</span>}</> : "—"}
                    </td>
                    <td className="px-4 py-3 tabular">
                      {j?.security ? <>
                        {j.security.apps_affected} program{j.security.apps_affected === 1 ? "" : "s"}
                        {j.security.kev > 0 && <div><Badge variant="danger">{j.security.kev} used in attacks</Badge></div>}
                      </> : <span className="text-muted-foreground">{j ? "not compared yet" : "—"}</span>}
                    </td>
                    <td className="px-4 py-3 tabular">{x.summary.updates ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </>
  );
}
