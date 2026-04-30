-- Trading Observability - Event Store
-- Schema v0.1

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS market_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          TEXT NOT NULL,
    event_type      TEXT NOT NULL,          -- 'trade', 'price_tick'
    price           NUMERIC(20, 8) NOT NULL,
    quantity        NUMERIC(20, 8) NOT NULL,
    event_time      TIMESTAMPTZ NOT NULL,   -- timestamp from Binance
    ingest_time     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    latency_ms      INTEGER GENERATED ALWAYS AS (
                        EXTRACT(EPOCH FROM (ingest_time - event_time)) * 1000
                    ) STORED,
    trade_id        BIGINT,                 -- Binance trade ID
    is_buyer_maker  BOOLEAN,
    raw             JSONB                   -- payload original completo
);

-- Índices para queries frecuentes
-- idx_symbol_time es el más crítico: /replay lo usa en cada request
CREATE INDEX IF NOT EXISTS idx_market_events_symbol_time   ON market_events (symbol, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_market_events_event_time    ON market_events (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_market_events_event_type    ON market_events (event_type);

-- Vista de métricas por ventana de tiempo
CREATE OR REPLACE VIEW metrics_1min AS
SELECT
    symbol,
    date_trunc('minute', event_time)        AS bucket,
    COUNT(*)                                AS trade_count,
    AVG(latency_ms)                         AS avg_latency_ms,
    MAX(latency_ms)                         AS max_latency_ms,
    MIN(price)                              AS price_low,
    MAX(price)                              AS price_high,
    SUM(quantity)                           AS volume,
    AVG(ABS(price - LAG(price) OVER (
        PARTITION BY symbol ORDER BY event_time
    )))                                     AS avg_slippage
FROM market_events
WHERE event_type = 'trade'
GROUP BY symbol, bucket;
