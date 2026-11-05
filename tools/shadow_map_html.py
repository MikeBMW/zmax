#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🗺 影子模式建图 → 单文件 3D HTML (数据内联, 手机可开)。
输入: 影子会话目录 (poses.jsonl + map.json + summary.json)
输出: <session>/shadow_3d.html
说明: 显示的是**真机 TCP 轨迹 + 工作空间覆盖栅格** (base_link, 米), 全部来自只读真值,
      不是示意图; 无深度 ⇒ 不画点云, 不编造 3D 结构。
"""
import json, math, os, sys

def load_poses(p):
    out = []
    for line in open(p, encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if "p" in d:                      # 离线覆盖图格式 {t, p:[x,y,z]}
            t = d["p"]
        else:
            t = d.get("tcp") or d.get("endInRef")
        if not t or len(t) < 3:
            continue
        out.append({"t": d.get("t"), "p": [float(t[0]), float(t[1]), float(t[2])]})
    return out

def main():
    sess = sys.argv[1] if len(sys.argv) > 1 else ""
    if not sess or not os.path.isdir(sess):
        print("用法: shadow_map_html.py <session_dir>"); return 2
    poses = load_poses(os.path.join(sess, "poses.jsonl"))
    mp = json.load(open(os.path.join(sess, "map.json"), encoding="utf-8"))
    sm = {}
    sp = os.path.join(sess, "summary.json")
    if os.path.exists(sp):
        sm = json.load(open(sp, encoding="utf-8"))
    cl = json.load(open(os.path.join(sess, "calib_live.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(sess, "calib_live.json")) else {}
    data = {"poses": poses, "cells": mp.get("cells", []), "cell": mp.get("cell_m", 0.02),
            "coverage": mp.get("coverage", {}), "calib": {k: cl.get(k) for k in
            ("pairs", "resid_old_deg_median", "resid_old_deg_p90", "status",
             "holdout_resid_new_deg", "delta_from_handeye_deg", "accepted")},
            "summary": {k: sm.get(k) for k in ("frames", "keyframes", "elapsed_s", "ended")}}
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    out = os.path.join(sess, "shadow_3d.html")
    open(out, "w", encoding="utf-8").write(html)
    print(json.dumps({"ok": True, "html": out, "poses": len(poses), "cells": len(data["cells"]),
                      "coverage": data["coverage"]}, ensure_ascii=False))
    return 0

TEMPLATE = r"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🔮 影子模式 · 真机建图 (base_link)</title>
<style>
html,body{margin:0;height:100%;background:#0b0f14;color:#d8e2ec;font:13px/1.5 -apple-system,"PingFang SC",sans-serif;overflow:hidden}
#c{position:fixed;inset:0}
#hud{position:fixed;left:10px;top:10px;background:rgba(12,18,26,.86);border:1px solid #1e2b3a;border-radius:10px;padding:10px 12px;max-width:min(92vw,420px);backdrop-filter:blur(6px)}
#hud b{color:#7ee0c0;font-weight:600}
#hud .k{color:#8ba0b4}
#hud .v{color:#e8f1fa;font-variant-numeric:tabular-nums}
table{border-collapse:collapse}
td{padding:1px 8px 1px 0;vertical-align:top}
#bar{position:fixed;right:10px;top:10px;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
button{background:#14202c;color:#cfe3f5;border:1px solid #26384a;border-radius:8px;padding:7px 10px;font-size:12px}
button.on{background:#1d4a3f;border-color:#2f7f68;color:#a9f0d8}
#err{position:fixed;inset:auto 10px 10px 10px;background:#3a1218;border:1px solid #7a2230;color:#ffb9c4;border-radius:10px;padding:10px;display:none;white-space:pre-wrap}
</style></head><body>
<canvas id="c"></canvas>
<div id="hud"></div>
<div id="bar">
<button id="bTraj" class="on">轨迹</button>
<button id="bCells" class="on">覆盖格</button>
<button id="bSpin" class="on">自动旋转</button>
<button id="bTop">俯视</button>
</div>
<div id="err"></div>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script>
const D = __DATA__;
function fail(m){const e=document.getElementById('err');e.style.display='block';e.textContent='渲染失败: '+m;}
try{
if(typeof THREE==='undefined') throw new Error('THREE 未加载 (无网络? 本页需 CDN 一次)');
const poses=D.poses, cells=D.cells, CS=D.cell||0.02;
const hud=document.getElementById('hud');
const cv=D.coverage||{}, cb=cv.bbox_m||[0,0,0,0,0,0];
function f(v,n=3){return (v===undefined||v===null)?'—':Number(v).toFixed(n);}
hud.innerHTML='<table>'+
'<tr><td class="k">样本/关键帧</td><td class="v">'+f(D.summary.frames,0)+' / '+f(D.summary.keyframes,0)+'</td></tr>'+
'<tr><td class="k">时长</td><td class="v">'+f(D.summary.elapsed_s,0)+' s</td></tr>'+
'<tr><td class="k">覆盖面积</td><td class="v">'+f(cv.area_m2,4)+' m² ('+f(cv.cells,0)+' 格)</td></tr>'+
'<tr><td class="k">TCP 范围</td><td class="v">x '+f(cb[0])+'~'+f(cb[3])+' · y '+f(cb[1])+'~'+f(cb[4])+'</td></tr>'+
'<tr><td class="k">z</td><td class="v">'+f(cv.z_range_m?cv.z_range_m[0]:null)+' ~ '+f(cv.z_range_m?cv.z_range_m[1]:null)+' m</td></tr>'+
'<tr><td class="k">手眼自证</td><td class="v">'+(D.calib.pairs||0)+' 对 · 残差中位 '+f(D.calib.resid_old_deg_median,2)+'° · '+ (D.calib.status||'waiting')+'</td></tr>'+
'</table><div style="color:#7f93a6;margin-top:6px;font-size:11px">影子模式: 只读 Orin 图像+位姿 · 零下行 · 数据=TCP 真值</div>';
const scene=new THREE.Scene(); scene.background=new THREE.Color(0x0b0f14);
const cam=new THREE.PerspectiveCamera(55,innerWidth/innerHeight,0.01,50);
const rnd=new THREE.WebGLRenderer({canvas:document.getElementById('c'),antialias:true});
rnd.setPixelRatio(Math.min(2,devicePixelRatio)); rnd.setSize(innerWidth,innerHeight);
const cx=(cb[0]+cb[3])/2, cy=(cb[1]+cb[4])/2;
const SPAN=Math.max(0.25,(Math.max(cb[3]-cb[0],cb[4]-cb[1]))*2.2);
cam.position.set(cx+SPAN*.75,cy-SPAN*.75,SPAN*.95); cam.lookAt(cx,cy,0.1);
scene.add(new THREE.AmbientLight(0x8899aa,1.1));
const dl=new THREE.DirectionalLight(0xffffff,1.0); dl.position.set(2,-2,3); scene.add(dl);
const grid=new THREE.GridHelper(0.6,30,0x1b2a3a,0x14202c); grid.position.set(cx,cy,0); grid.rotation.x=Math.PI/2; scene.add(grid);
// 覆盖格
const gCell=new THREE.Group(); scene.add(gCell);
const maxn=Math.max(1,...cells.map(c=>c.n));
cells.forEach(c=>{
  const g=new THREE.BoxGeometry(CS*.92,CS*.92,0.002);
  const col=new THREE.Color().setHSL(0.42,0.75,0.25+0.45*(c.n/maxn));
  const m=new THREE.Mesh(g,new THREE.MeshBasicMaterial({color:col,transparent:true,opacity:0.9}));
  m.position.set((c.i+0.5)*CS,(c.j+0.5)*CS,0.0); gCell.add(m);
});
// 轨迹 (时间渐变)
const gTraj=new THREE.Group(); scene.add(gTraj);
if(poses.length>1){
  const pts=poses.map(p=>new THREE.Vector3(p.p[0],p.p[1],p.p[2]));
  const geo=new THREE.BufferGeometry().setFromPoints(pts);
  geo.setAttribute('color',new THREE.Float32BufferAttribute(
    pts.flatMap((_,i)=>{const t=i/(pts.length-1);const c=new THREE.Color().setHSL(0.58-0.45*t,0.9,0.55);return [c.r,c.g,c.b];}),3));
  gTraj.add(new THREE.Line(geo,new THREE.LineBasicMaterial({vertexColors:true})));
  const s=new THREE.Mesh(new THREE.SphereGeometry(0.006,12,12),new THREE.MeshBasicMaterial({color:0x35e08a}));
  s.position.copy(pts[0]); gTraj.add(s);
  const e=new THREE.Mesh(new THREE.SphereGeometry(0.006,12,12),new THREE.MeshBasicMaterial({color:0xff6b8a}));
  e.position.copy(pts[pts.length-1]); gTraj.add(e);
}
document.getElementById('bTraj').onclick=e=>{gTraj.visible=!gTraj.visible;e.target.classList.toggle('on',gTraj.visible);};
document.getElementById('bCells').onclick=e=>{gCell.visible=!gCell.visible;e.target.classList.toggle('on',gCell.visible);};
let spin=true; document.getElementById('bSpin').onclick=e=>{spin=!spin;e.target.classList.toggle('on',spin);};
document.getElementById('bTop').onclick=()=>{cam.position.set(cx,cy,SPAN*1.25);cam.lookAt(cx,cy,0);};
let down=false,px=0,py=0;
rnd.domElement.addEventListener('pointerdown',e=>{down=true;px=e.clientX;py=e.clientY;});
addEventListener('pointerup',()=>down=false);
addEventListener('pointermove',e=>{if(!down)return;const dx=e.clientX-px,dy=e.clientY-py;px=e.clientX;py=e.clientY;
  const off=cam.position.clone().sub(new THREE.Vector3(cx,cy,0.1));
  const theta=Math.atan2(off.y,off.x)+dx*0.006, r=Math.hypot(off.x,off.y);
  const z=Math.max(0.02,off.z+dy*0.004);
  cam.position.set(cx+r*Math.cos(theta),cy+r*Math.sin(theta),z);cam.lookAt(cx,cy,0.1);});
addEventListener('resize',()=>{cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();rnd.setSize(innerWidth,innerHeight);});
let a=0;
(function loop(){requestAnimationFrame(loop);
  if(spin){a+=0.0035;const off=cam.position.clone().sub(new THREE.Vector3(cx,cy,0.1));
    const th=Math.atan2(off.y,off.x)+0.0035,r=Math.hypot(off.x,off.y);
    cam.position.set(cx+r*Math.cos(th),cy+r*Math.sin(th),off.z);cam.lookAt(cx,cy,0.1);}
  gCell.rotation.z=0; rnd.render(scene,cam);})();
}catch(e){fail(e.message);}
</script></body></html>"""

if __name__ == "__main__":
    sys.exit(main())
