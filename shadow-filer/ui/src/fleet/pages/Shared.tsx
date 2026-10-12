/* What a share link opens: one organisation's evidence, read-only, for someone without an account. */
import { useEffect, useState } from "react";
import { Copy, Printer } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { when } from "@/lib/format";
import { Card, ListSkeleton, Notice, Stat } from "@/shadow/ui";
import { api, type Shared } from "../api";
import { ControlCard, Mark, Section } from "../parts";
import { Frame, Logo } from "./SignIn";

const ANSWER = { yes: "Yes", no: "No", na: "Does not apply" } as const;

export function SharedPage({ token }: { token: string }) {
  const [d, setD] = useState<Shared | null>(null);
  const [gone, setGone] = useState<string | null>(null);
  useEffect(() => { api.shared(token).then(setD).catch((e) => setGone((e as Error).message)); }, [token]);
  const copy = async () => { try { await navigator.clipboard.writeText(d?.text ?? ""); toast.success("Copied"); } catch { toast.error("Could not copy."); } };

  if (gone) return <Frame title="This link does not open anything"><Notice tone="warn">{gone}</Notice><p className="mt-3 text-sm text-muted-foreground">Ask the organisation that sent it for a new one.</p></Frame>;
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex h-12 items-center gap-2.5 border-b px-6">
        <Logo /><span className="text-sm font-semibold">Shadow Filer</span>
        <span className="text-sm text-muted-foreground">· shared evidence, read-only</span>
      </header>
      <main className="mx-auto w-full max-w-5xl space-y-8 px-6 py-8">
        {!d ? <ListSkeleton rows={4} /> : (
          <>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <h1 className="text-2xl font-semibold tracking-tight">Security posture of {d.organisation}</h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  Shared as “{d.label}”. This link stops working on {new Date(d.expires_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" })}. Produced {when(d.generated_at)}.
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => void copy()}><Copy />Copy as text</Button>
                <Button variant="outline" size="sm" onClick={() => window.print()}><Printer />Print</Button>
              </div>
            </div>

            <Card data-print-card className="rounded-lg p-5">
              <div className="flex flex-wrap items-center justify-between gap-6">
                <div className="text-xl font-semibold tabular">{d.all_passing} of {d.devices} device{d.devices === 1 ? "" : "s"} pass{d.all_passing === 1 ? "es" : ""} all five control areas</div>
                <div className="grid grid-cols-5 gap-6">
                  {d.areas.map((a) => <Stat key={a.key} label={a.title} value={<span className="tabular">{a.pass}<span className="text-sm font-normal text-muted-foreground"> of {d.judged}</span></span>} />)}
                </div>
              </div>
              <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">
                Each PC is measured by an agent on the PC and judged on the organisation's server against the five Cyber Essentials control areas. A PC reports counts and settings, never account names, file names or addresses.
                This is not the scheme's own tool and passing here is not a certificate.
              </p>
            </Card>

            {d.device_list.map((dev) => (
              <Section key={dev.id} title={dev.name}
                sub={[dev.windows, dev.model, dev.last_seen ? `last report ${when(dev.last_seen)}` : "never reported", dev.security ? `${dev.security.apps_affected} program${dev.security.apps_affected === 1 ? "" : "s"} with known flaws, ${dev.security.kev} used in real attacks` : null].filter(Boolean).join(" · ")}>
                {dev.compliance
                  ? <div className="space-y-4">{dev.compliance.controls.map((ctl) => <ControlCard key={ctl.key} ctl={ctl} deviceId="" />)}</div>
                  : <Card className="rounded-lg px-5 py-4 text-sm text-muted-foreground">Enrolled, not judged yet.</Card>}
              </Section>
            ))}

            <Section title="Declared by the organisation" sub="Things no program on a PC can measure. These are the organisation's own statements, not measurements.">
              <Card data-print-card className="divide-y rounded-lg">
                {d.declared.map((q) => (
                  <div key={q.key} data-print-row className="flex flex-wrap items-start gap-3 px-5 py-3">
                    <Mark status={q.answer === "yes" ? "pass" : q.answer === "no" ? "fail" : "unknown"} quiet />
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">{q.title}</div>
                      <div className="text-sm text-muted-foreground">Declared: {q.answer ? ANSWER[q.answer] : "not answered"}{q.note ? ` (${q.note})` : ""}{q.ts ? ` · ${when(q.ts)}` : ""}</div>
                    </div>
                  </div>
                ))}
              </Card>
            </Section>
          </>
        )}
      </main>
    </div>
  );
}
