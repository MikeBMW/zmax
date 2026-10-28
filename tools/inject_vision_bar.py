#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「产品愿景 · 最后一厘米」条装进 ar3d 页 (老倪 2026-10-28)。

要求: 「根据产品愿景 … 这个愿景，一个在 AR 场景体现」
做法: 在屏幕下方、市场预期窗口之上，加一条 42px 的愿景条 —— 不遮 3D 视口、不抢按钮区。
  左: 愿景一句话 · 最后一厘米
  中: 闭环四环节 (看 → 判 → 动 → 验)，生产时点亮呼吸灯
  右: 三个可数的东西 (动作单元 / 完成件数 / 数据回流) + 四个物理量 (插入行程/速度/力上限/像素当量)
数据: /api/ar/vision (唯一依据 tools/spec/vision.json) + window.__PROD__ 的演练件数;
  条上不预先固定任何数字 (除 vision.json 里的物理量)。

跑法: python3 tools/inject_vision_bar.py   (幂等)
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "tools", "web", "tcp-ar.html")

CSS = """
<style id="visBarCss">
#visBar{position:fixed;left:0;right:0;bottom:140px;height:42px;z-index:59;
  display:flex;align-items:center;gap:10px;padding:0 12px;font-size:12px;
  background:linear-gradient(90deg,rgba(88,166,255,.10),rgba(11,15,20,.92) 40%,rgba(11,15,20,.92));
  border-top:1px solid #21262d;border-bottom:1px solid #21262d;color:#c9d1d9;overflow:hidden}
#visBar .vT{font-weight:700;color:#58a6ff;white-space:nowrap}
#visBar .vSub{color:#8b949e;white-space:nowrap;font-size:11px}
#visBar .vLoop{display:flex;align-items:center;gap:4px;white-space:nowrap}
#visBar .vLoop b{font-weight:600;color:#8b949e;font-size:11px}
#visBar .vDot{width:7px;height:7px;border-radius:50%;background:#30363d;display:inline-block}
#visBar.run .vDot{background:#3fb950;animation:vp 1.4s infinite}
#visBar.run .vDot:nth-child(2){animation-delay:.35s}
#visBar.run .vDot:nth-child(3){animation-delay:.7s}
#visBar.run .vDot:nth-child(4){animation-delay:1.05s}
@keyframes vp{0%,100%{opacity:.35}50%{opacity:1}}
#visBar .vK{color:#8b949e;white-space:nowrap}
#visBar .vK b{color:#e6edf3;font-weight:700;font-variant-numeric:tabular-nums}
#visBar .vPhys{margin-left:auto;color:#8b949e;white-space:nowrap;font-size:11px}
#visBar .vPhys b{color:#d29922}
@media (max-width:1200px){#visBar .vSub,#visBar .vPhys{display:none}}
</style>
"""

HTML = """
<div id="visBar" title="产品愿景: 让工业机器人干精密活 —— 把工厂里最难的那一厘米交给设备自己完成">
  <span class="vT">🎯 让工业机器人干精密活</span>
  <span class="vSub">· 最后一厘米</span>
  <span class="vLoop"><b>看</b><i class="vDot"></i><b>判</b><i class="vDot"></i><b>动</b><i class="vDot"></i><b>验</b><i class="vDot"></i></span>
  <span class="vK">动作单元 <b id="vUnits">—</b> · 段 <b id="vSegs">—</b></span>
  <span class="vK">完成 <b id="vPieces">0</b> 件</span>
  <span class="vK">数据回流 <b id="vReflux">0</b> 条</span>
  <span class="vPhys" id="vPhys">插入 — mm @ — mm/s · 力 ≤ — N · — mm/px · — s/件</span>
</div>
"""

JS = """
<script id="visBarJs">
(function(){
  var V=null, $=function(id){return document.getElementById(id)};
  function fmt(n){return (n||0).toLocaleString('zh-CN')}
  fetch('/api/ar/vision').then(function(r){return r.json()}).then(function(d){
    if(!d||!d.ok) return;
    V=d;
    $('vUnits').textContent=fmt(d.units||0);
    $('vSegs').textContent=fmt(d.segs||0);
    var o=(d.ar&&d.ar.overlay)||{};
    $('vPhys').innerHTML='插入 <b>'+(o.insert_mm||'—')+'</b> mm @ <b>'+(o.insert_mm_s||'—')
      +'</b> mm/s · 力 ≤ <b>'+(o.force_limit_n||'—')+'</b> N · <b>'+(o.pixel_mm_at_300||'—')
      +'</b> mm/px · <b>'+(o.tact_s||'—')+'</b> s/件 @ <b>'+(o.uph||'—')+'</b> UPH'
      +' · 目标 <b>'+(o.uph_target||300)+'</b> UPH';
    document.getElementById('visBar').title=(d.vision&&d.vision.subline||'')+'\\n'+(d.vision&&d.vision.answer||'');
  }).catch(function(){});
  setInterval(function(){
    var bar=$('visBar'); if(!bar) return;
    var P=window.__PROD__; if(!P||!P.read) return;
    var r=P.read(); var pieces=r.pieces||0;
    $('vPieces').textContent=fmt(pieces);
    $('vReflux').textContent=fmt(pieces*5);          // 每件 5 类采集项: 图像/力/关节/结果/干预
    if(r.running) bar.classList.add('run'); else bar.classList.remove('run');
  },400);
  window.__VIS__={get:function(){return {units:$('vUnits').textContent,segs:$('vSegs').textContent,pieces:$('vPieces').textContent,
    reflux:$('vReflux').textContent,phys:$('vPhys').textContent,on:document.getElementById('visBar').classList.contains('run')}}};
})();
</script>
"""


def main():
    s = open(P, encoding="utf-8").read()
    if 'id="visBar"' in s:
        s = re.sub(r'<style id="visBarCss">.*?</style>', '', s, flags=re.S)
        s = re.sub(r'<div id="visBar".*?\n</div>\n', '', s, flags=re.S)
        s = re.sub(r'<script id="visBarJs">.*?</script>', '', s, flags=re.S)
        print("旧愿景条已剔除, 重装")
    assert s.count("</body></html>") == 1, "页面结构变了: 找不到唯一的 </body></html>"
    s = s.replace("</body></html>", CSS + HTML + JS + "</body></html>")
    open(P, "w", encoding="utf-8").write(s)
    print("愿景条已装入 %s (%d 字节)" % (os.path.relpath(P, ROOT), len(s.encode())))


if __name__ == "__main__":
    main()
