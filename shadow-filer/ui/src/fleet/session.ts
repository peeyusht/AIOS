/* Who is signed in, for the whole console. The server decides what a person may do; this only hides what
   would be refused anyway. */
import { useSyncExternalStore } from "react";
import { api, SESSION_ENDED, type Me, type Role } from "./api";

type State = { loaded: boolean; me: Me | null };
let state: State = { loaded: false, me: null };
const subs = new Set<() => void>();
const set = (s: State) => { state = s; subs.forEach((f) => f()); };

export async function refreshMe() {
  try { set({ loaded: true, me: await api.me() }); } catch { set({ loaded: true, me: null }); }
}
export async function signOut() {
  try { await api.logout(); } catch { /* the session is gone either way */ }
  set({ loaded: true, me: null });
}
window.addEventListener(SESSION_ENDED, () => { if (state.me) set({ loaded: true, me: null }); });

const subscribe = (cb: () => void) => { subs.add(cb); return () => void subs.delete(cb); };
export const useSession = () => useSyncExternalStore(subscribe, () => state);

const RANK: Record<Role, number> = { auditor: 0, admin: 1, owner: 2 };
/** May the signed-in person do what this role can? */
export function useCan(role: Role) {
  const s = useSession();
  return !!s.me?.role && RANK[s.me.role] >= RANK[role];
}
export const ROLE_LABEL: Record<Role, string> = { owner: "Owner", admin: "Admin", auditor: "Auditor" };
export const ROLE_ABOUT: Record<Role, string> = {
  owner: "Everything, including adding and changing people.",
  admin: "Accept checks, record declarations, make share links and enrolment tokens, remove a device.",
  auditor: "Read everything. Change nothing.",
};
