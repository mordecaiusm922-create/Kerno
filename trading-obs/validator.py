import sqlite3, time, os

DB_PATH = os.getenv("DB_PATH", "kerno.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def record_signal(symbol, signal, bucket, confidence, price_entry, event_time_ms):
    conn = get_conn()
    conn.execute("""
        INSERT INTO signal_outcomes
        (symbol, signal, bucket, confidence, price_entry, event_time_ms)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (symbol, signal, bucket, confidence, price_entry, event_time_ms))
    conn.commit()
    conn.close()

def validate_pending():
    conn = get_conn()
    pending = conn.execute("""
        SELECT id, symbol, signal, bucket, price_entry, event_time_ms
        FROM signal_outcomes
        WHERE result_10s = 'PENDING'
        AND event_time_ms < (strftime('%s','now') * 1000 - 10000)
    """).fetchall()
    for row in pending:
        # Get price ~10s after signal
        price_10s = conn.execute("""
            SELECT price FROM market_events
            WHERE symbol=? AND event_time_ms >= ? + 8000
            ORDER BY event_time_ms ASC LIMIT 1
        """, (row["symbol"], row["event_time_ms"])).fetchone()
        price_30s = conn.execute("""
            SELECT price FROM market_events
            WHERE symbol=? AND event_time_ms >= ? + 28000
            ORDER BY event_time_ms ASC LIMIT 1
        """, (row["symbol"], row["event_time_ms"])).fetchone()
        # Threshold adaptativo: max(floor, alpha*vol, beta*spread)
        bucket = row["bucket"] if row["bucket"] else "MEDIUM"
        # Obtener volatilidad local de las ultimas señales
        vol_row = conn.execute("""
            SELECT AVG(ABS(price_entry - price_10s) / price_entry * 100)
            FROM signal_outcomes
            WHERE symbol=? AND price_10s IS NOT NULL
            AND event_time_ms >= ? - 300000
        """, (row["symbol"], row["event_time_ms"])).fetchone()
        local_vol = vol_row[0] if vol_row and vol_row[0] else 0.005
        floor = {"SMALL": 0.002, "MEDIUM": 0.004, "LARGE": 0.008, "EXTREME": 0.015}.get(bucket, 0.004)
        thr = max(floor, local_vol * 0.5)
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
            result_30s = "PENDING"
        conn.execute("""
            UPDATE signal_outcomes
            SET result_10s=?, result_30s=?, price_10s=?, price_30s=?
            WHERE id=?
        """, (result_10s, result_30s,
              price_10s[0] if price_10s else None,
              price_30s[0] if price_30s else None,
              row["id"]))
    conn.commit()
    conn.close()

def validator_loop():
    while True:
        try:
            validate_pending()
        except Exception as e:
            print(f"[validator] error: {e}")
        time.sleep(5)

if __name__ == "__main__":
    print("[validator] iniciando loop...")
    validator_loop()
