/* Who has access and through what: people and their roles, share links for someone without an account,
   enrolment tokens for PCs, and your own password. */
import { useState, type ReactNode } from "react";
import { Copy, Link2, MonitorSmartphone, UserPlus, X } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { usePoll } from "@/lib/hooks";
import { when } from "@/lib/format";
import { Card, Confirm, ListSkeleton, LoadError, Notice, PageHeader, Segmented, Spin } from "@/shadow/ui";
import { api, type Access, type Person, type Role, type UserAction } from "../api";
import { Section } from "../parts";
import { ROLE_ABOUT, ROLE_LABEL, useCan } from "../session";

const ROLES: Role[] = ["auditor", "admin", "owner"];
const roleOptions = ROLES.map((r) => ({ value: r, label: ROLE_LABEL[r] }));
const here = () => `${window.location.origin}${window.location.pathname}`;

/** Something that is shown once: a link or a token. */
type Once = { title: string; value: string; about: ReactNode };

function ShownOnce({ once, onClose }: { once: Once; onClose: () => void }) {
  const copy = async () => { try { await navigator.clipboard.writeText(once.value); toast.success("Copied"); } catch { toast.error("Could not copy. Select it and copy by hand."); } };
  return (
    <Notice tone="success" className="mb-6">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="font-medium">{once.title}</div>
          <div className="path select-all break-all rounded-md border bg-card px-2.5 py-2 text-xs">{once.value}</div>
          <div className="text-sm">{once.about} <span className="font-medium">It is shown only now.</span></div>
          <Button size="sm" variant="outline" onClick={() => void copy()}><Copy />Copy</Button>
        </div>
        <Button size="icon" variant="ghost" onClick={onClose} aria-label="Close"><X /></Button>
      </div>
    </Notice>
  );
}

function AddPerson({ days, onAdded }: { days: number; onAdded: (o: Once) => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("auditor");
  const [busy, setBusy] = useState(false);
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.addUser(email.trim(), name.trim(), role);
      onAdded({ title: `Send this link to ${email.trim()}`, value: `${here()}#/setup/${r.setup_token}`, about: `They set their own password with it. It works once, for ${r.valid_days} days.` });
      setEmail(""); setName("");
    } catch (err) { toast.error((err as Error).message); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={add} className="space-y-3 px-5 py-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="block min-w-56 flex-1 space-y-1.5"><span className="text-sm font-medium">Email address</span><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required className="h-9" /></label>
        <label className="block min-w-40 flex-1 space-y-1.5"><span className="text-sm font-medium">Name (optional)</span><Input value={name} onChange={(e) => setName(e.target.value)} className="h-9" /></label>
        <div className="space-y-1.5"><span className="block text-sm font-medium">Role</span><Segmented label="Role" value={role} onChange={setRole} options={roleOptions} /></div>
        <Button type="submit" disabled={busy || !email.trim()}>{busy ? <Spin /> : <UserPlus />}Add</Button>
      </div>
      <p className="text-xs text-muted-foreground">{ROLE_LABEL[role]}: {ROLE_ABOUT[role]} No email is sent: you pass the link on yourself. It is valid for {days} days.</p>
    </form>
  );
}

function PersonRow({ u, mine, canManage, onDo }: { u: Person; mine: boolean; canManage: boolean; onDo: (a: UserAction, role?: Role) => void }) {
  return (
    <tr className="align-top">
      <td className="px-4 py-3">
        <div className="font-medium">{u.name || u.email}{mine && <Badge variant="muted" className="ml-2">You</Badge>}</div>
        {u.name && <div className="text-xs text-muted-foreground">{u.email}</div>}
      </td>
      <td className="px-4 py-3"><Badge variant={u.role === "owner" ? "info" : "muted"}>{ROLE_LABEL[u.role]}</Badge></td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1.5">
          {u.disabled ? <Badge variant="danger">Switched off</Badge>
            : !u.has_password ? <Badge variant="warning">Has not set a password yet</Badge>
            : !u.second_factor ? <Badge variant="warning">No second factor yet</Badge>
            : <Badge variant="success">Password and second factor</Badge>}
          {u.locked && <Badge variant="warning">Locked for a few minutes</Badge>}
        </div>
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{u.last_login ? when(u.last_login) : "never"}</td>
      <td className="px-4 py-3 text-right">
        {canManage && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button size="sm" variant="outline">Change</Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              {!mine && <>
                <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">Role</DropdownMenuLabel>
                {ROLES.filter((r) => r !== u.role).map((r) => <DropdownMenuItem key={r} onSelect={() => onDo("role", r)}>Make {ROLE_LABEL[r].toLowerCase()}</DropdownMenuItem>)}
                <DropdownMenuSeparator />
              </>}
              <DropdownMenuItem onSelect={() => onDo("reset_password")}>New link to set a password</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onDo("reset_second_factor")}>Let them set up a new second factor</DropdownMenuItem>
              {!mine && <><DropdownMenuSeparator /><DropdownMenuItem onSelect={() => onDo(u.disabled ? "enable" : "disable")}>{u.disabled ? "Switch on again" : "Switch off"}</DropdownMenuItem></>}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </td>
    </tr>
  );
}

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try { await api.changePassword(current, next); toast.success("Password changed. Other browsers were signed out."); setCurrent(""); setNext(""); }
    catch (err) { toast.error((err as Error).message); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={save} className="flex flex-wrap items-end gap-3 px-5 py-4">
      <label className="block min-w-48 flex-1 space-y-1.5"><span className="text-sm font-medium">Current password</span><Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" className="h-9" /></label>
      <label className="block min-w-48 flex-1 space-y-1.5"><span className="text-sm font-medium">New password (12 characters or more)</span><Input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" className="h-9" /></label>
      <Button type="submit" variant="outline" disabled={busy || !current || next.length < 12}>{busy && <Spin />}Change password</Button>
      {next.length > 0 && next.length < 12 && <p className="w-full text-xs text-warning">That is {next.length} character{next.length === 1 ? "" : "s"}: {12 - next.length} more needed.</p>}
    </form>
  );
}

export function AccessPage() {
  const q = usePoll<Access>(api.access, null);
  const isOwner = useCan("owner"), isAdmin = useCan("admin");
  const [once, setOnce] = useState<Once | null>(null);
  const [ask, setAsk] = useState<{ u: Person; action: UserAction; role?: Role } | null>(null);
  const [label, setLabel] = useState("");
  const [days, setDays] = useState("14");
  const [tokenLabel, setTokenLabel] = useState("");
  const [uses, setUses] = useState("1");
  const d = q.data;

  const run = async (fn: () => Promise<void>) => { try { await fn(); await q.reload(); } catch (e) { toast.error((e as Error).message); } };
  const change = (u: Person, action: UserAction, role?: Role) => run(async () => {
    const r = await api.changeUser(u.id, action, role);
    if (r.setup_token) setOnce({ title: `Send this link to ${u.email}`, value: `${here()}#/setup/${r.setup_token}`, about: `They set a new password with it. It works once, for ${r.valid_days} days. Their old password works until then.` });
    else toast.success("Done");
  });
  const addLink = (e: React.FormEvent) => { e.preventDefault(); void run(async () => {
    const r = await api.addShareLink(label.trim(), Number(days) || 14);
    setOnce({ title: `The link for ${label.trim()}`, value: `${here()}#/share/${r.share_token}`, about: `Whoever has it can read the organisation's evidence for ${r.days} days, without an account, and change nothing. You can withdraw it at any time.` });
    setLabel("");
  }); };
  const addToken = (e: React.FormEvent) => { e.preventDefault(); void run(async () => {
    const r = await api.addEnrolmentToken(tokenLabel.trim(), Number(uses) || 1, 7);
    setOnce({ title: "Enrolment token", value: r.enrolment_token, about: <>On each PC: <span className="path">shadow_agent.py fleet enrol {window.location.origin} &lt;token&gt;</span>. Good for {r.uses} PC{r.uses === 1 ? "" : "s"}, for {r.days} days.</> });
    setTokenLabel("");
  }); };
  const QUESTION: Record<string, (u: Person, role?: Role) => [string, string, string]> = {
    disable: (u) => [`Switch off ${u.email}?`, "They are signed out now and cannot sign in until switched on again. Nothing they did is removed from the record.", "Switch off"],
    reset_second_factor: (u) => [`Let ${u.email} set up a new second factor?`, "Their authenticator app and recovery codes stop working and they are signed out. At the next sign-in, with their password, they set up a new one. Do this only when you are sure it is them asking.", "Reset"],
    role: (u, role) => [`Make ${u.email} ${role ? ROLE_LABEL[role].toLowerCase() : ""}?`, role ? ROLE_ABOUT[role] : "", "Change role"],
  };

  return (
    <>
      <PageHeader title="Access" sub="Who can open this console, what they may do, and what you have handed out." />
      {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
      {once && <ShownOnce once={once} onClose={() => setOnce(null)} />}
      {!d ? !q.error && <ListSkeleton rows={3} /> : (
        <div className="space-y-8">
          {isAdmin && (
            <Section title="People" sub="Everyone signs in with their own password and a second factor. Every change they make is recorded under their name.">
              <Card className="overflow-x-auto rounded-lg">
                <table className="w-full text-sm">
                  <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                    <tr><th className="px-4 py-2 font-medium">Person</th><th className="px-4 py-2 font-medium">Role</th><th className="px-4 py-2 font-medium">Sign-in</th><th className="px-4 py-2 font-medium">Last signed in</th><th className="px-4 py-2" /></tr>
                  </thead>
                  <tbody className="divide-y">
                    {d.users.map((u) => <PersonRow key={u.id} u={u} mine={u.id === d.me.id} canManage={isOwner}
                      onDo={(a, role) => (a in QUESTION ? setAsk({ u, action: a, role }) : void change(u, a, role))} />)}
                  </tbody>
                </table>
                {isOwner && <div className="border-t"><AddPerson days={d.setup_days} onAdded={(o) => { setOnce(o); void q.reload(); }} /></div>}
              </Card>
              {!isOwner && <p className="text-sm text-muted-foreground">Only an owner can add or change people.</p>}
            </Section>
          )}

          {isAdmin && (
            <Section title="Share links" sub="For a broker or an assessor without an account: the organisation's evidence, read-only, until the link expires.">
              <Card className="rounded-lg">
                {d.share_links.length > 0 && (
                  <div className="divide-y">
                    {d.share_links.map((l) => (
                      <div key={l.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3">
                        <Link2 className="size-4 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <span className="font-medium">{l.label}</span>
                          <Badge variant={l.state === "active" ? "success" : "muted"} className="ml-2">{l.state === "active" ? "Active" : l.state === "expired" ? "Expired" : "Withdrawn"}</Badge>
                          <div className="text-xs text-muted-foreground">
                            Made {when(l.created_at)} by {l.created_by.replace(/^user:/, "")} · {l.state === "active" ? `ends ${new Date(l.expires_at).toLocaleDateString()}` : `ended ${new Date(l.expires_at).toLocaleDateString()}`} · opened {l.opened} time{l.opened === 1 ? "" : "s"}{l.last_opened ? `, last ${when(l.last_opened)}` : ""}
                          </div>
                        </div>
                        {l.state === "active" && <Button size="sm" variant="outline" onClick={() => void run(async () => { await api.revokeShareLink(l.id); toast.success("Withdrawn. The link no longer opens anything."); })}>Withdraw</Button>}
                      </div>
                    ))}
                  </div>
                )}
                <form onSubmit={addLink} className={"flex flex-wrap items-end gap-3 px-5 py-4" + (d.share_links.length ? " border-t" : "")}>
                  <label className="block min-w-56 flex-1 space-y-1.5"><span className="text-sm font-medium">Who is it for?</span><Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Broker, renewal 2027" className="h-9" /></label>
                  <label className="block w-28 space-y-1.5"><span className="text-sm font-medium">Days (1 to 90)</span><Input type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} className="h-9" /></label>
                  <Button type="submit" variant="outline" disabled={!label.trim()}><Link2 />Make a link</Button>
                </form>
              </Card>
            </Section>
          )}

          {isAdmin && (
            <Section title="Enrolment tokens" sub="A token lets a PC join this organisation. Tokens that are used up or expired are not listed.">
              <Card className="rounded-lg">
                {d.enrolment_tokens.length > 0 && (
                  <div className="divide-y">
                    {d.enrolment_tokens.map((t) => (
                      <div key={t.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                        <MonitorSmartphone className="size-4 text-muted-foreground" />
                        <span className="font-medium">{t.label || "No label"}</span>
                        <span className="text-muted-foreground">{t.uses_left} PC{t.uses_left === 1 ? "" : "s"} left · ends {new Date(t.expires_at).toLocaleDateString()}</span>
                      </div>
                    ))}
                  </div>
                )}
                <form onSubmit={addToken} className={"flex flex-wrap items-end gap-3 px-5 py-4" + (d.enrolment_tokens.length ? " border-t" : "")}>
                  <label className="block min-w-56 flex-1 space-y-1.5"><span className="text-sm font-medium">Label (optional)</span><Input value={tokenLabel} onChange={(e) => setTokenLabel(e.target.value)} placeholder="Front office PCs" className="h-9" /></label>
                  <label className="block w-32 space-y-1.5"><span className="text-sm font-medium">How many PCs</span><Input type="number" min={1} max={500} value={uses} onChange={(e) => setUses(e.target.value)} className="h-9" /></label>
                  <Button type="submit" variant="outline">Make a token</Button>
                </form>
              </Card>
              {d.organisation_keys > 0 && <p className="text-sm text-muted-foreground">This organisation also has {d.organisation_keys} organisation key{d.organisation_keys === 1 ? "" : "s"} made on the server, for scripts. A key can read and change nothing.</p>}
            </Section>
          )}

          <Section title="Your account" sub={<>{d.me.email} · {ROLE_LABEL[d.me.role]}: {ROLE_ABOUT[d.me.role]}</>}>
            <Card className="rounded-lg"><ChangePassword /></Card>
            <p className="text-sm text-muted-foreground">You are signed out after 2 hours without activity, and after {d.session_hours} hours at the latest. Lost your authenticator app? An owner can let you set up a new one.</p>
          </Section>
        </div>
      )}

      <Confirm
        open={!!ask}
        onOpenChange={(o) => { if (!o) setAsk(null); }}
        title={ask ? QUESTION[ask.action]!(ask.u, ask.role)[0] : ""}
        confirmLabel={ask ? QUESTION[ask.action]!(ask.u, ask.role)[2] : ""}
        danger={ask?.action === "disable"}
        onConfirm={() => { if (ask) void change(ask.u, ask.action, ask.role); setAsk(null); }}
      >
        <p>{ask ? QUESTION[ask.action]!(ask.u, ask.role)[1] : ""}</p>
      </Confirm>
    </>
  );
}
