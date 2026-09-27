import pytest

from kerno.db import _to_pg
from tests.conftest import PG_URL


def test_placeholder_translation():
    assert _to_pg("SELECT * FROM t WHERE a = ? AND b = '?' AND c LIKE 'x%'") == \
        "SELECT * FROM t WHERE a = %s AND b = '?' AND c LIKE 'x%%'"


def test_migrations_are_idempotent(db):
    assert db.migrate() == []
    with db.connect() as c:
        assert c.scalar("SELECT COUNT(*) FROM symbol_registry") == 5


def test_transaction_rolls_back(db):
    with pytest.raises(RuntimeError), db.connect() as c:
        c.execute("INSERT INTO basis_log (ts_ms, spot_price, spot_ts_ms, perp_price, perp_ts_ms, basis_pct) "
                  "VALUES (1, 1, 1, 1, 1, 0)")
        raise RuntimeError("boom")
    with db.connect() as c:
        assert c.scalar("SELECT COUNT(*) FROM basis_log") == 0


def test_supabase_anon_role_is_locked_out(db):
    """On Postgres, the Supabase `anon` role (used by the public REST API) can't touch any table."""
    if db.dialect != "postgres":
        pytest.skip("postgres only")
    import psycopg

    with db.connect() as c:
        tables = [r["relname"] for r in c.fetchall(
            "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'")]
        assert tables
        for t in tables:
            assert c.scalar("SELECT relrowsecurity FROM pg_class WHERE relname = ? "
                            "AND relnamespace = 'public'::regnamespace", (t,)) is True, t
    with psycopg.connect(PG_URL) as conn:
        conn.execute("SET ROLE anon")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM trades LIMIT 1")
