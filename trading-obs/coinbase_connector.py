"""
Kerno — Coinbase connector (v0.45b)

Implements ExchangeConnector for Coinbase's Advanced Trade WebSocket
(wss://advanced-trade-ws.coinbase.com), channel "market_trades".

Differences from BinanceConnector that this connector must handle:
  - Bidirectional protocol: must send a `subscribe` message after connecting
    (Binance encodes subscription in the URL path).
  - Public market data does not require authentication.
  - Messages are batched: one message can contain multiple trades from the
    last ~250ms (Binance: one trade per message).
  - Timestamps are ISO 8601 strings with nanosecond precision, not epoch ms —
    must be parsed and converted.
  - exchange_trade_id is already a string (no cast needed, unlike Binance's
    integer trade_id).
  - Subscribes to "heartbeats" alongside "market_trades" to prevent the
    connection closing after 60-90s of inactivity.

Emits canonical Trade event dicts per docs/schemas.md, with
"exchange": "coinbase" and "event_type": "trade".
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import AsyncIterator

import websockets
from websockets.exceptions import ConnectionClosed

from connector import ExchangeConnector

logger = logging.getLogger("kerno.connectors.coinbase")

COINBASE_WS_URL = "wss://advanced-trade-ws.coinbase.com"
RECONNECT_DELAY = 3


def _parse_iso_to_ms(time_str: str) -> int:
    """
    Convert a Coinbase ISO 8601 timestamp (possibly with nanosecond precision,
    e.g. "2023-02-09T20:19:35.39625135Z") to epoch milliseconds.

    Python's datetime.fromisoformat only handles up to microseconds, so we
    truncate any fractional-second component to 6 digits before parsing.
    Sub-millisecond precision is lost; this is acceptable per
    docs/connectors.md v0.45 validation plan.
    """
    if time_str.endswith("Z"):
        time_str = time_str[:-1] + "+00:00"

    if "." in time_str:
        head, rest = time_str.split(".", 1)
        frac, _, tz = rest.partition("+")
        tz = "+" + tz if tz else ""
        if not tz and "-" in rest[1:]:
            # handle "-HH:MM" offsets (rare for Coinbase, which uses Z, but be safe)
            idx = rest.rfind("-")
            frac, tz = rest[:idx], rest[idx:]
        frac = frac[:6].ljust(6, "0")
        time_str = f"{head}.{frac}{tz}"

    dt = datetime.fromisoformat(time_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class CoinbaseConnector(ExchangeConnector):
    exchange_name = "coinbase"

    def parse_message(self, raw_msg: str) -> dict | None:
        """
        Parse a single raw Coinbase WS message. Returns None for non-trade
        messages (heartbeats, subscription acks, snapshots with no trades).

        Note: a single market_trades message can contain MULTIPLE trades.
        This method only validates/identifies the message; trade extraction
        happens in `_iter_trades_from_message` since one message yields zero
        or many canonical events.
        """
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError as exc:
            logger.warning("Parse error (invalid JSON): %s", exc)
            return None

        if msg.get("channel") != "market_trades":
            return None

        return msg

    def _iter_trades_from_message(self, msg: dict, raw_msg: str) -> list[dict]:
        """
        Extract zero or more canonical Trade event dicts from a parsed
        market_trades message.
        """
        events: list[dict] = []
        ingest_time_ms = int(time.time() * 1000)

        for event in msg.get("events", []):
            for trade in event.get("trades", []):
                try:
                    events.append({
                        "exchange":          self.exchange_name,
                        "symbol":            trade["product_id"],
                        "event_type":        "trade",
                        "price":             float(trade["price"]),
                        "quantity":          float(trade["size"]),
                        "event_time_ms":     _parse_iso_to_ms(trade["time"]),
                        "ingest_time_ms":    ingest_time_ms,
                        "exchange_trade_id": trade["trade_id"],
                        "side":              "sell" if trade["side"].upper() == "SELL" else "buy",
                        "raw":               raw_msg,
                    })
                except (KeyError, ValueError) as exc:
                    logger.warning("Trade parse error (missing/bad field %s): %s", exc, trade)

        return events

    async def stream(self, stop: asyncio.Event) -> AsyncIterator[dict]:
        """
        Yield canonical trade event dicts for all subscribed symbols.

        Coinbase's WS multiplexes all subscribed product_ids over a single
        connection (unlike Binance's per-symbol connections), so this opens
        one connection and subscribes to all self.symbols at once.
        """
        while not stop.is_set():
            try:
                async with websockets.connect(
                    COINBASE_WS_URL, ping_interval=20, ping_timeout=10
                ) as ws:
                    await self._subscribe(ws)
                    logger.info("Conectado -> %s (symbols=%s)", COINBASE_WS_URL, self.symbols)

                    async for raw_msg in ws:
                        if stop.is_set():
                            break

                        msg = self.parse_message(raw_msg)
                        if msg is None:
                            continue

                        for trade_event in self._iter_trades_from_message(msg, raw_msg):
                            yield trade_event

            except ConnectionClosed as exc:
                logger.warning(
                    "WS cerrado (%s) - reconectando en %ds", exc.code, RECONNECT_DELAY
                )
            except OSError as exc:
                logger.error("Error de red: %s", exc)

            if not stop.is_set():
                await asyncio.sleep(RECONNECT_DELAY)

    async def _subscribe(self, ws) -> None:
        """
        Send subscribe messages for market_trades and heartbeats.

        Must be sent within 5 seconds of connecting or Coinbase disconnects.
        Public market data does not require authentication (jwt field omitted).
        """
        for channel in ("market_trades", "heartbeats"):
            await ws.send(json.dumps({
                "type": "subscribe",
                "product_ids": self.symbols,
                "channel": channel,
            }))