"""
Kerno — Bybit connector (v0.55a)

Implements ExchangeConnector for Bybit v5's public linear (USDT perpetual)
WebSocket (wss://stream.bybit.com/v5/public/linear), channel "publicTrade".

Per Finding #2 (docs/connectors.md): Bybit's linear perpetual BTCUSDT uses the
same native symbol string as Binance spot BTCUSDT. To keep trades.symbol
collision-safe by construction, this connector emits "symbol": "BTCUSDT-PERP"
(not the raw "BTCUSDT"). symbol_registry.native_symbol retains the true
exchange-native value ("BTCUSDT") for reference.

Differences from BinanceConnector/CoinbaseConnector:
  - Bidirectional protocol: must send a `subscribe` message after connecting
    (like Coinbase; unlike Binance's URL-encoded subscription).
  - Public market data does not require authentication.
  - Messages are batched: one message's `data` array can contain multiple
    trades (like Coinbase; unlike Binance's one-trade-per-message).
  - Timestamps (`T`) are already epoch milliseconds (like Binance; unlike
    Coinbase's ISO 8601 strings) — no conversion needed.
  - exchange_trade_id (`i`) is already a string (like Coinbase; unlike
    Binance's integer `t`).

Emits canonical Trade event dicts per docs/schemas.md, with
"exchange": "bybit", "event_type": "trade", "symbol": "<NATIVE>-PERP".
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

logger = logging.getLogger("kerno.connectors.bybit")

BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
RECONNECT_DELAY = 3
PING_INTERVAL = 20  # Bybit recommends periodic application-level pings


class BybitConnector(ExchangeConnector):
    exchange_name = "bybit"

    def __init__(self, symbols: list[str]):
        """
        symbols: native Bybit symbols to subscribe to (e.g. ["BTCUSDT"]).
        Emitted canonical events use "<symbol>-PERP" as the `symbol` field
        per Finding #2 (collision-safe vs Binance spot's native "BTCUSDT").
        """
        super().__init__(symbols)

    def parse_message(self, raw_msg: str) -> dict | None:
        """
        Parse a single raw Bybit WS message. Returns None for non-trade
        messages (pong responses, subscription acks, other topics).

        Note: a single publicTrade message can contain MULTIPLE trades.
        This method only validates/identifies the message; trade extraction
        happens in `_iter_trades_from_message` since one message yields zero
        or many canonical events.
        """
        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError as exc:
            logger.warning("Parse error (invalid JSON): %s", exc)
            return None

        topic = msg.get("topic", "")
        if not topic.startswith("publicTrade."):
            return None

        return msg

    def _iter_trades_from_message(self, msg: dict, raw_msg: str) -> list[dict]:
        """
        Extract zero or more canonical Trade event dicts from a parsed
        publicTrade message.
        """
        events: list[dict] = []
        ingest_time_ms = int(time.time() * 1000)

        for trade in msg.get("data", []):
            try:
                native_symbol = trade["s"]
                events.append({
                    "exchange":          self.exchange_name,
                    "symbol":            f"{native_symbol}-PERP",
                    "event_type":        "trade",
                    "price":             float(trade["p"]),
                    "quantity":          float(trade["v"]),
                    "event_time_ms":     int(trade["T"]),
                    "ingest_time_ms":    ingest_time_ms,
                    "exchange_trade_id": trade["i"],
                    "side":              "sell" if trade["S"].upper() == "SELL" else "buy",
                    "raw":               raw_msg,
                })
            except (KeyError, ValueError) as exc:
                logger.warning("Trade parse error (missing/bad field %s): %s", exc, trade)

        return events

    async def stream(self, stop: asyncio.Event) -> AsyncIterator[dict]:
        """
        Yield canonical trade event dicts for all subscribed symbols.

        Bybit's linear WS multiplexes all subscribed symbols over a single
        connection (like Coinbase), so this opens one connection and
        subscribes to all self.symbols' publicTrade topics at once.
        """
        while not stop.is_set():
            try:
                async with websockets.connect(
                    BYBIT_WS_URL, ping_interval=20, ping_timeout=10
                ) as ws:
                    await self._subscribe(ws)
                    logger.info("Conectado -> %s (symbols=%s)", BYBIT_WS_URL, self.symbols)

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
        Send a subscribe message for publicTrade.<symbol> for each symbol.
        Public market data does not require authentication.
        """
        await ws.send(json.dumps({
            "op": "subscribe",
            "args": [f"publicTrade.{symbol}" for symbol in self.symbols],
        }))