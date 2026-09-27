"""
Binance spot trade stream.

Uses one combined-stream connection for all symbols:
wss://stream.binance.com:9443/stream?streams=btcusdt@trade/ethusdt@trade

Note: Binance.com rejects connections from US IP addresses (HTTP 451).
Deploy the ingestor in a non-US region.
"""

from __future__ import annotations

from kerno.connectors.base import ExchangeConnector, make_trade, now_ms

BINANCE_WS_BASE = "wss://stream.binance.com:9443"


class BinanceConnector(ExchangeConnector):
    exchange_name = "binance"

    def url(self) -> str:
        streams = "/".join(f"{s.lower()}@trade" for s in self.symbols)
        return f"{BINANCE_WS_BASE}/stream?streams={streams}"

    def parse_message(self, raw_msg):
        msg = self._loads(raw_msg)
        if not isinstance(msg, dict):
            return []
        data = msg.get("data", msg)  # combined stream wraps payload in "data"
        if not isinstance(data, dict) or data.get("e") != "trade":
            return []
        ingest = now_ms()

        def build(d):
            return make_trade(
                self.exchange_name, d["s"], d["t"], d["p"], d["q"],
                # m = buyer is maker -> the aggressor sold
                "sell" if d["m"] else "buy",
                d["T"], ingest, d,
            )

        trade = self._safe(build, data)
        return [trade] if trade else []
