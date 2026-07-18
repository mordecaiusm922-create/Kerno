"""
Kerno — OKX connector (v0.65)

Implements ExchangeConnector for OKX v5's public WebSocket
(wss://ws.okx.com:8443/ws/v5/public), channel "trades".

v0.65 hypothesis: Kerno supports structurally more complex markets without
breaking abstractions. OKX is the proof because:
  - Same endpoint handles SPOT, SWAP, FUTURES, OPTION via instId variation
    (e.g. "BTC-USDT" for spot, "BTC-USDT-SWAP" for perpetual)
  - instId is already self-describing — no suffix disambiguation needed
    ("BTC-USDT" has a hyphen; Binance's "BTCUSDT" doesn't — no collision)
  - Ping/pong is text-frame based (send "ping", receive "pong") rather
    than the WebSocket protocol-level ping used by Binance/Coinbase/Bybit

Differences from previous connectors:
  - Text-frame ping: must send "ping" string every N seconds to keep alive
    (connection drops after 30s of inactivity if no message received)
  - Timestamps (`ts`) are epoch milliseconds as strings (parse to int)
  - exchange_trade_id (`tradeId`) is a string (no cast needed)
  - side is already "buy"/"sell" lowercase (no conversion needed)
  - Subscribe args use {"channel": "trades", "instId": "<instId>"} per symbol

Emits canonical Trade event dicts per docs/schemas.md, with
"exchange": "okx", "event_type": "trade", "symbol": instId (e.g. "BTC-USDT").
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

logger = logging.getLogger("kerno.connectors.okx")

OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
RECONNECT_DELAY = 3
PING_INTERVAL_S = 20   # send "ping" every 20s; server closes after 30s of silence


class OKXConnector(ExchangeConnector):
    exchange_name = "okx"

    def parse_message(self, raw_msg: str) -> dict | None:
        """
        Parse a single raw OKX WS message. Returns None for non-trade
        messages (pong responses, subscription acks, other channels).

        Note: a single trades message can contain MULTIPLE trades in data[].
        This method only validates/identifies the message; extraction in
        _iter_trades_from_message.
        """
        # OKX sends "pong" as a plain text frame in response to "ping"
        if raw_msg == "pong":
            return None

        try:
            msg = json.loads(raw_msg)
        except json.JSONDecodeError as exc:
            logger.warning("Parse error (invalid JSON): %s", exc)
            return None

        # Skip subscription acks and error events
        if "event" in msg:
            if msg.get("event") == "error":
                logger.error("OKX WS error: %s %s", msg.get("code"), msg.get("msg"))
            return None

        if msg.get("arg", {}).get("channel") != "trades":
            return None

        return msg

    def _iter_trades_from_message(self, msg: dict, raw_msg: str) -> list[dict]:
        """
        Extract zero or more canonical Trade event dicts from a parsed
        trades message.
        """
        events: list[dict] = []
        ingest_time_ms = int(time.time() * 1000)

        for trade in msg.get("data", []):
            try:
                events.append({
                    "exchange":          self.exchange_name,
                    "symbol":            trade["instId"],
                    "event_type":        "trade",
                    "price":             float(trade["px"]),
                    "quantity":          float(trade["sz"]),
                    "event_time_ms":     int(trade["ts"]),
                    "ingest_time_ms":    ingest_time_ms,
                    "exchange_trade_id": trade["tradeId"],
                    "side":              trade["side"],   # already "buy"/"sell"
                    "raw":               raw_msg,
                })
            except (KeyError, ValueError) as exc:
                logger.warning("Trade parse error (missing/bad field %s): %s", exc, trade)

        return events

    async def stream(self, stop: asyncio.Event) -> AsyncIterator[dict]:
        """
        Yield canonical trade event dicts for all subscribed symbols.

        OKX multiplexes all symbols over one connection. Sends text-frame
        "ping" every PING_INTERVAL_S to keep the connection alive.
        """
        while not stop.is_set():
            try:
                async with websockets.connect(
                    OKX_WS_URL, ping_interval=None  # disable ws-protocol pings; we do text pings
                ) as ws:
                    await self._subscribe(ws)
                    logger.info("Conectado -> %s (symbols=%s)", OKX_WS_URL, self.symbols)

                    last_ping = time.monotonic()

                    async for raw_msg in ws:
                        if stop.is_set():
                            break

                        # Text-frame ping keepalive
                        if time.monotonic() - last_ping >= PING_INTERVAL_S:
                            await ws.send("ping")
                            last_ping = time.monotonic()

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
        Send subscribe message for trades channel for each instId.
        No authentication required for public market data.
        """
        await ws.send(json.dumps({
            "op": "subscribe",
            "args": [
                {"channel": "trades", "instId": symbol}
                for symbol in self.symbols
            ]
        }))
