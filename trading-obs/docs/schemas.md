# Market Schema

> Status: design reference for v0.25 (Market Schema milestone). The current
> `market_events` table is Binance-shaped and does not yet conform to this schema.
> This document defines the target so v0.25 has no ambiguity about scope.

## Goals

- One canonical representation per event type, independent of exchange.
- Every exchange adapter (current: Binance; future: Coinbase, Kraken, Bybit, ...)
  normalizes into these types.
- Deterministic replay requires that two adapters producing the "same" market event
  produce byte-identical canonical records (modulo exchange-specific raw payload,
  which is preserved separately for audit).

## Canonical event types

### Trade

| Field | Type | Notes |
|---|---|---|
| `exchange` | string | e.g. "binance" |
| `symbol` | string | canonical symbol, see Symbol Registry |
| `exchange_trade_id` | string | opaque exchange-native trade id, always TEXT (Binance emits integers, Coinbase emits strings — never assume a type/format for this field) |
| `price` | float | |
| `quantity` | float | base asset units |
| `side` | enum (`buy`/`sell`) | aggressor side |
| `event_time_ms` | int | exchange-reported event time |
| `ingest_time_ms` | int | local receive time |
| `raw` | json | original exchange payload, for audit |

### OrderBook (delta or snapshot)

| Field | Type | Notes |
|---|---|---|
| `exchange` | string | |
| `symbol` | string | |
| `type` | enum (`snapshot`/`delta`) | |
| `bids` | array of [price, qty] | |
| `asks` | array of [price, qty] | |
| `event_time_ms` | int | |
| `ingest_time_ms` | int | |
| `sequence` | int | exchange sequence number, for gap detection |

### Ticker

| Field | Type | Notes |
|---|---|---|
| `exchange` | string | |
| `symbol` | string | |
| `best_bid` | float | |
| `best_ask` | float | |
| `last_price` | float | |
| `event_time_ms` | int | |
| `ingest_time_ms` | int | |

### FundingRate

| Field | Type | Notes |
|---|---|---|
| `exchange` | string | |
| `symbol` | string | perpetual contract symbol |
| `funding_rate` | float | |
| `funding_time_ms` | int | next funding settlement time |
| `event_time_ms` | int | |

### Liquidation

| Field | Type | Notes |
|---|---|---|
| `exchange` | string | |
| `symbol` | string | |
| `side` | enum (`buy`/`sell`) | side of the liquidated position |
| `price` | float | |
| `quantity` | float | |
| `event_time_ms` | int | |

## SymbolRegistry

A mapping table from canonical symbol to per-exchange native symbol, so that
"BTCUSDT" on Binance and the equivalent contract on Bybit/OKX map to one canonical
identifier. Required fields:

| Field | Type | Notes |
|---|---|---|
| `canonical_symbol` | string | e.g. "BTC-USDT-PERP" |
| `exchange` | string | |
| `native_symbol` | string | e.g. "BTCUSDT" |
| `asset_base` | string | "BTC" |
| `asset_quote` | string | "USDT" |
| `instrument` | string | groups pairs sharing a base asset across quote currencies/exchanges for cross-exchange analysis, e.g. "BTC" for both BTC-USDT (Binance) and BTC-USD (Coinbase). Distinct pairs remain distinct `canonical_symbol`s — basis risk between quote currencies (USDT vs USD) must stay visible, not hidden by false equivalence. |
| `instrument_type` | enum (`spot`/`perp`/`future`) | |
| `tick_size` | float | minimum price increment |
| `lot_size` | float | minimum quantity increment |

## v0.45a schema correction (validated hypothesis: multi-exchange `trades`)

The original `trade_id INTEGER` field assumed exchange-native trade IDs are
numeric. This held for Binance but breaks for Coinbase, which emits string trade
IDs. This was caught and corrected *before* writing the Coinbase connector
(v0.45a), per the principle: the multi-exchange model must survive a second
exchange without special-case exceptions.

Fix: `trade_id INTEGER` -> `exchange_trade_id TEXT` (opaque identifier; the
internal primary key remains `id INTEGER PRIMARY KEY AUTOINCREMENT`, unaffected).
3,025,526 existing rows migrated via `CAST(trade_id AS TEXT)`, zero data loss.

`symbol_registry.instrument` was added in the same migration to support the
Instrument/Pair distinction: BTC-USDT and BTC-USD are related but distinct pairs
(different quote currencies), grouped under `instrument='BTC'` for cross-exchange
queries without conflating them as the same `canonical_symbol`.

## Migration note (v0.1 -> v0.25)

The current `market_events` table stores Binance trade-stream messages with
Binance-native field names. v0.25 introduces:

1. A `trades` table conforming to the Trade schema above, populated going forward by
   adapter-normalized writes.
2. A one-time backfill script that maps existing `market_events` rows into `trades`
   where the mapping is unambiguous (Binance trade stream -> Trade schema is a direct
   field rename).
3. `feature_store` continues to read from `trades`, not `market_events`, after
   migration. Feature formulas do not change — only the upstream table name and field
   names.

No feature recomputation is required for this migration since the underlying values
are identical; only field names and table name change.

Note: `trade_id` was further corrected to `exchange_trade_id TEXT` in v0.45a (see
above) ahead of the Coinbase connector.

## Existing labels (feature_store, unchanged by this schema)

These remain as-is; they describe model targets, not raw market data:

| Field | Type | Notes |
|---|---|---|
| `micro_label` | enum | `CONTINUATION_UP`, `CONTINUATION_DOWN`, `ABSORPTION`, `NOISE` |
| `outcome_10s` | string ('0'/'1') | resolved by validator.py |
| `outcome_30s` | string ('0'/'1') | resolved by validator.py |
| `stage1_label` | int (0/1) | 1 = TRADEABLE, 0 = NEUTRAL |