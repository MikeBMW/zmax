#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ar_render_station.py — 🖼 render 站: 渲染帧 → L2 感知 → plan 规划 → 双臂执行 (真跑)

老倪 2026-10-29: 「再做一个 render 页面, 我要看到渲染后的图像; L2 的感知要接入渲染后的图像进行感知,
输出感知定位的结果, 你来设计方案, 给到 plan 模块进行规划, 驱动 AR 场景的左臂和右臂都进行基于
plan 节点和动作执行节点的指令, 要真正跑通 AR 场景和使用渲染真图, 模型要真运行」

## 链路 (每一环都是真跑, 无 mock / 无写死答案)
   ① 帧源   : 8802 /frame.png          ArMujocoEnv 渲染帧 960×720 (不是相机帧)
   ② L2 感知: models/yolo_ar_peg.pt    YoloPerception.detect() 真推理 → 2D 框 + conf
   ③ 3D 定位: 8802 /unproj            像素 → 台面 3D (启动时 9 点单应标定, 残差自报)
   ④ plan   : tools/dual_arm_plan.py  几何双臂规划 → 有序步骤 (L 协同 / R 主操作)
   ⑤ act    : 8802 /ik + /control     每步 IK → 下发 → 按 /state.json 真值判到位
   ⑥ 复测   : 再抓一帧 → 再跑 L2      → 与首次框对比 (闭环证据)

## 页面 (极简, 手机可看)
  左: 渲染帧 + L2 框 + 目标点    右: 感知/规划/双臂真值 + 日志

用法:
  DISPLAY=:0 MUJOCO_GL=glfw ./gui-venv311/bin/python tools/ar_render_station.py --port 8804
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))

RENDER = os.environ.get("ZMAX_RENDER_URL", "http://127.0.0.1:8802")
WEIGHTS = os.environ.get("ZMAX_AR_WEIGHTS", os.path.join(ROOT, "models", "yolo_ar_peg.pt"))
CONF = float(os.environ.get("ZMAX_L2_CONF", "0.30"))
MIN_BOX_PX = 600.0            # 渲染帧里光模块 ~90x50=4500px; <600 判为误检

CH = None          # 🧩 引擎链 (ss_station_engine.StationChain), 首次用时初始化
ST = {"phase": "idle", "cycle": 0, "ts": 0.0, "frame_ts": 0.0, "frame_age": None,
      "img_bytes": 0, "l2": {}, "perc": {}, "plan": {}, "act": {"steps": [], "cur": None},
      "truth": {}, "calib": {}, "log": [], "err": None, "auto": False,
      "perf": {}, "recheck": {}, "live": {}, "proj": {}, "view": "ar3d",
      "chain": {}}
IMG = {"close": b"", "ar3d": b"", "n": 0}
VIEW_CAL = {"close": None, "ar3d": None}
LOCK = threading.Lock()
RUNQ = {"go": 0}


def log(msg):
    line = "%s %s" % (time.strftime("%H:%M:%S"), msg)
    with LOCK:
        ST["log"] = (ST["log"] + [line])[-60:]
    print(line, flush=True)


def http_get(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def http_json(url, timeout=8):
    return json.loads(http_get(url, timeout).decode("utf-8"))


def http_post(url, obj, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ─────────── L2 感知 (真模型, 渲染帧) ───────────
class L2:
    def __init__(self):
        self.yp = None
        self.info = {}

    def load(self):
        if self.yp is None:
            from lerobot.perception.yolo import YoloPerception
            self.yp = YoloPerception(weights=WEIGHTS, cam=None)
            self.yp._load()
            names = list(getattr(self.yp, "names", {}).values()) if isinstance(
                getattr(self.yp, "names", {}), dict) else getattr(self.yp, "names", [])
            self.info = {"weights": os.path.basename(WEIGHTS), "classes": names[:12],
                         "conf": CONF}
            log("L2 权重加载: %s · 类别 %s" % (self.info["weights"], names[:6]))
        return self.yp

    def detect(self, img_bgr):
        yp = self.load()
        t0 = time.time()
        # detect_all: 同一帧所有框 (detect() 每类只留一个, 多实例会丢)
        dets = yp.detect_all(img_bgr, conf=CONF, already_bgr=True) or []
        ms = (time.time() - t0) * 1000
        cands = [{"cls": d["cls"], "conf": float(d.get("conf") or 0),
                  "box": [float(v) for v in d.get("box") or [0, 0, 0, 0]]} for d in dets]
        cands.sort(key=lambda c: -c["conf"])
        # 类别优先 (gold/module/peg), 同类取面积最大; 面积闸: 渲染帧里模块约 90x50px
        def area(c):
            b = c.get("box") or [0, 0, 0, 0]
            return max(0.0, (b[2] - b[0]) * (b[3] - b[1]))
        gold = [c for c in cands
                if any(k in str(c["cls"]).lower() for k in ("gold", "module", "peg", "opt"))]
        pool = gold or cands
        pool.sort(key=lambda c: (-area(c), -c["conf"]))
        best = pool[0] if pool else None
        if best is not None and area(best) < MIN_BOX_PX:
            best = None          # 小框 = 别的东西/误检, 不冒充光模块定位
        return {"ok": best is not None, "best": best, "n": len(cands), "ms": round(ms, 1),
                "conf": round(best["conf"], 3) if best else None,
                "weights": self.info.get("weights"), "cands": cands[:5],
                "raw_ms": round(ms, 1)}


L2M = L2()


# ─────────── 一次闭环 ───────────
def _chain():
    """🧩 引擎链单例 (六层真源码, 首次调用时加载)。"""
    global CH
    if CH is None:
        import ss_station_engine as SSE
        CH = SSE.StationChain()
        log("🧩 引擎链接入: 前馈 loaded=%s · 物理闸 dt=%.3fs · 安全限幅 %.2f"
            % (CH.ff.loaded, CH.dt, CH.limit))
    return CH


def proj_px(cam, xyz):
    """世界点 → 该视角像素 (用 8802 /calib.json 的 P)。取不到就返回 None, 不瞎画。"""
    cal = VIEW_CAL.get(cam) or {}
    Pm = cal.get("P")
    if not Pm or not xyz:
        return None
    a = Pm[0][0] * xyz[0] + Pm[0][1] * xyz[1] + Pm[0][2] * xyz[2] + Pm[0][3]
    b = Pm[1][0] * xyz[0] + Pm[1][1] * xyz[1] + Pm[1][2] * xyz[2] + Pm[1][3]
    c = Pm[2][0] * xyz[0] + Pm[2][1] * xyz[1] + Pm[2][2] * xyz[2] + Pm[2][3]
    if abs(c) < 1e-12:
        return None
    return [round(a / c, 1), round(b / c, 1)]


def live_feed():
    """常驻实时取流: 两路视角各 ~6Hz 拉帧 + 0.5Hz 拉真值/标定 ⇒ 页面不再是一张静止图。

    🔴 原来只在跑闭环时才更新一帧 (perceive_once 里写 IMG) ⇒ 页面看着"不动"。
    """
    last_cal = 0.0
    while True:
        try:
            for cam in ("ar3d", "close"):
                try:
                    raw = http_get("%s/frame.png?cam=%s" % (RENDER, cam), timeout=4)
                    with LOCK:
                        IMG[cam] = raw
                except Exception:                                            # noqa: BLE001
                    pass
            stt = http_json(RENDER + "/status.json")
            tru = http_json(RENDER + "/state.json")
            if time.time() - last_cal > 30:
                try:
                    cal = http_json(RENDER + "/calib.json").get("calibs") or {}
                    with LOCK:
                        VIEW_CAL.update({k: cal.get(k) for k in ("close", "ar3d")})
                    last_cal = time.time()
                except Exception:                                            # noqa: BLE001
                    pass
            truth = tru.get("truth") or {}
            with LOCK:
                view = ST.get("view") or "ar3d"
                ST["live"] = {"n": stt.get("n"), "age_s": stt.get("age_s"),
                              "views": {k: {"gold_px": (v or {}).get("gold_px"),
                                            "box": (v or {}).get("box")}
                                        for k, v in (stt.get("views") or {}).items()},
                              "same_frame": True}
                ST["truth_live"] = truth
                ST["cal_view"] = {k: {"res_px": (v or {}).get("res_px_med"),
                                      "res_plane": (v or {}).get("res_plane_px_med")}
                                  for k, v in VIEW_CAL.items() if v}
                if truth:
                    ST["proj"] = {k: proj_px(view, truth.get(k))
                                  for k in ("gold", "tcpL", "tcpR", "hole")}
        except Exception as e:                                               # noqa: BLE001
            with LOCK:
                ST["live_err"] = "%s: %s" % (type(e).__name__, e)
        time.sleep(0.16)


# 让出视野的停机位 (实测: 双臂 home 姿态正好压在机位与料盘之间, 模块被完全挡住 gold_px=0;
#   抬到 z=0.47 后 gold_px 2200+, 框回到 [420,341,506,386])
PARK_CLEAR = {"R": [0.20, -0.06, 0.55], "L": [0.20, 0.56, 0.55]}   # 双臂抬起在料盘两侧: 特写不挡(gold_px 2497)、全景两队都在画面内


def park_clear(wait=3.5):
    """双臂抬到视野外 (真值到位才算), 之后拍帧才有干净底图。

    🕊 2026-10-29: 原来是一发式无 seed/rate 的 IK ⇒ 实测 660/476/377/190mm 瞬移 (跳分支 + PD 大摆),
       这是"右臂轨迹不连续"里最大的一跳。现在走同一条平滑回放 (S 曲线 + seed + rate),
       轨迹同样由 L2 节点 n_geoplan.smooth_traj 给出。ZMAX_STATION_REPLAY=0 时退回老路径。
    """
    degs = {}
    if _REPLAY:
        cur = {"L": None, "R": None, "gripL": 0.0, "gripR": 0.0}
        okn = 0
        for side, xyz in PARK_CLEAR.items():
            r = exec_replay(side, list(xyz), "抬起(让出视野)", cur, tol=8.0, log=log, idx=0, grip=0.0)
            if r and r.get("deg"):
                degs[side] = r["deg"]
                okn += 1
        if okn == 2:
            http_post(RENDER + "/control", {"mode": "sim", "L": degs["L"], "R": degs["R"],
                                            "gripL": 0.0, "gripR": 0.0})
            time.sleep(wait)
            try:                       # 停到位切 idle, 画面恢复"活"的微动 (否则帧不动像卡死)
                http_post(RENDER + "/control", {"mode": "idle"})
            except Exception:                                                # noqa: BLE001
                pass
            # ⚠ 必须回 {"ok": True}: boot_scene 拿 r.get("ok") 判成没成功 ⇒ 重试 12 次,
            #   每次都再 park 一遍 ⇒ 同一个摆场动作和闭环控制环互抢 (实测步骤2 到位 190mm)。
            return {"ok": True, "deg": degs, "src": "replay_smooth"}
        log("⚠ park_clear 平滑回放未成功 (%d/2) → 退老路径" % okn)
    for side, xyz in PARK_CLEAR.items():
        ik = http_json("%s/ik?side=%s&x=%.4f&y=%.4f&z=%.4f" % (RENDER, side, xyz[0], xyz[1], xyz[2]))
        if ik.get("ok"):
            degs[side] = ik["deg"]
    if len(degs) == 2:
        http_post(RENDER + "/control", {"mode": "sim", "L": degs["L"], "R": degs["R"],
                                        "gripL": 0.0, "gripR": 0.0})
        time.sleep(wait)
        # 停到位后切回 idle: 臂保持当前姿态, 画面恢复"活"的微动 (模块小幅漂移+机位微抖),
        # 否则 sim 模式没有新指令 ⇒ 帧永远不变, 页面看着像卡死 (实测 md5 两次一致)
        try:
            http_post(RENDER + "/control", {"mode": "idle"})
        except Exception:                                                    # noqa: BLE001
            pass
        return {"ok": True, "deg": degs}
    log("⚠ park_clear IK 不可达: %s" % list(degs))
    return {"ok": False, "deg": degs}


def perceive_once():
    """抓 8802 渲染帧 → L2 → 2D→3D。返回 (l2, perc, jpg, frame_ts, calib)。

    前置闸: 8802 的金色像素数 (场景真值) 太少 ⇒ 模块根本不在画面里 (被臂挡住/已在场外),
    这时不拿模型去"硬凑一个框", 直接如实返回 ok=False。
    """
    import cv2
    import numpy as np
    stt = http_json(RENDER + "/status.json")
    if float(stt.get("gold_px") or 0) < 300:
        return ({"ok": False, "err": "画面里无模块 (gold_px=%s)" % stt.get("gold_px"),
                 "ms": 0, "n": 0, "conf": None, "best": None,
                 "weights": L2M.info.get("weights")},
                {"ok": False, "err": "画面里无模块像素"}, b"", float(stt.get("ts") or 0),
                (stt.get("calib") or {}))
    raw = http_get(RENDER + "/frame.png")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("渲染帧解不开 (8802 /frame.png)")
    # 🔴 通道口径实测 (2026-10-29, 同一帧): 喂 imdecode 的 BGR 原样 → conf 0.964 框 [449,363,541,411];
    #    先转 RGB 再进 detect() (它内部又 RGB2BGR) → 同一目标只有 0.307, 还多出 0.399 的假框。
    #    ⇒ 在役 AR 权重吃的是 BGR 原样, 必须原样喂, 不要多转一次。
    l2 = L2M.detect(img)
    # ① 感知归口: 本拍 L2 结果写 `/dev/shm/l2_det.json` (引擎常驻回路 + 画布 n_yolo 读同一份),
    #    写完回读确认 —— 不假设"写过了"就是"进状态空间了"。
    try:
        _sh = _chain().put_det(l2, img_url=RENDER + "/frame.png?cam=close")
        l2["shared"] = {"ok": bool(_sh.get("ok")), "file": _sh.get("file"),
                        "n": _sh.get("readback_n"), "src": _sh.get("readback_src")}
    except Exception as e:                                                   # noqa: BLE001
        l2["shared"] = {"ok": False, "err": "%s: %s" % (type(e).__name__, e)}
    perc = {"ok": False}
    if l2["ok"]:
        x1, y1, x2, y2 = l2["best"]["box"]
        u, v = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        try:
            r = http_json("%s/unproj?u=%.2f&v=%.2f" % (RENDER, u, v))
            if r.get("ok"):
                # 单应反解给的是台面高度; 目标点取模块自身高度 (台面 + 模块半厚)
                cal = stt.get("calib") or {}
                z_gold = float(cal.get("plane_z") or r["z"]) + 0.012
                perc = {"ok": True, "xyz": [round(r["x"], 5), round(r["y"], 5), round(z_gold, 5)],
                        "uv": [round(u, 1), round(v, 1)], "src": "L2 2D框中心 + 台面单应反解",
                        "plane": r.get("z")}
        except Exception as e:                                               # noqa: BLE001
            perc = {"ok": False, "err": "反解失败: %s" % e}
    with LOCK:
        # 🔗 ssaoi / sstactile 等旁挂节点要的"本拍真实输入": 帧级指标 (不是编的检测结论)
        ST["frame_stat"] = {"mean": round(float(img.mean()), 2), "shape": list(img.shape),
                            "det_n": (l2 or {}).get("n"), "conf": (l2 or {}).get("conf")}
    _, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return l2, perc, jpg.tobytes(), float(stt.get("ts") or 0), (stt.get("calib") or {})



# ── 🕊 平滑回放执行器 (2026-10-29 老倪: 「要动作和平滑的 UPH 轨迹一样, 而且要由 L2 节点实际发出」) ──
#   轨迹来源 = L2 节点 n_geoplan 的 smooth_traj (同一份实现, 不是另写一套): 五次多项式 S 曲线,
#   峰值速度 = 段 v_cap, 峰值加速度 = a_max, 首末速度 0 ⇒ 起停不顿。
#   执行端只做三件事: ①按时间采样 (20ms) ②小增益真值纠偏 (补 PD 静差) ③IK 带 seed + rate, 不换分支。
#   切回老 P 环: ZMAX_STATION_REPLAY=0
_REPLAY = (os.environ.get("ZMAX_STATION_REPLAY", "1") != "0")
_REPLAY_DT = float(os.environ.get("ZMAX_REPLAY_DT", "0.02"))       # 20ms = 50Hz 采样
_REPLAY_RATE = float(os.environ.get("ZMAX_REPLAY_RATE_DEG", "3"))  # IK 每拍关节限速 (50Hz 折算)
_REPLAY_K = float(os.environ.get("ZMAX_REPLAY_K", "0.35"))         # 纠偏增益
_REPLAY_CORR_MM = float(os.environ.get("ZMAX_REPLAY_CORR_MM", "6"))


def exec_replay(side, tgt, action, cur, tol, log, idx=0, grip=None, a_max=2.0):
    """按 L2 节点给的 S 曲线轨迹回放到真机位姿 (mujoco)。返回与老链路同形的 rec。"""
    from lerobot.engineering.nodes import geo_plan_impl          # 同一份 L2 实现 (n_geoplan)
    t0 = time.time()
    st = http_json(RENDER + "/state.json") or {}
    tr = st.get("truth") or {}
    tcp0 = tr.get("tcp" + side)
    if not tcp0:
        return None
    try:
        ch = _chain()
        sk = ch.skill_info(ch.stage_for(action))
    except Exception:                                            # noqa: BLE001
        sk = {}
    v_cap = float(sk.get("v_cap_m_s") or 0.35)
    traj = geo_plan_impl.smooth_traj(tcp0, tgt, v_cap=v_cap, a_max=a_max, dt=_REPLAY_DT)
    if not traj.get("ok"):
        return None
    log("🕊 平滑回放 步骤%d %s %s · S曲线 T=%.2fs · %d拍@%.0fms · 峰速%.0fmm/s · 峰加速度%.2fm/s² · 轨迹源=L2 n_geoplan.smooth_traj"
        % (idx, side, action, traj["T"], traj["n"], _REPLAY_DT * 1000,
           traj["v_peak_mm_s"], traj["a_peak_m_s2"]))
    dt = traj["dt"]
    cap_m = v_cap * dt * 1.5                       # 单拍位移上限 (轨迹 7mm + 纠偏余量)
    best, reached, ik_used, n_sent = 9999.0, False, None, 0
    last_deg = cur.get(side) or None               # ⭐ 跨步保留 seed: 段首第一拍也不换 IK 分支
    t_start = time.monotonic()
    prev_cmd = list(tcp0)
    # ⚠ 不追帧: 迭代比 dt 慢时, 原来的"对齐到时刻表"会连发两条指令 (实测 2.5°×2 = 5°/31ms
    #   ⇒ 换算到末端 1.3m/s 的猛冲)。这里改成"落后就丢过期的点, 每 dt 最多下发一次"。
    k_idx = 0
    _npts = len(traj["pts"])
    while k_idx < _npts:
        want = t_start + k_idx * dt
        now = time.monotonic()
        if want > now:
            time.sleep(want - now)
        _behind = int((time.monotonic() - t_start) / dt)
        if _behind > k_idx + 1:
            k_idx = min(_behind, _npts - 1)
        pt = traj["pts"][k_idx]
        tr = (http_json(RENDER + "/state.json") or {}).get("truth") or {}
        tcp = tr.get("tcp" + side)
        if not tcp:
            k_idx += 1
            continue
        d_mm = sum((tgt[i] - tcp[i]) ** 2 for i in range(3)) ** 0.5 * 1000.0
        best = min(best, d_mm)
        if d_mm <= tol:
            reached = True
            break
        # 指令点 = 轨迹点 + 小增益纠偏 (限 6mm)
        cmd = []
        for i in range(3):
            corr = max(-_REPLAY_CORR_MM / 1000.0, min(_REPLAY_CORR_MM / 1000.0,
                                                      _REPLAY_K * (pt[i] - tcp[i])))
            cmd.append(pt[i] + corr)
        # 🔗 L2 全链 (2026-10-29 老倪: "所有 L2 节点都接上, 保证都运行, 可逐个开关"):
        #   每个采样点跑一遍 17 个 L2 节点; 指令点优先用**预测位姿**(帧间连续),
        #   但只在与轨迹点同侧且偏差 <8mm 时采用 —— 外推跑偏就退回轨迹点 (不拿预测当真相)。
        _l2 = _chain().l2()
        if _l2 is not None:
            try:
                _tr_all = (http_json(RENDER + "/state.json") or {}).get("truth") or {}
                _pe = ST.get("perc") or {}
                _obs = _chain().obs43(
                    tcp, _tr_all.get("grip" + side), _pe.get("xyz") or _tr_all.get("gold"),
                    (ST.get("plan") or {}).get("hole") or _tr_all.get("hole"),
                    _tr_all.get("goal") or _tr_all.get("gold"),
                    _tr_all.get("q" + side), _tr_all.get("dq" + side), _tr_all.get("rot" + side))
                _ctx = {"t": time.time(), "dt": dt, "tgt": tgt, "pos": list(tcp), "action": action,
                        "obs43": _obs, "l2": ST.get("l2"), "perc": _pe,
                        "frame_stat": ST.get("frame_stat"), "mem_tmpl": ST.get("mem_tmpl"),
                        "cmd_xyz": list(pt), "err_m": d_mm / 1000.0}
                _r = _l2.run(_ctx)
                _cp = _r.get("cmd_xyz")
                if _cp:
                    _dd = sum((_cp[i] - pt[i]) ** 2 for i in range(3)) ** 0.5
                    _same_side = all((_cp[i] - tcp[i]) * (tgt[i] - tcp[i]) >= -1e-9 for i in range(3))
                    if _dd < 0.008 and _same_side:
                        cmd = list(_cp)
                with LOCK:
                    ST["l2_nodes"] = _l2.status()
            except Exception as _e:                                          # noqa: BLE001
                with LOCK:
                    ST["l2_nodes"] = {"err": "%s: %s" % (type(_e).__name__, _e)}
        # 安全校验: 相对上一条指令的单拍位移不得超过 cap (超了沿方向截断, 不跳)
        step = [cmd[i] - prev_cmd[i] for i in range(3)]
        sn = sum(v * v for v in step) ** 0.5
        if sn > cap_m > 0:
            cmd = [prev_cmd[i] + step[i] * (cap_m / sn) for i in range(3)]
        _seed = ",".join("%.2f" % v for v in last_deg) if last_deg else ""
        url = "%s/ik?side=%s&x=%.5f&y=%.5f&z=%.5f&rate=%g%s" % (
            RENDER, side, cmd[0], cmd[1], cmd[2], _REPLAY_RATE, ("&seed=" + _seed) if _seed else "")
        ik = http_json(url)
        if not ik.get("ok"):
            # ⚠ rate=3°/拍对 50mm 级误差太小 ⇒ 解被限幅后判不可达 ⇒ 永远原地 (实测步骤2 卡 52.7mm)。
            #   升档到 14° 重试一次: 仍是同一条 seed 的最近解, 只是允许本拍多走一点。
            # ⚠ 升档只到 2.5°/拍: 实测 PD 指令-真值几乎 1:1 跟得上 (cmdΔ 5.3° ↔ actΔ 5.7°),
            #   所以"快"完全是**指令快** —— 之前升到 8°/拍 ⇒ 42mm/32ms = 1.3m/s 的猛冲。
            ik = http_json("%s/ik?side=%s&x=%.5f&y=%.5f&z=%.5f&rate=1.0%s" % (
                RENDER, side, cmd[0], cmd[1], cmd[2], ("&seed=" + _seed) if _seed else ""))
            if not ik.get("ok"):
                k_idx += 1
                continue
        ik_used = ik
        last_deg = list(ik["deg"])
        prev_cmd = cmd
        cur[side] = ik["deg"]
        if grip is not None:
            cur["grip" + side] = float(grip)
        http_post(RENDER + "/control", {"mode": "sim", "L": cur.get("L"), "R": cur.get("R"),
                                       "gripL": cur.get("gripL") or 0.0, "gripR": cur.get("gripR") or 0.0})
        n_sent += 1
    # 🎯 收尾逼近: S 曲线走完若还差 (PD 滞后/静差) ⇒ 20ms 小步闭环补到位, 每拍 ≤5mm
    #    (不加这一段会停在 40~50mm: 轨迹给的是理想点, 机械臂跟不上就再也不动了 — 实测步骤2 46.8mm)
    t_end = time.monotonic() + 6.0
    n_settle = 0
    while (not reached) and time.monotonic() < t_end:
        tr = (http_json(RENDER + "/state.json") or {}).get("truth") or {}
        tcp = tr.get("tcp" + side)
        if not tcp:
            time.sleep(_REPLAY_DT)
            continue
        err = [tgt[i] - tcp[i] for i in range(3)]
        d_mm = sum(v * v for v in err) ** 0.5 * 1000.0
        best = min(best, d_mm)
        if d_mm <= tol:
            reached = True
            break
        k_gain = 0.6
        step = [v * k_gain for v in err]
        sn = sum(v * v for v in step) ** 0.5
        cap_ = 0.003
        if sn > cap_:
            step = [v * (cap_ / sn) for v in step]
        cmd = [tcp[i] + step[i] for i in range(3)]
        _seed = ",".join("%.2f" % v for v in last_deg) if last_deg else ""
        ik = http_json("%s/ik?side=%s&x=%.5f&y=%.5f&z=%.5f&rate=1.0%s" % (
            RENDER, side, cmd[0], cmd[1], cmd[2], ("&seed=" + _seed) if _seed else ""))
        if not ik.get("ok"):
            ik = http_json("%s/ik?side=%s&x=%.5f&y=%.5f&z=%.5f&rate=1.5%s" % (
                RENDER, side, cmd[0], cmd[1], cmd[2], ("&seed=" + _seed) if _seed else ""))
        if ik.get("ok"):
            ik_used = ik
            last_deg = list(ik["deg"])
            cur[side] = ik["deg"]
            prev_cmd = cmd
            http_post(RENDER + "/control", {"mode": "sim", "L": cur.get("L"), "R": cur.get("R"),
                                           "gripL": cur.get("gripL") or 0.0, "gripR": cur.get("gripR") or 0.0})
            n_sent += 1
            n_settle += 1
        time.sleep(_REPLAY_DT)
    rec = {"i": 0, "side": side, "action": action, "ok": reached,
           "ik_mm": (ik_used or {}).get("err_mm"), "reached_mm": round(best, 1), "tol_mm": tol,
           "passes": n_sent, "deg": (ik_used or {}).get("deg"), "grip": cur.get("grip" + side),
           "chain": {"path": "replay", "src": "L2 n_geoplan.smooth_traj", "settle_ticks": n_settle,
                     "T_s": traj["T"], "n_pts": traj["n"], "sent": n_sent,
                     "v_cap_m_s": v_cap, "peak_v_mm_s": traj["v_peak_mm_s"]},
           "ms": round((time.time() - t0) * 1000)}
    return rec


def act_execute(plan, tol_default=12.0):
    """按步骤执行: IK → 下发 (两臂同帧) → 等真值到位。每步留证。"""
    cur = {"L": None, "R": None, "gripL": 0.0, "gripR": 0.0}
    out = []
    for s in plan.get("steps") or []:
        side = s["side"]
        tgt = s["xyz"]
        tol = float(s.get("tol_mm") or tol_default)
        t0 = time.time()
        if "夹" in str(s.get("action")) or "松" in str(s.get("action")):
            # 夹爪步骤: TCP 不动, 等夹爪沉降后按指令生效判
            http_post(RENDER + "/control", {"mode": "sim", "L": cur["L"], "R": cur["R"],
                                            "gripL": cur["gripL"], "gripR": cur["gripR"]})
            time.sleep(1.6)
            rec = {"i": s["i"], "side": side, "action": s["action"], "ok": True,
                   "ik_mm": None, "reached_mm": None, "tol_mm": 0,
                   "grip": cur["grip" + side], "ms": round((time.time() - t0) * 1000)}
            out.append(rec)
            with LOCK:
                ST["act"] = {"steps": out, "cur": s["i"]}
            log("✓ 步骤%d %s %s · 夹爪 %.2f · %dms" % (s["i"], side, s["action"],
                                                      cur["grip" + side], rec["ms"]))
            continue
        # 🕊 平滑回放 (默认): 轨迹由 L2 节点 n_geoplan 出, 执行端按 20ms 采样回放
        if _REPLAY:
            _r = exec_replay(side, tgt, s.get("action"), cur, tol, log, idx=s["i"],
                             grip=float(s.get("grip") or 0.0))
            if _r is not None:
                _r["i"] = s["i"]
                out.append(_r)
                with LOCK:
                    ST["act"] = {"steps": out, "cur": s["i"]}
                log("%s 步骤%d %s %s · 到位 %.1fmm (tol %s) · %d拍 · %dms"
                    % ("✓" if _r["ok"] else "⚠", s["i"], side, s["action"],
                       _r["reached_mm"], tol, _r["passes"], _r["ms"]))
                continue
        # 🧩 过引擎链执行: 每拍 u_ff → decide(原子技能物理闸 SK01-08 + 五条物理约束)
        #    → safety.saturate → 应用增量 → IK 下发 → 真值回读。执行端不二次削 (单点削)。
        ch_eng = _chain()
        best, reached, ik_used, ticks = 9999.0, False, {}, 0
        trail = []
        hist = []
        last_deg = {}          # 本步逐拍 IK 的 seed (上一条指令), 防跳分支
        _chain().reset_gate()          # 新一步: 清闸的上一拍速度/加速度 (防第一拍被旧方向拖)
        for tick in range(120):
            hist.append(best)
            # 停摆判据: 最近 30 拍内最小误差没有改善 0.5mm 才算停摆 (逐拍比会误判 —— 单拍内
            # 只走 0.2mm 是正常的, 之前按"每拍都比上一拍好 0.2mm"卡, 会在第 55 拍误断)
            # 只跟"30 拍前的最好成绩"比: 拿 min(hist[-30:]) 比是反的 (best 本就是历史最小值,
            # best > min - 0.5 恒真 ⇒ 在第 30 拍必断, 长距离撤离被误杀: 实测 400mm→70mm 就断了)
            if len(hist) > 31 and best > hist[-31] - 0.5:
                log('⚠ 步骤%d %s 伺服停摆 (30 拍停在 %.1fmm) → 判未到位' % (s['i'], side, best))
                break
            tr = (http_json(RENDER + "/state.json") or {}).get("truth") or {}
            tcp = tr.get("tcp" + side)
            if not tcp:
                time.sleep(0.1)
                continue
            if (os.environ.get("ZMAX_STATION_CHAIN") or "skill").strip().lower() == "plan":
                # 🧩 完整链 (老倪 2026-10-29 定序): 感知→obs43→运动规划(测地线块)‖前馈MLP
                #   →λ加权→动作调制器→安全限幅→技能派发→执行器。技能不再产 u_ff, 只做派发。
                _pe = ST.get("perc") or {}
                _peg = _pe.get("xyz") or tr.get("gold")
                _hole = (ST.get("plan") or {}).get("hole") or tr.get("hole")
                _obs = ch_eng.obs43(tcp, tr.get("grip" + side), _peg, _hole,
                                    tr.get("goal") or tr.get("gold"),      # [33:36] 环境目标点
                                    tr.get("q" + side), tr.get("dq" + side), tr.get("rot" + side))
                ch = ch_eng.tick_plan(side, _obs, s["action"], seg_target=tgt)
                if not ch.get("ok"):
                    log('⚠ 步骤%d %s 规划出不了块: %s → 判未到位' % (s['i'], side, ch.get("why")))
                    break
            else:
                ch = ch_eng.tick(side, tcp, tgt, s["action"], grip=float(s.get("grip") or 0.0))
            ticks = ch["i"] if not ticks else ticks + 1
            d_now = ch["dist_m"] * 1000.0
            best = min(best, d_now)
            trail.append({"i": ch["i"], "t": ch["t"], "stage": ch["stage"], "skill": ch["skill"],
                          "u_ff_src": ch["u_ff_src"], "u_ff": ch["u_ff"], "u_sat": ch["u_sat"],
                          "gate_why": ch["gate_why"], "gate_cut": ch["gate_cut"],
                          "err_mm": round(d_now, 1), "delta_mm": ch["delta_mm"]})
            with LOCK:
                ST["chain"] = {"last": ch, "trail": trail[-40:], "stats": dict(ch_eng.stats),
                               "skill_dispatch": os.path.join("zmax_data", "ss_live",
                                                              "skill_dispatch.json")}
            if d_now <= tol:
                reached = True
                break
            # 执行端伺服静差补偿 (PD 位置执行器有 6~12mm 重力静差): 指令点 = 目标 + 残差,
            # 限幅 30mm。这不是"二次削" —— 削幅只发生在引擎闸/安全限幅, 这里只是补执行器静差,
            # 不做的话闭环永远卡在静差距离上 (实测: 每步都停 9.7~39mm, 一个都到不了 8mm)。
            _sag = [max(-0.03, min(0.03, tgt[k] - tcp[k])) for k in range(3)]
            # 指令点 = 真值 + **引擎给的增量** + 执行器静差补偿 (引擎驱动, 补偿只补静差)
            _step = [ch["delta"][k] + _sag[k] for k in range(3)]
            _sn = sum(v * v for v in _step) ** 0.5
            if _sn > 0.045:                       # 每拍总位移 ≤45mm (引擎增量+静差补偿合计限幅)
                _step = [v * (0.045 / _sn) for v in _step]
            cmd_tgt = [tcp[k] + _step[k] for k in range(3)]
            _seed = ",".join("%.2f" % v for v in (last_deg.get(side) or [])) if last_deg.get(side) else ""
            ik = http_json("%s/ik?side=%s&x=%.5f&y=%.5f&z=%.5f%s&rate=14"
                           % (RENDER, side, cmd_tgt[0], cmd_tgt[1], cmd_tgt[2],
                              ("&seed=" + _seed) if _seed else ""))
            if not ik.get("ok"):
                # 增量不可达 → 直接把本段目标拿去 IK (仍由引擎给出方向, 只换步长)
                ik = http_json("%s/ik?side=%s&x=%.5f&y=%.5f&z=%.5f&rate=14%s"
                               % (RENDER, side, tgt[0], tgt[1], tgt[2],
                                  ("&seed=" + _seed) if _seed else ""))
                if not ik.get("ok"):
                    break
            ik_used = ik
            last_deg[side] = list(ik["deg"])
            cur[side] = ik["deg"]
            cur["grip" + side] = float(s.get("grip") or 0.0)
            http_post(RENDER + "/control", {"mode": "sim", "L": cur["L"], "R": cur["R"],
                                            "gripL": cur["gripL"], "gripR": cur["gripR"]})
            time.sleep(0.15)
        rec = {"i": s["i"], "side": side, "action": s["action"], "ok": reached,
               "ik_mm": (ik_used or {}).get("err_mm"), "reached_mm": round(best, 1), "tol_mm": tol,
               "passes": ticks, "deg": (ik_used or {}).get("deg"), "grip": cur["grip" + side],
               "chain": {"skill": ch_eng.skill_info(ch_eng.stage_for(s["action"])),
                         "u_ff_src": (trail[-1]["u_ff_src"] if trail else None),
                         "u_sat": (trail[-1]["u_sat"] if trail else None),
                         "gate_why": (trail[-1]["gate_why"] if trail else None),
                         "ticks": len(trail)},
               "ms": round((time.time() - t0) * 1000)}
        out.append(rec)
        with LOCK:
            ST["act"] = {"steps": out, "cur": s["i"]}
        log("%s 步骤%d %s %s · 到位 %.1fmm (tol %s) · %dms"
            % ("✓" if reached else "⚠", s["i"], side, s["action"], best, tol, rec["ms"]))
    return out, None


_CYCLE_LOCK = threading.Lock()
_RESET_DONE = False


def _load_mem_tmpl():
    """肌肉记忆模板 = 段表 sim_insert.json 里每一段的起止位姿 (真源, 不另造)。"""
    p = os.path.join(ROOT, "zmax_data", "runtime", "traj", "sim_insert.json")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        out = []
        for sg in (d.get("plan") or []):
            for key in ("a", "b"):
                v = sg.get(key)
                if isinstance(v, (list, tuple)) and len(v) >= 3:
                    out.append([float(v[0]), float(v[1]), float(v[2])])
        return out
    except Exception:                                                           # noqa: BLE001
        return []


def run_cycle():
    """感知 → 规划 → 双臂执行 → 复测。全程真跑。

    🔒 2026-10-29: 实测两次 /api/run 叠加 ⇒ 两个控制环同时下发, 互相把臂拽走
       (步骤2 到位 190.3mm / 步骤3 168mm, 采样里 118mm/37ms 的假"高速")。
       这里用非阻塞锁做**单飞**: 已有一轮在跑就忽略本次请求, 并留日志。
    """
    if not _CYCLE_LOCK.acquire(blocking=False):
        log("⚠ 已有一轮闭环在跑 ⇒ 本次 /api/run 忽略 (防两条控制环互抢)")
        return None
    try:
        return _run_cycle_inner()
    finally:
        _CYCLE_LOCK.release()


def _run_cycle_inner():
    with LOCK:
        ST.update({"phase": "perceive", "err": None})
    t_start = time.time()
    try:
        # 🔴 先回 home: 上一次执行的臂会挡住机位, 直接拍帧 ⇒ L2 检到的是臂/别的东西 (实测 152mm 定位偏差)
        try:
            # 🔴 /reset 是**场景瞬移** (双臂瞬间回 home, 实测 tcpR 一帧跳 660mm)。原来每轮都做 ⇒
            #   视频开头必然抽一下。改成默认只在进程首轮做 (ZMAX_STATION_RESET_EACH=1 恢复每轮)。
            global _RESET_DONE
            _each = os.environ.get("ZMAX_STATION_RESET_EACH", "0") == "1"
            if _each or not _RESET_DONE:
                http_post(RENDER + "/reset", {})
                _RESET_DONE = True
                time.sleep(1.2)
            park_clear(4.5)              # reset 后双臂在 home 会挡住模块 ⇒ 先抬开再拍
        except Exception as e:                                               # noqa: BLE001
            log("⚠ reset/park 失败: %s" % e)
        # 感知也要重试: 模块随 jitter 微动, 单帧可能正好被臂/反光挡住 ⇒ 最多 3 帧, 每帧都留证
        l2 = perc = None
        for pattempt in range(1, 4):
            l2, perc, jpg, fts, calib = perceive_once()
            with LOCK:
                IMG["jpg"] = jpg
                IMG["n"] += 1
            if perc.get("ok") or l2.get("ok"):
                break
            time.sleep(0.45)
        with LOCK:
            ST.update({"l2": l2, "perc": perc, "frame_ts": fts,
                       "frame_age": round(time.time() - fts, 2) if fts else None,
                       "calib": calib, "phase": "plan", "perc_attempts": pattempt})
        log("L2: %s · conf %s · n=%s · %.0fms" % ((l2.get("best") or {}).get("cls"), l2.get("conf"),
                                                 l2.get("n"), l2.get("ms", 0)))
        truth = (http_json(RENDER + "/state.json") or {}).get("truth") or {}
        # 感知精度 (对真值, 不是对像素真值框): 只作核对, 不参与控制
        if perc.get("ok") and truth.get("gold"):
            g = truth["gold"]
            perc["truth_err_mm"] = round(sum((a - b) ** 2 for a, b in
                                             zip(perc["xyz"], g)) ** 0.5 * 1000, 1)
            perc["truth"] = g
        from dual_arm_plan import DualArmPlanner
        plan = DualArmPlanner().plan(perc, truth)
        with LOCK:
            ST.update({"plan": plan, "truth": truth, "phase": "act"})
        if not plan.get("ok"):
            with LOCK:
                ST.update({"phase": "idle", "err": plan.get("reason")})
            log("⚠ 不规划: %s" % plan.get("reason"))
            return
        steps, err = act_execute(plan)
        # 复测: 等臂离开画面稳定后再抓帧, 最多 3 帧重试 (检测不到就如实报, 不编框)
        with LOCK:
            ST["phase"] = "recheck"
        time.sleep(0.9)
        l2b = percb = None
        for attempt in range(1, 4):
            l2b, percb, jpgb, ftsb, _ = perceive_once()
            with LOCK:
                IMG["jpg"] = jpgb
                IMG["n"] += 1
            if l2b.get("ok"):
                break
            time.sleep(0.7)
        with LOCK:
            ST["recheck"] = {"l2": l2b, "perc": percb, "attempts": attempt,
                             "frame_age": round(time.time() - ftsb, 2)}
        try:
            _evidence(jpgb if l2b.get("ok") else jpg, l2b, percb)
        except Exception as e:                                               # noqa: BLE001
            log("⚠ 取证图失败: %s" % e)
        try:
            _stt = http_json(RENDER + "/status.json")
            http_post(RENDER + "/control", {"mode": "idle"})
            with LOCK:
                ST["gold_px_after"] = _stt.get("gold_px")
        except Exception:                                                    # noqa: BLE001
            pass
        okn = sum(1 for s in steps if s.get("ok"))
        with LOCK:
            ST.update({"phase": "done",
                       "perf": {"cycle_ms": round((time.time() - t_start) * 1000),
                                "steps": len(steps), "ok_steps": okn},
                       "cycle": ST["cycle"] + 1, "ts": time.time(), "err": err})
        log("闭环完成: %d/%d 步到位 · 总 %dms · 复测 %s"
            % (okn, len(steps), ST["perf"]["cycle_ms"],
               "有框" if l2b.get("ok") else "无框"))
    except Exception as e:                                                   # noqa: BLE001
        import traceback
        tb = traceback.format_exc(limit=6).strip().splitlines()
        with LOCK:
            ST.update({"phase": "idle", "err": "%s: %s" % (type(e).__name__, e)})
        log("✗ 闭环异常: %s: %s" % (type(e).__name__, e))
        for ln in tb[-6:]:
            log("   " + ln)


def _evidence(jpg_bytes, l2b, percb):
    """落盘一张取证图: L2 框(绿) + 渲染真值框(青) + 定位点(黄十字) + 关键数字。"""
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(jpg_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return
    lab = http_json(RENDER + "/label.json")
    if lab.get("box"):
        b = lab["box"]
        cv2.rectangle(img, (b[0], b[1]), (b[2], b[3]), (255, 255, 0), 1)
        cv2.putText(img, "render GT", (b[0], min(img.shape[0] - 4, b[3] + 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
    if l2b.get("ok") and (l2b.get("best") or {}).get("box"):
        x1, y1, x2, y2 = [int(v) for v in l2b["best"]["box"]]
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(img, "L2 yolo_ar_peg %.2f" % float(l2b.get("conf") or 0),
                    (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    if percb and percb.get("ok") and percb.get("uv"):
        u, v = [int(round(x)) for x in percb["uv"]]
        cv2.drawMarker(img, (u, v), (0, 210, 255), cv2.MARKER_CROSS, 18, 1)
        cv2.putText(img, "3D %s" % np.round(percb["xyz"], 3).tolist(), (u + 10, v + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 210, 255), 1)
    ts = time.strftime("%H:%M:%S")
    cv2.putText(img, "%s  render->L2->plan->dual-arm  station:8805" % ts,
                (8, img.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1)
    out = os.path.join(ROOT, "zmax_data", "ss_live", "render_station_evidence.jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cv2.imwrite(out, img)
    with LOCK:
        ST["evidence"] = out
    log("取证图: %s" % out)


def _init_static():
    with LOCK:
        if not ST.get("mem_tmpl"):
            ST["mem_tmpl"] = _load_mem_tmpl()


def boot_scene():
    """开机把场景摆成"能用眼看"的状态: reset + 双腕到停机位 (两视角都能看到机器人和桌子)。

    渲染站要建 env + 27 点标定 (~10s), 早调 /reset 会 503 ⇒ 必须重试, 不能一次失败就放弃。
    """
    for attempt in range(12):
        try:
            stt = http_json(RENDER + "/status.json")
            cal = (stt.get("calibs") or {})
            ready = stt.get("ok") and cal.get("close", {}).get("ok") and cal.get("ar3d", {}).get("ok")
        except Exception:                                                    # noqa: BLE001
            ready = False
        if ready:
            try:
                http_post(RENDER + "/reset", {})
                time.sleep(1.2)
                r = park_clear(4.0)
                if r.get("ok"):
                    tru = (http_json(RENDER + "/state.json") or {}).get("truth") or {}
                    log("场景就位: 双臂停停机位 tcpL=%s tcpR=%s (两视角都可见)"
                        % (tru.get("tcpL"), tru.get("tcpR")))
                    return
            except Exception as e:                                           # noqa: BLE001
                log("开机摆场重试 #%d: %s" % (attempt + 1, e))
        time.sleep(4.0)
    log("⚠ 开机摆场未成功 (12 次重试), 等下一次闭环自会摆场")


def worker():
    while True:
        go = RUNQ.get("go", 0)
        if go > 0:
            RUNQ["go"] = go - 1
            run_cycle()
            continue
        with LOCK:
            auto = ST.get("auto")
        if auto:
            run_cycle()
            time.sleep(1.0)
            continue
        time.sleep(0.2)


PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>render · 渲染帧→L2→plan→双臂</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0b0e13;color:#d8dee9;font:13px/1.55 ui-monospace,Consolas,monospace}
header{padding:8px 12px;background:#111722;border-bottom:1px solid #223;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
h1{font-size:14px;margin:0;color:#7ee787;font-weight:600}
.b{padding:1px 7px;border:1px solid #2b3547;border-radius:9px;color:#9fb3c8;font-size:12px}
.ok{color:#3fb950;border-color:#1f6f34}.bad{color:#f85149;border-color:#7d2b26}.warn{color:#d29922;border-color:#6b5320}
main{display:grid;grid-template-columns:1.15fr .85fr;gap:10px;padding:10px;max-width:1500px;margin:0 auto}
@media(max-width:900px){main{grid-template-columns:1fr}}
.card{background:#0f1520;border:1px solid #1d2735;border-radius:8px;padding:8px 10px;margin-bottom:10px}
.card h2{font-size:12px;margin:0 0 6px;color:#79c0ff;font-weight:600;letter-spacing:.04em}
#wrap{position:relative;background:#05070a;border-radius:6px;overflow:hidden}
#im{width:100%;display:block}
#ov{position:absolute;inset:0;width:100%;height:100%}
table{width:100%;border-collapse:collapse;font-size:12px}
td,th{padding:2px 4px;border-bottom:1px solid #17202e;text-align:left;vertical-align:top}
th{color:#8b98a5;font-weight:500}
.num{color:#e6edf3}
button{background:#1f6feb;border:0;color:#fff;border-radius:6px;padding:6px 12px;font:13px ui-monospace;cursor:pointer}
button.gray{background:#30363d}button:disabled{opacity:.5;cursor:default}
#log{white-space:pre-wrap;font-size:11.5px;color:#9aa7b4;max-height:170px;overflow:auto;background:#080b10;border-radius:6px;padding:6px}
.k{color:#8b98a5}.v{color:#e6edf3}
</style></head><body>
<header>
  <h1>🖼 render 站 · 渲染帧 → L2 感知 → plan → 双臂执行</h1>
  <span id="hd" class="b">连接中…</span>
  <span id="hg" class="b">帧龄 -</span>
  <span id="hs" class="b">同帧 -</span>
  <button id="b4" class="gray">👁 视角: 全景(ar3d)</button>
  <button id="b1">▶ 跑一次闭环</button>
  <button id="b2" class="gray">🔁 自动循环: 关</button>
  <button id="b3" class="gray">⟲ 复位场景</button>
</header>
<main>
<div>
  <div class="card"><h2 id="c1">① 渲染帧 (8802 · ArMujocoEnv · 960×720) + L2 结果</h2>
    <div id="wrap"><img id="im" src="/api/frame.jpg"><canvas id="ov"></canvas></div>
    <div id="cap" style="margin-top:5px;color:#8b98a5;font-size:11.5px">—</div>
  </div>
  <div class="card"><h2>⑤ 执行步骤 (plan → act · 按真值判到位)</h2><div id="steps">—</div></div>
</div>
<div>
  <div class="card"><h2>② L2 感知 (权重 / 框 / 置信度)</h2><div id="l2">—</div></div>
  <div class="card"><h2>③ 感知定位 (2D → 台面 3D)</h2><div id="perc">—</div></div>
  <div class="card"><h2>④ plan 节点输出</h2><div id="plan">—</div></div>
  <div class="card"><h2>⑥ 双臂真值 (TCP · 关节角)</h2><div id="arms">—</div></div>
  <div class="card"><h2>⑦ 引擎链 (⚡前馈 → ⚖物理闸 → 🛡安全限幅 → 🎯技能 → 执行)</h2>
<div class="card"><div id="ch1" class="kv">u_ff -</div><div id="ch2" class="kv">u_sat -</div>
<div id="ch3" class="kv">闸 -</div><div id="ch4" class="kv">增量 -</div></div>
<h2>日志</h2><div id="log">—</div></div>
</div>
</main>
<script>
let LIVE={}, IMGN=0, SHOWOV=true, VIEW='ar3d';
const VNOTE={close:'特写 (料盘+模块 · L2 训练域)', ar3d:'全景 (与 AR 页 3D 同视角: yaw-0.9 pitch0.55 d1.6)'};
function applyView(){
  $('b4').textContent='👁 视角: '+(VIEW==='ar3d'?'全景(ar3d)':'特写(close)');
  $('c1').textContent='① 渲染帧 (8802 · ArMujocoEnv · 960×720) · '+VNOTE[VIEW];
  $('im').src='/api/frame.png?cam='+VIEW+'&t='+(IMGN++);
}
async function setView(v){ VIEW=v; applyView();
  try{ await fetch('/api/view',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({view:v})}); }catch(e){}
}
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function kw(o){return Object.entries(o||{}).map(([k,v])=>`<div><span class="k">${esc(k)}</span> <span class="v">${esc(typeof v==='object'?JSON.stringify(v):v)}</span></div>`).join('')}
async function tick(){
  try{
    const r=await fetch('/api/live',{cache:'no-store'}); LIVE=await r.json();
  }catch(e){ $('hd').textContent='连接失败'; return; }
  const p=LIVE.perf||{}, ph=LIVE.phase||'idle';
  $('hd').className='b '+(ph==='idle'&&!LIVE.err?'ok':(LIVE.err?'bad':'warn'));
  $('hd').textContent=(LIVE.err?('✗ '+LIVE.err):('phase '+ph))+' · 第'+(LIVE.cycle||0)+'轮';
  const LV=LIVE.live||{};
  $('hg').textContent='帧龄 '+(LV.age_s==null?'-':LV.age_s)+'s · n='+(LV.n==null?'-':LV.n)+' · L2 '+(LIVE.l2&&LIVE.l2.ms||'-')+'ms';
  const C=(LIVE.chain||{}), L=C.last||{}, SM=C.stats||{};
  if(L){
    $('ch1').textContent='技能 '+(L.skill||'-')+' ('+(L.stage||'-')+') · u_ff 来源 '+(L.u_ff_src||'-')+' · u_ff '+JSON.stringify(L.u_ff)+' m/s · v_cap '+(L.v_cap_m_s||0);
    $('ch2').textContent='u_sat '+JSON.stringify(L.u_sat)+' (限幅 '+((LIVE.engine&&LIVE.engine.limit)||0.6)+') · 位置误差 '+(L.err_mm!=null?(L.err_m*1000).toFixed(1):'-')+'mm';
    $('ch3').textContent='物理闸 '+(L.gate_why||'-')+(L.gate_cut?(' · 削因 '+JSON.stringify(L.gate_cut)):'');
    $('ch4').textContent='本拍增量 '+JSON.stringify(L.delta_mm)+' mm · 累计 tick '+(SM.ticks||0)+' · 闸削 '+JSON.stringify(SM.gate_cuts||{});
  }
  $('hs').textContent='两视角同帧 '+(LV.n==null?'-':('#'+LV.n))+' · 标定残差 全P '+(LIVE.cal_view&&LIVE.cal_view[VIEW]?LIVE.cal_view[VIEW].res_px:'-')+'px';
  $('cap').textContent='帧时间 '+(LIVE.frame_ts?new Date(LIVE.frame_ts*1000).toLocaleTimeString():'-')
    +' · 权重 '+(LIVE.l2&&LIVE.l2.weights||'-')
    +' · 标定残差 '+(LIVE.cal_view&&LIVE.cal_view[VIEW]?('全P '+LIVE.cal_view[VIEW].res_px+'px / 台面 '+LIVE.cal_view[VIEW].res_plane+'px'):'-')
    +' · 视角 '+(LIVE.view||'');
  const l2=LIVE.l2||{}, pe=LIVE.perc||{};
  $('l2').innerHTML=l2.ok?(
    `<div><span class="k">类别</span> <span class="v">${esc(l2.best.cls)}</span> <span class="k">conf</span> <span class="v">${l2.conf}</span> <span class="k">框数</span> <span class="v">${l2.n}</span></div>
     <div><span class="k">框 px</span> <span class="v">[${(l2.best.box||[]).map(Math.round).join(', ')}]</span></div>
     <div><span class="k">权重</span> <span class="v">${esc(l2.weights)}</span> <span class="k">耗时</span> <span class="v">${l2.ms}ms</span></div>`)
    :'<span class="bad">本帧无检测结果 (不冒充)</span>';
  $('perc').innerHTML=pe.ok?(
    `<div><span class="k">定位 xyz (m)</span> <span class="v">[${pe.xyz.join(', ')}]</span></div>
     <div><span class="k">来源</span> <span class="v">${esc(pe.src||'')}</span></div>
     <div><span class="k">与真值偏差</span> <span class="v ${pe.truth_err_mm>15?'warn':'ok'}">${pe.truth_err_mm==null?'-':pe.truth_err_mm+'mm'}</span>
       <span class="k">真值</span> <span class="v">${pe.truth?('['+pe.truth.map(v=>v.toFixed(3)).join(', ')+']'):'-'}</span></div>`)
    :'<span class="warn">无 3D 定位</span>';
  const pl=LIVE.plan||{};
  $('plan').innerHTML=pl.ok?(
    `<div><span class="k">规划器</span> <span class="v">${esc(pl.src)}</span></div>
     <div><span class="k">目标</span> <span class="v">[${(pl.target||[]).join(', ')}]</span></div>
     <div><span class="k">孔口</span> <span class="v">[${(pl.hole||[]).join(', ')}]</span></div>
     <div><span class="k">步骤</span> <span class="v">${(pl.steps||[]).length} 步</span> <span class="k">说明</span> <span class="v">${esc(pl.reason||'')}</span></div>`)
    :('<span class="warn">'+esc(pl.reason||'未规划')+'</span>');
  const st=((LIVE.act||{}).steps)||[];
  $('steps').innerHTML= st.length?('<table><tr><th>#</th><th>臂</th><th>动作</th><th>到位</th><th>ms</th></tr>'+st.map(s=>
    `<tr><td>${s.i}</td><td>${s.side}</td><td>${esc(s.action)}</td><td class="${s.ok?'ok':'warn'}">${s.reached_mm==null?'-':s.reached_mm+'mm'}</td><td>${s.ms}</td></tr>`).join('')+'</table>')
    :'—';
  const tr=LIVE.truth||{};
  $('arms').innerHTML=tr.tcpR?(
    `<table><tr><th>臂</th><th>TCP xyz (m)</th><th>关节角 (°)</th></tr>
     <tr><td>R</td><td class="num">${(tr.tcpR||[]).map(v=>v.toFixed(3)).join(', ')}</td><td>${(tr.qR||[]).map(v=>(v*57.3).toFixed(0)).join(' ')}</td></tr>
     <tr><td>L</td><td class="num">${(tr.tcpL||[]).map(v=>v.toFixed(3)).join(', ')}</td><td>${(tr.qL||[]).map(v=>(v*57.3).toFixed(0)).join(' ')}</td></tr></table>
     <div style="margin-top:4px"><span class="k">光模块</span> <span class="v">${(tr.gold||[]).map(v=>v.toFixed(3)).join(', ')}</span>
     <span class="k">孔口</span> <span class="v">${(tr.hole||[]).map(v=>v.toFixed(3)).join(', ')}</span></div>`)
    :'—';
  $('log').textContent=(LIVE.log||[]).join('\n')||'—';
  $('log').scrollTop=1e6;
  drawOv();
}
function drawOv(){
  const im=$('im'), cv=$('ov');
  const w=im.clientWidth||im.naturalWidth, h=im.clientHeight||im.naturalHeight;
  if(cv.width!==w||cv.height!==h){cv.width=w;cv.height=h;}
  const g=cv.getContext('2d'); g.clearRect(0,0,w,h);
  const sx=w/(im.naturalWidth||960), sy=h/(im.naturalHeight||720);
  const l2=LIVE.l2||{}, pe=LIVE.perc||{};
  if(VIEW==='ar3d'){
    // 全景: 画投影出来的 光模块/双腕 (用 8802 标定的 3×4 P, 不是手推)
    const pr=LIVE.proj||{}, tl=LIVE.truth_live||{};
    const mk=(p,color,label)=>{
      if(!p) return;
      const [u,v]=p; if(!(u>=-50&&u<=w+50&&v>=-50&&v<=h+50)) return;
      g.strokeStyle=color; g.lineWidth=1.6;
      g.beginPath(); g.arc(u*sx,v*sy,7,0,Math.PI*2); g.stroke();
      g.beginPath(); g.moveTo(u*sx-11,v*sy); g.lineTo(u*sx+11,v*sy);
      g.moveTo(u*sx,v*sy-11); g.lineTo(u*sx,v*sy+11); g.stroke();
      g.fillStyle=color; g.font='11px monospace';
      g.fillText(label,u*sx+10,v*sy-8);
    };
    mk(pr.tcpR,'#ff6b6b','R腕 '+(tl.tcpR?tl.tcpR.map(v=>v.toFixed(2)).join(','):''));
    mk(pr.tcpL,'#4dabf7','L腕 '+(tl.tcpL?tl.tcpL.map(v=>v.toFixed(2)).join(','):''));
    mk(pr.gold,'#ffd166','光模块 '+(tl.gold?tl.gold.map(v=>v.toFixed(3)).join(','):''));
    mk(pr.hole,'#51cf66','孔口');
    g.fillStyle='#8b98a5'; g.font='12px monospace';
    g.fillText('全景 = 同一仿真同一帧 · 双腕真值投影', 10, h-10);
    return;
  }
  if(l2.ok&&l2.best&&l2.best.box){
    const [x1,y1,x2,y2]=l2.best.box;
    g.strokeStyle='#00e676'; g.lineWidth=2; g.strokeRect(x1*sx,y1*sy,(x2-x1)*sx,(y2-y1)*sy);
    const lab=`L2 ${l2.best.cls} ${l2.conf}`;
    g.font='12px monospace'; const tw=g.measureText(lab).width;
    g.fillStyle='rgba(0,0,0,.6)'; g.fillRect(x1*sx-2,y1*sy-15,tw+6,15);
    g.fillStyle='#00e676'; g.fillText(lab,x1*sx+2,y1*sy-4);
  }
  if(pe.ok&&pe.uv){
    const [u,v]=pe.uv;
    g.strokeStyle='#ffd166'; g.lineWidth=1.5;
    g.beginPath(); g.moveTo(u*sx-9,v*sy); g.lineTo(u*sx+9,v*sy); g.moveTo(u*sx,v*sy-9); g.lineTo(u*sx,v*sy+9); g.stroke();
    g.fillStyle='#ffd166'; g.font='11px monospace';
    g.fillText('定位 '+pe.xyz.map(v=>v.toFixed(3)).join(','),u*sx+11,v*sy+4);
  }
}
$('b1').onclick=async()=>{ $('b1').disabled=true; await fetch('/api/run',{method:'POST'}); setTimeout(()=>$('b1').disabled=false,800); };
$('b2').onclick=async()=>{ const r=await fetch('/api/auto',{method:'POST'}).then(r=>r.json());
  $('b2').textContent='🔁 自动循环: '+(r.auto?'开':'关'); $('b2').className='gray'+(r.auto?'':'')};
$('b3').onclick=async()=>{ await fetch('/api/reset',{method:'POST'}); };
$('b4').onclick=()=>setView(VIEW==='ar3d'?'close':'ar3d');
setInterval(tick,700); tick(); applyView();
setInterval(()=>{ $('im').src='/api/frame.png?cam='+VIEW+'&t='+(IMGN++); },220);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):                                              # noqa: D401
        pass

    def _send(self, code, body, ctype, cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:                                                    # noqa: BLE001
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):                                                        # noqa: N802
        p = urllib.parse.urlparse(self.path).path
        if p in ("/", "/render", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if p in ("/api/frame.jpg", "/api/frame", "/api/frame.png"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            cam = (q.get("cam") or [""])[0] or None
            with LOCK:
                cam = cam or (ST.get("view") or "close")
                if cam not in ("close", "ar3d"):
                    cam = "close"
                b = IMG.get(cam) or b""
            if not b:
                self._send(503, b"no frame", "text/plain")
                return
            self._send(200, b, "image/png" if b[:4] == b"\x89PNG" else "image/jpeg")
            return
        if p == "/api/live":
            with LOCK:
                st = {k: v for k, v in ST.items() if k != "img_bytes"}
            self._json(st)
            return
        if p == "/api/l2":
            ch = _chain()
            l2 = ch.l2() if ch is not None else None
            self._json({"ok": bool(l2), **(l2.status() if l2 else {"err": "L2 链不可用"})})
            return
        if p == "/api/health":
            self._json({"ok": True, "phase": ST.get("phase"), "cycle": ST.get("cycle"),
                        "weights": L2M.info.get("weights"), "render": RENDER})
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self):                                                       # noqa: N802
        p = urllib.parse.urlparse(self.path).path
        if p == "/api/l2":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            except Exception:                                                # noqa: BLE001
                body = {}
            ch = _chain()
            l2 = ch.l2() if ch is not None else None
            if l2 is None:
                self._json({"ok": False, "err": "L2 链不可用"}, 503)
                return
            if body.get("reset"):
                l2.stats = {k: {"calls": 0, "ms": 0.0, "ok": None, "note": "未跑"}
                            for k in l2.status()["order"]}
                self._json({"ok": True, "reset": True})
                return
            if body.get("all") is not None:
                on = bool(body.get("all"))
                for k in l2.status()["order"]:
                    l2.sw[k] = on
                from ss_l2_chain import save_switches
                save_switches(l2.sw)
                self._json({"ok": True, "switches": dict(l2.sw)})
                return
            self._json(l2.set_switch(str(body.get("node") or ""), bool(body.get("on"))))
            return
        if p == "/api/run":
            RUNQ["go"] = RUNQ.get("go", 0) + 1
            self._json({"ok": True, "queued": RUNQ["go"]})
            return
        if p == "/api/view":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            except Exception:                                                # noqa: BLE001
                body = {}
            v = str(body.get("view") or "").strip()
            if v not in ("close", "ar3d"):
                self._json({"ok": False, "err": "view 只能是 close|ar3d"}, 400)
                return
            with LOCK:
                ST["view"] = v
            self._json({"ok": True, "view": v})
            return
        if p == "/api/auto":
            with LOCK:
                ST["auto"] = not bool(ST.get("auto"))
                a = ST["auto"]
            self._json({"ok": True, "auto": a})
            return
        if p == "/api/reset":
            try:
                http_post(RENDER + "/reset", {})
            except Exception as e:                                          # noqa: BLE001
                self._json({"ok": False, "err": str(e)}, 500)
                return
            with LOCK:
                ST.update({"phase": "idle", "err": None, "auto": False,
                           "plan": {}, "perc": {}, "l2": {}, "act": {"steps": [], "cur": None}})
            self._json({"ok": True})
            return
        self._send(404, b"not found", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8804)
    ap.add_argument("--warm", action="store_true", help="启动即加载 YOLO 权重")
    a = ap.parse_args()
    _init_static()                       # 肌肉记忆模板 (段表) 预载, 给 ss_mem_l2 用
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=live_feed, daemon=True).start()
    threading.Thread(target=boot_scene, daemon=True).start()
    if a.warm:
        threading.Thread(target=L2M.load, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    print("🖼 render 站 :%d · 帧源 %s · 权重 %s · 页面 /"
          % (a.port, RENDER, os.path.basename(WEIGHTS)), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
