content = open('README.md', encoding='utf-8').read()

content = content.replace(
    '## Architecture\n\n---',
    '## Architecture\n\n```\nBinance WebSocket (trade stream)\n        ↓\nEvent Ingestion — ingestor.py\n        ↓\nSQLite storage — kerno.db (2M+ events)\n        ↓\nSpike Detection — percentile bucketing (p75 / p90 / p99)\n        ↓\nEdge Map — asset-specific reversal/continuation probabilities\n        ↓\nConfidence Layer — base score + streak bonus\n        ↓\nSignal Recording — /events endpoint\n        ↓\nValidator — background thread, resolves outcomes at 10s and 30s\n        ↓\nREST API — FastAPI (/events /signals /accuracy /metrics)\n        ↓\nPrecision Dashboard — real-time feed with confidence filter\n```\n\n---'
, 1)

content = content.replace(
    'Each signal carries a confidence score computed as:The Precision',
    'Each signal carries a confidence score computed as:\n\n```\nbase_confidence = f(bucket)      # SMALL=0.35, MEDIUM=0.62, LARGE=0.80, EXTREME=0.92\nstreak_bonus    = consecutive_same_signal * 0.04  (capped at 0.15)\nconfidence      = clip(base + streak_bonus, 0, 1)\n```\n\nThe Precision'
, 1)

open('README.md', 'w', encoding='utf-8').write(content)

arch_ok = 'Binance WebSocket' in content
conf_ok = 'base_confidence' in content
print('Architecture OK:', arch_ok)
print('Confidence OK:', conf_ok)
if arch_ok and conf_ok:
    print('LISTO PARA SUBIR')
