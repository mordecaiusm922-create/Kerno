# Architecture (v1.0)

```
 Binance / Bybit / OKX / Coinbase websockets
                 │  kerno/connectors/*  (reconnect+backoff, stale-feed detection)
                 ▼
          kerno ingest ──► trades (Postgres/Supabase, hot window)
                                 │                        │
                                 │                 kerno archive
                                 │                        ▼
                                 │        Parquet per exchange/symbol/day
                                 │        (verified, SHA-256, S3-compatible)
                                 ▼
          kerno engine  (ordered by event_time, exchange_trade_id; 3s watermark)
            features.py  ─ point-in-time features, FEATURE_VERSION
            model.py     ─ Stage 1 P(tradeable) × Stage 2 P(direction), JSON models
                                 ▼
                              signals  ◄── kerno validate (outcomes from later trades,
                                 │                         net of costs, data watermark)
          kerno basis ──► basis_log (spot vs perp)
                                 ▼
          kerno api (read-only, API keys, rate limits, audit log) ──► terminal / clients
```

## Guarantees

| Guarantee | How |
|---|---|
| No look-ahead in features | Windows contain only trades processed before the event trade. Tested by tampering with all later trades and checking features are unchanged. |
| Determinism | The engine is a pure function of the ordered trade stream. Live processing and `kerno replay` run the same code; tested prefix-vs-full equality. |
| No train/serve skew | Training reads the feature vectors the engine stored with each signal. |
| Honest outcomes | Entry after a configurable delay, fixed horizons, PnL net of costs, resolved only when data covers the horizon. |
| No silent data loss | Ingest retries DB writes and counts drops. The archive verifies before deleting, and deletes only when asked. |
| Read-only API | No endpoint writes market data or signals. Tested by hashing every table before and after hitting all endpoints. |

## Tables

| Table | Written by | Retention |
|---|---|---|
| `trades` | ingest | hot window (archive + `--delete` after N days) |
| `signals` | engine, validator (outcome columns) | forever |
| `engine_state` | engine (cursor, same transaction as signals) | — |
| `basis_log` | basis | forever |
| `symbol_registry` | migration seed | — |
| `api_keys`, `api_audit_log` | CLI, API | forever |
| `archive_manifest` | archive | forever |

## Processes

`kerno run-all` runs ingest, engine, validator and basis in one process (enough
for a single small server). Each one can also run on its own (`kerno ingest`,
`kerno engine`, …) and scale independently. The API is always a separate process.

## Modeling

Two stages, per stream:

1. **Stage 1 — tradability.** Does the price move more than the round-trip cost within the horizon? It uses no directional inputs.
2. **Stage 2 — direction.** Is the move a continuation of the spike or an absorption (reversal)?

Both are standardized logistic regressions with isotonic calibration, trained by
`kerno train` on a time-ordered 60/20/20 split with embargo. A model is
deployed only if it beats the gate on the untouched test segment.
