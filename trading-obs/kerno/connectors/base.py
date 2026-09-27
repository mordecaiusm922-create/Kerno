"""
Connector SDK.

Every exchange adapter subclasses ExchangeConnector and only implements:
  - url()            : websocket URL to connect to
  - subscribe(ws)    : optional subscription handshake after connecting
  - parse_message()  : raw frame -> list of canonical Trade dicts

The base class owns the connection lifecycle (reconnect with exponential
backoff + jitter, stale-feed detection, optional application-level pings), so
every exchange gets the same resilience behaviour.

Canonical Trade (docs/schemas.md):
    exchange, symbol, exchange_trade_id (str), price, quantity,
    side ('buy'|'sell', aggressor), event_time_ms, ingest_time_ms, raw (json str)
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import random
import time
from collections.abc import AsyncIterator
from typing import Any

import websockets

logger = logging.getLogger("kerno.connectors")

MAX_BACKOFF_S = 60.0
STALE_FEED_S = 60.0  # reconnect if no frame at all arrives for this long


def now_ms() -> int:
    return int(time.time() * 1000)


def make_trade(
    exchange: str,
    symbol: str,
    exchange_trade_id: Any,
    price: Any,
    quantity: Any,
    side: str,
    event_time_ms: Any,
    ingest_time_ms: int,
    raw: Any,
) -> dict:
    """Build and validate one canonical trade. Raises ValueError on bad input."""
    price_f = float(price)
    qty_f = float(quantity)
    if not price_f > 0:
        raise ValueError(f"non-positive price {price!r}")
    if qty_f < 0:
        raise ValueError(f"negative quantity {quantity!r}")
    side = side.lower()
    if side not in ("buy", "sell"):
        raise ValueError(f"unknown side {side!r}")
    return {
        "exchange": exchange,
        "symbol": symbol,
        "exchange_trade_id": str(exchange_trade_id),
        "price": price_f,
        "quantity": qty_f,
        "side": side,
        "event_time_ms": int(event_time_ms),
        "ingest_time_ms": ingest_time_ms,
        "raw": json.dumps(raw, separators=(",", ":")),
    }


class ExchangeConnector(abc.ABC):
    #: canonical exchange identifier, e.g. "binance"
    exchange_name: str
    #: text frame sent every app_ping_interval_s (OKX style); None disables
    app_ping: str | None = None
    app_ping_interval_s: float = 20.0
    #: websocket protocol-level ping; None disables (OKX)
    ws_ping_interval: float | None = 20.0

    def __init__(self, symbols: list[str]):
        if not symbols:
            raise ValueError(f"{type(self).__name__} needs at least one symbol")
        self.symbols = [s.upper() for s in symbols]

    @abc.abstractmethod
    def url(self) -> str: ...

    async def subscribe(self, ws) -> None:  # pragma: no cover - default no-op
        return None

    @abc.abstractmethod
    def parse_message(self, raw_msg: str | bytes) -> list[dict]:
        """Parse one frame into zero or more canonical trades. Never raises."""

    async def stream(self, stop: asyncio.Event) -> AsyncIterator[dict]:
        attempt = 0
        while not stop.is_set():
            connected_at = time.monotonic()
            pinger: asyncio.Task | None = None
            try:
                async with websockets.connect(
                    self.url(),
                    ping_interval=self.ws_ping_interval,
                    ping_timeout=10 if self.ws_ping_interval else None,
                    max_size=2**22,
                ) as ws:
                    await self.subscribe(ws)
                    logger.info("[%s] connected symbols=%s", self.exchange_name, self.symbols)
                    if self.app_ping:
                        pinger = asyncio.create_task(self._ping_loop(ws))
                    while not stop.is_set():
                        try:
                            raw_msg = await asyncio.wait_for(ws.recv(), timeout=STALE_FEED_S)
                        except TimeoutError:
                            logger.warning("[%s] no frames for %ss, reconnecting", self.exchange_name, STALE_FEED_S)
                            break
                        for trade in self.parse_message(raw_msg):
                            yield trade
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # network errors, HTTP 451/403 on connect, protocol errors
                logger.warning("[%s] connection error: %s: %s", self.exchange_name, type(exc).__name__, exc)
            finally:
                if pinger:
                    pinger.cancel()

            if stop.is_set():
                break
            # a connection that stayed up a while resets the backoff
            attempt = 0 if time.monotonic() - connected_at > 60 else attempt + 1
            delay = min(MAX_BACKOFF_S, 2 ** min(attempt, 6)) * (0.5 + random.random() / 2)
            logger.info("[%s] reconnecting in %.1fs", self.exchange_name, delay)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _ping_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(self.app_ping_interval_s)
            await ws.send(self.app_ping)

    def _loads(self, raw_msg: str | bytes) -> Any:
        try:
            return json.loads(raw_msg)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            return None

    def _safe(self, build, item) -> dict | None:
        try:
            return build(item)
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("[%s] bad trade payload (%s): %.300s", self.exchange_name, exc, item)
            return None
