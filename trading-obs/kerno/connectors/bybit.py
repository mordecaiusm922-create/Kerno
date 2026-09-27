"""
Bybit v5 linear (USDT perpetual) publicTrade stream.

Finding #2 (docs/connectors.md): Bybit's perpetual BTCUSDT has the same native
symbol as Binance spot BTCUSDT, so the canonical symbol is suffixed "-PERP" to
stay collision-safe by construction.

Note: Bybit blocks US IP addresses. Deploy the ingestor in a non-US region.
"""

from __future__ import annotations

import json

from kerno.connectors.base import ExchangeConnector, make_trade, now_ms

BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"


class BybitConnector(ExchangeConnector):
    exchange_name = "bybit"

    def url(self) -> str:
        return BYBIT_WS_URL

    async def subscribe(self, ws) -> None:
        await ws.send(json.dumps({"op": "subscribe", "args": [f"publicTrade.{s}" for s in self.symbols]}))

    def parse_message(self, raw_msg):
        msg = self._loads(raw_msg)
        if not isinstance(msg, dict) or not str(msg.get("topic", "")).startswith("publicTrade."):
            return []
        ingest = now_ms()

        def build(t):
            return make_trade(
                self.exchange_name, f"{t['s']}-PERP", t["i"], t["p"], t["v"],
                t["S"], t["T"], ingest, t,
            )

        return [x for x in (self._safe(build, t) for t in msg.get("data", [])) if x]
