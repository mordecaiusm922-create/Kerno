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

## v0.45 — Coinbase connector (cross-exchange hypothesis)

v0.45's purpose is not "add a 4th exchange." It's to test a single hypothesis:
**Kerno can observe the same instrument (BTC) on two distinct venues (Binance,
Coinbase) and produce a coherent, comparable view.** Everything downstream
(cross-exchange anomaly detection, liquidity intelligence, lead-lag analysis,
funding/basis analysis) depends on this holding without special-case exceptions.

### Finding #1 (v0.45a, resolved before writing CoinbaseConnector)

`trades.trade_id` was `INTEGER`, correct for Binance (numeric trade IDs) but wrong
for Coinbase (string trade IDs, e.g. `"000000000"`). This is a model-level bug, not
a Coinbase-specific quirk — any future exchange could emit non-numeric IDs.

Fixed via schema correction (see schemas.md): `trade_id` -> `exchange_trade_id TEXT`,
treated as an opaque exchange-native identifier. The internal primary key (`id
INTEGER PRIMARY KEY AUTOINCREMENT`) was never affected — it's a separate concept
(Option A vs B distinction: trade_id is an opaque external ID, not an internal key).

Also added `symbol_registry.instrument` (Instrument/Pair distinction): BTC-USDT
(Binance) and BTC-USD (Coinbase) are related but not identical — different quote
currencies mean basis risk exists between them. `instrument='BTC'` groups them for
cross-exchange queries without claiming false equivalence at the `canonical_symbol`
level.

### Coinbase Advanced Trade WebSocket — researched details

- Endpoint: `wss://advanced-trade-ws.coinbase.com`, channel `market_trades`.
- Public market data does not require authentication (auth recommended for
  reliability but not mandatory).
- Bidirectional protocol: client must send a `subscribe` message after connecting
  (unlike Binance, where the URL path encodes the subscription). Must subscribe
  within 5 seconds of connecting or the server disconnects.
- Messages are **batched**: each message's `events[].trades[]` array can contain
  multiple trades from the last 250ms, unlike Binance's one-trade-per-message.
- Timestamps are ISO 8601 strings with nanosecond precision (e.g.
  `"2019-08-14T20:42:27.265Z"`), not epoch milliseconds — must be parsed and
  converted to `event_time_ms`. Sub-millisecond precision is lost in this
  conversion (acceptable).
- Heartbeats channel should be subscribed alongside `market_trades` to prevent the
  connection from closing after 60-90 seconds of inactivity.

### Field mapping: Coinbase `market_trades` -> Trade schema

| Coinbase field | Trade schema field | Notes |
|---|---|---|
| (constant) | `exchange` | `"coinbase"` |
| `product_id` (e.g. `"BTC-USD"`) | `symbol` | native pair, resolved via symbol_registry |
| `trade_id` (string) | `exchange_trade_id` | already TEXT, no cast needed |
| `price` (string) | `price` | parse to float |
| `size` (string) | `quantity` | parse to float |
| `side` (`"BUY"`/`"SELL"`) | `side` | lowercase to `buy`/`sell` |
| `time` (ISO 8601 + ns) | `event_time_ms` | parse ISO -> epoch ms |
| (local clock) | `ingest_time_ms` | `time.time() * 1000` on receipt |

### Validation plan (the actual point of v0.45)

After `CoinbaseConnector` is implemented and run alongside `BinanceConnector` for a
period with sufficient overlap, validate against `trades`:

1. **Timestamp comparability**: are `event_time_ms` values from both exchanges on
   the same epoch/unit and mutually meaningful for ordering?
2. **Symbol registry resolution**: does `instrument='BTC'` correctly group
   BTC-USDT (binance) and BTC-USD (coinbase) rows for a joint query?
3. **Relative latency**: can `ingest_time_ms - event_time_ms` be compared
   meaningfully across exchanges (different network paths, different exchange-side
   timestamp semantics)?
4. **Relative spread/price**: do BTC-USDT and BTC-USD prices track closely enough
   (modulo USDT/USD basis) to be useful for anomaly detection?
5. **Replay determinism**: does interleaving events from two exchanges by
   `event_time_ms` preserve a sensible temporal order for replay (v0.6)?

If any of these fail, the fix is at the schema/registry level (as with Finding #1),
not a per-connector hack. This is the bar v0.45 needs to clear before v0.55
(Bybit perpetuals — funding/basis analysis) and v0.65 (OKX — structural complexity)
build on top of it.