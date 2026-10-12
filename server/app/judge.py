"""
Judging a device on the server (phase 2): known flaws, end of support and the compliance checks, from what the
device reported. One copy of the rules for every device.

The matching itself is the agent's own code, shared unchanged: `cve.py` (which product is this, is this
version affected) and `eol.py` (which release line, is it still supported), against one copy of the public
lists kept by the worker. The thresholds, the five control areas and the declared questions come from the
agent's `compliance.py`, so the PC's own console and the server cannot drift apart.

The checks are written again here, because the server sees less than the PC does, on purpose: a device sends
counts and true/false, never account names, paths or addresses (see `fleet.payload` in the agent). So the
evidence lines here say "1 account" where the PC's own page names it.

Everything in this file is plain Python over dictionaries. Only `flaws()` and `support()` open the reference
lists; the API never calls those two.
"""
import re
from datetime import date

import compliance as agent          # the agent's module: THRESHOLDS, CONTROLS, DECLARED and the small helpers

T = agent.THRESHOLDS
C = agent._check
KEYS = {k for k, _, _ in agent.DECLARED}
CHECK_ID = re.compile(r"[a-z]{2,4}\.[a-z_]{2,20}")


def _list(v) -> list:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _s(n: int, one: str = "", many: str = "s") -> str:
    return one if n == 1 else many


# --------------------------------------------------------------------------- the reference lists
def ref_ready(cfg: dict) -> bool:
    """Is there a complete copy of the CVE list to compare with? A half-downloaded one would call a device
    clean that is not."""
    import cve
    return bool(cve.status(cfg)["complete"])


def flaws(cfg: dict, snaps: dict) -> dict | None:
    """Installed programs and services against the CVE list. None when the device has not reported its
    programs or the list is not there yet. Store and packaged apps are not judged, as on the PC."""
    import cve
    a = snaps.get("apps")
    if not isinstance(a, dict) or not ref_ready(cfg):
        return None
    desktop = [x for x in _list(a.get("apps")) if x.get("kind") == "desktop" and x.get("name")]
    judged = cve.match(cfg, desktop)
    by_name = {}
    for j in judged:
        by_name.setdefault((j["name"], j.get("version")), j)
        by_name.setdefault(j["name"], j)
    svcs = _list((snaps.get("services") or {}).get("services")) if isinstance(snaps.get("services"), dict) else []
    alone = [s for s in svcs if not s.get("app_name")]
    own = cve.match(cfg, [{"name": s.get("product") or s.get("name") or "", "version": s.get("version") or "",
                           "publisher": s.get("publisher") or ""} for s in alone])
    own = {id(s): j for s, j in zip(alone, own)}
    out_apps = [{k: j.get(k) for k in ("name", "version", "judged_version", "publisher", "available", "update_to",
                                       "products", "cves", "unversioned")} for j in judged if j["products"]]
    out_apps.sort(key=lambda x: (-sum(1 for c in x["cves"] if c["kev"]), -len(x["cves"]), x["name"].lower()))
    out_svcs = []
    for s in svcs:
        src = (by_name.get((s["app_name"], s.get("version"))) or by_name.get(s["app_name"])) if s.get("app_name") else own.get(id(s))
        out_svcs.append({**{k: s.get(k) for k in ("name", "service", "running", "start", "account", "product", "version",
                                                  "exposed", "app_name")},
                         "ports": [{"port": p.get("port"), "network": bool(p.get("network"))} for p in _list(s.get("ports"))],
                         "products": (src or {}).get("products", []), "cves": (src or {}).get("cves", []),
                         "unversioned": (src or {}).get("unversioned", 0)})
    out_svcs.sort(key=lambda x: (not (x["exposed"] and x["cves"]), not x["cves"], not x["exposed"], str(x["name"]).lower()))
    hit = [x for x in out_apps if x["cves"]]
    ids = {c["id"] for x in hit for c in x["cves"]}
    return {"installed": len(desktop), "recognised": len(out_apps), "apps": out_apps, "services": out_svcs,
            "summary": {"apps_affected": len(hit), "cves": len(ids),
                        "kev": len({c["id"] for x in hit for c in x["cves"] if c["kev"]}),
                        "critical": len({c["id"] for x in hit for c in x["cves"] if (c["score"] or 0) >= 9}),
                        "fix_available": sum(1 for x in hit if x.get("available")),
                        "services": len(out_svcs), "services_exposed": sum(1 for x in out_svcs if x["exposed"]),
                        "services_affected": sum(1 for x in out_svcs if x["cves"])}}


def windows_parts(device: dict) -> tuple:
    """(build number, display version, edition) from what a device reports: 'Windows 11 Enterprise 26H2' and
    build '26300.9550'."""
    try:
        build = int(str(device.get("build") or "0").split(".")[0])
    except ValueError:
        build = 0
    words = str(device.get("windows") or "").split()[2:]
    ver = words[-1] if words and re.fullmatch(r"\d\dH\d|\d{4}", words[-1], re.I) else ""
    return build, ver, " ".join(words[:-1] if ver else words)


def support(cfg: dict, snaps: dict, today: date) -> dict | None:
    """Which programs, and which Windows, are a release line that no longer gets security updates."""
    import cve
    import eol
    if not cve.db_path(cfg).exists() or not eol.status(cfg)["products"]:
        return None
    out = {"programs": None, "installed": 0, "windows": None}
    a = snaps.get("apps")
    if isinstance(a, dict):
        desktop = [x for x in _list(a.get("apps")) if x.get("kind") == "desktop" and x.get("name")]
        out["installed"] = len(desktop)
        out["programs"] = [{k: x.get(k) for k in ("name", "version", "product", "line", "state", "until", "latest")}
                           for x in eol.match(cfg, desktop, today) if x.get("product")]
    d = snaps.get("device")
    if isinstance(d, dict):
        build, ver, edition = windows_parts(d)
        out["windows"] = eol.windows(cfg, build, ver, edition, today)
    return out


# --------------------------------------------------------------------------- the checks
def firewall_checks(n) -> list:
    title = "Windows Firewall is on for every profile"
    fw = _list(n.get("firewall")) if isinstance(n, dict) else []
    if not fw:
        return [C("fw.on", title, "unknown", "The device has not reported its network settings.", to="network")]
    off = [f.get("name") or "?" for f in fw if not f.get("enabled")]
    other = [str(x) for x in n.get("other_firewalls") or []]
    out = [C("fw.on", title, "pass" if not off else "warn" if other else "fail",
             "On for Domain, Private and Public." if not off else
             f"Off for {', '.join(off)}." + (f" {', '.join(other)} is registered as the firewall instead." if other else
                                            " No other firewall is registered with Windows."),
             [f"{f.get('name')}: {'on' if f.get('enabled') else 'OFF'}, incoming {str(f.get('inbound') or '?').lower()}" for f in fw],
             None if not off else "On the PC, in its own console: Network > Exposure > Turn on.", "network")]
    all_off = len(off) == len(fw)
    allow_all = [f.get("name") for f in fw if f.get("enabled") and str(f.get("inbound") or "").lower() == "allow"]
    out.append(C("fw.default", "Incoming connections are blocked unless a rule allows them",
                 "unknown" if all_off else "fail" if allow_all else "pass",
                 "Cannot be judged while the firewall is off." if all_off else
                 f"The {', '.join(allow_all)} profile lets every incoming connection through." if allow_all else
                 "Each profile that is on blocks incoming connections by default.", to="network"))
    ports = [e for e in _list(n.get("listening")) if e.get("reach") == "network" and not e.get("windows") and e.get("proto") == "TCP"]
    names = sorted({e["process"] for e in ports if e.get("process")})
    out.append(C("fw.ports", "Programs that accept connections from the network are known and wanted",
                 "info" if ports else "pass",
                 f"{len(ports)} TCP port{_s(len(ports))} opened by {len(names)} program{_s(len(names))} that are not part of "
                 "Windows. Each should be one you want reachable." if ports else
                 "No program outside Windows accepts connections from the network.",
                 [f"{e.get('process') or '?'}: TCP {e.get('port')}" for e in ports[:30]], to="network"))
    ru = n.get("rules")
    if not isinstance(ru, dict):
        out.append(C("fw.rules", "Every rule that lets connections in is for a program you know", "unknown",
                     "The firewall rules could not be read on the device.", to="network"))
    else:
        wide, gone, progs = ru.get("any_program_any_port") or 0, ru.get("left_over") or 0, ru.get("programs") or 0
        out.append(C("fw.rules", "Every rule that lets connections in is for a program you know",
                     "fail" if wide else "warn" if gone else "info" if progs else "pass",
                     (f"{wide} rule{_s(wide, ' lets', 's let')} any program in on any port. " if wide else "")
                     + (f"{gone} rule set{_s(gone, ' is', 's are')} left over from programs that are no longer on the device. " if gone else "")
                     + f"{ru.get('total') or 0} rules let connections in: {ru.get('windows') or 0} are Windows' own, the rest cover "
                       f"{progs} program{_s(progs)}. The device's own console lists them.",
                     fix="On the PC: Windows Security > Firewall > Advanced settings > Inbound Rules: delete what is not needed."
                     if wide or gone else None, to="network"))
    shares = n.get("shared_folders") or 0
    out.append(C("fw.shares", "No folders are shared from the device without a reason", "warn" if shares else "pass",
                 f"{shares} folder{_s(shares, ' is', 's are')} shared." if shares else "No folders are shared.", to="network"))
    return out


def configuration_checks(p) -> list:
    if not isinstance(p, dict):
        return [C("cfg.lock", "The PC locks by itself when left alone", "unknown", "The device has not reported its settings.")]
    lim = T["lock_seconds"] // 60
    out = [C("cfg.lock", "The PC locks by itself when left alone", "pass" if p.get("lock_found") else "warn",
             f"An automatic lock within {lim} minutes is set." if p.get("lock_found") else
             f"No automatic lock within {lim} minutes was found for the signed-in user (no locking screen saver, no inactivity "
             "limit, and the screen is not set to go off and ask to sign in).",
             fix=None if p.get("lock_found") else "On the PC: Settings > Accounts > Sign-in options, and Settings > System > Power.")]
    off = bool(p.get("autoplay_off"))
    out.append(C("cfg.autoplay", "AutoPlay is off, so a plugged-in drive runs nothing by itself", "pass" if off else "fail",
                 "AutoPlay is off." if off else "AutoPlay is on for removable drives.",
                 fix=None if off else "On the PC: Settings > Bluetooth & devices > AutoPlay: switch it off."))
    known = p.get("accounts_enabled") is not None
    out.append(C("cfg.guest", "The Guest account is disabled", "fail" if p.get("guest_enabled") else "pass" if known else "unknown",
                 "The Guest account is enabled." if p.get("guest_enabled") else "Disabled." if known else "The local accounts were not reported."))
    nopw = p.get("accounts_without_password") or 0
    out.append(C("cfg.password", "Every account that can sign in needs a password",
                 "fail" if nopw else "pass" if known else "unknown",
                 f"{nopw} enabled account{_s(nopw, ' does', 's do')} not require a password. It may still have one; Windows just "
                 "does not insist. The device's own console names it." if nopw else
                 "Every enabled account requires a password." if known else "The local accounts were not reported.",
                 fix="On the PC, in an administrator terminal: net user <name> /passwordreq:yes" if nopw else None))
    enc, drives = p.get("drives_encrypted"), p.get("drives") or 0
    out.append(C("cfg.encryption", "Drives are encrypted (BitLocker)",
                 "unknown" if enc is None else "pass" if enc else "fail",
                 "The drives were not reported." if enc is None else
                 f"Encrypted: all {drives} drive{_s(drives)}." if enc else
                 f"Not every drive is encrypted ({drives} drive{_s(drives)} reported). A lost or stolen PC gives up its files.",
                 fix=None if enc is not False else "On the PC: Settings > Privacy & security > Device encryption, or Manage "
                                                   "BitLocker. Asked for by insurers; not one of the five Cyber Essentials controls."))
    return out


BROWSER = {"chrome_default": "Google Chrome", "chrome_period": "Google Chrome", "edge_default": "Microsoft Edge", "firefox_off": "Firefox"}


def update_checks(p, device, vul, sup, apps, today: date) -> list:
    out = []
    p = p if isinstance(p, dict) else {}
    build, _ver, _ed = windows_parts(device) if isinstance(device, dict) else (0, "", "")
    win = (sup or {}).get("windows") or {"state": "unknown", "until": None}
    state = win["state"]
    if state == "unknown" and build:
        state = "ended" if build <= 22000 else "unlisted"      # Windows 10 and Windows 11 21H2, as on the PC
    name = f"{(device or {}).get('windows') or 'Windows'} (build {(device or {}).get('build') or '?'})" if isinstance(device, dict) else "Windows"
    out.append(C("upd.supported", "Windows is a version that still gets security updates",
                 "unknown" if not build else "fail" if state == "ended" else "warn" if state == "soon" else "pass",
                 "The device has not reported its Windows version." if not build else
                 f"{name} stopped getting security updates" + (f" on {win['until']}" if win.get("until") else "") + ", unless extended support was bought."
                 if state == "ended" else
                 f"{name} gets security updates until {win['until']}: less than 90 days from now." if state == "soon" else
                 f"{name} gets security updates until {win['until']}." if win.get("until") else
                 f"{name}. Not known to be out of support.",
                 fix="Upgrade Windows." if state in ("ended", "soon") else None))
    age, lim = agent._days(p.get("windows_last_update"), today), T["windows_update_days"]
    out.append(C("upd.windows", f"Windows installed an update in the last {lim} days",
                 "unknown" if age is None else "pass" if 0 <= age <= lim else "fail",
                 "The date of the last update was not reported." if age is None else
                 f"Last update on {p['windows_last_update']}, {age} days ago. Whether a newer one exists is not checked.",
                 fix=None if age is not None and age <= lim else "On the PC: Settings > Windows Update > Check for updates."))
    if p:
        off, paused = bool(p.get("windows_updates_off")), bool(p.get("windows_updates_paused"))
        out.append(C("upd.automatic", "Windows installs updates by itself", "fail" if off else "warn" if paused else "pass",
                     "Automatic updates are switched off by policy." if off else "Updates are paused." if paused else
                     "Automatic updates are not switched off or paused."))
    flaw_title = f"No high or critical flaw older than {T['patch_days']} days in installed programs"
    if vul is None:
        out.append(C("upd.flaws", flaw_title, "unknown", "The device has not reported its programs, or the server's copy of the "
                                                         "CVE list is not complete yet.", to="security"))
    else:
        old, rows = [], []
        for a in vul["apps"]:
            hit = [x for x in a["cves"] if (x.get("score") or 0) >= T["high_score"] and (agent._days(x.get("published"), today) or 0) > T["patch_days"]]
            if hit:
                old.append(a["name"])
                worst = max(agent._days(x.get("published"), today) or 0 for x in hit)
                rows.append(f"{a['name']} {a.get('judged_version') or ''}: {len(hit)} high or critical, oldest {worst} days"
                            + (f", fix: update to {a['update_to']}" if a.get("update_to") else ""))
        kev = vul["summary"]["kev"]
        out.append(C("upd.flaws", flaw_title, "fail" if old else "pass",
                     (f"{len(old)} program{_s(len(old), ' has', 's have')} high or critical flaws published more than {T['patch_days']} days ago"
                      + (f"; {kev} of the flaws {_s(kev, 'is', 'are')} being used in real attacks." if kev else ".")) if old else
                     f"None among the {vul['recognised']} programs that could be compared.",
                     rows, "Update the program on the PC (its console: Security > Programs), or install the fix version shown."
                     if old else None, "security"))
        out.append(C("upd.coverage", "Every installed program can be compared with the list of known flaws", "info",
                     f"{vul['recognised']} of {vul['installed']} programs match a product in the CVE list. The others are not "
                     "judged: unknown, not safe.", to="security"))
    eol_title = "Installed programs are versions that still get security updates"
    if not sup or sup.get("programs") is None:
        out.append(C("upd.unsupported", eol_title, "unknown", "The device has not reported its programs, or the server has no "
                                                              "end-of-life list yet.", to="programs"))
    else:
        ended = [x for x in sup["programs"] if x["state"] == "ended"]
        soon = [x for x in sup["programs"] if x["state"] == "soon"]
        row = lambda x, verb: (f"{x['name']}: the {x['line']} line {verb} {x['until'] or '(no date given)'}"
                               + (f"; newest in that line is {x['latest']}" if x.get("latest") and x["state"] != "ended" else ""))
        out.append(C("upd.unsupported", eol_title, "fail" if ended else "warn" if soon else "pass",
                     (f"{len(ended)} program{_s(len(ended), ' is', 's are')} a release line that no longer gets security updates. " if ended else "")
                     + (f"{len(soon)} more lose{_s(len(soon), 's', '')} support within 90 days. " if soon else "")
                     + f"{len(sup['programs'])} of {sup['installed']} programs are in the end-of-life list; the others are not judged.",
                     [row(x, "ended on") for x in ended] + [row(x, "ends on") for x in soon],
                     "Move to a supported release line of the program." if ended or soon else None, "programs"))
    if p:
        bad = sorted({BROWSER[k] for k in p.get("browser_updates_off") or [] if k in BROWSER})
        out.append(C("upd.browsers", "Browsers update themselves", "fail" if bad else "pass",
                     f"Updates are switched off by policy for {', '.join(bad)}." if bad else
                     "No policy switches off automatic updates for Chrome, Edge or Firefox.",
                     fix="Remove the policy on the PC." if bad else None))
    if isinstance(apps, dict):
        newer = [a for a in _list(apps.get("apps")) if a.get("available")]
        out.append(C("upd.pending", "Installed programs are on their newest version", "warn" if newer else "info",
                     f"{len(newer)} program{_s(len(newer), ' has', 's have')} a newer version available." if newer else
                     "The device reported no newer versions. If its check for newer versions is switched off, none are reported.",
                     [f"{a.get('name')}: {a.get('version')} -> {a.get('available')}" for a in newer][:40],
                     "Update on the PC (its console: Library > Applications > Updates)." if newer else None, "programs"))
    return out


def access_checks(p) -> list:
    if not isinstance(p, dict):
        return [C("acc.daily", "The account used every day is not an administrator", "unknown", "The device has not reported its settings.")]
    adm = bool(p.get("daily_account_is_admin"))
    out = [C("acc.daily", "The account used every day is not an administrator", "fail" if adm else "pass",
             "The signed-in account is a member of the Administrators group. Anything that runs as that user can ask for full "
             "control of the PC with one click on a prompt." if adm else "The signed-in account is a standard account.",
             fix="Create a separate administrator account and make the everyday one a standard user." if adm else None)]
    n = p.get("admin_accounts")
    out.append(C("acc.admins", "Few accounts have administrator rights", "unknown" if n is None else "warn" if n > 3 else "pass",
                 "The Administrators group was not reported." if n is None else
                 f"Members of the Administrators group: {n} (groups and disabled accounts included)."))
    return out


def malware_checks(p) -> list:
    if not isinstance(p, dict):
        return [C("mal.present", "Antivirus protection is installed and switched on", "unknown", "The device has not reported its settings.")]
    on, n = p.get("antivirus_on"), p.get("antivirus_products") or 0
    out = [C("mal.present", "Antivirus protection is installed and switched on",
             "pass" if on else "fail" if n else "unknown",
             f"On ({n} product{_s(n)} registered with Windows)." if on else
             "Installed but switched off." if n else "Windows did not report an antivirus product.",
             fix=None if on else "On the PC: Windows Security > Virus & threat protection.")]
    rt = p.get("realtime_protection")
    if rt is not None:
        out.append(C("mal.realtime", "Files are checked as they are opened (real-time protection)",
                     "pass" if rt else "warn" if on else "fail",
                     "Microsoft Defender's real-time protection is on." if rt else
                     "Microsoft Defender's real-time protection is off" + ("; another antivirus product is on." if on else ".")))
        age, lim = p.get("signature_age_days"), T["signature_days"]
        out.append(C("mal.signatures", f"Antivirus definitions are less than {lim} days old",
                     "unknown" if age is None or age < 0 else "pass" if age <= lim else "fail",
                     "The age of the definitions was not reported." if age is None or age < 0 else
                     f"Microsoft Defender's definitions are {age} day{_s(age)} old."))
    return out


# --------------------------------------------------------------------------- putting it together
def overlay(comp: dict, accepted: dict) -> dict:
    """Apply the accepted exceptions ({check id: {reason, ts, actor}}) and count again. An accepted check
    keeps its failing mark and only stops counting against its control area."""
    every = []
    for g in comp["controls"]:
        for ch in g["checks"]:
            a = accepted.get(ch["id"])
            ch["accepted"] = a if a and ch["status"] in ("fail", "warn") else None
        g["status"] = agent._roll(g["checks"])
        g["counts"] = {s: sum(1 for ch in g["checks"] if ch["status"] == s and not ch["accepted"]) for s in ("pass", "fail", "warn", "unknown")}
        g["accepted"] = sum(1 for ch in g["checks"] if ch["accepted"])
        every += g["checks"]
    comp["summary"] = {"controls_passing": sum(1 for g in comp["controls"] if g["status"] == "pass"), "controls": len(comp["controls"]),
                       "fail": sum(1 for ch in every if ch["status"] == "fail" and not ch["accepted"]),
                       "warn": sum(1 for ch in every if ch["status"] == "warn" and not ch["accepted"]),
                       "unknown": sum(1 for ch in every if ch["status"] == "unknown"),
                       "passed": sum(1 for ch in every if ch["status"] == "pass"),
                       "accepted": sum(1 for ch in every if ch["accepted"])}
    return comp


def assess(snaps: dict, vul: dict | None, sup: dict | None, accepted: dict, today: date) -> dict:
    """The five control areas for one device, from what it reported and what the lists say about it."""
    p, dev = snaps.get("posture"), snaps.get("device")
    groups = {"firewalls": firewall_checks(snaps.get("network")), "configuration": configuration_checks(p),
              "updates": update_checks(p, dev, vul, sup, snaps.get("apps"), today), "access": access_checks(p),
              "malware": malware_checks(p)}
    comp = {"controls": [{"key": k, "title": t, "about": about, "checks": groups[k]} for k, t, about in agent.CONTROLS],
            "thresholds": T}
    return overlay(comp, accepted)


def history_line(comp: dict) -> dict:
    return {"controls": {g["key"]: g["status"] for g in comp["controls"]},
            "checks": {ch["id"]: ("accepted" if ch["accepted"] else ch["status"]) for g in comp["controls"] for ch in g["checks"]},
            "summary": {k: comp["summary"][k] for k in ("controls_passing", "fail", "warn", "unknown")}}


def summary(comp: dict, vul: dict | None, sup: dict | None) -> dict:
    """The few numbers the fleet list and dashboard show per device."""
    win = (sup or {}).get("windows") or {}
    progs = (sup or {}).get("programs") or []
    return {"compliance": {**comp["summary"], "areas": {g["key"]: g["status"] for g in comp["controls"]}},
            "failing": [{"id": ch["id"], "title": ch["title"], "control": g["key"]} for g in comp["controls"] for ch in g["checks"]
                        if ch["status"] == "fail" and not ch["accepted"]],
            "security": {**vul["summary"], "installed": vul["installed"], "recognised": vul["recognised"],
                         "exploited": [{"program": a["name"], "version": a.get("judged_version"), "cve": c["id"], "fix": a.get("update_to")}
                                       for a in vul["apps"] for c in a["cves"] if c["kev"]][:20]} if vul else None,
            "support": {"windows": win.get("state"), "windows_until": win.get("until"),
                        "ended": [x["name"] for x in progs if x["state"] == "ended"],
                        "soon": [x["name"] for x in progs if x["state"] == "soon"]} if sup else None}


def declared(rows: list) -> list:
    """The declared questions with the organisation's answers ({key, answer, note, at})."""
    said = {r["key"]: r for r in rows}
    return [{"key": k, "title": t, "about": why, "answer": (said.get(k) or {}).get("answer"), "note": (said.get(k) or {}).get("note") or "",
             "ts": (said.get(k) or {}).get("at")} for k, t, why in agent.DECLARED]


# --------------------------------------------------------------------------- as text
def device_text(dev: dict, comp: dict, vul: dict | None, judged_at: str) -> list:
    m = comp["summary"]
    lines = [f"{dev.get('name') or 'Device'}: {dev.get('windows') or 'Windows version not reported'}"
             + (f", {dev['model']}" if dev.get("model") else "") + (f", serial {dev['serial']}" if dev.get("serial") else ""),
             f"  Last report {dev.get('last_seen') or 'never'}; judged {judged_at}.",
             f"  {m['controls_passing']} of {m['controls']} control areas pass; {m['fail']} failing checks, {m['warn']} to look at, "
             f"{m['unknown']} could not be checked, {m['accepted']} accepted with a reason."]
    if vul:
        s = vul["summary"]
        lines.append(f"  {vul['recognised']} of {vul['installed']} programs compared with the CVE list: {s['apps_affected']} with known flaws "
                     f"({s['cves']} CVEs, {s['kev']} used in real attacks, {s['critical']} critical).")
    for g in comp["controls"]:
        lines.append(f"  {g['title'].upper()}: {agent.MARK[g['status']].strip()}")
        for ch in g["checks"]:
            lines.append(f"    [{agent.MARK[ch['status']]}] {ch['title']}")
            lines.append(f"           {ch['detail']}")
            for e in ch["evidence"][:12]:
                lines.append(f"             - {e}")
            if ch["accepted"]:
                lines.append(f"           Accepted on {str(ch['accepted'].get('ts'))[:10]}: {ch['accepted'].get('reason')}")
    return lines


def report_text(org: str, when: str, devices: list, said: list) -> str:
    """The evidence for a whole organisation as plain text. `devices` is [(device, compliance, flaws, judged_at)],
    with compliance None for a device that has not been judged yet."""
    judged = [d for d in devices if d[1]]
    full = sum(1 for d in judged if d[1]["summary"]["controls_passing"] == d[1]["summary"]["controls"])
    lines = [f"Security posture of {org}", f"Produced {when} by the Shadow Filer fleet server from what each PC's agent reported.",
             f"{len(devices)} device{_s(len(devices))}; {len(judged)} judged; {full} with all five control areas passing.", ""]
    for dev, comp, vul, at in devices:
        lines += device_text(dev, comp, vul, at) if comp else [f"{dev.get('name')}: enrolled, not judged yet (no report, or the server has not got to it)."]
        lines.append("")
    lines.append("DECLARED BY THE ORGANISATION (not measured)")
    for q in said:
        a = {"yes": "Yes", "no": "No", "na": "Does not apply", None: "Not answered"}[q["answer"]]
        lines.append(f"  {a:<15} {q['title']}" + (f" ({q['note']})" if q["note"] else "") + (f" [{str(q['ts'])[:10]}]" if q["ts"] else ""))
    lines += ["", "Each PC reports counts and settings, never account names, file names or addresses, so some lines say how many "
                  "and not which.", "This follows the Cyber Essentials control areas but is not a certificate."]
    return "\n".join(lines) + "\n"
