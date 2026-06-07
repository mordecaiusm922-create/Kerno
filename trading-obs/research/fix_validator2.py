c = open("validator.py", encoding="utf-8").read()

old = """        SELECT id, symbol, signal, price_entry, event_time_ms
        FROM signal_outcomes
        WHERE result_10s = 'PENDING'
        AND event_time_ms < (strftime('%s','now') * 1000 - 10000)"""

new = """        SELECT id, symbol, signal, bucket, price_entry, event_time_ms
        FROM signal_outcomes
        WHERE result_10s = 'PENDING'
        AND event_time_ms < (strftime('%s','now') * 1000 - 10000)"""

if old in c:
    c = c.replace(old, new, 1)
    open("validator.py", "w", encoding="utf-8").write(c)
    print("OK: bucket agregado al SELECT")
else:
    print("NOT FOUND")