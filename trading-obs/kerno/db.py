"""
Storage layer: one small API over SQLite (local research, tests) and
PostgreSQL (Supabase or any managed Postgres in production).

SQL in this codebase is written once, with `?` placeholders and syntax both
engines support (ON CONFLICT DO NOTHING, row values). For Postgres the
placeholders are rewritten to `%s`.

    db = Database("postgresql://...")        # or "sqlite:///kerno.db"
    with db.connect() as c:                   # one transaction
        rows = c.fetchall("SELECT ... WHERE symbol = ?", (sym,))
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any

logger = logging.getLogger("kerno.db")

_PLACEHOLDER = re.compile(r"'[^']*'|\?")


def _to_pg(sql: str) -> str:
    # replace ? outside single-quoted literals; escape literal % for psycopg
    sql = sql.replace("%", "%%")
    return _PLACEHOLDER.sub(lambda m: "%s" if m.group(0) == "?" else m.group(0), sql)


class Conn:
    """Thin wrapper giving both engines the same fetch API and dict rows."""

    def __init__(self, raw: Any, dialect: str):
        self.raw = raw
        self.dialect = dialect

    def _sql(self, sql: str) -> str:
        return _to_pg(sql) if self.dialect == "postgres" else sql

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        cur = self.raw.execute(self._sql(sql), tuple(params))
        return cur.rowcount

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        rows = [tuple(r) for r in rows]
        if not rows:
            return
        if self.dialect == "postgres":
            with self.raw.cursor() as cur:
                cur.executemany(self._sql(sql), rows)
        else:
            self.raw.executemany(sql, rows)

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = self.raw.execute(self._sql(sql), tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        cur = self.raw.execute(self._sql(sql), tuple(params))
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.fetchone(sql, params)
        return None if row is None else next(iter(row.values()))

    def iter_rows(self, sql: str, params: Sequence[Any] = (), batch: int = 10_000) -> Iterator[dict[str, Any]]:
        """Stream a large result set without loading it all in memory."""
        if self.dialect == "postgres":
            with self.raw.cursor(name="kerno_stream") as cur:  # server-side cursor
                cur.itersize = batch
                cur.execute(self._sql(sql), tuple(params))
                for row in cur:
                    yield dict(row)
        else:
            cur = self.raw.execute(sql, tuple(params))
            while True:
                chunk = cur.fetchmany(batch)
                if not chunk:
                    break
                for row in chunk:
                    yield dict(row)


class Database:
    def __init__(self, url: str, pool_size: int = 5):
        self.url = url
        if url.startswith(("postgres://", "postgresql://")):
            self.dialect = "postgres"
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(
                url,
                min_size=1,
                max_size=pool_size,
                # prepare_threshold=None keeps us compatible with Supabase's
                # transaction pooler (PgBouncer/Supavisor, port 6543)
                kwargs={"row_factory": dict_row, "prepare_threshold": None},
                open=True,
            )
        else:
            self.dialect = "sqlite"
            path = url.removeprefix("sqlite:///").removeprefix("sqlite://")
            self.path = path
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        if self.dialect == "postgres":
            self._pool.close()

    @contextmanager
    def connect(self) -> Iterator[Conn]:
        """One transaction: commit on success, rollback on error."""
        if self.dialect == "postgres":
            with self._pool.connection() as raw:  # commits / rolls back on exit
                yield Conn(raw, "postgres")
        else:
            raw = sqlite3.connect(self.path, timeout=30)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA journal_mode=WAL")
            raw.execute("PRAGMA synchronous=NORMAL")
            raw.execute("PRAGMA foreign_keys=ON")
            try:
                yield Conn(raw, "sqlite")
                raw.commit()
            except BaseException:
                raw.rollback()
                raise
            finally:
                raw.close()

    # ── migrations ──────────────────────────────────────────────────────────
    def migrate(self) -> list[str]:
        """Apply pending schema migrations in order. Idempotent."""
        folder = resources.files("kerno") / "schema" / self.dialect
        files = sorted(p for p in folder.iterdir() if p.name.endswith(".sql"))
        applied_now: list[str] = []
        with self.connect() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version TEXT PRIMARY KEY, applied_at_ms BIGINT NOT NULL)"
            )
            done = {r["version"] for r in c.fetchall("SELECT version FROM schema_migrations")}
        for f in files:
            version = f.name.removesuffix(".sql")
            if version in done:
                continue
            script = f.read_text(encoding="utf-8")
            with self.connect() as c:
                if self.dialect == "postgres":
                    c.raw.execute(script)
                else:
                    c.raw.executescript(script)
                c.execute(
                    "INSERT INTO schema_migrations (version, applied_at_ms) VALUES (?, ?)",
                    (version, _now_ms()),
                )
            logger.info("applied migration %s", version)
            applied_now.append(version)
        return applied_now


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


_DB: Database | None = None


def get_db(url: str | None = None) -> Database:
    """Process-wide Database (pool) singleton."""
    global _DB
    if _DB is None or (url is not None and url != _DB.url):
        from kerno.config import get_settings

        _DB = Database(url or get_settings().database_url)
    return _DB
