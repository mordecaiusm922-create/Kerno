# Legacy research scripts (v0.1 – v0.75)

Kept for provenance only. **Not production code, not maintained.**

- They read the pre-v1 SQLite schema (`market_events`, `feature_store`) from a local `kerno.db`.
- Several contain the integrity problems documented in `docs/audit.md`: in-place feature rewrites, a shuffled calibration split, `latency_ms` used as a feature, and training on the full dataset.
- The scripts that rewrote application code (`patch_*.py`, `fix_api.py`, `gen_frontend*.py`, …) were deleted; they remain in git history.

Their replacements: `kerno replay` (features and signals), `kerno validate` (outcomes) and `kerno train` (purged, gated training).
