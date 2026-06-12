# Connector SDK

> Status: specification skeleton. Full design is scoped for v0.35 (Connector SDK),
> with Binance as the first formal adapter. This document exists so v0.15 has
> placeholders for every planned doc; it is not a complete spec.

## Goal

A single `ExchangeConnector` interface that every exchange adapter implements, so
that adding exchange #2 through #100 is a matter of implementing the interface against
the canonical Market Schema (schemas.md), not writing bespoke ingestion code.

## TODO before v0.35 design is final

- [ ] Define `ExchangeConnector` interface methods: connect, subscribe(symbols,
      channels), on_trade, on_orderbook, on_ticker, on_funding, on_liquidation,
      disconnect, reconnect/backoff policy.
- [ ] Define how each adapter maps exchange-native messages to canonical Market
      Schema types (schemas.md) — likely one mapping function per message type per
      exchange.
- [ ] Refactor `ingestor.py` (current Binance-specific implementation) into a
      `BinanceConnector` implementing the new interface, as the reference
      implementation.
- [ ] Define connector health/monitoring contract: how does a connector report
      connection state, sequence gaps, reconnect events?
- [ ] Define rate-limit and subscription-limit handling per exchange (varies widely).
- [ ] Decide on testing strategy: replay recorded exchange messages through each
      connector and assert canonical output matches a golden file.

## Constraints carried from architecture.md / vision.md

- Schema first: connectors only ever produce canonical Market Schema types — no
  exchange-native types leak past the connector boundary.
- No point-to-point integrations: a new exchange means a new `ExchangeConnector`
  implementation, not special-cased code elsewhere in the pipeline.
- v0.45 (first 3 connectors) and v2.0 (10 exchanges) depend directly on this SDK
  being stable before they start.
