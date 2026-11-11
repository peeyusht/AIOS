# Spec: India frameworks — CERT-In MSME controls and DPDP Rule 6

Status: proposed, 11 Nov 2026. Nothing in this spec is approved yet. Section 7 lists the decisions the owner
must take before any of it is built; several of them change rules in `CLAUDE.md` that say "ask first".

Status of each item was checked against the code on 11 Nov 2026 (`shadow-filer/compliance.py`,
`shadow-filer/fleet.py`, `shadow-filer/watch.py`, `server/app/judge.py`, `server/schema.sql`):

| Mark | Meaning |
|---|---|
| **BUILT** | Measured and judged today; the check id is given |
| **PARTIAL** | The reading exists but the judgement, the threshold, the fleet payload or the server side is missing |
| **NEW** | Not built |

Types: **M** measured by the agent · **D** declared by the organisation (always shown as declared, never as
measured) · **W** a workflow kept on the server (dates, owners, reminders, uploaded proof) · **S** judged on the
server from facts it already has.

---

## 1. The two frameworks, as written

### CERT-In "15 Elemental Cyber Defense Controls for MSMEs" (CISG-2025-03, v1.0, 1 Sep 2025)
15 controls, 45 recommendations. Applies to MSMEs as classified by the Ministry of MSME (S.O. 1702(E), 2020).
The document says MSMEs **may** have a baseline audit by a CERT-In empanelled auditor at least once a year.
Much vendor marketing calls it mandatory; the text says "may". Do not claim otherwise in the product.
Separate from it, the 6-hour incident reporting duty comes from CERT-In's directions under section 70B(6) of
the IT Act and does apply.

### DPDP Rules 2025, Rule 6 (G.S.R. 846(E), notified 13 Nov 2025, in force 13 May 2027)
Seven minimum safeguards for every Data Fiduciary:
(a) encryption, obfuscation, masking or virtual tokens; (b) access control over computer resources;
(c) visibility through logs, monitoring and review; (d) continuity measures including backups;
(e) retention of logs and personal data for one year unless another law says otherwise;
(f) security provisions in contracts with Data Processors; (g) technical and organisational measures for
effective observance. Rule 7: breach intimation to the Board and to affected people, detailed report within
72 hours. Penalty ceiling for failing to take reasonable security safeguards: ₹250 crore.

Out of scope, and the DPDP page must say so: notice, consent, consent managers, data-principal rights,
children's data, cross-border transfer. An endpoint agent cannot evidence those. The page is "Rule 6 and 7
evidence", never "DPDP compliance".

---

## 2. The change everything else depends on: one measurement, several verdicts

Today `compliance.py` has one rulebook (`THRESHOLDS`, `CONTROLS`, `DECLARED`, `SCHEME` = Cyber Essentials
v3.3) and `server/app/judge.py` imports it. The same fact must be judged differently per framework:

| Fact | Cyber Essentials v3.3 | CERT-In MSME | DPDP Rule 6 |
|---|---|---|---|
| Lockout after N wrong passwords | pass if 1–10 | pass if 3–5 (RPP.2) | pass if 1–10 (no number given; use CE) |
| Drive encryption | note only (`info`), never fails | note | **fail** on a device marked "holds personal data" |
| Event log retention | not asked | ≥180 days (LM.1) | ≥365 days on personal-data devices (6(1)(e)) |
| Automatic lock | note only | note | part of (b), note |

**F-0 Framework profiles — BUILT 11 Nov 2026** (`compliance.FRAMEWORKS`, `judge_framework`; CERT-In lockout in
`cfg.unlock`). What was built differs from the bullets below in these ways, found once the code was read:
- CERT-In lockout **below 3** (1 or 2 tries) is `warn`, not `fail`: stricter than RPP.2 asks, and it locks people
  out easily, but it is not weaker. 0 (never) and above 5 fail; unreadable is `unknown` in every profile.
- A control area whose checks are all notes (`info`) has the status `info`, not `pass`, and does not count in
  "areas met" (DPDP's 6(1)(a) on a device not labelled as holding personal data). Before, an all-notes area
  would have rolled up as "pass".
- DPDP areas: `enc` 6(1)(a) (`cfg.encryption`), `access` 6(1)(b) (accounts, lockout, lock, admin rights, firewall),
  `other` "Other reasonable safeguards" (patching, malware, AutoPlay), labelled on the page as our own mapping:
  Rule 6 does not name them. (c), (d), (e) come with F-10 and F-12.
- CERT-In areas: NES, EMS, SC, PM, RPP, ACIM; only those with measured checks. `upd.unsupported` is in SC (SC.3),
  `cfg.lock` and `cfg.encryption` are notes in SC.
- Declared questions are one pool (`compliance.QUESTIONS`), one answer per key; each framework lists the keys it
  asks with its own reason. CERT-In's perimeter firewall is a new key `perimeter`, not the CE `router` question
  reworded, because one answer must not stand for two different questions.
- The PC itself has no labels; on the agent DPDP encryption is always a note until F-1 labels devices on the
  server. The server's judge already takes `labels`.
- The server re-judges every device when the judging code changes (a fingerprint of `judge.py` and
  `compliance.py` is part of the worker's reference version), so a rule change does not wait for the next day.
- Local choice of frameworks: table `compliance_settings` in the agent's database, Compliance › Frameworks;
  server: `organisations.frameworks` (text[], default `{ce}`), set by an admin or owner on the Evidence page
  (`POST /api/v1/frameworks`, audit-logged). A share link sees only the frameworks the organisation shows.

Original specification:
- `compliance.FRAMEWORKS = {"ce": {...}, "certin": {...}, "dpdp": {...}}`. Each profile has its own
  thresholds, its control areas (a list of check ids per area), its declared questions and a `scheme` string.
- Checks are measured once (the existing `_check` functions keep their ids) and then given a status per
  profile. A check can be `info` in one profile and `fail` in another.
- `compliance_history` keeps one line per day **per profile** (agent: key `day|profile`; server: add a
  `framework` column to the primary key).
- Exceptions (`compliance_accepted`, server `exceptions`) are per check, not per profile: an accepted check
  stays accepted, with its failing mark, in every profile.
- The organisation (server) or the PC owner (local) chooses which profiles are shown. Default: CE only, so
  nothing changes for existing users.
- `judge.py` keeps importing the profiles from the agent's `compliance.py`, as today, so the two cannot drift.
- Tests: the same posture judged under all three profiles gives the verdicts in the table above.

**F-1 Device labels — NEW (W).** On the server, an admin can mark a device `personal_data` and/or `critical`
(CERT-In EAM.1 "classification of sensitive assets"). DPDP checks that say "on personal-data devices" use the
label. F-11 can suggest the label; a person sets it. New table `device_labels (org_id, device_id, label, at,
actor)` with row-level security and a line in the isolation test.

---

## 3. CERT-In: control by control

| # | Recommendation (short) | Feature | Type | Status |
|---|---|---|---|---|
| EAM.1 | Inventory of hardware, software, information assets; classify sensitive ones | Device + program inventory | M | **BUILT** (device, apps, services snapshots) |
| | | "Personal data" / "critical" labels | W | **NEW** (F-1) |
| EAM.2 | Asset lifecycle to secure disposal | Device retirement record (F-20) | W | **NEW**. Today "remove a device" only deletes it |
| NES.1 | Perimeter firewall; host firewall on and configured | Windows Firewall per profile, default inbound block, wide-open and left-over rules | M | **BUILT** `fw.on`, `fw.default`, `fw.rules` |
| | | Perimeter firewall | D | **PARTIAL**: declared item `router` exists, worded for Cyber Essentials (router password, firmware). Add a CERT-In wording. Later: F-30 FortiGate read-only |
| NES.2 | Wi-Fi WPA2/WPA3, no default creds, guest segregated, no auto-connect to open Wi-Fi | F-2 Wi-Fi posture | M | **NEW** |
| NES.3 | Encrypted VPN with MFA for remote access | Declared | D | **NEW** question |
| NES.4 | SPF, DKIM, DMARC | F-3 mail domain check | S | **NEW**. Needs decision D-3 |
| EMS.1 | Licensed AV, current; Defender and Firewall not disabled | AV present and on, real-time, definition age | M | **BUILT** `mal.present`, `mal.realtime`, `mal.signatures`, `fw.on` |
| EMS.2 | No pirated or unauthorised software; only authorised people install | F-4 approved-software list; daily account not admin | M+S | **PARTIAL**: `acc.daily` BUILT; approved list NEW |
| EMS.3 | Onboard with Cyber Swachhta Kendra | Declared | D | **NEW** question |
| EMS.4 | Restrict USB and removable media; disable autorun | AutoPlay/autorun off | M | **BUILT** `cfg.autoplay` |
| | | F-5 USB storage policy | M | **NEW** |
| SC.1 | Baseline configurations, approved by the entity | F-6 baseline drift | S | **NEW** |
| SC.2 | Disable unnecessary features, ports, services, protocols | Listening ports, non-Windows services, shares | M | **BUILT** `fw.ports`, `fw.shares`, services snapshot |
| | | F-7 SMBv1, RDP and NLA, remote registry, PowerShell v2 | M | **NEW** |
| SC.3 | Remove unused software; change default passwords | End-of-life programs | M | **BUILT** `upd.unsupported` |
| | | Guest account off | M | **BUILT** `cfg.guest` |
| | | Built-in Administrator (RID 500) enabled | M | **NEW** (the account list is already read; add the check) |
| PM.1 | Patch OS, applications, firmware | Windows monthly release within 14 days, auto-update on, CVEs, pending updates, browsers | M | **BUILT** `upd.windows`, `upd.automatic`, `upd.flaws`, `upd.pending`, `upd.browsers` |
| | | F-8 BIOS/firmware version and date | M | **PARTIAL**: `Win32_BIOS` is already read for the serial; version and release date are not |
| PM.2 | Monitor vendor notices and CERT-In advisories | CVE + CISA KEV lists | S | **BUILT** (`cve.py`) |
| | | F-9 CERT-In advisories matched to installed software | S | **NEW**. First check that CERT-In publishes something machine-readable; if not, drop it |
| IM.1 | Documented incident response plan | Declared | D | **BUILT** `incident_plan` (as a question; no document, no date) |
| IM.2 | Test the plan regularly | Last test date, reminder | W | **NEW** |
| IM.3 | Report to CERT-In within 6 hours | F-21 incident register | W | **NEW** |
| LM.1 | Logging on; logs kept ≥180 days, within India | F-10 log retention and audit policy | M | **NEW** |
| LM.2 | Monitor network and privileged actions | Out of scope (that is SIEM/EDR). Shown as "not measured by this product" | – | not planned |
| LM.3 | Monitoring tools (recommended) | Declared | D | **NEW** question |
| AT.1 | Awareness training at least twice a year | Training dates, reminder every 6 months | W | **PARTIAL**: `training` declared yes/no exists; dates and cadence NEW |
| AT.2 | CERT-In workshops and drills | Declared | D | **NEW** question |
| TPRM.1–2 | Vendor due diligence; same baseline for vendors | F-22 vendor register | W | **NEW** |
| DPBP.1 | Regular backups, encrypted, offsite and offline | F-12 backup detection | M | **NEW** |
| | | Declared | D | **BUILT** `backups` |
| DPBP.2 | Test restores | Declared, with a date | D | **BUILT** `backup_test` (12-month wording; keep) |
| DPBP.3 | Minimum business continuity plan | Declared | D | **NEW** question |
| DPBP.4 | Secure disposal of media | F-20 retirement record | W | **NEW** |
| GC.1 | Named security in-charge / SPoC | F-23 governance record | W | **NEW** |
| GC.2–3 | Approved security policy, periodic review | F-23 | W | **NEW** |
| GC.4 | Follow CERT-In and regulator directions | Declared | D | **NEW** question |
| RPP.1 | Length 8–12+, complexity, expiry, no reuse | F-13 password policy | M | **NEW** (same `net accounts` call already made for lockout) |
| RPP.2 | Lock after 3–5 failed attempts | Lockout threshold | M | **BUILT** 11 Nov 2026 `cfg.unlock`: ≤10 in CE and DPDP, 3–5 in the CERT-In profile (F-0) |
| RPP.3 | MFA for critical systems, admins, remote access | Declared | D | **BUILT** `mfa` (worded for cloud services; add admin/remote wording) |
| RPP.4 | Passwords stored with secure hashing | Out of scope for an endpoint agent | – | not planned |
| ACIM.1 | Unique user IDs, no shared accounts | Enabled accounts, accounts with no password, never-used accounts | M | **PARTIAL**: `cfg.password` BUILT; `cfg.unused` BUILT on the PC only (the payload sends `accounts_enabled`, not the unused count, so the server cannot judge it) |
| ACIM.2 | Role-based, least privilege | Daily account not admin | M | **BUILT** `acc.daily` |
| ACIM.3 | Review access quarterly and on exit | F-24 access review | W | **NEW** |
| ACIM.4 | Admin rights only when essential | Admin account count | M | **BUILT** `acc.admins` |
| PS.1–2 | Physical controls; asset return on exit | Declared; asset return part of F-20 | D/W | **NEW** |
| VAA.1 | Independent VA at least yearly; fix findings | F-25 VA report record | W | **NEW**. Our own CVE list is **not** "independent"; never present it as the VA |
| VAA.2 | Periodic risk assessment | Declared, with a date | D | **NEW** question |

---

## 4. DPDP Rule 6 and 7

| Rule | Feature | Type | Status |
|---|---|---|---|
| 6(1)(a) encryption | BitLocker per drive | M | **PARTIAL**: measured (`cfg.encryption`, payload `drives_encrypted`), but always `info`. DPDP profile: fail on personal-data devices (F-0, F-1) |
| 6(1)(b) access control | Password policy, lockout, guest, accounts without password, admins, daily account, lock | M | **PARTIAL**: all BUILT except F-13 password policy |
| 6(1)(c) logs, monitoring, review | F-10 audit policy on; F-24 log review sign-off | M+W | **NEW** |
| 6(1)(d) continuity, backups | F-12; declared `backups`, `backup_test` | M+D | **PARTIAL** (declared BUILT, detection NEW) |
| 6(1)(e) one-year retention | F-10 oldest Security log entry ≥365 days on personal-data devices | M | **NEW** |
| 6(1)(f) processor contracts | F-22 vendor register with "security clause" and contract upload | W | **NEW** |
| 6(1)(g) effective observance | Daily history, evidence report, share link, audit log | S | **BUILT** (server phase 2–3) |
| 7 breach intimation | F-21 incident register with the 72-hour clock | W | **NEW** |
| Which devices hold personal data? | F-11 personal-data discovery | M | **PARTIAL**: `watch.py` finds PAN, Aadhaar, card, account, passport, private keys in **Downloads only**, on the personal agent only, and nothing leaves the PC |

---

## 5. New features, specified

Every new measured fact is a count, a number of days or true/false. None of them names an account, a file, a
path, an SSID or an address. Each one added to `fleet.payload()` needs the owner's yes (D-1).

**F-2 Wi-Fi posture (M).** `netsh wlan show interfaces` and `netsh wlan show profiles` (fixed commands, no
arguments built from data). Facts: `wifi_connected` (bool), `wifi_auth` of the connected network (`open`,
`wep`, `wpa`, `wpa2`, `wpa3`; never the SSID), `wifi_open_autoconnect` (count of saved open networks set to
connect by themselves). Check `net.wifi`: fail on open or WEP, warn on WPA (v1) or open networks saved with
auto-connect. Desktop with no Wi-Fi adapter: check not shown.

**F-3 Mail domain (S).** On the server: the organisation enters its mail domain; the worker looks up the SPF
and DMARC TXT records (and DKIM for selectors the organisation names; DKIM cannot be found without a selector)
once a day. Check `org.mail`: pass if SPF exists and DMARC policy is `quarantine` or `reject`; warn on
`p=none`. **Breaks the current rule** that the worker sends nothing about a customer (a DNS query carries the
domain). Needs D-3.

**F-4 Approved software (S).** The organisation marks programs as approved in the server's Software page; a
device with a program that is not approved gets `acc.unapproved` (warn). No list = check not shown.

**F-5 USB storage (M).** Read `HKLM\SYSTEM\CurrentControlSet\Services\USBSTOR\Start` (4 = disabled) and the
removable-storage deny policies under `HKLM\SOFTWARE\Policies\Microsoft\Windows\RemovableStorageDevices`.
Fact `usb_storage`: `blocked` | `read_only` | `allowed`. CERT-In profile: `allowed` = warn (the text says
"restrict or control", not "block").

**F-6 Baseline drift (S).** The organisation picks one device's current posture as its approved baseline
(or the defaults of a profile). Each device shows which posture facts differ. Uses facts already sent.

**F-7 Insecure protocols (M).** SMBv1 server enabled (`Get-SmbServerConfiguration`), RDP enabled
(`fDenyTSConnections`) and whether NLA is required (`UserAuthentication`), Remote Registry running,
PowerShell v2 feature present. Facts: four booleans. Checks `cfg.smb1` (fail), `cfg.rdp` (warn if RDP on
without NLA; info if on with NLA), `cfg.remreg` (warn), `cfg.psv2` (warn).

**F-8 Firmware (M).** Add `SMBIOSBIOSVersion` and `ReleaseDate` to the existing `Win32_BIOS` read.
Fact `bios_date`. Check `upd.firmware`: warn if older than 3 years (our own number; say so). The maker's
latest version cannot be known offline; do not claim "out of date".

**F-9 CERT-In advisories (S).** Only if CERT-In publishes a feed that can be fetched without sending anything
about a customer. Otherwise not built. Investigate before planning.

**F-10 Logs (M).** Fixed PowerShell: for the Security, System and Application logs, `MaximumSizeInBytes`,
`LogMode` (Circular / AutoBackup / Retain) and the `TimeCreated` of the oldest record; plus `auditpol /get
/category:*` for Logon/Logoff and Account Management (success and failure). Facts: `log_days_security`
(age of the oldest entry), `log_mode_security`, `audit_logon` (bool), `audit_account_mgmt` (bool).
Checks `log.retention` (CERT-In: fail below 180 days; DPDP: fail below 365 on personal-data devices),
`log.audit` (fail if logon auditing is off). **Expect wide failure**: the default 20 MB Security log rolls
over in days. The fix text points to AutoBackup mode or the customer's own log collection. **We do not
collect the logs**: they contain user names, and holding them would make us a Data Processor. "Stored
within India" (LM.1) is a declaration, not a measurement.

**F-11 Personal-data discovery (M).** Move the detectors of `watch.py` (PAN, Aadhaar with Verhoeff, card with
Luhn, bank account, passport, private key; same "looks the part" rules) into code the device agent can run
over the user's Documents, Desktop and Downloads, text files and Office/PDF only, size-capped, cloud-only
files skipped (`is_cloud_only`), password-protected PDFs never opened. Fact per device: counts per kind and
the number of files, nothing else (no names, no paths, no numbers). Suggests label F-1. **Breaks two rules**:
the device agent has no file-reading code (D-2), and the payload gains a file-derived fact (D-1).

**F-12 Backups (M).** Detect: Windows File History configured and its last backup time; Windows Server
Backup / `wbadmin` last success where present; known backup agents among installed programs and their
services' state (a small, named list: Veeam Agent, Acronis, Macrium, Backblaze, OneDrive Known Folder Move).
Facts: `backup_tool` (bool), `backup_last_days` (int or null when not knowable). Check `bak.recent`: warn if
no tool is found, warn if the last known run is older than 7 days. Never fail: a backup taken elsewhere
(NAS, server-side) is invisible here; the declared answer stays the evidence.

**F-13 Password policy (M).** Extend the existing `net accounts` read: minimum length, maximum age, history
length, and complexity (from `secedit /export` is too heavy; use the `PasswordComplexity` value from the
local policy via `net accounts` where available, otherwise unknown). Facts: `pw_min_length`, `pw_max_age_days`,
`pw_history`. Check `cfg.pwpolicy`: CERT-In fail below 8. Same English-text limit as the lockout read
(anything else = unknown).

**F-20 Device retirement (W).** "Remove a device" becomes "Retire": date, reason, how the disk was wiped or
destroyed, who, optional uploaded certificate, asset returned (PS.2). The device's history stays, marked
retired. Covers EAM.2, DPBP.4, PS.2.

**F-21 Incident register (W).** An incident: when detected, what, devices involved, whether personal data
was involved. Two clocks on screen: CERT-In 6 hours from detection; DPDP 72 hours for the detailed report to
the Board (only when personal data is involved). Fields laid out like CERT-In's incident reporting form so
they can be copied; we do not submit anything. Audit-logged.

**F-22 Vendor register (W).** Vendor, what they do, whether they process personal data, due-diligence date,
"contract has security clauses" (DPDP 6(1)(f)), contract upload, and the vendor's own evidence: a share link
from their organisation on this server, or an uploaded report. Covers TPRM.1–2 and 6(1)(f).

**F-23 Governance record (W).** Security in-charge (name, contact), policy document upload with approval date
and next review date, reminders. Covers GC.1–3.

**F-24 Reviews (W).** Quarterly access review and periodic log review: who signed off, when, a note. Overdue
shows on the Overview. Covers ACIM.3 and DPDP 6(1)(c) "review".

**F-25 VA report (W).** Upload the yearly independent VA report, its date and the auditor; list findings
with an owner and a closed date. Covers VAA.1.

**F-30 Perimeter firewall, read-only (M, later).** A read-only FortiGate API token, kept by the customer's
side, never by the server: admin access exposed to WAN, default admin, firmware version against Fortinet's
end-of-support list. Separate design; listed here so NES.1 has a path beyond a declaration.

New declared questions (D), per profile: VPN with MFA (NES.3), CSK onboarding (EMS.3), monitoring tool
(LM.3), logs kept in India (LM.1), CERT-In drills (AT.2), continuity plan (DPBP.3), follow CERT-In directions
(GC.4), physical access controls (PS.1), risk assessment date (VAA.2). Each declared answer gets an optional
date and an optional uploaded document.

**Evidence uploads (all W features).** Not built today: the server has no file storage. Needs its own design:
size limit, allowed types (PDF, images; never HTML or SVG), stored outside the database, scanned for nothing
and served only with `nosniff` and download disposition, per-organisation, row-level security on the index
table, retention and deletion rules. This is customer data at rest: phase 6 hardening (backups, encryption at
rest) must come first.

---

## 6. Order of work

1. **F-0 profiles** and the CERT-In lockout threshold. No payload change. Unblocks everything. **BUILT 11 Nov 2026.**
2. **Measured, payload change needed (D-1):** F-13 password policy, F-7 protocols, F-8 firmware, F-5 USB,
   built-in Administrator enabled, never-used account count, F-2 Wi-Fi, F-10 logs, F-12 backups.
3. **Server workflows without uploads:** F-1 labels, F-21 incidents, F-24 reviews, F-23 (without document),
   new declared questions with dates.
4. **Uploads**, after phase 6 hardening: F-20, F-22, F-23 documents, F-25.
5. **Decision-gated:** F-11 (D-1, D-2), F-3 (D-3), F-9 (feasibility), F-30 (own design).

Tests for every step, in the existing suites: `shadow-filer/tests/test_compliance.py` (profiles, thresholds),
`tests/test_fleet.py` (each new payload field is a count or boolean; planted names, paths, SSIDs and numbers
never come out), `device-agent/tests` (the new readings work as SYSTEM), `server/tests/test_server.py`
(every new table in the isolation test).

---

## 7. Decisions the owner must take first

- **D-1 Widen `fleet.payload()`** with: `pw_min_length`, `pw_max_age_days`, `pw_history`, `smb1_on`, `rdp_on`,
  `rdp_nla`, `remote_registry_on`, `psv2_present`, `bios_date`, `usb_storage`, `builtin_admin_enabled`,
  `accounts_never_used`, `wifi_auth`, `wifi_open_autoconnect`, `log_days_security`, `log_mode_security`,
  `audit_logon`, `audit_account_mgmt`, `backup_tool`, `backup_last_days`. All counts, days, enums or booleans.
  The SENT list in `fleet.py` and `docs/architecture.md` changes with it.
- **D-2 File reading in the device agent** (F-11). Today it deliberately has none, and the file-organising
  half "never leaves the PC". Counts only would leave, but the promise changes.
- **D-3 Customer-specific DNS lookups by the worker** (F-3). Today the worker goes online only for three
  public lists and sends nothing about a customer.
- **D-4 Evidence uploads on the server.** New class of stored customer data; schedule after phase 6.
- **D-5 Which profile is the default** for a new organisation: CE (as today) or CERT-In for Indian customers.

---

## Sources
- CERT-In, 15 Elemental Cyber Defense Controls for MSMEs, v1.0, 1 Sep 2025 (copy on it.delhi.gov.in:
  https://it.delhi.gov.in/sites/default/files/IT/generic_multiple_files/elemental_cyber_defense.pdf)
- DPDP Rules 2025, Rule 6 text and commencement (G.S.R. 846(E) and 843(E), 13 Nov 2025), as quoted by
  https://www.sansalegal.com/post/how-to-specify-reasonable-security-safeguards-under-rule-6-of-the-dpdp-rules-2025
  and https://dpdp.myndsolution.com/wiki/rules/rule-6-reasonable-security-safeguards/ . Read the Gazette text
  itself before building F-10's thresholds.
- Penalty ceiling: Schedule to the DPDP Act 2023 (₹250 crore, security safeguards).
