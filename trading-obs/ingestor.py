"""
Kerno — Binance WebSocket ingestor (SQLite dev mode)

Uso:
  python ingestor.py
  python ingestor.py --symbols BTCUSDT ETHUSDT SOLUSDT
"""
import asyncio
import json
import logging
import signal
import time
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from db.connection import get_conn, init_db

# ── Config ─────────────────────────────────────────────────────────────────
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"
BATCH_SIZE      = 50
BATCH_TIMEOUT   = 2.0
RECONNECT_DELAY = 3
MAX_BUFFER      = 5_000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("kerno.ingestor")


# ── Parser ──────────────────────────────────────────────────────────────────
def parse_trade(raw: dict) -> dict | None:
    if raw.get("e") != "trade":
        return None
    return {
        "symbol":         raw["s"],
        "event_type":     "trade",
        "price":          float(raw["p"]),
        "quantity":       float(raw["q"]),
        "event_time_ms":  raw["T"],
        "ingest_time_ms": int(time.time() * 1000),
        "trade_id":       raw["t"],
        "is_buyer_maker": 1 if raw["m"] else 0,
        "raw":            json.dumps(raw),
    }


# ── Batch writer ─────────────────────────────────────────────────────────────
class BatchWriter:
    INSERT_SQL = """
        INSERT INTO market_events
            (symbol, event_type, price, quantity,
             event_time_ms, ingest_time_ms, trade_id, is_buyer_maker, raw)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    def __init__(self):
        self._buffer: list[dict] = []
        self._last_flush = time.monotonic()

    async def add(self, event: dict):
        if len(self._buffer) >= MAX_BUFFER:
            logger.warning("Buffer overflow — dropping oldest event")
            self._buffer.pop(0)

        self._buffer.append(event)

        if (len(self._buffer) >= BATCH_SIZE or
                time.monotonic() - self._last_flush >= BATCH_TIMEOUT):
            await self.flush()

    async def flush(self):
        if not self._buffer:
            return

        rows = [
            (e["symbol"], e["event_type"], e["price"], e["quantity"],
             e["event_time_ms"], e["ingest_time_ms"],
             e["trade_id"], e["is_buyer_maker"], e["raw"])
            for e in self._buffer
        ]

        try:
            conn = get_conn()
            conn.executemany(self.INSERT_SQL, rows)
            conn.commit()
            conn.close()
            logger.info("Flush → %d eventos guardados", len(rows))
        except Exception as exc:
            logger.error("DB flush error: %s", exc)
            raise

        self._buffer.clear()
        self._last_flush = time.monotonic()


# ── Stream por símbolo ────────────────────────────────────────────────────────
async def stream_symbol(symbol: str, writer: BatchWriter, stop: asyncio.Event):
    url = f"{BINANCE_WS_BASE}/{symbol.lower()}@trade"
    logger.info("Conectando → %s", url)

    while not stop.is_set():
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                logger.info("[%s] Conectado ✓", symbol)
                async for raw_msg in ws:
                    if stop.is_set():
                        break
                    try:
                        event = parse_trade(json.loads(raw_msg))
                        if event:
                            await writer.add(event)
                    except (json.JSONDecodeError, KeyError) as exc:
                        logger.warning("[%s] Parse error: %s", symbol, exc)

        except ConnectionClosed as exc:
            logger.warning("[%s] WS cerrado (%s) — reconectando en %ds", symbol, exc.code, RECONNECT_DELAY)
        except OSError as exc:
            logger.error("[%s] Error de red: %s", symbol, exc)

        if not stop.is_set():
            await asyncio.sleep(RECONNECT_DELAY)


async def flush_loop(writer: BatchWriter, stop: asyncio.Event):
    while not stop.is_set():
        await asyncio.sleep(BATCH_TIMEOUT)
        await writer.flush()


# ── Main ──────────────────────────────────────────────────────────────────────
async def run(symbols: list[str]):
    init_db()

    stop   = asyncio.Event()
    writer = BatchWriter()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows no soporta add_signal_handler — Ctrl+C igual funciona

    tasks = [
        asyncio.create_task(stream_symbol(s, writer, stop)) for s in symbols
    ] + [asyncio.create_task(flush_loop(writer, stop))]

    logger.info("Kerno corriendo — símbolos: %s", symbols)

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except KeyboardInterrupt:
        stop.set()

    await writer.flush()
    logger.info("Kerno apagado limpiamente ✓")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Kerno — Binance ingestor")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT"])
    args = parser.parse_args()
    asyncio.run(run([s.upper() for s in args.symbols]))
