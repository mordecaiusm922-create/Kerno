#!/usr/bin/env bash
# setup.sh — inicializa el entorno completo de trading-obs
# Uso: bash setup.sh

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Trading Observability — Setup v0.1"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── 1. Verificar dependencias ──────────────────────────────────────────────
log "Verificando dependencias..."

command -v python3 >/dev/null 2>&1 || err "Python 3 no encontrado. Instálalo primero."
command -v docker  >/dev/null 2>&1 || err "Docker no encontrado. Instálalo primero."
command -v node    >/dev/null 2>&1 || warn "Node.js no encontrado — necesario para el frontend."

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
log "Python $PYTHON_VERSION detectado"

# ── 2. Estructura de carpetas ──────────────────────────────────────────────
log "Creando estructura de proyecto..."

mkdir -p trading-obs/{db,frontend/src/components,frontend/public,scripts}

# ── 3. Entorno virtual Python ──────────────────────────────────────────────
log "Creando entorno virtual Python..."

if [ ! -d "trading-obs/.venv" ]; then
    python3 -m venv trading-obs/.venv
    log "Entorno virtual creado en trading-obs/.venv"
else
    warn "Entorno virtual ya existe — skipping"
fi

# ── 4. Instalar dependencias Python ───────────────────────────────────────
log "Instalando dependencias Python..."

trading-obs/.venv/bin/pip install --quiet --upgrade pip
trading-obs/.venv/bin/pip install --quiet \
    asyncpg==0.29.0 \
    websockets==12.0 \
    fastapi==0.111.0 \
    "uvicorn[standard]==0.30.1" \
    pydantic==2.7.1 \
    python-dotenv==1.0.1

log "Dependencias Python instaladas"

# ── 5. Archivo .env ────────────────────────────────────────────────────────
if [ ! -f "trading-obs/.env" ]; then
    cat > trading-obs/.env << 'EOF'
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trading_obs
API_PORT=8000
LOG_LEVEL=INFO
EOF
    log ".env creado"
else
    warn ".env ya existe — skipping"
fi

# ── 6. Levantar PostgreSQL ─────────────────────────────────────────────────
log "Levantando PostgreSQL con Docker..."

cd trading-obs

if docker compose ps postgres 2>/dev/null | grep -q "running"; then
    warn "PostgreSQL ya está corriendo — skipping"
else
    docker compose up -d postgres
    log "Esperando que PostgreSQL esté listo..."
    until docker compose exec -T postgres pg_isready -U postgres >/dev/null 2>&1; do
        sleep 1
        echo -n "."
    done
    echo ""
    log "PostgreSQL listo"
fi

cd ..

# ── 7. Resumen final ───────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup completo ✓"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Próximos comandos:"
echo ""
echo "  # Terminal 1 — Ingestor"
echo "  cd trading-obs"
echo "  source .venv/bin/activate"
echo "  python ingestor.py --symbols BTCUSDT ETHUSDT"
echo ""
echo "  # Terminal 2 — API"
echo "  cd trading-obs"
echo "  source .venv/bin/activate"
echo "  uvicorn api:app --reload --port 8000"
echo ""
echo "  # Docs API: http://localhost:8000/docs"
echo "  # pgAdmin:  http://localhost:5050"
echo "              admin@trading.local / admin"
echo ""
