#!/usr/bin/env python3
"""跟随真实机器人: 实时学习新轨迹 + 映射到五流形 (A 位置 / B 轴 S² / C 四元数 S³ / D 滚转 S¹ / E 相位)。

与 8815 那套的区别: 8815 是**已知 215 点轨迹**的看板(相位靠投影已知轨迹);
这里是**未知新轨迹**, 一边跟着走一边把路径学出来 ——
  · 学习期 (open):  E = 本次已走弧长占比 (实时进度), 页面标"学习进度", 不冒充闭环相位
  · 闭环后 (closed): 首尾 ≤30mm 且总长 ≥500mm ⇒ 判定成回路, E = 累计弧长/闭环总长 (真相位)
只读真值, 不下发任何动作。

HTTP (默认 8817):
  GET /healthz      存活 + 帧龄
  GET /api/follow   A/B/C/D/E + 路线统计 (页面与外部都用这个)
  GET /follow       五视图页面
  POST /api/follow/reset   清空重学 (换一条新轨迹时用)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "zmax_data", "se3_follow")
TRUTH = os.environ.get("ZMAX_FOLLOW_TRUTH", "http://127.0.0.1:8797/api/tcp")
MIN_STEP_MM = float(os.environ.get("ZMAX_FOLLOW_MIN_STEP_MM", "2.0"))     # 小于此不记点(防抖)
CLOSE_MM = float(os.environ.get("ZMAX_FOLLOW_CLOSE_MM", "30"))            # 首尾距离阈值
MIN_LOOP_MM = float(os.environ.get("ZMAX_FOLLOW_MIN_LOOP_MM", "500"))
RETRACE_MM = float(os.environ.get("ZMAX_FOLLOW_RETRACE_MM", "25"))   # 回程贴在去程上 <25mm ⇒ 判"往返"不是"闭环"


def _seg_dist(p, a, b):
    """点到线段距离 (mm)"""
    ax, ay, az = a
    vx, vy, vz = b[0] - ax, b[1] - ay, b[2] - az
    wx, wy, wz = p[0] - ax, p[1] - ay, p[2] - az
    vv = vx * vx + vy * vy + vz * vz
    t = 0.0 if vv <= 1e-12 else max(0.0, min(1.0, (wx * vx + wy * vy + wz * vz) / vv))
    return math.dist(p, (ax + vx * t, ay + vy * t, az + vz * t))


def _retrace_mm(path):
    """回程贴合度: 后半段每点到底半段折线的最近距离中位数。
    ~0mm ⇒ 原路返回(往返, 不是闭环); 几十 mm 以上 ⇒ 真环路。"""
    n = len(path)
    if n < 20:
        return None
    half = n // 2
    seg = [q["A_mm"] for q in path[:half + 1]]
    if len(seg) < 2:
        return None
    ds = sorted(min(_seg_dist(q["A_mm"], seg[i], seg[i + 1]) for i in range(len(seg) - 1))
                for q in path[half:])
    return ds[len(ds) // 2]
MAX_JUMP_MM = float(os.environ.get("ZMAX_FOLLOW_MAX_JUMP_MM", "300"))   # 单次跳变闸 (真机 20Hz 下最大 ~50mm)
STALE_S = float(os.environ.get("ZMAX_FOLLOW_STALE_S", "5"))             # 真值帧龄超这个就不记点 (控制器重启期)

S = {
    "path": [],            # [{i, A_mm, B, C, D, j, t}]
    "cum": 0.0,            # 累计弧长 mm
    "closed": False,
    "last": None,          # 最近一次真值换算结果
    "ts0": 0.0,
    "n_truth": 0,
    "err": "",
}


def _get(url: str, timeout: float = 1.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def hopf(q):
    """四元数 (qx,qy,qz,qw) → 轴 n (S²) 与滚转 φ (S¹)。与 se3_hopf 同式。"""
    x, y, z, w = q
    nn = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / nn, y / nn, z / nn, w / nn
    n = (2 * (x * z + w * y), 2 * (y * z - w * x), w * w + z * z - x * x - y * y)
    ln = math.sqrt(sum(v * v for v in n)) or 1.0
    n = tuple(v / ln for v in n)
    phi = (2.0 * math.atan2(z, w)) % (2 * math.pi)
    theta = 2.0 * math.degrees(math.acos(max(-1.0, min(1.0, abs(w)))))
    return n, phi, theta


def step() -> None:
    try:
        d = _get(TRUTH)
    except Exception as e:                                                    # noqa: BLE001
        S["err"] = "真值读取失败: %s" % str(e)[:80]
        return
    if not d.get("ok"):
        S["err"] = "真值不可用"
        return
    age = d.get("age_s")
    if age is not None and float(age) > STALE_S:
        # 控制器重启/真值断流期间: 文件还在但冻住了。不许把它当实时记点(实测帧龄 85s 时仍照算)
        S["err"] = "真值陈旧 %.1fs (重启中?) — 不记点" % float(age)
        S["stale_s"] = round(float(age), 1)
        return
    S["stale_s"] = round(float(age), 1) if age is not None else None
    S["err"] = ""
    S["n_truth"] += 1
    p = [float(d["x"]) * 1000.0, float(d["y"]) * 1000.0, float(d["z"]) * 1000.0]
    q = [float(v) for v in (d.get("quat") or [0, 0, 0, 1])]
    n, phi, theta = hopf(q)
    rec = {"A_mm": [round(v, 2) for v in p], "B": [round(v, 6) for v in n],
           "C_q": [round(v, 6) for v in q], "C_theta_deg": round(theta, 3),
           "D_phi_deg": round(math.degrees(phi), 3),
           "j": d.get("joints"), "t": time.time(), "age_s": d.get("age_s")}
    S["last"] = rec
    path = S["path"]
    # 真值断流后恢复 ⇒ 重新锚定, 不把"重启期间臂被搬走"的距离算成跳变/弧长
    gap = S.get("t_last_ok") and (rec["t"] - S["t_last_ok"] > STALE_S * 2)
    S["t_last_ok"] = rec["t"]
    if not path:
        rec.update({"i": 0})
        path.append(rec)
        S["ts0"] = rec["t"]
    else:
        prev = path[-1]
        dm = math.dist(prev["A_mm"], rec["A_mm"])
        if gap:
            S["gaps"] = S.get("gaps", 0) + 1
            S["last_gap_mm"] = round(dm, 1)
            path.append({"i": len(path), "A_mm": rec["A_mm"], "B": rec["B"], "C_q": rec["C_q"],
                         "C_theta_deg": rec["C_theta_deg"], "D_phi_deg": rec["D_phi_deg"],
                         "t": rec["t"], "gap_mm": round(dm, 1), "reanchor": True})
            S["reanchor"] = True
        elif dm > MAX_JUMP_MM:
            # 真值源换台/单位错/臂被搬走 ⇒ 不许把这段距离算进弧长 (实测会算出 660 km)
            S["jumps"] = S.get("jumps", 0) + 1
            S["last_jump_mm"] = round(dm, 1)
            S["err"] = "跳变 %.0f mm 已丢弃(真值源换了或单位不对)" % dm
            path.append({"i": len(path), "A_mm": rec["A_mm"], "B": rec["B"], "C_q": rec["C_q"],
                         "C_theta_deg": rec["C_theta_deg"], "D_phi_deg": rec["D_phi_deg"],
                         "t": rec["t"], "gap_mm": round(dm, 1)})
            S["reanchor"] = True
        elif dm >= MIN_STEP_MM:
            S["cum"] += dm
            rec.update({"i": len(path), "d_mm": round(dm, 2)})
            path.append(rec)
            # 闭环判定: 走够长 + 回到起点附近
            if (not S["closed"] and S["cum"] >= MIN_LOOP_MM
                    and math.dist(path[0]["A_mm"], rec["A_mm"]) <= CLOSE_MM):
                S["closed"] = True
                S["L_closed"] = S["cum"]
                # 🔴 2026-11-19 实测踩坑: 从插口退出来一路开回起点, 首尾也 ≤30mm ⇒ 被判"闭环 s=0",
                #   其实这是**往返**(去程+原路返回), 不是环路。区别看回程有没有贴在去程上。
                r = _retrace_mm(path)
                S["retrace_mm"] = None if r is None else round(r, 1)
                S["shape"] = "retrace" if (r is not None and r < RETRACE_MM) else "loop"
    # 相位: 闭环用真相位, 否则只报学习进度 (不许冒充 s)
    if S["closed"] and S.get("shape") == "retrace":
        # 往返: 去程 0→1, 回程 1→0 (三角波), 不冒充环路相位
        L = S.get("L_closed") or S["cum"]
        p_ = max(0.0, min(1.0, S["cum"] / L))
        s = p_ * 2.0 if p_ <= 0.5 else 2.0 - p_ * 2.0
        S["E"] = {"mode": "retrace", "s": round(s, 4), "p": round(p_, 4),
                  "s_mm": round(s * L / 2.0, 1), "cum_mm": round(S["cum"], 1),
                  "L_mm": round(L, 1), "retrace_mm": S.get("retrace_mm"),
                  "label": "行程相位 (往返 0→1→0, 非闭环)"}
    elif S["closed"]:
        L = S.get("L_closed") or S["cum"]
        # S¹ 是环: 走第二圈以后要取模, 不许出现 s>1 (实测连走 1.8 圈报出 1.8344)
        laps = int(S["cum"] // L)
        S["E"] = {"mode": "closed", "s": round((S["cum"] % L) / L, 4),
                  "s_mm": round(S["cum"] % L, 1), "cum_mm": round(S["cum"], 1),
                  "L_mm": round(L, 1), "laps": laps, "retrace_mm": S.get("retrace_mm"),
                  "label": "相位 s (闭环, 0→1 循环)"}
    else:
        S["E"] = {"mode": "learning", "s": None, "cum_mm": round(S["cum"], 1),
                  "label": "学习进度 (未闭环, 不报 s)"}
    if S["path"]:
        _save_json(os.path.join(OUT, "session.json"),
                   {"n": len(S["path"]), "cum_mm": round(S["cum"], 2), "closed": S["closed"],
                    "shape": S.get("shape"), "retrace_mm": S.get("retrace_mm"), "path": S["path"]},
                   bak=True)
        _save_json(os.path.join(OUT, "snapshot.json"),
                   {"ts": rec["t"], "A_mm": rec["A_mm"], "B": rec["B"], "C_q": rec["C_q"],
                    "C_theta_deg": rec["C_theta_deg"], "D_phi_deg": rec["D_phi_deg"],
                    "E": S["E"], "age_s": rec["age_s"], "n": len(S["path"])})


def loop(rate: float) -> None:
    dt = 1.0 / max(1.0, rate)
    while True:
        t0 = time.time()
        step()
        time.sleep(max(0.0, dt - (time.time() - t0)))


def api() -> dict:
    last = S["last"] or {}
    path = S["path"]
    out = {
        "ok": bool(last) and not S["err"],
        "err": S["err"],
        "truth_src": TRUTH,
        "age_s": last.get("age_s"),
        "n_truth": S["n_truth"],
        "A": {"mm": last.get("A_mm"), "view": "位置 ∈ ℝ³ (右图: 已学路径 + 当前点)"},
        "B": {"n": last.get("B"), "norm": round(math.sqrt(sum(v * v for v in (last.get("B") or [0, 0, 0]))), 6),
              "view": "接近轴 ∈ S² (右图: 球面点 + 从球心射出的箭头)"},
        "C": {"q": last.get("C_q"), "theta_deg": last.get("C_theta_deg"),
              "view": "姿态 ∈ S³ (右图: 转角 θ 与四元数分量)"},
        "D": {"phi_deg": last.get("D_phi_deg"), "view": "滚转 ∈ S¹ (右图: 表盘 + 弧)"},
        "E": S.get("E") or {"mode": "learning", "s": None, "cum_mm": 0.0,
                            "label": "学习进度 (未闭环, 不报 s)"},
        "route": {"n_pts": len(path), "cum_mm": round(S["cum"], 1), "closed": S["closed"],
                  "shape": S.get("shape"), "retrace_mm": S.get("retrace_mm"),
                  "jumps": S.get("jumps", 0), "last_jump_mm": S.get("last_jump_mm"),
                  "span_mm": ([round(max(p["A_mm"][k] for p in path) - min(p["A_mm"][k] for p in path), 1)
                               for k in range(3)] if len(path) > 1 else [0, 0, 0]),
                  "t_s": round((path[-1]["t"] - path[0]["t"]), 1) if len(path) > 1 else 0.0},
        "ts": time.time(),
    }
    return out


PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>跟随真机 · 五流形 A~E</title>
<style>
:root{--bg:#0b0f14;--fg:#e8eef6;--dim:#8aa0b8;--a:#37d0ff;--b:#9fe8ff;--c:#b39dff;--d:#ffd166;--e:#3ddc84}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,"Noto Sans SC",sans-serif}
header{padding:10px 16px;border-bottom:1px solid #1c2733;display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}#st{color:var(--dim);font-size:13px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px}
.card{background:#0f1620;border:1px solid #1c2733;border-radius:10px;padding:8px 10px}
.card h2{font-size:13px;margin:0 0 6px;color:var(--dim);font-weight:600}
.card h2 b{color:var(--fg)}canvas{width:100%;display:block;border-radius:6px;background:#0a1017}
.num{font-variant-numeric:tabular-nums;font-size:12px;color:var(--dim);margin-top:4px;min-height:18px}
</style></head><body>
<header><h1>跟随真机 · A B C D E 五流形</h1><span id="st">连接中…</span></header>
<div class="grid">
 <div class="card"><h2><b>A</b> 位置 ∈ ℝ³ · 已学路径</h2><canvas id="ca" height="300"></canvas><div class="num" id="na"></div></div>
 <div class="card"><h2><b>B</b> 接近轴 n ∈ S²</h2><canvas id="cb" height="300"></canvas><div class="num" id="nb"></div></div>
 <div class="card"><h2><b>C</b> 姿态 ∈ S³ · 转角 θ</h2><canvas id="cc" height="300"></canvas><div class="num" id="nc"></div></div>
 <div class="card"><h2><b>D</b> 滚转 φ ∈ S¹</h2><canvas id="cd" height="300"></canvas><div class="num" id="nd"></div></div>
 <div class="card" style="grid-column:1/3"><h2><b>E</b> 相位 / 学习进度</h2><canvas id="ce" height="220"></canvas><div class="num" id="ne"></div></div>
</div>
<script>
const F=(v,n=1)=>Array.isArray(v)?v.map(x=>x.toFixed(n)).join(' / '):(v==null?'—':v);
function ctx(id){const c=document.getElementById(id);const d=devicePixelRatio||1;const w=c.clientWidth||600;c.width=w*d;c.height=c.height*d||300;const x=c.getContext('2d');x.setTransform(d,0,0,d,0,0);return [x,w,c.height/d];}
let PATH=[],LAST=null,E=null;
function drawA(){const [g,w,h]=ctx('ca');g.clearRect(0,0,w,h);
 if(!PATH.length){g.fillStyle='#8aa0b8';g.font='13px sans-serif';g.fillText('等待真值…',12,24);return;}
 const xs=PATH.map(p=>p[0]),ys=PATH.map(p=>p[1]),zs=PATH.map(p=>p[2]);
 const mn=[Math.min(...xs),Math.min(...ys),Math.min(...zs)],mx=[Math.max(...xs),Math.max(...ys),Math.max(...zs)];
 const sp=mx.map((v,i)=>Math.max(1,v-mn[i]));
 // 俯视 (x-y) 为主, z 用亮度表示
 const sx=v=>(v-mn[0])/sp[0]*(w-40)+20, sy=v=>h-20-(v-mn[1])/sp[1]*(h-40);
 g.strokeStyle='#37d0ff';g.lineWidth=1.6;g.beginPath();
 PATH.forEach((p,i)=>{i?g.lineTo(sx(p[0]),sy(p[1])):g.moveTo(sx(p[0]),sy(p[1]))});g.stroke();
 PATH.forEach((p,i)=>{const z=(p[2]-mn[2])/sp[2];g.fillStyle=`rgba(55,208,255,${0.15+0.75*z})`;g.fillRect(sx(p[0])-1,sy(p[1])-1,2,2);});
 if(LAST){g.fillStyle='#3ddc84';g.beginPath();g.arc(sx(LAST[0]),sy(LAST[1]),5,0,7);g.fill();
  g.strokeStyle='#3ddc84';g.lineWidth=1;g.beginPath();g.arc(sx(LAST[0]),sy(LAST[1]),9,0,7);g.stroke();}
 g.fillStyle='#8aa0b8';g.font='12px sans-serif';
 g.fillText(`跨距 ${sp.map(v=>v.toFixed(0)).join('×')} mm · 点 ${PATH.length}`,10,16);
}
function drawB(){const [g,w,h]=ctx('cb');g.clearRect(0,0,w,h);
 const cx=w/2,cy=h/2,R=Math.min(w,h)*0.36;
 g.strokeStyle='#1c2733';g.lineWidth=1;g.beginPath();g.arc(cx,cy,R,0,7);g.stroke();
 g.strokeStyle='#16202b';g.beginPath();g.ellipse(cx,cy,R,R*0.32,0,0,7);g.stroke();
 if(!LAST)return;const n=LAST;
 const px=cx+R*n[0],py=cy-R*n[2];
 g.strokeStyle='#9fe8ff';g.lineWidth=2;g.beginPath();g.moveTo(cx,cy);g.lineTo(px,py);g.stroke();
 g.fillStyle='#9fe8ff';g.beginPath();g.arc(px,py,6,0,7);g.fill();
 g.fillStyle='#8aa0b8';g.font='12px sans-serif';g.fillText('球心 → 轴方向',10,16);
}
function drawC(){const [g,w,h]=ctx('cc');g.clearRect(0,0,w,h);
 if(!LAST)return;const th=LAST[1];
 const cx=w/2,cy=h/2+10,R=Math.min(w,h)*0.32;
 g.strokeStyle='#1c2733';g.lineWidth=10;g.beginPath();g.arc(cx,cy,R,Math.PI,2*Math.PI);g.stroke();
 const f=Math.min(1,th/180);
 g.strokeStyle='#b39dff';g.lineWidth=10;g.beginPath();g.arc(cx,cy,R,Math.PI,Math.PI+Math.PI*f);g.stroke();
 g.fillStyle='#e8eef6';g.font='600 24px sans-serif';g.textAlign='center';g.fillText(th.toFixed(1)+'°',cx,cy);
 g.textAlign='left';g.fillStyle='#8aa0b8';g.font='12px sans-serif';g.fillText('四元数角 (S³)',10,16);
}
function drawD(){const [g,w,h]=ctx('cd');g.clearRect(0,0,w,h);
 if(!LAST)return;const ph=LAST[2]*Math.PI/180;
 const cx=w/2,cy=h/2,R=Math.min(w,h)*0.34;
 g.strokeStyle='#1c2733';g.lineWidth=1;g.beginPath();g.arc(cx,cy,R,0,7);g.stroke();
 for(let k=0;k<12;k++){const a=k*Math.PI/6;g.strokeStyle=k%3?'#16202b':'#2a3a4c';g.beginPath();
  g.moveTo(cx+Math.cos(a)*R,cy+Math.sin(a)*R);g.lineTo(cx+Math.cos(a)*(R+6),cy+Math.sin(a)*(R+6));g.stroke();}
 g.strokeStyle='#ffd166';g.lineWidth=3;g.beginPath();g.moveTo(cx,cy);
 g.lineTo(cx+Math.cos(ph)*R*0.92,cy+Math.sin(ph)*R*0.92);g.stroke();
 g.fillStyle='#ffd166';g.beginPath();g.arc(cx,cy,5,0,7);g.fill();
 g.fillStyle='#8aa0b8';g.font='12px sans-serif';g.fillText('滚转 φ (S¹)',10,16);
}
function drawE(){const [g,w,h]=ctx('ce');g.clearRect(0,0,w,h);
 const cx=w/2,cy=h/2+6,R=Math.min(w*0.22,h*0.40);
 const closed=E&&E.mode==='closed';const val=closed?(E.s||0):(E?Math.min(1,(E.cum_mm||0)/2000):0);
 g.strokeStyle='#1c2733';g.lineWidth=16;g.beginPath();g.arc(cx,cy,R,0,7);g.stroke();
 g.strokeStyle=closed?'#3ddc84':'#f5a623';g.lineWidth=16;g.lineCap='round';
 g.beginPath();g.arc(cx,cy,R,-Math.PI/2,-Math.PI/2+2*Math.PI*val);g.stroke();
 g.fillStyle='#e8eef6';g.font='600 20px sans-serif';g.textAlign='center';
 g.fillText(closed?(val*100).toFixed(1)+'%':`${(E.cum_mm||0).toFixed(0)} mm`,cx,cy);
 g.textAlign='left';g.fillStyle='#8aa0b8';g.font='13px sans-serif';
 g.fillText(closed?'相位 s (闭环, 0→1)':'学习进度 (未闭环 ⇒ 不报 s)',cx-R-40,cy+R+34);
}
async function tick(){
 try{
  const r=await fetch('api/follow',{cache:'no-store'});const d=await r.json();
  const st=document.getElementById('st');
  st.textContent = d.ok? `真值龄 ${(d.age_s??0).toFixed(2)}s · 点 ${d.route.n_pts} · 弧长 ${d.route.cum_mm} mm · ${d.route.closed?'已闭环':'学习中'}`
                      : `未就绪: ${d.err||'—'}`;
  if(d.A.mm){LAST=[...d.A.mm, d.B.n, d.C.theta_deg, d.D.phi_deg];}
  E=d.E;
  document.getElementById('na').textContent = d.A.mm? `TCP ${F(d.A.mm)} mm` : '';
  document.getElementById('nb').textContent = d.B.n? `n ${F(d.B.n,3)} · |n|=${d.B.norm}` : '';
  document.getElementById('nc').textContent = d.C.q? `θ ${d.C.theta_deg}° · q ${F(d.C.q,3)}` : '';
  document.getElementById('nd').textContent = d.D.phi_deg!=null? `φ ${d.D.phi_deg}°` : '';
  document.getElementById('ne').textContent = d.E? `${d.E.label} · 弧长 ${d.route.cum_mm} mm` : '';
  // 路径 (抽稀到 ≤600 点画)
  const s=await fetch('session.json',{cache:'no-store'}).then(x=>x.json()).catch(()=>null);
  if(s&&s.path){const step=Math.max(1,Math.ceil(s.path.length/600));
    PATH=s.path.filter((_,i)=>i%step===0).map(p=>p.A_mm);}
  drawA();drawB();drawC();drawD();drawE();
 }catch(e){document.getElementById('st').textContent='连接失败: '+e.message;}
 setTimeout(tick,400);
}
tick();
addEventListener('resize',()=>{});
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _s(self, code, body, ct="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):          # 直接给 dict 时自动序列化 (否则 Content-Length 会变成键数)
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/healthz":
            return self._s(200, {"ok": True, "age_s": (S["last"] or {}).get("age_s"),
                                 "n_pts": len(S["path"]), "err": S["err"]})
        if p == "/api/follow":
            return self._s(200, api())
        if p == "/follow":
            return self._s(200, PAGE, "text/html; charset=utf-8")
        if p == "/session.json":
            fp = os.path.join(OUT, "session.json")
            if os.path.exists(fp):
                return self._s(200, open(fp, "rb").read())
            return self._s(404, {"error": "no session"})
        return self._s(404, {"error": "no route", "path": p})

    def do_POST(self):
        p = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        if p == "/api/follow/reset":
            S.update({"path": [], "cum": 0.0, "closed": False, "last": None, "ts0": 0.0})
            return self._s(200, {"ok": True, "msg": "已清空, 开始学新轨迹"})
        return self._s(404, {"error": "no route", "path": p})


def _save_json(path: str, obj, bak: bool = False) -> None:
    """原子写 (tmp + os.replace) —— 非原子写实测会在 systemctl restart 撞上写一半,
    留下 0 字节 session.json, 重启后 load 失败, 161 点白学。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    if bak:
        try:
            shutil.copyfile(path, path.replace(".json", ".bak.json"))
        except Exception:                                                    # noqa: BLE001
            pass


def load_session() -> bool:
    """重启后接着用已学路径 (老倪 2026-11-19「全部重启」): 有 session.json 就读回来,
    省得每次重启都把走过的路丢掉。closed 的 old session 顺手补齐 shape(环路/往返)。"""
    fp = os.path.join(OUT, "session.json")
    for cand in (fp, fp.replace(".json", ".bak.json")):
        if not os.path.exists(cand):
            continue
        try:
            d = json.load(open(cand, encoding="utf-8"))
            if len(d.get("path") or []) >= 2:
                print("[load] 源文件 %s" % os.path.basename(cand), flush=True)
                break
        except Exception:                                                    # noqa: BLE001
            continue
    else:
        return False
    try:
        path = d.get("path") or []
        if len(path) < 2:
            return False
        S.update({"path": path, "cum": float(d.get("cum_mm") or 0.0),
                  "closed": bool(d.get("closed"))})
        seg = 0.0
        for a, b in zip(path, path[1:]):
            dd = math.dist(a["A_mm"], b["A_mm"])
            if dd <= MAX_JUMP_MM:
                seg += dd
        S["cum"] = seg
        if S["closed"]:
            S["L_closed"] = S["cum"]
            r = _retrace_mm(path)
            S["retrace_mm"] = None if r is None else round(r, 1)
            S["shape"] = "retrace" if (r is not None and r < RETRACE_MM) else "loop"
        S["last"] = path[-1]
        print("[load] 接上已有会话: %d 点 · 弧长 %.1f mm · closed=%s · shape=%s · retrace=%s" % (
            len(path), S["cum"], S["closed"], S.get("shape"), S.get("retrace_mm")), flush=True)
        return True
    except Exception as e:                                                   # noqa: BLE001
        print("[load] 读 session.json 失败:", str(e)[:80], flush=True)
        return False


def import_traj(path: str) -> dict:
    """把一份已录轨迹 (real_traj_joints 口径: frames[{p(m),q,j,t}]) 灌进本次会话, 算弧长/闭环/相位。"""
    d = json.load(open(path, encoding="utf-8"))
    fr = d.get("frames") or d.get("path") or []
    S.update({"path": [], "cum": 0.0, "closed": False, "last": None, "ts0": 0.0, "jumps": 0})
    prev = None
    for i, f in enumerate(fr):
        A = [float(v) * 1000.0 for v in f["p"]]
        q = [float(v) for v in f["q"]]
        n, phi, theta = hopf(q)
        rec = {"i": i, "A_mm": [round(v, 2) for v in A], "B": [round(v, 6) for v in n],
               "C_q": [round(v, 6) for v in q], "C_theta_deg": round(theta, 3),
               "D_phi_deg": round(math.degrees(phi), 3),
               "j": f.get("j"), "t": float(f.get("t") or i)}
        if prev is not None:
            dm = math.dist(prev["A_mm"], rec["A_mm"])
            if dm <= MAX_JUMP_MM:
                S["cum"] += dm
                rec["d_mm"] = round(dm, 2)
        prev = rec
        S["path"].append(rec)
    S["last"] = S["path"][-1] if S["path"] else None
    if len(S["path"]) > 1 and S["cum"] >= MIN_LOOP_MM and math.dist(
            S["path"][0]["A_mm"], S["path"][-1]["A_mm"]) <= CLOSE_MM:
        S["closed"] = True
        S["L_closed"] = S["cum"]
        S["E"] = {"mode": "closed", "s": round((S["cum"] % S["L_closed"]) / S["L_closed"], 4),
                  "s_mm": round(S["cum"] % S["L_closed"], 1), "cum_mm": round(S["cum"], 1),
                  "L_mm": round(S["L_closed"], 1), "laps": int(S["cum"] // S["L_closed"]),
                  "label": "相位 s (闭环, 0→1 循环)"}
    os.makedirs(OUT, exist_ok=True)
    json.dump({"n": len(S["path"]), "cum_mm": round(S["cum"], 2), "closed": S["closed"],
               "src": os.path.abspath(path), "path": S["path"]},
              open(os.path.join(OUT, "session.json"), "w"), ensure_ascii=False)
    return {"n": len(S["path"]), "cum_mm": round(S["cum"], 1), "closed": S["closed"],
            "L_mm": round(S.get("L_closed") or 0, 1), "E": S.get("E")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--import", dest="imp", help="灌入一份已录轨迹 (real_traj_joints 口径) 后继续服务")
    ap.add_argument("--port", type=int, default=8817)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--rate", type=float, default=20.0)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if not a.imp and "--fresh" not in os.environ.get("ZMAX_FOLLOW_FLAGS", ""):
        load_session()
    if a.imp:
        print("[import]", json.dumps(import_traj(a.imp), ensure_ascii=False), flush=True)
    if not a.imp or "--follow-live" in os.environ.get("ZMAX_FOLLOW_FLAGS", ""):
        threading.Thread(target=loop, args=(a.rate,), daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print("[follow] http://%s:%d/follow  (truth=%s, rate=%.0fHz)" % (a.host, a.port, TRUTH, a.rate), flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
