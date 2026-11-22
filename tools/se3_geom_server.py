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
import math
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

REPO = "/home/ubuntu/zmax"
WEB = os.path.join(REPO, "tools", "web")
SDK = os.path.join(REPO, "zmax_data", "rokae_sdk")
_J = {}
_LAST = {"i": None}
_STATUS_URL = (os.environ.get("ZMAX_SE3_STATUS_URL") or "http://127.0.0.1:8797/api/arm/step_traj/status").strip()
_ST = {"ts": 0.0, "cursor": 0, "running": False}


def _quat_rpy(r, p, y):
    """roll/pitch/yaw(rad) → 四元数(w,x,y,z), 与 tools/se3_hopf.py 同一约定。"""
    cr, sr = math.cos(r / 2.0), math.sin(r / 2.0)
    cp, sp = math.cos(p / 2.0), math.sin(p / 2.0)
    cy, sy = math.cos(y / 2.0), math.sin(y / 2.0)
    return (cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy)


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

# 录制轨迹上的"停留点"——**几何判据算出来的**, 不是硬编:
#   ① 速度是局部极小且 < 15% 中位速度(真的停住, 不是慢) ② 停点前后 ±3 帧的方向变化 >= 25°(真的换向)
#   ③ 前后两段位移都 > 10mm(排除抖动) ④ 5 帧内只留方向变化最大的一个(补点不算新停点)
# 🔴 旧的硬编 5 点里有 4 个根本不是停点: #125 走 454mm/s(274%中位) / #151 214mm/s / #172 161mm/s /
#    #205 179mm/s —— 那段轨迹根本没停, 只是"到达即触发 AOI", 于是环上多出 4 个假停留。
STOP_SPEED_FRAC = 0.0        # 🔴 0 = 不卡速度: 方向突变就停(老倪口径), >0 才是"只认近似静止的停点"
STOP_TURN_DEG = float(os.environ.get("ZMAX_STOP_TURN") or 45.0)   # 转向阈值(度)
STOP_WIN = int(os.environ.get("ZMAX_STOP_WIN") or 5)              # 前后各取 5 帧算方向(抑噪)
STOP_MIN_MM = 10.0                                                # 前后段太短(抖动)不算突变
STOP_DEDUP = 5
# AOI/夹爪"事件点": 到点触发, 但录制轨迹在这些点上是**在动**的 ⇒ 只用来给状态贴标签, 不当停留点画
EVENTS = [
    {"i": 9,   "kind": "grip", "name": "抓取光模块(最低抓取点)", "hold_ms": 2000, "port": None, "stop": True},
    {"i": 19,  "kind": "scan", "name": "扫码点", "hold_ms": None, "port": 10082, "stop": True},
    {"i": 35,  "kind": "work", "name": "设备工作点(推进到底·在此检查)", "hold_ms": 5000, "port": 10082, "stop": True},
    {"i": 77,  "kind": "grip", "name": "抓取点(最下面·抓光模块)", "hold_ms": 2000, "port": None, "stop": True},
    {"i": 125, "kind": "aoi",  "name": "金手指 AOI", "hold_ms": None, "port": 10082, "stop": False},
    {"i": 151, "kind": "aoi",  "name": "金手指 AOI", "hold_ms": None, "port": 10082, "stop": False},
    {"i": 172, "kind": "aoi",  "name": "表面 AOI",  "hold_ms": None, "port": 10083, "stop": False},
    {"i": 205, "kind": "grip", "name": "松爪·放置", "hold_ms": 2600, "port": None,  "stop": False},
]


def _detect_stops():
    """按几何判据从录制轨迹里找真实停留点(速度≈0 且方向突变)。"""
    try:
        d = _load(os.path.join(SDK, _setf("real_traj_joints.json")), "traj_raw") or {}
        fr = d.get("frames") or []
    except Exception:                                                   # noqa: BLE001
        fr = []
    n = len(fr)
    if n < 12:
        return []
    # 🔴 real_traj_joints 的 p 是**米**(0.665 m), 而阈值是按 mm 写的(10mm) ⇒ 直接比会一个停点都找不到
    pos = []
    for f in fr:
        q = list(f.get("p") or [0, 0, 0])
        if max(abs(c) for c in q) < 20:
            q = [c * 1000.0 for c in q]
        pos.append(q)
    tt = [float(f.get("t") or 0) for f in fr]
    sp = [0.0] * n
    for i in range(1, n):
        dt = max(1e-6, tt[i] - tt[i - 1])
        sp[i] = math.dist(pos[i], pos[i - 1]) / dt
    med = sorted(sp[1:])[len(sp[1:]) // 2] or 1.0
    W = STOP_WIN

    def _ang(i):
        vb = [pos[i][k] - pos[i - W][k] for k in range(3)]
        va = [pos[i + W][k] - pos[i][k] for k in range(3)]
        lb = math.sqrt(sum(x * x for x in vb)); la = math.sqrt(sum(x * x for x in va))
        if lb < 1e-6 or la < 1e-6:
            return 0.0, lb, la
        c = max(-1.0, min(1.0, sum(vb[k] * va[k] for k in range(3)) / (lb * la)))
        return math.degrees(math.acos(c)), lb, la

    out = []
    for i in range(W, n - W):
        if STOP_SPEED_FRAC > 0 and sp[i] >= STOP_SPEED_FRAC * med:
            continue
        a, lb, la = _ang(i)
        if a < STOP_TURN_DEG or lb < STOP_MIN_MM or la < STOP_MIN_MM:
            continue
        row = {"i": i, "speed_mm_s": round(sp[i], 2), "turn_deg": round(a, 1),
               "speed_pct": round(100.0 * sp[i] / med, 1)}
        if out and i - out[-1]["i"] <= STOP_DEDUP:
            if a > out[-1]["turn_deg"]:
                out[-1] = row
        else:
            out.append(row)
    return out


STOPS = []          # 启动时由 _stops() 现算并缓存(录制文件改了要重算)

# 老倪在页面上给停点起的名字 / 删掉的停点, 存这里(改一次就持久)
LABELS_F = os.path.join(SDK, "stop_labels.json")


def _labels():
    try:
        return json.load(open(LABELS_F, encoding="utf-8"))
    except Exception:                                                   # noqa: BLE001
        return {}


PTS_F = os.path.join(SDK, "point_stops.json")      # 215 点回放: 每个点是否停 1 秒 + 名字
# 两套点位表并存(老倪: 之前的记住) —— "215" = 旧的 215 点; "v2" = 2026-11-21 手走重录 8mm 重采样表
PTS_SETS = {
    "215": (os.path.join(SDK, "real_traj_joints.json"), os.path.join(SDK, "point_stops.json")),
    "v2": (os.path.join(SDK, "real_traj_joints_v2.json"), os.path.join(SDK, "point_stops_v2.json")),
    # 现场演示那一遍 (老倪 2026-11-22 手工走: 槽2→扫码→插入→检测→钩拉环→检测面/侧面→下盘)
    "demo": (os.path.join(SDK, "real_traj_joints_demo.json"), os.path.join(SDK, "point_stops_v2.json")),
}


def _pts_set(name):
    return PTS_SETS.get(name or "215") or PTS_SETS["215"]


# ── 看板(相位图)用哪套点位表 ────────────────────────────────────────────────
# 老倪 2026-11-21「相位图重新画 给出状态」: 新表(v2, 手走重录 239 点)是当前真源,
# 所以默认 v2; 想回看旧 215 点看板就 ZMAX_SE3_SET=215 重启。
SET = (os.environ.get("ZMAX_SE3_SET") or "v2").strip()
PTS_N = 239 if SET == "v2" else (287 if SET == "demo" else 215)


def _setf(base: str) -> str:
    """real_traj_joints.json → real_traj_joints_v2.json(按当前 SET)"""
    if SET == "v2":
        return base[:-5] + "_v2.json"
    if SET == "demo":
        return base[:-5] + "_demo.json"      # 现场演示那一遍 (_geo 从 tools/web 读同名文件)
    return base


def _pts_cfg(f=None):
    try:
        return json.load(open(f or PTS_F, encoding="utf-8"))
    except Exception:                                                   # noqa: BLE001
        return {}


def _pts_list(setname="215"):
    """215 个点的关节(度)/TCP(mm) + 是否停止点 —— 页面要一次列全, 老倪逐点看。"""
    _tj, _cf = _pts_set(setname)
    try:
        st = json.load(open(_tj, encoding="utf-8"))
    except Exception:                                                   # noqa: BLE001
        st = {}
    fr = st.get("frames") or []
    cfg = _pts_cfg(_cf)
    out = []
    for i, f in enumerate(fr):
        j = [round(math.degrees(float(v)), 2) for v in (f.get("j") or [])[:6]]
        q = list(f.get("p") or [0, 0, 0])
        if max(abs(c) for c in q) < 20.0:
            q = [c * 1000.0 for c in q]
        c = cfg.get(str(i)) or {}
        out.append({"i": i, "j": j, "tcp": [round(float(v), 1) for v in q[:3]],
                    "t": round(float(f.get("t") or 0.0), 3),
                    "stop": bool(c.get("stop")), "name": c.get("name") or ""})
    return out


def _save_labels(d):
    tmp = LABELS_F + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LABELS_F)


def _stops():
    if SET == "v2":
        # v2 表没有"几何突变自动检出"的历史包袱: 停点就是老倪手走时真的停住的那 15 个点
        try:
            cfg = _pts_cfg(os.path.join(SDK, "point_stops_v2.json"))
        except Exception:                                                # noqa: BLE001
            cfg = {}
        res = []
        for k, v in sorted(((int(k), v) for k, v in cfg.items()), key=lambda kv: kv[0]):
            if not (v or {}).get("stop"):
                continue
            nm = (v or {}).get("name") or ""
            res.append({"i": k, "kind": "stop", "name": nm, "label": nm or ("#%d" % k),
                        "hold_ms": 1000, "port": None, "speed_mm_s": 0.0,
                        "turn_deg": 0.0, "speed_pct": 0.0})
        return res
    st = _load(os.path.join(SDK, "real_traj_joints.json"), "traj_raw") or {}
    key = st.get("n_frames")
    hit = _J.get("stops")
    if hit and hit[0] == key:
        return hit[1]
    det = _detect_stops()
    ev = {e["i"]: e for e in EVENTS}
    res = []
    for r in det:
        e = ev.get(r["i"]) or {}
        res.append({"i": r["i"], "kind": e.get("kind") or "stop",
                    "name": e.get("name") or "",       # 没名字就给空, 页面显示 #帧号, 等老倪填
                    "hold_ms": e.get("hold_ms"), "port": e.get("port"),
                    "speed_mm_s": r["speed_mm_s"], "turn_deg": r["turn_deg"],
                    "speed_pct": r["speed_pct"]})
    lab = _labels()
    res = [r for r in res if not (lab.get(str(r["i"])) or {}).get("del")]
    for r in res:
        nm = (lab.get(str(r["i"])) or {}).get("name")
        if nm:
            r["name"] = nm
        r["label"] = r["name"] or ("#%d" % r["i"])
    _J["stops"] = (key, res)
    return res



_SPD_COLOR = {100.0: "#37d0ff", 85.0: "#3ddc84", 70.0: "#f5a623", 60.0: "#e0563f"}

# 老倪口述并已按轨迹核过的阶段(按帧区间): 起始点 → 转移 → 下降 → 抓取点 → 上升 → 转移 → 扫码点
# 依据(逐帧几何): #1..#5 水平 210mm/垂直 −79mm; #6..#8 垂直 −103mm(水平仅 2mm);
#                #10..#14 垂直 +149mm(水平 27mm); #15..#18 水平 221mm/垂直 +7mm
PHASES = [
    (0, 0,   "初始点"),
    (1, 5,   "转移"),
    (6, 8,   "下降"),
    (9, 9,   "抓取点"),
    (10, 14, "上升"),
    (15, 18, "转移"),
    (19, 19, "扫码点"),
    # ⚠️ 以下 6 行是按**逐帧几何**推的(不是老倪口述), 请他确认后再定名:
    #   #21 微调 11.9mm → #22-#23 平移 36.5mm → #24-#32 来回 187mm(搜索?) → #33-#35 垂直下压 38.4mm(插入)
    (20, 20, "转移"),        # 扫码点 → 对位点: 199mm 平移(帧 #20 = 对位点/停止点)
    (21, 23, "对位"),
    (24, 32, "力控搜索"),
    (33, 34, "插入"),
    (35, 35, "设备工作点"),   # 插到底 = 设备检测点 = **拔出动作的起点**(检测完成后从这里拔)
    (36, 39, "离开"),        # 检查完 → 离开插口: 左移 116mm, z 190→198
    (40, 40, "拔出点"),      # 拔出完成(元件已出), 下一步转移
    (41, 54, "转移"),        # 拔出点 → 下一个停止点: 350mm(z 208→299→251, 绕行)
    (55, 55, "过渡点"),      # 过渡点(不停): (736,-121,251)
    (56, 57, "下探"),        # 122mm+90mm 俯冲到废料点
    (58, 58, "废料点"),      # 不良品分拣点: (847,-284,147), 到点松爪
    (59, 73, "转移"),        # 废料点 → 下一个停止点: 绕 z=294 高点回到 (681,130,233)
    (74, 74, "过渡点"),      # 过渡点(不停): (681,130,233)
    (75, 76, "下探"),        # 俯冲到全轨迹最低点 z=119.2
    (77, 77, "抓取点"),      # 最下面的点 = 抓取点(下料位抓光模块): (651,205,119)
    # ↓↓↓ 这一轮是循环的第二遍: 抓起 → 扫码 → 上插口插入 → 到底 → 到下面拔出点
    (78, 85, "上升"),        # 抓起后抬升到扫码高度 z 143→269
    (86, 88, "扫码点"),      # 第二次扫码: (754.7,28.8,271.4) — 与 #19 同一姿态(±0.5mm)
    (89, 92, "转移"),        # 扫码 → 插口上方
    (93, 93, "对位点"),      # (762.6,228.1,190.1) — 与 #20 同一姿态
    (94, 96, "对位"),        # 横移对轴心
    (97, 104, "力控搜索"),   # 抬到 z≈237 来回搜索
    (105, 107, "插入"),      # 下压进插口
    (108, 108, "设备工作点"),# 插到底 (801,229.9,189.2)
    (109, 109, "拔出点"),    # 下插口的拔出点
]


_STATES_F = os.path.join(SDK, "phase_states_%s.json" % SET)   # 每个轨迹集有自己的状态表 (v2/demo)
if not os.path.exists(_STATES_F):
    _STATES_F = os.path.join(SDK, "phase_states_v2.json")


def _states():
    """我标注的工艺状态段(239 点): [{'i0','i1','name','color','kind','p0','p1','s_mm'}]
    真源 zmax_data/rokae_sdk/phase_states_v2.json, 由 tools/make_v2_states.py 按几何拐点生成。
    (老倪 2026-11-21「239 个点, 更新到相位图 S1, 自己标注状态」)"""
    try:
        d = json.load(open(_STATES_F, encoding="utf-8"))
        st = d.get("states") or []
        return st if st else []
    except Exception:                                                    # noqa: BLE001
        return []


def _states_payload(bl=None):
    """把状态段 + 实测块耗时合并成环上要画的东西: 每段 i0/i1/name/color/kind + 实测秒数 + 弧长。"""
    st = _states()
    if not st:
        return []
    _phd = _load(os.path.join(SDK, _setf("traj_phase.json")), "phase") or {}
    ss = [f.get("s") for f in (_phd.get("frames") or [])]
    out = []
    tot = 0.0
    for s in st:
        a, b = int(s["i0"]), int(s["i1"])
        t = 0.0
        for x in (bl or []):
            lo, hi = max(a, x["i0"]), min(b, x["i1"])
            if hi < lo:
                continue
            n = max(1, x["i1"] - x["i0"] + 1)
            t += (x.get("t_s") or 0.0) * ((hi - lo + 1) / n)
        tot += t
        r = dict(s)
        r["t_s"] = round(t, 2)
        if ss and 0 <= a < len(ss):
            r["s0"] = ss[a]
            r["s1"] = ss[min(b, len(ss) - 1)]
        out.append(r)
    for r in out:
        r["t_frac"] = round((r["t_s"] / tot), 4) if tot else 0.0
    return out


if _states():                      # 任何轨迹集有自己的状态表就用它 (v2/demo)
    # 🔴 行名 = 动作段(接近/抬升/对位/插入/退让/二次插入/微调/退出/送废/回程),
    #    不再拿"停点"当状态 —— #99 工作点与 #100 插入同坐标同弧长, 那样会切出 0 长度的缝。
    PHASES = [(s["i0"], s["i1"], s["name"]) for s in _states()]
elif SET == "v2":
    # 兜底: 状态文件缺失时退回"停点即状态"(旧口径)
    _named = [(r["i"], r.get("name") or ("#%d" % r["i"])) for r in _stops()]
    PHASES = []
    _prev = -1
    for _i, _nm in _named:
        PHASES.append((_prev + 1, _i, _nm))
        _prev = _i
    if _prev < PTS_N - 1:
        # 末帧(#238)与最后一个停点(#237)同处初始点附近 ⇒ 仍挂在最后一行, 免得清单里多出
        # 一个画布有、右侧 15 行里没有的名字(实测对不上就是这里)
        PHASES.append((_prev + 1, PTS_N - 1, (_named[-1][1] if _named else "初始点")))


def _phase_of(i0, i1):
    mid = 0.5 * (i0 + i1)
    for a, b, nm in PHASES:
        if a - 0.5 <= mid <= b + 0.5:
            return nm
    return None


def _phase_blocks(bl, ss):
    """把 0..19 帧这一段按人工确认的阶段切成行(起始点/转移/下降/抓取点/上升/转移/扫码点),
    时间按与实测块的重叠帧数摊分 —— 这样清单读起来就是老倪口述的那条工艺顺序,
    而不是被速度档碎成 0-6/7-9/10-12/13-16 这种对不上话的块。"""
    out, used_to = [], PHASES[-1][1]     # 人工阶段覆盖到哪一帧, 之后才用实测块(否则同一段会出现两行同名)
    for a, b, nm in PHASES:
        t = 0.0
        spd = 0.0
        for x in bl:
            lo, hi = max(a, x["i0"]), min(b, x["i1"])
            if hi < lo:
                continue
            n = max(1, (x["i1"] - x["i0"] + 1))
            t += (x["t_s"] or 0.0) * ((hi - lo + 1) / n)
            spd = max(spd, x.get("speed") or 0.0)
        s0 = ss[a] if a < len(ss) else 0.0
        s1 = ss[b] if b < len(ss) else 1.0
        out.append({"i0": a, "i1": b, "n_pts": b - a + 1, "t_s": round(t, 3),
                    "s0": s0, "s1": s1, "speed": spd, "err": 0.0,
                    "axis_max": 0.0, "roll_max": 0.0, "state": nm, "state_tags": []})
    rest = [x for x in bl if x["i0"] > used_to]
    return out + rest


def _sectors():
    """节拍构成: 从真机跑批日志取每一块的 (i0,i1,s0,s1,secs,speed)。

    这是"扇形的角度来源" —— 角度=相位 s(弧长真相位), 扇区耗时=实测 secs。
    同 (i,i1) 重复出现时保留最后一条(重跑覆盖)。
    """
    # demo(现场演示那一遍): 扇区直接由 phase_states_demo.json 的 31 段构成 ——
    # 没有"段跑日志"那种实测 chunk, 就用状态段的 i0/i1 换成相位 s 当扇区边界。
    if SET == "demo":
        _st = _states()
        if not _st:
            return None
        _ph = _load(os.path.join(SDK, "traj_phase_demo.json"), "phase") or {}
        _s = [f.get("s") for f in (_ph.get("frames") or [])]
        bl = []
        for k, s in enumerate(_st):
            i0, i1 = int(s["i0"]), int(s["i1"])
            s0 = _s[i0] if i0 < len(_s) and _s[i0] is not None else i0 / max(1, len(_s) - 1)
            s1 = _s[i1] if i1 < len(_s) and _s[i1] is not None else (i1 + 1) / max(1, len(_s))
            bl.append({"i0": i0, "i1": i1, "n_pts": s.get("n_pts"), "s0": float(s0),
                       "s1": float(max(s1, s0 + 1e-4)), "t_s": s.get("dur_s"),
                       "speed": None, "err": None, "axis_max": 0.0, "roll_max": 0.0,
                       "name": s.get("name"), "color": s.get("color")})
        # 扇区首尾相接(否则页面"覆盖"会 >100%: 实测 201% —— 段边界各自四舍五入后重叠)
        for _a, _b in zip(bl, bl[1:]):
            _a["s1"] = min(_a["s1"], _b["s0"])
            if _a["s1"] <= _a["s0"]:
                _a["s1"] = min(1.0, _a["s0"] + 1e-4)
        if bl:
            bl[0]["s0"] = 0.0
            bl[-1]["s1"] = 1.0
        return {"blocks": bl, "states": _st, "n_blocks": len(bl),
                "total_s": round(sum((s.get("dur_s") or 0) for s in _st), 1),
                "tiers": [], "stops": [], "source": "demo(phase_states_demo.json)"}

    blocks = {}
    mt = []
    # 🔴 段跑日志里的 i 是**相对起点**的(第二段 start=60 却从 0 记起), 两个日志混在一起会撞键,
    #   而且状态判定会错(#0~11 被当成"含 #9 合爪")。这里一律用 traj_phase 的 s 反查绝对索引。
    _ph = _load(os.path.join(SDK, _setf("traj_phase.json")), "phase") or {}
    _ss = [f["s"] for f in _ph.get("frames", [])]
    if SET == "v2":
        # v2: 扇区直接取"这趟真机回放"的实测 chunk(i0,i1,secs,speed) —— 比旧日志干净
        try:
            _sv = json.load(open(os.path.join(SDK, "sectors_v2.json"), encoding="utf-8"))
        except Exception:                                                # noqa: BLE001
            _sv = {}
        for b in (_sv.get("blocks") or []):
            if b.get("s0") is None or b.get("s1") is None:
                continue
            blocks[round(float(b["s0"]), 5)] = {
                "i0": int(b["i0"]), "i1": int(b["i1"]), "n_pts": b.get("n_pts"),
                "s0": float(b["s0"]), "s1": float(b["s1"]), "t_s": b.get("t_s"),
                "speed": b.get("speed"), "err": b.get("err"),
                "axis_max": b.get("axis_max") or 0.0, "roll_max": b.get("roll_max") or 0.0}
        if not blocks:
            return None
        mt = [os.path.getmtime(os.path.join(SDK, "sectors_v2.json"))]
        key = (tuple(mt), len(blocks))
        hit = _J.get("sectors")
        if hit and hit[0] == key:
            return hit[1]
        bl = sorted(blocks.values(), key=lambda b: b["s0"])
        # chunk 的 s0/s1 只覆盖"点", 点与点之间那段弧(31→32 …)不属于任何块 ⇒ 环上出现 53 道细缝,
        # 标题的"覆盖"只有 82%。这里把每块的 s1 拉到下一块的 s0(末块拉到 1.0),
        # 环就连续了; 耗时(t_s)不动, 只补几何。
        for _a, _b in zip(bl, bl[1:]):
            _a["s1"] = max(_a["s1"], _b["s0"])
        if bl:
            bl[-1]["s1"] = max(bl[-1]["s1"], 1.0)
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
        for b in bl:
            span = max(b["s1"] - b["s0"], 1e-9)
            b["t_per_mm"] = round((b["t_s"] or 0.0) / (span * 2454.9), 4)
            b["frac"] = round((b["t_s"] or 0.0) / tot, 4)
            b["state"] = _phase_of(b["i0"], b["i1"]) or "转移"
            tags = []
            if (b["n_pts"] or 0) <= 3:
                tags.append("碎步%d点" % b["n_pts"])
            b["state_tags"] = tags
        slow = sorted(bl, key=lambda b: -(b["t_s"] or 0))[:5]
        stops = []
        for s0 in _stops():
            i = s0["i"]
            r = dict(s0)
            if _ss and 0 <= i < len(_ss):
                r["s"] = _ss[i]
                r["s_mm"] = _ph["frames"][i].get("s_mm")
            stops.append(r)
        out = {"blocks": bl, "n_blocks": len(bl), "total_s": round(tot, 2), "tiers": tiers,
               "stops": stops, "states": _states_payload(bl),
               "holds": [r["i"] for r in stops], "holds_ms": 1000,
               "stop_rule": {"speed_frac": 0.0, "turn_deg": 0.0, "dedup": 0,
                             "note": "v2: 停点=手走重录时真停住的 15 个点"},
               "slowest": [{"i0": b["i0"], "i1": b["i1"], "t_s": b["t_s"], "s0": b["s0"],
                            "s1": b["s1"], "state": b.get("state"), "speed": b.get("speed"),
                            "n_pts": b.get("n_pts")} for b in slow]}
        _J["sectors"] = (key, out)
        return out

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
    if _ss:
        bl = _phase_blocks(bl, _ss)          # 0..19 帧按人工阶段成行, 之后保持实测块
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
        _pn = _phase_of(b["i0"], b["i1"])
        if _pn:
            st = _pn
        elif 9 in rng:
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
    for s0 in _stops():
        i = s0["i"]
        r = dict(s0)
        if _ss and 0 <= i < len(_ss):
            r["s"] = _ss[i]
            r["s_mm"] = _ph["frames"][i].get("s_mm")
        stops.append(r)
    out = {"blocks": bl, "n_blocks": len(bl), "total_s": round(tot, 2), "tiers": tiers, "stops": stops,
           "states": _states_payload(bl),
           "holds": [r["i"] for r in stops],      # 执行器要在这些帧停一下(页面删掉的就自动消失)
           "holds_ms": 1000,
           "stop_rule": {"speed_frac": STOP_SPEED_FRAC, "turn_deg": STOP_TURN_DEG, "dedup": STOP_DEDUP},
           "slowest": [{"i0": b["i0"], "i1": b["i1"], "t_s": b["t_s"], "s0": b["s0"], "s1": b["s1"],
                         "state": b.get("state"), "speed": b.get("speed"),
                         "n_pts": b.get("n_pts")} for b in slow]}
    _J["sectors"] = (key, out)
    return out


_POS0 = None                       # 首帧 TCP(mm), 用于"闭环回到起点"判定
try:
    _hp = json.load(open(os.path.join(SDK, _setf("traj_hopf.json")), encoding="utf-8"))
    _POS0 = [float(v) for v in _hp["frames"][0]["p_mm"][:3]]
except Exception:
    _POS0 = None

_PB = {"mtime": 0.0, "prog": None, "src": ""}


def playback_prog(max_age: float = 6.0):
    """执行器真相位: RT 回放每 ~10 拍把 ph(0~1) 写进 meas_*.jsonl 的每一条。

    看板原 prog 由**最近点检索**推出 —— 路径自交段会锁到另一条分支, 索引卡住 ⇒
    百分比停住(实测停 48% 而相位仍按 0.383%/s 均匀推进), 索引回跳还会让它掉回 41.5%。
    这里直接读执行器写入的相位, 只认 6s 内的那份。
    """
    import glob
    try:
        files = glob.glob(os.path.join(REPO, "zmax_data", "rokae_sdk", "logs", "meas_*.jsonl"))
        if not files:
            return None
        f = max(files, key=os.path.getmtime)
        mt = os.path.getmtime(f)
        stale = (time.time() - mt) > max_age
        if not stale and mt == _PB["mtime"] and _PB["prog"] is not None:
            return _PB
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 8192))
            tail = fh.read().decode("utf-8", "ignore").strip().splitlines()
        for line in reversed(tail):
            try:
                d = json.loads(line)
            except Exception:                                      # noqa: BLE001
                continue
            if isinstance(d.get("ph"), (int, float)):
                _PB.update({"mtime": mt, "prog": float(d["ph"]),
                            "phl": float(d.get("phl") if d.get("phl") is not None else d["ph"]),
                            "src": os.path.basename(f),
                            "hold": int(d.get("h") or 0), "hold_i": int(d.get("hi") if d.get("hi") is not None else -1)})
                # 跑完的那一趟(ph≈1)即使文件不再更新也继续认 —— 否则 6s 后显示口径掉回最近点,
                # 用户看到"来源跳变 + 100% 闪一下"
                # 🔴 不能用"跑完就一直冻结在 100%": 段跑(如 0→9)的 ph 是**段末**, 会显示 100% 而臂只在
                #    全路径 4%。超时就回到"按位姿现算"(全程跑完时最近点也是 100.0%, 数值不变只换来源)。
                if stale:
                    return None
                return _PB
    except Exception:                                              # noqa: BLE001
        return None
    return None


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

    def do_POST(self):                                                   # noqa: N802
        if urlparse(self.path).path == "/api/pts":
            return self._post_pt()
        """POST /api/stop {i, name} 改名 ; {i, del:true} 删掉这个停点"""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:                                           # noqa: BLE001
            return self._send(400, {"ok": False, "why": "bad json: %s" % e})
        try:
            i = int(body.get("i"))
        except Exception:                                                # noqa: BLE001
            return self._send(400, {"ok": False, "why": "缺少 i"})
        lab = _labels()
        cur = lab.get(str(i)) or {}
        if body.get("del"):
            cur["del"] = True
            cur.pop("name", None)
        else:
            nm = str(body.get("name") or "").strip()
            if nm:
                cur["name"] = nm[:40]
                cur.pop("del", None)
            else:                                                        # 空名 = 恢复默认
                lab.pop(str(i), None)
                _save_labels(lab)
                _J.pop("stops", None)
                _J.pop("sectors", None)          # 🔴 扇形/停点表也缓存, 不清就页面看到的还是旧名字
                return self._send(200, {"ok": True, "stops": _stops()})
        lab[str(i)] = cur
        _save_labels(lab)
        _J.pop("stops", None)
        _J.pop("sectors", None)
        return self._send(200, {"ok": True, "stops": _stops()})

    def _post_pt(self):
        """POST /api/pts {i, stop:true/false, name?} —— 打勾=这个点停 1 秒"""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            i = int(body.get("i"))
        except Exception as e:                                           # noqa: BLE001
            return self._send(400, {"ok": False, "why": "bad body: %s" % e})
        _tj, _cf = _pts_set(str(body.get("set") or "215"))
        cfg = _pts_cfg(_cf)
        cur = cfg.get(str(i)) or {}
        if "stop" in body:
            cur["stop"] = bool(body.get("stop"))
        if "name" in body:
            nm = str(body.get("name") or "").strip()
            if nm:
                cur["name"] = nm[:40]
            else:
                cur.pop("name", None)
        if cur.get("stop") or cur.get("name"):
            cfg[str(i)] = cur
        else:
            cfg.pop(str(i), None)
        tmp = _cf + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _cf)
        return self._send(200, {"ok": True, "i": i, "stop": bool(cur.get("stop")),
                                "n_stop": sum(1 for v in cfg.values() if v.get("stop"))})

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
        if p == "/api/geo":
            return self._send(200, self._geo())
        if p == "/api/pts":
            qs = parse_qs(urlparse(self.path).query)
            setn = (qs.get("set") or ["215"])[0]
            pl = _pts_list(setn)
            return self._send(200, {"ok": True, "set": setn, "n": len(pl), "pts": pl,
                                    "n_stop": sum(1 for x in pl if x["stop"]),
                                    "sets": sorted(PTS_SETS)})
        if p in ("/points", "/points/"):
            try:
                h = open(os.path.join(WEB, "points.html"), "rb").read()
            except OSError as e:
                return self._send(500, {"ok": False, "why": "点位页缺失: %s" % e})
            return self._send(200, h, "text/html; charset=utf-8")
        if p == "/healthz":
            return self._send(200, {"ok": True, "svc": "zmax-se3-geom", "ts": time.time()})
        return self._send(404, {"ok": False, "why": "not found: %s" % p})

    def _geo(self):
        """给 8815 的 A/B/C/D 面板用的几何数据(与 _live 同一套表, 换成 v2 就是 239 点)。

        字段与页面内嵌 D 完全同形: p(mm) / n / phi / q / dn / dphi / spd / s / s_mm。
        """
        traj = _load(os.path.join(WEB, _setf("real_traj_joints.json")), "traj") or {}
        hopf = _load(os.path.join(SDK, _setf("traj_hopf.json")), "hopf") or {}
        phase = _load(os.path.join(SDK, _setf("traj_phase.json")), "phase") or {}
        fr = traj.get("frames") or []
        if not fr:
            return {"ok": False, "why": "traj 缺失(%s)" % _setf("real_traj_joints.json")}
        hf = hopf.get("frames") or []
        pf = phase.get("frames") or []
        spd = [100.0] * len(fr)          # 速度档: 用 sectors 的实测块给每帧标上当时速度
        for b in ((_sectors() or {}).get("blocks") or []):
            sp = float(b.get("speed") or 100.0)
            for k in range(int(b["i0"]), min(len(fr), int(b["i1"]) + 1)):
                spd[k] = sp
        out, n_prev, phi_prev = [], None, None
        for i, f in enumerate(fr):
            q = list(f.get("p") or [0, 0, 0])
            if max(abs(c) for c in q) < 20.0:                    # 米 → mm
                q = [c * 1000.0 for c in q]
            h = hf[i] if i < len(hf) else {}
            ph = pf[i] if i < len(pf) else {}
            w, x, y, z = _quat_rpy(*(f.get("rpy") or [0.0, 0.0, 0.0])[:3])
            n = h.get("n") or [0.0, 0.0, 1.0]
            phi = float(h.get("phi_deg") if h.get("phi_deg") is not None else 0.0)
            dn = 0.0 if n_prev is None else round(math.degrees(math.acos(max(-1.0, min(1.0,
                sum(n[k] * n_prev[k] for k in range(3)))))), 3)
            dphi = 0.0 if phi_prev is None else round(phi - phi_prev, 3)
            if dphi > 180.0:
                dphi -= 360.0
            elif dphi < -180.0:
                dphi += 360.0
            out.append({"i": i, "p": [round(v, 1) for v in q[:3]], "n": [round(v, 4) for v in n],
                        "phi": round(phi, 2), "q": [round(v, 4) for v in (w, x, y, z)],
                        "dn": dn, "dphi": dphi, "spd": spd[i],
                        "s": ph.get("s"), "s_mm": ph.get("s_mm")})
            n_prev, phi_prev = n, phi
        st = _states()                       # 每个轨迹集自己的工艺状态 (v2 14 段 / demo 32 段)
        return {"ok": True, "set": SET, "n": len(out),
                "len_mm": round(float((phase.get("summary") or {}).get("len_mm") or 0.0), 1),
                "states": ({"states": st} if st else {}).get("states", []),
                "frames": out}

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
        traj = _load(os.path.join(WEB, _setf("real_traj_joints.json")), "traj")
        hopf = _load(os.path.join(SDK, _setf("traj_hopf.json")), "hopf")
        phase = _load(os.path.join(SDK, _setf("traj_phase.json")), "phase")
        out = {"ok": True, "ts": time.time(), "svc": "zmax-se3-geom", "set": SET,
               "truth_src": (tcp or {}).get("src") or "local latest.json"}
        if not traj:
            out.update({"ok": False, "why": "traj 缺失(%s)" % _setf("real_traj_joints.json")})
            return out
        # ⚠️ v2 的 frames[].p 存的是**米**, 而 demo(现场演示)存的是**毫米** ——
        #    一律 ×1000 会把 655mm 变成 655000mm, 投影就会算出"距 574 米"的鬼值(实测踩到)。
        #    按量级自动判单位: 坐标绝对值 <10 视为米。
        P = [[c * (1000.0 if max(abs(x) for x in f["p"]) < 10.0 else 1.0) for c in f["p"]]
             for f in traj["frames"]]
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
            # 🔴 闭环轨迹: 首帧与末帧同一位置(18.8mm) ⇒ 回到初始点会被最近点判成"末帧 214"显示 100%。
            #    站在初始点 = 新一趟的 0%, 所以只要贴首帧就把 i 归零。
            try:
                _p0 = _POS0 if "_POS0" in globals() else None
                if _p0 and i >= len(phase["frames"]) - 6 and \
                   sum((q[k] - _p0[k]) ** 2 for k in range(3)) ** 0.5 < 30.0:
                    i = 0
            except Exception:
                pass
            # 🔴 自交处有多个"一样近"的候选(插孔走廊被走 3 趟) ⇒ 一律取**最早**那一趟,
            #    否则页面会从第 7 行一下跳到第 12 行(老倪:"怎么跳到 12 了")。
            try:
                _c = [k for k, dv in enumerate(d) if dv <= max(3.0, _dmin + 3.0)]
                if _c and (_li is None or i > _li + 30) and min(_c) < i:
                    i = min(_c)
            except Exception:
                pass
            # 🔴 窗口/游标给出的索引若离真机 >60mm, 说明锚点已经过期(实测: 臂在插到底位
            #    818,227,190, 却被游标窗口指到 i=62 距 574m) ⇒ 退回全局最近点, 否则页面会跳到别的段。
            if i is not None and (d[i] if i < len(d) else 1e9) > 60.0:
                i = _ig
            _LAST["i"] = i
            out["tcp_mm"] = [round(v, 1) for v in q]
            out["age_s"] = round(time.time() - float(tcp.get("ts") or 0), 2)
            out["nearest"] = {"i": i, "dist_mm": round(d[i], 1)}   # 报"该点"的距离, 不报全局最小(会自相矛盾)
            if phase:
                r = phase["frames"][i]
                # s 是 S¹ 圆坐标(过 seam 回绕到 0) ⇒ 同时给 prog(单趟 0→1 单调), 界面上用它
                _s_end = float(phase.get("frames", [{}])[-1].get("s") or 1.0) or 1.0
                _p = min(1.0, float(r["s"]) / _s_end)
                # 🔴 相位不许回退: 最近点检索会在自交段来回跳(i 反复), 直接透传 s 就会出现"相位回退/调回 0"。
                #    同一趟内取高水位; 只有确实回到起点附近且上一趟已走完才允许重置。
                # 🔴 显示相位 = 执行器相位(优先) 或 最近点相位, 然后**全程高水位**;
                #    只有"换了一趟"(meas 文件名变了)才重置。之前用 `i<=2` 判新一趟 —— 路径是闭环,
                #    末段姿态离起点只有 18.8mm(帧212), 最近点一snap 到 i≈0 就会把 95% 打回去。
                _pb = playback_prog()
                if _pb and _pb.get("prog") is not None:
                    _p = float(_pb["prog"])
                    _src = "playback:%s" % _pb["src"]
                    _key = _pb["src"]
                    # 高水位只在**真在跑**时生效(同一趟 meas 文件内防回退)
                    _prev = _LAST.get("prog")
                    if _prev is not None and _LAST.get("meas_key") == _key:
                        _p = max(_p, float(_prev))
                    _LAST.update({"prog": _p, "meas_key": _key})
                else:
                    # 停了/段跑结束: 一律按"当前位姿现算", 否则高水位会把上次的 27.1% 永远钉住
                    _src, _key = "nearest", "nearest"
                    _LAST.update({"prog": _p, "meas_key": _key})
                out["nearest"].update({"s": r["s"], "s_mm": r["s_mm"], "prog": _p,
                                       "prog_pct": round(100.0 * _p, 2), "prog_src": _src,
                                       "hold": int((_pb or {}).get("hold") or 0),
                                       "hold_i": int((_pb or {}).get("hold_i") if (_pb or {}).get("hold_i") is not None else -1)})
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
            _hf = (hopf or {}).get("frames") or [{}]      # demo 集帧数不同, 硬取 [30] 会 IndexError
            ref = _hf[min(30, len(_hf) - 1)].get("n")
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
