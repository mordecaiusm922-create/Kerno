"""
API keys, rate limiting and audit logging.

- Keys look like `kerno_<43 random chars>`. Only their SHA-256 is stored; the
  plaintext is shown once at creation (`kerno keys create <name>`).
- Each key has its own per-minute rate limit (token bucket, per process).
- Every authenticated request is written to `api_audit_log`.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass

from kerno.db import Database

KEY_PREFIX = "kerno_"
CACHE_TTL_S = 30.0


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def create_key(db: Database, name: str, rate_limit_per_min: int | None = None) -> str:
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    with db.connect() as c:
        c.execute(
            "INSERT INTO api_keys (name, key_prefix, key_hash, rate_limit_per_min, created_at_ms) VALUES (?, ?, ?, ?, ?)",
            (name, key[:12], hash_key(key), rate_limit_per_min, int(time.time() * 1000)),
        )
    return key


def list_keys(db: Database) -> list[dict]:
    with db.connect() as c:
        return c.fetchall(
            "SELECT id, name, key_prefix, rate_limit_per_min, created_at_ms, revoked_at_ms FROM api_keys ORDER BY id"
        )


def revoke_key(db: Database, key_id: int) -> bool:
    with db.connect() as c:
        return c.execute(
            "UPDATE api_keys SET revoked_at_ms = ? WHERE id = ? AND revoked_at_ms IS NULL",
            (int(time.time() * 1000), key_id),
        ) > 0


@dataclass(frozen=True)
class Principal:
    key_id: int
    name: str
    rate_limit_per_min: int


class KeyStore:
    """Hash -> principal lookup with a short cache (revocations apply within CACHE_TTL_S)."""

    def __init__(self, db: Database, default_rate: int):
        self.db = db
        self.default_rate = default_rate
        self._cache: dict[str, tuple[float, Principal | None]] = {}
        self._lock = threading.Lock()

    def lookup(self, key: str) -> Principal | None:
        if not key.startswith(KEY_PREFIX) or len(key) > 128:
            return None
        h = hash_key(key)
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(h)
            if hit and now - hit[0] < CACHE_TTL_S:
                return hit[1]
        with self.db.connect() as c:
            row = c.fetchone(
                "SELECT id, name, rate_limit_per_min FROM api_keys WHERE key_hash = ? AND revoked_at_ms IS NULL", (h,)
            )
        principal = (
            Principal(int(row["id"]), row["name"], int(row["rate_limit_per_min"] or self.default_rate)) if row else None
        )
        with self._lock:
            if len(self._cache) > 10_000:
                self._cache.clear()
            self._cache[h] = (now, principal)
        return principal


class RateLimiter:
    """Token bucket per key: capacity = limit, refills limit tokens per minute."""

    def __init__(self) -> None:
        self._buckets: dict[int, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key_id: int, limit_per_min: int) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key_id, (float(limit_per_min), now))
            tokens = min(float(limit_per_min), tokens + (now - last) * limit_per_min / 60.0)
            if tokens < 1.0:
                self._buckets[key_id] = (tokens, now)
                return False
            self._buckets[key_id] = (tokens - 1.0, now)
            return True


def write_audit(db: Database, key_id: int | None, method: str, path: str, query: str, status: int,
                duration_ms: int, client_ip: str | None) -> None:
    with db.connect() as c:
        c.execute(
            "INSERT INTO api_audit_log (ts_ms, key_id, method, path, query, status, duration_ms, client_ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (int(time.time() * 1000), key_id, method, path[:512], query[:1024], status, duration_ms, client_ip),
        )
