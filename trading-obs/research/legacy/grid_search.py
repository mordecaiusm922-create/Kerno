import subprocess
import itertools

holds = [5, 10, 20, 60]
zs    = [1.5, 2.0, 2.5, 3.0]
results = []

print("hold   z     WR%    PnL%      DD%")
print("-" * 42)

for h, z in itertools.product(holds, zs):
    r = subprocess.run(
        ["python", "backtester.py", "--symbol", "BTCUSDT",
         "--hold", str(h), "--z", str(z), "--no-save"],
        capture_output=True, text=True
    )
    pnl, wr, dd = None, None, None
    for line in r.stdout.splitlines():
        if "Win rate" in line:
            wr = float(line.split(":")[1].strip().replace("%",""))
        if "Total PnL" in line:
            pnl = float(line.split(":")[1].strip().replace("%",""))
        if "Max drawdown" in line:
            dd = float(line.split(":")[1].strip().replace("%","").replace("-",""))
    results.append({"hold":h,"z":z,"wr":wr,"pnl":pnl,"dd":dd})
    print(f"  {h:3d}s  {z:.1f}  {str(wr)+'%':7s}  {pnl:+.4f}%  {dd:.4f}%")

print("-" * 42)
valid = [x for x in results if x["pnl"] is not None]
if valid:
    best = max(valid, key=lambda x: x["pnl"])
    print(f"MEJOR: hold={best['hold']}s z={best['z']} WR={best['wr']}% PnL={best['pnl']:+.4f}%")
