# Kerno

**Real-time market microstructure intelligence engine.**

Kerno processes raw trade events from crypto exchanges and estimates the probability of short-term price behavior — reversal vs continuation — conditioned on spike characteristics and asset-specific edge maps.

---

## What it is

Most retail trading systems react to price movements without understanding the underlying microstructure dynamics. Kerno focuses on:

- Event-level signal detection (tick data, not candles)
- Latency-aware ingestion and analysis
- Probabilistic outcomes instead of deterministic buy/sell signals
- Real-time validation of signal accuracy (10s / 30s outcomes)

This is not a trading bot. It is a **microstructure intelligence layer**.

---

## Architecture
---

## Key Findings (calibrated on 13h of live data, 2M+ events)

### BTCUSDT
| Bucket  | N     | Rev%  | Cont% | Edge      |
|---------|-------|-------|-------|-----------|
| SMALL   | 2175  | 63.0% | 37.0% | REV_EDGE  |
| MEDIUM  | 437   | 72.8% | 27.2% | REV_EDGE  |
| LARGE   | 263   | 44.7% | 55.3% | NO_EDGE   |
| EXTREME | 30    | 13.0% | 87.0% | CONT_EDGE |

### ETHUSDT
| Bucket  | N     | Rev%  | Cont% | Edge      |
|---------|-------|-------|-------|-----------|
| SMALL   | 1627  | 51.2% | 48.8% | NO_EDGE   |
| MEDIUM  | 325   | 47.3% | 52.7% | NO_EDGE   |
| LARGE   | 196   | 30.3% | 69.7% | CONT_EDGE |
| EXTREME | 22    | 28.6% | 71.4% | CONT_EDGE |

**Interpretation:** Small/medium spikes in BTC tend to revert. Extreme spikes continue. ETH shows edge only in large moves. This is regime-dependent microstructure behavior — not noise.

---

## Confidence Layer

Each signal carries a confidence score computed as:

```
base_confidence = f(bucket)      # SMALL=0.35, MEDIUM=0.62, LARGE=0.80, EXTREME=0.92
streak_bonus    = consecutive_same_signal * 0.04  (capped at 0.15)
confidence      = clip(base + streak_bonus, 0, 1)
```

The Precision Dashboard filters by `min_confidence` (default 0.60), showing only signals with statistical backing.

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /events` | Raw trade events enriched with spike intelligence |
| `GET /signals?min_confidence=0.60` | Filtered high-confidence signals only |
| `GET /accuracy` | Live win rate by signal type (10s and 30s outcomes) |
| `GET /metrics` | Bucketed market metrics by minute |
| `GET /replay` | Historical event replay by time range |
| `GET /backtest` | Spike-follow strategy backtest |
| `GET /dashboard` | Live precision intelligence dashboard |

---

## Honest Limitations

- **Signals at tick level do not yet survive execution costs.** Spread and fees consume the edge in SMALL bucket.
- **MEDIUM bucket shows the strongest signal** (73% reversal, conf=0.730) but sample size is still growing.
- **Validation is ongoing.** Win rate stabilizes after ~50 validated MEDIUM signals.
- The edge map is calibrated on a single market regime (May 2026, BTC ranging ~$78k). Regime changes will require recalibration.

---

## Stack

- **Ingestion:** Python, Binance WebSocket API
- **Storage:** SQLite (kerno.db)
- **API:** FastAPI + Uvicorn
- **Dashboard:** Vanilla JS + Chart.js
- **Validation:** Background thread, SQLite-backed outcomes

---

## Roadmap

- [ ] Higher timeframe aggregation (1m / 5m candles) for signal generation
- [ ] Volume and volatility features
- [ ] Time-of-day regime detection
- [ ] WebSocket push (replace polling)
- [ ] ML-based probability estimation (replace static edge map)
- [ ] Execution-aware backtesting (fees, slippage, latency)
- [ ] Multi-asset correlation layer

---

## Status

> Kerno is in the **research infrastructure** phase.  
> The pipeline is production-grade. The signals are statistically grounded.  
> Profit extraction is the next research problem.

---

## Running locally

```bash
# Terminal 1 — ingestor
python ingestor.py

# Terminal 2 — API
uvicorn api:app --reload

# Dashboard
open http://localhost:8000/dashboard
```
