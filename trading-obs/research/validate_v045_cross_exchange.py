"""
v0.45 — Cross-exchange hypothesis validation runner.

Runs BinanceConnector and CoinbaseConnector concurrently for a fixed duration,
writes their canonical events to the `trades` table, then runs the 5 checks
defined in docs/connectors.md (v0.45 validation plan):

  1. Timestamp comparability
  2. Symbol registry resolution (instrument grouping)
  3. Relative latency (ingest_time_ms - event_time_ms) across exchanges
  4. Relative spread/price (BTC-USDT vs BTC-USD)
  5. Replay determinism (interleaving by event_time_ms preserves sensible order)

This is a standalone script — it does NOT modify ingestor.py or the production
pipeline. It writes to the same `trades` table (rows are tagged by `exchange`,
so production data and validation-run data coexist; validation rows can be
identified by event_time_ms falling within the run window printed at the end).

Usage:
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\validate_v045_cross_exchange.py [duration_seconds]

Default duration: 120 seconds.
"""

import asyncio
import logging
import os
import sqlite3
import sys
import time

# Allow imports of connector.py / binance_connector.py / coinbase_connector.py
# from the project root when this script is run as research\validate_v045_cross_exchange.py
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from binance_connector import BinanceConnector
from coinbase_connector import CoinbaseConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("kerno.validate_v045")

DB_PATH = "kerno.db"

INSERT_SQL = """
INSERT OR IGNORE INTO trades
    (exchange, symbol, exchange_trade_id, price, quantity, side, event_time_ms, ingest_time_ms, raw)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


async def run_connector(connector, stop: asyncio.Event, buffer: list, name: str):
    count = 0
    async for event in connector.stream(stop):
        buffer.append(event)
        count += 1
    logger.info("%s: collected %d events", name, count)


async def collect(duration_seconds: int) -> tuple[list[dict], list[dict]]:
    stop = asyncio.Event()

    binance = BinanceConnector(["BTCUSDT"])
    coinbase = CoinbaseConnector(["BTC-USD"])

    binance_events: list[dict] = []
    coinbase_events: list[dict] = []

    tasks = [
        asyncio.create_task(run_connector(binance, stop, binance_events, "binance")),
        asyncio.create_task(run_connector(coinbase, stop, coinbase_events, "coinbase")),
    ]

    logger.info("Collecting for %ds...", duration_seconds)
    await asyncio.sleep(duration_seconds)
    stop.set()

    # give connectors a moment to wind down their loops
    await asyncio.sleep(1.0)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    return binance_events, coinbase_events


def write_events(events: list[dict]) -> int:
    if not events:
        return 0
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    rows = [
        (e["exchange"], e["symbol"], e["exchange_trade_id"], e["price"], e["quantity"],
         e["side"], e["event_time_ms"], e["ingest_time_ms"], e["raw"])
        for e in events
    ]
    cur.executemany(INSERT_SQL, rows)
    con.commit()
    written = cur.rowcount  # note: rowcount for executemany w/ OR IGNORE is unreliable in sqlite3; report len instead
    con.close()
    return len(rows)


def run_checks(window_start_ms: int, window_end_ms: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("\n" + "=" * 60)
    print("CHECK 1: Timestamp comparability")
    print("=" * 60)
    cur.execute("""
        SELECT exchange, MIN(event_time_ms), MAX(event_time_ms), COUNT(*)
        FROM trades
        WHERE event_time_ms BETWEEN ? AND ?
        GROUP BY exchange
    """, (window_start_ms, window_end_ms))
    for row in cur.fetchall():
        print(f"  exchange={row[0]:10s} min_ts={row[1]} max_ts={row[2]} n={row[3]}")
    print("  -> Both ranges should fall within the run window and overlap in")
    print("     wall-clock terms (convert min/max to readable time to confirm).")

    print("\n" + "=" * 60)
    print("CHECK 2: Symbol registry resolution (instrument grouping)")
    print("=" * 60)
    cur.execute("""
        SELECT t.exchange, t.symbol, sr.instrument, sr.canonical_symbol
        FROM trades t
        LEFT JOIN symbol_registry sr
          ON sr.exchange = t.exchange AND sr.native_symbol = t.symbol
        WHERE t.event_time_ms BETWEEN ? AND ?
        GROUP BY t.exchange, t.symbol
    """, (window_start_ms, window_end_ms))
    rows = cur.fetchall()
    for row in rows:
        status = "OK" if row[2] is not None else "UNRESOLVED (missing symbol_registry entry)"
        print(f"  exchange={row[0]:10s} symbol={row[1]:10s} instrument={row[2]} canonical={row[3]} [{status}]")

    print("\n" + "=" * 60)
    print("CHECK 3: Relative latency (ingest_time_ms - event_time_ms)")
    print("=" * 60)
    cur.execute("""
        SELECT exchange,
               AVG(ingest_time_ms - event_time_ms) AS avg_latency_ms,
               MIN(ingest_time_ms - event_time_ms) AS min_latency_ms,
               MAX(ingest_time_ms - event_time_ms) AS max_latency_ms
        FROM trades
        WHERE event_time_ms BETWEEN ? AND ?
        GROUP BY exchange
    """, (window_start_ms, window_end_ms))
    for row in cur.fetchall():
        print(f"  exchange={row[0]:10s} avg={row[1]:.1f}ms min={row[2]}ms max={row[3]}ms")
    print("  -> Coinbase latency includes the 250ms batching window by design;")
    print("     expect Coinbase avg latency to run ~125-250ms higher than Binance")
    print("     for this reason alone. A difference far beyond that suggests a")
    print("     timestamp unit/format issue.")

    print("\n" + "=" * 60)
    print("CHECK 4: Relative price (BTC-USDT vs BTC-USD)")
    print("=" * 60)
    cur.execute("""
        SELECT exchange, AVG(price), MIN(price), MAX(price), COUNT(*)
        FROM trades
        WHERE event_time_ms BETWEEN ? AND ?
        GROUP BY exchange
    """, (window_start_ms, window_end_ms))
    rows = cur.fetchall()
    for row in rows:
        print(f"  exchange={row[0]:10s} avg_price={row[1]:.2f} min={row[2]:.2f} max={row[3]:.2f} n={row[4]}")
    if len(rows) == 2:
        diff_pct = (rows[1][1] - rows[0][1]) / rows[0][1] * 100
        print(f"  -> avg price diff: {diff_pct:.4f}% (USDT/USD basis; expect small, <0.1% typical)")

    print("\n" + "=" * 60)
    print("CHECK 5: Replay determinism (interleaving order)")
    print("=" * 60)
    cur.execute("""
        SELECT exchange, symbol, event_time_ms, price
        FROM trades
        WHERE event_time_ms BETWEEN ? AND ?
        ORDER BY event_time_ms ASC
        LIMIT 20
    """, (window_start_ms, window_end_ms))
    rows = cur.fetchall()
    for row in rows:
        print(f"  t={row[2]} exchange={row[0]:10s} symbol={row[1]:10s} price={row[3]}")
    print("  -> Interleaved ordering above should look like a plausible single")
    print("     timeline (no large unexplained gaps or out-of-order clusters per")
    print("     exchange). This is a visual sanity check, not a pass/fail metric.")

    con.close()


def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 120

    window_start_ms = int(time.time() * 1000)
    binance_events, coinbase_events = asyncio.run(collect(duration))
    window_end_ms = int(time.time() * 1000)

    n_b = write_events(binance_events)
    n_c = write_events(coinbase_events)
    logger.info("Wrote %d binance rows, %d coinbase rows to trades", n_b, n_c)

    if n_b == 0:
        print("\nWARNING: 0 Binance events collected — connector may have failed silently.")
    if n_c == 0:
        print("\nWARNING: 0 Coinbase events collected — connector may have failed silently.")

    run_checks(window_start_ms, window_end_ms)


if __name__ == "__main__":
    main()