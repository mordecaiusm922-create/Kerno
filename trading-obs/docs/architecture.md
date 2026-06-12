# Architecture

## Current pipeline (v0.1)

```
Binance WebSocket
      |
      v
  ingestor.py  ----------------------------> kerno.db (SQLite)
                                                  |
                                                  v
                                          market_events
                                          (3M+ ticks, BTC/ETH)
                                                  |
                                                  v
                                          feature_store
                                          (233k rows, versioned features)
                                                  |
                    +-----------------------------+-----------------------------+
                    v                                                             v
            Stage 1: kerno_stage1.pkl                              Stage 2: kerno_model_final.pkl
            (tradability filter, LogReg)                            (directional classifier, LogReg calibrated)
            features:                                                features (per-asset):
              - event_density_1m / 5m                                 - spike_pct, zscore
              - density_ratio                                         - spread_est, volatility_1m
              - vol_compression                                       - latency_ms, imbalance_20
              - spread_est / spread_z_5m                               - burst_1s, vol_ratio, dir_burst
              - burstiness_5m
              - density_x_spread
                    |                                                             |
                    +----------------> joint_score = p_tradeable * score <-------+
                                                  |
                                                  v
                                          FastAPI /signals
                                                  |
                                                  v
                                          terminal.html (Signal Terminal)
                                                  |
                                                  v
                                          validator.py
                                          -> signal_outcomes (WIN/LOSS/NEUTRAL,
                                             resolved at 10s/30s horizons)
```

## Layer separation (enforced)

| Layer | Description | Lives in |
|---|---|---|
| Raw data | Unmodified exchange messages | `market_events` table |
| Normalized events | Canonical schema (post v0.25) | future: `events` table per Market Schema |
| Features | Computed from normalized events, versioned by formula | `feature_store` |
| Signals | Model output (Stage 1 + Stage 2 + joint score) | `/signals` API response |
| Outcomes | Resolved labels for validation | `signal_outcomes` |

Feature computation must never read post-event data. Label generation must never feed
back into feature computation. This separation is what the purged walk-forward
validation depends on.

## Two-stage model architecture

**Stage 1 (tradability filter):** answers "is this moment economically actionable at
all?" Trained on BTC+ETH pooled, since the question is asset-agnostic (is the market
moving enough to matter). Output: `p_tradeable`.

**Stage 2 (directional classifier):** answers "given that it's actionable, which
direction (continuation vs. absorption)?" Trained separately per asset, since BTC and
ETH have distinct generating processes:

- **BTC friction model**: driven by spike size, spread, volatility ratio.
- **ETH flow model**: driven by signed order flow imbalance, burst acceleration,
  return acceleration.

**Joint score:** `joint_score = p_tradeable * score`. This is the single number the
terminal and downstream consumers act on.

## Why two-stage and per-asset

158/161 historical outcomes were NEUTRAL because the market was flat most of the
time. A single model trying to learn both "is this actionable" and "which direction"
simultaneously collapses to predicting NEUTRAL everywhere. Splitting the questions
lets Stage 1 learn market-state actionability and Stage 2 learn direction
conditioned on actionability.

A pooled BTC+ETH directional model collapses toward AUC ~0.5 because the two assets'
generating processes (friction vs. flow) are different enough that shared
coefficients average out the signal in both.

## Validation

Purged walk-forward, 60-second embargo between train/test windows. Random splits are
disallowed for any model in this pipeline — temporal leakage in tick data is severe
and not visually obvious in aggregate metrics.

## Stack by stage

| Stage | Storage | Notes |
|---|---|---|
| Now (v0.1–v0.5) | SQLite | Sufficient for single-machine research; ~1GB scale |
| v0.5+ | DuckDB / ClickHouse | Once historical storage formalizes hot/cold partitioning |
| v2.0+ | Parquet + Postgres + Redis/NATS | Multi-exchange scale, streaming features |

## Current known gaps (tracked, not blocking v0.1)

- No formal Market Schema yet — `market_events` is Binance-shaped, not canonical
  (addressed in v0.25).
- No Connector SDK — Binance ingestion is hand-written, not behind an interface
  (addressed in v0.35).
- No deterministic replay engine — backtesting cannot yet reconstruct exact historical
  market state (addressed in v0.6).
- Feature store is not versioned by formula — recomputing features with a changed
  definition would silently mix old/new values (addressed in v0.8).

## Components reference

| File | Role |
|---|---|
| `ingestor.py` | Binance WebSocket → `market_events` (SQLite) |
| `api.py` | FastAPI app, serves `/health`, `/signals`, `/events` |
| `validator.py` | Background process resolving pending signal outcomes at 10s/30s |
| `terminal.html` | Signal terminal UI, served at `/terminal` |
| `kerno_stage1.pkl` | Stage 1 tradability model |
| `kerno_model_final.pkl` | Stage 2 directional models (BTC friction + ETH flow) |
| `kerno_model_v3.pkl` | Experimental pooled model with interaction terms (research only) |
| `feature_specs/*.yaml` / `*.json` | Declarative feature definitions per model |
| `research/` | Patch/fix/train/build scripts — not part of the production path |
