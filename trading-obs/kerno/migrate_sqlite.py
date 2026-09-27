"""
One-time migration of a legacy local kerno.db (SQLite) into the configured
database (usually Supabase Postgres).

Copied:   trades, market_events (legacy Binance table, mapped to trades),
          symbol_registry, basis_log, and signals when the source already has
          the v1 schema (e.g. a local SQLite used for a full-history replay)
Skipped:  signal_outcomes and feature_store. Those were produced by code with
          look-ahead bias and non-reproducible in-place feature rewrites (see
          docs/audit.md). Regenerate signals with `kerno replay` instead.

The source file is opened read-only. Inserts are idempotent (ON CONFLICT DO
NOTHING), so the migration can be interrupted and re-run.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from kerno.db import Database
from kerno.ingest import INSERT_TRADE_SQL

logger = logging.getLogger("kerno.migrate")

BATCH = 5_000


def _tables(src: sqlite3.Connection) -> set[str]:
    return {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _columns(src: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in src.execute(f"PRAGMA table_info({table})")}


def _chunks(cur: sqlite3.Cursor) -> Iterator[list[tuple]]:
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            return
        yield rows


def _valid_trade(t: tuple) -> bool:
    _, _, tid, price, qty, side, ev, ing, _ = t
    return tid not in (None, "") and price is not None and price > 0 and qty is not None and qty >= 0 \
        and side in ("buy", "sell") and ev is not None and ing is not None


def migrate(src_path: Path, db: Database, since_days: float | None = None, with_raw: bool = False) -> dict[str, Any]:
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    tables = _tables(src)
    since_ms = int((time.time() - since_days * 86400) * 1000) if since_days else 0
    report: dict[str, Any] = {"skipped_invalid": 0}

    def copy_trades(name: str, query: str) -> None:
        n = 0
        for rows in _chunks(src.execute(query, (since_ms,))):
            good = [r for r in rows if _valid_trade(r)]
            report["skipped_invalid"] += len(rows) - len(good)
            with db.connect() as c:
                c.executemany(INSERT_TRADE_SQL, good)
            n += len(good)
            if n % (BATCH * 20) < BATCH:
                logger.info("%s: %d rows copied", name, n)
        report[name] = n

    if "trades" in tables:
        raw = "raw" if with_raw and "raw" in _columns(src, "trades") else "NULL"
        copy_trades("trades", (
            "SELECT exchange, symbol, CAST(exchange_trade_id AS TEXT), price, quantity, side, "
            f"event_time_ms, ingest_time_ms, {raw} FROM trades WHERE event_time_ms >= ? ORDER BY id"
        ))
    if "market_events" in tables:
        raw = "raw" if with_raw else "NULL"
        copy_trades("market_events", (
            "SELECT 'binance', symbol, CAST(trade_id AS TEXT), price, quantity, "
            "CASE WHEN is_buyer_maker = 1 THEN 'sell' ELSE 'buy' END, event_time_ms, ingest_time_ms, "
            f"{raw} FROM market_events WHERE event_type = 'trade' AND trade_id IS NOT NULL "
            "AND event_time_ms >= ? ORDER BY id"
        ))

    if "symbol_registry" in tables:
        cols = ["canonical_symbol", "exchange", "native_symbol", "asset_base", "asset_quote",
                "instrument_type", "tick_size", "lot_size"]
        if "instrument" in _columns(src, "symbol_registry"):
            cols.append("instrument")
        rows = src.execute(f"SELECT {', '.join(cols)} FROM symbol_registry").fetchall()
        with db.connect() as c:
            c.executemany(
                f"INSERT INTO symbol_registry ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                "ON CONFLICT DO NOTHING",
                rows,
            )
        report["symbol_registry"] = len(rows)

    if "basis_log" in tables:
        cols = ["ts_ms", "spot_price", "spot_ts_ms", "perp_price", "perp_ts_ms", "basis_pct", "okx_price", "okx_ts_ms"]
        n = 0
        for rows in _chunks(src.execute(f"SELECT {', '.join(cols)} FROM basis_log WHERE ts_ms >= ? ORDER BY ts_ms", (since_ms,))):
            with db.connect() as c:
                c.executemany(
                    f"INSERT INTO basis_log ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) ON CONFLICT DO NOTHING",
                    rows,
                )
            n += len(rows)
        report["basis_log"] = n

    if "signals" in tables and "feature_version" in _columns(src, "signals"):
        from kerno.engine import SIGNAL_COLUMNS

        outcome_cols = ["status", "price_entry", "price_10s", "price_30s", "ret_10s_bps", "ret_30s_bps",
                        "pnl_10s_bps", "pnl_30s_bps", "cost_bps", "resolved_at_ms"]
        cols = list(SIGNAL_COLUMNS) + outcome_cols
        n = 0
        cur = src.execute(f"SELECT {', '.join(cols)} FROM signals WHERE event_time_ms >= ? ORDER BY id", (since_ms,))
        for rows in _chunks(cur):
            with db.connect() as c:
                c.executemany(
                    f"INSERT INTO signals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) ON CONFLICT DO NOTHING",
                    rows,
                )
            n += len(rows)
        report["signals"] = n

    for legacy in ("signal_outcomes", "feature_store"):
        if legacy in tables:
            logger.warning("skipping legacy table %s (look-ahead / non-reproducible; see docs/audit.md)", legacy)
    src.close()
    return report
