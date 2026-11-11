/* The changelog, shared by the PC's console and the fleet console (opened from the version at the foot of the sidebar). */
import { Badge } from "@/components/ui/badge";
import { CHANGELOG } from "@/changelog";
import { APP } from "@/version";
import { Card, PageHeader } from "../ui";

export function ChangelogPage() {
  const built = APP.builtAt ? new Date(APP.builtAt).toLocaleString() : "";
  return (
    <>
      <PageHeader title="Changelog" sub={<>You are running <span className="font-mono">{APP.label}</span>{built && <>, built {built}</>}.</>} />
      <div className="space-y-4">
        {CHANGELOG.map((r) => (
          <Card key={r.version} className="rounded-lg p-5">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="font-mono text-sm font-semibold">v{r.version}</span>
              {r.version === APP.version && <Badge variant="info">this build</Badge>}
              <span className="font-medium">{r.title}</span>
              <span className="ml-auto text-xs text-muted-foreground">{new Date(r.date + "T12:00:00").toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" })}</span>
            </div>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed">
              {r.items.map((x, i) => <li key={i}>{x}</li>)}
            </ul>
          </Card>
        ))}
      </div>
    </>
  );
}
