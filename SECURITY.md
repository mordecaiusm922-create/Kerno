# Security policy

## Reporting

Report vulnerabilities privately to the repository owner (GitHub → Security →
"Report a vulnerability"). Do not open public issues for security problems.

## Design summary

- API: per-client keys (SHA-256 stored, never plaintext), revocation, per-key rate limits, audit log of every request, strict CSP and security headers, read-only endpoints.
- Database: Supabase `anon`/`authenticated` roles are revoked on every table and RLS is enabled. Credentials only come from the environment.
- Models: JSON only, hash-verified against `trading-obs/models/manifest.json`. Pickle is never loaded.
- Supply chain: hash-pinned dependencies, `pip-audit` in CI, Dependabot.
- Data: raw trades are archived to verified Parquet before any deletion.

See `trading-obs/docs/audit.md` for the full audit and open items.
