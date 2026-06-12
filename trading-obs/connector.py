"""
Kerno — Connector SDK (v0.35)

Defines the ExchangeConnector interface. Every exchange adapter (Binance, and
future Coinbase/Bybit/etc.) implements this interface and emits canonical event
dicts conforming to docs/schemas.md (Trade schema for now; OrderBook/Ticker/
FundingRate/Liquidation will follow as connectors that need them are added).

This is intentionally minimal for v0.35: the goal is to put a stable interface
in front of the existing Binance ingestion logic without changing its behavior.
Future connectors (v0.45+) implement the same interface.
"""

from __future__ import annotations

import abc
import asyncio
from typing import AsyncIterator


class ExchangeConnector(abc.ABC):
    """
    Base interface for an exchange market-data connector.

    A connector is responsible for:
      - establishing and maintaining a connection to one exchange's market
        data feed (with its own reconnect/backoff policy)
      - normalizing exchange-native messages into canonical event dicts
        (see docs/schemas.md)
      - exposing those events as an async stream via `stream()`

    A connector is NOT responsible for batching, persistence, or feature
    computation — those remain the caller's job (see ingestor.py BatchWriter).
    """

    #: Canonical exchange identifier, e.g. "binance". Used as the `exchange`
    #: field on every emitted event.
    exchange_name: str

    def __init__(self, symbols: list[str]):
        """
        symbols: list of native exchange symbols to subscribe to
                 (e.g. ["BTCUSDT", "ETHUSDT"] for Binance).
        """
        self.symbols = [s.upper() for s in symbols]

    @abc.abstractmethod
    async def stream(self, stop: asyncio.Event) -> AsyncIterator[dict]:
        """
        Yield canonical event dicts until `stop` is set.

        Each yielded dict must conform to one of the canonical event schemas
        in docs/schemas.md (Trade, OrderBook, Ticker, FundingRate,
        Liquidation), identified by an `event_type` field.

        Implementations are responsible for their own reconnect/backoff
        logic — `stream()` should not raise on transient connection errors,
        only on `stop` being set or on unrecoverable errors.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def parse_message(self, raw_msg: str) -> dict | None:
        """
        Parse one raw exchange message into a canonical event dict, or None
        if the message is not a type this connector cares about (e.g.
        heartbeat/control frames).

        Exposed separately from `stream()` so parsing logic can be unit
        tested against recorded exchange messages without a live connection.
        """
        raise NotImplementedError
