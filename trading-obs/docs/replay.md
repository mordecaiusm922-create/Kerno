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
- **Warm-up:** all engine state is bounded to the last 5 minutes
  (`MAX_WINDOW_MS`), including the spike-percentile tail since `fv3`.
  Replaying `WARMUP_MS` (10 minutes) before any start point reproduces a
  continuous run exactly: 5 minutes rebuild the window and 5 more replay event
  detection so the 1-second cooldown state is exact too. The worker restart
  and the daily dataset builder both rely on this, and tests assert exact
  equality.
- **Late trades:** the live engine runs 3 s behind wall clock. A trade that
  arrives later than that with an older event time is not seen live but is
  seen by a later replay. The ingest stats log reports latency so this can be
  monitored.

## Versioning

Change a feature definition → bump `FEATURE_VERSION` in `kerno/features.py`.
Old signals stay under the old version; the engine's cursor is per version, so
the new version starts fresh, and old models are refused automatically.
