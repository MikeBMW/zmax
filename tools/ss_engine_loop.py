#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_engine_loop.py — 流形引擎 **常驻周期循环** (全系统核心回路)

老倪 2026-10-14:
    「常驻循环在周期性调，由状态空间工程调用，流形引擎是全系统的核心，怎么只是调用一次呢？改」

改前的事实 (不是猜的):
    · ManifoldEngine.step() 全仓库只有 4 处调用: ①画布节点「🧮 流形引擎」执行时
      ②引擎自检 manifold_engine.py:823 ③hom 演示 ④bench 工具 —— **全是手跑/一次性**
    · 10Hz 常驻的 zmax-torque-bus (tools/tdrive_bus.py) 每周期算的是 T = M·(−∇Φ),
      **不经过 ManifoldEngine.step()** ⇒ 引擎核心在系统里"没有常驻回路"
    ⇒ 本脚本补上这条回路: 常驻按周期真调 `eng.step(...)`, 每周期把结果落 tap + 发 DDS,
      由**状态空间工程**驱动 (工程文件 / 活跃任务 / 主参数 M 每 5s 跟随真源变化)。

真源 (全部现读, 不造):
    状态   ← ①--state-file 外部实时源(每周期读最新一行 {"obs":[43],...})
             ②状态空间工程运行轨迹真源 data/database/zmax/sources/canvas/ss_traj_last.json
               (控制台 ▶ 运行状态空间时落盘; 每周期按 idx 滚动取一帧, 走完一圈标 replay=true)
             ③都没有 ⇒ **空转并明说** (不造状态; 一有真源立刻开始每周期调)
    工程   ← data/database/zmax/zmax_space.proj         (名称/saved_at)
    任务   ← config/ss_task_binding.json                (active_task + 名称)
    主参数 ← config/calib/zmax_manifold.json            (M)
    标定   ← models/manifold_engine.npz (在 ⇒ 用它; 不在 ⇒ 用轨迹现场 fit, 并如实标注)

输出 (与 tdrive_bus 同口径: 单一写入器 + 原子写 + 环形上限):
    tap   /dev/shm/zmax_ss_engine/engine_<scene>.jsonl   每周期一行, **最后一行才是 payload**
    快照  zmax_data/ss_live/engine_latest.json           最新一帧 (单文件覆盖, 不增长)
    状态  zmax_data/ss_live/engine_loop_status.json      周期数/实测频率/源/帧龄
    日志  每秒一行: 周期 / Hz / Φ / ‖a‖ / H(内稳态) / M / 任务 / 工程
    发布  tools/dds/ss_daemon.py 读 tap → DDS topic **zmax/ss_engine** (单写入器口径)

用法:
    gui-venv311/bin/python tools/ss_engine_loop.py run --hz 10            # 常驻
    gui-venv311/bin/python tools/ss_engine_loop.py run --hz 10 --seconds 6
    gui-venv311/bin/python tools/ss_engine_loop.py once | status | selftest
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

TAP_DIR = os.environ.get("ZMAX_SS_ENGINE_TAP_DIR") or "/dev/shm/zmax_ss_engine"
TAP_MAX_MB = float(os.environ.get("ZMAX_SS_ENGINE_TAP_MAX_MB") or 32)
LIVE_DIR = os.path.join(ROOT, "zmax_data", "ss_live")
# 🔓 2026-10-14 老倪「流形引擎的断点还是没进」: 常驻服务 (systemd) 拿着单写入器锁 ⇒ F5 起调试会话时
#   会打印「已有写入器在跑 (pid …)」**直接退出, 一次 step 都没调** ⇒ 断点当然不进。
#   `--instance <名字>` 让调试实例用自己的 tap/pid (默认 main = 常驻服务那份), 互不干扰:
#     调试实例写 /dev/shm/zmax_ss_engine_<名字>/ + zmax_data/ss_live/engine_loop_<名字>.pid
#   (守护只读主 tap ⇒ 调试实例的帧不会被当成在役帧发上 DDS, 也不会污染常驻回路的记录。)
INSTANCE = "main"
PID = os.path.join(LIVE_DIR, "engine_loop.pid")
LIVE = os.path.join(LIVE_DIR, "engine_latest.json")
STATUS = os.path.join(LIVE_DIR, "engine_loop_status.json")
TRAJ = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "ss_traj_last.json")
PROJ = os.path.join(ROOT, "data", "database", "zmax", "zmax_space.proj")
BINDING = os.path.join(ROOT, "config", "ss_task_binding.json")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
CKPT = os.path.join(ROOT, "models", "manifold_engine.npz")
STATE_DIM = 43
LATENT = 16
ACTION_DIM = 4


# 🧠 多层 pipeline 逐层真跑 (老倪 2026-10-14「所有层按 pipeline 依次全都运行推理」)
#   · 输入用**真产线帧** (8791 /aoi_modelin.png = 喂产线检测器的那张图) ⇒ L2 在役 YOLO 有真检出
#   · 每 N 周期跑一遍 L5→MEM→L2→L4→L3, 每层落一行计数 ⇒ models_manifest 探针读的是真调用, 不造假绿
PIPE_IMG_DEFAULT = os.environ.get("ZMAX_SS_PIPE_IMG") or "http://127.0.0.1:8791/aoi_modelin.png"
PIPE_TAP = os.path.join(ROOT, "zmax_data/ss_live/layer_calls.jsonl")


def _log(msg: str) -> None:
    print("[%s] %s" % (time.strftime("%F %T"), msg), flush=True)


def _j(path: str, default=None):
    try:
        with io.open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                        # noqa: BLE001
        return default


def _atomic_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _trim_tap(path: str, cap_bytes: int) -> None:
    """环形上限: 超了就只留尾部一半 (追加型流, 不许 rm 正在写的 fd)。"""
    try:
        if os.path.getsize(path) <= cap_bytes:
            return
        with open(path, "rb") as fh:
            fh.seek(max(0, cap_bytes // 2))
            tail = fh.read()
        with open(path, "wb") as fh:
            fh.write(tail)
    except Exception:                                                        # noqa: BLE001
        pass


# ─────────────────────────── 真源读取 ───────────────────────────
def read_project() -> dict:
    d = _j(PROJ, {}) or {}
    return {"project": str(d.get("name") or ""), "project_saved_at": str(d.get("saved_at") or ""),
            "canvas_source": str(d.get("canvas_source") or "")}


def read_task() -> dict:
    d = _j(BINDING, {}) or {}
    aid = str(d.get("active_task") or "")
    nm = ""
    for t in (d.get("tasks") or []):
        if isinstance(t, dict) and str(t.get("task_id")) == aid:
            nm = str(t.get("name") or "")
            break
    return {"task_id": aid, "task_name": nm}


def read_M() -> tuple[float, str]:
    """主参数 M 真源 (键名不写死 —— 按候选键取, 并回报用了哪个键)。"""
    d = _j(CALIB, {}) or {}
    for k in ("M", "m", "manifold_M", "master_M", "M_value"):
        try:
            v = float(d[k])
        except (KeyError, TypeError, ValueError):
            continue
        if 1e-9 < v < 1e6:
            return v, k
    for k in ("master_param", "calib"):
        sub = d.get(k)
        if isinstance(sub, dict):
            for kk in ("M", "m", "value"):
                try:
                    v = float(sub[kk])
                except (KeyError, TypeError, ValueError):
                    continue
                if 1e-9 < v < 1e6:
                    return v, "%s.%s" % (k, kk)
    return -1.0, ""


def read_traj(path: str) -> dict | None:
    """状态空间工程运行轨迹真源 (obs 矩阵 + 执行动作 + 场景/任务标识)。"""
    d = _j(path, None)
    if not isinstance(d, dict):
        return None
    obs = d.get("obs")
    if not isinstance(obs, list) or not obs:
        return None
    try:
        arr = np.asarray(obs, dtype=float)
    except Exception:                                                        # noqa: BLE001
        return None
    if arr.ndim != 2 or arr.shape[1] < STATE_DIM:
        return None
    return {"obs": arr, "u": d.get("u_exec_vec"), "t": d.get("t"),
            "saved_at": str(d.get("saved_at") or ""), "scene": str(d.get("scene") or ""),
            "task_id": str(d.get("task_id") or ""), "src": str(d.get("src") or ""),
            "path": path, "mtime": os.path.getmtime(path)}


def read_state_file(path: str) -> dict | None:
    """外部实时状态源: json ({\"obs\":[43]}) 或 jsonl (取最后一行)。"""
    if not os.path.isfile(path):
        return None
    try:
        if path.endswith(".jsonl"):
            last = None
            with io.open(path, encoding="utf-8") as fh:
                for ln in fh:
                    if ln.strip():
                        last = ln
            d = json.loads(last) if last else None
        else:
            d = _j(path, None)
    except Exception:                                                        # noqa: BLE001
        return None
    if not isinstance(d, dict):
        return None
    obs = d.get("obs") or d.get("state")
    try:
        v = np.asarray(obs, dtype=float).ravel()
    except Exception:                                                        # noqa: BLE001
        return None
    if v.size < STATE_DIM:
        return None
    return {"obs": v[:STATE_DIM][None, :], "u": None, "t": None,
            "saved_at": time.strftime("%F %T"), "scene": str(d.get("scene") or ""),
            "task_id": str(d.get("task_id") or ""), "src": "外部实时源 " + path,
            "path": path, "mtime": os.path.getmtime(path)}


# ─────────────────────────── 引擎构建 ───────────────────────────
def build_engine(traj: dict, M: float, inertia: bool, su2_tangent: bool = True):
    """与画布节点「🧮 流形引擎」同口径建引擎: load(models/manifold_engine.npz), 失败则现场 fit。

    su2_tangent (2026-10-19 老倪「接进 ss_engine_loop」): SU(2)≅S³ ⇒ ∇Φ 必须去掉法向分量
    (旧版只有 sphere 分支有投影, 实测法向泄漏 50.5%@k=150)。**真机下发链未动** —— 本循环只算
    方向/动作建议 (写 engine_latest + DDS), 不直接命令机械臂。
    """
    from lerobot.manifold.manifold_engine import ManifoldEngine               # noqa: PLC0415
    eng = ManifoldEngine(manifold_type="su2", latent_dim=LATENT, state_dim=STATE_DIM,
                         action_dim=ACTION_DIM, manifold_M=(M if M > 0 else 3.643),
                         inertia=bool(inertia), su2_tangent=bool(su2_tangent))
    loaded = False
    try:
        loaded = bool(eng.load(CKPT))
    except Exception:                                                        # noqa: BLE001
        loaded = False
    # 🎯 目标 = 轨迹末帧收敛态 (与画布节点「🧮 流形引擎」同口径的真值锚, 不是自选)
    #   ⚠️ 必须放在**两条路径之前**: 实测踩过 —— 只放在拟合分支里 ⇒ 加载标定那条路 goal_point=None
    #   ⇒ gradient_flow 的 Φ 恒 0、∇Φ 恒 0 (每周期动作等于没有目标的下坠: 表面"在跑", 实际无势场)。
    try:
        eng.goal_point = eng.project(traj["obs"][-1, :STATE_DIM])["p"]
        goal_note = " · 目标=轨迹末帧"
    except Exception as e:                                                   # noqa: BLE001
        eng.goal_point = None
        goal_note = " · ⚠️ 目标未设(%s)" % type(e).__name__
    if loaded:
        return eng, ("标定文件 %s%s" % (os.path.basename(CKPT), goal_note)), traj
    O = traj["obs"]
    u = traj.get("u")
    U = np.asarray(u, dtype=float)[:len(O), :ACTION_DIM] if u else np.zeros((len(O), ACTION_DIM))
    if U.shape[0] < len(O):
        U = np.vstack([U, np.zeros((len(O) - U.shape[0], ACTION_DIM))])
    try:
        eng.fit(O[:, :STATE_DIM], U)
        note = "现场拟合 (无标定文件 %s)" % os.path.basename(CKPT)
    except Exception as e:                                                   # noqa: BLE001
        note = "拟合失败(%s) → 未标定占位解码" % type(e).__name__
    return eng, note + goal_note, traj


# ─────────────────────────── 主循环 ───────────────────────────
class Loop:
    def _chunk_stage(self) -> tuple[int, str]:
        """当前八阶段 (真源 zmax_data/ss_live/trace_live.json = ss_stage 话题的同一份; 读不到就 0 + 如实标注)。"""
        try:
            d = _j(os.path.join(LIVE_DIR, "trace_live.json"), None) or {}
            _n = str(d.get("阶段") or d.get("stage") or "")
            if _n:
                for i, s_ in enumerate(["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]):
                    if s_ in _n:
                        return i, s_
            _i = d.get("idx8")
            if isinstance(_i, (int, float)):
                return max(0, min(7, int(_i))), str(_n)
        except Exception:                                                    # noqa: BLE001
            pass
        return 0, ""

    def _skill_err(self, ttl=1.0):
        """⚖ 原子技能物理偏差 (真源 zmax_data/ss_live/skill_error.json, 技能派发服务写)。

        返回该文件 dict (含 err/err_norm/big/why/phys), 帧龄 >5s 视为停更返回 None。
        """
        _now = time.time()
        if getattr(self, "_serr_cache", None) and (_now - self._serr_cache[0] < ttl):
            return self._serr_cache[1]
        _d = None
        try:
            _p = os.path.join(LIVE_DIR, "skill_error.json")
            with open(_p, encoding="utf-8") as _f:
                _d = json.load(_f)
            if _now - float(_d.get("ts") or 0.0) > 5.0:
                _d = None
        except Exception:                                                    # noqa: BLE001
            _d = None
        self._serr_cache = (_now, _d)
        return _d

    def _skill_trace(self, p: dict) -> dict:
        """⚖ 物理闸/顶层补偿 → 平铺 trace 键 (信号分析直接画)。单位: mm/s 与 mm。"""
        if not p:
            return {}
        _top = p.get("top") or {}
        _ks = {"skill闸.大偏差": (1.0 if p.get("big_stage") else 0.0),
               "skill闸.削因_速度": float((p.get("stats") or {}).get("n_cut", {}).get("速度", 0)),
               "skill闸.削因_加速度": float((p.get("stats") or {}).get("n_cut", {}).get("加速度", 0)),
               "顶层补偿_mm": float((_top.get("goal_delta_mm") or [0, 0, 0])[0] * 1000.0 / 1000.0),
               "顶层补偿_累计_mm": float(_top.get("cum_mm") or 0.0),
               "顶层补偿_次数": float(_top.get("n") or 0)}
        _en = p.get("err_norm") or {}
        if isinstance(_en, dict):
            for _st, _v in list(_en.items())[:8]:
                try:
                    _ks["skill闸.%s_偏差_mm_s" % _st] = round(float(_v) * 1000.0, 4)   # m/s → mm/s
                except Exception:                                            # noqa: BLE001
                    pass
            _ks["skill闸.末端偏差_mm_s"] = round(float(list(_en.values())[-1]) * 1000.0, 4) if _en else 0.0
        return _ks

    def _top_compensate(self, e: dict) -> dict:
        """📡 融合定位核对 → 🧮 流形引擎**顶层结构补偿** (老倪 2026-10-15)。

        口径 (为什么不是"看到大偏差就直接改结构"):
          ① 先过**融合定位**核对: 定位真值 (zmax_data/rokae_sdk/tcp_out/latest.json) 必须新鲜 (≤2s) ——
             定位是死的/在漂的时候改顶层 = 拿错基准改结构, 只会把偏差放大;
          ② 大偏差必须**持续** (同一技能连续 ≥3 拍) —— 单拍大偏差多半是换块/换段的瞬态, 不该改顶层;
          ③ 补偿量**限幅** 2mm/次 且累计封顶 20mm —— 顶层结构是小步修, 不是一把翻;
          ④ 全部落 trace (顶层补偿_mm / 顶层补偿_累计_mm / 顶层补偿_note), 界面上看得见"改了几次、改了多少"。
        """
        st = str((e.get("big_stage") or "") or "")
        out = {"goal_delta_mm": [0.0, 0.0, 0.0], "n": int(getattr(self, "_top_n", 0)),
               "cum_mm": float(getattr(self, "_top_cum", 0.0)), "note": "", "applied": 0}
        if not st:
            return out
        # ① 融合定位核对
        _age = None
        try:
            # 融合定位真值路径可用 ZMAX_FUSION_TRUTH 覆盖 (**只给离线自检用**; 现场恒为 tcp_out/latest.json)
            _p = os.environ.get("ZMAX_FUSION_TRUTH") or os.path.join(
                ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
            _age = time.time() - os.path.getmtime(_p) if os.path.isfile(_p) else None
        except Exception:                                                    # noqa: BLE001
            _age = None
        if _age is None:
            out["note"] = "🚫 融合定位无真值 (tcp_out/latest.json 不在) ⇒ 不改顶层"
            return out
        if _age > 2.0:
            out["note"] = "🚫 融合定位帧龄 %.1fs > 2s (定位可能在漂) ⇒ 不改顶层" % _age
            return out
        # ② 持续性
        if getattr(self, "_top_stage", None) == st:
            self._top_n = int(getattr(self, "_top_n", 0)) + 1
        else:
            self._top_stage = st
            self._top_n = 1
        if self._top_n < 3:
            out["note"] = "⏳ 大偏差持续 %d/3 拍 (瞬态不改顶层)" % self._top_n
            out["n"] = self._top_n
            return out
        # ③ 限幅补偿 (方向 = 偏差方向; 2mm/次, 累计 ≤20mm)
        _vec = (e.get("err") or {}).get(st) or [0.0, 0.0, 0.0]
        _v = np.asarray(_vec, float).ravel()[:3]
        _n = float(np.linalg.norm(_v))
        if _n < 1e-9:
            out["note"] = "偏差方向为 0 ⇒ 不补偿"
            return out
        if self.eng is None or getattr(self.eng, "goal_point", None) is None:
            out["note"] = "🚫 引擎无目标点 ⇒ 无处补偿"
            return out
        try:
            _step_mm = float(os.environ.get("ZMAX_TOP_COMP_MM", "2.0"))
            _cap_mm = float(os.environ.get("ZMAX_TOP_COMP_CAP_MM", "20.0"))
            _cum = float(getattr(self, "_top_cum", 0.0))
            if _cum >= _cap_mm:
                out["note"] = "⛔ 顶层补偿累计 %.1fmm 已到顶 (%.0fmm) ⇒ 停手, 交人工/重标定" % (_cum, _cap_mm)
                out["cum_mm"] = _cum
                return out
            _d = (_v / _n) * (_step_mm / 1000.0)
            _g = np.asarray(self.eng.goal_point, float).ravel().copy()
            _g[:3] = _g[:3] + _d
            self.eng.goal_point = _g
            self._top_cum = _cum + _step_mm
            out.update({"goal_delta_mm": [round(float(x * 1000.0), 4) for x in _d], "applied": 1,
                        "cum_mm": self._top_cum, "n": self._top_n,
                        "note": "✅ 顶层补偿 %.0fmm (方向=偏差方向; 累计 %.0fmm) · 融合定位帧龄 %.2fs"
                                % (_step_mm, self._top_cum, _age)})
        except Exception as ex:                                               # noqa: BLE001
            out["note"] = "补偿失败 %s: %s" % (type(ex).__name__, str(ex)[:60])
        return out

    def _meta_pred(self):
        """🧾 元任务预测 (真源 meta_pred.json —— 与话题 zmax/ss_meta_pred 同源; 读不到返回 None)。"""
        try:
            d = _j(os.path.join(LIVE_DIR, "meta_pred.json"), None) or {}
            _t = d.get("top") or []
            _v = [float(x.get("score") or 0.0) for x in _t if isinstance(x, dict)]
            return {"top1": (_v[0] if _v else 0.0),
                    "spread": ((_v[0] - _v[1]) if len(_v) > 1 else 0.0),
                    "n_meta": int(d.get("n_meta") or 0), "frozen": int(d.get("frozen") or 0)}
        except Exception:                                                    # noqa: BLE001
            return None

    def __init__(self, hz: float, state_file: str | None, traj_path: str, inertia: bool,
                 encoder: str = "pca", l4_hz: float = 1.0, l4_url: str = "",
                 pipe: bool = False, pipe_every: int = 5, pipe_img: str = "",
                 su2_tangent: bool = True) -> None:
        self.dt = 1.0 / max(1e-6, float(hz))
        self.hz = float(hz)
        self.encoder = str(encoder or "pca")
        self.l4_hz = float(l4_hz)
        self.l4_url = l4_url
        self.l4 = None
        self.hjepa = None            # 🧠 H-JEPA 三层潜空间通道 (--encoder hjepa, 老倪 2026-10-22 A)
        self._hj_retry = 0
        self._state_now = None       # 本周期真值 state (H-JEPA 的 state7 取它前 7 维, 非零填充)
        # 🧠 多层 pipeline (L5→MEM→L2→L4→L3 依次真跑)
        self.pipe = None
        self.pipe_on = bool(pipe)
        self.pipe_every = max(1, int(pipe_every))
        self.pipe_img_url = pipe_img or PIPE_IMG_DEFAULT
        self.pipe_frame = None
        self.pipe_frame_ts = 0.0
        self.pipe_calls = 0
        self.pipe_last: dict = {}
        self.state_file = state_file
        self.traj_path = traj_path
        self.inertia = bool(inertia)
        # 🔵 2026-10-19: SU(2) 切空间投影 (SU(2)≅S³) —— 只改 ∇Φ 的方向质量, 不动真机下发链
        #   ZMAX_MANIFOLD_SU2_TANGENT 可整体关 (0) 回旧口径, 便于同口径 A/B。
        self.su2_tangent = bool(su2_tangent)
        self.n = 0
        # 🧩 动作块流水线 (老倪 2026-10-15): H>1 才建; ZMAX_CHUNK_H=1/0 ⇒ 完全不参与 (逐位回退)
        try:
            _h = int(os.environ.get("ZMAX_CHUNK_H", "8"))
        except Exception:                                                    # noqa: BLE001
            _h = 8
        if _h > 1:
            from ss_chunk_pipeline import ChunkPipeline                       # noqa: PLC0415
            self.chunk = ChunkPipeline(h=_h)
        else:
            self.chunk = None
        self.idle_n = 0
        self.eng = None
        self.calib_note = ""
        self.src_key = ""
        self.traj = None
        self.idx = 0
        self.M, self.M_key = -1.0, ""
        self.proj, self.task = {}, {}
        self.meta = {}                       # 🧾 本任务元任务派生件 (任务变才重算, 见 refresh)
        self.t_src = 0.0
        self.t_stat = 0.0
        self.tap_path = ""
        self.slice = []
        # 实例隔离 (老倪「断点还是没进」: 常驻服务持锁 ⇒ 调试实例用自己的 tap/pid, 互不干扰)
        self.inst = INSTANCE
        self.tap_dir = TAP_DIR if self.inst == "main" else "%s_%s" % (TAP_DIR, self.inst)
        self.pid_path = PID if self.inst == "main" else PID[:-4] + "_%s.pid" % self.inst
        self.live_path = LIVE if self.inst == "main" else LIVE[:-5] + "_%s.json" % self.inst
        self.status_path = STATUS if self.inst == "main" else STATUS[:-5] + "_%s.json" % self.inst

    def _attach_encoder(self) -> None:
        """🧠 老倪 2026-10-14: L4 潜空间 = VLM 通用视觉编码器(输入) → 黎曼度规约束(引擎) → INTACT(意图解码)。

        `--encoder l4` ⇒ 引擎潜表示由**真实相机帧**经 VLM 编码 + 度规约束给出 (带帧龄);
        `--encoder hjepa` ⇒ 🧠 H-JEPA 三层潜空间接成**第三潜通道** (老倪 2026-10-22 A):
                            主潜表示仍走 PCA (goal 语义不变), H-JEPA 每步真前向 → rec["hjepa"]
                            (三层范数/能量/预测残差); 势注入 HJEPA_W 默认 0 ⇒ 逐位零回归。
        `--encoder pca` (默认) ⇒ 内建 PCA 编码器 (零回归)。接不上就明写原因并留在 pca, 不假装。
        """
        if self.eng is None:
            return
        if self.encoder == "hjepa":
            self._attach_hjepa()
            return
        if self.encoder != "l4":
            return
        try:
            from lerobot.manifold.l4_live import FRAME_URL_DEFAULT, L4LiveProvider   # noqa: PLC0415
            if self.l4 is None:
                self.l4 = L4LiveProvider(ROOT, frame_url=(self.l4_url or FRAME_URL_DEFAULT),
                                         interval=1.0 / max(0.05, self.l4_hz))
                ok, why = self.l4.start()
                if not ok:
                    _log("⚠️ L4 潜空间接不上 ⇒ 本轮用内建 PCA 编码器 (原因: %s)" % why)
                    self.l4 = None
                    return
                _log("🧠 L4 潜空间已接入: %s" % why)
            self.eng.set_latent_provider(self.l4, self.l4.note_base)
        except Exception as e:                                                   # noqa: BLE001
            _log("⚠️ L4 接入异常 (%s: %s) ⇒ 退回内建 PCA" % (type(e).__name__, str(e)[:90]))
            self.l4 = None

    def _hjepa_state7(self):
        """H-JEPA 的 state7: 优先本周期真值; 首周期还没走到 step 时用轨迹真源末帧 (都是真数据)。"""
        s = self._state_now
        if s is None:
            try:
                O = (self.traj or {}).get("obs")
                s = None if O is None else O[min(getattr(self, "idx", 0), len(O) - 1)]
            except Exception:                                                # noqa: BLE001
                s = None
        return None if s is None else np.asarray(s, float)[:7]

    def _attach_hjepa(self) -> None:
        """H-JEPA 三层潜空间 → 引擎第三潜通道 (真权重真前向; 缺什么明写, 不装)。

        主潜表示**不动** (goal/Φ 仍是轨迹潜空间的概念); H-JEPA 走 `eng.set_hjepa_provider`。
        state7 取本周期 `state[:7]` (真值, 非零填充); 图像支路用真帧文件, 实测该权重图像不敏感 (见判据 J7)。
        """
        try:
            from lerobot.manifold.hjepa_state import HJEPAStateProvider        # noqa: PLC0415
        except Exception as e:                                                   # noqa: BLE001
            _log("⚠️ H-JEPA 模块导入失败 (%s: %s) ⇒ 不接" % (type(e).__name__, str(e)[:90]))
            return
        try:
            if self.hjepa is None:
                _fr = ""
                try:
                    import glob as _g                                       # noqa: PLC0415
                    _c = sorted(_g.glob(os.path.join(ROOT, "zmax_data/eval_frames/live_*")))
                    for _d in reversed(_c[-6:]):
                        _imgs = sorted(_g.glob(os.path.join(_d, "*.png")))
                        if _imgs:
                            _fr = _imgs[len(_imgs) // 2]
                            break
                except Exception:                                            # noqa: BLE001
                    _fr = ""
                self.hjepa = HJEPAStateProvider(ROOT, frame_path=_fr,
                                                state_fn=self._hjepa_state7)
                ok, why = self.hjepa.start()
                if not ok:
                    _log("⚠️ H-JEPA 接不上 ⇒ 不接 (原因: %s)" % why)
                    self.hjepa = None
                    return
                _log("🧠 H-JEPA 已接入引擎 (第三潜通道): %s" % why)
            info = self.eng.set_hjepa_provider(self.hjepa, self.hjepa.note_base)
            _log("🧠 H-JEPA 通道就位: %s (w_phi=%.2f ⇒ %s)" % (
                info.get("note"), info.get("w_phi") or 0.0,
                "只观测不动动作" if not (info.get("w_phi") or 0.0) else "参与势场"))
        except Exception as e:                                                   # noqa: BLE001
            _log("⚠️ H-JEPA 接入异常 (%s: %s) ⇒ 不接" % (type(e).__name__, str(e)[:90]))
            self.hjepa = None

    # 真源 5s 跟随 (工程/任务/M/源文件)—— 与 tdrive_bus 的场景跟随同口径
    # ── 🧠 多层 pipeline: 让 L5/MEM/L2/L4/L3 每周期按序真跑 (不是只看状态灯) ──
    def _attach_pipeline(self) -> None:
        if not self.pipe_on:
            return
        try:
            _tp = os.path.join(ROOT, "tools")
            if _tp not in sys.path:
                sys.path.insert(0, _tp)
            from multi_layer_pipeline import Pipeline, build_default_spec          # noqa: PLC0415
            spec = build_default_spec(L5="planner.rules", L2="detect.yolo", L4="node.unified")
            spec["L4"] = {"impl": "node.unified", "on": True, "combine": "vote", "peers": ["node.intact"]}
            self.pipe = Pipeline(spec)
            self.pipe = self.pipe                                       # 装配一次, 不每周期重建 (会重载模型)
            _log("🧠 多层 pipeline 已接入常驻回路: L5→MEM→L2(yolo 在役)→L4(vote[unified,intact])→L3"
                 " · 每 %d 周期真跑 · 输入帧 %s" % (self.pipe_every, self.pipe_img_url))
        except Exception as e:                                                    # noqa: BLE001
            self.pipe = None
            _log("⚠️ 多层 pipeline 接不上 (%s: %s) ⇒ 本轮回退单层引擎" % (type(e).__name__, str(e)[:100]))

    def _pick_frame(self):
        """取一帧真产线图 (TTL 2s 缓存, 不每周期拉 1.7MB)。"""
        now = time.time()
        if self.pipe_frame is not None and (now - self.pipe_frame_ts) < 2.0:
            return self.pipe_frame
        try:
            import cv2                                                            # noqa: PLC0415
            import urllib.request                                                 # noqa: PLC0415
            raw = urllib.request.urlopen(urllib.request.Request(
                self.pipe_img_url, headers={"User-Agent": "zmax-engine-loop"}), timeout=8).read()
            im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if im is not None:
                self.pipe_frame, self.pipe_frame_ts = im, now
                return im
        except Exception:                                                         # noqa: BLE001
            pass
        return self.pipe_frame

    def _run_pipeline(self, state) -> dict:
        """逐层真跑一次并落每层计数 (探针的真源)。"""
        if self.pipe is None:
            return {}
        img = self._pick_frame()
        if img is None:
            return {}
        obs39 = np.asarray(state, float).ravel()[:39]
        t0 = time.perf_counter()
        try:
            out = self.pipe.run(img=np.ascontiguousarray(img), obs39=obs39)
        except Exception as e:                                                    # noqa: BLE001
            self.pipe_last = {"err": "%s: %s" % (type(e).__name__, str(e)[:140])}
            _log("⚠️ pipeline 本轮异常: %s" % self.pipe_last["err"])
            return self.pipe_last
        ms = (time.perf_counter() - t0) * 1000.0
        layers = {}
        for k, v in (out or {}).items():
            layers[str(k)] = {"ok": bool(getattr(v, "ok", False)),
                              "src": str(getattr(v, "src", ""))[:44],
                              "ms": round(float(getattr(v, "latency_ms", 0.0) or 0.0), 2)}
        self.pipe_calls += 1
        rec = {"ts": time.time(), "ts_str": time.strftime("%F %T"), "cycle": self.n,
               "pipe_calls": self.pipe_calls, "ms": round(ms, 2), "layers": layers}
        self.pipe_last = rec
        try:
            with open(PIPE_TAP, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:                                                         # noqa: BLE001
            pass
        return rec

    def _refresh(self, force: bool = False) -> None:
        if not force and (time.time() - self.t_src) < 5.0:
            return
        self.t_src = time.time()
        p0, t0, (m0, mk0) = self.proj, self.task, (self.M, self.M_key)
        self.proj, self.task = read_project(), read_task()
        self.M, self.M_key = read_M()
        new = None
        if self.state_file:
            new = read_state_file(self.state_file)
            if new is not None:
                self.src_key = "state_file"
        if new is None:
            new = read_traj(self.traj_path)
            if new is not None:
                self.src_key = "traj"
                if self.traj is None or new["mtime"] != self.traj["mtime"]:
                    self.idx = 0
        if new is None:
            if self.src_key:
                _log("⏸ 状态真源消失 (%s) → 空转, 不造状态" % self.src_key)
            self.src_key = ""
            self.traj = None
            return
        changed = (self.src_key != getattr(self, "_last_src", None) or
                   self.traj is None or new["mtime"] != self.traj["mtime"])
        self._last_src = self.src_key
        self.traj = new
        if changed or p0 != self.proj or t0 != self.task or m0 != self.M:
            try:
                self.eng, self.calib_note, _ = build_engine(new, self.M, self.inertia,
                                                            su2_tangent=self.su2_tangent)
                self._attach_encoder()
                self._attach_pipeline()
                self.idx = 0
                _log("🧮 引擎就位: %s · 源=%s (%d 帧) · M=%.4f (键 %s) · su2切投影=%s · 工程 %s · 任务 %s"
                     % (self.calib_note, self.src_key, len(new["obs"]), self.M, self.M_key,
                        "开" if self.su2_tangent else "关",
                        self.proj.get("project") or "?", self.task.get("task_id") or "?"))
                # 📍 断点位置自证 (老倪: 「断点还是没进」——先把"该打在哪一行"打到日志里)
                try:
                    import lerobot.manifold.manifold_engine as _me              # noqa: PLC0415
                    _f = os.path.relpath(_me.__file__, ROOT)
                    _l = [n + 1 for n, x in enumerate(open(_me.__file__, encoding="utf-8"))
                          if x.lstrip().startswith("def step(self, state")][0]
                    _log("📍 断点请打: %s:%d (def step) → 本循环每周期都会经过 (GIL 下多线程, 但 step 在本线程调用)"
                         % (_f, _l))
                except Exception:                                                # noqa: BLE001
                    pass
                # 🧾 元任务 (老倪 2026-10-14: 「流形引擎, 需要根据任务, 输出 元任务」)
                #   引擎每周期都在跑 ⇒ 它是"根据任务"最合适的**触发者**; 但元任务清单本体是配置的
                #   派生件 (功能+参数+依赖+验证+层), 内容一律真源现算 (复用 export_meta_doc 同一条映射链),
                #   **不从意图直读**。这里只做两件事: 任务变 ⇒ 重算派生件(落 zmax_data/ss_live/
                #   meta_tasks.json) + 记下本任务元任务数 (随每周期 rec 带出); 5s 常态发布由
                #   主参数节点出口 zmax/ss_meta_task 负责, 不在这里每步刷清单 (避免污染高频记录)。
                try:
                    import ss_meta_task as _SM                              # noqa: PLC0415
                    self.meta = _SM.build(self.task.get("task_id") or None, write=True)
                    _log("🧾 元任务: %s → %d 个 (全量 %d · 层 %s) · 真源现算, 非意图直读"
                         % (self.meta.get("task_id") or "—", self.meta.get("n") or 0,
                            self.meta.get("n_all") or 0, self.meta.get("by_layer") or {}))
                except Exception as e:                                        # noqa: BLE001
                    self.meta = {}
                    _log("⚠️ 元任务派生失败: %s: %s" % (type(e).__name__, str(e)[:80]))
            except Exception as e:                                            # noqa: BLE001
                _log("⚠️ 引擎构建失败 (%s) → 本周期不发" % type(e).__name__)
                self.eng = None
        scn = str(self.traj.get("scene") or os.environ.get("ZMAX_SS_ENGINE_SCENE") or "default")
        self.tap_path = os.path.join(self.tap_dir, "engine_%s.jsonl" % scn)

    def cycle(self) -> dict | None:
        self._refresh()
        if self.eng is None or self.traj is None:
            self.idle_n += 1
            if self.idle_n % max(1, int(self.hz * 5)) == 1:
                _log("⏸ 无状态真源 → 空转 (不造状态)。给 --state-file <jsonl> 或用状态空间工程 ▶ 运行"
                     " (会落盘 %s)" % os.path.relpath(self.traj_path, ROOT))
            return None
        O = self.traj["obs"]
        state = O[min(self.idx, len(O) - 1), :STATE_DIM]
        replay = self.idx >= len(O)
        self.idx = (self.idx + 1) % (len(O) + 1)
        self._state_now = np.asarray(state, float)
        if self.encoder == "hjepa" and self.hjepa is None and self._hj_retry < 3:
            self._hj_retry += 1
            self._attach_hjepa()
        t0 = time.perf_counter()
        rec = self.eng.step(np.asarray(state, float), dt=self.dt)
        ms = (time.perf_counter() - t0) * 1000.0
        self.n += 1
        # 🧩 动作块流水线 (老倪 2026-10-15; ZMAX_CHUNK_H<=1 不进): 引擎出块 → 前馈序列 → 加权 → 逐拍调制
        #    → 逐拍安全 → 技能派发。**不改** rec["action"] (引擎动作照旧), 块走独立分支 + 落盘给技能服务。
        phys_rec: dict = {}
        chunk_rec: dict = {}
        if self.chunk is not None and not replay:
            try:
                _si, _sn = self._chunk_stage()
                chunk_rec = self.chunk.step(self.eng, np.asarray(state, float), state=np.asarray(state, float),
                                            stage_idx=_si, meta=self._meta_pred(),
                                            residual=float(rec.get("residual") or 0.0))
                chunk_rec["stage_name"] = _sn
            except Exception as e:                                           # noqa: BLE001
                chunk_rec = {"ok": False, "reason": "%s: %s" % (type(e).__name__, str(e)[:120])}
        # ⚖ 物理偏差: 读技能闸的真源 → 大偏差走"融合定位 → 顶层补偿"
        try:
            _se = self._skill_err()
            if _se:
                phys_rec = {"big_stage": _se.get("big_stage") or "", "err_norm": _se.get("err_norm") or {},
                            "big": _se.get("big") or {}, "why": _se.get("why") or {},
                            "stats": _se.get("stats") or {},
                            "top": self._top_compensate(_se) if _se.get("big_stage") else {}}
        except Exception as e:                                               # noqa: BLE001
            phys_rec = {"note": "物理偏差读取失败 %s: %s" % (type(e).__name__, str(e)[:60])}
        # 🧠 老倪 2026-10-14「所有层按 pipeline 依次全都运行推理」: 每 N 周期按序真跑 L5→MEM→L2→L4→L3
        pipe_rec: dict = {}
        if self.pipe is not None and (self.n % self.pipe_every == 0):
            pipe_rec = self._run_pipeline(state)
        hom = rec.get("homeostasis") or {}
        p = np.asarray(rec.get("p"), float).ravel()
        a = np.asarray(rec.get("action"), float).ravel()
        return {
            "ts": time.time(), "ts_str": time.strftime("%F %T"), "cycle": self.n,
            "hz": self.hz, "ms": round(ms, 3), "dt": self.dt,
            "provider": self.src_key, "source": self.traj.get("src") or "",
            "traj_at": self.traj.get("saved_at") or "", "traj_n": int(len(O)),
            "idx": int(min(self.idx - 1, len(O) - 1)), "replay": bool(replay),
            "project": self.proj.get("project") or "", "project_saved_at": self.proj.get("project_saved_at") or "",
            "task_id": self.task.get("task_id") or self.traj.get("task_id") or "",
            "task_name": self.task.get("task_name") or "",
            "meta_n": int((self.meta or {}).get("n") or 0),        # 🧾 本任务元任务数 (真源现算)
            "meta_all": int((self.meta or {}).get("n_all") or 0),
            "scene": str(self.traj.get("scene") or ""),
            "M": float(self.M), "M_key": self.M_key, "inertia": bool(self.inertia),
            "su2_tangent": bool(self.su2_tangent),
            "calib": self.calib_note, "decode_src": str(rec.get("decode_src") or ""),
            "manifold": str(rec.get("manifold") or ""), "status": str(rec.get("status") or ""),
            "p": [round(float(x), 6) for x in p],
            "phi": float(rec.get("phi") or 0.0),
            "grad_norm": float(np.linalg.norm(np.asarray(rec.get("grad"), float))) if rec.get("grad") is not None else -1.0,
            "action": [round(float(x), 6) for x in a], "action_norm": float(np.linalg.norm(a)),
            "confidence": float(rec.get("confidence") or 0.0),
            "anomaly": float(rec.get("anomaly") or 0.0),
            "residual": float(rec.get("residual") or 0.0),
            "momentum": rec.get("momentum"),
            "hom_enabled": bool(rec.get("hom_enabled")),
            "hom_mode": str(hom.get("mode") or ""), "hom_kind": str(hom.get("kind") or ""),
            "hom_vitality": float(hom.get("vitality") or 0.0),
            "hom_gain": float(hom.get("action_gain") if hom.get("action_gain") is not None else 1.0),
            "hom_dominant": str(hom.get("dominant") or ""),
            "hom_urgency": float(hom.get("dominant_urgency") or 0.0),
            "hom_veto": bool(hom.get("safety_override")),
            # 🧠 潜表示来源 (老倪 2026-10-14「VLM 视觉编码器是输入」): 本周期喝的到底是哪条编码链 +
            #   实际用的潜坐标。pca=内建拟合; l4=VLM 视觉编码器→黎曼度规约束 (带帧龄)。两者都在 tap 里可核。
            "z_source": str(rec.get("z_source") or ""),
            "z_latent": [round(float(x), 6) for x in (rec.get("z") if rec.get("z") is not None else [])],
            "encoder": ("l4" if self.l4 is not None else "pca"),
            "t_encode_ms": float(rec.get("t_encode_ms") or 0.0),
            "t_project_ms": float(rec.get("t_project_ms") or 0.0),
            "t_grad_ms": float(rec.get("t_grad_ms") or 0.0),
            # 🧠 多层 pipeline 逐层真跑结果 (L5/MEM/L2/L4/L3 的 ok/src/ms + 本次总耗时)
            # 🧩 块流水线的关键量**平铺**到本帧顶层 (信号分析按 sseng.* 前缀逐个当信号画 ⇒ 不用改读法)
            **({k: v for k, v in (self.chunk.trace_keys(chunk_rec)
                                  if (self.chunk is not None and isinstance(chunk_rec, dict)) else {}).items()}),
            # ⚖ 原子技能物理闸的偏差 → 状态校正器(小偏差, 见 state_space_sim/skill_dispatch) /
            #   大偏差 → 融合定位核对 → 流形引擎顶层结构补偿 (老倪 2026-10-15)
            **self._skill_trace(phys_rec),
            "chunk": chunk_rec if isinstance(chunk_rec, dict) else {},
            "hjepa": rec.get("hjepa") or {},
            "chunk_keys": (self.chunk.trace_keys(chunk_rec)
                           if (self.chunk is not None and isinstance(chunk_rec, dict)) else {}),
            "pipe": pipe_rec if isinstance(pipe_rec, dict) else {},
            "pipe_calls": int(self.pipe_calls),
            "pipe_on": bool(self.pipe is not None),
        }

    def emit(self, d: dict) -> None:
        os.makedirs(os.path.dirname(self.tap_path), exist_ok=True)
        with io.open(self.tap_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
        _trim_tap(self.tap_path, int(TAP_MAX_MB * 1024 * 1024))
        _atomic_json(self.live_path, d)

    def say(self, d: dict, t0: float, n0: int) -> None:
        self.slice.append(d)
        self.slice = self.slice[-max(1, int(self.hz)):]
        if self.n % max(1, int(self.hz)) == 0:
            hz_act = len(self.slice) / max(1e-6, (d["ts"] - self.slice[0]["ts"]) or self.dt)
            if self.l4 is not None and self.eng is not None:
                self.eng.latent_provider_note = self.l4.note()      # 每周期刷新帧龄 (真源现算)
            _log("周期 %6d · %5.2fHz · Φ=%+.4f ‖∇Φ‖=%6.2f ‖a‖=%.3f · M=%.4f%s · H=%s(gain %.2f)%s"
                 " · p̂=%.4f 置信=%.2f · %.2fms · 帧#%d/%d%s · 任务 %s · 工程 %s"
                 % (d["cycle"], hz_act, d["phi"], d["grad_norm"], d["action_norm"], d["M"],
                    "(惯性)" if d["inertia"] else "", d["hom_mode"] or "-", d["hom_gain"],
                    "(veto)" if d["hom_veto"] else "",
                    float(np.linalg.norm(d["p"])), d["confidence"], d["ms"], d["idx"] + 1, d["traj_n"],
                    "(回放)" if d["replay"] else "", d["task_id"] or "?", d["project"] or "?"))
            _atomic_json(self.status_path, {"updated": d["ts_str"], "cycles": self.n, "idle_cycles": self.idle_n,
                                  "hz_target": self.hz, "provider": d["provider"], "cycle": d["cycle"],
                                  "tap": self.tap_path, "pid": os.getpid(),
                                  "traj_n": d["traj_n"], "M": d["M"], "calib": d["calib"],
                                  "task_id": d["task_id"], "project": d["project"],
                                  "last_ms": d["ms"], "uptime_s": round(d["ts"] - t0, 1)})

    def run(self, seconds: float = 0.0, once: bool = False, lock: bool = True) -> int:
        own = 0
        if lock and os.path.isfile(self.pid_path):
            try:
                own = int(io.open(self.pid_path, encoding="utf-8").read().strip() or 0)
                os.kill(own, 0)
                # 🔴 2026-10-19 现场: pid 会被系统复用 —— 引擎某次崩掉时写下的 pid,
                #   后来被 vl_safety_fast.py 捡到(pid 5282) ⇒ os.kill 成功 ⇒ 引擎每次启动都判
                #   "已有写入器在跑" 直接退出, 实测重启 669 次、chunk_latest 1.8 小时不更新。
                #   ⇒ 活着的 pid 也必须校 cmdline, 不是引擎自己就按陈旧锁接管。
                try:
                    _cl = io.open("/proc/%d/cmdline" % own, "rb").read().decode("utf-8", "ignore")
                except Exception:                                            # noqa: BLE001
                    _cl = ""
                if "ss_engine_loop" not in _cl:
                    _log("⚠ pid 文件里的 %d 不是引擎进程(cmdline=%r) ⇒ 陈旧锁, 接管"
                         % (own, _cl.replace("\x00", " ")[:90]))
                    own = 0
            except Exception:                                                # noqa: BLE001
                own = 0
        if own and own != os.getpid():
            print(json.dumps({"started": False, "reason": "已有写入器在跑 (pid %d)" % own},
                             ensure_ascii=False))
            return 1
        os.makedirs(LIVE_DIR, exist_ok=True)
        os.makedirs(self.tap_dir, exist_ok=True)
        with io.open(self.pid_path, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
        _log("▶ 流形引擎常驻周期循环: %.1fHz · 实例=%s · tap %s · 状态源 %s"
             % (self.hz, self.inst, self.tap_dir, self.state_file or os.path.relpath(self.traj_path, ROOT)))
        t0 = time.time()
        try:
            while True:
                ts = time.time()
                try:
                    d = self.cycle()
                    if d:
                        self.emit(d)
                        self.say(d, t0, 0)
                except Exception as e:                                       # noqa: BLE001
                    _log("⚠️ 第 %d 周期异常: %s" % (self.n + 1, str(e)[:160]))
                if once:
                    break
                if seconds and (time.time() - t0) >= float(seconds):
                    break
                time.sleep(max(0.0, self.dt - (time.time() - ts)))
        finally:
            try:
                os.remove(self.pid_path)
            except Exception:                                                # noqa: BLE001
                pass
        print(json.dumps({"cycles": self.n, "idle": self.idle_n, "provider": self.src_key,
                          "tap": self.tap_path, "calib": self.calib_note,
                          "seconds": round(time.time() - t0, 1)}, ensure_ascii=False))
        return 0 if self.n else 0


def cmd_seed(episode: str, out: str | None = None) -> int:
    """先把一份**真实** episode (reports/ss_episode*.npz, obs[43]+u_exec_vec) 落成轨迹真源。

    为什么需要: 控制台 ▶ 运行状态空间会自动落盘轨迹真源 (simulink_module 的 dump); 若还没跑过,
    常驻回路没有状态源 ⇒ 会空转。本命令让回路可以先吃**已有的真实 episode** 跑起来
    (src 字段如实写清来源; 之后工程一跑, 更新的真源会覆盖它并被回路自动接上)。
    """
    out = out or TRAJ
    d = np.load(episode, allow_pickle=True)
    obs = np.asarray(d["obs"], float)
    u = np.asarray(d["u_exec_vec"], float) if "u_exec_vec" in d else None
    meta = d["meta"] if "meta" in d else None
    try:
        meta = meta.item() if hasattr(meta, "item") else (dict(meta) if meta is not None else {})
    except Exception:                                                        # noqa: BLE001
        meta = {}
    rows = [[round(float(x), 6) for x in r] for r in obs[-400:, :STATE_DIM]]
    obj = {"saved_at": time.strftime("%F %T"),
           "src": "真实 episode %s (obs[43]+u_exec_vec; seed 命令落盘, 非自造)" % os.path.basename(episode),
           "n": len(rows), "obs_dim": int(obs.shape[1]),
           "scene": str((meta or {}).get("scene") or ""),
           "task_id": read_task().get("task_id") or "", "obs": rows,
           "u_exec_vec": ([[round(float(x), 6) for x in r] for r in u[-400:]] if u is not None else None),
           "t": None}
    _atomic_json(out, obj)
    back = _j(out, {}) or {}
    ok = len(back.get("obs") or []) == len(rows)
    print("种子轨迹真源: %s · %d 帧 × %d 维 · 回读校验 %s" %
          (os.path.relpath(out, ROOT), len(rows), int(obs.shape[1]), "OK ✅" if ok else "失败 ❌"))
    return 0 if ok else 1


def cmd_status() -> int:
    st = _j(STATUS, {}) or {}
    tr = _j(TRAJ, {}) if os.path.isfile(TRAJ) else {}
    print(json.dumps({
        "status_file": STATUS, "loop": st,
        "traj_source": {"path": os.path.relpath(TRAJ, ROOT), "exists": os.path.isfile(TRAJ),
                        "saved_at": (tr or {}).get("saved_at"), "n": len((tr or {}).get("obs") or []),
                        "src": (tr or {}).get("src")},
        "tap_dir": TAP_DIR, "tap_files": sorted(os.path.basename(p) for p in
                                                ([os.path.join(TAP_DIR, f) for f in os.listdir(TAP_DIR)]
                                                 if os.path.isdir(TAP_DIR) else [])),
        "project": read_project(), "task": read_task(), "M": read_M(),
    }, ensure_ascii=False, indent=1))
    return 0


def cmd_selftest() -> int:
    """机制自检: 用**标注为自检**的斜坡状态确认「每周期真调 step + 落盘 + 频率」。
    自检输出只写 scratch, **不进** tap/快照 (不拿自检数据冒充在役)。"""
    import tempfile
    sd = os.path.join(ROOT, ".hermes", "cache", "scratch", "ss_engine_selftest")
    os.makedirs(sd, exist_ok=True)
    n = 8
    obs = [np.sin(np.arange(STATE_DIM) * 0.1 + i * 0.05).tolist() for i in range(n)]
    tp = os.path.join(sd, "traj_selftest.json")
    with io.open(tp, "w", encoding="utf-8") as fh:
        json.dump({"saved_at": time.strftime("%F %T"), "scene": "selftest", "src": "自检斜坡状态 (非在役数据)",
                   "obs": obs}, fh, ensure_ascii=False)
    lp = Loop(hz=10.0, state_file=None, traj_path=tp, inertia=False, su2_tangent=True)
    lp.t_src = 0.0
    got = []
    t0 = time.time()
    for _ in range(n):
        d = lp.cycle()
        if d:
            got.append(d)
        time.sleep(0.01)
    secs = time.time() - t0
    def _fin(v):
        try:
            return all(np.isfinite(float(x)) for x in (v or []))
        except Exception:                                                    # noqa: BLE001
            return False
    ok = (len(got) == n
          and all(isinstance(d.get("p"), list) and d["p"] and _fin(d["p"]) for d in got)
          and all(isinstance(d.get("action"), list) and len(d["action"]) == ACTION_DIM for d in got)
          and all(d.get("ms") is not None and _fin(d["action"]) for d in got))
    print("自检: 周期 %d/%d · %.2fs · 实测 %.1fHz · step 平均 %.2fms · 校准=%s"
          % (len(got), n, secs, len(got) / max(1e-6, secs),
             (sum(d["ms"] for d in got) / max(1, len(got))), lp.calib_note))
    print("自检结果:", "全部通过 ✅" if ok else "未通过 ❌")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run",
                    choices=["run", "once", "status", "selftest", "seed"])
    ap.add_argument("--hz", type=float, default=float(os.environ.get("ZMAX_SS_ENGINE_HZ") or 10.0))
    ap.add_argument("--seconds", type=float, default=0.0, help="跑多久 (0=常驻)")
    ap.add_argument("--state-file", default=os.environ.get("ZMAX_SS_ENGINE_STATE"),
                    help="外部实时状态源 (json/jsonl, 含 obs[43])")
    ap.add_argument("--traj", default=os.environ.get("ZMAX_SS_ENGINE_TRAJ") or TRAJ,
                    help="状态空间工程轨迹真源 (默认 %s)" % os.path.relpath(TRAJ, ROOT))
    ap.add_argument("--inertia", action="store_true", help="二阶演化 (M=等效惯量, 默认过阻尼=旧行为)")
    # 🔵 2026-10-19 老倪「现在就把 su2_tangent 接进 ss_engine_loop, 但先不接入真机」
    #   接到本回路 (只算方向/动作建议, 写 engine_latest + DDS); 真机下发链 (8793/l2_daemon/臂) 一行未改。
    #   默认开; --no-su2-tangent 或 ZMAX_MANIFOLD_SU2_TANGENT=0 可回旧口径做同口径 A/B。
    _def_su2 = str(os.environ.get("ZMAX_MANIFOLD_SU2_TANGENT", "1")).strip().lower() not in ("0", "false", "no", "off")
    ap.add_argument("--su2-tangent", dest="su2_tangent", action="store_true", default=_def_su2,
                    help="SU(2)≅S³ 切空间投影 (默认开; 只改 ∇Φ 方向, 不动真机)")
    ap.add_argument("--no-su2-tangent", dest="su2_tangent", action="store_false",
                    help="关掉切空间投影 (旧口径, 零回归对照臂)")
    ap.add_argument("--instance", default=os.environ.get("ZMAX_SS_ENGINE_INSTANCE") or "main",
                    help="实例名: main=常驻服务那份; 用别的名字(如 debug) ⇒ 独立 tap/pid, 可与服务并行 "
                         "(调试断点用, 不污染在役记录)")
    ap.add_argument("--no-lock", action="store_true", help="不检查/不写单写入器锁 (纯调试用)")
    ap.add_argument("--episode", default="", help="seed 用: 真实 episode npz (reports/ss_episode*.npz)")
    ap.add_argument("--out", default="", help="seed 用: 输出路径 (默认轨迹真源)")
    ap.add_argument("--encoder", default=os.environ.get("ZMAX_SS_ENGINE_ENCODER") or "pca",
                    choices=["pca", "l4", "hjepa"],
                    help="潜表示来源: pca=内建 PCA (默认) · l4=VLM视觉编码器→黎曼度规约束 · "
                         "hjepa=H-JEPA 三层潜空间接成第三潜通道 (rec['hjepa'], 势注入见 HJEPA_W)")
    ap.add_argument("--l4-hz", type=float, default=float(os.environ.get("ZMAX_L4_HZ") or 1.0),
                    help="L4 潜表示刷新节拍 Hz (视觉塔实测 ~0.8s/帧, 故独立线程按此节拍)")
    ap.add_argument("--l4-frame-url", default=os.environ.get("ZMAX_L4_FRAME_URL") or "",
                    help="L4 视觉编码器的帧 URL (空=用内建帧源)")
    # 🧠 老倪 2026-10-14「所有层按 pipeline 依次全都运行推理」
    ap.add_argument("--pipeline", action="store_true",
                    default=bool(os.environ.get("ZMAX_SS_PIPELINE")),
                    help="每 N 周期按序真跑整条 pipeline L5→MEM→L2→L4→L3 (所有层真推理)")
    ap.add_argument("--pipe-every", type=int, default=int(os.environ.get("ZMAX_SS_PIPE_EVERY") or 5),
                    help="每几个引擎周期跑一次整条 pipeline (默认 5; 10Hz 下 = 2Hz)")
    ap.add_argument("--pipe-img", default=os.environ.get("ZMAX_SS_PIPE_IMG") or "",
                    help="L2 输入的**真产线帧** URL (默认 8791 /aoi_modelin.png)")
    a = ap.parse_args()
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "selftest":
        return cmd_selftest()
    if a.cmd == "seed":
        return cmd_seed(a.episode, a.out or None)
    global INSTANCE
    INSTANCE = str(a.instance or "main")
    lp = Loop(hz=a.hz, state_file=a.state_file, traj_path=a.traj, inertia=a.inertia,
              encoder=a.encoder, l4_hz=a.l4_hz, l4_url=a.l4_frame_url,
              pipe=a.pipeline, pipe_every=a.pipe_every, pipe_img=a.pipe_img,
              su2_tangent=a.su2_tangent)
    # `run --seconds N` 必须真按 N 收 (实测踩过: 恒传 0 ⇒ --seconds 被忽略, 一直跑)
    rc = lp.run(seconds=(a.seconds if a.cmd == "run" else 1.0), once=(a.cmd == "once"),
                lock=not a.no_lock)
    # 🐛 实测: 接了 L4 (torch+CUDA 在常驻线程里) 后, 解释器收尾阶段会 **Aborted** (CUDA 上下文析构);
    #   进程已跑完且 tap/状态都已落盘 ⇒ 按项目惯例 flush 后 os._exit 交付同一退出码 (不弹假异常)。
    try:
        if lp.l4 is not None:
            lp.l4.stop()
    except Exception:                                                        # noqa: BLE001
        pass
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(rc or 0))


if __name__ == "__main__":
    raise SystemExit(main())
