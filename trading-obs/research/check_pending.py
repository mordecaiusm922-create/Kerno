import sqlite3, time
conn = sqlite3.connect("kerno.db")
conn.row_factory = sqlite3.Row
now_ms = int(time.time()*1000)
pending = conn.execute("""
    SELECT id, event_time_ms, result_10s 
    FROM signal_outcomes 
    WHERE result_10s = 'PENDING'
    AND event_time_ms < ?
    LIMIT 5
""", (now_ms - 10000,)).fetchall()
print("Pending count:", len(pending))
for r in pending:
    print(dict(r))
conn.close()