"""SE(3) 分层几何看板服务 (8815)。

一张页面把状态口径按流形对象画出来, 另开一个只读 JSON 给页面标"现在":
  位置 ∈ ℝ³   → 路径 + 包围盒 + 停留点 (主图)
  姿态 ∈ S³   → 四元数轴角球 (点 = 虚部, 半径 = sin(θ/2))
  S² 轴       → 单位球 + 轴轨迹 + 孔轴参考 + 轴误差
  S¹ 滚转     → 表盘指针 φ + Δφ/帧
  TQ 速度     → 沿路径的切向箭头 (颜色 = flow 四档)
  S¹ 相位     → 弧长相位环 + s 读数 (traj_phase.json)

刻意不做的事: 不改任何轨迹/执行文件, 只读 tools/web/real_traj_joints.json、
zmax_data/rokae_sdk/traj_hopf.json、traj_phase.json 和真值 tcp_out/latest.json。
"""
import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

REPO = "/home/ubuntu/zmax"
WEB = os.path.join(REPO, "tools", "web")
SDK = os.path.join(REPO, "zmax_data", "rokae_sdk")
_J = {}
_LAST = {"i": None}
_STATUS_URL = (os.environ.get("ZMAX_SE3_STATUS_URL") or "http://127.0.0.1:8797/api/arm/step_traj/status").strip()
_ST = {"ts": 0.0, "cursor": 0, "running": False}


def _run_cursor():
    """执行器游标 (跑批中才有意义); 取不到/没在跑 ⇒ None, 走纯几何投影。"""
    if not _STATUS_URL:
        return None
    now = time.time()
    if now - float(_ST["ts"]) > 1.0:
        try:
            import urllib.request
            with urllib.request.urlopen(_STATUS_URL, timeout=0.6) as r:
                d = json.loads(r.read().decode())
            _ST.update(ts=now, cursor=int(d.get("cursor") or 0), running=bool(d.get("running")))
        except Exception:                                                    # noqa: BLE001
            _ST["ts"] = now
    return _ST["cursor"] if (_ST["running"] and _ST["cursor"] > 0) else None      # 相位连续性: 上一次投影到的索引(防止自交处跳到别的分支)


LOGS = ("traj_step_geom.log", "traj_step_geom2.log")

# 🔭 远端真值 (2026-11-19): intel 550C 没有珞石 SDK ⇒ 配这条 URL 就能看真机信号
#   口径 = 本机 8797 GET /api/tcp: {x,y,z(m), quat=[qx,qy,qz,qw], joints(rad), age_s}
TRUTH_URL = (os.environ.get("ZMAX_SE3_TRUTH_URL") or "").strip()


def _fetch_truth(url: str, timeout: float = 1.5):
    """拉远端真值并归一成本地 latest.json 同口径; 失败返回 None (不静默造值)。"""
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
        quat = d.get("quat") or []
        if not d.get("ok") or len(quat) != 4 or d.get("x") is None:
            return None
        return {"x": float(d["x"]), "y": float(d["y"]), "z": float(d["z"]),
                "qx": float(quat[0]), "qy": float(quat[1]), "qz": float(quat[2]), "qw": float(quat[3]),
                "joints": d.get("joints"),
                "ts": time.time() - float(d.get("age_s") or 0.0),
                "frame": d.get("frame") or "base_link", "src": "remote"}
    except Exception:                                                       # noqa: BLE001
        return None

# 录制轨迹上的"停留点"(到点必须先停稳, 才允许做夹爪/AOI 动作) —— 真源两处, 不另编:
#   · 夹爪: 回放计划 grip 项(#9 close hold 2000ms / #205 open hold 2600ms), 见 arm_step_traj 的 grip_plan
#   · AOI : tools/rokae/arm_step_traj.py:105  AOI_ON_ARRIVE = {125:(10082,金手指), 151:(10082,金手指), 172:(10083,表面)}
STOPS = [
    {"i": 9,   "kind": "grip", "name": "合爪·抓取", "hold_ms": 2000, "port": None},
    {"i": 125, "kind": "aoi",  "name": "金手指 AOI", "hold_ms": None, "port": 10082},
    {"i": 151, "kind": "aoi",  "name": "金手指 AOI", "hold_ms": None, "port": 10082},
    {"i": 172, "kind": "aoi",  "name": "表面 AOI",  "hold_ms": None, "port": 10083},
    {"i": 205, "kind": "grip", "name": "松爪·放置", "hold_ms": 2600, "port": None},
]
_SPD_COLOR = {100.0: "#37d0ff", 85.0: "#3ddc84", 70.0: "#f5a623", 60.0: "#e0563f"}


def _sectors():
    """节拍构成: 从真机跑批日志取每一块的 (i0,i1,s0,s1,secs,speed)。

    这是"扇形的角度来源" —— 角度=相位 s(弧长真相位), 扇区耗时=实测 secs。
    同 (i,i1) 重复出现时保留最后一条(重跑覆盖)。
    """
    blocks = {}
    mt = []
    # 🔴 段跑日志里的 i 是**相对起点**的(第二段 start=60 却从 0 记起), 两个日志混在一起会撞键,
    #   而且状态判定会错(#0~11 被当成"含 #9 合爪")。这里一律用 traj_phase 的 s 反查绝对索引。
    _ph = _load(os.path.join(SDK, "traj_phase.json"), "phase") or {}
    _ss = [f["s"] for f in _ph.get("frames", [])]

    def _idx(s):
        if not _ss:
            return None
        k = min(range(len(_ss)), key=lambda q: abs(_ss[q] - s))
        return k if abs(_ss[k] - s) < 0.002 else None
    for fn in LOGS:
        path = os.path.join(SDK, fn)
        try:
            mt.append(os.path.getmtime(path))
        except OSError:
            continue
        try:
            for ln in open(path, encoding="utf-8", errors="ignore"):
                ln = ln.strip()
                if not ln.startswith('{"progress"'):
                    continue
                try:
                    st = json.loads(ln)["step"]
                except Exception:                                        # noqa: BLE001
                    continue
                if st.get("s0") is None or st.get("s1") is None:
                    continue
                _a, _b = _idx(st["s0"]), _idx(st["s1"])
                if _a is None or _b is None:            # 反查不到就不收(宁可少, 不许错位)
                    continue
                blocks[round(st["s0"], 5)] = {          # 用相位做键: 两段日志不会撞
                    "i0": _a, "i1": _b, "n_pts": st.get("n_pts"),
                    "s0": st["s0"], "s1": st["s1"], "t_s": st.get("secs"),
                    "speed": st.get("speed_cmd"), "err": st.get("err_deg"),
                    "axis_max": st.get("axis_dn_max"), "roll_max": st.get("roll_dp_max")}
        except OSError:
            continue
    if not blocks:
        return None
    key = (tuple(mt), len(blocks))
    hit = _J.get("sectors")
    if hit and hit[0] == key:
        return hit[1]
    bl = sorted(blocks.values(), key=lambda b: b["s0"])
    tot = sum(b["t_s"] or 0.0 for b in bl) or 1.0
    by_spd = {}
    for b in bl:
        k = float(b["speed"] or 0)
        d = by_spd.setdefault(k, {"speed": k, "t_s": 0.0, "n_blocks": 0, "s_span": 0.0})
        d["t_s"] += b["t_s"] or 0.0
        d["n_blocks"] += 1
        d["s_span"] += (b["s1"] - b["s0"])
    tiers = [{"speed": k, "t_s": round(v["t_s"], 2), "frac": round(v["t_s"] / tot, 4),
              "n_blocks": v["n_blocks"], "s_frac": round(v["s_span"], 4),
              "color": _SPD_COLOR.get(k, "#8fa3b3")}
             for k, v in sorted(by_spd.items(), reverse=True)]
    # 每块: 耗时 + 单位相位耗时(哪个扇区慢) + 当时状态
    # 🔴 状态是**推断**, 依据只有两条可核证据: ①录制轨迹的停留点(#9 合爪 / #125·#151 金手指AOI /
    #    #172 表面检测 / #205 松爪放置, 见 traj_step_cmd 的 dwell_ms) ②该块实测速度档。
    #    录制文件本身没有阶段标注真源, 所以标签写成"推断口径", 不给假真值。
    for b in bl:
        span = max(b["s1"] - b["s0"], 1e-9)
        b["t_per_mm"] = round((b["t_s"] or 0.0) / (span * 7861.8), 4)
        b["frac"] = round((b["t_s"] or 0.0) / tot, 4)
        rng = range(b["i0"], b["i1"] + 1)
        tags = []
        if 9 in rng:
            st = "抓取(合爪)"
        elif 125 in rng or 151 in rng:
            st = "金手指 AOI"
        elif 172 in rng:
            st = "表面检测"
        elif 205 in rng:
            st = "放置(松爪)"
        elif b["i0"] == 0:
            st = "起始接近"
        elif (b["speed"] or 0) >= 85:
            st = "转移"
        elif (b["speed"] or 0) >= 70:
            st = "对位"
        else:
            st = "操作区"
        if (b.get("axis_max") or 0) >= 10:
            tags.append("轴断层%.0f°" % b["axis_max"])
        if (b.get("roll_max") or 0) >= 12:
            tags.append("滚转%.0f°" % b["roll_max"])
        if (b["n_pts"] or 0) <= 3:
            tags.append("碎步%d点" % b["n_pts"])
        b["state"] = st
        b["state_tags"] = tags
    slow = sorted(bl, key=lambda b: -(b["t_s"] or 0))[:5]
    # 停留点: 补相位(角度)与毫米, 供环上画标记; s 取自 traj_phase(与扇形同一坐标)
    stops = []
    for s0 in STOPS:
        i = s0["i"]
        r = {"i": i, "kind": s0["kind"], "name": s0["name"], "hold_ms": s0["hold_ms"], "port": s0["port"]}
        if _ss and 0 <= i < len(_ss):
            r["s"] = _ss[i]
            r["s_mm"] = _ph["frames"][i].get("s_mm")
        stops.append(r)
    out = {"blocks": bl, "n_blocks": len(bl), "total_s": round(tot, 2), "tiers": tiers, "stops": stops,
           "slowest": [{"i0": b["i0"], "i1": b["i1"], "t_s": b["t_s"], "s0": b["s0"], "s1": b["s1"],
                         "state": b.get("state"), "speed": b.get("speed"),
                         "n_pts": b.get("n_pts")} for b in slow]}
    _J["sectors"] = (key, out)
    return out


def _load(path, key):
    """带 mtime 缓存: 文件改了才重读, 免得每 1s 都 parse 一次 30KB JSON。"""
    try:
        m = os.path.getmtime(path)
    except OSError:
        return None
    hit = _J.get(key)
    if hit and hit[0] == m:
        return hit[1]
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:                                                    # noqa: BLE001
        return hit[1] if hit else None
    _J[key] = (m, d)
    return d


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):                                           # 静音, 不刷 journal
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                                    # noqa: N802
        p = urlparse(self.path).path
        if p in ("/", "/index.html", "/se3", "/se3/"):
            try:
                h = open(os.path.join(WEB, "se3_geom.html"), "rb").read()
            except OSError as e:
                return self._send(500, {"ok": False, "why": "看板文件缺失: %s" % e})
            return self._send(200, h, "text/html; charset=utf-8")
        if p == "/api/se3":
            return self._send(200, self._live())
        if p == "/healthz":
            return self._send(200, {"ok": True, "svc": "zmax-se3-geom", "ts": time.time()})
        return self._send(404, {"ok": False, "why": "not found: %s" % p})

    def _live(self):
        """现在: 真机 TCP 最近点投影 → (i, s) + 该点姿态/速度; 不做任何下发。"""
        # 真值来源: 本机 tcp_out/latest.json 优先; 帧龄 >2s 且配了 ZMAX_SE3_TRUTH_URL 就拉远端
        #   (intel 550C 看板靠这条看真机信号: 它没有珞石 SDK, 只经 HTTP 读本机 8797 /api/tcp)
        tcp = _load(os.path.join(SDK, "tcp_out", "latest.json"), "tcp")
        if TRUTH_URL:
            _age = time.time() - float((tcp or {}).get("ts") or 0)
            if not tcp or _age > 2.0:
                _r = _fetch_truth(TRUTH_URL)
                if _r:
                    _r["src"] = "远端 %s (本机 latest.json 帧龄 %.1fs)" % (TRUTH_URL, _age)
                    tcp = _r
        traj = _load(os.path.join(WEB, "real_traj_joints.json"), "traj")
        hopf = _load(os.path.join(SDK, "traj_hopf.json"), "hopf")
        phase = _load(os.path.join(SDK, "traj_phase.json"), "phase")
        out = {"ok": True, "ts": time.time(), "svc": "zmax-se3-geom",
               "truth_src": (tcp or {}).get("src") or "local latest.json"}
        if not traj:
            out.update({"ok": False, "why": "traj 缺失"})
            return out
        P = [[c * 1000.0 for c in f["p"]] for f in traj["frames"]]
        out["n"] = len(P)
        if tcp:
            q = [tcp["x"] * 1000.0, tcp["y"] * 1000.0, tcp["z"] * 1000.0]
            d = [((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2) ** 0.5 for p in P]
            # 🔴 轨迹有 22 处自交(几何近重合), 全局最近点会跳到另一分支(实测跑到 #60~71 时报 #2)。
            #   用相位连续性约束: 在上次索引附近开窗找, 只有窗口内没有近点时才回退全局。
            _li = _LAST.get("i")
            _dmin = min(d)
            _ig = d.index(_dmin)
            # ⓪ 跑批时以执行器游标为准: 投影只在 [cursor-2, cursor+14] 内找 ——
            #    停车/慢速时几何最近点会沿轨迹后退几帧(实测 7 次, 25~76mm), 游标能消掉它。
            _anchor = _run_cursor()
            if _anchor is None and min(d[0], d[-1]) <= 12.0 and _dmin <= min(d[0], d[-1]) + 8.0:
                # 空闲 + 贴着首/末点: 直接报端点。臂停在起点时几何最近点常落在自交处
                # (实测停在 663/-29/292 报 #69 s=31%, 实际它离 #214 只有 4.7mm)
                i = 0 if d[0] <= d[-1] else len(d) - 1
            elif _anchor is not None:
                lo, hi = max(0, _anchor - 2), min(len(d), _anchor + 14)
                w = d[lo:hi]
                i = lo + w.index(min(w))
                # 跑批是单向回放 ⇒ 索引不许后退 (实测: 只加窗口还有 5 次 25~76mm 后退)
                i = max(i, int(_LAST.get("i") or 0))
            # ① 紧贴某点(≤3mm) ⇒ 以几何为准: 臂停在起/终点时, 自交窗口常被另一分支占住
            #    (实测 intel 看板停回起点仍报 #69, 就是窗口赢过了 2.3mm 的全局最近点)
            elif _dmin <= 3.0:
                i = _ig
            elif _li is None:
                i = _ig
            else:
                lo, hi = max(0, _li - 6), min(len(P), _li + 40)
                win = d[lo:hi]
                j = lo + win.index(min(win))
                i = j if min(win) <= max(6.0 * min(d), 25.0) else d.index(min(d))
            _LAST["i"] = i
            out["tcp_mm"] = [round(v, 1) for v in q]
            out["age_s"] = round(time.time() - float(tcp.get("ts") or 0), 2)
            out["nearest"] = {"i": i, "dist_mm": round(d[i], 1)}   # 报"该点"的距离, 不报全局最小(会自相矛盾)
            if phase:
                r = phase["frames"][i]
                out["nearest"].update({"s": r["s"], "s_mm": r["s_mm"]})
            if hopf:
                hf = hopf["frames"][i]
                out["nearest"].update({"n": hf.get("n"), "phi_deg": hf.get("phi_deg")})
            if tcp.get("joints"):
                out["joints_deg"] = [round(v * 180.0 / 3.141592653589793, 2) for v in tcp["joints"]]
        # 🌀 实时姿态 → Hopf 拆 S²(轴) + S¹(滚转), 公式与 tools/se3_hopf.py 同源:
        #    n=(2(xz+wy), 2(yz-wx), w²+z²-x²-y²),  φ=2·atan2(z,w)
        if tcp and tcp.get("qw") is not None:
            w = float(tcp["qw"]); x = float(tcp["qx"]); y = float(tcp["qy"]); z = float(tcp["qz"])
            nn = (w * w + x * x + y * y + z * z) ** 0.5 or 1.0
            w, x, y, z = w / nn, x / nn, y / nn, z / nn
            n = [2.0 * (x * z + w * y), 2.0 * (y * z - w * x), w * w + z * z - x * x - y * y]
            ln = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5 or 1.0
            out["quat"] = [round(v, 6) for v in (w, x, y, z)]
            out["n"] = [round(v / ln, 6) for v in n]
            out["phi_deg"] = round(2.0 * __import__("math").degrees(__import__("math").atan2(z, w)), 3)
            # 与孔轴(插入段参考)的夹角, 现场看姿态偏没偏
            ref = (hopf or {}).get("frames", [{}])[30].get("n")
            if ref:
                d = sum(a * b for a, b in zip(out["n"], ref))
                out["axis_err_deg"] = round(__import__("math").degrees(
                    __import__("math").acos(max(-1.0, min(1.0, d)))), 2)
        out["summary"] = (phase or {}).get("summary") if phase else None
        sec = _sectors()
        if sec:
            out["sectors"] = sec
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8815)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), H)
    print("zmax-se3-geom on http://%s:%d/  (看板 / · 实时 /api/se3 · 健康 /healthz)" % (a.host, a.port),
          flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
