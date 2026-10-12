# Architecture: from one PC to a managed fleet

Status on 12 Oct 2026: the single-PC product is built (`shadow-filer/`). Phases 1 and 2 of the central
server are built (`server/`, and `shadow-filer/fleet.py` on the agent). Phases 3 to 6 are planned, not
started.

## What the product is

Evidence that a small organisation's PCs are patched, firewalled and inventoried, in language an owner, an
insurance broker or a Cyber Essentials assessor can read. It is not EDR (no real-time detection or response)
and not full MDM (no policy enforcement, no phones). The file-organising half of `shadow-filer` (Inbox,
filing, Cleanup, the work journal) is a personal tool and never leaves the PC.

## The shape

```
  PC                                   Central server                         Database server
 ┌──────────────────────┐   HTTPS    ┌──────────────────────────────┐       ┌────────────────────┐
 │ agent                │ ─────────► │ reverse proxy (TLS)          │       │ PostgreSQL         │
 │  collects facts      │  outbound  │ API service  (FastAPI)       │ ────► │  organisations     │
 │  runs approved       │   only     │ worker       (feeds, judging)│       │  devices, facts    │
 │  actions             │ ◄───────── │ web console  (fleet + device)│       │  reference lists   │
 │ local console        │  replies   └──────────────────────────────┘       │  judgements, audit │
 └──────────────────────┘                                                    └────────────────────┘
```

Every connection is started by the PC, to one HTTPS address. No PC opens a port, so the agent works behind
home routers and office firewalls with nothing to configure.

## Where the work happens

| | Single PC (today) | Central design |
|---|---|---|
| Collect programs, services, network, settings | agent | agent |
| CVE, known-exploited and end-of-life lists | a 400 MB copy on each PC | one copy on the server |
| Match programs to flaws; compliance checks | agent | server, so one rule fix applies to every device |
| History, declarations, accepted exceptions | the agent's SQLite file | server database |
| Console | `127.0.0.1:8765` | web console on the server; the local one stays |
| Update / Stop service / Firewall on | local click, local guard rules | server queues a command; the agent re-checks it against its own lists and runs it |

The matching and end-of-life code (`cve.py`, `eol.py`) is plain Python with no dependence on Windows, which
is why the server is Python: the server image copies those two files from the agent unchanged, so there is
one set of matching rules. The thresholds, the five control areas and the declared questions come from the
agent's `compliance.py` in the same way. The checks themselves are written a second time for the server
(`server/app/judge.py`), because the server sees less than the PC does: counts and true/false, never an
account name or a path. Its evidence says "1 account does not require a password"; the PC's own console
says which.

## Components

**Agent** (`shadow-filer/`). Today a user-mode process started by Task Scheduler. `fleet.py` adds enrolment
and a check-in loop. From phase 4 it runs as a Windows service with a signed installer and self-update.

**API service** (`server/app/main.py`, FastAPI). Three groups of calls: agents (`/api/v1/enrol`,
`/api/v1/checkin`), console (`/api/v1/devices`, ...), and health. Stateless; any number can run behind the
proxy.

**Worker** (`server/app/worker.py`). Downloads the CVE, known-exploited and end-of-life lists daily into a
SQLite file on its own volume (the same file format the agent keeps), and judges a device again when its
facts changed, a list changed, or the day changed; it writes the judgement and one compliance line per
device per day. It is the only container that goes online, and only for those public downloads. It asks
the database which devices are waiting through one function that answers with ids only, then works inside
one organisation at a time under the same row-level security as the API. During the first download
(about 9 minutes) devices are judged on their settings alone and judged again when the lists are there.

**Web console.** Built from the same source tree as the PC's console (`shadow-filer/ui`, entry
`src/fleet`), so it shares its components and styles, and served by the API. Pages: Overview (how many
devices pass each control area, which checks fail where, flaws used in real attacks, 90 days of history),
Devices, one device (Compliance, Security, Programs, Network, Reported), Software (which program is on
which devices, in which versions), Evidence (the report as text, the organisation's declarations, the
record). It can accept a failing check with a reason and record a declaration; it cannot change a PC.

**Reverse proxy.** TLS, request size limits, rate limits. Caddy in the compose file from phase 6; in phase 1
the API listens on localhost only.

**Database server.** PostgreSQL 17.

## Data model

Phase 1 tables (`server/schema.sql`):

| Table | Holds |
|---|---|
| `organisations` | one row per customer |
| `admin_keys` | console access keys (hashed), per organisation |
| `enrolment_tokens` | one-time or limited-use tokens (hashed) that let an agent join an organisation |
| `devices` | identity, key hash, last seen, agent version, a small summary |
| `snapshots` | what a device reported, per kind (`device`, `apps`, `services`, `network`, `posture`), kept only when it changed |
| `audit_log` | enrolments, key use, later every command and sign-in |

Phase 2 tables:

| Table | Holds |
|---|---|
| `judgements` | the latest judgement of each device: flaws, end of support, the checks, a summary |
| `compliance_history` | one line per device per day with each check's result |
| `declarations` | what the organisation states about things no program can measure |
| `exceptions` | a failing check accepted on one device, with the reason and who |
| `reference_status` | how fresh the public lists are (shared; no customer data) |

The lists themselves (`cve`, `aff`, `kev`, `eol_product`) are not in PostgreSQL: they are public, the same
for everyone, and stay in the worker's SQLite file so the agent's matching code reads them unchanged.

Later phases add: `users`, `roles`, `sessions` (3); `commands`, `command_results` (5).

**Separation between customers** is enforced by the database, not only by the application. Every table with
customer data has an `org_id` and row-level security with `FORCE ROW LEVEL SECURITY`; the API connects as a
role that cannot bypass it and sets the organisation for each transaction. The only code that can look across
organisations is four `SECURITY DEFINER` functions: three turn a presented key or token into an organisation
(`auth_device`, `auth_admin`, `redeem_token`) and one tells the worker which devices are waiting, by id
(`judge_queue`). The worker has its own database role, which cannot read keys, tokens or the audit log;
the API's role cannot create a judgement. A bug in a query therefore returns nothing instead of another
customer's data. `server/tests/test_server.py` proves it by querying one organisation's devices as another.

## Identity and trust

- **Enrolment.** An administrator creates a token for an organisation (limited uses, an expiry). The agent
  presents it once and receives a device id and a random 256-bit device key. The server stores only SHA-256
  hashes of tokens and keys.
- **Check-in.** The agent sends its key as a bearer credential over TLS. Phase 4 replaces this with a key
  pair generated on the device (the private key never leaves it) and requests signed by it.
- **Console.** Phase 1: an organisation admin key. Phase 3: named users, multi-factor sign-in, roles (owner,
  admin, read-only auditor) and a time-limited share link for a broker or assessor.
- **Transport.** HTTPS only. The agent refuses a plain `http://` server unless it is `localhost`, for
  development.

## What leaves a PC

Today's promise is "nothing leaves this PC". Enrolling a PC replaces that promise with this list, which the
agent can print (`shadow_agent.py fleet show`) before anything is sent.

Sent: the PC's name, make, model, serial number and Windows version; installed programs (name, version,
publisher, install date, size); Windows services that are not part of Windows (name, state, account type,
product, version, port numbers); firewall state per profile, the network's Public/Private mark, listening
ports (number, program name, reachable from the network or not), counts of rules and shared folders; security
settings as true/false or counts (antivirus on, drives encrypted, lock, AutoPlay, how many administrator
accounts).

Never sent: anything about files or documents (the whole file-organising half), account names, install
folders and program paths (they contain the user name), IP and MAC addresses, the addresses of open
connections, the list of neighbouring devices, the routing table, the hosts file, DNS servers, the update
log's free text.

## Remote actions (phase 5)

The most dangerous feature, so it comes last and stays narrow. Only the three actions that exist locally
(update one application, stop one service, switch the firewall on). The server signs each command; the agent
verifies the signature and then applies the same guard rules as a local click (the application must be in its
own list with an update that is not blocked, never a major-version jump, never "all"). Every command and
result is in the audit log. The local console remains the place an owner can refuse.

## Hard parts, known in advance

- **A service cannot see per-user things**: programs installed for one user, the lock setting, AutoPlay. The
  service agent needs a per-user helper or has to read each user's registry hive.
- **winget does not run normally as a service.** Remote updates need another mechanism or a workaround. This
  is untested and the least certain piece of the plan.
- **Custody of customers' inventories**: backups, breach responsibility, data-protection law per country.
- **A compromised server could push commands to every PC**, which is why commands are signed, narrow and
  re-checked on the device.
- **Code signing.** Unsigned agents are flagged by antivirus and cannot be updated safely in the field.

## Phases

| Phase | Delivers | Status |
|---|---|---|
| 1. Pipeline proof | server, database, enrolment, the user-mode agent uploading inventory, a fleet device list | built |
| 2. Central judging | CVE, end-of-life and compliance on the server; per-device pages and a fleet dashboard; the evidence report per device and per organisation | built |
| 3. Organisations and roles | sign-in with multi-factor, owner / admin / auditor roles, share link | not started |
| 4. Service agent and installer | runs as a service, signed, self-updating, per-user helper, device key pair | not started |
| 5. Remote actions | signed command queue, audit, approvals | not started |
| 6. Hardening | TLS proxy, rate limits, backups, monitoring, penetration test, published data list | not started |

Phases 1 to 3 are enough to show a broker or a first customer. Phase 4 should wait until someone has said
the report is worth paying for.

## Decisions taken (12 Oct 2026)

1. **Hosting:** one rented cloud server to start. Phase 1 runs with Docker Compose on a developer PC; the same
   compose file is what goes on the server.
2. **Many customers from day one:** organisation separation is in the database from the first table.
3. **View-only first:** phases 1 to 3 have no remote actions.
4. **Stack:** Python, FastAPI, PostgreSQL.
5. **The local console stays** on each PC, as the fallback and the place an owner approves actions.

## Containers

Every server part is a container, built and run with Docker Compose (`server/docker-compose.yml`): `db`,
`init` (one-off database setup), `api` (with the console built into its image), `worker`, and on demand
`manage` (admin commands) and `test`. Phase 6 adds `proxy` as a further service in the same file. The same
compose file runs on a developer PC and on the rented server. The image is built from the repository root,
because it takes three modules and the console's source from the agent; `/.dockerignore` lets in exactly
those, so nothing personal from the agent's folder can reach an image.

The agent is the one part that is not a container and cannot be. Its job is to read the PC it runs on:
the registry, the services, the firewall, the installed programs. A Linux container on Windows runs in a
virtual machine and sees none of that; a Windows container sees its own registry and services, not the
host's. The agent's front end, however, can be built in a container (`shadow-filer/docker-compose.yml`,
service `ui-build`), so a build machine needs only Docker.

## Running it

See `server/README.md`.
