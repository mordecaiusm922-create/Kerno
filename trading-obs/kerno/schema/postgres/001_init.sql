-- Kerno schema v1 (PostgreSQL / Supabase)
--
-- Hot store only: raw trades are kept here for a rolling window and archived
-- to immutable Parquet (see `kerno archive`). Signals, outcomes and basis
-- history are kept forever.

CREATE TABLE IF NOT EXISTS trades (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exchange          TEXT             NOT NULL,
    symbol            TEXT             NOT NULL,
    exchange_trade_id TEXT             NOT NULL,
    price             DOUBLE PRECISION NOT NULL CHECK (price > 0),
    quantity          DOUBLE PRECISION NOT NULL CHECK (quantity >= 0),
    side              TEXT             NOT NULL CHECK (side IN ('buy', 'sell')),
    event_time_ms     BIGINT           NOT NULL,
    ingest_time_ms    BIGINT           NOT NULL,
    raw               TEXT,
    UNIQUE (exchange, symbol, exchange_trade_id)
);
CREATE INDEX IF NOT EXISTS idx_trades_sym_time ON trades (exchange, symbol, event_time_ms, exchange_trade_id);
CREATE INDEX IF NOT EXISTS brin_trades_event_time ON trades USING brin (event_time_ms);

CREATE TABLE IF NOT EXISTS symbol_registry (
    canonical_symbol TEXT NOT NULL,
    exchange         TEXT NOT NULL,
    native_symbol    TEXT NOT NULL,
    asset_base       TEXT NOT NULL,
    asset_quote      TEXT NOT NULL,
    instrument       TEXT,
    instrument_type  TEXT NOT NULL CHECK (instrument_type IN ('spot', 'perp', 'future')),
    tick_size        DOUBLE PRECISION,
    lot_size         DOUBLE PRECISION,
    PRIMARY KEY (canonical_symbol, exchange)
);

CREATE TABLE IF NOT EXISTS basis_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts_ms       BIGINT           NOT NULL,
    spot_price  DOUBLE PRECISION NOT NULL,
    spot_ts_ms  BIGINT           NOT NULL,
    perp_price  DOUBLE PRECISION NOT NULL,
    perp_ts_ms  BIGINT           NOT NULL,
    basis_pct   DOUBLE PRECISION NOT NULL,
    okx_price   DOUBLE PRECISION,
    okx_ts_ms   BIGINT,
    UNIQUE (ts_ms)
);

-- One row per detected market event, written by the signal engine.
-- Features are computed only from trades at or before the event trade.
-- Outcome columns are filled later by the validator from trades strictly after it.
CREATE TABLE IF NOT EXISTS signals (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exchange          TEXT             NOT NULL,
    symbol            TEXT             NOT NULL,
    exchange_trade_id TEXT             NOT NULL,
    event_time_ms     BIGINT           NOT NULL,
    price             DOUBLE PRECISION NOT NULL,
    spike_bps         DOUBLE PRECISION NOT NULL,
    spike_dir         SMALLINT         NOT NULL,
    bucket            TEXT             NOT NULL,
    features          TEXT             NOT NULL,
    p_tradeable       DOUBLE PRECISION,
    p_continuation    DOUBLE PRECISION,
    joint_score       DOUBLE PRECISION,
    signal            TEXT             NOT NULL,
    predicted_dir     SMALLINT,
    stage1_model      TEXT,
    stage2_model      TEXT,
    feature_version   TEXT             NOT NULL,
    engine_version    TEXT             NOT NULL,
    created_at_ms     BIGINT           NOT NULL,
    status            TEXT             NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'RESOLVED', 'NO_DATA')),
    price_entry       DOUBLE PRECISION,
    price_10s         DOUBLE PRECISION,
    price_30s         DOUBLE PRECISION,
    ret_10s_bps       DOUBLE PRECISION,
    ret_30s_bps       DOUBLE PRECISION,
    pnl_10s_bps       DOUBLE PRECISION,
    pnl_30s_bps       DOUBLE PRECISION,
    cost_bps          DOUBLE PRECISION,
    resolved_at_ms    BIGINT,
    UNIQUE (exchange, symbol, exchange_trade_id, feature_version)
);
CREATE INDEX IF NOT EXISTS idx_signals_sym_time ON signals (exchange, symbol, event_time_ms);
CREATE INDEX IF NOT EXISTS idx_signals_pending ON signals (status, event_time_ms) WHERE status = 'PENDING';

CREATE TABLE IF NOT EXISTS engine_state (
    exchange                TEXT   NOT NULL,
    symbol                  TEXT   NOT NULL,
    feature_version         TEXT   NOT NULL,
    last_event_time_ms      BIGINT NOT NULL,
    last_exchange_trade_id  TEXT   NOT NULL,
    updated_at_ms           BIGINT NOT NULL,
    PRIMARY KEY (exchange, symbol, feature_version)
);

CREATE TABLE IF NOT EXISTS api_keys (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name               TEXT    NOT NULL,
    key_prefix         TEXT    NOT NULL,
    key_hash           TEXT    NOT NULL UNIQUE,
    rate_limit_per_min INTEGER,
    created_at_ms      BIGINT  NOT NULL,
    revoked_at_ms      BIGINT
);

CREATE TABLE IF NOT EXISTS api_audit_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts_ms       BIGINT  NOT NULL,
    key_id      BIGINT,
    method      TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    query       TEXT,
    status      INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    client_ip   TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON api_audit_log (ts_ms);

CREATE TABLE IF NOT EXISTS archive_manifest (
    exchange      TEXT   NOT NULL,
    symbol        TEXT   NOT NULL,
    day           TEXT   NOT NULL,
    rows          BIGINT NOT NULL,
    sha256        TEXT   NOT NULL,
    uri           TEXT   NOT NULL,
    created_at_ms BIGINT NOT NULL,
    PRIMARY KEY (exchange, symbol, day)
);

-- Supabase exposes the `public` schema through its auto-generated REST API
-- (PostgREST) to the `anon` and `authenticated` roles. Kerno never uses that
-- API: lock every table down so the anon key can read or write nothing.
-- The table owner (the role Kerno connects as) bypasses RLS.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['trades','symbol_registry','basis_log','signals','engine_state',
                             'api_keys','api_audit_log','archive_manifest','schema_migrations']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I FROM anon', t);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE format('REVOKE ALL ON TABLE %I FROM authenticated', t);
        END IF;
    END LOOP;
END $$;

INSERT INTO symbol_registry
    (canonical_symbol, exchange, native_symbol, asset_base, asset_quote, instrument, instrument_type, tick_size, lot_size)
VALUES
    ('BTCUSDT',      'binance',  'BTCUSDT',  'BTC', 'USDT', 'BTC', 'spot', 0.01, 0.00001),
    ('ETHUSDT',      'binance',  'ETHUSDT',  'ETH', 'USDT', 'ETH', 'spot', 0.01, 0.0001),
    ('BTCUSDT-PERP', 'bybit',    'BTCUSDT',  'BTC', 'USDT', 'BTC', 'perp', 0.1,  0.001),
    ('BTC-USDT',     'okx',      'BTC-USDT', 'BTC', 'USDT', 'BTC', 'spot', 0.1,  0.00000001),
    ('BTC-USD',      'coinbase', 'BTC-USD',  'BTC', 'USD',  'BTC', 'spot', 0.01, 0.00000001)
ON CONFLICT DO NOTHING;
