"""Database access. Every transaction carries a security context that Postgres row-level security enforces."""
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg2
import psycopg2.extras

import config

psycopg2.extras.register_uuid()


@dataclass(frozen=True)
class Ctx:
    role: str
    org_id: str = ""
    user_id: str = ""


SYSTEM = Ctx(role="system")


@contextmanager
def tx(ctx: Ctx = SYSTEM):
    conn = psycopg2.connect(config.DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor,
                            options="-c search_path=app")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.role', %s, true), set_config('app.org_id', %s, true), "
                "set_config('app.user_id', %s, true)",
                (ctx.role, str(ctx.org_id or ""), str(ctx.user_id or "")),
            )
            yield cur
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def Json(value):
    return psycopg2.extras.Json(value)
