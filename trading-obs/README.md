# Kerno

**Crypto market microstructure data and research infrastructure.**

Kerno captures tick-level trades from Binance, Bybit, OKX and Coinbase into
one canonical schema. It detects microstructure events point-in-time, scores
them with validated two-stage models, and measures every signal's outcome net
of trading costs. Every number it publishes is reproducible from stored data.

> Kerno is not a trading bot and does not place orders.

```
exchanges ─► ingest ─► trades (Postgres/Supabase) ─► engine ─► signals ◄─ validator
                            │                                    │
                            └─► archive (Parquet, verified)       └─► read-only API ─► clients
```

See [docs/architecture.md](docs/architecture.md) for the guarantees (no
look-ahead, determinism, no train/serve skew, honest outcomes) and how they
are tested.

## Quick start (local, SQLite)

```bash
cd trading-obs
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[archive,train,dev]"
cp .env.example .env                              # set DATABASE_URL=sqlite:///kerno.db for local
kerno init-db
kerno keys create me                              # prints your API key once
kerno run-all                                     # terminal 1: ingest + engine + validator + basis
kerno api                                         # terminal 2: http://127.0.0.1:8000/terminal
```

## Cloud (Supabase)

[docs/cloud.md](docs/cloud.md) covers why Supabase rather than Firebase,
sizing, migrating an old local `kerno.db`, archiving to Supabase Storage, and
where to run the workers.

## Commands

| Command | What it does |
|---|---|
| `kerno init-db` | apply migrations (tables, indexes, RLS lock-down on Supabase) |
| `kerno run-all` / `ingest` / `engine` / `validate [--once]` / `basis` | workers |
| `kerno api [--host --port]` | read-only HTTP API + terminal |
| `kerno replay --exchange --symbol` | recompute signals over stored history (same code as live) |
| `kerno train --exchange --symbol [--stage 1\|2\|all]` | train, validate, and deploy only if the gate passes |
| `kerno archive [--before-days 7] [--delete]` | verified Parquet export (+ S3 upload), optional hot-store cleanup |
| `kerno migrate-sqlite PATH [--since-days N]` | import a legacy or local SQLite database |
| `kerno keys create\|list\|revoke` | API keys per client |

## Models

No model is deployed by default (`models/manifest.json` is empty). The v0.x
pickles were removed: they were trained on features that can't be reproduced
live, with time leakage in calibration ([docs/audit.md](docs/audit.md)).
Until a model passes the gate, signals are recorded as `UNSCORED` with their
full feature vectors, which is the training set for the next model:

```bash
kerno replay --exchange binance --symbol BTCUSDT
kerno validate --once
kerno train --exchange binance --symbol BTCUSDT
```

The gate requires test-segment AUC > 0.55 and, for the direction model,
positive mean PnL after `KERNO_COST_BPS`, measured over every event in the
test period.

## Tests

```bash
pytest                                   # SQLite
KERNO_TEST_POSTGRES_URL=postgresql://... pytest    # also against Postgres
```

CI runs lint, the full suite on SQLite and on a Postgres set up like Supabase
(`anon`/`authenticated` roles with default grants), and `pip-audit` on the
hash-pinned lock file.

## Docs

- [architecture.md](docs/architecture.md): pipeline, guarantees, tables
- [api.md](docs/api.md): endpoints and fields
- [replay.md](docs/replay.md): determinism contract and versioning
- [schemas.md](docs/schemas.md), [connectors.md](docs/connectors.md): canonical schema and exchange findings
- [cloud.md](docs/cloud.md): Supabase deployment (in Spanish)
- [audit.md](docs/audit.md): September 2026 security and integrity audit
- [vision.md](docs/vision.md)
