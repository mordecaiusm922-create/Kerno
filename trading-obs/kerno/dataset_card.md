---
license: cc-by-nc-4.0
pretty_name: Kerno Crypto Microstructure Events
tags:
  - finance
  - crypto
  - market-microstructure
  - time-series
  - bitcoin
size_categories:
  - 100K<n<10M
configs:
  - config_name: events
    data_files: "events/**/*.parquet"
    default: true
  - config_name: summary
    data_files: "summary/**/*.parquet"
  - config_name: basis
    data_files: "basis/**/*.parquet"
---

# Kerno Crypto Microstructure Events

A daily, **verifiable** dataset of tick-level microstructure events for BTC and ETH on
Binance (spot and USDT-M perpetual) and Bybit (perpetual). Each event comes with
point-in-time features and the **realized outcome** 10 s and 30 s later.

It is built to be the dataset you would want for machine learning on market
microstructure, without the usual traps:

- **No look-ahead.** Features use only trades at or before the event. Outcomes use only later trades.
- **Realistic entry.** The outcome is measured from the first trade 250 ms after the event, not from the print that triggered it.
- **Deterministic and reproducible.** Every file is regenerated bit-for-bit from the exchanges' public dumps by open-source code with the pinned dependency versions (`requirements.txt`). The manifest records the exact source SHA-256s, output SHA-256s, code version and parameters.

## Files

| Config | Path | One row per |
|---|---|---|
| `events` | `events/exchange=*/symbol=*/date=*/events.parquet` | detected event |
| `summary` | `summary/date=*/summary.parquet` | stream × day |
| `basis` | `basis/pair=*/date=*/basis_1m.parquet` | minute (Binance spot vs USDT-M perp) |
| — | `manifest/date=*.json` | day: provenance and parameters |

### `events` columns

| Column | Meaning |
|---|---|
| `exchange`, `symbol` | `binance`/`bybit`; `BTCUSDT` = spot, `BTCUSDT-PERP` = perpetual |
| `exchange_trade_id`, `event_time_ms`, `price` | the trade that triggered the event |
| `spike_bps`, `spike_dir` | tick move that triggered it (bps, ±1) |
| `bucket` | size vs the trailing 5-minute distribution: `MEDIUM` (≥p75), `LARGE` (≥p90), `EXTREME` (≥p99) |
| `status` | `RESOLVED`, or `NO_DATA` if the tape had a gap > 5 s at an outcome time |
| `price_entry` | first trade ≥ event + 250 ms |
| `price_10s`, `price_30s` | first trade ≥ event + 10 s / 30 s |
| `ret_10s_bps`, `ret_30s_bps` | `(exit − entry) / entry × 1e4` |
| `f_*` | point-in-time features (spike z-score/percentile, Roll spread, realized volatility 5 s/1 m/5 m, aggressor-flow imbalance, burstiness, trade density, …) |
| `feature_version`, `engine_version` | definitions used |

An event is a trade whose tick return is ≥ 1 bp and at least the 75th
percentile of the non-zero tick returns of the previous 5 minutes, with at
most one event per stream per second.

### `summary` headline columns

`continuation_rate_10s` is the share of events whose 10 s move continued the
spike direction. `share_abs_ret_10s_gt_cost` is the share that moved more than
the reference round-trip cost (`cost_bps`).

## Verify it yourself

```bash
git clone https://github.com/mordecaiusm922-create/Kerno && cd Kerno/trading-obs
pip install --require-hashes -r requirements.txt && pip install --no-deps -e .
kerno dataset build --date 2026-09-20 --out check/
# compare check/manifest/date=2026-09-20.json "outputs[*].sha256" with this repository's manifest
```

## Sources and license

Derived from the public trade dumps published by Binance (data.binance.vision)
and Bybit (public.bybit.com). Raw trades are not redistributed here.

The dataset is licensed **CC BY-NC 4.0**: free for research and non-commercial
use with attribution. For commercial use, fresher data or an API, open an issue
in the GitHub repository.

**Not investment advice.** This is descriptive market data. Past event outcomes
do not predict future returns, and nothing here is a recommendation to trade.
