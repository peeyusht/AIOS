/* The fleet server's console: every enrolled PC of one organisation, judged on the server. Same components
   and styles as the PC's own console (src/shadow), a different shell and its own pages. */
import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { ClipboardCheck, LayoutDashboard, LogOut, MonitorSmartphone, Moon, Package, Sun, Users } from "lucide-react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Spin } from "@/shadow/ui";
import { refreshMe, ROLE_LABEL, signOut, useSession } from "./session";
import { OverviewPage } from "./pages/Overview";
import { DevicesPage } from "./pages/Devices";
import { DevicePage } from "./pages/Device";
import { SoftwarePage } from "./pages/Software";
import { EvidencePage } from "./pages/Evidence";
import { AccessPage } from "./pages/Access";
import { SharedPage } from "./pages/Shared";
import { Logo, SetPassword, SignIn } from "./pages/SignIn";

const NAV = [
  { path: "/overview", label: "Overview", icon: LayoutDashboard },
  { path: "/devices", label: "Devices", icon: MonitorSmartphone },
  { path: "/software", label: "Software", icon: Package },
  { path: "/evidence", label: "Evidence", icon: ClipboardCheck },
  { path: "/access", label: "Access", icon: Users },
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

const subscribe = (cb: () => void) => {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
};
const hash = () => window.location.hash.replace(/^#/, "") || "/overview";

function Shell({ path }: { path: string }) {
  const { me } = useSession();
  const { dark, toggle } = useTheme();
  const parts = path.split("/").filter(Boolean);
  const section = NAV.some((n) => n.path === "/" + parts[0]) ? "/" + parts[0] : "/overview";
  let page: ReactNode;
  if (section === "/devices") page = parts[1] ? <DevicePage id={parts[1]} tab={parts[2]} key={parts[1]} /> : <DevicesPage />;
  else if (section === "/software") page = <SoftwarePage />;
  else if (section === "/evidence") page = <EvidencePage />;
  else if (section === "/access") page = <AccessPage />;
  else page = <OverviewPage />;
  return (
    <>
      <div className="flex min-h-screen bg-background text-foreground">
        <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3 py-4 text-sidebar-foreground max-[1000px]:w-48">
          <div className="mb-6 flex items-center gap-2.5 px-2">
            <Logo />
            <div className="min-w-0 leading-tight">
              <div className="text-sm font-semibold text-foreground">Shadow Filer</div>
              <div className="truncate text-xs text-muted-foreground" title={me?.organisation}>{me?.organisation || "fleet"}</div>
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
            <span className="text-sm text-muted-foreground">Fleet console{me?.organisation && <> · <span className="font-medium text-foreground">{me.organisation}</span></>}</span>
            <div className="ml-auto flex items-center gap-2">
              <span className="hidden text-sm text-muted-foreground min-[900px]:inline">{me?.name || me?.email}</span>
              {me?.role && <Badge variant="muted">{ROLE_LABEL[me.role]}</Badge>}
              <Button variant="ghost" size="sm" onClick={() => void signOut()}><LogOut />Sign out</Button>
              <Button variant="ghost" size="icon" onClick={toggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>{dark ? <Sun /> : <Moon />}</Button>
            </div>
          </header>
          <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8 fade-in" key={section + (parts[1] ?? "")}>{page}</main>
        </div>
      </div>
      <Toaster position="top-center" offset={{ top: 60 }} theme={dark ? "dark" : "light"} closeButton />
    </>
  );
}

export default function FleetApp() {
  const path = useSyncExternalStore(subscribe, hash, () => "/overview");
  const session = useSession();
  const parts = path.split("/").filter(Boolean);
  const outside = parts[0] === "share" || parts[0] === "setup";       // pages that need no account
  useEffect(() => { if (!outside) void refreshMe(); }, [outside]);

  let view: ReactNode;
  if (parts[0] === "share" && parts[1]) view = <SharedPage token={parts[1]} key={parts[1]} />;
  else if (parts[0] === "setup" && parts[1]) view = <SetPassword token={parts[1]} key={parts[1]} />;
  else if (!session.loaded) view = <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground"><Spin /></div>;
  else if (session.me?.stage === "ok") return <TooltipProvider delayDuration={300}><Shell path={path} /></TooltipProvider>;
  else view = <SignIn stage={session.me?.stage ?? null} />;
  return <TooltipProvider delayDuration={300}>{view}<Toaster position="top-center" closeButton /></TooltipProvider>;
}
