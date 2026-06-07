# Kerno

**Real-time market microstructure research engine.**

Kerno ingests tick-level trade events from Binance, computes microstructure features, and classifies market events as continuation, absorption, or no-edge using asset-specific calibrated models.

---

## What it is

Kerno is a **research infrastructure** for market microstructure intelligence — not a trading bot.

It answers one question per event:

> "Is this market event economically actionable, and if so, is it continuation or absorption?"

---

## Architecture

```
Binance WebSocket → ingestor.py → kerno.db (SQLite)
                                       ↓
                              feature_store (233k rows)
                                       ↓
                    Stage 1: Tradability filter (P(tradeable))
                                       ↓
                    Stage 2: Directional classifier (P(continuation))
                                       ↓
                         Joint score = P(tradeable) × P(continuation)
                                       ↓
                    FastAPI /signals → terminal dashboard
```

---

## Models

Two asset-specific models validated with purged walk-forward (60s embargo):

| Model               | Asset   | Type                | Purged AUC | Brier |
| ------------------- | ------- | ------------------- | ---------- | ----- |
| BTC friction model  | BTCUSDT | Logistic Regression | 0.634      | 0.058 |
| ETH flow model      | ETHUSDT | Logistic Regression | 0.662      | 0.089 |
| Stage 1 tradability | Both    | Logistic Regression | 0.647      | —     |

**BTC** responds to spike size and microstructure friction.
**ETH** responds to aggressive flow persistence and burst acceleration.

---

## Honest limitations

* Models calibrated on May 2026 data (~13 days BTC, ~10 hours ETH)
* 158/161 validator outcomes were NEUTRAL — market was below economic threshold during capture
* Stage 1 distribution is compressed (std ~0.04) — needs more regime diversity
* SQLite is adequate for research; production would require TimescaleDB or DuckDB
* No execution-aware backtesting yet (fees, slippage not modeled)

---

## API

| Endpoint        | Description                                  |
| --------------- | -------------------------------------------- |
| `GET /signals`  | Live ML signals with joint score and drivers |
| `GET /events`   | Raw events with spike intelligence           |
| `GET /accuracy` | Live win rate from validator                 |
| `GET /metrics`  | Bucketed market metrics                      |
| `GET /terminal` | Signal terminal dashboard                    |
| `GET /health`   | System status                                |

Example `/signals` response:

```json
{
  "symbol": "BTCUSDT",
  "signal": "CONTINUATION",
  "score": 0.802,
  "p_tradeable": 0.795,
  "joint_score": 0.799,
  "confidence": "HIGH",
  "drivers": ["latency_ms", "burst_1s", "dir_burst"],
  "action": "FILTER_IN"
}
```

---

## Running locally

```bash
# Terminal 1 — ingestor
python ingestor.py

# Terminal 2 — API
uvicorn api:app --reload

# Dashboard
open http://localhost:8000/terminal
```

---

## Stack

* **Ingestion:** Python, Binance WebSocket
* **Storage:** SQLite (~938 MB, 3M+ events)
* **API:** FastAPI + Uvicorn
* **ML:** scikit-learn (LogisticRegression, isotonic calibration)
* **Dashboard:** Vanilla JS
* **Validation:** Purged walk-forward, 60s embargo

---

## Feature specs

* `feature_specs/eth_flow_v1.json` — ETH flow model features
* `feature_specs/stage1_tradability_v1.yaml` — Stage 1 tradability filter spec

---

## Status

> Kerno is in **research infrastructure** phase.
> The pipeline is operational. The signal exists but has not been validated against execution costs.
> Next: execution-aware labeling, DuckDB migration, regime-conditioned retraining.
