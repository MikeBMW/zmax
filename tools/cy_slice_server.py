#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cy_slice_server.py — 六维卡拉比-丘流形切面 · 网页服务 (孔洞可视化, WebGL)

端口 8810 (只读, 不下发任何动作)
    GET /                 交互页 (本地 three.js, 拖拽旋转 / 滚轮缩放 / W 线框 / R 复位)
    GET /slice.json       切面网格 (顶点/面/分支) + 数学元数据
    GET /slice.obj        同一张曲面的 OBJ (给 Blender/MeshLab 复核)
    GET /live.json        十维引擎隐藏 6 维 (力/公差/置信度) 现场值 + gate
    GET /three.module.js  本地 three.js (不依赖外网 CDN)
    GET /health           存活

口径: 画的不是"想象中的 CY", 而是 x⁵+y⁵=1 (Fermat 五次平面曲线) 的**真实解集**,
      逐点残差 |x⁵+y⁵−1| ~1e-14; 孔洞数 = 亏格 6, 由 Riemann–Hurwitz 推出。
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.manifold.core.calabi_yau import quintic_slice_mesh, to_obj  # noqa: E402

PORT = int(os.environ.get("ZMAX_CY_PORT", "8810"))
START_TS = time.time()

# 📇 本机标准服务清单 (页面右下角"本机服务"卡片逐个探活; 只读, 不改任何服务)
SERVICES = [
    ("8791", "看板 dashboard", "/"),
    ("8793", "工位页 station", "/station"),
    ("8797", "AR 三维页", "/ar"),
    ("8810", "六维CY切面 (本页)", "/"),
    ("8898", "手臂相机 YOLO", "/health"),
    ("8796", "SAM3 分割", "/health"),
    ("8789", "health 汇总", "/health"),
]
LIVE_DIR = os.environ.get("ZMAX_SS_LIVE") or os.path.join(ROOT, "zmax_data/ss_live")
THREE_JS = os.path.join(ROOT, "tools/three.module.js")

_CACHE = {}


def mesh_payload() -> dict:
    """页面用网格 + 元数据 (进程内缓存)"""
    if "page" not in _CACHE:
        m = quintic_slice_mesh(n_rad=20, n_ang=72, r_max=1.02)
        _CACHE["page"] = {
            "v": [[round(float(c), 5) for c in p] for p in m["V"]],
            "f": m["F"].tolist(),
            "s": m["SHEET"].tolist(),
            "meta": dict(m["meta"], resid_max=m["resid_max"],
                         genus_derivation="2g−2 = 5·(2·0−2) + 5·(5−1) = 10 ⇒ g = 6",
                         ts=time.time()),
        }
    return _CACHE["page"]


def obj_payload() -> str:
    if "obj" not in _CACHE:
        _CACHE["obj"] = to_obj(quintic_slice_mesh())
    return _CACHE["obj"]


def version_now() -> dict:
    """版本号真源 = VERSION.md「## 版本历史」表首 (每请求热读, 改号不用重启本服务)

    ⚠️ 表头上面还有正文提到历史版本号(实测解析到 5.50.771) ⇒ 必须先定位「## 版本历史」再抓
       `**vX.Y.Z**` 形式的首行, 不能全文找第一个 "v5."。
    """
    import re as _re
    pv = os.path.join(ROOT, "VERSION.md")
    try:
        txt = open(pv, encoding="utf-8").read()
        seg = txt.split("## 版本历史", 1)[-1]
        m = _re.search(r"\*\*v(\d+\.\d+\.\d+)\*\*", seg)
        if m:
            return {"version": m.group(1), "tag": "v" + m.group(1)}
    except Exception:                                                      # noqa: BLE001
        pass
    return {"version": "?", "tag": "?"}


_SVC_CACHE = {"ts": 0.0, "items": []}


def services_payload() -> dict:
    """逐个 TCP 探活 (0.25s 超时, 5s 缓存) —— 页面用来显示"这台机器上哪些服务活着" """
    import socket
    now = time.time()
    if now - _SVC_CACHE["ts"] < 5.0 and _SVC_CACHE["items"]:
        return {"ts": _SVC_CACHE["ts"], "items": _SVC_CACHE["items"]}
    items = []
    for port, name, path in SERVICES:
        up = False
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
                up = True
        except Exception:                                                  # noqa: BLE001
            up = False
        items.append({"port": port, "name": name, "up": up, "path": path})
    _SVC_CACHE.update(ts=now, items=items)
    return {"ts": now, "items": items}


def live_payload() -> dict:
    """隐藏 6 维现场值: 十维引擎落盘的 mani10_live.json (缺失就明说, 不编)"""
    p = os.path.join(LIVE_DIR, "mani10_live.json")
    out = {"ok": False, "src": p, "age_s": None, "hidden6": None, "gate": None}
    try:
        d = json.load(open(p, encoding="utf-8"))
        out.update(ok=True, age_s=round(time.time() - float(d.get("t", 0)), 1),
                   gate=d.get("gate"), utilization=d.get("utilization"),
                   V=d.get("V"), action6=d.get("action6"))
        X = d.get("X10") or []
        out["hidden6"] = [float(x) for x in X[4:10]] if len(X) >= 10 else None
    except Exception as e:                                                 # noqa: BLE001
        out["err"] = "%s: %s" % (type(e).__name__, e)
    return out


PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>六维卡拉比-丘流形 · 切面 (孔洞 g=6)</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;background:#07090d;color:#d8dee9;font:14px/1.6 -apple-system,"Noto Sans CJK SC",system-ui,sans-serif}
 header{padding:13px 20px 9px;border-bottom:1px solid #1b2230}
 h1{margin:0;font-size:17px;font-weight:600;letter-spacing:.3px}
 h1 span{color:#7bdcb5}
 .sub{color:#78849a;font-size:12px;margin-top:4px}
 main{display:grid;grid-template-columns:1fr 352px;height:calc(100vh - 60px)}
 #stage{position:relative;background:radial-gradient(circle at 50% 45%,#0e1520 0%,#07090d 72%)}
 #stage canvas{display:block;cursor:grab}
 #stage canvas:active{cursor:grabbing}
 .hud{position:absolute;left:14px;top:12px;font:12px/1.7 ui-monospace,Menlo,monospace;color:#8d99ad;
      background:rgba(7,9,13,.7);border:1px solid #1b2230;border-radius:8px;padding:8px 11px;white-space:pre;pointer-events:none}
 .hud b{color:#7bdcb5;font-weight:600}
 aside{border-left:1px solid #1b2230;overflow:auto;padding:16px 16px 40px}
 .card{background:#0d1219;border:1px solid #1b2230;border-radius:10px;padding:12px 13px;margin-bottom:12px}
 .card h2{margin:0 0 8px;font-size:12px;letter-spacing:.6px;color:#7bdcb5;text-transform:uppercase;font-weight:600}
 .kv{display:flex;justify-content:space-between;gap:10px;font-size:13px;padding:2px 0}
 .kv i{color:#78849a;font-style:normal}
 .kv b{font-weight:600;color:#e6ebf3}
 .mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}
 .bar{height:7px;background:#141b26;border-radius:4px;overflow:hidden;margin:3px 0 7px}
 .bar>div{height:100%;background:linear-gradient(90deg,#2d7d9a,#7bdcb5);border-radius:4px;transition:width .25s}
 .lg{display:flex;align-items:center;gap:7px;font-size:12px;color:#9aa6b8;margin-top:6px}
 .dot{width:10px;height:10px;border-radius:3px}
 .warn{color:#e0b060}.bad{color:#e06c75}
 footer{position:fixed;left:0;right:352px;bottom:0;padding:6px 14px;font-size:11px;color:#5b667a;
        background:linear-gradient(transparent,#07090d 60%)}
 @media(max-width:900px){main{grid-template-columns:1fr;height:auto}aside{border-left:0;border-top:1px solid #1b2230}footer{right:0}}
</style></head><body>
<header>
  <h1>六维卡拉比-丘流形 · <span>实二维切面</span> — 孔洞即拓扑亏格 <span>g = 6</span></h1>
  <div class="sub">Fermat 五次曲面 x⁵+y⁵=1 的真实解集 · 逐点残差 &lt; 1e-13 · 5 个全分歧点 ⇒ Riemann–Hurwitz 六个孔洞</div>
</header>
<main>
  <div id="stage">
    <div class="hud" id="hud">载入中…</div>
  </div>
  <aside>
    <div class="card">
      <h2>数学</h2>
      <div class="kv"><i>切面曲线</i><b class="mono">x⁵ + y⁵ = 1</b></div>
      <div class="kv"><i>空间</i><b>CY₃ ⊂ CP⁴ 复二维切片</b></div>
      <div class="kv"><i>亏格 (孔洞数)</i><b style="color:#7bdcb5">g = 6</b></div>
      <div class="kv"><i>分歧点</i><b>5 个 (全分歧 e=5)</b></div>
      <div class="kv"><i>推导</i><b class="mono" id="deriv" style="font-size:11px">—</b></div>
      <div class="kv"><i>网格残差</i><b class="mono" id="resid">—</b></div>
    </div>
    <div class="card">
      <h2>隐藏 6 维现场值 (十维引擎)</h2>
      <div id="live" class="mono warn">读取中…</div>
    </div>
    <div class="card">
      <h2>五个分支 (y 的 5 个解)</h2>
      <div id="legend"></div>
      <div class="lg"><span class="dot" style="background:#7bdcb5"></span>颜色 = 分支 · 瓣间空隙即孔洞</div>
    </div>
    <div class="card">
      <h2>本机服务 (只读探活)</h2>
      <div id="svc" class="mono">读取中…</div>
    </div>
    <div class="card">
      <h2>导出</h2>
      <div class="kv"><i>网格</i><b><a href="/slice.json" style="color:#7bdcb5">/slice.json</a></b></div>
      <div class="kv"><i>OBJ</i><b><a href="/slice.obj" style="color:#7bdcb5">/slice.obj</a></b></div>
    </div>
  </aside>
</main>
<footer id="ft">只读可视化 · 不下发任何动作 · WebGL 深度缓冲 · 数据源 /slice.json</footer>
<script type="module">
import * as THREE from '/three.module.js';
const stage=document.getElementById('stage');
const rnd=new THREE.WebGLRenderer({antialias:true,alpha:true});
rnd.setPixelRatio(Math.min(devicePixelRatio,2));
stage.appendChild(rnd.domElement);
const scene=new THREE.Scene();
const cam=new THREE.PerspectiveCamera(38,1,0.05,200);
cam.position.set(0,0,8.6);
scene.add(new THREE.AmbientLight(0xffffff,0.55));
const L1=new THREE.DirectionalLight(0xffffff,1.0); L1.position.set(3.5,5,4.5); scene.add(L1);
const L2=new THREE.DirectionalLight(0x8fd0ff,0.55); L2.position.set(-4.5,-3,-2.5); scene.add(L2);
const L3=new THREE.DirectionalLight(0xffb86b,0.35); L3.position.set(0,-5,3); scene.add(L3);
const COL=[0xe06c75,0xe0b060,0x7bdcb5,0x61aeee,0xb48ce0];
const grp=new THREE.Group(); scene.add(grp);
let mesh=null, wire=false, yaw=-0.62, pitch=0.28, zoom=1.45, drag=false, px=0, py=0, tris=0;

function resize(){
  const w=stage.clientWidth||800, h=stage.clientHeight||600;
  rnd.setSize(w,h,false); cam.aspect=w/h; cam.updateProjectionMatrix();
}
addEventListener('resize',resize);

function build(M){
  const pos=[], col=[], c=new THREE.Color();
  for(const t of M.f){
    for(const i of t){
      const v=M.v[i];
      pos.push(v[0], v[2], v[1]);            // 曲面的"瓣轴"是原 z ⇒ 摆到 three 的 y
      c.setHex(COL[M.s[i] % 5]); col.push(c.r,c.g,c.b);
    }
  }
  const g=new THREE.BufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));
  g.setAttribute('color',new THREE.Float32BufferAttribute(col,3));
  g.computeVertexNormals();
  const mat=new THREE.MeshStandardMaterial({vertexColors:true, metalness:0.22, roughness:0.46,
        side:THREE.DoubleSide, flatShading:true});
  mesh=new THREE.Mesh(g,mat); grp.add(mesh);
  tris=(pos.length/9)|0;
  document.getElementById('deriv').textContent=M.meta.genus_derivation;
  document.getElementById('resid').textContent='max|…| = '+M.meta.resid_max.toExponential(1);
  document.getElementById('legend').innerHTML=[0,1,2,3,4].map(function(k){
    return '<div class="lg"><span class="dot" style="background:#'+COL[k].toString(16).padStart(6,'0')+
           '"></span>分支 '+k+' · ω<sup>'+k+'</sup>(1−x⁵)<sup>1/5</sup></div>';
  }).join('');
  window.__cyReady=true;
  resize();
}

fetch('/slice.json').then(r=>r.json()).then(build).catch(function(e){
  document.getElementById('hud').textContent='载入失败: '+e;
});

function loop(){
  requestAnimationFrame(loop);
  grp.rotation.set(pitch,yaw,0);
  cam.position.z=8.6/zoom;
  rnd.render(scene,cam);
  if(mesh){
    document.getElementById('hud').innerHTML =
      'yaw <b>'+(yaw*57.3).toFixed(0)+'°</b> · pitch <b>'+(pitch*57.3).toFixed(0)+'°</b> · zoom <b>'+
      zoom.toFixed(2)+'×</b> · <b>'+tris+'</b> 面\n亏格 <b>g = 6</b> ⇒ 六个孔洞 · 五瓣在 |x|=1 的 5 个分歧点相接';
  }
}
loop();

stage.addEventListener('mousedown',function(e){drag=true;px=e.clientX;py=e.clientY;});
addEventListener('mouseup',function(){drag=false;});
addEventListener('mousemove',function(e){ if(!drag) return;
  yaw+=(e.clientX-px)*0.0075;
  pitch=Math.max(-1.45,Math.min(1.45,pitch+(e.clientY-py)*0.0075));
  px=e.clientX;py=e.clientY;});
stage.addEventListener('wheel',function(e){e.preventDefault();
  zoom=Math.max(.4,Math.min(4.5,zoom*(e.deltaY>0?.92:1.08)));},{passive:false});
addEventListener('keydown',function(e){var k=e.key.toLowerCase();
  if(k==='w'&&mesh){wire=!wire;mesh.material.wireframe=wire;}
  if(k==='r'){yaw=-0.62;pitch=0.28;zoom=1.45;}});

// 🧾 页脚版本/uptime (真源 VERSION.md, 服务端热读) + 📇 本机服务探活
function foot(){
  fetch('/health').then(function(r){return r.json();}).then(function(h){
    document.getElementById('ft').textContent =
      'Z-MAX v' + h.version + ' · 8810 六维CY切面 · up ' + h.uptime_s + 's · 亏格 g=6 · ' +
      h.tris + ' 面 · 只读可视化, 不下发任何动作';
  }).catch(function(){});
}
foot(); setInterval(foot, 30000);
function svc(){
  fetch('/services.json').then(function(r){return r.json();}).then(function(d){
    var el=document.getElementById('svc');
    el.innerHTML = d.items.map(function(it){
      var dot = it.up ? '<b style="color:#7bdcb5">●</b>' : '<b style="color:#e06c75">○</b>';
      return '<div class="kv"><i>'+dot+' '+it.port+'</i><b style="font-size:12px">'+it.name+'</b></div>';
    }).join('');
  }).catch(function(){});
}
svc(); setInterval(svc, 5000);

setInterval(function(){fetch('/live.json').then(function(r){return r.json();}).then(function(d){
  var el=document.getElementById('live');
  if(!d.ok){el.className='mono bad';el.textContent='无现场值: '+(d.err||'mani10_live.json 未生成');return;}
  el.className='mono';
  var h=d.hidden6||[], nm=['f_x','f_y','f_z','σ_n','σ_t','c'], mx=[60,60,60,1,1,1];
  if(h.length!==6){el.textContent='隐藏 6 维缺失';return;}
  el.innerHTML = h.map(function(v,i){
    return '<div class="kv"><i>'+nm[i]+'</i><b>'+v.toFixed(3)+'</b></div><div class="bar"><div style="width:'+
           Math.min(100,Math.abs(v)/mx[i]*100).toFixed(0)+'%"></div></div>';
  }).join('') +
  '<div class="kv"><i>gate</i><b>'+(d.gate?('force '+(d.gate.force_ok?'✓':'✗')+' · conf '+(d.gate.conf_ok?'✓':'✗')):'—')+'</b></div>'+
  '<div class="kv"><i>帧龄</i><b>'+d.age_s+'s</b></div>';
}).catch(function(){});},2000);
</script></body></html>
"""


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):                                        # 静音
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:                                                  # noqa: BLE001
            pass

    def do_GET(self):                                                      # noqa: N802
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if p == "/slice.json":
            return self._send(json.dumps(mesh_payload()).encode(), "application/json")
        if p == "/slice.obj":
            return self._send(obj_payload().encode(), "text/plain; charset=utf-8")
        if p == "/live.json":
            return self._send(json.dumps(live_payload(), ensure_ascii=False).encode(),
                              "application/json")
        if p == "/three.module.js":
            try:
                return self._send(open(THREE_JS, "rb").read(), "text/javascript; charset=utf-8")
            except Exception:                                              # noqa: BLE001
                return self._send(b"// three.js missing", "text/javascript", 404)
        if p == "/version.json":
            return self._send(json.dumps(version_now(), ensure_ascii=False).encode(),
                              "application/json")
        if p == "/services.json":
            return self._send(json.dumps(services_payload(), ensure_ascii=False).encode(),
                              "application/json")
        if p == "/health":
            m = mesh_payload()
            v = version_now()
            return self._send(json.dumps({
                "ok": True, "service": "zmax-cy-slice", "port": PORT,
                "version": v.get("version"), "tag": v.get("tag"),
                "uptime_s": round(time.time() - START_TS, 1),
                "genus": m["meta"]["genus"], "verts": len(m["v"]), "tris": len(m["f"]),
                "resid_max": m["meta"]["resid_max"], "ts": time.time()},
                ensure_ascii=False).encode(), "application/json")
        return self._send(b'{"ok":false,"err":"not found"}', "application/json", 404)


def main():
    mesh_payload()                                                         # 预生成
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("CY slice server → http://0.0.0.0:%d/  (g=%d, %d 面)"
          % (PORT, mesh_payload()["meta"]["genus"], len(mesh_payload()["f"])), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
