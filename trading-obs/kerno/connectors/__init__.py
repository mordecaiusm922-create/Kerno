"""Exchange connectors. `build_connector("binance", ["BTCUSDT"])`."""

from __future__ import annotations

from kerno.connectors.base import ExchangeConnector
from kerno.connectors.binance import BinanceConnector
from kerno.connectors.bybit import BybitConnector
from kerno.connectors.coinbase import CoinbaseConnector
from kerno.connectors.okx import OKXConnector

REGISTRY: dict[str, type[ExchangeConnector]] = {
    "binance": BinanceConnector,
    "bybit": BybitConnector,
    "coinbase": CoinbaseConnector,
    "okx": OKXConnector,
}


def build_connector(exchange: str, native_symbols: list[str]) -> ExchangeConnector:
    try:
        cls = REGISTRY[exchange.lower()]
    except KeyError:
        raise ValueError(f"unknown exchange {exchange!r}; known: {sorted(REGISTRY)}") from None
    return cls(native_symbols)


def canonical_symbol(exchange: str, native_symbol: str) -> str:
    """Symbol as stored in `trades.symbol` for a subscribed native symbol."""
    native_symbol = native_symbol.upper()
    return f"{native_symbol}-PERP" if exchange.lower() == "bybit" else native_symbol


__all__ = ["REGISTRY", "ExchangeConnector", "build_connector", "canonical_symbol"]
