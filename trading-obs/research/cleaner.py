import sqlite3, time, os

DB_PATH = "kerno.db"

while True:
    time.sleep(300)
    try:
        conn = sqlite3.connect(DB_PATH)
        cutoff = int((time.time() - 2*3600) * 1000)
        deleted = conn.execute("DELETE FROM market_events WHERE event_time_ms < ?", (cutoff,)).rowcount
        conn.commit()
        size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
        if deleted > 0:
            print(f"Limpieza: {deleted} eventos | DB: {size_mb:.1f} MB")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
