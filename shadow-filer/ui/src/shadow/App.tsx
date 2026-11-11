import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import {
  Activity as ActivityIcon, ClipboardCheck, LayoutDashboard, LibraryBig, BellRing, Eye, EyeOff, FlaskConical, Inbox as InboxIcon, Moon, Network as NetworkIcon, RefreshCw, Search as SearchIcon,
  Lock, Settings as SettingsIcon, ShieldAlert, Sparkles, Sun, Trash2, WifiOff,
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
import { Tip } from "./ui";
import { InboxPage } from "./pages/Inbox";
import { DashboardPage } from "./pages/Dashboard";
import { SearchPage } from "./pages/Search";
import { CleanupPage } from "./pages/Cleanup";
import { WatchPage } from "./pages/Watch";
import { SecurityPage } from "./pages/Security";
import { NetworkPage } from "./pages/Network";
import { CompliancePage } from "./pages/Compliance";
import { LibraryPage } from "./pages/Library";
import { ActivityPage } from "./pages/Activity";
import { SettingsPage } from "./pages/Settings";
import { ChangelogPage } from "./pages/Changelog";
import { APP } from "@/version";

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

type NavItem = { path: string; label: string; icon: typeof InboxIcon };
const GROUPS: { name: string | null; items: NavItem[] }[] = [
  { name: null, items: [{ path: "/dashboard", label: "Today", icon: LayoutDashboard }] },
  { name: "Files", items: [
    { path: "/inbox", label: "Inbox", icon: InboxIcon },
    { path: "/search", label: "Search", icon: SearchIcon },
    { path: "/cleanup", label: "Cleanup", icon: Trash2 },
    { path: "/watch", label: "Watch", icon: BellRing },
    { path: "/library", label: "Library", icon: LibraryBig },
  ] },
  { name: "Protection", items: [
    { path: "/security", label: "Security", icon: ShieldAlert },
    { path: "/network", label: "Network", icon: NetworkIcon },
    { path: "/compliance", label: "Compliance", icon: ClipboardCheck },
  ] },
  { name: "Agent", items: [
    { path: "/activity", label: "Activity", icon: ActivityIcon },
    { path: "/settings", label: "Settings", icon: SettingsIcon },
  ] },
];
const NAV = GROUPS.flatMap((g) => g.items);

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
      <rect x="1" y="1" width="30" height="30" rx="8" className="fill-primary" />
      <path d="M9 12h6l1.6 2H23v8H9z" className="fill-primary-foreground" />
    </svg>
  );
}

const subscribeHash = (cb: () => void) => {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
};
const dashboardHash = () => window.location.hash.replace(/^#/, "") || "/dashboard";

/** Pages laid out edge to edge in panes, as in the design (no page padding). */
const WORKSPACE = new Set(["/inbox", "/security", "/compliance"]);

export default function ShadowApp() {
  const path = useSyncExternalStore(subscribeHash, dashboardHash, () => "/dashboard");
  const requested = "/" + (path.split("/")[1] || "dashboard");
  const section = NAV.some((item) => item.path === requested) || requested === "/changelog" ? requested : "/dashboard";
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
    case "/compliance": page = <CompliancePage />; break;
    case "/library": page = <LibraryPage />; break;
    case "/activity": page = <ActivityPage />; break;
    case "/settings": page = <SettingsPage status={s} />; break;
    case "/changelog": page = <ChangelogPage />; break;
    default: page = <DashboardPage />;
  }

  const counts: Record<string, { n: number; tone: string; label: string } | null> = {
    "/inbox": count.data && count.data.total > 0 ? { n: count.data.total, tone: "bg-primary text-primary-foreground", label: `${count.data.total} files waiting` } : null,
    "/watch": watch.data && watch.data.counts.soon > 0 ? { n: watch.data.counts.soon, tone: "bg-warning text-background", label: `${watch.data.counts.soon} dates coming up` } : null,
    "/security": security.data?.summary
      ? security.data.summary.kev > 0 ? { n: security.data.summary.kev, tone: "bg-destructive text-destructive-foreground", label: `${security.data.summary.kev} flaws used in real attacks` }
        : security.data.summary.apps_affected > 0 ? { n: security.data.summary.apps_affected, tone: "bg-warning text-background", label: `${security.data.summary.apps_affected} programs with known flaws` } : null
      : null,
  };
  const here = NAV.find((n) => n.path === section) ?? NAV[0]!;
  const group = GROUPS.find((g) => g.items.includes(here))?.name;

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex min-h-screen bg-background text-foreground max-[700px]:flex-col">
        <aside className="sticky top-0 z-30 flex h-screen w-[84px] shrink-0 flex-col items-center gap-3 overflow-y-auto border-r border-rail-border bg-rail py-3 text-rail-foreground max-[700px]:h-auto max-[700px]:w-full max-[700px]:flex-row max-[700px]:overflow-x-auto max-[700px]:border-b max-[700px]:border-r-0 max-[700px]:px-2 max-[700px]:py-1.5">
          <a href="#/dashboard" onClick={(e) => go(e, "/dashboard")} className="shrink-0 rounded-lg" aria-label="Shadow Filer: Today"><Logo /></a>
          <nav aria-label="Main" className="flex flex-col items-center gap-1 max-[700px]:flex-row">
            {GROUPS.map((g, gi) => (
              <div key={gi} className="contents">
                {gi > 0 && <span aria-hidden className="my-1.5 h-px w-9 shrink-0 bg-rail-border max-[700px]:mx-1 max-[700px]:h-8 max-[700px]:w-px" />}
                {g.items.map(({ path: p, label, icon: Icon }) => {
                  const active = section === p;
                  const badge = counts[p];
                  return (
                    <a
                      key={p}
                      href={`#${p}`}
                      onClick={(e) => go(e, p)}
                      aria-current={active ? "page" : undefined}
                      aria-label={badge ? `${label}, ${badge.label}` : undefined}
                      className={cn(
                        "relative flex min-h-[52px] w-[68px] shrink-0 flex-col items-center justify-center gap-1 rounded-lg text-[10.5px] font-medium leading-none transition-colors",
                        active ? "bg-rail-active text-rail-active-foreground ring-1 ring-inset ring-white/10" : "text-rail-foreground hover:bg-rail-active/60 hover:text-rail-active-foreground",
                      )}
                    >
                      <Icon className="size-[18px]" aria-hidden />
                      <span>{label}</span>
                      {badge && <span aria-hidden className={cn("absolute right-1.5 top-1 min-w-4 rounded-full px-1 text-center font-mono text-[10px] font-bold leading-4 tabular", badge.tone)}>{badge.n}</span>}
                    </a>
                  );
                })}
              </div>
            ))}
          </nav>
          <div className="mt-auto flex flex-col items-center gap-1 pb-1 max-[700px]:ml-auto max-[700px]:mt-0 max-[700px]:flex-row max-[700px]:pb-0">
            <Button variant="ghost" size="icon" onClick={toggle} className="text-rail-foreground hover:bg-rail-active hover:text-rail-active-foreground" aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
              {dark ? <Sun /> : <Moon />}
            </Button>
            {/* the release and the build, so a screenshot says which one it was; opens the changelog */}
            <a href="#/changelog" onClick={(e) => go(e, "/changelog")} title={`${APP.label}${APP.builtAt ? ` — built ${new Date(APP.builtAt).toLocaleString()}` : ""}. What changed: Changelog.`}
              className="font-mono text-[10px] tabular-nums text-rail-foreground/70 hover:text-rail-active-foreground hover:underline">v{APP.version}</a>
          </div>
        </aside>

        <div className="flex min-h-screen min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-20 flex flex-wrap items-center gap-x-4 gap-y-2 border-b bg-sidebar px-6 py-2.5">
            <span className="font-mono text-xs text-muted-foreground">
              this PC{group && <><span className="px-1 opacity-50">/</span>{group.toLowerCase()}</>}<span className="px-1 opacity-50">/</span><span className="text-foreground">{here.label.toLowerCase()}</span>
            </span>
            {section !== "/search" && <TopSearch />}
            <div className="ml-auto flex flex-wrap items-center gap-1.5">
              <StatusChips s={s} reachable={conn.reachable} />
              {s?.restart_needed && (
                <a href="#/settings" onClick={(e) => go(e, "/settings")}>
                  <Badge variant="warning" className="cursor-pointer"><RefreshCw className="size-3" /> Restart needed</Badge>
                </a>
              )}
              {mock && <DemoMenu onChange={() => { status.reload(); count.reload(); }} />}
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

          <main className={cn("flex min-w-0 flex-1 flex-col fade-in", !WORKSPACE.has(section) && "px-6 py-5")} key={section}>{page}</main>
        </div>
      </div>
      <Toaster position="top-center" offset={{ top: 60 }} theme={dark ? "dark" : "light"} closeButton />
    </TooltipProvider>
  );
}

/** The search box in the top bar: Ctrl K (or /) focuses it, Enter opens Search with the words typed. */
function TopSearch() {
  const ref = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
      if ((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing)) { e.preventDefault(); ref.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    try { sessionStorage.setItem("sf-q", q.trim()); } catch { /* ignore */ }
    window.location.hash = "#/search";
  };
  return (
    <form role="search" onSubmit={submit} className="mx-auto flex h-9 w-full min-w-[220px] max-w-md flex-1 items-center gap-2 rounded-lg border bg-background px-3 text-muted-foreground focus-within:ring-2 focus-within:ring-ring">
      <SearchIcon className="size-4 shrink-0" aria-hidden />
      <input ref={ref} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search your files" placeholder="Search your files by what they are about"
        className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground" />
      <kbd className="rounded border px-1.5 font-mono text-[11px]">Ctrl K</kbd>
    </form>
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

function StatusChips({ s, reachable }: { s: Status | null; reachable: boolean }) {
  const chip = "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[11px] text-muted-foreground";
  if (!s) return <span className={chip}>connecting…</span>;
  const watching = reachable && s.watching;
  const modelReady = s.ollama && !s.model_missing;
  return (
    <>
      <Tip tip={s.inbox[0] ? `Watching ${s.inbox.join(", ")}` : undefined}>
        <span className={chip} tabIndex={0}><span className={cn("size-1.5 rounded-full", watching ? "bg-success" : "bg-warning")} aria-hidden />{watching ? "watching" : "not watching"}</span>
      </Tip>
      <span className={cn(chip, !modelReady && "border-warning/40 text-warning")}>{s.model} {modelReady ? "ready" : "not ready"}</span>
      <Tip tip="Your files are read on this PC. Nothing about them leaves it.">
        <span className={cn(chip, "border-primary/30 bg-info-soft text-accent-foreground")} tabIndex={0}><Lock className="size-3" aria-hidden />local only</span>
      </Tip>
    </>
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
