# Trading Observability — v0.1

> Ingestor async de trades en tiempo real desde Binance,
> con persistencia en PostgreSQL y cálculo de latencia.

## Stack

- **Ingestor**: Python async + WebSockets (Binance)
- **DB**: PostgreSQL 16 (event store con latency_ms generado)
- **API**: FastAPI + asyncpg
- **Infra local**: Docker Compose

---

## Arrancar en 3 pasos

### 1. Levantar PostgreSQL

```bash
docker-compose up -d postgres
```

El schema se aplica automáticamente al iniciar.

### 2. Instalar dependencias Python

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Correr el ingestor

```bash
# BTC por defecto
python ingestor.py

# Múltiples símbolos
python ingestor.py --symbols BTCUSDT ETHUSDT SOLUSDT
```

### 4. Correr la API (otra terminal)

```bash
uvicorn api:app --reload --port 8000
```

Docs interactivas: http://localhost:8000/docs

---

## Variables de entorno

Crea un `.env` en la raíz (opcional, ya hay defaults):

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trading_obs
```

---

## Endpoints

| Endpoint | Descripción |
|---|---|
| `GET /events?symbol=BTCUSDT&limit=100` | Últimos N trades |
| `GET /replay?symbol=BTCUSDT&from=...&to=...` | Replay por rango de tiempo |
| `GET /metrics?symbol=BTCUSDT&minutes=60` | Latencia + slippage + volumen |
| `GET /health` | Healthcheck |

---

## Qué mide el sistema

```
latency_ms = ingest_time - event_time (Binance timestamp)
```

Cada evento guardado incluye:
- Precio y cantidad exacta
- Timestamp del exchange vs timestamp local → **latencia del feed**
- Si el buyer es maker (dirección del trade)
- Payload raw en JSONB (para queries futuras)

---

## Estructura del proyecto

```
trading-obs/
├── ingestor.py          ← WebSocket async + batch writer
├── api.py               ← FastAPI endpoints
├── db/
│   ├── schema.sql       ← Event store + vista metrics_1min
│   └── connection.py    ← Pool asyncpg
├── requirements.txt
├── docker-compose.yml
└── README.md
```

---

## Próximo paso natural

Una vez que tienes datos fluyendo:

1. **Frontend**: Timeline visual con `lightweight-charts`
2. **Alertas**: Detectar spikes de latencia (>100ms)
3. **User trades**: Permitir subir trades propios y compararlos con el mercado
4. **Anomaly detection**: Identificar comportamientos raros automáticamente
