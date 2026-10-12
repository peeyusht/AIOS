import { useState } from "react";
import { Copy, Download } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import { Card, ListSkeleton, LoadError, Notice, PageHeader, Segmented } from "@/shadow/ui";
import { api, type Answer, type AuditEntry, type Declared, type Fleet } from "../api";
import { Section } from "../parts";
import { useCan } from "../session";

const OPTS = [{ value: "yes", label: "Yes" }, { value: "no", label: "No" }, { value: "na", label: "Does not apply" }] as const;

function DeclaredRow({ d, onSave, readOnly }: { d: Declared; onSave: (a: Answer, note: string) => void; readOnly: boolean }) {
  const [note, setNote] = useState(d.note);
  if (readOnly) {
    return (
      <div className="px-5 py-4">
        <div className="font-medium">{d.title}</div>
        <p className="text-sm text-muted-foreground">{d.about}</p>
        <p className="mt-1 text-sm">Declared: <span className="font-medium">{d.answer ? OPTS.find((o) => o.value === d.answer)?.label : "not answered"}</span>{d.note && ` (${d.note})`}{d.ts && <span className="text-muted-foreground"> · {when(d.ts)}</span>}</p>
      </div>
    );
  }
  return (
    <div className="grid gap-3 px-5 py-4 min-[1000px]:grid-cols-[1fr_auto]">
      <div className="min-w-0">
        <div className="font-medium">{d.title}</div>
        <p className="text-sm text-muted-foreground">{d.about}</p>
        <Input value={note} onChange={(e) => setNote(e.target.value)} onBlur={() => note !== d.note && d.answer && onSave(d.answer, note)}
          placeholder={d.answer ? "Note (optional)" : "Answer first, then add a note"} disabled={!d.answer} className="mt-2 h-8 max-w-md text-sm" aria-label={`Note for: ${d.title}`} />
      </div>
      <div className="flex flex-col items-start gap-1.5 min-[1000px]:items-end">
        <div className="flex items-center gap-2">
          <Segmented label={d.title} value={(d.answer ?? "") as "yes"} onChange={(v) => onSave(d.answer === v ? null : v, note)} options={OPTS as unknown as { value: "yes"; label: string }[]} />
          {d.answer && <button className="text-xs text-muted-foreground hover:text-foreground hover:underline" onClick={() => onSave(null, "")}>Clear</button>}
        </div>
        <span className="text-xs text-muted-foreground">{d.ts ? `answered ${when(d.ts)}` : "not answered"}</span>
      </div>
    </div>
  );
}

const ACTION: Record<string, string> = {
  "device.enrolled": "A PC enrolled", "device.removed": "A device was removed", "check.accepted": "A failing check was accepted",
  "check.acceptance_withdrawn": "An acceptance was withdrawn", "declaration.changed": "A declaration was changed",
  "signin": "Signed in", "signin.locked": "Locked after wrong tries", "mfa.set_up": "Set up a second factor", "mfa.recovery_code_used": "Used a recovery code",
  "password.set": "Set a password", "password.changed": "Changed their password", "user.added": "A person was added", "user.role": "A role was changed",
  "user.disable": "A person was switched off", "user.enable": "A person was switched on", "user.reset_password": "A new set-password link was made",
  "user.reset_second_factor": "A second factor was reset", "share_link.created": "A share link was made", "share_link.withdrawn": "A share link was withdrawn",
  "enrolment_token.created": "An enrolment token was made",
};
const about = (e: AuditEntry) => {
  const d = e.detail as Record<string, string | null>;
  if (e.action === "declaration.changed") return `${d.key}: ${d.answer ?? "cleared"}${d.note ? ` (${d.note})` : ""}`;
  return [d.name, d.email, d.role, d.label, d.check, d.reason, d.left != null ? `${d.left} left` : null].filter(Boolean).join(" · ");
};

export function EvidencePage() {
  const q = usePoll<Fleet>(api.fleet, null);
  const log = usePoll(api.audit, null);
  const [busy, setBusy] = useState(false);
  const canEdit = useCan("admin");
  const d = q.data;

  const declare = async (key: string, a: Answer, note: string) => {
    try { await api.declare(key, a, note); await q.reload(); void log.reload(); } catch (e) { toast.error((e as Error).message); }
  };
  const report = async (how: "copy" | "save") => {
    setBusy(true);
    try {
      const r = await api.report();
      if (how === "copy") { await navigator.clipboard.writeText(r.text); toast.success("Copied"); return; }
      const url = URL.createObjectURL(new Blob([r.text], { type: "text/plain" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: `security-posture-${r.generated_at.slice(0, 10)}.txt` });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast.error((e as Error).message || "That did not work."); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader
        title="Evidence"
        sub="What an insurer's questionnaire or a Cyber Essentials assessor asks for: the report for every PC, what the organisation declares, and the record of who accepted what."
        actions={<>
          <Button variant="outline" size="sm" onClick={() => void report("copy")} disabled={busy || !d}><Copy />Copy the report</Button>
          <Button variant="outline" size="sm" onClick={() => void report("save")} disabled={busy || !d}><Download />Save as text</Button>
        </>}
      />
      {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
      {!d ? !q.error && <ListSkeleton rows={4} /> : (
        <div className="space-y-8">
          <Notice>
            The report lists every device with each check, its evidence and any accepted exception, then the declarations below. {d.judged} of {d.devices} device{d.devices === 1 ? " has" : "s have"} been judged.
            It follows the Cyber Essentials control areas and is not a certificate. To print one device, open it and use Print.
          </Notice>

          <Section title="Declared by the organisation" sub="Things no program on a PC can measure. They apply to the whole organisation.">
            <Notice>These are your own statements. They are always shown as declared, never as measured.</Notice>
            <Card className="divide-y rounded-lg">{d.declared.map((x) => <DeclaredRow key={x.key + (x.ts ?? "")} d={x} readOnly={!canEdit} onSave={(a, n) => void declare(x.key, a, n)} />)}</Card>
          </Section>

          <Section title="Record" sub="Sign-ins, enrolments, accepted exceptions, changed declarations and changes to who has access, each under the name of who did it. Entries cannot be edited or removed.">
            <Card className="overflow-x-auto rounded-lg">
              {log.error ? <div className="p-4"><LoadError error={log.error} onRetry={log.reload} /></div> : !log.data ? <div className="p-4"><ListSkeleton rows={2} h="h-8" /></div> : (
                <table className="w-full text-sm">
                  <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground"><tr><th className="px-4 py-2 font-medium">When</th><th className="px-4 py-2 font-medium">What</th><th className="px-4 py-2 font-medium">Details</th><th className="px-4 py-2 font-medium">By</th></tr></thead>
                  <tbody className="divide-y">
                    {log.data.entries.map((e, i) => (
                      <tr key={i} className="align-top">
                        <td className="whitespace-nowrap px-4 py-2.5 text-muted-foreground">{when(e.at)}</td>
                        <td className="px-4 py-2.5 font-medium">{ACTION[e.action] ?? e.action}</td>
                        <td className="px-4 py-2.5">{about(e)}</td>
                        <td className="path px-4 py-2.5 text-muted-foreground">{e.actor.startsWith("user:") ? e.actor.slice(5) : e.actor.startsWith("key:") ? "organisation key" : e.actor.startsWith("token:") ? "enrolment token" : e.actor === "server:manage" ? "on the server" : e.actor}</td>
                      </tr>
                    ))}
                    {log.data.entries.length === 0 && <tr><td colSpan={4} className="px-4 py-6 text-center text-muted-foreground">Nothing recorded yet.</td></tr>}
                  </tbody>
                </table>
              )}
            </Card>
          </Section>
        </div>
      )}
    </>
  );
}
