"""
Kerno — Binance connector (v0.35)

Implements ExchangeConnector for Binance's spot trade stream
(wss://stream.binance.com:9443/ws/{symbol}@trade).

This is a behavior-preserving extraction of the connection/parsing logic that
previously lived directly in ingestor.py (stream_symbol + parse_trade). The
emitted events are unchanged in shape — same fields as before — but now
carry an explicit "exchange" field per the canonical Trade schema
(docs/schemas.md), and "event_type" is set to "trade".

ingestor.py's BatchWriter/flush_loop/run() are unchanged by this module;
v0.35 only introduces the connector boundary. Wiring ingestor.py to use
BinanceConnector instead of stream_symbol/parse_trade directly is a
follow-up integration step (kept separate to minimize risk of breaking the
running production ingestor in a single change).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosed

from connector import ExchangeConnector

logger = logging.getLogger("kerno.connectors.binance")

BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"
RECONNECT_DELAY = 3


class BinanceConnector(ExchangeConnector):
    exchange_name = "binance"

    def parse_message(self, raw_msg: str) -> dict | None:
        """
        Parse a raw Binance @trade stream message into a canonical Trade
        event dict. Returns None for message types this connector doesn't
        emit (currently only "trade" messages are handled).

        This is the same mapping as the original parse_trade() in
        ingestor.py, plus the canonical "exchange" field and
        "event_type": "trade".
        """
        try:
            raw = json.loads(raw_msg)
        except json.JSONDecodeError as exc:
            logger.warning("Parse error (invalid JSON): %s", exc)
            return None

        if raw.get("e") != "trade":
            return None

        try:
            return {
                "exchange":       self.exchange_name,
                "symbol":         raw["s"],
                "event_type":     "trade",
                "price":          float(raw["p"]),
                "quantity":       float(raw["q"]),
                "event_time_ms":  raw["T"],
                "ingest_time_ms": int(time.time() * 1000),
                "trade_id":       raw["t"],
                "is_buyer_maker": 1 if raw["m"] else 0,
                "raw":            raw_msg,
            }
        except KeyError as exc:
            logger.warning("Parse error (missing field %s): %s", exc, raw)
            return None

    async def stream(self, stop: asyncio.Event) -> AsyncIterator[dict]:
        """
        Yield canonical trade event dicts for all subscribed symbols.

        Runs one connection per symbol concurrently (same as the original
        per-symbol stream_symbol() loops in ingestor.py), merging their
        output into a single async stream via an internal queue.
        """
        queue: asyncio.Queue[dict] = asyncio.Queue()

        tasks = [
            asyncio.create_task(self._stream_symbol(symbol, queue, stop))
            for symbol in self.symbols
        ]

        try:
            while not stop.is_set() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if stop.is_set():
                        break
                    continue
                yield event
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _stream_symbol(
        self, symbol: str, queue: asyncio.Queue, stop: asyncio.Event
    ) -> None:
        url = f"{BINANCE_WS_BASE}/{symbol.lower()}@trade"
        logger.info("Conectando -> %s", url)

        while not stop.is_set():
            try:
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=10
                ) as ws:
                    logger.info("[%s] Conectado", symbol)
                    async for raw_msg in ws:
                        if stop.is_set():
                            break
                        event = self.parse_message(raw_msg)
                        if event:
                            await queue.put(event)

            except ConnectionClosed as exc:
                logger.warning(
                    "[%s] WS cerrado (%s) - reconectando en %ds",
                    symbol, exc.code, RECONNECT_DELAY,
                )
            except OSError as exc:
                logger.error("[%s] Error de red: %s", symbol, exc)

            if not stop.is_set():
                await asyncio.sleep(RECONNECT_DELAY)
