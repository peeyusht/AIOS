import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import {
  Activity as ActivityIcon, LayoutDashboard, LibraryBig, BellRing, Eye, EyeOff, FlaskConical, Inbox as InboxIcon, Moon, Network as NetworkIcon, RefreshCw, Search as SearchIcon,
  Settings as SettingsIcon, ShieldAlert, Sparkles, Sun, Trash2, WifiOff,
} from "lucide-react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { api, isMock, onConnection } from "@/lib/api";
import { usePoll, navigationGuard } from "@/lib/hooks";
import type { Status } from "@/lib/types";
import { InboxPage } from "./pages/Inbox";
import { DashboardPage } from "./pages/Dashboard";
import { SearchPage } from "./pages/Search";
import { CleanupPage } from "./pages/Cleanup";
import { WatchPage } from "./pages/Watch";
import { SecurityPage } from "./pages/Security";
import { NetworkPage } from "./pages/Network";
import { LibraryPage } from "./pages/Library";
import { ActivityPage } from "./pages/Activity";
import { SettingsPage } from "./pages/Settings";

export const INBOX_CHANGED = "sf-inbox-changed";
export const WATCH_CHANGED = "sf-watch-changed";
export const emitWatchChanged = () => window.dispatchEvent(new Event(WATCH_CHANGED));
export const SECURITY_CHANGED = "sf-security-changed";
export const emitSecurityChanged = () => window.dispatchEvent(new Event(SECURITY_CHANGED));
export const emitInboxChanged = () => window.dispatchEvent(new Event(INBOX_CHANGED));

function useTheme() {
  const [dark, setDark] = useState(() => {
    let t: string | null = null;
    try { t = localStorage.getItem("sf-theme"); } catch { /* ignore */ }
    return t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useEffect(() => { document.documentElement.classList.toggle("dark", dark); }, [dark]);
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("sf-theme", next ? "dark" : "light"); } catch { /* ignore */ }
  };
  return { dark, toggle };
}

const NAV = [
  { path: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { path: "/inbox", label: "Inbox", icon: InboxIcon },
  { path: "/search", label: "Search", icon: SearchIcon },
  { path: "/cleanup", label: "Cleanup", icon: Trash2 },
  { path: "/watch", label: "Watch", icon: BellRing },
  { path: "/security", label: "Security", icon: ShieldAlert },
  { path: "/network", label: "Network", icon: NetworkIcon },
  { path: "/library", label: "Library", icon: LibraryBig },
  { path: "/activity", label: "Activity", icon: ActivityIcon },
  { path: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

function Logo() {
  return (
    <svg viewBox="0 0 24 24" className="size-7" aria-hidden>
      <rect x="2" y="2" width="20" height="20" rx="6" className="fill-primary" />
      <path d="M7 9.5h4l1.2 1.5H17v6H7z" className="fill-primary-foreground" opacity=".95" />
      <path d="M8.5 13.5h7" className="stroke-primary" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

const subscribeHash = (cb: () => void) => {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
};
const dashboardHash = () => window.location.hash.replace(/^#/, "") || "/dashboard";

export default function ShadowApp() {
  const path = useSyncExternalStore(subscribeHash, dashboardHash, () => "/dashboard");
  const requested = "/" + (path.split("/")[1] || "dashboard");
  const section = NAV.some((item) => item.path === requested) ? requested : "/dashboard";
  const { dark, toggle } = useTheme();
  const mock = isMock();
  const [conn, setConn] = useState({ reachable: true, stale: false });
  useEffect(() => onConnection((c) => setConn({ ...c })), []);
  const status = usePoll<Status>(api.status, conn.reachable ? 10_000 : 3_000);
  const count = usePoll(() => api.inbox(0, 1), 30_000);
  const watch = usePoll(() => api.watch(), 300_000);
  useEffect(() => {
    const h = () => watch.reload();
    window.addEventListener(WATCH_CHANGED, h);
    return () => window.removeEventListener(WATCH_CHANGED, h);
  }, [watch]);
  const security = usePoll(() => api.security(true), 300_000);
  useEffect(() => {
    const h = () => security.reload();
    window.addEventListener(SECURITY_CHANGED, h);
    return () => window.removeEventListener(SECURITY_CHANGED, h);
  }, [security]);
  useEffect(() => {
    const h = () => count.reload();
    window.addEventListener(INBOX_CHANGED, h);
    return () => window.removeEventListener(INBOX_CHANGED, h);
  }, [count]);

  // guard against leaving settings with unsaved changes via in-app nav
  const go = (e: React.MouseEvent, to: string) => {
    if (navigationGuard && !navigationGuard()) e.preventDefault();
    else if (to === path) e.preventDefault();
  };

  const s = status.data;
  let page: ReactNode;
  switch (section) {
    case "/inbox": page = <InboxPage />; break;
    case "/search": page = <SearchPage />; break;
    case "/cleanup": page = <CleanupPage />; break;
    case "/watch": page = <WatchPage />; break;
    case "/security": page = <SecurityPage />; break;
    case "/network": page = <NetworkPage />; break;
    case "/library": page = <LibraryPage />; break;
    case "/activity": page = <ActivityPage />; break;
    case "/settings": page = <SettingsPage status={s} />; break;
    default: page = <DashboardPage />;
  }

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex min-h-screen bg-background text-foreground">
        <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3 py-4 text-sidebar-foreground max-[1000px]:w-48">
          <div className="mb-6 flex items-center gap-2.5 px-2">
            <Logo />
            <div className="leading-tight">
              <div className="text-sm font-semibold text-foreground">Shadow Filer</div>
              <div className="text-xs text-muted-foreground">on this PC</div>
            </div>
          </div>
          <nav aria-label="Main" className="space-y-0.5">
            {NAV.map(({ path: p, label, icon: Icon }) => {
              const active = section === p;
              return (
                <a
                  key={p}
                  href={`#${p}`}
                  onClick={(e) => go(e, p)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                    active ? "bg-sidebar-accent font-medium text-foreground" : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
                  )}
                >
                  <Icon className="size-4" aria-hidden />
                  <span className="flex-1">{label}</span>
                  {p === "/inbox" && count.data && count.data.total > 0 && (
                    <span className="rounded-full bg-primary px-1.5 text-[11px] font-semibold leading-5 text-primary-foreground tabular" aria-label={`${count.data.total} files waiting`}>
                      {count.data.total}
                    </span>
                  )}
                  {p === "/watch" && watch.data && watch.data.counts.soon > 0 && (
                    <span className="rounded-full bg-warning-soft px-1.5 text-[11px] font-semibold leading-5 text-warning ring-1 ring-warning/30 tabular" aria-label={`${watch.data.counts.soon} dates coming up`}>
                      {watch.data.counts.soon}
                    </span>
                  )}
                  {p === "/security" && security.data?.summary && security.data.summary.kev > 0 && (
                    <span className="rounded-full bg-danger-soft px-1.5 text-[11px] font-semibold leading-5 text-destructive ring-1 ring-destructive/30 tabular" aria-label={`${security.data.summary.kev} flaws used in real attacks`}>
                      {security.data.summary.kev}
                    </span>
                  )}
                  {p === "/security" && security.data?.summary && security.data.summary.kev === 0 && security.data.summary.apps_affected > 0 && (
                    <span className="rounded-full bg-warning-soft px-1.5 text-[11px] font-semibold leading-5 text-warning ring-1 ring-warning/30 tabular" aria-label={`${security.data.summary.apps_affected} programs with known flaws`}>
                      {security.data.summary.apps_affected}
                    </span>
                  )}
                </a>
              );
            })}
          </nav>
          <div className="mt-auto px-2 text-xs leading-relaxed text-muted-foreground">
            Runs only on this computer. Nothing leaves it.
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 flex h-12 items-center gap-3 border-b bg-background/85 px-6 backdrop-blur">
            <StatusLine s={s} reachable={conn.reachable} />
            <div className="ml-auto flex items-center gap-2">
              {s?.restart_needed && (
                <a href="#/settings" onClick={(e) => go(e, "/settings")}>
                  <Badge variant="warning" className="cursor-pointer"><RefreshCw className="size-3" /> Restart needed</Badge>
                </a>
              )}
              {mock && <DemoMenu onChange={() => { status.reload(); count.reload(); }} />}
              <Button variant="ghost" size="icon" onClick={toggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
                {dark ? <Sun /> : <Moon />}
              </Button>
            </div>
          </header>

          <div className="space-y-2 px-6 pt-4 empty:hidden">
            {conn.stale && (
              <Banner tone="danger">
                This page is out of date. Reload.
                <Button size="sm" variant="outline" className="ml-3" onClick={() => location.reload()}>Reload</Button>
              </Banner>
            )}
            {!conn.reachable && (
              <Banner tone="danger" icon={<WifiOff />}>Agent not reachable, retrying…</Banner>
            )}
            {conn.reachable && s?.problem && <Banner tone="danger">{s.problem}</Banner>}
            {conn.reachable && s && s.ollama === false && (
              <Banner tone="warn">Ollama isn't answering, so the model can't suggest folders right now. Rules and similar-document suggestions still work.</Banner>
            )}
            {conn.reachable && s?.model_missing && (
              <Banner tone="warn">
                The model <span className="path">{s.model}</span> is not installed. Run <span className="path">ollama pull {s.model}</span> in a terminal.
              </Banner>
            )}
          </div>

          <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8 fade-in" key={section}>{page}</main>
        </div>
      </div>
      <Toaster position="top-center" offset={{ top: 60 }} theme={dark ? "dark" : "light"} closeButton />
    </TooltipProvider>
  );
}

function Banner({ tone, icon, children }: { tone: "danger" | "warn"; icon?: ReactNode; children: ReactNode }) {
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn(
      "flex items-center gap-2 rounded-lg border px-4 py-2 text-sm [&_svg]:size-4",
      tone === "danger" ? "border-destructive/30 bg-danger-soft [&>svg]:text-destructive" : "border-warning/30 bg-warning-soft [&>svg]:text-warning",
    )}>
      {icon ?? <Sparkles aria-hidden />}
      <div className="flex flex-1 flex-wrap items-center">{children}</div>
    </div>
  );
}

function StatusLine({ s, reachable }: { s: Status | null; reachable: boolean }) {
  if (!s) return <span className="text-sm text-muted-foreground">Connecting to the agent…</span>;
  const watching = reachable && s.watching;
  const modelReady = s.ollama && !s.model_missing;
  return (
    <div className="flex min-w-0 items-center gap-4 text-sm">
      <span className="flex items-center gap-2">
        <span className={cn("size-2 rounded-full", watching ? "bg-success" : "bg-warning")} aria-hidden />
        <span className="font-medium">{watching ? "Watching" : "Not watching"}</span>
        {watching && s.inbox[0] && <span className="path hidden text-muted-foreground xl:inline">{s.inbox[0]}</span>}
      </span>
      <span className="flex items-center gap-1.5 text-muted-foreground">
        Model <span className="path text-foreground">{s.model}</span>
        <Badge variant={modelReady ? "success" : "warning"}>{modelReady ? "ready" : "not ready"}</Badge>
      </span>
    </div>
  );
}

function DemoMenu({ onChange }: { onChange: () => void }) {
  const [, force] = useState(0);
  const [demo, setDemo] = useState<typeof import("@/lib/mock").demo | null>(null);
  useEffect(() => { import("@/lib/mock").then((m) => setDemo(m.demo)); }, []);
  if (!demo) return null;
  const flip = (k: keyof typeof demo) => {
    demo[k] = !demo[k];
    force((n) => n + 1);
    onChange();
    window.dispatchEvent(new Event(INBOX_CHANGED));
    window.dispatchEvent(new Event("sf-demo-changed"));
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="rounded-full focus-visible:outline-2" aria-label="Demo data options">
          <Badge variant="info" className="cursor-pointer"><FlaskConical className="size-3" /> Demo data</Badge>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Fictional data. Simulate states:
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuCheckboxItem checked={demo.unreachable} onCheckedChange={() => flip("unreachable")}>Agent unreachable</DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={demo.emptyInbox} onCheckedChange={() => flip("emptyInbox")}>
          {demo.emptyInbox ? <EyeOff className="mr-1 size-3.5" /> : <Eye className="mr-1 size-3.5" />} Empty inbox
        </DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={demo.problem} onCheckedChange={() => flip("problem")}>Watcher problem</DropdownMenuCheckboxItem>
        <DropdownMenuCheckboxItem checked={demo.modelMissing} onCheckedChange={() => flip("modelMissing")}>Model missing / Ollama down</DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
