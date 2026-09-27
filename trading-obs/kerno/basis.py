"""
Spot-vs-perp basis sampler.

Every SAMPLE_INTERVAL_S it reads the latest trade of each leg from `trades`
(written by the ingestor - no extra websocket connections) and logs a basis
observation if both legs are fresh.

    basis_pct = (perp - spot) / spot * 100
"""

from __future__ import annotations

import logging
import threading
import time

from kerno.db import Conn, Database

logger = logging.getLogger("kerno.basis")

SPOT = ("binance", "BTCUSDT")
PERP = ("bybit", "BTCUSDT-PERP")
REF = ("okx", "BTC-USDT")
SAMPLE_INTERVAL_S = 30
STALENESS_MS = 60_000


def _latest(c: Conn, leg: tuple[str, str], since_ms: int) -> dict | None:
    return c.fetchone(
        "SELECT price, event_time_ms FROM trades WHERE exchange = ? AND symbol = ? AND event_time_ms >= ? "
        "ORDER BY event_time_ms DESC, exchange_trade_id DESC LIMIT 1",
        (leg[0], leg[1], since_ms),
    )


def sample_basis(db: Database, now_ms: int | None = None) -> dict | None:
    now_ms = now_ms or int(time.time() * 1000)
    since = now_ms - STALENESS_MS
    with db.connect() as c:
        spot, perp, ref = (_latest(c, leg, since) for leg in (SPOT, PERP, REF))
        if not spot or not perp:
            return None
        row = {
            "ts_ms": now_ms,
            "spot_price": float(spot["price"]),
            "spot_ts_ms": int(spot["event_time_ms"]),
            "perp_price": float(perp["price"]),
            "perp_ts_ms": int(perp["event_time_ms"]),
            "basis_pct": (float(perp["price"]) - float(spot["price"])) / float(spot["price"]) * 100,
            "okx_price": float(ref["price"]) if ref else None,
            "okx_ts_ms": int(ref["event_time_ms"]) if ref else None,
        }
        c.execute(
            "INSERT INTO basis_log (ts_ms, spot_price, spot_ts_ms, perp_price, perp_ts_ms, basis_pct, okx_price, okx_ts_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            tuple(row.values()),
        )
    return row


def run_basis(db: Database, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            row = sample_basis(db)
            if row:
                logger.info("basis %+.4f%% spot=%.2f perp=%.2f", row["basis_pct"], row["spot_price"], row["perp_price"])
            else:
                logger.info("basis: waiting for fresh spot and perp trades")
        except Exception:
            logger.exception("basis sample failed")
        stop.wait(SAMPLE_INTERVAL_S)
