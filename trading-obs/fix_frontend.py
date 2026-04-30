"""
fix_frontend.py — reemplaza frontend/index.html con version Chart.js (sin CDN roto)
Ejecutar desde: C:\Users\usuario\Downloads\trading-obs\trading-obs
"""
import os

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kerno — Market Observatory</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:#080c10;--surface:#0d1218;--border:#1a2230;
    --accent:#00e5ff;--green:#7fff6e;--red:#ff4d6d;
    --text:#e2eaf4;--muted:#4a5a70;
    --mono:'Space Mono',monospace;--display:'Syne',sans-serif;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:var(--mono);font-size:13px;min-height:100vh;overflow:hidden}
  body::before{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(0,229,255,.015) 1px,transparent 1px),linear-gradient(90deg,rgba(0,229,255,.015) 1px,transparent 1px);background-size:40px 40px;pointer-events:none;z-index:0}
  header{position:relative;z-index:10;display:flex;align-items:center;justify-content:space-between;padding:14px 28px;border-bottom:1px solid var(--border);background:rgba(8,12,16,.95)}
  .logo{font-family:var(--display);font-weight:800;font-size:20px;color:var(--accent);display:flex;align-items:center;gap:10px}
  .logo-dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.3;transform:scale(.5)}}
  .header-right{display:flex;align-items:center;gap:20px}
  .symbol-tabs{display:flex;gap:3px;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:3px}
  .tab{padding:5px 14px;border-radius:4px;cursor:pointer;font-family:var(--mono);font-size:12px;color:var(--muted);background:none;border:none;transition:all .2s}
  .tab.active{background:var(--accent);color:var(--bg);font-weight:700}
  .live-badge{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--green)}
  .live-dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 1.5s infinite}
  .metrics-bar{position:relative;z-index:10;display:grid;grid-template-columns:repeat(6,1fr);border-bottom:1px solid var(--border);background:var(--surface)}
  .metric-cell{padding:12px 18px;border-right:1px solid var(--border)}
  .metric-cell:last-child{border-right:none}
  .metric-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px}
  .metric-value{font-family:var(--display);font-size:18px;font-weight:600;color:var(--text);transition:color .3s}
  .metric-value.up{color:var(--green)}.metric-value.down{color:var(--red)}
  .metric-sub{font-size:10px;color:var(--muted);margin-top:2px}
  .main{position:relative;z-index:10;display:grid;grid-template-columns:1fr 300px;height:calc(100vh - 114px)}
  .chart-panel{display:flex;flex-direction:column;border-right:1px solid var(--border)}
  .panel-header{display:flex;align-items:center;justify-content:space-between;padding:10px 18px;border-bottom:1px solid var(--border);background:rgba(13,18,24,.9)}
  .panel-title{font-family:var(--display);font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px}
  .panel-title span{font-size:10px;color:var(--muted);font-family:var(--mono);font-weight:400}
  .controls{display:flex;gap:6px}
  .btn{padding:4px 10px;border-radius:4px;border:1px solid var(--border);background:var(--surface);color:var(--muted);font-family:var(--mono);font-size:11px;cursor:pointer;transition:all .2s}
  .btn:hover,.btn.active{border-color:var(--accent);color:var(--accent)}
  .chart-wrap{flex:1;position:relative;padding:12px;min-height:0}
  .latency-strip{height:72px;border-top:1px solid var(--border);padding:8px 18px;background:var(--surface)}
  .strip-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:5px}
  #latency-bars{display:flex;align-items:flex-end;gap:2px;height:36px;overflow:hidden}
  .lat-bar{flex:1;min-width:3px;border-radius:1px 1px 0 0;background:var(--accent);opacity:.7;transition:height .3s}
  .lat-bar.high{background:var(--red);opacity:1}
  .feed-panel{display:flex;flex-direction:column;overflow:hidden}
  #trade-feed{flex:1;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--border) transparent}
  .feed-header{display:grid;grid-template-columns:1fr 1fr 55px;padding:7px 14px;border-bottom:1px solid var(--border);font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;background:var(--surface)}
  .fh-r{text-align:right}
  .trade-row{display:grid;grid-template-columns:1fr 1fr 55px;padding:6px 14px;border-bottom:1px solid rgba(26,34,48,.4);font-size:12px;animation:fadeIn .25s ease}
  .trade-row:hover{background:rgba(0,229,255,.03)}
  @keyframes fadeIn{from{opacity:0;transform:translateX(6px)}to{opacity:1;transform:translateX(0)}}
  .t-price{font-weight:700}.t-price.buy{color:var(--green)}.t-price.sell{color:var(--red)}
  .t-qty{color:var(--muted);text-align:right}
  .t-lat{color:var(--muted);text-align:right;font-size:10px}.t-lat.slow{color:var(--red)}
  #loading{position:fixed;inset:0;background:var(--bg);z-index:100;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;transition:opacity .5s}
  #loading.hidden{opacity:0;pointer-events:none}
  .loading-logo{font-family:var(--display);font-size:42px;font-weight:800;color:var(--accent);letter-spacing:-1px}
  .loading-bar{width:200px;height:2px;background:var(--border);border-radius:2px;overflow:hidden}
  .loading-fill{height:100%;background:var(--accent);border-radius:2px;animation:load 1.5s ease forwards}
  @keyframes load{from{width:0}to{width:100%}}
  .loading-text{font-size:11px;color:var(--muted);letter-spacing:2px;text-transform:uppercase}
  #toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%) translateY(60px);background:var(--red);color:white;padding:8px 18px;border-radius:6px;font-size:12px;z-index:200;transition:transform .3s}
  #toast.show{transform:translateX(-50%) translateY(0)}
</style>
</head>
<body>
<div id="loading">
  <div class="loading-logo">KERNO</div>
  <div class="loading-bar"><div class="loading-fill"></div></div>
  <div class="loading-text">Connecting to market feed...</div>
</div>
<div id="toast">API not reachable — is the backend running?</div>
<header>
  <div class="logo"><div class="logo-dot"></div>KERNO</div>
  <div class="header-right">
    <div class="symbol-tabs">
      <button class="tab active" onclick="switchSymbol('BTCUSDT',this)">BTC/USDT</button>
      <button class="tab"        onclick="switchSymbol('ETHUSDT',this)">ETH/USDT</button>
    </div>
    <div class="live-badge"><div class="live-dot"></div>LIVE</div>
  </div>
</header>
<div class="metrics-bar">
  <div class="metric-cell"><div class="metric-label">Last Price</div><div class="metric-value" id="m-price">—</div><div class="metric-sub" id="m-change">—</div></div>
  <div class="metric-cell"><div class="metric-label">Avg Latency</div><div class="metric-value" id="m-lat">—</div><div class="metric-sub">ms feed delay</div></div>
  <div class="metric-cell"><div class="metric-label">Max Latency</div><div class="metric-value" id="m-maxlat">—</div><div class="metric-sub">ms worst case</div></div>
  <div class="metric-cell"><div class="metric-label">Trades / min</div><div class="metric-value" id="m-count">—</div><div class="metric-sub">last minute</div></div>
  <div class="metric-cell"><div class="metric-label">Price Range</div><div class="metric-value" id="m-range">—</div><div class="metric-sub">low -> high</div></div>
  <div class="metric-cell"><div class="metric-label">Volume</div><div class="metric-value" id="m-vol">—</div><div class="metric-sub">last minute</div></div>
</div>
<div class="main">
  <div class="chart-panel">
    <div class="panel-header">
      <div class="panel-title">Price Timeline <span id="chart-range">last 5 min</span></div>
      <div class="controls">
        <button class="btn active" onclick="setWindow(5,this)">5m</button>
        <button class="btn"        onclick="setWindow(15,this)">15m</button>
        <button class="btn"        onclick="setWindow(60,this)">1h</button>
      </div>
    </div>
    <div class="chart-wrap"><canvas id="priceChart"></canvas></div>
    <div class="latency-strip">
      <div class="strip-label">Feed Latency — last 60 events</div>
      <div id="latency-bars"></div>
    </div>
  </div>
  <div class="feed-panel">
    <div class="panel-header"><div class="panel-title">Live Trades</div></div>
    <div class="feed-header"><div>Price</div><div class="fh-r">Qty</div><div class="fh-r">Lat ms</div></div>
    <div id="trade-feed"></div>
  </div>
</div>
<script>
const API='http://localhost:8000';
let symbol='BTCUSDT',minutes=5,prevPrice=null,chart=null;

function initChart(){
  const ctx=document.getElementById('priceChart').getContext('2d');
  chart=new Chart(ctx,{
    type:'line',
    data:{labels:[],datasets:[{data:[],borderColor:'#00e5ff',backgroundColor:'rgba(0,229,255,0.08)',borderWidth:2,pointRadius:0,pointHoverRadius:4,tension:0.3,fill:true}]},
    options:{
      responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false,backgroundColor:'#0d1218',borderColor:'#1a2230',borderWidth:1,titleColor:'#4a5a70',bodyColor:'#e2eaf4',callbacks:{label:c=>' $'+c.parsed.y.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}}},
      scales:{
        x:{ticks:{color:'#4a5a70',maxTicksLimit:8,font:{family:'Space Mono',size:10}},grid:{color:'#1a2230'}},
        y:{ticks:{color:'#4a5a70',font:{family:'Space Mono',size:10},callback:v=>'$'+v.toLocaleString('en-US')},grid:{color:'#1a2230'},position:'right'}
      },
      interaction:{mode:'nearest',axis:'x',intersect:false}
    }
  });
}

async function fetchEvents(){const r=await fetch(API+'/events?symbol='+symbol+'&limit=300');return r.json()}
async function fetchMetrics(){const r=await fetch(API+'/metrics?symbol='+symbol+'&minutes='+minutes);return r.json()}

function updateChart(events){
  if(!events.length)return;
  const cutoff=Date.now()-minutes*60*1000;
  const filtered=events.filter(e=>e.event_time_ms>=cutoff).sort((a,b)=>a.event_time_ms-b.event_time_ms);
  const step=Math.max(1,Math.floor(filtered.length/200));
  const s=filtered.filter((_,i)=>i%step===0);
  chart.data.labels=s.map(e=>{const d=new Date(e.event_time_ms);return d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0')+':'+d.getSeconds().toString().padStart(2,'0')});
  chart.data.datasets[0].data=s.map(e=>e.price);
  chart.update('none');
}

function updateMetrics(events,metrics){
  if(events.length){
    const price=events[0].price;
    const el=document.getElementById('m-price');
    el.textContent=price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    if(prevPrice!==null){const diff=price-prevPrice;const pct=(diff/prevPrice*100).toFixed(3);document.getElementById('m-change').textContent=(diff>=0?'+':'')+pct+'%';el.className='metric-value '+(diff>=0?'up':'down')}
    prevPrice=price;
    const lats=events.slice(0,60).map(e=>Math.abs(e.latency_ms));
    const avg=Math.round(lats.reduce((a,b)=>a+b,0)/lats.length);
    const max=Math.max(...lats);
    document.getElementById('m-lat').textContent=avg;
    document.getElementById('m-maxlat').textContent=max;
    updateLatencyBars(lats);
  }
  if(metrics.length){
    const m=metrics[0];
    document.getElementById('m-count').textContent=m.trade_count.toLocaleString();
    document.getElementById('m-range').textContent=m.price_low.toFixed(0)+'-'+m.price_high.toFixed(0);
    document.getElementById('m-vol').textContent=m.volume.toFixed(3);
  }
}

function updateLatencyBars(lats){
  const max=Math.max(...lats,1);
  document.getElementById('latency-bars').innerHTML=lats.map(l=>{const h=Math.max(3,Math.round(l/max*36));return '<div class="lat-bar '+(l>300?'high':'')+'" style="height:'+h+'px"></div>'}).join('');
}

function updateFeed(events){
  if(!events.length)return;
  document.getElementById('trade-feed').innerHTML=events.slice(0,80).map(e=>{
    const side=e.is_buyer_maker?'sell':'buy';
    const lat=Math.abs(e.latency_ms);
    return '<div class="trade-row"><div class="t-price '+side+'">'+e.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})+'</div><div class="t-qty">'+e.quantity.toFixed(5)+'</div><div class="t-lat '+(lat>300?'slow':'')+'">'+lat+'</div></div>';
  }).join('');
}

function switchSymbol(sym,btn){symbol=sym;prevPrice=null;document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));btn.classList.add('active');refresh()}
function setWindow(min,btn){minutes=min;document.querySelectorAll('.btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');document.getElementById('chart-range').textContent='last '+min+' min';refresh()}

async function refresh(){
  try{
    const[events,metrics]=await Promise.all([fetchEvents(),fetchMetrics()]);
    updateChart(events);updateMetrics(events,metrics);updateFeed(events);
  }catch(e){
    const t=document.getElementById('toast');t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3000);
  }
}

async function boot(){
  initChart();
  await refresh();
  document.getElementById('loading').classList.add('hidden');
  setInterval(refresh,2000);
}
boot();
</script>
</body>
</html>"""

target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "index.html")
os.makedirs(os.path.dirname(target), exist_ok=True)

with open(target, "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"OK frontend actualizado: {target}")
print("Recarga http://localhost:8000/ en el browser")
