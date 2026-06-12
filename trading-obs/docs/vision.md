# Vision

## What Kerno is

Kerno is a quantitative research infrastructure for market microstructure. It ingests
tick-level data from exchanges, computes microstructural features, and classifies
short-horizon market events (continuation vs. absorption vs. no-edge) using
asset-specific calibrated models.

The core deliverable is **reproducibility**: any market state can be reconstructed
deterministically from historical data, replayed, and re-scored under the same
feature definitions that were used in production at that point in time.

## What Kerno is not

- Kerno is not a trading bot. It does not place orders or manage positions.
- Kerno is not a signal-selling service. Output is information for a decision layer,
  not an execution instruction.
- Kerno is not a generic "pooled" classifier. BTC and ETH (and future assets) have
  distinct generating processes and get distinct models.
- Kerno is not built around adding more LLM-based components to the data core.

## Thesis

The metric that matters is not "how many exchanges are connected" but "how many
markets can be reproduced deterministically from historical data." Connector count is
a vanity metric; deterministic replay is the moat.

## Guiding principles

1. **Schema first.** Market Schema → Connector SDK → Exchange Adapters, in that order.
   Every adapter normalizes into the same canonical event types.
2. **Replay determinism as the core primitive.** Backtesting, anomaly detection, and
   feature recomputation all sit on top of the replay engine, not beside it.
3. **Strict separation of concerns.** Raw data, normalized events, computed features,
   signals, and outcomes are distinct layers. Feature computation never sees
   post-event data; label generation never leaks into feature computation.
4. **Two-stage modeling.** Tradability (Stage 1) is decided before direction
   (Stage 2). A single model that tries to answer both questions collapses to
   "everything is neutral" when markets are mostly flat.
5. **Per-asset models, not pooled models.** BTC responds to friction (spike size,
   spread, volatility). ETH responds to flow (burst acceleration, signed imbalance).
   Pooling these processes destroys signal.
6. **Validation discipline.** Purged walk-forward with embargo is mandatory. Random
   splits are never acceptable for time-series microstructure data.
7. **Prove depth before breadth.** Ten robust connectors before a hundred connectors.
   SQLite/DuckDB for research before ClickHouse/Postgres at scale.

## Roadmap shape

The roadmap (v0.1 → v3.0) moves from "stabilize the current single-exchange
prototype" through "formalize schemas and connector SDK" to "deterministic replay and
backtesting" and finally to "multi-exchange scale." Each milestone is defined by a
verifiable capability, not a date.
