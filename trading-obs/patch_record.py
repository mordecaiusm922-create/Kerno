content = open('api.py', encoding='utf-8').read()

old = '''        prev_price = d["price"]
        enriched.append(d)
    return enriched'''

new = '''        prev_price = d["price"]
        # Registrar señales con confidence > 0.50 para validacion
        intel = d.get("intelligence", {})
        if intel.get("confidence", 0) >= 0.50 and intel.get("signal") not in ("NO_DATA", "NO_EDGE"):
            try:
                conn2 = get_conn()
                conn2.execute("""
                    INSERT INTO signal_outcomes
                    (symbol, signal, bucket, confidence, price_entry, event_time_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (d["symbol"], intel["signal"], intel.get("bucket",""),
                      intel["confidence"], d["price"], d["event_time_ms"]))
                conn2.commit()
                conn2.close()
            except Exception:
                pass
        enriched.append(d)
    return enriched'''

if old in content:
    content = content.replace(old, new, 1)
    open('api.py', 'w', encoding='utf-8').write(content)
    print('OK: signal recording activo')
else:
    print('ERROR: texto no encontrado')
