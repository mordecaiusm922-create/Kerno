"""
Runtime configuration, read from environment variables (and `.env` if
python-dotenv is installed). Nothing secret is ever hard-coded here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional convenience for local development
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_MODELS_DIR = PACKAGE_DIR.parent / "models"

# exchange -> native symbols subscribed by `kerno ingest` when --stream is not given
DEFAULT_STREAMS = "binance:BTCUSDT,ETHUSDT;bybit:BTCUSDT;okx:BTC-USDT"


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    v = os.getenv(name)
    return default if v in (None, "") else float(v)


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    return default if v in (None, "") else int(v)


def parse_streams(spec: str) -> dict[str, list[str]]:
    """'binance:BTCUSDT,ETHUSDT;okx:BTC-USDT' -> {'binance': [...], 'okx': [...]}"""
    out: dict[str, list[str]] = {}
    for part in filter(None, (p.strip() for p in spec.split(";"))):
        exchange, _, symbols = part.partition(":")
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if not exchange or not syms:
            raise ValueError(f"bad stream spec {part!r}, expected exchange:SYM1,SYM2")
        out.setdefault(exchange.strip().lower(), []).extend(syms)
    return out


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///kerno.db"))
    streams: dict[str, list[str]] = field(
        default_factory=lambda: parse_streams(os.getenv("KERNO_STREAMS", DEFAULT_STREAMS))
    )
    store_raw: bool = field(default_factory=lambda: _bool("KERNO_STORE_RAW", False))

    # evaluation: round-trip trading cost charged to every signal (fees + spread), in bps
    cost_bps: float = field(default_factory=lambda: _float("KERNO_COST_BPS", 10.0))
    # realistic entry: first trade at least this long after the signal trade
    entry_delay_ms: int = field(default_factory=lambda: _int("KERNO_ENTRY_DELAY_MS", 250))

    models_dir: Path = field(default_factory=lambda: Path(os.getenv("KERNO_MODELS_DIR", str(DEFAULT_MODELS_DIR))))

    # API
    auth_disabled: bool = field(default_factory=lambda: _bool("KERNO_AUTH_DISABLED", False))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("KERNO_CORS_ORIGINS", "").split(",") if o.strip()]
    )
    default_rate_limit_per_min: int = field(default_factory=lambda: _int("KERNO_RATE_LIMIT_PER_MIN", 120))
    expose_docs: bool = field(default_factory=lambda: _bool("KERNO_EXPOSE_DOCS", True))

    # archive (Parquet). If S3 settings are present, files are also uploaded
    # (works with Supabase Storage's S3 endpoint, Cloudflare R2, AWS S3).
    archive_dir: Path = field(default_factory=lambda: Path(os.getenv("KERNO_ARCHIVE_DIR", "archive")))
    s3_bucket: str = field(default_factory=lambda: os.getenv("KERNO_S3_BUCKET", ""))
    s3_endpoint_url: str = field(default_factory=lambda: os.getenv("KERNO_S3_ENDPOINT_URL", ""))
    s3_region: str = field(default_factory=lambda: os.getenv("KERNO_S3_REGION", ""))

    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


def get_settings() -> Settings:
    return Settings()
