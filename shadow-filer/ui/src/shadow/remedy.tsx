/* Update an application and stop a service: the two things the console can change on this PC.
   Each is one click, confirmed in a dialog, run by the agent one at a time, and reported in the bar. */
import { useEffect, useRef, useState } from "react";
import { Download, Square, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import type { RemedyJob, RemedyResponse, UpdatePlan } from "@/lib/types";
import { Confirm, Mono, Notice, Spin, Tip, act } from "./ui";

const REMEDY_STARTED = "sf-remedy-started";
const emitStarted = () => window.dispatchEvent(new Event(REMEDY_STARTED));

/** Shows the running update or stop, then its result. `onDone` reloads the page's lists. */
export function RemedyBar({ onDone }: { onDone: () => void }) {
  const [fast, setFast] = useState(false);
  const [result, setResult] = useState<RemedyJob | null>(null);
  const q = usePoll<RemedyResponse>(() => api.remedy(), fast ? 2000 : 60_000);
  const job = q.data?.job;
  const was = useRef(false);
  useEffect(() => {
    const h = () => { setFast(true); setResult(null); void q.reload(); };
    window.addEventListener(REMEDY_STARTED, h);
    return () => window.removeEventListener(REMEDY_STARTED, h);
  }, [q]);
  useEffect(() => {
    const r = !!job?.running;
    if (r) setFast(true);
    if (was.current && !r && job) { setFast(false); setResult(job); onDone(); }
    was.current = r;
  }, [job?.running]); // eslint-disable-line react-hooks/exhaustive-deps

  if (job?.running) {
    return (
      <Notice className="mb-4" icon={<Spin />}>
        {job.action === "stop" ? <>Stopping <b>{job.name}</b>…</> : <>Updating <b>{job.name}</b> to {job.target}…</>}
        <span className="block text-muted-foreground">Windows may ask for permission on your desktop. This can take a few minutes.</span>
      </Notice>
    );
  }
  if (!result) return null;
  return (
    <Notice className="mb-4" tone={result.ok ? "success" : "danger"}>
      <div className="flex items-start gap-3">
        <span className="flex-1">{result.message}</span>
        <button aria-label="Dismiss" className="text-muted-foreground hover:text-foreground" onClick={() => setResult(null)}><X className="size-4" /></button>
      </div>
    </Notice>
  );
}

/** The Update button for one application, or why it cannot be updated from here. */
export function UpdateButton({ app }: { app: { id: string; name: string; version: string; update?: UpdatePlan | null } }) {
  const [open, setOpen] = useState(false);
  const u = app.update;
  if (!u) return null;
  if (u.blocked) {
    return <Tip tip={u.blocked}><span><Badge variant="muted">Not from here</Badge></span></Tip>;
  }
  const go = async () => {
    setOpen(false);
    if (await act(() => api.remedyUpdate(app.id))) emitStarted();
  };
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}><Download /> Update</Button>
      <Confirm open={open} onOpenChange={setOpen} title={`Update ${app.name}?`} confirmLabel="Accept terms and update" onConfirm={go}>
        <p className="text-foreground"><span className="tabular">{app.version || "?"}</span> → <b className="tabular">{u.to}</b></p>
        {u.kind === "same_line" && (
          <p>The latest version is {u.latest}, a major-version jump that can break data or settings. This update stays on the line you have.</p>
        )}
        <p>The agent runs <Mono className="text-xs">winget upgrade --id {u.id}{u.kind === "same_line" ? ` --version ${u.to}` : ""}</Mono>, which downloads the installer from the publisher and runs it.</p>
        <p>Close the program first if it is open. Windows may ask for permission on your desktop; declining stops the update.</p>
        <p>By continuing you accept the publisher's licence terms for this update.</p>
      </Confirm>
    </>
  );
}

/** Stop one running service. */
export function StopButton({ svc }: { svc: { id: string; name: string; running: boolean } }) {
  const [open, setOpen] = useState(false);
  if (!svc.running) return null;
  const go = async () => {
    setOpen(false);
    if (await act(() => api.remedyStop(svc.id))) emitStarted();
  };
  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}><Square /> Stop</Button>
      <Confirm open={open} onOpenChange={setOpen} title={`Stop ${svc.name}?`} confirmLabel="Stop service" danger onConfirm={go}>
        <p>Whatever uses this service stops working until it is started again.</p>
        <p>It is stopped, not disabled: Windows starts it again at the next restart if it is set to start automatically. To keep it off, change its start-up type in Windows' Services.</p>
        <p>Windows will ask for permission on your desktop.</p>
      </Confirm>
    </>
  );
}
