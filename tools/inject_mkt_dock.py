#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「生产演练 + 市场预期」独立窗口装进 ar3d 页 (老倪 2026-10-28 第十一轮)。

做什么:
  1) 屏幕下方固定一个独立 dock (#mktDock), 不遮挡主区 (body 加 padding-bottom)
  2) 选工单 (T1/T2/T3) → 「▶ 安排生产」→ 按实测节拍 11.42s/件 累计产量与产值
  3) dock 实时显示: 已生产件数 · 演练工时 · 实测 UPH · 累计产值 · 年化产量/收入/年毛利/回收期 · 三方分成
  4) 数据全部来自 /api/ar/cost (tools/cost_model.build_tiers() 现算), 页面不另存一份数字
  5) 暴露 window.__PROD__ 供离屏判据确定性推进 (tick(dt))
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "tools", "web", "tcp-ar.html")

CSS = """
<style id="mktDockCss">
body{padding-bottom:196px}
#mktDock{position:fixed;left:0;right:0;bottom:0;z-index:80;background:linear-gradient(180deg,#0b1117,#0d141c);
  border-top:2px solid #3fbf7f;box-shadow:0 -6px 18px rgba(0,0,0,.55);font-family:Consolas,Menlo,monospace;
  color:#c9d1d9;padding:7px 12px 8px;box-sizing:border-box}
#mktDock .mRow{display:flex;align-items:center;gap:9px;flex-wrap:nowrap;overflow:hidden}
#mktDock .mT{font-size:12px;font-weight:700;color:#f0c674;white-space:nowrap}
#mktDock select,#mktDock button{background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;
  font-size:11.5px;padding:2px 8px;cursor:pointer;font-family:inherit}
#mktDock button.on{background:#1d3b28;border-color:#3fbf7f;color:#7ee2a8}
#mktDock .mK{display:flex;flex-direction:column;min-width:86px;background:#11171e;border:1px solid #21262d;
  border-radius:6px;padding:3px 8px}
#mktDock .mK b{font-size:13px;color:#58a6ff;font-weight:700;line-height:1.25;white-space:nowrap}
#mktDock .mK span{font-size:9.5px;color:#7d8590;white-space:nowrap}
#mktDock .mWide{flex:1 1 auto;min-width:0}
#mktDock .mWide b{color:#b58cf0;font-size:12px;white-space:normal;line-height:1.35}
#mktDock .mLed{width:8px;height:8px;border-radius:50%;background:#7d8590;flex:0 0 auto}
#mktDock .mLed.run{background:#3fbf7f;box-shadow:0 0 6px #3fbf7f}
</style>
"""

HTML = """
<div id="mktDock">
  <div class="mRow" style="margin-bottom:4px">
    <span class="mLed" id="mkLed"></span>
    <span class="mT">💰 生产演练 · 市场预期</span>
    <select id="mkTier" title="选工单: T1 基础 / T2 精细 / T3 专业">
      <option value="A">T1 基础 (L2 · ≤30 TOPS)</option>
      <option value="B">T2 精细 (L2+L3 · ≤80 TOPS)</option>
      <option value="C">T3 专业 (L2+L3+L4 · ≤300 TOPS)</option>
    </select>
    <button id="mkStart">▶ 安排生产</button>
    <button id="mkStop">⏸ 暂停</button>
    <button id="mkReset">↺ 重置</button>
    <select id="mkSpeed" title="演练倍速">
      <option value="1">x1 实时</option>
      <option value="60" selected>x60 (1s=1min)</option>
      <option value="600">x600 (1s=10min)</option>
    </select>
    <span id="mkStat" style="font-size:11px;color:#7d8590;margin-left:2px">待机</span>
  </div>
  <div class="mRow" style="margin-bottom:4px">
    <div class="mK"><b id="mkPc">0</b><span>已生产 (件)</span></div>
    <div class="mK"><b id="mkHr">0.00</b><span>演练工时 (h)</span></div>
    <div class="mK"><b id="mkUph">—</b><span>实测 UPH</span></div>
    <div class="mK"><b id="mkVal">0</b><span>累计收入 (元)</span></div>
    <div class="mK"><b id="mkBatch">0</b><span>完成批次 (8h/批)</span></div>
    <div class="mK"><b id="mkPy">—</b><span>年化产量 (件/年)</span></div>
    <div class="mK"><b id="mkRev">—</b><span>设备售价 (万)</span></div>
    <div class="mK"><b id="mkGross">—</b><span>三方年毛利 (万)</span></div>
    <div class="mK"><b id="mkPb">—</b><span>软件方回收 (年)</span></div>
    <div class="mK"><b id="mkUnit">—</b><span>客户单件成本 (元)</span></div>
  </div>
  <div class="mRow">
    <div class="mK mWide" style="flex:1 1 58%"><b id="mkExpect">市场预期加载中…</b><span>预测口径: 实测节拍 × 档位工时 × OEE (与《性能配置》《成本分析》同一真源)</span></div>
    <div class="mK mWide" style="flex:1 1 42%"><b id="mkSplit">三方分成 加载中…</b><span>机器人本体硬件 / 模型软件 / 运营数据</span></div>
  </div>
</div>
"""

JS = """
<script id="mktDockJs">
(function(){
  var PROD={tier:'A',running:false,simT:0,pieces:0,speed:60,tact:11.42,COST:null};
  var $=function(id){return document.getElementById(id)};
  function fmt(n,d){d=d||0;return (n||0).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d})}
  function wan(n){return (n/1e4).toFixed(1)}
  function row(){ if(!PROD.COST) return null;
    for(var i=0;i<PROD.COST.tiers.length;i++){ if(PROD.COST.tiers[i].id===PROD.tier) return PROD.COST.tiers[i]; }
    return null; }
  function mk(){ if(!PROD.COST) return null;
    for(var i=0;i<PROD.COST.market.length;i++){ if(PROD.COST.market[i].tier===PROD.tier) return PROD.COST.market[i]; }
    return null; }
  function render(){
    var t=row(), m=mk(); if(!t) return;
    var uph=PROD.COST.uph_geo, pieces=Math.floor(PROD.simT/PROD.tact), hours=PROD.simT/3600;
    PROD.pieces=pieces;
    $('mkPc').textContent=fmt(pieces);
    $('mkHr').textContent=hours.toFixed(2);
    $('mkUph').textContent=uph.toFixed(1);
    var lpr=(t.license_per_piece||0)+(t.ops_fee_per_piece||0);
    $('mkVal').textContent=fmt((t.price_set||0)+pieces*lpr,2);
    $('mkBatch').textContent=fmt(Math.floor(hours/8));
    $('mkPy').textContent=fmt(t.pieces_year);
    var g3=(t.gross_year_hw||0)+(t.gross_year_sw||0)+(t.gross_year_op||0);
    $('mkRev').textContent=wan(t.price_set||0);
    $('mkGross').textContent=wan(g3);
    $('mkPb').textContent=(t.payback_sw_cash==null?'—':t.payback_sw_cash.toFixed(2));
    $('mkUnit').textContent=(t.client_unit_cost||0).toFixed(4);
    var sp=(PROD.COST.split||{})[PROD.tier]||{};
    var pct=((sp.s4_priced||{}).pct)||{};
    $('mkSplit').textContent='硬件 '+(pct.hw||0)+'% · 软件 '+(pct.sw||0)+'% · 运营 '+(pct.op||0)+'%'
      +'　(售价封顶 '+wan(t.price_cap||0)+' 万 · 许可 '+(t.license_per_piece||0).toFixed(3)
      +' 元/件 + 运营 '+(t.ops_fee_per_piece||0).toFixed(3)+' 元/件)';
    $('mkExpect').textContent='按 '+t.id+' 配置 · 售价 '+wan(t.price_set||0)+' 万 (上限 '+wan(t.price_cap||0)
      +' 万) · '+uph.toFixed(1)+' UPH · '+t.hours_per_year+'h/年 · OEE '+t.oee
      +' ⇒ '+fmt(t.pieces_year)+' 件/年 · 客户单件 '+(t.client_unit_cost||0).toFixed(3)
      +' 元 (人工 0.36 元, 省 '+(t.client_save_pct||0)+'%) · 三方年毛利 '+wan(g3)+' 万';
  }
  function setLed(on){ var l=$('mkLed'); if(l) l.className='mLed'+(on?' run':'');
    $('mkStat').textContent=on?'生产中 · 速率 x'+PROD.speed:'待机';
    $('mkStart').className=on?'on':''; }
  function tick(dt){
    if(PROD.running){ PROD.simT+=dt*PROD.speed; }
    render();
  }
  function load(){
    fetch('/api/ar/cost').then(function(r){return r.json()}).then(function(d){
      if(!d||!d.ok) return;
      PROD.COST=d; PROD.tact=d.tact_s||11.42; render();
    }).catch(function(){});
  }
  window.__PROD__={
    load:load, tick:tick, read:function(){ return {tier:PROD.tier,running:PROD.running,simT:PROD.simT,
      pieces:PROD.pieces,speed:PROD.speed,tact:PROD.tact,
      pc:$('mkPc').textContent,val:$('mkVal').textContent,uph:$('mkUph').textContent,
      expect:$('mkExpect').textContent,split:$('mkSplit').textContent,stat:$('mkStat').textContent}; },
    setTier:function(t){PROD.tier=t; $('mkTier').value=t; render();},
    start:function(){PROD.running=true;setLed(true);},
    stop:function(){PROD.running=false;setLed(false);},
    reset:function(){PROD.simT=0;PROD.pieces=0;render();},
    setSpeed:function(s){PROD.speed=s;$('mkSpeed').value=String(s);setLed(PROD.running);}
  };
  document.addEventListener('DOMContentLoaded',function(){
    load();
    $('mkTier').addEventListener('change',function(e){PROD.tier=e.target.value;render();});
    $('mkSpeed').addEventListener('change',function(e){PROD.speed=parseFloat(e.target.value);setLed(PROD.running);});
    $('mkStart').addEventListener('click',function(){PROD.running=true;setLed(true);});
    $('mkStop').addEventListener('click',function(){PROD.running=false;setLed(false);});
    $('mkReset').addEventListener('click',function(){PROD.simT=0;PROD.pieces=0;render();});
    setInterval(function(){tick(0.25)},250);
  });
})();
</script>
"""


def main():
    s = open(P, encoding="utf-8").read()
    if 'id="mktDock"' in s:
        # 幂等: 先剔除旧的 CSS/HTML/JS 再装新的
        import re
        s = re.sub(r'<style id="mktDockCss">.*?</style>', '', s, flags=re.S)
        s = re.sub(r'<div id="mktDock">.*?\n</div>\n', '', s, flags=re.S)
        s = re.sub(r'<script id="mktDockJs">.*?</script>', '', s, flags=re.S)
        print("旧 dock 已剔除, 重装")
    assert s.count("</body></html>") == 1, "页面结构变了: 找不到唯一的 </body></html>"
    s = s.replace("</body></html>", CSS + HTML + JS + "</body></html>")
    open(P, "w", encoding="utf-8").write(s)
    print("dock 已装入 %s (%d 字节)" % (os.path.relpath(P, ROOT), len(s.encode())))


if __name__ == "__main__":
    main()
