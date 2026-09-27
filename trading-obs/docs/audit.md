# Security and integrity audit (September 2026)

Scope: the whole repository as of commit `0752a7c` (v0.75). Status column
reflects the v1.0 restructure.

The most serious problems were not classic security bugs. They were
**integrity** bugs: the published track record could not be trusted. For a
product meant to serve funds that is the worst possible failure, because it is
exactly what a quant due-diligence review checks first.

## Critical — integrity of the track record

| # | Finding | Where (v0.75) | Status |
|---|---|---|---|
| C1 | `GET /events` inserted a row into `signal_outcomes` for every qualifying event **on every request**. Each dashboard refresh duplicated signals; anyone could inflate or skew `/accuracy` with a `curl` loop. | `api.py:423` | **Fixed.** The API is read-only; signals are written only by the engine worker, idempotently (`UNIQUE` per trade + feature version). Regression test: `tests/test_api.py::test_get_requests_never_write`. |
| C2 | Look-ahead with an inverted sign in `/events`: rows were iterated newest-first, so `prev_price` was the *later* trade. The "spike" of each trade used the next trade's price, and the signal was recorded at the earlier trade's timestamp. | `api.py:402-423` | **Fixed.** `kerno/engine.py` processes trades in event-time order; features use only prior trades. Tests: `test_no_look_ahead`, `test_features_ignore_future_trades`. |
| C3 | `p_tradeable` was not produced by the Stage 1 model (never loaded). It was a hand-written formula of the Stage 2 score itself. `joint_score` was a mean, while the README described a product. | `api.py:306, 623-624` | **Fixed.** Stage 1 and Stage 2 are real models; `joint_score = P(tradeable) × P(direction)`, and it is `null` when Stage 1 isn't deployed. |
| C4 | Validator threshold used volatility from signals *after* the one being judged (no upper time bound). Outcomes ignored fees and spread, and used a ±band that labelled most outcomes NEUTRAL. | `validator.py:44-60` | **Fixed.** Outcomes are raw signed returns plus PnL net of `KERNO_COST_BPS`, entered after `KERNO_ENTRY_DELAY_MS`, from trades strictly after the signal, and only once data covers the horizon (data watermark). |
| C5 | `cleaner.py` deleted every trade older than 2 hours, contradicting the "deterministic replay is the moat" thesis. | `cleaner.py:10` | **Fixed.** Replaced by `kerno archive`: verified Parquet (row count + SHA-256, manifest table, optional S3 upload) *before* any deletion, and deletion only with `--delete`. |
| C6 | The production model (`save_model.py`) was fitted on 100% of the data with a shuffled 5-fold `CalibratedClassifierCV` (time leakage). The README's purged-walk-forward AUC came from a different script and did not describe the deployed artifact. | `research/save_model.py` | **Fixed.** `kerno train`: time-ordered train/calibration/test split with embargo, walk-forward AUC, and a deployment gate (test AUC and net-of-cost PnL). The metrics are stored inside the artifact. |
| C7 | Features were produced offline by a chain of scripts that rewrote `feature_store` in place (`fix_spread2.py`, `fix_volatility2.py` with a non-idempotent transform, …). No live process updated `feature_store`, so `/signals` served stale backfilled rows as "live". `latency_ms` (a property of the collector's network, not the market) was a model input. | `research/*` | **Fixed.** One versioned feature module (`kerno/features.py`, `FEATURE_VERSION`) is used live, in replay and in training. Latency is not a feature. |

## High — security

| Finding | Status |
|---|---|
| No authentication, rate limit or CORS policy; a public deploy was planned (`terminal.html` pointed at Railway). Combined with C1, anyone could also write to the DB. | **Fixed.** Per-client API keys (only SHA-256 stored), revocation, per-key token-bucket rate limit, audit log of every request, explicit CORS allowlist, security headers + strict CSP. |
| Models loaded with `pickle.load`: whoever can replace a `.pkl` gets code execution in the API process. `.pkl` files were committed despite `.gitignore`. | **Fixed.** Models are plain JSON (coefficients + scaler + isotonic table), inference is pure Python, and each file must match its SHA-256 in `models/manifest.json`. All `.pkl` removed. |
| Unpinned dependencies (`requirements.txt` without versions). | **Fixed.** Hash-pinned locks (`pip-compile --generate-hashes`), `pip-audit` in CI, Dependabot. |
| `docker-compose.yml` used `postgres/postgres` and `admin/admin`, published 5432 and 5050 on all interfaces; `setup.sh` wrote the same credentials to `.env`. | **Fixed.** Password must come from `.env`; ports bound to `127.0.0.1`; pgAdmin removed; non-root container image. |
| Unbounded queries on SQLite (`/metrics?minutes=1440`, `/replay` without window limit) blocked the ingestor's writes. | **Fixed.** Postgres, bounded windows (replay ≤ 1h, metrics ≤ 4h), strict parameter validation. |
| Supabase exposes the `public` schema through PostgREST to the `anon` key by default. | **Mitigated by design.** The migration enables RLS on every table and revokes all privileges from `anon`/`authenticated`. Test: `test_supabase_anon_role_is_locked_out`. |

## Medium / low

| Finding | Status |
|---|---|
| XSS sinks: `innerHTML` with API data in three dashboards. | **Fixed.** A single terminal renders with `textContent` only; no inline script. |
| Request-history-dependent output (`_streak_cache` raised confidence the more the endpoint was called); `_pct_cache` never refreshed. | **Fixed.** The engine is a pure function of the trade sequence. |
| `/signals` returned HTTP 500 when the model was missing. | **Fixed.** Signals are recorded as `UNSCORED` without models. |
| ~100 `patch_*.py` / `fix_*.py` scripts rewrote `api.py` by string manipulation; no traceability. | **Fixed.** Removed. The remaining analysis scripts live in `research/legacy/` and are documented as non-production. |
| Connectors stored the whole batched message as `raw` on every trade of the batch (DB bloat); OKX only pinged when a message arrived (quiet feeds died); `websockets` HTTP errors other than `OSError` crashed the connector. | **Fixed.** Per-trade raw (optional), independent ping task, exponential backoff with jitter, stale-feed detection. |
| No tests, no CI. | **Fixed.** 58 tests, run on SQLite and on Postgres configured like Supabase. |
| Prices stored as floats. | **Not an issue on closer inspection.** IEEE-754 doubles round-trip every decimal of ≤15 significant digits, which covers exchange price and size strings. |

## Still open (outside the code)

- **Exchange data licensing.** Redistributing Binance/Bybit/OKX/Coinbase market data to third parties is governed by each exchange's terms. Resolve this before charging clients for raw data.
- **Regulatory.** Selling directional signals to funds may be regulated investment advice in some jurisdictions (e.g. the US Investment Advisers Act). Get legal advice before selling signals. Selling data and tooling is lower risk.
- **Geo-blocking.** Binance.com and Bybit reject US IP addresses. Run the ingestor in a non-US region.
- **SOC 2.** Needed for most institutional clients; start with a Type I once the platform is in the cloud.
- **Coinbase `side` semantics** in `market_trades` should be verified against a recorded session before flow features from Coinbase are relied on.
- **GitHub Actions** are pinned to version tags; pin them to commit SHAs for a stricter supply chain.
