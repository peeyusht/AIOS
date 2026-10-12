import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, Copy, EyeOff, File as FileIcon, Folder, FolderSearch, LibraryBig, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { bytes, dateTime, when } from "@/lib/format";
import type { AppChange, InstalledApp, LibraryApplications, LibraryInstaller, LibraryKind, LibraryResponse, LibrarySrc } from "@/lib/types";
import { Input } from "@/components/ui/input";
import { Card, EmptyState, ListSkeleton, LoadError, Notice, PageHeader, Segmented, Spin, act } from "../ui";

const LEVEL: Record<LibraryInstaller["level"], { label: string; v: "success" | "warning" | "danger" | "muted" }> = {
  signed: { label: "Signed", v: "success" },
  unsigned: { label: "Not signed", v: "warning" },
  untrusted: { label: "Not trusted", v: "warning" },
  tampered: { label: "Changed after signing", v: "danger" },
  unknown: { label: "Unknown", v: "muted" },
};

const SrcBadge = ({ s }: { s: LibrarySrc }) =>
  s === "inbox" ? <Badge variant="warning">Downloads</Badge> : <Badge variant="success">Filed</Badge>;

const cap = (s: string) => (s ? s[0]!.toUpperCase() + s.slice(1) : s);

export function LibraryPage() {
  const [running, setRunning] = useState(false);
  const q = usePoll<LibraryResponse>(() => api.library(), running ? 2000 : 300_000);
  const d = q.data;
  const wasRunning = useRef(false);
  useEffect(() => {
    const r = !!d?.runner.running;
    setRunning(r);
    if (wasRunning.current && !r) void q.reload();
    wasRunning.current = r;
  }, [d?.runner.running]); // eslint-disable-line react-hooks/exhaustive-deps

  const scan = async () => {
    if (await act(() => api.libraryScan())) { setRunning(true); await q.reload(); }
  };
  const checkUpdates = async () => {
    if (await act(() => api.libraryCheckUpdates())) { setRunning(true); await q.reload(); }
  };
  const reveal = (path: string) => void act(() => api.libraryReveal(path));
  const hide = async (kind: LibraryKind, key: string) => {
    if (!(await act(() => api.libraryDismiss(kind, key)))) return;
    await q.reload();
    toast("Hidden", {
      action: { label: "Undo", onClick: async () => { if (await act(() => api.libraryDismiss(kind, key, true))) await q.reload(); } },
    });
  };
  const restore = async () => { if (await act(() => api.libraryRestore())) await q.reload(); };

  const isRunning = !!d?.runner.running;
  const scanBtn = (
    <Button variant="outline" onClick={scan} disabled={isRunning}>{isRunning ? <Spin /> : <RefreshCw />} Scan now</Button>
  );

  return (
    <div>
      <PageHeader
        title="Library"
        sub={
          <>
            What you already hold: firmware and VM images, versions of documents, look-alike pictures, who signed your installers, and the applications on this PC.
            <span className="block">Read-only. Nothing here moves or deletes a file.</span>
          </>
        }
        actions={
          d && d.enabled ? (
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">
                {isRunning
                  ? <span className="inline-flex items-center gap-1.5 [&_svg]:size-3.5"><Spin /> {d.runner.progress ?? "Scanning…"}</span>
                  : d.scanned_at && <>Scanned {when(d.scanned_at)} · {(d.files ?? 0).toLocaleString()} files</>}
              </span>
              {scanBtn}
            </div>
          ) : undefined
        }
      />
      {q.error && !d && <LoadError error={q.error} onRetry={q.reload} />}
      {!d && !q.error && <ListSkeleton rows={4} />}
      {d && !d.enabled && (
        <EmptyState icon={<LibraryBig />} title="The library is switched off">
          Turn it on in <a href="#/settings" className="text-primary underline-offset-4 hover:underline">Settings › Library</a>.
        </EmptyState>
      )}
      {d && d.enabled && d.runner.error && <Notice tone="danger" className="mb-4">{d.runner.error}</Notice>}
      {d && d.enabled && !d.scanned_at && !isRunning && (
        <EmptyState icon={<LibraryBig />} title="No scan yet"><div className="mt-3">{scanBtn}</div></EmptyState>
      )}
      {d && d.enabled && (d.scanned_at || isRunning) && (
        <Tabs defaultValue="images">
          <TabsList className="mb-6">
            {([["images", "Images"], ["versions", "Versions"], ["similar", "Pictures"], ["installers", "Installers"]] as const).map(([k, l]) => (
              <TabsTrigger key={k} value={k}>{l}<span className="ml-1.5 tabular text-muted-foreground">{d.counts[k] ?? 0}</span></TabsTrigger>
            ))}
            <TabsTrigger value="applications">Applications<span className="ml-1.5 tabular text-muted-foreground">{d.applications?.counts.desktop ?? 0}</span></TabsTrigger>
          </TabsList>
          <TabsContent value="images"><Images d={d} reveal={reveal} hide={hide} /></TabsContent>
          <TabsContent value="versions"><Versions d={d} reveal={reveal} hide={hide} /></TabsContent>
          <TabsContent value="similar"><Pictures d={d} reveal={reveal} hide={hide} /></TabsContent>
          <TabsContent value="installers"><Installers d={d} reveal={reveal} hide={hide} /></TabsContent>
          <TabsContent value="applications"><Applications a={d.applications ?? null} checkNow={checkUpdates} isRunning={isRunning} /></TabsContent>
        </Tabs>
      )}
      {d && d.dismissed > 0 && (
        <p className="mt-8 text-sm text-muted-foreground">
          {d.dismissed} hidden · <button className="text-primary underline-offset-4 hover:underline" onClick={restore}>Show them again</button>
        </p>
      )}
    </div>
  );
}

type P = { d: LibraryResponse; reveal: (p: string) => void; hide: (k: LibraryKind, key: string) => void };

const Strip = ({ children, warn }: { children: ReactNode; warn?: ReactNode }) => (
  <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
    <span className="text-muted-foreground">{children}</span>
    {warn && <span className="rounded-md bg-warning-soft px-2 py-0.5 text-warning">{warn}</span>}
  </div>
);
const ShowBtn = ({ path, reveal }: { path: string; reveal: (p: string) => void }) => (
  <Button variant="ghost" size="sm" onClick={() => reveal(path)}><FolderSearch /> Show</Button>
);
const HideBtn = ({ onClick }: { onClick: () => void }) => (
  <Button variant="ghost" size="sm" onClick={onClick}><EyeOff /> Hide</Button>
);
const Row = ({ children }: { children: ReactNode }) => (
  <div className="flex items-center gap-3 border-t py-2 text-sm first:border-t-0">{children}</div>
);
const Name = ({ name, path, className }: { name: string; path: string; className?: string }) => (
  <span className={cn("path min-w-0 flex-1 truncate", className)} title={path}>{name}</span>
);
const Muted = ({ children, className }: { children: ReactNode; className?: string }) => (
  <span className={cn("shrink-0 text-muted-foreground tabular", className)}>{children}</span>
);

function Images({ d, reveal, hide }: P) {
  if (!d.images.length) return <EmptyState icon={<LibraryBig />} title="No firmware, OS or VM images found." />;
  return (
    <div>
      <Strip warn={d.summary.images_in_downloads_bytes > 0 && `${bytes(d.summary.images_in_downloads_bytes)} of this is still in Downloads`}>
        {d.images.length} {d.images.length === 1 ? "product" : "products"} · {bytes(d.summary.images_bytes)}
      </Strip>
      <div className="space-y-3">
        {d.images.map((p) => (
          <Card key={p.key} className="p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="font-semibold">{p.product}</span>
              {p.versions.map((v, i) => <Badge key={v} variant={i === 0 ? "info" : "muted"}>{v}</Badge>)}
              <span className="ml-auto text-sm text-muted-foreground tabular">{bytes(p.size)}</span>
              <HideBtn onClick={() => hide("images", p.key)} />
            </div>
            {p.items.map((it) => (
              <Row key={it.path}>
                <span className="shrink-0 text-muted-foreground [&_svg]:size-4">{it.is_dir ? <Folder /> : <FileIcon />}</span>
                <Name name={it.name} path={it.path} />
                {it.version && <Muted>{it.version}{it.build && ` · build ${it.build}`}</Muted>}
                {it.is_dir && <Muted>{it.files} files</Muted>}
                <Muted className="w-16 text-right">{bytes(it.size)}</Muted>
                <SrcBadge s={it.source} />
                <Muted className="w-28">{dateTime(it.modified)}</Muted>
                <ShowBtn path={it.path} reveal={reveal} />
              </Row>
            ))}
          </Card>
        ))}
      </div>
    </div>
  );
}

function Versions({ d, reveal, hide }: P) {
  const [f, setF] = useState<"all" | "versions" | "same-name">("all");
  if (!d.versions.length) return <EmptyState icon={<LibraryBig />} title="No documents with several versions." />;
  const list = d.versions.filter((c) => f === "all" || c.kind === f);
  return (
    <div>
      <Strip warn={d.summary.filed_is_older > 0 && `${d.summary.filed_is_older} where the copy you filed is older than one in Downloads`}>
        {d.versions.length} {d.versions.length === 1 ? "document" : "documents"} with more than one version
      </Strip>
      <div className="mb-4">
        <Segmented label="Kind" value={f} onChange={setF} options={[{ value: "all", label: "All" }, { value: "versions", label: "Versions" }, { value: "same-name", label: "Same name" }]} />
        {f === "same-name" && <p className="mt-2 text-sm text-muted-foreground">Same name, different content: often different documents that were downloaded under one name.</p>}
      </div>
      <div className="space-y-3">
        {list.map((c) => (
          <Card key={c.key} className="p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="font-semibold">{cap(c.title)}</span>
              <Badge variant="muted" className="path">{c.ext}</Badge>
              {c.filed_is_older && <Badge variant="warning">Filed copy is older</Badge>}
              <span className="ml-auto text-sm text-muted-foreground">{c.members.length} copies</span>
              <HideBtn onClick={() => hide("versions", c.key)} />
            </div>
            {[...c.members].sort((a, b) => (b.modified ?? "").localeCompare(a.modified ?? "")).map((m) => (
              <Row key={m.path}>
                <Name name={m.name} path={m.path} className="flex-none max-w-[30%]" />
                {m.label && <Badge variant="muted">{m.label}</Badge>}
                {m.newest && <Badge variant="success">Newest</Badge>}
                <Muted className="w-16 text-right">{bytes(m.size)}</Muted>
                <Muted className="w-28">{dateTime(m.modified)}</Muted>
                <SrcBadge s={m.source} />
                <span className="path min-w-0 flex-1 truncate text-muted-foreground" title={m.folder}>{m.folder}</span>
                <ShowBtn path={m.path} reveal={reveal} />
              </Row>
            ))}
          </Card>
        ))}
      </div>
    </div>
  );
}

function Pictures({ d, reveal, hide }: P) {
  if (!d.similar.length) return <EmptyState icon={<LibraryBig />} title="No look-alike pictures found." />;
  return (
    <div>
      <Strip>{d.similar.length} {d.similar.length === 1 ? "group" : "groups"} of pictures that look the same</Strip>
      <div className="space-y-3">
        {d.similar.map((g) => (
          <Card key={g.key} className="p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="font-semibold">{g.members.length} pictures</span>
              {g.identical ? <Badge variant="info">Same size: probably exact copies</Badge> : <Badge variant="muted">Resized or re-saved</Badge>}
              <span className="ml-auto" />
              <HideBtn onClick={() => hide("similar", g.key)} />
            </div>
            {g.members.map((m) => (
              <Row key={m.path}>
                <Name name={m.name} path={m.path} className="flex-none max-w-[30%]" />
                <Muted>{m.w} × {m.h}</Muted>
                <Muted className="w-16 text-right">{bytes(m.size)}</Muted>
                <SrcBadge s={m.source} />
                <span className="path min-w-0 flex-1 truncate text-muted-foreground" title={m.folder}>{m.folder}</span>
                <ShowBtn path={m.path} reveal={reveal} />
              </Row>
            ))}
          </Card>
        ))}
      </div>
    </div>
  );
}

function Installers({ d, reveal, hide }: P) {
  return (
    <div>
      {d.signatures_checked === false && <Notice className="mb-4">Signature checks are switched off or not available on this system.</Notice>}
      {!d.installers.length ? (
        <EmptyState icon={<LibraryBig />} title="No programs or installers found." />
      ) : (
        <>
          <Strip warn={d.summary.not_signed > 0 && `${d.summary.not_signed} without a publisher Windows can vouch for`}>
            {d.installers.length === 1 ? "1 program or installer" : `${d.installers.length} programs and installers`}
          </Strip>
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="px-4 py-2 font-medium">File</th>
                  <th className="px-2 py-2 font-medium">Signature</th>
                  <th className="px-2 py-2 font-medium">Publisher</th>
                  <th className="px-2 py-2 text-right font-medium">Size</th>
                  <th className="px-2 py-2 font-medium">Where</th>
                  <th className="px-4 py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {d.installers.map((x) => (
                  <tr key={x.path} className="border-b align-top last:border-b-0">
                    <td className="max-w-[16rem] px-4 py-3">
                      <div className="path truncate" title={x.path}>{x.name}</div>
                      {x.version && <div className="text-xs text-muted-foreground">version {x.version}</div>}
                      {x.installed_version && (
                        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                          <span>Installed: {x.installed_name} {x.installed_version}</span>
                          {x.file_is === "older" && <Badge variant="warning">This file is older</Badge>}
                          {x.file_is === "same" && <Badge variant="muted">Same version</Badge>}
                          {x.file_is === "newer" && <Badge variant="info">This file is newer</Badge>}
                        </div>
                      )}
                      {x.host && <div className="text-xs text-muted-foreground">from {x.host}</div>}
                    </td>
                    <td className="px-2 py-3">
                      <Badge variant={LEVEL[x.level]?.v ?? "muted"}>{LEVEL[x.level]?.label ?? x.level}</Badge>
                      <div className="mt-1 max-w-xs text-xs text-muted-foreground">{x.text}</div>
                    </td>
                    <td className="px-2 py-3">{x.publisher || "—"}</td>
                    <td className="whitespace-nowrap px-2 py-3 text-right tabular">{bytes(x.size)}</td>
                    <td className="px-2 py-3"><SrcBadge s={x.source} /></td>
                    <td className="whitespace-nowrap px-4 py-2 text-right">
                      <ShowBtn path={x.path} reveal={reveal} />
                      <HideBtn onClick={() => hide("installers", x.path)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}

const EVENT: Record<AppChange["event"], { label: string; v: "success" | "info" | "muted" }> = {
  installed: { label: "Installed", v: "success" },
  updated: { label: "Updated", v: "info" },
  removed: { label: "Removed", v: "muted" },
};
const dayOf = (s: string | null) => {
  if (!s) return "—";
  const d = new Date(s.length === 10 ? s + "T00:00:00" : s);
  return isNaN(d.getTime()) ? s : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
};
function cmpVersion(a: string, b: string) {
  const pa = a.split(/[^0-9a-z]+/i), pb = b.split(/[^0-9a-z]+/i);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? "", y = pb[i] ?? "";
    const nx = Number(x), ny = Number(y);
    const c = x !== "" && y !== "" && !isNaN(nx) && !isNaN(ny) ? nx - ny : x.localeCompare(y, undefined, { numeric: true });
    if (c) return c;
  }
  return 0;
}
type SortKey = "name" | "version" | "available" | "publisher" | "installed" | "size";
const DATE_TITLE = "No install date recorded: this is the day the entry last changed, which moves with every update";

function copyUpgrade(id: string | null | undefined) {
  if (!id) return;
  try {
    void navigator.clipboard?.writeText(`winget upgrade --id ${id}`).then(() => toast.success("Command copied. Paste it into a terminal to update."), () => {});
  } catch { /* fall back silently */ }
}
const CopyCmd = ({ id }: { id: string | null | undefined }) => id ? (
  <Button variant="ghost" size="icon" className="size-7 [&_svg]:size-3.5" aria-label="Copy the update command" title={`winget upgrade --id ${id}`} onClick={() => copyUpgrade(id)}><Copy /></Button>
) : null;

function Applications({ a, checkNow, isRunning }: { a: LibraryApplications | null; checkNow: () => void; isRunning: boolean }) {
  const [text, setText] = useState("");
  const [show, setShow] = useState<"desktop" | "packaged" | "all" | "updates">("desktop");
  const [sort, setSort] = useState<{ k: SortKey; asc: boolean }>({ k: "name", asc: true });
  const [allChanges, setAllChanges] = useState(false);
  if (!a) return (
    <EmptyState icon={<LibraryBig />} title="The applications list is switched off">
      Turn it on in <a href="#/settings" className="text-primary underline-offset-4 hover:underline">Settings › Library</a>.
    </EmptyState>
  );
  if (!a.scanned_at) return <EmptyState icon={<LibraryBig />} title="No list yet">Scan now fills it.</EmptyState>;
  const upd = a.updates?.enabled ? a.updates : null;
  const t = text.trim().toLowerCase();
  const list = a.apps
    .filter((x) => show === "all" || (show === "updates" ? !!(upd && x.available) : x.kind === show))
    .filter((x) => !t || x.name.toLowerCase().includes(t) || x.publisher.toLowerCase().includes(t));
  const val = (x: InstalledApp): string | number | null =>
    sort.k === "size" ? x.size : sort.k === "installed" ? x.installed : sort.k === "version" ? x.version : sort.k === "available" ? (x.available ?? null) : sort.k === "publisher" ? x.publisher : x.name;
  const sorted = [...list].sort((p, q) => {
    const x = val(p), y = val(q);
    const ex = x == null || x === "", ey = y == null || y === "";
    if (ex || ey) return ex === ey ? p.name.localeCompare(q.name) : ex ? 1 : -1; // empty values last
    const c = sort.k === "version" || sort.k === "available" ? cmpVersion(String(x), String(y))
      : typeof x === "number" && typeof y === "number" ? x - y
      : String(x).localeCompare(String(y), undefined, { sensitivity: "base", numeric: true });
    return sort.asc ? c : -c;
  });
  const changes = allChanges ? a.changes : a.changes.slice(0, 8);
  const Th = ({ k, children, right }: { k: SortKey; children: ReactNode; right?: boolean }) => {
    const on = sort.k === k;
    return (
      <th className={cn("px-2 py-2 font-medium first:px-4 last:px-4", right && "text-right")} aria-sort={on ? (sort.asc ? "ascending" : "descending") : "none"}>
        <button className={cn("inline-flex items-center gap-1 hover:text-foreground [&_svg]:size-3", on && "text-foreground")}
          onClick={() => setSort(on ? { k, asc: !sort.asc } : { k, asc: true })}>
          {children}{on && (sort.asc ? <ArrowUp /> : <ArrowDown />)}
        </button>
      </th>
    );
  };
  return (
    <div>
      <Strip warn={(!a.desktop_read || !a.packaged_read) && "Windows could not be asked this time; showing the last list"}>
        {a.counts.desktop} programs · {bytes(a.total_bytes)} for the {a.sized} that state a size · {a.counts.packaged} Store and packaged apps
      </Strip>
      {!upd ? (
        <p className="mb-4 text-sm text-muted-foreground">Checking for newer versions is off. It goes online, so it is switched on in <a href="#/settings" className="text-primary underline-offset-4 hover:underline">Settings › Library</a>.</p>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <span>
              {upd.count === 0 && upd.checked_at ? "Everything winget knows about is up to date" : `${upd.count} with a newer version`}
              {" · "}{upd.checked_at ? `asked ${when(upd.checked_at)}` : "not asked yet"}
            </span>
            <Button variant="outline" size="sm" onClick={checkNow} disabled={isRunning}>{isRunning ? <Spin /> : <RefreshCw />} Check now</Button>
          </div>
          {!upd.ok && (
            <Notice tone="warn" className="mb-4">{upd.error ?? "The last check did not work."}{upd.listed_at ? ` Showing the list from ${when(upd.listed_at)}.` : ""}</Notice>
          )}
        </>
      )}
      {a.changes.length > 0 ? (
        <Card className="mb-4 p-4">
          <div className="mb-2 font-semibold">Changed recently</div>
          {changes.map((c, i) => (
            <Row key={i}>
              <Muted className="w-28">{dayOf(c.ts)}</Muted>
              <Badge variant={EVENT[c.event].v}>{EVENT[c.event].label}</Badge>
              <span className="min-w-0 flex-1 truncate">{c.name}</span>
              <Muted>{c.event === "updated" ? `${c.old_version} → ${c.new_version}` : c.event === "installed" ? c.new_version : c.old_version}</Muted>
            </Row>
          ))}
          {a.changes.length > 8 && (
            <Button variant="ghost" size="sm" className="mt-1" onClick={() => setAllChanges(!allChanges)}>{allChanges ? "Show fewer" : `Show all ${a.changes.length}`}</Button>
          )}
        </Card>
      ) : (
        <p className="mb-4 text-sm text-muted-foreground">No changes noticed since {a.history_since ? dayOf(a.history_since) : "the first list"}.</p>
      )}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Filter by name or publisher" aria-label="Filter applications" className="w-72" />
        <Segmented label="Show" value={show} onChange={setShow}
          options={[{ value: "desktop", label: "Programs" }, { value: "packaged", label: "Store and packaged" }, { value: "all", label: "All" }, ...(upd ? [{ value: "updates" as const, label: "Updates" }] : [])]} />
      </div>
      {!sorted.length ? (
        <p className="text-sm text-muted-foreground">Nothing matches.</p>
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b">
                <Th k="name">Name</Th><Th k="version">Version</Th>{upd && <Th k="available">Available</Th>}<Th k="publisher">Publisher</Th><Th k="installed">Installed</Th><Th k="size" right>Size</Th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((x) => (
                <tr key={x.id} className="border-b align-top last:border-b-0">
                  <td className="max-w-[20rem] px-4 py-2.5" title={x.location ?? undefined}>
                    <div className="flex items-center gap-1.5"><span className="truncate">{x.name}</span>{x.from_store && <Badge variant="muted">Store</Badge>}</div>
                    {(x.arch || x.scope === "user") && (
                      <div className="text-xs text-muted-foreground">{[x.arch, x.scope === "user" ? "this user only" : ""].filter(Boolean).join(" · ")}</div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5 tabular">{x.version || "—"}</td>
                  {upd && (
                    <td className="whitespace-nowrap px-2 py-1.5">
                      {x.available
                        ? <span className="inline-flex items-center gap-1"><Badge variant="info" className="tabular">{x.available}</Badge><CopyCmd id={x.update_id} /></span>
                        : <span className="text-muted-foreground">—</span>}
                    </td>
                  )}
                  <td className="px-2 py-2.5">{x.publisher || "—"}</td>
                  <td className="whitespace-nowrap px-2 py-2.5 tabular">
                    {x.date_is === "changed" && x.installed
                      ? <span className="text-muted-foreground" title={DATE_TITLE}>{dayOf(x.installed)}*</span>
                      : dayOf(x.installed)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right tabular">{x.size == null ? "—" : bytes(x.size)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {upd && upd.unmatched.length > 0 && (
        <Card className="mt-4 p-4">
          <div className="mb-1 font-semibold">Newer versions for things not in this list</div>
          <p className="mb-2 text-xs text-muted-foreground">winget knows these under another name.</p>
          {upd.unmatched.map((u) => (
            <Row key={u.id}>
              <span className="min-w-0 flex-1 truncate">{u.name}</span>
              <Muted className="tabular">{u.version} → {u.available}</Muted>
              <CopyCmd id={u.id} />
            </Row>
          ))}
        </Card>
      )}
      {a.counts.date_is_a_guess > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">* {a.counts.date_is_a_guess} {a.counts.date_is_a_guess === 1 ? "program records" : "programs record"} no install date; the date shown is when the entry last changed.</p>
      )}
    </div>
  );
}
