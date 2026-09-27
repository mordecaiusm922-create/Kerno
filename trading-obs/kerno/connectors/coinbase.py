"""
Coinbase Advanced Trade "market_trades" channel.

Timestamps are ISO-8601 with up to nanosecond precision; they are truncated to
microseconds and converted to epoch milliseconds. The "heartbeats" channel is
subscribed too so quiet products don't get disconnected.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from kerno.connectors.base import ExchangeConnector, make_trade, now_ms

COINBASE_WS_URL = "wss://advanced-trade-ws.coinbase.com"


def parse_iso_to_ms(time_str: str) -> int:
    s = time_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if "." in s:
        head, rest = s.split(".", 1)
        idx = next((i for i, ch in enumerate(rest) if ch in "+-"), len(rest))
        frac, tz = rest[:idx], rest[idx:]
        s = f"{head}.{frac[:6].ljust(6, '0')}{tz}"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


class CoinbaseConnector(ExchangeConnector):
    exchange_name = "coinbase"

    def url(self) -> str:
        return COINBASE_WS_URL

    async def subscribe(self, ws) -> None:
        for channel in ("market_trades", "heartbeats"):
            await ws.send(json.dumps({"type": "subscribe", "product_ids": self.symbols, "channel": channel}))

    def parse_message(self, raw_msg):
        msg = self._loads(raw_msg)
        if not isinstance(msg, dict) or msg.get("channel") != "market_trades":
            return []
        ingest = now_ms()

        def build(t):
            return make_trade(
                self.exchange_name, t["product_id"], t["trade_id"], t["price"], t["size"],
                t["side"], parse_iso_to_ms(t["time"]), ingest, t,
            )

        # NOTE: whether `side` on market_trades is the taker or the maker side has not
        # been verified yet; check a recorded session before relying on Coinbase flow features.
        out = []
        for event in msg.get("events", []):
            for t in event.get("trades", []):
                trade = self._safe(build, t)
                if trade:
                    out.append(trade)
        return out
