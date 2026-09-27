import sys
sys.path.insert(0, ".")
import backtester as bt

events = bt.load_events("BTCUSDT", 50000)
prices = [e["price"] for e in events]
diffs  = [abs(prices[i]-prices[i-1]) for i in range(1, len(prices))]
pcts   = [d/prices[i]*100 for i,d in enumerate(diffs)]

pcts.sort(reverse=True)
print("Top 20 movimientos reales en tus datos:")
for i, p in enumerate(pcts[:20]):
    print(f"  {i+1:2d}. {p:.4f}%  (${p/100*77000:.2f})")

import statistics
print("")
print("Media  :", round(statistics.mean(pcts), 6), "%")
print("Stdev  :", round(statistics.stdev(pcts), 6), "%")
print("Median :", round(statistics.median(pcts), 6), "%")
print("P99    :", round(sorted(pcts)[int(len(pcts)*0.99)], 6), "%")
print("P99.9  :", round(sorted(pcts)[int(len(pcts)*0.999)], 6), "%")
