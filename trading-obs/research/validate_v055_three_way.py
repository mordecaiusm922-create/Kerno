"""
v0.55 — Three-way cross-exchange validation runner.

Runs BinanceConnector (BTCUSDT spot), CoinbaseConnector (BTC-USD spot), and
BybitConnector (BTCUSDT linear perpetual, emitted as BTCUSDT-PERP) concurrently
for a fixed duration, writes to `trades`, then runs checks:

  1. Symbol collision check: BTCUSDT (binance) and BTCUSDT-PERP (bybit) are
     distinct rows in trades — Finding #2 enforced by construction.
  2. Symbol registry resolution: all 3 exchanges/symbols resolve to instrument='BTC'
  3. Spot vs perp basis: price delta between Binance spot and Bybit perp
     (sign and magnitude indicate whether perp is trading at premium or discount)
  4. Trade rate comparison: BTC-USDT vs BTC-USDT-PERP activity levels
  5. Timestamp sanity: all 3 feeds in same epoch/unit

Usage:
    C:\\Users\\usuario\\AppData\\Local\\Programs\\Python\\Python311\\python.exe research\\validate_v055_three_way.py [duration_seconds]

Default duration: 120 seconds.
"""

import asyncio
import logging
import os
import sqlite3
import sys
import time

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from binance_connector import BinanceConnector
from coinbase_connector import CoinbaseConnector
from bybit_connector import BybitConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("kerno.validate_v055")

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


async def collect(duration_seconds: int):
    stop = asyncio.Event()

    binance  = BinanceConnector(["BTCUSDT"])
    coinbase = CoinbaseConnector(["BTC-USD"])
    bybit    = BybitConnector(["BTCUSDT"])

    binance_events:  list[dict] = []
    coinbase_events: list[dict] = []
    bybit_events:    list[dict] = []

    tasks = [
        asyncio.create_task(run_connector(binance,  stop, binance_events,  "binance")),
        asyncio.create_task(run_connector(coinbase, stop, coinbase_events, "coinbase")),
        asyncio.create_task(run_connector(bybit,    stop, bybit_events,    "bybit")),
    ]

    logger.info("Collecting for %ds (3 connectors)...", duration_seconds)
    await asyncio.sleep(duration_seconds)
    stop.set()
    await asyncio.sleep(1.0)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    return binance_events, coinbase_events, bybit_events


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
    con.close()
    return len(rows)


def run_checks(window_start_ms: int, window_end_ms: int):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    print("\n" + "=" * 60)
    print("CHECK 1: Symbol collision safety (Finding #2)")
    print("=" * 60)
    cur.execute("""
        SELECT exchange, symbol, COUNT(*) as n
        FROM trades
        WHERE event_time_ms BETWEEN ? AND ?
        GROUP BY exchange, symbol
        ORDER BY exchange
    """, (window_start_ms, window_end_ms))
    rows = cur.fetchall()
    for row in rows:
        print(f"  exchange={row[0]:10s} symbol={row[1]:15s} n={row[2]}")
    symbols_seen = {row[1] for row in rows}
    collision = "BTCUSDT" in symbols_seen and "BTCUSDT-PERP" in symbols_seen
    print(f"  -> BTCUSDT and BTCUSDT-PERP coexist as distinct symbols: {'YES (correct)' if collision else 'MISSING DATA'}")

    print("\n" + "=" * 60)
    print("CHECK 2: Symbol registry resolution (all 3 -> instrument=BTC)")
    print("=" * 60)
    cur.execute("""
        SELECT t.exchange, t.symbol, sr.instrument, sr.canonical_symbol, sr.instrument_type
        FROM trades t
        LEFT JOIN symbol_registry sr
          ON sr.exchange = t.exchange AND sr.native_symbol = t.symbol
        WHERE t.event_time_ms BETWEEN ? AND ?
          AND t.exchange IN ('binance', 'coinbase', 'bybit')
        GROUP BY t.exchange, t.symbol
    """, (window_start_ms, window_end_ms))
    for row in cur.fetchall():
        status = "OK" if row[2] is not None else "UNRESOLVED"
        print(f"  {row[0]:10s} {row[1]:15s} instrument={row[2]} canonical={row[3]} type={row[4]} [{status}]")

    print("\n" + "=" * 60)
    print("CHECK 3: Spot vs perp basis (Binance BTCUSDT vs Bybit BTCUSDT-PERP)")
    print("=" * 60)
    cur.execute("""
        SELECT exchange, symbol, AVG(price) as avg_p, MIN(price), MAX(price), COUNT(*)
        FROM trades
        WHERE event_time_ms BETWEEN ? AND ?
          AND exchange IN ('binance', 'bybit')
        GROUP BY exchange, symbol
    """, (window_start_ms, window_end_ms))
    rows = cur.fetchall()
    for row in rows:
        print(f"  {row[0]:10s} {row[1]:15s} avg={row[2]:.2f} min={row[3]:.2f} max={row[4]:.2f} n={row[5]}")
    if len(rows) == 2:
        spot = next((r for r in rows if r[0] == "binance"), None)
        perp = next((r for r in rows if r[0] == "bybit"), None)
        if spot and perp:
            basis_pct = (perp[2] - spot[2]) / spot[2] * 100
            direction = "PREMIUM" if basis_pct > 0 else "DISCOUNT"
            print(f"  -> basis: {basis_pct:+.4f}% ({direction} — perp {'above' if basis_pct > 0 else 'below'} spot)")
            print(f"     (positive basis = market is bullish/leveraged long; negative = bearish/deleveraging)")

    print("\n" + "=" * 60)
    print("CHECK 4: Trade rate across 3 venues")
    print("=" * 60)
    duration_s = (window_end_ms - window_start_ms) / 1000
    cur.execute("""
        SELECT exchange, symbol, COUNT(*) as n
        FROM trades
        WHERE event_time_ms BETWEEN ? AND ?
        GROUP BY exchange, symbol
        ORDER BY n DESC
    """, (window_start_ms, window_end_ms))
    for row in cur.fetchall():
        rate = row[2] / duration_s
        print(f"  {row[0]:10s} {row[1]:15s} {row[2]:5d} trades ({rate:.1f} trades/s)")

    print("\n" + "=" * 60)
    print("CHECK 5: Timestamp sanity (all 3 feeds)")
    print("=" * 60)
    cur.execute("""
        SELECT exchange, symbol, MIN(event_time_ms), MAX(event_time_ms)
        FROM trades
        WHERE event_time_ms BETWEEN ? AND ?
        GROUP BY exchange, symbol
    """, (window_start_ms, window_end_ms))
    for row in cur.fetchall():
        span_s = (row[3] - row[2]) / 1000
        print(f"  {row[0]:10s} {row[1]:15s} span={span_s:.1f}s min_ts={row[2]} max_ts={row[3]}")
    print(f"  -> run window: {window_start_ms} -> {window_end_ms} ({duration_s:.0f}s)")
    print(f"     all spans should be <= {duration_s:.0f}s and non-zero")

    con.close()


def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 120

    window_start_ms = int(time.time() * 1000)
    b, c, by = asyncio.run(collect(duration))
    window_end_ms = int(time.time() * 1000)

    nb  = write_events(b)
    nc  = write_events(c)
    nby = write_events(by)
    logger.info("Wrote: binance=%d coinbase=%d bybit=%d rows to trades", nb, nc, nby)

    if nb == 0:
        print("WARNING: 0 Binance events")
    if nc == 0:
        print("WARNING: 0 Coinbase events")
    if nby == 0:
        print("WARNING: 0 Bybit events — connector may have failed, check logs above")

    run_checks(window_start_ms, window_end_ms)


if __name__ == "__main__":
    main()