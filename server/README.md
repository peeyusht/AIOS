# Fleet server (phases 1 to 4)

The central server from `docs/architecture.md`: PCs enrol and report what is installed; the server judges
each one (known flaws, end of support, the Cyber Essentials control areas); an administrator sees the
fleet, each device and the evidence report in a web console, signed in under their own name with a password
and an authenticator code. No remote actions (phase 5).

Everything here runs in containers and is started with Docker Compose. Nothing needs to be installed on the
machine except Docker.

| Container | What it is | Runs |
|---|---|---|
| `db` | PostgreSQL 17, data in the `fleet-db` volume | always |
| `init` | creates or updates the tables, sets the application role's password | once at start, then exits |
| `api` | the API and the web console | always |
| `worker` | keeps the public CVE, known-exploited and end-of-life lists (volume `fleet-ref`) and judges every device | always |
| `manage` | admin commands | on demand |
| `test` | the server's tests | on demand |

## Run it
```
cd server
docker compose up -d --build        # PostgreSQL on 127.0.0.1:5433, the API and console on 127.0.0.1:8770
docker compose ps
docker compose logs -f worker       # the first start downloads the lists: about 300 MB, about 9 minutes
```
The worker is the only container that goes online, and only to download public lists from nvd.nist.gov,
www.cisa.gov and endoflife.date; nothing about a customer or a device is in a request. Until the first
download is complete devices are judged on their settings alone, and again when the lists are there.
The image is built from the repository root (it shares the matching rules and the console's design with
the agent), so run compose from this folder and let it find the Dockerfile.
Both ports are reachable from this machine only. `docker compose down` stops everything and keeps the data;
`docker compose down -v` also deletes the database.

## First organisation and its first owner
```
docker compose run --rm manage org "Acme Ltd"
docker compose run --rm manage user "Acme Ltd" jo@acme.example     # prints a one-time link to set a password
docker compose run --rm manage list
```
Open the printed link, set a password, sign in, and set up the second factor with an authenticator app
(the page shows a code to scan and then eight recovery codes, once). Everything else is done in the
console under **Access**: more people, share links, enrolment tokens for PCs. The same command gives a
new link to someone who forgot their password; `--role admin|auditor` for other roles.

| Role | May |
|---|---|
| auditor | read everything |
| admin | also accept a failing check, record declarations, make share links and enrolment tokens, remove a device |
| owner | also add people, change roles, switch a person off, reset a password or second factor |

Still there from phase 1, for scripts: `manage admin-key "Acme Ltd"` prints an organisation key (send it as
`Authorization: Bearer ...`; it can read and change nothing), and `manage token "Acme Ltd" --uses 5` prints
an enrolment token.

## Enrol a PC
The agent is the one part that is not a container and cannot be: it has to read the PC's own registry,
services, firewall and installed programs, and a container sees only its own.

A customer's PC gets the device agent, a Windows service with its own installer (`../device-agent/README.md`):
```
msiexec /i ShadowFilerAgent-0.4.5.msi /qn SERVER=https://fleet.example.com TOKEN=<token>
```
Publish an installer on this server with `manage release add` (see that README) and admins can download it
from the console (Access) and every enrolled agent updates itself to it. `manage release list` and
`manage release withdraw <version>` are the other two.

The file-organising agent on your own PC can report too. On the PC, in `shadow-filer`:
```
.venv\Scripts\python shadow_agent.py fleet show                  # exactly what would be sent
.venv\Scripts\python shadow_agent.py fleet enrol http://127.0.0.1:8770 <token>
.venv\Scripts\python shadow_agent.py fleet checkin               # now; afterwards every 15 minutes while the agent runs
.venv\Scripts\python shadow_agent.py fleet status
.venv\Scripts\python shadow_agent.py fleet leave                 # stop reporting and forget the key
```
The agent refuses a plain `http://` server unless it is localhost. A PC on another machine needs the server
behind HTTPS (phase 6 adds the proxy container).

## What the console shows
- **Overview**: how many devices pass each control area, which checks fail on which devices, flaws that are
  being used in real attacks, devices that stopped reporting, the last 90 days.
- **Devices** and one device: its checks with evidence (accept one with a reason, or withdraw that), known
  flaws per program, programs with versions and support, firewall and listening ports, what it reported.
- **Software**: every program in the organisation, on which devices and in which versions.
- **Evidence**: the report for the organisation as text, its declarations, and the record of who did what.

A device reports counts and settings, never account names, paths or addresses, so the server says "1 account
does not require a password" and the PC's own console says which. `docker compose run --rm worker python -m
app.worker --once` judges whatever is waiting and stops.

## Tests
```
docker compose run --rm test
```
They create a database of their own in the `db` container and drop it afterwards, and judge against a tiny
made-up copy of the lists (nothing is downloaded). The important ones try to read and write one
organisation's rows as another, through the API and directly in SQL as the API's and the worker's database
roles.

## What protects what
- **Between organisations:** row-level security in the database, forced, with the API and the worker each
  connected as a role that cannot bypass it (`schema.sql`). The schema owner must be a superuser or have
  BYPASSRLS, for the three functions that turn a presented secret into an organisation and the one that
  tells the worker which devices are waiting (ids only). The worker's role cannot read keys, tokens or the
  audit log; the API's role cannot create a judgement.
- **Devices:** a PC makes its own key pair when it enrols and signs every request; the server keeps the
  public half. A request is refused if its clock is more than ten minutes off or not later than the last
  one from that device. An agent installs an update only if it is signed with the release key, which is not
  on this server (`../device-agent/release.py`); the database role of the API can read a release, not write one.
- **Secrets:** tokens and keys are random; only their SHA-256 is stored. Each is shown once. Passwords are
  scrypt hashes. The authenticator secret has to be readable to check a code, so it is encrypted with
  `FLEET_SECRET_KEY`, which is given to the API container and never stored in the database.
- **Signing in:** the second factor is required for everyone; a code works once; five wrong tries lock the
  account for 15 minutes; the session is a cookie the page cannot read (HttpOnly, SameSite=Strict, Secure
  over https) and every change also needs a header only the console adds. A share link opens one
  read-only page and nothing else.
- **Requests:** 5 MB limit, only the five known kinds of report, strict response headers (scripts only from
  the server itself).
- **Containers:** the API runs as an unprivileged user; the image that serves requests carries no test code.

## Not for production yet
A default `FLEET_SECRET_KEY` that is in this repository (make your own with `docker compose run --rm manage
secret-key`, put it in `.env`, and keep a copy: without it nobody's second factor can be checked and each
person needs theirs reset). Default passwords (set `POSTGRES_PASSWORD`, `FLEET_APP_PASSWORD` and `FLEET_WORKER_PASSWORD` in a `.env` file next to
`docker-compose.yml`), no TLS (the session cookie is only marked Secure over https), no rate limiting by
network address, no backups, no email for set-password links. These are phase 6.
