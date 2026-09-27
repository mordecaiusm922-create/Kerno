"""
OKX v5 public "trades" channel.

instId is self-describing ("BTC-USDT" spot, "BTC-USDT-SWAP" perp), so it is
used as the canonical symbol directly. OKX closes idle connections after 30s,
so a text "ping" is sent every 20s from an independent task (the previous
implementation only pinged when a message arrived, which let quiet feeds die).
"""

from __future__ import annotations

import json
import logging

from kerno.connectors.base import ExchangeConnector, make_trade, now_ms

logger = logging.getLogger("kerno.connectors.okx")

OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"


class OKXConnector(ExchangeConnector):
    exchange_name = "okx"
    app_ping = "ping"
    app_ping_interval_s = 20.0
    ws_ping_interval = None

    def url(self) -> str:
        return OKX_WS_URL

    async def subscribe(self, ws) -> None:
        await ws.send(json.dumps({
            "op": "subscribe",
            "args": [{"channel": "trades", "instId": s} for s in self.symbols],
        }))

    def parse_message(self, raw_msg):
        if raw_msg == "pong":
            return []
        msg = self._loads(raw_msg)
        if not isinstance(msg, dict):
            return []
        if msg.get("event") == "error":
            logger.error("[okx] ws error %s %s", msg.get("code"), msg.get("msg"))
            return []
        if msg.get("arg", {}).get("channel") != "trades":
            return []
        ingest = now_ms()

        def build(t):
            return make_trade(
                self.exchange_name, t["instId"], t["tradeId"], t["px"], t["sz"],
                t["side"], t["ts"], ingest, t,
            )

        return [x for x in (self._safe(build, t) for t in msg.get("data", [])) if x]

