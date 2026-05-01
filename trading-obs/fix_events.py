content = open('api.py', encoding='utf-8').read()

old = '    conn.close()\n    return [dict(r) for r in rows]'
new = '    conn.close()\n    enriched = []\n    prev_price = None\n    for r in rows:\n        d = dict(r)\n        if prev_price and prev_price > 0:\n            change_pct = (d["price"] - prev_price) / prev_price * 100\n            d["spike_pct"] = round(change_pct, 6)\n            d["intelligence"] = _classify(d["symbol"], change_pct)\n        else:\n            d["spike_pct"] = 0.0\n            d["intelligence"] = {"signal": "NO_DATA"}\n        prev_price = d["price"]\n        enriched.append(d)\n    return enriched'

if old in content:
    content = content.replace(old, new, 1)
    open('api.py', 'w', encoding='utf-8').write(content)
    print('OK: /events parcheado')
else:
    print('ERROR: texto no encontrado')
