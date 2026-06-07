c = open("validator.py", encoding="utf-8").read()

old = """        # Threshold por bucket: MEDIUM=0.01%, LARGE=0.02%, EXTREME=0.03%
        THRESH = {"SMALL": 0.005, "MEDIUM": 0.010, "LARGE": 0.020, "EXTREME": 0.030}
        bucket = row["bucket"] if row["bucket"] else "MEDIUM"
        thr = THRESH.get(bucket, 0.010)"""

new = """        # Threshold adaptativo: max(floor, alpha*vol, beta*spread)
        bucket = row["bucket"] if row["bucket"] else "MEDIUM"
        # Obtener volatilidad local de las ultimas señales
        vol_row = conn.execute(\"\"\"
            SELECT AVG(ABS(price_entry - price_10s) / price_entry * 100)
            FROM signal_outcomes
            WHERE symbol=? AND price_10s IS NOT NULL
            AND event_time_ms >= ? - 300000
        \"\"\", (row["symbol"], row["event_time_ms"])).fetchone()
        local_vol = vol_row[0] if vol_row and vol_row[0] else 0.005
        floor = {"SMALL": 0.002, "MEDIUM": 0.004, "LARGE": 0.008, "EXTREME": 0.015}.get(bucket, 0.004)
        thr = max(floor, local_vol * 0.5)"""

if old in c:
    c = c.replace(old, new, 1)
    open("validator.py", "w", encoding="utf-8").write(c)
    print("OK: threshold adaptativo implementado")
else:
    print("NOT FOUND")
    idx = c.find("THRESH")
    print(repr(c[idx-50:idx+200]))