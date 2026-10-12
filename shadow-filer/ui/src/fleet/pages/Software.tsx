import { useState } from "react";
import { Flame, Package } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { usePoll } from "@/lib/hooks";
import { Card, EmptyState, ListSkeleton, LoadError, PageHeader, Segmented } from "@/shadow/ui";
import { api, type Software, type SoftwareItem } from "../api";
import { DeviceLink } from "../parts";

type Show = "all" | "flaws" | "mixed" | "newer";

function Row({ p }: { p: SoftwareItem }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className="align-top">
        <td className="px-4 py-2.5">
          <div className="font-medium">{p.name}{p.kind === "packaged" && <Badge variant="muted" className="ml-2">Packaged</Badge>}</div>
          <div className="text-xs text-muted-foreground">{p.publisher}</div>
        </td>
        <td className="px-4 py-2.5 tabular">{p.devices}</td>
        <td className="px-4 py-2.5">
          {p.versions.length === 1 ? <span className="path">{p.versions[0]!.version || "—"}</span>
            : <button className="text-primary hover:underline" onClick={() => setOpen(!open)} aria-expanded={open}>{p.versions.length} versions</button>}
          {p.versions.length === 1 && p.devices > 1 && <button className="ml-2 text-xs text-primary hover:underline" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "hide" : "which PCs"}</button>}
        </td>
        <td className="px-4 py-2.5">
          <div className="flex flex-wrap gap-1.5">
            {p.exploited > 0 && <Badge variant="danger"><Flame className="size-3" />{p.exploited} used in attacks</Badge>}
            {p.cves > 0 && <Badge variant="warning">{p.cves} known flaw{p.cves === 1 ? "" : "s"}</Badge>}
            {p.ended && <Badge variant="danger">Support ended</Badge>}
            {p.newer && <Badge variant="muted">Newer: {p.newer}</Badge>}
          </div>
        </td>
      </tr>
      {open && (
        <tr className="bg-muted/30">
          <td colSpan={4} className="px-4 py-2.5 text-sm">
            {p.versions.map((v) => (
              <div key={v.version} className="flex gap-3 py-0.5">
                <span className="path w-40 shrink-0">{v.version || "version not known"}</span>
                <span>{v.devices.map((x, i) => <span key={x.id}>{i > 0 && ", "}<DeviceLink id={x.id} name={x.name} tab="programs" /></span>)}</span>
              </div>
            ))}
          </td>
        </tr>
      )}
    </>
  );
}

export function SoftwarePage() {
  const q = usePoll<Software>(api.software, 120_000);
  const [find, setFind] = useState("");
  const [show, setShow] = useState<Show>("all");
  const d = q.data;
  const all = d?.programs ?? [];
  const needle = find.trim().toLowerCase();
  const pick = { all: () => true, flaws: (p: SoftwareItem) => p.cves > 0 || p.ended, mixed: (p: SoftwareItem) => p.versions.length > 1, newer: (p: SoftwareItem) => !!p.newer };
  const rows = all.filter((p) => pick[show](p) && (!needle || `${p.name} ${p.publisher}`.toLowerCase().includes(needle)));
  const n = (k: Show) => all.filter(pick[k]).length;
  return (
    <>
      <PageHeader title="Software" sub="Every program reported by the organisation's PCs: which devices have it, and in which versions." />
      {q.error && <div className="mb-4"><LoadError error={q.error} onRetry={q.reload} /></div>}
      {!d ? !q.error && <ListSkeleton rows={5} h="h-12" /> : all.length === 0 ? (
        <EmptyState icon={<Package />} title="No programs reported yet">A PC reports its programs when Library › Applications is switched on in its own console.</EmptyState>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find a program or maker" className="h-9 max-w-xs" aria-label="Find a program" />
            <Segmented label="Which programs" value={show} onChange={setShow} options={[
              { value: "all", label: `All (${all.length})` }, { value: "flaws", label: `Flaws or unsupported (${n("flaws")})` },
              { value: "mixed", label: `More than one version (${n("mixed")})` }, { value: "newer", label: `Newer version (${n("newer")})` }]} />
            <span className="ml-auto text-xs text-muted-foreground">{d.devices} device{d.devices === 1 ? "" : "s"} reporting programs</span>
          </div>
          <Card className="overflow-x-auto rounded-lg">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                <tr><th className="px-4 py-2 font-medium">Program</th><th className="px-4 py-2 font-medium">Devices</th><th className="px-4 py-2 font-medium">Version</th><th className="px-4 py-2 font-medium">Known about it</th></tr>
              </thead>
              <tbody className="divide-y">
                {rows.slice(0, 500).map((p) => <Row key={p.name + p.kind} p={p} />)}
                {rows.length === 0 && <tr><td colSpan={4} className="px-4 py-6 text-center text-muted-foreground">Nothing matches.</td></tr>}
              </tbody>
            </table>
          </Card>
          {rows.length > 500 && <p className="text-sm text-muted-foreground">Showing the first 500 of {rows.length}. Narrow the search to see the rest.</p>}
          <p className="text-sm text-muted-foreground">Flaws are counted for the worst installed version. A program with no mark was either compared and is clean, or matches no product in the public lists and is not judged.</p>
        </div>
      )}
    </>
  );
}
