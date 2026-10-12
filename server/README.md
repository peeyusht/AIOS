# Fleet server (phase 1)

The central server from `docs/architecture.md`: PCs enrol and report what is installed; an administrator
sees the list of devices. No judging of flaws or compliance yet (phase 2), no remote actions (phase 5).

## Run it on this machine
```
cd server
docker compose up -d --build        # PostgreSQL on 127.0.0.1:5433, the API and fleet page on 127.0.0.1:8770
```
Both are reachable from this machine only. `docker compose down` stops them and keeps the data;
`docker compose down -v` also deletes the database.

## First organisation, key and token
Run these with the server's Python environment (`python -m venv .venv`, then
`.venv\Scripts\python -m pip install -r requirements.txt httpx`):
```
.venv\Scripts\python -m app.manage org "Acme Ltd"
.venv\Scripts\python -m app.manage admin-key "Acme Ltd"          # console key, shown once
.venv\Scripts\python -m app.manage token "Acme Ltd" --uses 5     # enrolment token, shown once
```
Open http://127.0.0.1:8770 and paste the console key.

## Enrol a PC
On the PC, in `shadow-filer`:
```
.venv\Scripts\python shadow_agent.py fleet show                  # exactly what would be sent
.venv\Scripts\python shadow_agent.py fleet enrol http://127.0.0.1:8770 <token>
.venv\Scripts\python shadow_agent.py fleet checkin               # now; afterwards every 15 minutes while the agent runs
.venv\Scripts\python shadow_agent.py fleet status
.venv\Scripts\python shadow_agent.py fleet leave                 # stop reporting and forget the key
```
The agent refuses a plain `http://` server unless it is localhost. A PC on another machine needs the server
behind HTTPS (phase 6 adds the proxy to the compose file).

## Tests
```
.venv\Scripts\python -m unittest discover -s tests
```
They need the compose PostgreSQL running, create a throwaway database in it and drop it afterwards, and are
skipped when it is not there. The important ones try to read and write one organisation's rows as another,
through the API and directly in SQL as the application's database role.

## What protects what
- **Between organisations:** row-level security in the database, forced, with the API connected as a role
  that cannot bypass it (`schema.sql`). The schema owner must be a superuser or have BYPASSRLS, for the three
  functions that turn a presented secret into an organisation.
- **Secrets:** tokens and keys are random; only their SHA-256 is stored. Each is printed once.
- **Requests:** 5 MB limit, only the five known kinds of report, strict response headers.

## Not for production yet
Default passwords in `docker-compose.yml` (set `POSTGRES_PASSWORD` and `FLEET_APP_PASSWORD`), no TLS, no rate
limiting, no backups, console access by a shared key instead of named users. These are phases 3 and 6.
