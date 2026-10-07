#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sdk_motion_service.py — 本机 SDK 直连动作服务 (纯新增件: 新端口新页面, 老页面/老执行器一行不改)

口径(2026-10-07 老倪现场指令):
  · 「不要改变 orin 原来的任何服务。你可以直接调用SDK，但要独立实现」
  · 本服务只跟**本机**的 SDK 常驻代理(tools/rokae/sdk_agent.py, 跑在 docker 里)说话:
      写一行 JSON 进 FIFO → 代理执行 → 读回结果 JSON。全程不碰 Orin。
  · 授权只能从**命令行**给(tools/sdk_arm_auth.sh), 页面**只能看倒计时、不能自助授权**;
    便于撤销(POST /revoke 永远允许)。
  · 每步动作都留证: ~/zmax/zmax_data/sdk_arm_audit.jsonl + ~/zmax/zmax_data/rokae_sdk/logs/sdk_ctl_*.json

路由:
  GET  /            极简点动页(手机可用): 授权倒计时/实时位姿/方向按钮/步长/速度/停止/复位/日志
  GET  /state       JSON: 授权 + 心跳(电源/状态/位姿/采样器龄/报警)
  GET  /log?n=30    JSON: 最近动作流水(可复制)
  POST /move        {"axis":"x|y|z","mm":1.0,"speed":5.0}  (需授权; 每步 ≤20mm)
  POST /stop        (永远允许)
  POST /reset       (需授权)
  POST /revoke      立刻撤销授权(永远允许)
"""
import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("ZMAX_ARM_PORT", "8798"))
HOME = os.path.expanduser("~")
SDK_DIR = os.path.join(HOME, "zmax_data", "rokae_sdk")
FIFO = os.path.join(SDK_DIR, "cmd_arm.fifo")
RESULT = os.path.join(SDK_DIR, "tcp_out", "agent_result.json")
HEART = os.path.join(SDK_DIR, "tcp_out", "agent_heartbeat.json")
AUTH = os.path.join(HOME, "zmax_data", "sdk_arm_auth.json")
AUDIT = os.path.join(HOME, "zmax_data", "sdk_arm_audit.jsonl")

MAX_STEP_MM = 20.0          # 单步上限(页面档位最大 20)
MAX_SPEED = 60.0            # mm/s
MIN_INTERVAL = 0.5          # 两条动作最小间隔(秒)
LOCK = threading.Lock()
LAST_MOVE = [0.0]


def jload(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                        # noqa: BLE001
        return d if d is not None else {}


def audit(rec):
    rec["ts_str"] = time.strftime("%F %T")
    rec["ts"] = time.time()
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    with open(AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def auth_state():
    a = jload(AUTH, {})
    if not a.get("enabled"):
        return {"armed": False, "why": "未授权(命令行 tools/sdk_arm_auth.sh --ttl 1800 --uses 30)"}
    left = a.get("ttl_s", 0) - (time.time() - a.get("ts", 0))
    used, mux = a.get("used", 0), a.get("max_uses", 0)
    ok = left > 0 and used < mux
    return {"armed": bool(ok), "left_s": max(0, int(left)), "used": used, "max_uses": mux,
            "by": a.get("by"), "note": a.get("note"),
            "why": None if ok else ("授权已过期" if left <= 0 else "次数用尽")}


def consume_auth():
    """原子核销一次授权。返回 (ok, auth_dict)。"""
    with LOCK:
        a = jload(AUTH, {})
        st = auth_state()
        if not st.get("armed"):
            return False, st
        a["used"] = int(a.get("used", 0)) + 1
        a["t"] = time.strftime("%F %T")
        tmp = AUTH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(a, f, ensure_ascii=False, indent=1)
        os.replace(tmp, AUTH)
        return True, auth_state()


def refund_auth(why=""):
    """没送达就退还本次核销的授权(不白扣次数)。"""
    with LOCK:
        a = jload(AUTH, {})
        if a.get("used"):
            a["used"] = max(0, int(a["used"]) - 1)
            a["last_refund"] = why[:80]
            tmp = AUTH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(a, f, ensure_ascii=False, indent=1)
            os.replace(tmp, AUTH)


def send_cmd(req, timeout=45.0):
    """写 FIFO 给常驻代理, 等它把结果写进 RESULT。"""
    rid = uuid.uuid4().hex[:12]
    req = dict(req)
    req["id"] = rid
    if not os.path.exists(FIFO):
        return {"ok": False, "err": "代理未运行: 找不到 FIFO %s (先跑 bash tools/start_sdk_arm.sh)" % FIFO}
    try:
        before = os.path.getmtime(RESULT) if os.path.exists(RESULT) else 0
    except Exception:                                                        # noqa: BLE001
        before = 0
    try:
        with open(FIFO, "w", encoding="utf-8") as f:  # 写端关闭 = 代理读到 EOF 重开, 不影响
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
    except PermissionError as e:
        return {"ok": False, "err": "FIFO 不可写(%s): %s 权限需宿主用户可写" % (e, FIFO)}
    except Exception as e:                                                    # noqa: BLE001
        return {"ok": False, "err": "FIFO 打开失败: %s" % e}
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.1)
        r = jload(RESULT, {})
        if r.get("id") == rid:
            return {"ok": r.get("rc") in (0,), "rc": r.get("rc"), "verdict": r.get("verdict"),
                    "result": r, "took_s": round(time.time() - t0, 2)}
        try:
            if os.path.exists(RESULT) and os.path.getmtime(RESULT) <= before:
                continue
        except Exception:                                                    # noqa: BLE001
            pass
    return {"ok": False, "err": "等待代理结果超时(%.0fs) · id=%s" % (timeout, rid)}


PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>真机点动 · 本机SDK直连</title><style>
body{font:15px/1.5 -apple-system,"Noto Sans CJK SC",sans-serif;margin:0;background:#111;color:#eee}
.wrap{max-width:640px;margin:0 auto;padding:12px}
h3{margin:6px 0 10px;font-size:16px;font-weight:600}
.bar{background:#1b1b1b;border-radius:8px;padding:8px 10px;margin-bottom:10px;font-size:13px;color:#bbb}
.bar b{color:#fff}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:8px 0}
button{font-size:17px;padding:14px 4px;border-radius:10px;border:1px solid #333;background:#232323;color:#eee;cursor:pointer}
button.mv{font-weight:600}
button:active{background:#2f6f4f}
button.warn{background:#5a2323}
button.on{background:#2f6f4f;border-color:#3f9f6f}
.row{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.row button{font-size:14px;padding:8px 12px;flex:0 0 auto}
pre{background:#0c0c0c;border:1px solid #222;border-radius:8px;padding:8px;font-size:12px;max-height:230px;overflow:auto;white-space:pre-wrap}
.arm{color:#7fd1a0}.dis{color:#ff9b9b}
</style></head><body><div class="wrap">
<h3>真机点动 · 本机 SDK 直连（不经 Orin）</h3>
<div class="bar" id="s">加载中…</div>
<div class="row"><span style="align-self:center;color:#888">步长</span>
 <button class="st" data-mm="0.5">0.5</button><button class="st on" data-mm="1">1</button>
 <button class="st" data-mm="5">5</button><button class="st" data-mm="10">10</button><button class="st" data-mm="20">20</button>
 <span style="align-self:center;color:#888">速度</span>
 <button class="sp" data-sp="2">2</button><button class="sp on" data-sp="5">5</button>
 <button class="sp" data-sp="10">10</button><button class="sp" data-sp="20">20</button></div>
<div class="grid">
 <button class="mv" data-a="z" data-s="1">↑ Z+</button>
 <button class="mv" data-a="x" data-s="-1">← X-</button>
 <button class="mv" data-a="x" data-s="1">X+ →</button>
 <button class="mv" data-a="y" data-s="-1">Y-</button>
 <button class="mv" data-a="z" data-s="-1">↓ Z-</button>
 <button class="mv" data-a="y" data-s="1">Y+</button>
</div>
<div class="row"><button class="warn" id="stop">⏹ 停</button><button id="reset">↺ 复位</button>
 <button id="revoke" class="warn">⛔ 撤销授权</button><button id="ref">🔄 刷新</button></div>
<pre id="j">点一次方向键开始。</pre>
<pre id="l">日志…</pre>
</div><script>
let MM=1, SP=5;
function sel(){document.querySelectorAll('.st').forEach(b=>b.classList.toggle('on',+b.dataset.mm==MM));
 document.querySelectorAll('.sp').forEach(b=>b.classList.toggle('on',+b.dataset.sp==SP));}
document.querySelectorAll('.st').forEach(b=>b.onclick=()=>{MM=+b.dataset.mm;sel()});
document.querySelectorAll('.sp').forEach(b=>b.onclick=()=>{SP=+b.dataset.sp;sel()});
async function j(u,p){const r=await fetch(u,{method:p?'POST':'GET',body:p?JSON.stringify(p):undefined});
 const d=await r.json();document.getElementById('j').textContent=JSON.stringify(d,null,1);return d;}
document.querySelectorAll('.mv').forEach(b=>b.onclick=async()=>{
 const ax=b.dataset.a, sg=+b.dataset.s, mm=MM*sg;
 const d={axis:ax,mm:mm,speed:SP};
 document.getElementById('j').textContent='下发 '+ax+' '+(mm>0?'+':'')+mm+'mm @'+SP+'mm/s …';
 const r=await j('/move',d); refresh();});
document.getElementById('stop').onclick=async()=>{await j('/stop',{});refresh();};
document.getElementById('reset').onclick=async()=>{await j('/reset',{});refresh();};
document.getElementById('revoke').onclick=async()=>{await j('/revoke',{});refresh();};
document.getElementById('ref').onclick=()=>refresh();
async function refresh(){const s=await (await fetch('/state')).json();
 const a=s.auth||{}, h=s.heartbeat||{};
 const p=(h.pose&&h.pose.tcp)||[]; const sm=h.sampler||{};
 document.getElementById('s').innerHTML =
  (a.armed?'<b class=arm>已授权</b> 剩 '+(a.left_s/60).toFixed(1)+' 分钟 · '+a.used+'/'+a.max_uses+' 次'
          :'<b class=dis>未授权</b> '+(a.why||''));
 document.getElementById('s').innerHTML += ' · 位姿 '+p.map(v=>(+v).toFixed(4)).join(', ')+
  ' · 采样龄 '+(sm.age_s!=null?sm.age_s:'?')+'s · '+(h.state?h.state.powerState+'/'+h.state.operationState:'代理无心跳');
 fetch('/log?n=12').then(r=>r.json()).then(d=>{document.getElementById('l').textContent=
  (d.lines||[]).map(x=>x.ts_str+' '+(x.axis||x.cmd)+' '+(x.mm!=null?x.mm+'mm':'')+' '+(x.verdict||'')).join('\\n')||'（空）';});}
refresh();setInterval(refresh,3000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj, ctype="application/json; charset=utf-8"):
        b = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False, indent=1).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):                                               # 静音
        pass

    def do_GET(self):
        if self.path.startswith("/state"):
            hb = jload(HEART, {})
            return self._send(200, {"auth": auth_state(), "heartbeat": hb,
                                    "last": jload(RESULT, {}), "caps": {"max_step_mm": MAX_STEP_MM, "max_speed": MAX_SPEED}})
        if self.path.startswith("/log"):
            n = 30
            m = re.search(r"n=(\d+)", self.path)
            if m:
                n = min(int(m.group(1)), 200)
            lines = []
            if os.path.exists(AUDIT):
                with open(AUDIT, encoding="utf-8") as f:
                    lines = [json.loads(x) for x in f.read().splitlines() if x.strip()][-n:]
            return self._send(200, {"lines": list(reversed(lines))})
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        return self._send(404, {"err": "not found"})

    def do_POST(self):
        ln = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(ln) or b"{}")
        except Exception:                                                     # noqa: BLE001
            body = {}
        p = self.path.split("?")[0]
        if p == "/revoke":
            a = jload(AUTH, {})
            a.update({"enabled": False, "revoked_ts": time.time(),
                      "revoked_str": time.strftime("%F %T")})
            tmp = AUTH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(a, f, ensure_ascii=False, indent=1)
            os.replace(tmp, AUTH)
            audit({"cmd": "revoke", "note": "页面撤销"})
            return self._send(200, {"ok": True, "auth": auth_state()})
        if p == "/stop":
            r = send_cmd({"cmd": "stop"}, timeout=20)
            audit({"cmd": "stop", "verdict": r.get("verdict") or r.get("err")})
            return self._send(200, r)
        if p in ("/move", "/reset"):
            ax, mm, speed = "", 0.0, 5.0
            if p == "/move":
                ax = str(body.get("axis") or "").lower()
                mm = float(body.get("mm") or 0.0)
                speed = float(body.get("speed") or 5.0)
                if ax not in ("x", "y", "z"):
                    return self._send(400, {"err": "axis 必须是 x/y/z"})
                if abs(mm) > MAX_STEP_MM:
                    return self._send(400, {"err": "单步 %.1fmm 超过上限 %.0fmm" % (mm, MAX_STEP_MM)})
                if abs(mm) < 1e-9:
                    return self._send(400, {"err": "mm 不能为 0"})
                if speed > MAX_SPEED:
                    return self._send(400, {"err": "速度超过上限 %.0fmm/s" % MAX_SPEED})
            if time.time() - LAST_MOVE[0] < MIN_INTERVAL:
                return self._send(429, {"err": "太快了, 间隔 ≥%.1fs" % MIN_INTERVAL})
            ok, st = consume_auth()
            if not ok:
                audit({"cmd": "refuse", "why": st.get("why"), "req": body})
                return self._send(403, {"err": "未授权: %s" % st.get("why"), "auth": st})
            LAST_MOVE[0] = time.time()
            if p == "/move":
                d = {"x": 0.0, "y": 0.0, "z": 0.0}
                d[ax] = mm
                r = send_cmd({"cmd": "move-rel", "dx": d["x"], "dy": d["y"], "dz": d["z"],
                              "speed": speed, "cap_mm": MAX_STEP_MM})
                if not r.get("ok"):
                    refund_auth(r.get("err") or "未送达")
                audit({"cmd": "move", "axis": ax, "mm": mm, "speed": speed,
                       "verdict": r.get("verdict") or r.get("err"), "auth_used": st.get("used"),
                       "evidence": (r.get("result", {}).get("out") or {}).get("evidence_path")})
            else:
                r = send_cmd({"cmd": "reset"}, timeout=20)
                audit({"cmd": "reset", "verdict": r.get("verdict") or r.get("err")})
            return self._send(200, r)
        return self._send(404, {"err": "not found"})


if __name__ == "__main__":
    os.makedirs(os.path.join(SDK_DIR, "tcp_out"), exist_ok=True)
    print("SDK 动作服务: http://0.0.0.0:%d/  · 授权文件 %s" % (PORT, AUTH))
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
