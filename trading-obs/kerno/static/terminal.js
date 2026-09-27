"use strict";
// All data is rendered with textContent - never innerHTML - so nothing coming
// from the API can inject markup or script.
(function () {
  const $ = (id) => document.getElementById(id);
  const store = {
    get: () => { try { return sessionStorage.getItem("kerno_key") || ""; } catch (e) { return ""; } },
    set: (v) => { try { sessionStorage.setItem("kerno_key", v); } catch (e) { /* ignore */ } },
  };
  let timer = null;

  function fmt(v, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return typeof v === "number" ? v.toFixed(digits) : String(v);
  }
  function cell(text, cls) {
    const td = document.createElement("td");
    td.textContent = text;
    if (cls) td.className = cls;
    return td;
  }
  function signCls(v) { return v === null || v === undefined ? "muted" : v > 0 ? "pos" : v < 0 ? "neg" : ""; }
  function fill(tableId, rows) {
    const body = $(tableId).querySelector("tbody");
    body.replaceChildren(...rows.map((cells) => {
      const tr = document.createElement("tr");
      tr.append(...cells);
      return tr;
    }));
  }
  function setStatus(text, cls) { const s = $("status"); s.textContent = text; s.className = "status " + (cls || ""); }

  async function get(path, params) {
    const url = new URL(path, window.location.origin);
    Object.entries(params || {}).forEach(([k, v]) => url.searchParams.set(k, v));
    const res = await fetch(url, { headers: { "X-API-Key": store.get() }, cache: "no-store" });
    if (!res.ok) throw new Error(res.status + " " + res.statusText);
    return res.json();
  }

  async function refresh() {
    const [exchange, symbol] = $("stream").value.split("|");
    try {
      const [signals, p10, p30, basis] = await Promise.all([
        get("/v1/signals", { exchange, symbol, limit: 40 }),
        get("/v1/performance", { exchange, symbol, horizon: 10 }),
        get("/v1/performance", { exchange, symbol, horizon: 30 }),
        get("/v1/basis", { limit: 20 }),
      ]);
      fill("signals", signals.map((s) => [
        cell(new Date(s.event_time_ms).toLocaleTimeString([], { hour12: false })),
        cell(fmt(s.price, 2)),
        cell(fmt(s.spike_bps, 2), signCls(s.spike_bps)),
        cell(s.bucket),
        cell(s.signal, s.signal === "CONTINUATION" || s.signal === "ABSORPTION" ? "" : "muted"),
        cell(fmt(s.p_tradeable, 3)),
        cell(fmt(s.p_continuation, 3)),
        cell(s.status, "muted"),
        cell(fmt(s.pnl_10s_bps, 2), signCls(s.pnl_10s_bps)),
        cell(fmt(s.pnl_30s_bps, 2), signCls(s.pnl_30s_bps)),
      ]));
      const perfRows = [];
      [p10, p30].forEach((p) => Object.entries(p.stats).forEach(([group, st]) => {
        perfRows.push([
          cell(group), cell(p.horizon_s + "s"), cell(String(st.n)),
          cell(st.n ? (st.hit_rate * 100).toFixed(1) + "%" : "—"),
          cell(fmt(st.mean_net_bps, 2), signCls(st.mean_net_bps)),
          cell(fmt(st.mean_gross_bps, 2), signCls(st.mean_gross_bps)),
          cell(fmt(st.t_stat, 2)),
        ]);
      }));
      fill("perf", perfRows);
      fill("basis", basis.map((b) => [
        cell(new Date(b.ts_ms).toLocaleTimeString([], { hour12: false })),
        cell(fmt(b.spot_price, 2)), cell(fmt(b.perp_price, 2)),
        cell(fmt(b.basis_pct, 4), signCls(b.basis_pct)),
      ]));
      setStatus("live", "ok");
    } catch (e) {
      setStatus(String(e.message || e), "err");
    }
  }

  $("apikey").value = store.get();
  $("controls").addEventListener("submit", (ev) => {
    ev.preventDefault();
    store.set($("apikey").value.trim());
    if (timer) clearInterval(timer);
    refresh();
    timer = setInterval(refresh, 5000);
  });
  $("stream").addEventListener("change", refresh);
  if (store.get()) { refresh(); timer = setInterval(refresh, 5000); }
})();
