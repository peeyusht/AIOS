/* Signing in: address and password, then a code from an authenticator app. The first time, the app is set up
   here and the recovery codes are shown once. Also the page a one-time link opens to set a password. */
import { useEffect, useState, type ReactNode } from "react";
import { Check, Copy, KeyRound, ShieldCheck, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Card, Notice, Spin } from "@/shadow/ui";
import { api, type Stage } from "../api";
import { refreshMe, signOut } from "../session";

export function Logo() {
  return (
    <svg viewBox="0 0 24 24" className="size-7" aria-hidden>
      <rect x="2" y="2" width="20" height="20" rx="6" className="fill-primary" />
      <path d="M7 9.5h4l1.2 1.5H17v6H7z" className="fill-primary-foreground" opacity=".95" />
      <path d="M8.5 13.5h7" className="stroke-primary" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

export function Frame({ title, children, foot, wide }: { title: string; children: ReactNode; foot?: ReactNode; wide?: boolean }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6 py-10 text-foreground">
      <Card className={wide ? "w-full max-w-lg p-6" : "w-full max-w-md p-6"}>
        <div className="mb-5 flex items-center gap-2.5">
          <Logo />
          <div className="leading-tight"><div className="font-semibold">Shadow Filer</div><div className="text-xs text-muted-foreground">fleet console</div></div>
        </div>
        <h1 className="mb-3 text-lg font-semibold">{title}</h1>
        {children}
        {foot && <div className="mt-4 text-xs leading-relaxed text-muted-foreground">{foot}</div>}
      </Card>
    </div>
  );
}

function useForm() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return { busy, error, run, setError };
}

const StartAgain = () => <button className="text-primary hover:underline" onClick={() => void signOut()}>Start again with another account</button>;

function Password({ onStage }: { onStage: (s: Stage) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const f = useForm();
  return (
    <Frame title="Sign in" foot="An account is made by an owner of your organisation, who sends you a link to set your password.">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void f.run(async () => onStage((await api.login(email.trim(), password)).stage)); }}>
        <label className="block space-y-1.5"><span className="text-sm font-medium">Email address</span>
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus autoComplete="username" required /></label>
        <label className="block space-y-1.5"><span className="text-sm font-medium">Password</span>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        {f.error && <Notice tone="danger">{f.error}</Notice>}
        <Button type="submit" disabled={f.busy || !email.trim() || !password} className="w-full">{f.busy ? <Spin /> : <KeyRound />}Continue</Button>
      </form>
    </Frame>
  );
}

function Code({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState("");
  const f = useForm();
  const submit = () => f.run(async () => {
    const r = await api.code(code.trim());
    if (r.recovery_left != null) toast.message(`That was a recovery code. ${r.recovery_left} left.`, { description: "Ask an owner to let you set up a new second factor if you lost your authenticator app." });
    onDone();
  });
  return (
    <Frame title="Your code" foot={<StartAgain />}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <label className="block space-y-1.5"><span className="text-sm font-medium">The 6-digit code from your authenticator app</span>
          <Input value={code} onChange={(e) => setCode(e.target.value)} autoFocus inputMode="numeric" autoComplete="one-time-code" placeholder="123456" className="path text-base tracking-widest" /></label>
        <p className="text-xs text-muted-foreground">No app at hand? Type one of your recovery codes instead. Each works once.</p>
        {f.error && <Notice tone="danger">{f.error}</Notice>}
        <Button type="submit" disabled={f.busy || code.trim().length < 6} className="w-full">{f.busy ? <Spin /> : <ShieldCheck />}Sign in</Button>
      </form>
    </Frame>
  );
}

function SecondFactor({ onDone }: { onDone: () => void }) {
  const [info, setInfo] = useState<{ secret: string; qr: string; email: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);
  const f = useForm();
  useEffect(() => { api.secondFactor().then(setInfo).catch((e) => f.setError((e as Error).message)); /* once */ }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const copy = async (text: string) => { try { await navigator.clipboard.writeText(text); toast.success("Copied"); setSaved(true); } catch { toast.error("Could not copy. Write them down."); } };

  if (codes) {
    return (
      <Frame title="Keep these recovery codes" wide>
        <p className="text-sm text-muted-foreground">If you lose your phone, one of these signs you in instead of a code. Each works once. They are shown only now.</p>
        <div className="my-4 grid grid-cols-2 gap-x-6 gap-y-1.5 rounded-lg border bg-muted/40 px-4 py-3">{codes.map((c) => <span key={c} className="path text-sm">{c}</span>)}</div>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" onClick={() => void copy(codes.join("\n"))}><Copy />Copy</Button>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} className="size-4 accent-[var(--primary)]" />I have kept them somewhere safe</label>
          <Button className="ml-auto" disabled={!saved} onClick={onDone}>Open the console</Button>
        </div>
      </Frame>
    );
  }
  return (
    <Frame title="Set up your second factor" wide foot={<StartAgain />}>
      <p className="text-sm text-muted-foreground">Signing in needs a code from an authenticator app (Microsoft Authenticator, Google Authenticator, 1Password and others) as well as your password.</p>
      {!info ? (f.error ? <Notice tone="danger" className="mt-3">{f.error}</Notice> : <div className="flex justify-center py-10"><Spin /></div>) : (
        <form className="mt-4 space-y-4" onSubmit={(e) => { e.preventDefault(); void f.run(async () => setCodes((await api.confirmSecondFactor(code.trim())).recovery_codes)); }}>
          <div className="flex flex-wrap items-center gap-5">
            <img src={info.qr} alt="A code to scan with your authenticator app" className="size-44 rounded-lg border bg-white p-1" />
            <div className="min-w-0 flex-1 space-y-2 text-sm">
              <div><span className="font-medium">1.</span> Scan this with the app, or type the key in by hand:</div>
              <div className="path break-all rounded-md border bg-muted/40 px-2 py-1.5 text-xs">{info.secret.replace(/(.{4})/g, "$1 ").trim()}</div>
              <div><span className="font-medium">2.</span> Type the 6-digit code the app shows for {info.email}.</div>
            </div>
          </div>
          <Input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" placeholder="123456" className="path text-base tracking-widest" aria-label="Code from the app" autoFocus />
          {f.error && <Notice tone="danger">{f.error}</Notice>}
          <Button type="submit" disabled={f.busy || code.trim().length < 6} className="w-full">{f.busy ? <Spin /> : <ShieldCheck />}Confirm</Button>
        </form>
      )}
    </Frame>
  );
}

/** The password policy, one line per rule. The server checks the same rules again (auth.password_problem). */
export function passwordRules(password: string, email: string, min: number) {
  const mail = email.toLowerCase();
  return [
    { ok: password.length >= min, label: `At least ${min} characters`, miss: `it is ${password.length} character${password.length === 1 ? "" : "s"} long and needs at least ${min}` },
    { ok: new Set(password).size >= 5, label: "Not the same few characters repeated", miss: "it repeats the same few characters" },
    { ok: !mail || ![mail, mail.split("@")[0]].includes(password.toLowerCase()), label: "Not your email address", miss: "it is your email address" },
  ];
}

/** What is wrong with a new password, as one sentence, or null when it meets the policy. */
export function passwordProblem(password: string, again: string | null, email: string, min: number): string | null {
  const missed = passwordRules(password, email, min).filter((r) => !r.ok).map((r) => r.miss);
  if (missed.length) return `This password does not meet the password policy: ${missed.join(", and ")}.`;
  return again !== null && password !== again ? "The two passwords are not the same. Type the new password again in the second box." : null;
}

/** The rules as a list that ticks off while typing. */
export function PasswordPolicy({ password, email, min }: { password: string; email: string; min: number }) {
  return (
    <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs">
      <div className="mb-1 font-medium">Password policy</div>
      <ul className="space-y-0.5">
        {passwordRules(password, email, min).map((r) => {
          const state = !password ? "idle" : r.ok ? "ok" : "bad";
          return (
            <li key={r.label} className={cn("flex items-center gap-1.5", state === "ok" ? "text-success" : state === "bad" ? "text-destructive" : "text-muted-foreground")}>
              {state === "ok" ? <Check className="size-3.5" aria-label="Met" /> : state === "bad" ? <X className="size-3.5" aria-label="Not met" /> : <span className="inline-block size-3.5 text-center leading-3">·</span>}
              {r.label}{state === "bad" && r.label.startsWith("At least") && ` (${password.length} so far)`}
            </li>
          );
        })}
      </ul>
      <p className="mt-1.5 text-muted-foreground">Symbols, numbers and capital letters are allowed but not required. Length is what makes a password hard to guess: a few unrelated words work well.</p>
    </div>
  );
}

/** stage: where the server says this browser is (null: not signed in at all). */
export function SignIn({ stage }: { stage: Stage | null }) {
  const [local, setLocal] = useState<Stage | null>(stage);
  useEffect(() => setLocal(stage), [stage]);
  const done = () => void refreshMe();
  if (local === "mfa") return <Code onDone={done} />;
  if (local === "mfa_setup") return <SecondFactor onDone={done} />;
  return <Password onStage={(s) => (s === "ok" ? done() : setLocal(s))} />;
}

/** The page a one-time link opens: set your own password. */
export function SetPassword({ token }: { token: string }) {
  const [who, setWho] = useState<{ email: string; min_password: number } | null>(null);
  const [gone, setGone] = useState<string | null>(null);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [done, setDone] = useState(false);
  const f = useForm();
  useEffect(() => { api.setupCheck(token).then(setWho).catch((e) => setGone((e as Error).message)); }, [token]);
  const home = () => { window.location.hash = "/overview"; };

  if (gone) return <Frame title="This link does not work"><Notice tone="warn">{gone}</Notice><Button variant="outline" className="mt-4" onClick={home}>To the sign-in page</Button></Frame>;
  if (done) {
    return (
      <Frame title="Your password is set">
        <p className="text-sm text-muted-foreground">Sign in with {who?.email} and your new password. The first time, you will set up a second factor.</p>
        <Button className="mt-4 w-full" onClick={() => { void signOut().then(home); }}>Sign in</Button>
      </Frame>
    );
  }
  if (!who) return <Frame title="Set your password"><div className="flex justify-center py-8"><Spin /></div></Frame>;
  const submit = () => {
    const problem = passwordProblem(a, b, who.email, who.min_password);
    if (problem) { f.setError(problem); return; }
    void f.run(async () => { await api.setup(token, a); setDone(true); });
  };
  return (
    <Frame title="Set your password" foot="The link works once. Nobody else, not even the person who invited you, ever sees your password.">
      <p className="mb-3 text-sm text-muted-foreground">For <span className="font-medium text-foreground">{who.email}</span>.</p>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label className="block space-y-1.5"><span className="text-sm font-medium">New password</span>
          <Input type="password" value={a} onChange={(e) => { setA(e.target.value); f.setError(null); }} autoFocus autoComplete="new-password" /></label>
        <label className="block space-y-1.5"><span className="text-sm font-medium">The same again</span>
          <Input type="password" value={b} onChange={(e) => { setB(e.target.value); f.setError(null); }} autoComplete="new-password" /></label>
        <PasswordPolicy password={a} email={who.email} min={who.min_password} />
        {f.error && <Notice tone="danger">{f.error}</Notice>}
        <Button type="submit" disabled={f.busy || !a} className="w-full">{f.busy ? <Spin /> : <KeyRound />}Set password</Button>
      </form>
    </Frame>
  );
}
