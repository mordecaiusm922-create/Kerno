import os, sys

html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kerno - Market Observatory</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#080c10;--sur:#0d1218;--brd:#1a2230;--acc:#00e5ff;--grn:#7fff6e;--red:#ff4d6d;--txt:#e2eaf4;--mut:#4a5a70}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:'Courier New',monospace;font-size:13px;height:100vh;overflow:hidden}
header{display:flex;align-items:center;justify-content:space-between;padding:12px 24px;border-bottom:1px solid var(--brd);background:rgba(8,12,16,.97);position:relative;z-index:10}
.logo{font-size:20px;font-weight:900;color:var(--acc);letter-spacing:2px;display:flex;align-items:center;gap:10px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--grn);animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
.tabs{display:flex;gap:3px;background:var(--sur);border:1px solid var(--brd);border-radius:6px;padding:3px}
.tab{padding:5px 14px;border-radius:4px;cursor:pointer;font-size:11px;color:var(--mut);background:none;border:none;font-family:inherit}
.tab.on{background:var(--acc);color:#000;font-weight:700}
.live{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--grn)}
.ldot{width:6px;height:6px;border-radius:50%;background:var(--grn);animation:blink 1.5s infinite}
.mbar{display:grid;grid-template-columns:repeat(6,1fr);border-bottom:1px solid var(--brd);background:var(--sur);position:relative;z-index:10}
.mc{padding:10px 16px;border-right:1px solid var(--brd)}
.mc:last-child{border-right:none}
.ml{font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:1px;margin-bottom:3px}
.mv{font-size:17px;font-weight:700;color:var(--txt);transition:color .3s}
.mv.up{color:var(--grn)}.mv.dn{color:var(--red)}
.ms{font-size:10px;color:var(--mut);margin-top:2px}
.main{display:grid;grid-template-columns:1fr 290px;height:calc(100vh - 107px);position:relative;z-index:10}
.cp{display:flex;flex-direction:column;border-right:1px solid var(--brd)}
.ph{display:flex;align-items:center;justify-content:space-between;padding:9px 16px;border-bottom:1px solid var(--brd);background:rgba(13,18,24,.9)}
.pt{font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px}
.pt span{font-size:10px;color:var(--mut);font-weight:400}
.btns{display:flex;gap:5px}
.btn{padding:4px 10px;border-radius:4px;border:1px solid var(--brd);background:var(--sur);color:var(--mut);font-family:inherit;font-size:11px;cursor:pointer;transition:all .2s}
.btn.on,.btn:hover{border-color:var(--acc);color:var(--acc)}
.cw{flex:1;padding:10px;min-height:0;position:relative}
.ls{height:68px;border-top:1px solid var(--brd);padding:7px 16px;background:var(--sur)}
.sl{font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px}
#lb{display:flex;align-items:flex-end;gap:2px;height:34px;overflow:hidden}
.lb{flex:1;min-width:3px;border-radius:1px 1px 0 0;background:var(--acc);opacity:.7}
.lb.hi{background:var(--red);opacity:1}
.fp{display:flex;flex-direction:column;overflow:hidden}
#tf{flex:1;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--brd) transparent}
.fh{display:grid;grid-template-columns:1fr 1fr 50px;padding:6px 12px;border-bottom:1px solid var(--brd);font-size:10px;color:var(--mut);text-transform:uppercase;background:var(--sur)}
.fr{font-size:10px;text-align:right}
.tr{display:grid;grid-template-columns:1fr 1fr 50px;padding:5px 12px;border-bottom:1px solid rgba(26,34,48,.4);font-size:12px}
.tp{font-weight:700}.tp.b{color:var(--grn)}.tp.s{color:var(--red)}
.tq{color:var(--mut);text-align:right}.tl{color:var(--mut);text-align:right;font-size:10px}.tl.sl2{color:var(--red)}
#ld{position:fixed;inset:0;background:var(--bg);z-index:100;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;transition:opacity .4s}
#ld.hide{opacity:0;pointer-events:none}
.ll{font-size:40px;font-weight:900;color:var(--acc);letter-spacing:3px}
.lb2{width:180px;height:2px;background:var(--brd);border-radius:2px;overflow:hidden}
.lf{height:100%;background:var(--acc);animation:fill 1.5s ease forwards}
@keyframes fill{from{width:0}to{width:100%}}
.lt{font-size:10px;color:var(--mut);letter-spacing:2px}
#toast{position:fixed;bottom:16px;left:50%;transform:translateX(-50%) translateY(50px);background:var(--red);color:#fff;padding:7px 16px;border-radius:5px;font-size:12px;z-index:200;transition:transform .3s}
#toast.sh{transform:translateX(-50%) translateY(0)}
</style>
</head>
<body>
<div id="ld"><div class="ll">KERNO</div><div class="lb2"><div class="lf"></div></div><div class="lt">CONNECTING TO MARKET FEED...</div></div>
<div id="toast">API not reachable</div>
<header>
  <div class="logo"><div class="dot"></div>KERNO</div>
  <div style="display:flex;align-items:center;gap:18px">
    <div class="tabs">
      <button class="tab on" onclick="sw('BTCUSDT',this)">BTC/USDT</button>
      <button class="tab"    onclick="sw('ETHUSDT',this)">ETH/USDT</button>
    </div>
    <div class="live"><div class="ldot"></div>LIVE</div>
  </div>
</header>
<div class="mbar">
  <div class="mc"><div class="ml">Last Price</div><div class="mv" id="mp">-</div><div class="ms" id="mc2">-</div></div>
  <div class="mc"><div class="ml">Avg Latency</div><div class="mv" id="ml2">-</div><div class="ms">ms delay</div></div>
  <div class="mc"><div class="ml">Max Latency</div><div class="mv" id="mm">-</div><div class="ms">ms worst</div></div>
  <div class="mc"><div class="ml">Trades/min</div><div class="mv" id="mt">-</div><div class="ms">last min</div></div>
  <div class="mc"><div class="ml">Range</div><div class="mv" id="mr">-</div><div class="ms">low-high</div></div>
  <div class="mc"><div class="ml">Volume</div><div class="mv" id="mv2">-</div><div class="ms">last min</div></div>
</div>
<div class="main">
  <div class="cp">
    <div class="ph">
      <div class="pt">Price Timeline <span id="cr">last 5 min</span></div>
      <div class="btns">
        <button class="btn on" onclick="sw2(5,this)">5m</button>
        <button class="btn"    onclick="sw2(15,this)">15m</button>
        <button class="btn"    onclick="sw2(60,this)">1h</button>
      </div>
    </div>
    <div class="cw"><canvas id="pc"></canvas></div>
    <div class="ls"><div class="sl">Feed Latency - last 60 events</div><div id="lb"></div></div>
  </div>
  <div class="fp">
    <div class="ph"><div class="pt">Live Trades</div></div>
    <div class="fh"><div>Price</div><div class="fr">Qty</div><div class="fr">Lat</div></div>
    <div id="tf"></div>
  </div>
</div>
<script>
var API='http://localhost:8000',sym='BTCUSDT',min=5,prev=null,ch=null;
function ic(){
  var ctx=document.getElementById('pc').getContext('2d');
  ch=new Chart(ctx,{type:'line',data:{labels:[],datasets:[{data:[],borderColor:'#00e5ff',backgroundColor:'rgba(0,229,255,0.07)',borderWidth:2,pointRadius:0,tension:0.3,fill:true}]},options:{responsive:true,maintainAspectRatio:false,animation:false,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false,backgroundColor:'#0d1218',borderColor:'#1a2230',borderWidth:1,titleColor:'#4a5a70',bodyColor:'#e2eaf4'}},scales:{x:{ticks:{color:'#4a5a70',maxTicksLimit:7,font:{size:10}},grid:{color:'#1a2230'}},y:{ticks:{color:'#4a5a70',font:{size:10},callback:function(v){return '$'+v.toLocaleString()}},grid:{color:'#1a2230'},position:'right'}},interaction:{mode:'nearest',axis:'x',intersect:false}}});
}
async function fe(){var r=await fetch(API+'/events?symbol='+sym+'&limit=300');return r.json()}
async function fm(){var r=await fetch(API+'/metrics?symbol='+sym+'&minutes='+min);return r.json()}
function uc(ev){
  if(!ev.length)return;
  var cut=Date.now()-min*60000;
  var f=ev.filter(function(e){return e.event_time_ms>=cut}).sort(function(a,b){return a.event_time_ms-b.event_time_ms});
  var s=Math.max(1,Math.floor(f.length/200));
  var d=f.filter(function(_,i){return i%s===0});
  ch.data.labels=d.map(function(e){var dt=new Date(e.event_time_ms);return ('0'+dt.getHours()).slice(-2)+':'+('0'+dt.getMinutes()).slice(-2)+':'+('0'+dt.getSeconds()).slice(-2)});
  ch.data.datasets[0].data=d.map(function(e){return e.price});
  ch.update('none');
}
function um(ev,mx){
  if(ev.length){
    var p=ev[0].price;
    var el=document.getElementById('mp');
    el.textContent=p.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    if(prev!==null){var d=p-prev;var pc=(d/prev*100).toFixed(3);document.getElementById('mc2').textContent=(d>=0?'+':'')+pc+'%';el.className='mv '+(d>=0?'up':'dn')}
    prev=p;
    var ls=ev.slice(0,60).map(function(e){return Math.abs(e.latency_ms)});
    var avg=Math.round(ls.reduce(function(a,b){return a+b},0)/ls.length);
    document.getElementById('ml2').textContent=avg;
    document.getElementById('mm').textContent=Math.max.apply(null,ls);
    ulb(ls);
  }
  if(mx.length){var m=mx[0];document.getElementById('mt').textContent=m.trade_count.toLocaleString();document.getElementById('mr').textContent=m.price_low.toFixed(0)+'-'+m.price_high.toFixed(0);document.getElementById('mv2').textContent=m.volume.toFixed(3)}
}
function ulb(ls){
  var mx=Math.max.apply(null,ls)||1;
  document.getElementById('lb').innerHTML=ls.map(function(l){var h=Math.max(3,Math.round(l/mx*34));return '<div class="lb'+(l>300?' hi':'')+'" style="height:'+h+'px"></div>'}).join('');
}
function uf(ev){
  if(!ev.length)return;
  document.getElementById('tf').innerHTML=ev.slice(0,80).map(function(e){var si=e.is_buyer_maker?'s':'b';var lt=Math.abs(e.latency_ms);return '<div class="tr"><div class="tp '+si+'">'+e.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})+'</div><div class="tq">'+e.quantity.toFixed(5)+'</div><div class="tl'+(lt>300?' sl2':'')+' ">'+lt+'</div></div>'}).join('');
}
function sw(s,b){sym=s;prev=null;document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('on')});b.classList.add('on');rf()}
function sw2(m,b){min=m;document.querySelectorAll('.btn').forEach(function(x){x.classList.remove('on')});b.classList.add('on');document.getElementById('cr').textContent='last '+m+' min';rf()}
async function rf(){
  try{
    var r=await Promise.all([fe(),fm()]);
    uc(r[0]);um(r[0],r[1]);uf(r[0]);
  }catch(e){var t=document.getElementById('toast');t.classList.add('sh');setTimeout(function(){t.classList.remove('sh')},3000)}
}
async function boot(){ic();await rf();document.getElementById('ld').classList.add('hide');setInterval(rf,2000)}
boot();
</script>
</body>
</html>"""

target = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'frontend', 'index.html')
os.makedirs(os.path.dirname(target), exist_ok=True)
with open(target, 'w', encoding='utf-8') as f:
    f.write(html)
print('OK:', target)
