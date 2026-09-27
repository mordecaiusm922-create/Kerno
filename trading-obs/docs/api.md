# API (v1)

All `/v1/*` endpoints require `X-API-Key: kerno_...` (create one with
`kerno keys create <client-name> [--rate N]`). Responses are JSON, `Cache-Control: no-store`.
Every request is recorded in `api_audit_log`. Errors: 401 bad or missing key,
429 rate limit (see `Retry-After`), 400/422 invalid parameters.

| Endpoint | Params | Returns |
|---|---|---|
| `GET /health` (public) | — | `{status, version, database}` |
| `GET /v1/trades` | `exchange=binance`, `symbol=BTCUSDT`, `limit≤1000`, `before_ms` | latest canonical trades, newest first (page backwards with `before_ms`) |
| `GET /v1/replay` | `from`, `to` (ms, window ≤ 1h), `exchange`, `symbol`, `limit≤5000` | trades in time order |
| `GET /v1/metrics` | `exchange`, `symbol`, `minutes≤240` | 1-minute buckets: count, latency, low/high, volume |
| `GET /v1/signals` | `exchange`, `symbol`, `limit≤500`, `scored_only`, `min_joint`, `include_features` | signals with model outputs and resolved outcomes |
| `GET /v1/performance` | `exchange`, `symbol`, `horizon=10\|30`, `last_n` | n, hit rate, mean net/gross bps, std, t-stat for scored signals |
| `GET /v1/basis` | `limit≤2000` | spot/perp basis samples |
| `GET /v1/models` | — | deployed models with their validation metrics |
| `GET /terminal` (public page) | — | web terminal; asks for an API key |

Symbols are the canonical ones stored in `trades.symbol`: `BTCUSDT` (Binance
spot), `BTCUSDT-PERP` (Bybit), `BTC-USDT` (OKX), `BTC-USD` (Coinbase).

## Signal fields

| Field | Meaning |
|---|---|
| `spike_bps`, `spike_dir`, `bucket` | the tick move that triggered the event, and its percentile bucket vs the trailing distribution |
| `p_tradeable` | Stage 1: P(\|move\| > cost within the horizon); `null` if no Stage 1 model |
| `p_continuation` | Stage 2: P(the move continues in the spike direction) |
| `joint_score` | `p_tradeable × P(predicted direction)` |
| `signal` | `CONTINUATION`, `ABSORPTION`, `NO_EDGE` (Stage 1 below threshold) or `UNSCORED` (no model) |
| `status` | `PENDING` → `RESOLVED` or `NO_DATA` |
| `price_entry` | first trade ≥ event + entry delay |
| `ret_10s_bps`, `ret_30s_bps` | market return from entry |
| `pnl_10s_bps`, `pnl_30s_bps` | `predicted_dir × ret − cost_bps` |
