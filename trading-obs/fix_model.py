content = open('api.py', encoding='utf-8').read()

old = '    trade_id:       int | None'
new = '    trade_id:       int | None\n    spike_pct:      float | None = None\n    intelligence:   dict | None = None'

if old in content:
    content = content.replace(old, new, 1)
    open('api.py', 'w', encoding='utf-8').write(content)
    print('OK: TradeEvent actualizado')
else:
    print('ERROR: texto no encontrado')
