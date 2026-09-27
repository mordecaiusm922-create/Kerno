import sqlite3
conn = sqlite3.connect('kerno.db')

print("=== SIGNAL OUTCOMES ===")
total = conn.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0]
pending = conn.execute("SELECT COUNT(*) FROM signal_outcomes WHERE result_10s='PENDING'").fetchone()[0]
wins = conn.execute("SELECT COUNT(*) FROM signal_outcomes WHERE result_10s='WIN'").fetchone()[0]
losses = conn.execute("SELECT COUNT(*) FROM signal_outcomes WHERE result_10s='LOSS'").fetchone()[0]
print(f"Total: {total} | Pending: {pending} | WIN: {wins} | LOSS: {losses}")

print("\n=== POR BUCKET ===")
rows = conn.execute("""
    SELECT bucket, signal, COUNT(*) as n,
           SUM(CASE WHEN result_10s='WIN' THEN 1 ELSE 0 END) as wins,
           ROUND(AVG(confidence),3) as avg_conf
    FROM signal_outcomes WHERE result_10s != 'PENDING'
    GROUP BY bucket, signal ORDER BY n DESC
""").fetchall()
for r in rows:
    wr = round(r[3]/r[2]*100,1) if r[2] else 0
    print(f"  {r[1]:<12} {r[0]:<10} n={r[2]:<5} win={wr}%  conf={r[4]}")

print("\n=== MARKET EVENTS ===")
print("Total eventos:", conn.execute("SELECT COUNT(*) FROM market_events").fetchone()[0])
conn.close()
