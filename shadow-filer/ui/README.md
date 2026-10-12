# Shadow Filer console (front end)

The console is designed in **Lovable** and built here into plain static files that the agent serves.

- Lovable project (source of truth for the design): https://lovable.dev/projects/24a52f89-2976-48ff-9630-4d56617c2f80
- Preview on demo data: https://id-preview--24a52f89-2976-48ff-9630-4d56617c2f80.lovable.app

## Build
```
cd shadow-filer\ui
npm install        # first time only
npm run build      # type-checks, then writes ..\ui_dist (index.html + assets\)
```
Static files need no agent restart: reload the browser. `http://127.0.0.1:8765/?classic=1` still serves the
old single-file page (`ui.html`) if a build is ever broken.

## What comes from Lovable, and what is ours
| Path | Owner |
|---|---|
| `src/shadow/**` (App, pages, shared UI) | Lovable |
| `src/components/ui/**`, `src/styles.css`, `components.json` | Lovable (restyled shadcn components) |
| `src/lib/api.ts`, `adapt.ts`, `types.ts`, `mock.ts`, `format.ts`, `hooks.ts`, `utils.ts` | Lovable |
| `src/main.tsx`, `index.html`, `vite.config.ts`, `tsconfig.json`, `package.json` | ours: the static build |

Lovable's own project is a server-rendered TanStack Start app; only the files above are used. The app has its
own `#/inbox`-style routing, so it runs unchanged as a static page.

## Bringing a new Lovable version in
1. In Lovable, note the latest commit. Copy the Lovable-owned files above over the local ones (from Claude
   Code: read each with the Lovable connector at that commit and write it here unchanged). `git diff` should
   then show only what Lovable changed.
2. `src/lib/adapt.ts` maps the agent's real answers to the shapes in `types.ts` (the mock data already has
   those shapes). When a page shows wrong or missing real data, fix the mapping there.
3. `npm run build`, then open every page against the running agent and look at the browser console.
4. Any fix made locally must be sent back to Lovable as an exact change, or the next copy loses it.
   Last copied Lovable commit: `7f23999` (Network page; its `Network.tsx` was copied whole, the nav entry, route, `api.network` and the
   `Net*` types were added by hand, and the demo data for it in `mock.ts` was written locally, not copied).
   Before that `575597f` (Dashboard page, first in the sidebar and the landing page). Its `Dashboard.tsx` was copied
   whole; its changes to `App.tsx`, `api.ts`, `types.ts` and `mock.ts` were merged by hand, because those
   files carry the local changes listed below (Lovable's copies do not have them).
   Lovable also writes test files (`*.test.tsx`, vitest); they are not copied and `tsconfig.json` excludes them.
   Dependencies Lovable adds must be added to our `package.json` too (so far: `docx-preview`).
   **Local changes waiting to be sent to Lovable** (made here on 12 Oct 2026 at the user's request, in the
   existing style; a copy from Lovable before they are sent would lose them): the Security page
   (`src/shadow/pages/Security.tsx`), its nav entry, badge and `SECURITY_CHANGED` event in `App.tsx`, the
   Security section in `Settings.tsx`, `security*` calls in `api.ts`, the `Sec*` types in `types.ts` and the
   fictional security demo data and routes in `mock.ts`; and for Update / Stop service: `src/shadow/remedy.tsx`
   (bar, buttons, dialogs), its use in `Library.tsx` and `Security.tsx`, the `library.remediate` switch in
   `Settings.tsx`, `remedy*` calls, `UpdatePlan`/`Remedy*` types and mock routes.

## Rules the UI must keep
- No external requests (fonts, CDNs, images, analytics): the agent's CSP is `default-src 'self'`.
- `index.html` keeps `<meta name="shadow-token" content="__TOKEN__">`; the agent fills it in. With the literal
  `__TOKEN__` (Lovable preview, `npm run dev`) the app runs on fictional demo data from `mock.ts`.
- Every POST carries `X-Shadow-Token`. Never send real file names or screenshots of real data to Lovable.
