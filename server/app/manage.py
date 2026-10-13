"""
Administration from the command line, as the database owner. Phase 1 has no sign-up page: organisations,
admin keys and enrolment tokens are made here. Each secret is printed once and only its hash is stored.

  python -m app.manage init                          create or update the tables, set the two application roles' passwords
  python -m app.manage org "Acme Ltd"                create an organisation
  python -m app.manage admin-key "Acme Ltd"          a console key for it
  python -m app.manage token "Acme Ltd" [--uses 5] [--days 7]     an enrolment token for its PCs
  python -m app.manage user "Acme Ltd" jo@acme.example [--role owner] [--name "Jo"]
                                                     a person who signs in to the console; prints their one-time
                                                     link for setting a password (also for a forgotten one)
  python -m app.manage list                          organisations with their device counts
  python -m app.manage secret-key                    a key for FLEET_SECRET_KEY (encrypts second-factor secrets)
"""
import argparse
import json
import os
import secrets
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from .db import digest

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


def owner_url() -> str:
    return os.environ.get("DATABASE_URL_OWNER", "postgresql://postgres:postgres@127.0.0.1:5433/fleet")


def connect():
    return psycopg.connect(owner_url(), autocommit=True)


def init(c, app_password: str | None = None) -> None:
    c.execute(SCHEMA.read_text(encoding="utf-8"))
    pw = app_password or os.environ.get("FLEET_APP_PASSWORD") or "fleet_app"
    c.execute(sql.SQL("ALTER ROLE fleet_app PASSWORD {}").format(sql.Literal(pw)))
    wpw = os.environ.get("FLEET_WORKER_PASSWORD") or "fleet_worker"
    c.execute(sql.SQL("ALTER ROLE fleet_worker PASSWORD {}").format(sql.Literal(wpw)))


def org_id(c, name: str):
    r = c.execute("SELECT id FROM organisations WHERE name = %s", (name,)).fetchone()
    if not r:
        sys.exit(f"No organisation called {name!r}. Create it with: python -m app.manage org \"{name}\"")
    return r[0]


def create_org(c, name: str):
    return c.execute("INSERT INTO organisations (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                     (name.strip(),)).fetchone()[0]


def create_admin_key(c, org, label: str = "") -> str:
    key = "sfa_" + secrets.token_urlsafe(32)
    c.execute("INSERT INTO admin_keys (org_id, key_hash, label) VALUES (%s,%s,%s)", (org, digest(key), label))
    return key


def create_token(c, org, uses: int = 1, days: int = 7, label: str = "") -> str:
    token = "sfe_" + secrets.token_urlsafe(24)
    c.execute("INSERT INTO enrolment_tokens (org_id, token_hash, label, max_uses, expires_at) VALUES (%s,%s,%s,%s, now() + make_interval(days => %s))",
              (org, digest(token), label, uses, days))
    return token


def add_release(c, manifest_text: str, signature: str, package: bytes) -> str:
    """Offer a release of the device agent to this server's devices. Refused unless it is signed with the
    release key and the installer is the one the manifest describes: a server should not hand out what no
    agent would accept."""
    import release as rel
    m = rel.verify(manifest_text, signature)
    rel.check_package(m, package)
    c.execute("INSERT INTO agent_releases (version, manifest, signature, package) VALUES (%s,%s,%s,%s) "
              "ON CONFLICT (version) DO UPDATE SET manifest = EXCLUDED.manifest, signature = EXCLUDED.signature, "
              "package = EXCLUDED.package, published_at = now(), withdrawn = false",
              (m["version"], manifest_text, signature, package))
    return m["version"]


def release_from_folder(folder: Path, version: str | None = None) -> tuple:
    """(manifest text, signature, installer bytes) of the release in a folder as the build leaves it."""
    found = sorted(folder.glob(f"*{version}.json" if version else "*.json"))
    if len(found) != 1:
        sys.exit(f"Expected one release manifest (*.json) in {folder}, found {len(found)}. Name the version with --version.")
    text = found[0].read_text(encoding="utf-8")
    sig = found[0].with_suffix(".sig")
    try:
        name = json.loads(text)["file"]
        package = (folder / Path(str(name)).name).read_bytes()
        return text, sig.read_text(encoding="ascii").strip(), package
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f"The release in {folder} is not complete (manifest, .sig and the .msi it names): {e}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app.manage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("list")
    sub.add_parser("secret-key")
    u = sub.add_parser("user")
    u.add_argument("org")
    u.add_argument("email")
    u.add_argument("--role", default="owner", choices=["owner", "admin", "auditor"])
    u.add_argument("--name", default="")
    o = sub.add_parser("org")
    o.add_argument("name")
    k = sub.add_parser("admin-key")
    k.add_argument("org")
    k.add_argument("--label", default="")
    t = sub.add_parser("token")
    t.add_argument("org")
    t.add_argument("--uses", type=int, default=1)
    t.add_argument("--days", type=int, default=7)
    t.add_argument("--label", default="")
    r = sub.add_parser("release", help="offer a signed release of the device agent to this server's devices")
    r.add_argument("action", choices=["add", "list", "withdraw"])
    r.add_argument("what", nargs="?", default="", help="add: the folder the build wrote; withdraw: the version")
    r.add_argument("--version", default="")
    a = ap.parse_args()
    if a.cmd == "secret-key":       # needs no database
        from cryptography.fernet import Fernet
        print("Put this line in server/.env and keep a copy somewhere safe. Without it nobody's second factor can be checked:")
        print("FLEET_SECRET_KEY=" + Fernet.generate_key().decode())
        return
    with connect() as c:
        if a.cmd == "init":
            init(c)
            print("Tables are in place.")
        elif a.cmd == "org":
            print(f"Organisation {a.name!r}: {create_org(c, a.name)}")
        elif a.cmd == "admin-key":
            print("Console key (shown once, store it safely):")
            print(create_admin_key(c, org_id(c, a.org), a.label))
        elif a.cmd == "token":
            print(f"Enrolment token for {a.org!r}, {a.uses} use(s), valid {a.days} day(s) (shown once):")
            print(create_token(c, org_id(c, a.org), a.uses, a.days, a.label))
        elif a.cmd == "user":
            from . import auth, people
            try:
                token = people.add_first_user(c, org_id(c, a.org), a.email, a.role, a.name)
            except ValueError as e:
                sys.exit(str(e))
            base = (os.environ.get("PUBLIC_URL") or "http://127.0.0.1:8770").rstrip("/")
            print(f"{a.email} is {a.role} of {a.org!r}. Their link to set a password (works once, for {auth.SETUP_DAYS} days):")
            print(f"{base}/#/setup/{token}")
        elif a.cmd == "release":
            if a.action == "add":
                if not a.what:
                    sys.exit("Usage: manage release add <folder with the .msi, .json and .sig>")
                try:
                    v = add_release(c, *release_from_folder(Path(a.what), a.version or None))
                except ValueError as e:
                    sys.exit(f"Not published: {e}")
                print(f"Release {v} is on offer. Each device asks at its next report and installs it if it is newer than what it runs.")
            elif a.action == "withdraw":
                n = c.execute("UPDATE agent_releases SET withdrawn = true WHERE version = %s", (a.what,)).rowcount
                print(f"Release {a.what} is no longer offered." if n else f"No release {a.what!r}.")
                print("A PC that already installed it keeps it: an agent never goes back to an older version.")
            else:
                rows = c.execute("SELECT version, published_at, withdrawn, octet_length(package) FROM agent_releases ORDER BY published_at").fetchall()
                for v, at, gone, size in rows:
                    print(f"{v}  {at:%Y-%m-%d %H:%M}  {size / 1e6:.1f} MB{'  withdrawn' if gone else ''}")
                if not rows:
                    print("No releases.")
        elif a.cmd == "list":
            for name, n in c.execute("SELECT o.name, count(d.id) FROM organisations o LEFT JOIN devices d ON d.org_id = o.id GROUP BY o.name ORDER BY o.name"):
                print(f"{name}: {n} device(s)")


if __name__ == "__main__":
    main()
