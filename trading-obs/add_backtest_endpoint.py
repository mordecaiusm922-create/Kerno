"""
add_backtest_endpoint.py — agrega GET /backtest a api.py
Ejecutar desde la carpeta trading-obs
"""
import os

ENDPOINT = '''

# ── Backtest endpoint ─────────────────────────────────────────────────────────
import sys as _sys
import importlib.util as _ilu

def _load_backtester():
    p = os.path.join(os.path.dirname(__file__), "backtester.py")
    spec = _ilu.spec_from_file_location("backtester", p)
    mod  = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class BacktestResult(BaseModel):
    symbol:            str
    events_loaded:     int
    spikes_detected:   int
    trades_executed:   int
    win_rate_pct:      float | None
    total_pnl_pct:     float | None
    avg_pnl_pct:       float | None
    best_trade_pct:    float | None
    worst_trade_pct:   float | None
    max_drawdown_pct:  float | None
    profit_factor:     float | None
    avg_hold_sec:      float | None
    avg_entry_latency_ms: float | None
    verdict:           str

@app.get("/backtest", response_model=BacktestResult)
def run_backtest_endpoint(
    symbol:    Annotated[str,   Query()] = "BTCUSDT",
    hold:      Annotated[int,   Query(ge=5, le=300)] = 30,
    z:         Annotated[float, Query(ge=1.0, le=5.0)] = 2.0,
    min_spike: Annotated[float, Query(ge=0.001, le=1.0)] = 0.01,
    limit:     Annotated[int,   Query(ge=100, le=50000)] = 10000,
    save:      Annotated[bool,  Query()] = True,
):
    """
    Corre backtest sobre datos historicos en kerno.db.
    Estrategia: spike-follow — entra en direccion del spike, sale despues de hold segundos.
    """
    bt = _load_backtester()
    events = bt.load_events(symbol, limit)
    if len(events) < 20:
        raise HTTPException(400, f"Pocos datos: {len(events)} eventos. Deja el ingestor correr mas tiempo.")

    spikes = bt.detect_spikes(events, z_threshold=z, min_pct=min_spike)
    trades = bt.run_backtest(events, spikes, hold_seconds=hold)
    stats  = bt.compute_stats(trades)

    params = {"symbol": symbol, "events_loaded": len(events),
              "spikes_detected": len(spikes), "hold_seconds": hold,
              "z_threshold": z, "min_spike_pct": min_spike}

    if save and stats:
        bt.save_results(symbol, params, stats, trades)

    if not stats:
        return BacktestResult(
            symbol=symbol, events_loaded=len(events),
            spikes_detected=len(spikes), trades_executed=0,
            win_rate_pct=None, total_pnl_pct=None, avg_pnl_pct=None,
            best_trade_pct=None, worst_trade_pct=None, max_drawdown_pct=None,
            profit_factor=None, avg_hold_sec=None, avg_entry_latency_ms=None,
            verdict="Sin trades — aumenta el tiempo de captura o reduce z-threshold"
        )

    wr  = stats["win_rate_pct"]
    pnl = stats["total_pnl_pct"]
    if wr >= 55 and pnl > 0:
        verdict = "EDGE DETECTADO — estrategia tiene valor estadistico"
    elif pnl > 0:
        verdict = "PnL positivo — ajustar parametros para mejorar win rate"
    elif wr >= 50:
        verdict = "Win rate ok pero fees matan PnL — reducir hold time"
    else:
        verdict = "Sin edge — spike-follow no funciona en este periodo"

    return BacktestResult(
        symbol=symbol,
        events_loaded=len(events),
        spikes_detected=len(spikes),
        trades_executed=stats["total_trades"],
        win_rate_pct=stats["win_rate_pct"],
        total_pnl_pct=stats["total_pnl_pct"],
        avg_pnl_pct=stats["avg_pnl_pct"],
        best_trade_pct=stats["best_trade_pct"],
        worst_trade_pct=stats["worst_trade_pct"],
        max_drawdown_pct=stats["max_drawdown_pct"],
        profit_factor=stats["profit_factor"],
        avg_hold_sec=stats["avg_hold_sec"],
        avg_entry_latency_ms=stats["avg_entry_latency_ms"],
        verdict=verdict,
    )
'''

target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api.py")
content = open(target, encoding="utf-8").read()

if "/backtest" in content:
    print("Endpoint /backtest ya existe en api.py")
else:
    with open(target, "a", encoding="utf-8") as f:
        f.write(ENDPOINT)
    print("OK: /backtest agregado a api.py")

print("Reinicia uvicorn y prueba: http://localhost:8000/backtest?symbol=BTCUSDT")
