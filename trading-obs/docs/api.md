# API

Base URL (local dev): `http://localhost:8000`

## Current endpoints (v0.1, live)

### `GET /health`

Liveness check. Returns 200 OK if the API process is up and DB connection works.

### `GET /signals`

Returns recent signals (Stage 1 + Stage 2 + joint score) for a symbol.

**Query params:**

| Param | Type | Required | Notes |
|---|---|---|---|
| `symbol` | string | yes | e.g. `BTCUSDT` |
| `limit` | int | no | number of most recent signals, default unspecified |

**Response shape:**

```json
{
  "symbol": "BTCUSDT",
  "price": 78128.15,
  "event_time_ms": 1777666951310,
  "signal": "CONTINUATION",
  "spike_type": "SMALL",
  "score": 0.802,
  "confidence": "HIGH",
  "interpretation": "SMALL spike — directional momentum detected. Continuation likely (80%).",
  "action": "FILTER_IN",
  "drivers": ["latency_ms", "burst_1s", "dir_burst"],
  "p_tradeable": 0.795,
  "joint_score": 0.799
}
```

`joint_score = p_tradeable * score`. `drivers` lists the top contributing features for
this specific prediction.

### `GET /events`

Returns recent raw market events for a symbol.

**Query params:**

| Param | Type | Required | Notes |
|---|---|---|---|
| `symbol` | string | yes | e.g. `BTCUSDT` |
| `limit` | int | no | number of most recent events |

### `GET /terminal`

Serves `terminal.html` — the Signal Terminal UI. Not a JSON endpoint.

## Planned endpoints

### v0.25 (Market Schema)

- `GET /symbols` — returns the Symbol Registry (canonical symbol -> per-exchange
  native symbol mappings).

### v0.6 (Deterministic Replay)

- `POST /replay/sessions` — start a replay session (symbol, date range, speed).
- `GET /replay/sessions/{id}` — replay session status.
- `DELETE /replay/sessions/{id}` — stop a replay session.

### v0.7 (Backtesting)

- `POST /backtest` — run a strategy against a date range, returns performance
  metrics including realistic fees/spread/slippage.

### v0.95 (Alerts)

- `POST /alerts` — register a webhook/Telegram/Discord alert rule.
- `GET /alerts` / `DELETE /alerts/{id}` — manage alert rules.

### v1.0 (Internal Quant API)

- Full REST + WebSocket surface, API-key authenticated. Existing endpoints above
  migrate under this auth requirement.

## Auth

No authentication currently (local dev only). API-key auth is planned for v1.0
(Internal Quant API) and is a hard requirement before any public exposure.
