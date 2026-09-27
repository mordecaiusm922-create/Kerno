# Replay

`kerno replay --exchange binance --symbol BTCUSDT [--from-ms ..] [--to-ms ..] [--score]`
runs the signal engine over stored trades and writes signals. It is the same
code path as the live engine worker.

## Determinism contract

Same trades (exchange, symbol, exchange_trade_id, price, quantity, side,
event_time_ms) + same `FEATURE_VERSION` + same `ENGINE_VERSION` + same
`EngineConfig` → byte-identical signal rows (excluding `created_at_ms` and
outcome columns).

- **Ordering:** `(event_time_ms, exchange_trade_id)`. The tie-break is text
  ordering of the exchange id, which is stable and identical live and in replay.
- **Idempotency:** `signals` is unique on `(exchange, symbol, exchange_trade_id,
  feature_version)`, so replays never duplicate signals.
- **Warm-up:** all feature windows are ≤ 5 minutes (`MAX_WINDOW_MS`), so
  restarting from a cursor and preloading 5 minutes of trades reproduces the
  state exactly. The only exception is the 1-second event cooldown immediately
  after a restart, which is conservatively re-armed.
- **Late trades:** the live engine runs 3 s behind wall clock. A trade that
  arrives later than that with an older event time is not seen live but is
  seen by a later replay. The ingest stats log reports latency so this can be
  monitored.

## Versioning

Change a feature definition → bump `FEATURE_VERSION` in `kerno/features.py`.
Old signals stay under the old version; the engine's cursor is per version, so
the new version starts fresh, and old models are refused automatically.
