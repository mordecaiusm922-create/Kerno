"""
Kerno — basis logger (v0.75)

Long-running process (not a fixed-duration validation run): keeps
BinanceConnector (spot), BybitConnector (perp), and OKXConnector (spot,
cross-check) alive indefinitely, and every SAMPLE_INTERVAL_S seconds logs a
basis observation to basis_log.

This is the "depth over breadth" move: rather than adding a 5th exchange,
turn the repeated spot-vs-perp discount pattern (observed twice, independently,
during v0.55 and v0.65 validation runs) into an actual time series with
enough samples to say something statistically meaningful.

Also writes raw trades to `trades` (same as the validation runners) so the
underlying tick data keeps accumulating for future analysis.

Usage:
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\basis_logger.py

Stop with Ctrl+C. Runs until stopped — leave it running in a terminal for
hours/days to accumulate real basis history.

Resilience note: this grows kerno.db over time (raw trades + basis samples).
Run research/backup_kerno_db.py periodically while this is running, and keep
an eye on free disk space (this script does NOT check disk space itself).
"""

import asyncio
import logging
import os
import signal
import sqlite3
import sys
import time

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from binance_connector import BinanceConnector
from bybit_connector import BybitConnector
from okx_connector import OKXConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("kerno.basis_logger")

DB_PATH = "kerno.db"
SAMPLE_INTERVAL_S = 30
STALENESS_THRESHOLD_MS = 60_000  # don't log a basis sample if either price is older than this
TRADE_FLUSH_INTERVAL_S = 10

INSERT_TRADE_SQL = """
INSERT OR IGNORE INTO trades
    (exchange, symbol, exchange_trade_id, price, quantity, side, event_time_ms, ingest_time_ms, raw)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

INSERT_BASIS_SQL = """
INSERT INTO basis_log
    (ts_ms, spot_price, spot_ts_ms, perp_price, perp_ts_ms, basis_pct, okx_price, okx_ts_ms)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

# Shared last-seen state, updated by each connector's task
last_seen: dict[str, dict] = {
    "binance": {"price": None, "ts_ms": None},
    "bybit":   {"price": None, "ts_ms": None},
    "okx":     {"price": None, "ts_ms": None},
}

trade_buffer: list[dict] = []


async def run_connector(connector, stop: asyncio.Event, key: str):
    async for event in connector.stream(stop):
        last_seen[key]["price"] = event["price"]
        last_seen[key]["ts_ms"] = event["event_time_ms"]
        trade_buffer.append(event)


async def flush_trades_loop(stop: asyncio.Event):
    con = sqlite3.connect(DB_PATH)
    while not stop.is_set():
        await asyncio.sleep(TRADE_FLUSH_INTERVAL_S)
        if not trade_buffer:
            continue
        batch, trade_buffer[:] = trade_buffer[:], []
        rows = [
            (e["exchange"], e["symbol"], e["exchange_trade_id"], e["price"], e["quantity"],
             e["side"], e["event_time_ms"], e["ingest_time_ms"], e["raw"])
            for e in batch
        ]
        con.executemany(INSERT_TRADE_SQL, rows)
        con.commit()
        logger.info("Flushed %d trades to trades table", len(rows))
    con.close()


async def basis_sample_loop(stop: asyncio.Event):
    con = sqlite3.connect(DB_PATH)
    while not stop.is_set():
        await asyncio.sleep(SAMPLE_INTERVAL_S)

        spot = last_seen["binance"]
        perp = last_seen["bybit"]
        okx = last_seen["okx"]

        if spot["price"] is None or perp["price"] is None:
            logger.info("Waiting for both spot and perp prices before first sample...")
            continue

        now_ms = int(time.time() * 1000)
        if (now_ms - spot["ts_ms"] > STALENESS_THRESHOLD_MS or
                now_ms - perp["ts_ms"] > STALENESS_THRESHOLD_MS):
            logger.warning("Skipping sample: stale price data (spot or perp feed may have dropped)")
            continue

        basis_pct = (perp["price"] - spot["price"]) / spot["price"] * 100

        con.execute(INSERT_BASIS_SQL, (
            now_ms, spot["price"], spot["ts_ms"], perp["price"], perp["ts_ms"],
            basis_pct, okx["price"], okx["ts_ms"],
        ))
        con.commit()

        direction = "premium" if basis_pct > 0 else "discount"
        logger.info(
            "basis sample: spot=%.2f perp=%.2f basis=%+.4f%% (%s)",
            spot["price"], perp["price"], basis_pct, direction,
        )
    con.close()


async def run():
    stop = asyncio.Event()

    binance = BinanceConnector(["BTCUSDT"])
    bybit = BybitConnector(["BTCUSDT"])
    okx = OKXConnector(["BTC-USDT"])

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler — Ctrl+C still works

    tasks = [
        asyncio.create_task(run_connector(binance, stop, "binance")),
        asyncio.create_task(run_connector(bybit, stop, "bybit")),
        asyncio.create_task(run_connector(okx, stop, "okx")),
        asyncio.create_task(flush_trades_loop(stop)),
        asyncio.create_task(basis_sample_loop(stop)),
    ]

    logger.info("Basis logger running. Sampling every %ds. Ctrl+C to stop.", SAMPLE_INTERVAL_S)

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except KeyboardInterrupt:
        stop.set()

    logger.info("Basis logger stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(run())
