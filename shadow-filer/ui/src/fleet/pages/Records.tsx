/* Governance and reviews (spec F-23, F-24): the security in-charge, the policy's dates, and review sign-offs. Shown on
   the Evidence page. A sign-off is a person's statement: added, never edited. */
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import { Card, ListSkeleton, LoadError } from "@/shadow/ui";
import { api, type Records } from "../api";

const today = () => new Date().toISOString().slice(0, 10);

function Governance({ r, canEdit, reload }: { r: Records; canEdit: boolean; reload: () => void }) {
  const g = r.governance;
  const [f, setF] = useState({ incharge_name: g?.incharge_name ?? "", incharge_contact: g?.incharge_contact ?? "",
    policy_approved_on: g?.policy_approved_on ?? "", policy_next_review: g?.policy_next_review ?? "" });
  const save = async () => { try { await api.setGovernance(f); toast.success("Saved"); reload(); } catch (e) { toast.error((e as Error).message); } };
  const field = (k: keyof typeof f, label: string, type = "text", max?: string) => (
    <label className="grid gap-1 text-sm min-[700px]:grid-cols-[220px_1fr] min-[700px]:items-center">
      <span className="text-muted-foreground">{label}</span>
      <Input type={type} max={max} value={f[k]} disabled={!canEdit} onChange={(e) => setF({ ...f, [k]: e.target.value })} className="h-8 max-w-md" />
    </label>
  );
  return (
    <Card className="space-y-2 rounded-lg p-5">
      <h3 className="font-semibold">Governance</h3>
      <p className="text-sm text-muted-foreground">CERT-In GC.1 to GC.3: a named security in-charge, a security policy approved by the organisation, and its periodic review. The policy document itself can be attached once uploads exist.</p>
      {field("incharge_name", "Security in-charge")}
      {field("incharge_contact", "Their contact")}
      {field("policy_approved_on", "Security policy approved on", "date", today())}
      {field("policy_next_review", "Next review of the policy", "date")}
      {canEdit && <Button size="sm" onClick={() => void save()}>Save</Button>}
      {g && <p className="text-xs text-muted-foreground">Last changed {when(g.updated_at)} by {g.updated_by.replace(/^user:/, "")}</p>}
    </Card>
  );
}

function Review({ kind, r, canEdit, reload }: { kind: string; r: Records["reviews"][string]; canEdit: boolean; reload: () => void }) {
  const [day, setDay] = useState(today());
  const [note, setNote] = useState("");
  const sign = async () => {
    try { await api.addReview(kind, day, note); toast.success("Recorded"); setNote(""); reload(); } catch (e) { toast.error((e as Error).message); }
  };
  return (
    <Card className="space-y-2 rounded-lg p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{r.title}</h3>
        <Badge variant={r.state === "done" ? "success" : r.state === "overdue" ? "danger" : "warning"}>
          {r.state === "done" ? `next due ${r.due}` : r.state === "overdue" ? `due since ${r.due}` : "never recorded"}
        </Badge>
        <span className="text-xs text-muted-foreground">every {r.days} days</span>
      </div>
      <p className="text-sm text-muted-foreground">{r.about}</p>
      {canEdit && (
        <div className="flex flex-wrap items-center gap-2">
          <Input type="date" max={today()} value={day} onChange={(e) => setDay(e.target.value)} className="h-8 w-40" aria-label={`${r.title}: day`} />
          <Input placeholder="What was looked at, what was found (optional)" value={note} onChange={(e) => setNote(e.target.value)} className="h-8 max-w-md" />
          <Button size="sm" variant="outline" onClick={() => void sign()}>Sign off</Button>
        </div>
      )}
      {r.history.length > 0 && (
        <ul className="space-y-0.5 text-sm">
          {r.history.slice(0, 5).map((h, i) => <li key={i}><span className="font-mono text-xs">{h.reviewed_on}</span> · {h.actor.replace(/^user:/, "")}{h.note && ` · ${h.note}`}</li>)}
        </ul>
      )}
    </Card>
  );
}

export function RecordsSection({ canEdit, onChange }: { canEdit: boolean; onChange?: () => void }) {
  const q = usePoll<Records>(api.records, null);
  if (q.error) return <LoadError error={q.error} onRetry={q.reload} />;
  if (!q.data) return <ListSkeleton rows={2} />;
  const reload = () => { void q.reload(); onChange?.(); };
  return (
    <div className="space-y-4">
      <Governance key={q.data.governance?.updated_at ?? "none"} r={q.data} canEdit={canEdit} reload={reload} />
      {Object.entries(q.data.reviews).map(([k, r]) => <Review key={k} kind={k} r={r} canEdit={canEdit} reload={reload} />)}
    </div>
  );
}
