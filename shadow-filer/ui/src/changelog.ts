/* What changed in each release, newest first. The first entry's version must equal package.json's "version"
   (tests/test_version.py checks), and every code change raises it (scripts/check_version_bump.py). Write for the
   people who use the consoles: what they can now see or do, not how it was built. */
export interface Release { version: string; date: string; title: string; items: string[] }

export const CHANGELOG: Release[] = [
  {
    version: "1.5.0", date: "2026-11-11", title: "Version and changelog",
    items: [
      "The version and the build it came from are shown at the foot of the sidebar, on the PC's console and on the fleet console.",
      "This page: what changed in each release.",
    ],
  },
  {
    version: "1.4.0", date: "2026-11-11", title: "Mail domain check; all three frameworks for new organisations",
    items: [
      "Fleet: enter the organisation's mail domain on the Evidence page; once a day the server looks up its SPF, DMARC and DKIM records (CERT-In NES.4).",
      "Fleet: a new organisation shows CERT-In, DPDP and Cyber Essentials; existing ones keep their choice.",
    ],
  },
  {
    version: "1.3.0", date: "2026-11-11", title: "Incidents, governance, reviews and device labels",
    items: [
      "Fleet: an incident register with CERT-In's 6-hour and DPDP's 72-hour clocks, laid out for copying into the reports.",
      "Fleet: the security in-charge, the security policy's dates, and access and log reviews signed off by a person; overdue items on the Overview.",
      "Fleet: mark a device as holding personal data or as critical; DPDP judges encryption and log retention by it.",
      "Nine new declared questions for CERT-In and DPDP, and every declaration can carry the date it is about.",
    ],
  },
  {
    version: "1.2.0", date: "2026-11-11", title: "New checks on each PC",
    items: [
      "Password policy, old protocols (SMBv1, Remote Desktop, Remote Registry, PowerShell 2.0), firmware age and USB storage.",
      "The built-in Administrator account, accounts that never signed in, Wi-Fi encryption, the Security log's reach and audit settings, and backups.",
      "Each is sent to the fleet server as a count, a number of days or true/false; never a name, a path or a network name.",
    ],
  },
  {
    version: "1.1.0", date: "2026-11-11", title: "Frameworks: Cyber Essentials, CERT-In MSME, DPDP Rule 6",
    items: [
      "The same measurements judged by each framework's own rules; choose which frameworks the Compliance page shows.",
      "CERT-In: accounts must lock after 3 to 5 wrong passwords. DPDP: Rule 6 and 7 evidence, not a statement of compliance.",
    ],
  },
  {
    version: "1.0.0", date: "2026-11-11", title: "Redesigned console; Cyber Essentials v3.3",
    items: [
      "Icon rail, light and dark themes, a new Today page, Inbox, Security and Compliance.",
      "Compliance rules checked against Cyber Essentials v3.3 (April 2026).",
    ],
  },
];
