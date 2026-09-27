# Llevar Kerno a la nube (Supabase)

## ¿Firebase o Supabase?

**Supabase.** Kerno es una serie temporal de ticks con consultas SQL (ventanas, agregaciones por minuto, joins entre exchanges). Eso es exactamente lo que hace Postgres, y Supabase *es* Postgres gestionado.

| | Supabase (Postgres) | Firebase (Firestore) |
|---|---|---|
| Modelo de datos | Tablas SQL; el esquema de Kerno se usa tal cual | Documentos NoSQL: habría que rediseñarlo todo |
| Consultas | `GROUP BY`, ventanas de tiempo, índices compuestos | Sin agregaciones reales ni joins; consultas por rango limitadas |
| Coste con ticks | Se paga por almacenamiento/instancia | **Se paga por cada escritura**. BTCUSDT de Binance genera del orden de 1–3 millones de trades al día, lo que serían millones de escrituras diarias facturadas una a una |
| Salida | `pg_dump` estándar, sin lock-in | Formato propietario |
| Archivos (Parquet) | Supabase Storage con API compatible S3 | Cloud Storage (otro producto) |

Precios orientativos a la fecha de este documento; verifica los vigentes en supabase.com/pricing y firebase.google.com/pricing.

## Cuánto espacio ocupa

- En Postgres, un trade ocupa ~150 bytes con índices, sin `raw`. BTCUSDT + ETHUSDT de Binance, más el perp de Bybit y OKX, son **~200–500 MB por día**.
- En Parquet (zstd) son ~20–40 bytes por trade: **~20–60 MB por día**.

Por eso la base de datos solo guarda una **ventana caliente** (por defecto 7 días) y el histórico completo vive en Parquet (`kerno archive`):

- **Plan Free** (500 MB): alcanza para probar con un solo símbolo y archivando cada día.
- **Plan Pro** (8 GB de disco incluidos): 7 días calientes de 3–4 streams, más señales y basis sin límite práctico.

## Paso a paso

### 1. Crear el proyecto

1. En supabase.com, crea un proyecto nuevo. **Región: Frankfurt (eu-central-1) o Singapur**, no EE. UU.: Binance y Bybit bloquean IPs de EE. UU., y los workers deben estar en la misma región que la base de datos.
2. Guarda la contraseña de la base de datos en un gestor de contraseñas.
3. Ve a **Project Settings → Database → Connection string → Session pooler** y copia la URL. Añade `?sslmode=require` al final.

### 2. Configurar Kerno

```bash
cd trading-obs
cp .env.example .env         # rellena DATABASE_URL con la URL del paso anterior
pip install -e ".[archive,train]"
kerno init-db                # crea las tablas, activa RLS y revoca todo a anon/authenticated
kerno keys create yo         # tu API key; se muestra UNA vez
```

`init-db` deja la API REST automática de Supabase (la de la `anon key`) **sin acceso a ninguna tabla**. Kerno se conecta directamente a Postgres, así que no la necesita.

### 3. Rescatar tu `kerno.db` local (2.5 GB)

Tu histórico no cabe en el plan Free y tampoco tiene sentido meterlo entero en la base caliente. El camino es: esquema limpio en local → señales recalculadas → Parquet → subir a la nube solo lo pequeño.

```bash
# 0. copia de seguridad (fuera del disco de trabajo)
copy kerno.db D:\backup\kerno_2026-09.db

# 1. base v1 local con el histórico completo, en el esquema nuevo
set DATABASE_URL=sqlite:///kerno_v1.db
kerno init-db
kerno migrate-sqlite kerno.db

# 2. recalcular señales sin look-ahead sobre todo el histórico, y sus resultados
kerno replay --exchange binance --symbol BTCUSDT
kerno replay --exchange binance --symbol ETHUSDT
kerno validate --once

# 3. todo el histórico de trades a Parquet (y a Supabase Storage si configuras KERNO_S3_*),
#    y después se borran de la copia local solo los días verificados contra su Parquet
kerno archive --before-days 1 --delete

# 4. a la nube: señales ya resueltas, basis y registro de símbolos (pesan poco).
#    Los trades históricos se quedan en Parquet.
set DATABASE_URL=postgresql://...supabase...
kerno init-db
kerno migrate-sqlite kerno_v1.db
```

Los datos del esquema viejo `signal_outcomes` y `feature_store` **no se migran a propósito**: estaban contaminados por look-ahead (ver `docs/audit.md`).

### 4. Archivo en Supabase Storage (opcional, recomendado)

1. Ve a **Storage → New bucket** y crea `kerno-archive`, **privado**.
2. En **Storage → Settings → S3 connection**, crea un access key y apunta el endpoint y la región.
3. En `.env`, configura `KERNO_S3_BUCKET`, `KERNO_S3_ENDPOINT_URL`, `KERNO_S3_REGION`, `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY`.

`kerno archive` sube cada día, comprueba el tamaño y registra el SHA-256 en `archive_manifest` antes de borrar nada.

### 5. Dónde corren los procesos

La base de datos está en Supabase, pero el ingestor tiene que estar conectado 24/7 a los websockets. **Tu laptop no sirve para eso.** Opciones, todas con el `Dockerfile` incluido:

| Opción | Coste aprox. | Nota |
|---|---|---|
| VPS pequeño (Hetzner, DigitalOcean) en Frankfurt o Singapur | 5–10 USD/mes | `docker compose up -d api worker` |
| Railway / Render / Fly.io | 5–20 USD/mes | Dos servicios desde la misma imagen: `kerno run-all` y `kerno api --host 0.0.0.0` |

Hay que evitar las plataformas "serverless" que apagan el proceso (Cloud Run, Lambda, Vercel), porque cortan los websockets.

Tareas diarias (cron del VPS o *scheduled job* de la plataforma):

```bash
kerno archive --before-days 7 --delete
```

### 6. Seguridad en producción

- La API sale a internet solo detrás de HTTPS (Railway/Render lo dan por defecto; en un VPS usa Caddy o nginx con Let's Encrypt).
- Crea una API key por cliente (`kerno keys create fondo-x --rate 300`) y revócala con `kerno keys revoke <id>`.
- Configura `KERNO_CORS_ORIGINS` solo si un frontend en otro dominio llama a la API.
- Pon `KERNO_EXPOSE_DOCS=0` si no quieres publicar el esquema OpenAPI.
- Activa en Supabase las copias de seguridad diarias (incluidas en Pro) y, en planes superiores, PITR.
- Nunca subas `.env` a git: el `.gitignore` ya lo excluye.
