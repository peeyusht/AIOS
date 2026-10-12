/* Update an application and stop a service: the two things the console can change on this PC.
   Each is one click, confirmed in a dialog, run by the agent one at a time. What is happening is shown in
   three places, so it cannot be missed wherever the page is scrolled to: the button that was clicked, a
   toast, and a bar that stays at the top of the window. */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Download, ShieldCheck, Square, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { RemedyJob, UpdatePlan } from "@/lib/types";
import { Confirm, Mono, Notice, Spin, Tip, act } from "./ui";

/* One job at a time on the agent, so one shared state here: every button and the bar read the same thing. */
type Store = { job: RemedyJob | null; mine: string | null; result: RemedyJob | null };
let store: Store = { job: null, mine: null, result: null };
const subs = new Set<() => void>();
const doneSubs = new Set<() => void>();
const set = (p: Partial<Store>) => { store = { ...store, ...p }; subs.forEach((f) => f()); };
const useStore = () => useSyncExternalStore((f) => { subs.add(f); return () => void subs.delete(f); }, () => store);

let timer: ReturnType<typeof setTimeout> | null = null;
let toastId: string | number | undefined;
async function tick() {
  timer = null;
  let job: RemedyJob | null = null;
  try { job = (await api.remedy()).job; } catch { /* the agent may be busy: ask again */ }
  const was = !!store.job?.running;
  if (job) set({ job });
  if (job?.running || (!job && was)) { timer = setTimeout(tick, 1500); return; }
  if (was && job) {                                       // it just finished
    set({ result: job, mine: null });
    const id = toastId;                                   // the "Updating…" toast turns into the result
    toastId = undefined;
    if (job.ok) toast.success(job.message ?? "Done.", { id, description: undefined, duration: 10_000 });
    else toast.error(job.message ?? "It did not work.", { id, description: undefined, duration: 20_000 });
    doneSubs.forEach((f) => f());
  }
}
function watch() { if (!timer) timer = setTimeout(tick, 300); }

function started(id: string, text: string, action: "update" | "stop" | "firewall", name: string, target: string | null) {
  set({ mine: id, result: null, job: { ...EMPTY, running: true, action, name, target } });
  toastId = toast.loading(text, { description: "Windows may ask for permission on your desktop. This can take a few minutes.", duration: Infinity });
  watch();
}
const EMPTY: RemedyJob = { running: false, action: null, name: null, target: null, started: null, finished: null, ok: null, message: null };

/** Stays at the top of the window while an update or stop runs, then shows its result. `onDone` reloads the page's lists. */
export function RemedyBar({ onDone }: { onDone: () => void }) {
  const s = useStore();
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    const f = () => done.current();
    doneSubs.add(f);
    void tick();                                          // a job started earlier, or from another tab, shows too
    return () => void doneSubs.delete(f);
  }, []);
  const job = s.job;
  if (job?.running) {
    return (
      <div className="sticky top-14 z-10 mb-4" role="status" aria-live="polite">
        <Notice icon={<Spin />} className="bg-card shadow-md">
          {job.action === "firewall" ? <>Switching <b>Windows Firewall</b> on{job.target ? <> for {job.target}</> : null}…</>
            : job.action === "stop" ? <>Stopping <b>{job.name ?? "the service"}</b>…</>
            : job.name ? <>Updating <b>{job.name}</b>{job.target ? <> to {job.target}</> : null}…</> : <>Starting…</>}
          <span className="block text-muted-foreground">
            {job.message ?? "Windows may ask for permission on your desktop. This can take a few minutes."}
          </span>
        </Notice>
      </div>
    );
  }
  if (!s.result) return null;
  return (
    <div className="sticky top-14 z-10 mb-4" role="status" aria-live="polite">
      <Notice tone={s.result.ok ? "success" : "danger"} className="shadow-md">
        <div className="flex items-start gap-3">
          <span className="flex-1">{s.result.message}</span>
          <button aria-label="Dismiss" className="text-muted-foreground hover:text-foreground" onClick={() => set({ result: null })}><X className="size-4" /></button>
        </div>
      </Notice>
    </div>
  );
}

/** The Update button for one application, or why it cannot be updated from here. */
export function UpdateButton({ app }: { app: { id: string; name: string; version: string; update?: UpdatePlan | null } }) {
  const [open, setOpen] = useState(false);
  const s = useStore();
  const u = app.update;
  if (!u) return null;
  if (u.blocked) {
    return <Tip tip={u.blocked}><span><Badge variant="muted">Not from here</Badge></span></Tip>;
  }
  const busy = !!s.job?.running, mine = busy && s.mine === app.id;
  const go = async () => {
    setOpen(false);
    if (await act(() => api.remedyUpdate(app.id))) started(app.id, `Updating ${app.name} to ${u.to}…`, "update", app.name, u.to);
  };
  return (
    <>
      <Button variant="outline" size="sm" disabled={busy} onClick={() => setOpen(true)}
        title={busy && !mine ? "Another update or stop is still running" : undefined}>
        {mine ? <><Spin /> Updating…</> : <><Download /> Update</>}
      </Button>
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

/** Switch Windows Firewall on, for one profile or all. There is no "off": the agent cannot do that. */
export function FirewallButton({ profile, primary }: { profile: "all" | "Domain" | "Private" | "Public"; primary?: boolean }) {
  const [open, setOpen] = useState(false);
  const s = useStore();
  const id = "firewall:" + profile;
  const busy = !!s.job?.running, mine = busy && s.mine === id;
  const what = profile === "all" ? "all profiles" : `the ${profile} profile`;
  const go = async () => {
    setOpen(false);
    if (await act(() => api.remedyFirewallOn(profile))) started(id, `Switching Windows Firewall on for ${what}…`, "firewall", "Windows Firewall", what);
  };
  return (
    <>
      <Button variant={primary ? "default" : "outline"} size="sm" disabled={busy} onClick={() => setOpen(true)}
        title={busy && !mine ? "Another update or stop is still running" : undefined}>
        {mine ? <><Spin /> Switching on…</> : <><ShieldCheck /> {profile === "all" ? "Turn all on" : "Turn on"}</>}
      </Button>
      <Confirm open={open} onOpenChange={setOpen} title={`Turn Windows Firewall on for ${what}?`} confirmLabel="Turn on" onConfirm={go}>
        <p>Windows then blocks connections coming in from other devices unless a rule allows them. Programs that already have a rule keep working.</p>
        <p>A program on this PC that others connect to and that has no rule (a database, a file share, a remote-desktop tool) may stop being reachable until you allow it in Windows Security › Firewall.</p>
        <p>Windows will ask for permission on your desktop. Switching the firewall off again is done in Windows Security, not from here.</p>
      </Confirm>
    </>
  );
}

/** Stop one running service. */
export function StopButton({ svc }: { svc: { id: string; name: string; running: boolean } }) {
  const [open, setOpen] = useState(false);
  const s = useStore();
  if (!svc.running) return null;
  const busy = !!s.job?.running, mine = busy && s.mine === svc.id;
  const go = async () => {
    setOpen(false);
    if (await act(() => api.remedyStop(svc.id))) started(svc.id, `Stopping ${svc.name}…`, "stop", svc.name, null);
  };
  return (
    <>
      <Button variant="ghost" size="sm" disabled={busy} onClick={() => setOpen(true)}
        title={busy && !mine ? "Another update or stop is still running" : undefined}>
        {mine ? <><Spin /> Stopping…</> : <><Square /> Stop</>}
      </Button>
      <Confirm open={open} onOpenChange={setOpen} title={`Stop ${svc.name}?`} confirmLabel="Stop service" danger onConfirm={go}>
        <p>Whatever uses this service stops working until it is started again.</p>
        <p>It is stopped, not disabled: Windows starts it again at the next restart if it is set to start automatically. To keep it off, change its start-up type in Windows' Services.</p>
        <p>Windows will ask for permission on your desktop.</p>
      </Confirm>
    </>
  );
}
