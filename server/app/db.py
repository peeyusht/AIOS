"""Database access for the fleet server. The API connects as `fleet_app`, a role that cannot bypass row-level
security; `org()` opens a transaction with the organisation set, which is what every policy checks. A query
made outside `org()` sees no customer rows at all."""
import hashlib
import os
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://fleet_app:fleet_app@127.0.0.1:5433/fleet")


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(url(), min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=True)
    return _pool


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def digest(secret: str) -> str:
    """Secrets are random 256-bit values, so one SHA-256 is enough; only the hash is ever stored."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@contextmanager
def anon():
    """A transaction with no organisation: only the three auth functions return anything."""
    with pool().connection() as c:
        with c.transaction():
            yield c


@contextmanager
def org(org_id):
    """A transaction that can see and write one organisation's rows, and no other's."""
    with pool().connection() as c:
        with c.transaction():
            c.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
            yield c
