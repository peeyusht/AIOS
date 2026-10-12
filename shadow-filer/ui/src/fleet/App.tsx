/* The fleet server's console: every enrolled PC of one organisation, judged on the server. Same components
   and styles as the PC's own console (src/shadow), a different shell and its own pages. */
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { ClipboardCheck, KeyRound, LayoutDashboard, LogOut, MonitorSmartphone, Moon, Package, Sun } from "lucide-react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Card, Notice, Spin } from "@/shadow/ui";
import { api, getKey, setKey } from "./api";
import { OverviewPage } from "./pages/Overview";
import { DevicesPage } from "./pages/Devices";
import { DevicePage } from "./pages/Device";
import { SoftwarePage } from "./pages/Software";
import { EvidencePage } from "./pages/Evidence";

const NAV = [
  { path: "/overview", label: "Overview", icon: LayoutDashboard },
  { path: "/devices", label: "Devices", icon: MonitorSmartphone },
  { path: "/software", label: "Software", icon: Package },
  { path: "/evidence", label: "Evidence", icon: ClipboardCheck },
] as const;

function useTheme() {
  const [dark, setDark] = useState(() => {
    let t: string | null = null;
    try { t = localStorage.getItem("sf-theme"); } catch { /* ignore */ }
    return t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);
  const toggle = () => {
    setDark(!dark);
    try { localStorage.setItem("sf-theme", !dark ? "dark" : "light"); } catch { /* ignore */ }
  };
  return { dark, toggle };
}

function Logo() {
  return (
    <svg viewBox="0 0 24 24" className="size-7" aria-hidden>
      <rect x="2" y="2" width="20" height="20" rx="6" className="fill-primary" />
      <path d="M7 9.5h4l1.2 1.5H17v6H7z" className="fill-primary-foreground" opacity=".95" />
      <path d="M8.5 13.5h7" className="stroke-primary" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

const subscribe = (cb: () => void) => {
  window.addEventListener("hashchange", cb);
  window.addEventListener("sf-fleet-key", cb);
  return () => { window.removeEventListener("hashchange", cb); window.removeEventListener("sf-fleet-key", cb); };
};
const hash = () => window.location.hash.replace(/^#/, "") || "/overview";

function SignIn() {
  const [key, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const k = key.trim();
    if (!k) return;
    setBusy(true);
    setError(null);
    try { await api.check(k); setKey(k); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6 text-foreground">
      <Card className="w-full max-w-md p-6">
        <div className="mb-5 flex items-center gap-2.5">
          <Logo />
          <div className="leading-tight"><div className="font-semibold">Shadow Filer</div><div className="text-xs text-muted-foreground">fleet console</div></div>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">Console key</span>
            <Input type="password" value={key} onChange={(e) => setValue(e.target.value)} placeholder="sfa_…" autoFocus autoComplete="off" spellCheck={false} />
          </label>
          {error && <Notice tone="danger">{error}</Notice>}
          <Button type="submit" disabled={busy || !key.trim()} className="w-full">{busy ? <Spin /> : <KeyRound />}Open the console</Button>
        </form>
        <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
          The key belongs to one organisation and shows only its devices. It is kept for this browser tab only and is gone when the tab is closed.
        </p>
      </Card>
    </div>
  );
}

export default function FleetApp() {
  const path = useSyncExternalStore(subscribe, hash, () => "/overview");
  const signedIn = useSyncExternalStore(subscribe, () => !!getKey(), () => false);
  const { dark, toggle } = useTheme();
  const [org, setOrg] = useState("");
  useEffect(() => { if (signedIn) api.devices().then((d) => setOrg(d.organisation)).catch(() => undefined); }, [signedIn]);

  const parts = path.split("/").filter(Boolean);
  const section = NAV.some((n) => n.path === "/" + parts[0]) ? "/" + parts[0] : "/overview";
  let page: ReactNode;
  if (section === "/devices") page = parts[1] ? <DevicePage id={parts[1]} tab={parts[2]} key={parts[1]} /> : <DevicesPage />;
  else if (section === "/software") page = <SoftwarePage />;
  else if (section === "/evidence") page = <EvidencePage />;
  else page = <OverviewPage />;

  return (
    <TooltipProvider delayDuration={300}>
      {!signedIn ? <SignIn /> : (
        <div className="flex min-h-screen bg-background text-foreground">
          <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3 py-4 text-sidebar-foreground max-[1000px]:w-48">
            <div className="mb-6 flex items-center gap-2.5 px-2">
              <Logo />
              <div className="min-w-0 leading-tight">
                <div className="text-sm font-semibold text-foreground">Shadow Filer</div>
                <div className="truncate text-xs text-muted-foreground" title={org}>{org || "fleet"}</div>
              </div>
            </div>
            <nav aria-label="Main" className="space-y-0.5">
              {NAV.map(({ path: p, label, icon: Icon }) => {
                const active = section === p;
                return (
                  <a key={p} href={`#${p}`} aria-current={active ? "page" : undefined}
                    className={cn("flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                      active ? "bg-sidebar-accent font-medium text-foreground" : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground")}>
                    <Icon className="size-4" aria-hidden /><span className="flex-1">{label}</span>
                  </a>
                );
              })}
            </nav>
            <div className="mt-auto px-2 text-xs leading-relaxed text-muted-foreground">
              Judged on the server from what each PC reports. Nothing here can change a PC.
            </div>
          </aside>
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-20 flex h-12 items-center gap-3 border-b bg-background/85 px-6 backdrop-blur">
              <span className="text-sm text-muted-foreground">Fleet console{org && <> · <span className="font-medium text-foreground">{org}</span></>}</span>
              <div className="ml-auto flex items-center gap-1">
                <Button variant="ghost" size="sm" onClick={() => setKey(null)}><LogOut />Close</Button>
                <Button variant="ghost" size="icon" onClick={toggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>{dark ? <Sun /> : <Moon />}</Button>
              </div>
            </header>
            <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8 fade-in" key={section + (parts[1] ?? "")}>{page}</main>
          </div>
        </div>
      )}
      <Toaster position="top-center" offset={{ top: 60 }} theme={dark ? "dark" : "light"} closeButton />
    </TooltipProvider>
  );
}
