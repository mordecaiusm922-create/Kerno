"""
Ingestion: exchange connectors -> canonical `trades` table.

- One task per connector, all feeding a bounded queue.
- A single writer drains the queue in batches and inserts with
  ON CONFLICT DO NOTHING (reconnect duplicates are harmless).
- DB errors are retried with backoff; the batch is kept, not dropped.
- If the queue overflows (DB down for a long time) trades are dropped and
  counted loudly; dropped/gap counters are logged every minute.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from typing import Any

from kerno.connectors import build_connector
from kerno.db import Database

logger = logging.getLogger("kerno.ingest")

QUEUE_MAX = 200_000
BATCH_MAX = 2_000
BATCH_WAIT_S = 1.0

INSERT_TRADE_SQL = """
    INSERT INTO trades (exchange, symbol, exchange_trade_id, price, quantity, side,
                        event_time_ms, ingest_time_ms, raw)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT DO NOTHING
"""


def write_trades(db: Database, trades: list[dict[str, Any]], store_raw: bool) -> None:
    with db.connect() as c:
        c.executemany(INSERT_TRADE_SQL, (
            (t["exchange"], t["symbol"], t["exchange_trade_id"], t["price"], t["quantity"], t["side"],
             t["event_time_ms"], t["ingest_time_ms"], t["raw"] if store_raw else None)
            for t in trades
        ))


class Stats:
    def __init__(self) -> None:
        self.received: Counter[str] = Counter()
        self.written = 0
        self.dropped = 0
        self.gaps: Counter[str] = Counter()
        self._last_id: dict[str, int] = {}

    def observe(self, t: dict[str, Any]) -> None:
        key = f"{t['exchange']}:{t['symbol']}"
        self.received[key] += 1
        # Binance and Bybit-style numeric sequential ids let us detect missed trades
        if t["exchange"] == "binance":
            tid = int(t["exchange_trade_id"])
            last = self._last_id.get(key)
            if last is not None and tid > last + 1:
                self.gaps[key] += tid - last - 1
            self._last_id[key] = max(tid, last or tid)


async def _pump(connector, queue: asyncio.Queue, stats: Stats, stop: asyncio.Event) -> None:
    async for trade in connector.stream(stop):
        stats.observe(trade)
        try:
            queue.put_nowait(trade)
        except asyncio.QueueFull:
            stats.dropped += 1
            if stats.dropped % 10_000 == 1:
                logger.error("ingest queue full: %d trades dropped so far (database unavailable?)", stats.dropped)


async def _writer(db: Database, queue: asyncio.Queue, stats: Stats, stop: asyncio.Event, store_raw: bool) -> None:
    backoff = 1.0
    batch: list[dict[str, Any]] = []
    while not (stop.is_set() and queue.empty() and not batch):
        if not batch:
            deadline = time.monotonic() + BATCH_WAIT_S
            while len(batch) < BATCH_MAX:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(queue.get(), timeout=timeout))
                except TimeoutError:
                    break
            if not batch:
                continue
        try:
            await asyncio.to_thread(write_trades, db, batch, store_raw)
            stats.written += len(batch)
            batch = []
            backoff = 1.0
        except Exception as exc:
            if stop.is_set() and backoff >= 8:
                lost = len(batch) + queue.qsize()
                stats.dropped += lost
                logger.error("shutting down with database unavailable: %d trades not written", lost)
                return
            logger.error("trade write failed (%s: %s); retrying %d trades in %.0fs",
                         type(exc).__name__, exc, len(batch), backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


async def _report(stats: Stats, stop: asyncio.Event, queue: asyncio.Queue) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except TimeoutError:
            pass
        logger.info("ingest stats received=%s written=%d queued=%d dropped=%d gaps=%s",
                    dict(stats.received), stats.written, queue.qsize(), stats.dropped, dict(stats.gaps))


async def run_ingest(db: Database, streams: dict[str, list[str]], stop: asyncio.Event,
                     store_raw: bool = False) -> Stats:
    queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
    stats = Stats()
    connectors = [build_connector(ex, syms) for ex, syms in streams.items()]
    logger.info("ingesting %s", streams)
    pumps = [asyncio.create_task(_pump(c, queue, stats, stop)) for c in connectors]
    writer = asyncio.create_task(_writer(db, queue, stats, stop, store_raw))
    reporter = asyncio.create_task(_report(stats, stop, queue))
    await stop.wait()
    for p in pumps:
        p.cancel()
    await asyncio.gather(*pumps, return_exceptions=True)
    await writer  # drains what is queued
    reporter.cancel()
    logger.info("ingest stopped: written=%d dropped=%d", stats.written, stats.dropped)
    return stats
