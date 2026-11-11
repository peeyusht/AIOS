/* Incident register (spec F-21): what happened, when it was noticed, and two clocks. Laid out after CERT-In's incident
   reporting form so the fields can be copied into it; nothing is submitted from here. */
import { useRef, useState } from "react";
import { Copy, Plus, Siren } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import { Card, Confirm, EmptyState, ListSkeleton, LoadError, Notice, PageHeader } from "@/shadow/ui";
import { api, type Incident, type Incidents } from "../api";
import { Section } from "../parts";
import { useCan } from "../session";

/* <input type="datetime-local"> gives local time without a zone; the server wants the zone. */
const toIso = (local: string) => (local ? new Date(local).toISOString() : "");
const toLocal = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const nowLocal = () => toLocal(new Date().toISOString());

function Clock({ label, state, due }: { label: string; state: string | null; due: string | null }) {
  if (!state || !due) return null;
  const left = new Date(due).getTime() - Date.now();
  const h = Math.floor(Math.abs(left) / 3600000), m = Math.floor((Math.abs(left) % 3600000) / 60000);
  const text = state === "done" ? "done" : state === "overdue" ? `overdue by ${h} h ${m} min` : `${h} h ${m} min left`;
  return <Badge variant={state === "done" ? "success" : state === "overdue" ? "danger" : "warning"}>{label}: {text}</Badge>;
}

function asText(i: Incident) {
  return [
    `Incident: ${i.title}`, `Type: ${i.kind}`, `Occurred: ${i.occurred_at ?? "not known"}`, `Noticed: ${i.detected_at}`,
    `Systems or devices affected: ${[i.systems, i.devices.map((d) => d.name).join(", ")].filter(Boolean).join("; ") || "-"}`,
    `Personal data involved: ${i.personal_data ? "yes" : "no"}`, `Description: ${i.description || "-"}`, `Actions taken: ${i.actions || "-"}`,
    `Contact: ${i.contact || "-"}`, `Reported to CERT-In: ${i.certin_reported_at ?? "not yet"}`,
    ...(i.personal_data ? [`Detailed report to the Data Protection Board: ${i.board_reported_at ?? "not yet"}`, `Affected people told: ${i.people_told_at ?? "not yet"}`] : []),
  ].join("\n");
}

function IncidentCard({ i, canEdit, onChange }: { i: Incident; canEdit: boolean; onChange: (f: Record<string, unknown>) => Promise<void> }) {
  const stamp = (k: keyof Incident, label: string) => (
    <label className="flex items-center gap-2 text-sm">
      <span className="w-56 text-muted-foreground">{label}</span>
      <Input type="datetime-local" className="h-8 w-56" disabled={!canEdit} defaultValue={toLocal(i[k] as string | null)} max={nowLocal()}
        onBlur={(e) => { const v = toIso(e.target.value); if (v !== (i[k] ?? "")) void onChange({ [k]: v || null }); }} />
    </label>
  );
  const copy = async () => { try { await navigator.clipboard.writeText(asText(i)); toast.success("Copied"); } catch { toast.error("Could not copy."); } };
  return (
    <Card className="space-y-3 rounded-lg p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">{i.title} {i.closed_at && <Badge variant="muted">closed</Badge>}</h3>
          <p className="text-sm text-muted-foreground">{i.kind} · noticed {when(i.detected_at)}{i.personal_data ? " · personal data involved" : ""}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Clock label="CERT-In 6 h" state={i.certin} due={i.certin_due} />
          <Clock label="DPDP Board 72 h" state={i.board} due={i.board_due} />
          <Button variant="outline" size="sm" onClick={() => void copy()}><Copy />Copy for the report</Button>
        </div>
      </div>
      {i.description && <p className="text-sm leading-relaxed">{i.description}</p>}
      {(i.devices.length > 0 || i.systems) && <p className="text-sm"><span className="text-muted-foreground">Affected: </span>{[i.systems, i.devices.map((d) => d.name).join(", ")].filter(Boolean).join("; ")}</p>}
      <div className="space-y-1.5 border-t pt-3">
        {stamp("certin_reported_at", "Reported to CERT-In")}
        {i.personal_data && stamp("people_told_at", "Affected people told (without delay)")}
        {i.personal_data && stamp("board_reported_at", "Detailed report to the Board")}
        {stamp("closed_at", "Closed")}
      </div>
      {canEdit && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={i.personal_data} onChange={(e) => void onChange({ personal_data: e.target.checked })} />
          Personal data was involved (starts DPDP's 72-hour clock)
        </label>
      )}
      <p className="text-xs text-muted-foreground">Recorded by {i.created_by.replace(/^user:/, "")} · last changed {when(i.updated_at)} by {i.updated_by.replace(/^user:/, "")}</p>
    </Card>
  );
}

export function IncidentsPage() {
  const q = usePoll<Incidents>(api.incidents, 60_000);
  const canEdit = useCan("admin");
  const [adding, setAdding] = useState(false);
  const blank = { title: "", kind: "Other", detected_at: nowLocal(), occurred_at: "", description: "", systems: "", actions: "", contact: "", personal_data: false };
  const [f, setF] = useState(blank);
  const keep = useRef(false);
  const d = q.data;

  const save = async () => {
    try {
      await api.addIncident({ ...f, detected_at: toIso(f.detected_at), occurred_at: toIso(f.occurred_at) || null });
      toast.success("Recorded"); setF(blank); await q.reload();
    } catch (e) { keep.current = true; toast.error((e as Error).message); }
  };
  const change = (id: string) => async (fields: Record<string, unknown>) => {
    try { await api.changeIncident(id, fields); await q.reload(); } catch (e) { toast.error((e as Error).message); }
  };

  return (
    <>
      <PageHeader title="Incidents"
        sub="Every security incident, when it was noticed, and the deadlines that follow. Nothing is submitted from here: copy the record into CERT-In's form and the Board's."
        actions={canEdit && <Button size="sm" onClick={() => { setF(blank); setAdding(true); }}><Plus />Record an incident</Button>} />
      {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
      {!d ? !q.error && <ListSkeleton rows={3} /> : (
        <div className="space-y-6">
          <Notice>
            CERT-In: report within {d.certin_hours} hours of noticing an incident (directions under section 70B(6) of the IT Act). DPDP Rule 7: when
            personal data is involved, tell the affected people and the Board without delay, and send the Board a detailed report within {d.board_hours} hours.
          </Notice>
          {d.incidents.length === 0
            ? <EmptyState icon={<Siren />} title="No incident recorded">Record one as soon as it is noticed: the clocks start then.</EmptyState>
            : <Section title="Register" sub="Newest first. An incident is closed, never deleted.">
                <div className="space-y-4">{d.incidents.map((i) => <IncidentCard key={i.id + i.updated_at} i={i} canEdit={canEdit} onChange={change(i.id)} />)}</div>
              </Section>}
        </div>
      )}
      <Confirm open={adding} onOpenChange={(o) => { if (!o && keep.current) { keep.current = false; return; } setAdding(o); }} title="Record an incident" confirmLabel="Record" onConfirm={save}>
        <div className="space-y-2 text-foreground">
          <Input placeholder="What happened, in a few words" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} autoFocus />
          <select className="h-9 w-full rounded-md border bg-background px-2 text-sm" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })} aria-label="Kind of incident">
            {(d?.kinds ?? ["Other"]).map((k) => <option key={k}>{k}</option>)}
          </select>
          <label className="block text-sm">Noticed at <Input type="datetime-local" max={nowLocal()} value={f.detected_at} onChange={(e) => setF({ ...f, detected_at: e.target.value })} /></label>
          <label className="block text-sm">Happened at (if known) <Input type="datetime-local" max={nowLocal()} value={f.occurred_at} onChange={(e) => setF({ ...f, occurred_at: e.target.value })} /></label>
          <Textarea placeholder="Description" rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
          <Input placeholder="Systems affected (other than enrolled PCs)" value={f.systems} onChange={(e) => setF({ ...f, systems: e.target.value })} />
          <Textarea placeholder="Actions taken so far" rows={2} value={f.actions} onChange={(e) => setF({ ...f, actions: e.target.value })} />
          <Input placeholder="Contact person for this incident" value={f.contact} onChange={(e) => setF({ ...f, contact: e.target.value })} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.personal_data} onChange={(e) => setF({ ...f, personal_data: e.target.checked })} />Personal data was involved</label>
        </div>
      </Confirm>
    </>
  );
}
