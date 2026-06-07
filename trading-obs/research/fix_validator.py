content = open('validator.py', encoding='utf-8').read()

old = '''        if price_10s:
            p0 = row["price_entry"]
            p1 = price_10s[0]
            move_pct = (p1 - p0) / p0 * 100 if p0 else 0
            if row["signal"] == "REV_EDGE":
                result_10s = "WIN" if move_pct < -0.01 else "LOSS"
            elif row["signal"] == "CONT_EDGE":
                result_10s = "WIN" if move_pct > 0.01 else "LOSS"
            else:
                result_10s = "NEUTRAL"
        else:
            result_10s = "PENDING"
        if price_30s:
            p0 = row["price_entry"]
            p3 = price_30s[0]
            move_pct = (p3 - p0) / p0 * 100 if p0 else 0
            if row["signal"] == "REV_EDGE":
                result_30s = "WIN" if move_pct < -0.01 else "LOSS"
            elif row["signal"] == "CONT_EDGE":
                result_30s = "WIN" if move_pct > 0.01 else "LOSS"
            else:
                result_30s = "NEUTRAL"
        else:
            result_30s = "PENDING"'''

new = '''        # Threshold por bucket: MEDIUM=0.01%, LARGE=0.02%, EXTREME=0.03%
        THRESH = {"SMALL": 0.005, "MEDIUM": 0.010, "LARGE": 0.020, "EXTREME": 0.030}
        bucket = row["bucket"] if row["bucket"] else "MEDIUM"
        thr = THRESH.get(bucket, 0.010)
        if price_10s:
            p0 = row["price_entry"]
            p1 = price_10s[0]
            move_pct = (p1 - p0) / p0 * 100 if p0 else 0
            if row["signal"] == "REV_EDGE":
                result_10s = "WIN" if move_pct < -thr else ("NEUTRAL" if abs(move_pct) < thr*0.5 else "LOSS")
            elif row["signal"] == "CONT_EDGE":
                result_10s = "WIN" if move_pct > thr else ("NEUTRAL" if abs(move_pct) < thr*0.5 else "LOSS")
            else:
                result_10s = "NEUTRAL"
        else:
            result_10s = "PENDING"
        if price_30s:
            p0 = row["price_entry"]
            p3 = price_30s[0]
            move_pct = (p3 - p0) / p0 * 100 if p0 else 0
            if row["signal"] == "REV_EDGE":
                result_30s = "WIN" if move_pct < -thr else ("NEUTRAL" if abs(move_pct) < thr*0.5 else "LOSS")
            elif row["signal"] == "CONT_EDGE":
                result_30s = "WIN" if move_pct > thr else ("NEUTRAL" if abs(move_pct) < thr*0.5 else "LOSS")
            else:
                result_30s = "NEUTRAL"
        else:
            result_30s = "PENDING"'''

if old in content:
    content = content.replace(old, new, 1)
    open('validator.py', 'w', encoding='utf-8').write(content)
    print('OK: validator calibrado por bucket')
else:
    print('ERROR: texto no encontrado')
