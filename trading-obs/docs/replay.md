# Replay Engine

> Status: specification skeleton. Full design is scoped for v0.6 (Deterministic
> Replay). This document exists so v0.15 has placeholders for every planned doc; it
> is not a complete spec.

## Goal

Reconstruct any historical market state, byte-for-byte, from stored raw/normalized
events, and replay it at configurable speed (1x / 10x / 100x / as-fast-as-possible)
through the same feature computation and signal pipeline that runs in production.

## TODO before v0.6 design is final

- [ ] Define replay determinism guarantee precisely: same input events + same feature
      formula version -> byte-identical feature values and signals, regardless of
      wall-clock time of replay.
- [ ] Decide event ordering tiebreak rule when `event_time_ms` collides across
      multiple events (likely: exchange sequence number, then ingest order).
- [ ] Define replay session API: start/stop, speed control, symbol/date range
      selection, output sink (live feature_store vs. isolated replay table).
- [ ] Decide whether replay re-runs the full pipeline (ingestor-equivalent ->
      feature_store -> models -> signals) or starts from stored normalized events
      (skipping raw ingestion).
- [ ] Define how feature formula versioning (v0.8) interacts with replay — can a
      replay session pin a specific formula version?
- [ ] Define backtesting integration point (v0.7 depends on this).

## Constraints carried from architecture.md

- Replay must not introduce non-determinism (no wall-clock dependent code paths in
  feature computation).
- Replay reads from the canonical Market Schema (v0.25), not from exchange-native
  tables.
