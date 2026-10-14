# -*- coding: utf-8 -*-
"""tdrive_bus.py — 驱动扭矩发布器: T_drive = M·(−∇Φ) → 全局数据空间

老倪 2026-10-13: 「T drive = M·(−∇Φ) 用 topic 在全局数据空间输出，我要看到，并在实时监控里，有这个信号」。

物理口径 (规格原文):
    转动惯量 I  ↔  度量张量 M (主参数)
    角加速度 α  ↔  负梯度 −∇Φ
    驱动扭矩 T  ↔  T_drive = M·(−∇Φ)      单位 N·m

真实数据来源 (都不是造的):
    M   ← 主参数真源 config/calib/zmax_manifold.json  (MetricField.from_config: g(x)=M·G(x), det G=1)
    ∇Φ  ← 真实势场解析梯度 src/lerobot/memory/potential_field.py::MemoryLayerBridge.grad_raw
          (L2 肌肉记忆技能场 + L3 流程场 + L4 障碍/世界项, 按逐层开关合成; 全关 ⇒ 零 ⇒ 不干预)
    x   ← 真机 TCP 位置真源 zmax_data/rokae_sdk/tcp_out/latest.json (帧龄判定; 无新鲜值则用技能入口并如实标注)
    H   ← 健康度 (health.py 阈值真源) ⇒ normal/warning/critical ⇒ 增益 1.0 / 0.5 / 0.0

为什么必须用 grad_raw: `grad()` 为"意图方向"服务, 逐层求和后**归一化成单位向量** ⇒ 拿它算扭矩只能得到
‖M·1‖ 这种尺度无关的假量。T_drive 需要真实量纲的梯度 (实测: 归一前 ‖∇Φ‖≈69.1, 归一后 =1.0)。

落盘/发布 (单一写入器 + 原子写 + 回读):
    tap  zmax_data/ss_live/torque_<scene>.jsonl   (每帧一行; **最后一行才是 payload** —— 与能量层同口径)
    守护 tools/dds/ss_daemon.py::read_torque → pub_torque → DDS topic **zmax/ss_torque**
    注册 src/lerobot/dataspace/topics.py["ss_torque"] + zmax_data/dataspace/live.json
    ⇒ 实时监控 (📈 全局数据空间信号源) / 控制台数据空间页 都能看到这个信号

用法:
    QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/tdrive_bus.py run --hz 10 --seconds 30
    ... once | status | selftest
注意: tap 与 pid 锁都在 zmax_data/ss_live (不写 /tmp, 免得被清理)。
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
# 🔴 2026-10-13 老倪: 「torque_SCN-06-TRAY.jsonl 已 306.6 MB 这是啥？删掉，不要自己保存」
#   ⇒ tap (10Hz 逐帧流, ≈2.0 GB/天) 不再落盘: 默认写 **内存盘 /dev/shm**(重启即清), 并加**环形上限**
#   (超 ZMAX_TORQUE_TAP_MAX_MB 就只保留尾部, 默认 32MB)。要落盘显式给
#   ZMAX_TORQUE_TAP_DIR=<dir> (此时仍受同一上限约束), 判据脚本读同一环境变量解析。
TAP_DIR = os.environ.get("ZMAX_TORQUE_TAP_DIR") or "/dev/shm/zmax_torque"
TAP_MAX_MB = float(os.environ.get("ZMAX_TORQUE_TAP_MAX_MB") or 32)
# 最新值快照 + pid 锁仍留磁盘 (单文件覆盖写, 不增长 —— 实时监控按此读)
LIVE_DIR = os.path.join(ROOT, "zmax_data", "ss_live")
PID = os.path.join(LIVE_DIR, "torque.pid")


def _trim_tap(path: str, cap_bytes: int) -> None:
    """环形上限: 超过 cap 就只留尾部一半 (追加型流, 不许 rm 掉正在写的 fd)。"""
    try:
        if os.path.getsize(path) <= cap_bytes:
            return
        with open(path, "rb") as f:
            f.seek(max(0, cap_bytes // 2))
            tail = f.read()
        i = tail.find(b"\n")
        tail = tail[i + 1:] if i >= 0 else b""
        with open(path, "wb") as f:
            f.write(tail)
    except Exception:  # noqa: BLE001
        pass


def _active_scene() -> str:
    """🔴 当前场景真源 (2026-10-13): 原实现把 scene **写死成 SCN-07-AOI**(DEFAULT_SCENE) ⇒ 活跃任务
    已切到摆盘(TASK-06-TRAY/SCN-06-TRAY)时, 扭矩 payload 仍标 SCN-07-AOI, tap 也写进
    torque_SCN-07-AOI.jsonl ⇒ **同一时刻两处口径不一致**(实测: 判据 ⑨ 首帧 scene=SCN-07-AOI,
    而画布数据源/绑定文件都是摆盘)。口径: 场景跟随唯一真源 tools/ss_scene_switch.py,
    env ZMAX_TORQUE_SCENE 仅用于离线/单测指定。"""
    env = os.environ.get("ZMAX_TORQUE_SCENE")
    if env:
        return env
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import ss_scene_switch as _s
        w = _s.now() or {}
        scn = w.get("scn") or ""
        if not scn:
            # 🔴 2026-10-14 修: ss_scene_switch.now() 只回 **src_state(场景名) + node + color**, 根本没有 scn 字段
            #   ⇒ 原代码一直走下面的兜底 "SCN-06-TRAY", 于是切到插拔后 tap 仍叫 torque_SCN-06-TRAY.jsonl、
            #   payload 的 scene 也是摆盘 (同一类"写死旧场景"的坑, 换了个形式又踩一次)。改成按唯一映射表反查:
            #   ① now().scn → ② src_state 场景名反查 TASK_SCENE → ③ 活跃任务 (config/ss_task_binding.json) 查表
            st = str(w.get("src_state") or "")
            for _m in (_s.TASK_SCENE or {}).values():
                if st and st == _m.get("scene"):
                    scn = _m.get("scn") or ""
                    break
            if not scn:
                try:
                    import json as _j
                    _b = _j.load(open(os.path.join(ROOT, "config", "ss_task_binding.json"), encoding="utf-8"))
                    _m = (_s.TASK_SCENE or {}).get(str(_b.get("active_task") or "")) or {}
                    scn = _m.get("scn") or ""
                except Exception:                                         # noqa: BLE001
                    scn = ""
        if scn:
            return scn
    except Exception:                                                           # noqa: BLE001
        pass
    return "SCN-未登记"           # 兜底不再谎报某个场景 (取不到就说取不到)


DEFAULT_SCENE = _active_scene()
# 驱动扭矩的"转动惯量↔度量张量"对应关系: 旋转 3 维 + 平移 3 维 = 6 维
ROT_DIM, TRANS_DIM = 3, 3
UNIT_NOTE = ("单位按规格记 N·m; 真源主参数 M 是归一化度量 (det G=1, M=3.283 标定口径), "
             "未做扭矩计量学标定 ⇒ 该数值是**系统内部一致的驱动量**, 不是计量院校准过的物理牛米。")
# 规格 §五策略1: torque = clip(M·(−∇Φ), ±T_MAX); §五策略2: 再按健康度缩 (warning ×0.5 / critical ×0)
T_MAX_DEFAULT = 30.0


def load_t_max(cfg: dict) -> tuple:
    """T_MAX 真源: 主参数 cfg 里的 t_max/T_MAX/limits.torque_nm; 没有 ⇒ 规格默认 30 (并标明来源)。"""
    for k in ("t_max", "T_MAX", "torque_max_nm"):
        if isinstance(cfg.get(k), (int, float)) and float(cfg[k]) > 0:
            return float(cfg[k]), "config/calib/zmax_manifold.json::%s" % k
    lim = cfg.get("limits") or {}
    if isinstance(lim.get("torque_nm"), (int, float)) and float(lim["torque_nm"]) > 0:
        return float(lim["torque_nm"]), "config/calib/zmax_manifold.json::limits.torque_nm"
    return T_MAX_DEFAULT, "规格 §五 默认 30 N·m (真源未标定)"


def _tap_path(scene: str) -> str:
    return os.path.join(TAP_DIR, "torque_%s.jsonl" % scene)


def _live_path(scene: str) -> str:
    return os.path.join(LIVE_DIR, "torque_live.json")


# ─────────────────────── 真源读取 ───────────────────────
def load_metric():
    """主参数真源 → MetricField (真源读不到就报错, 绝不套默认值造数)。"""
    from lerobot.manifold.metric_field import MetricField, _load_manifold_cfg
    cfg = _load_manifold_cfg()
    if not cfg:
        raise RuntimeError("主参数真源读不到: config/calib/zmax_manifold.json")
    f = MetricField.from_config(cfg)
    return f, cfg


def read_x(bridge):
    """当前状态 x: 优先真机 TCP 位置真源; 无新鲜值 → 用激活技能入口 (如实标 source)。"""
    try:
        from lerobot.manifold.localization_mapping import read_robot_pose
        p = read_robot_pose()
        if p.get("available"):
            return np.asarray(p["xyz"], float)[:3], "robot_pose(tcp_out 真源, 帧龄 %.2fs)" % p["age_s"]
    except Exception as e:                                                        # noqa: BLE001
        _ = e
    try:
        f0 = bridge.fields[0]
        return np.asarray(f0.x_g, float)[:3], "技能入口 %s 谷底 (无新鲜位姿真源)" % f0.code
    except Exception:                                                             # noqa: BLE001
        return np.zeros(3), "无来源 (全零)"


def gates_str(bridge) -> str:
    g = bridge.gates()
    return " ".join("%s=%d" % (k, int(v)) for k, v in g.items())


def status_gain(H: float, status: str) -> tuple:
    """健康度 → 状态/增益 (规格 §六: >0.5 正常; 0.1~0.5 良好; 0.01~0.1 警告×0.5; <0.01 危险×0)"""
    s = (status or "").lower()
    if s in ("danger", "critical", "bad"):
        return "critical", 0.0
    if s in ("warning", "warn", "poor"):
        return "warning", 0.5
    if H < 0.0:
        return "unknown", 1.0
    if H < 0.01:
        return "critical", 0.0
    if H < 0.1:
        return "warning", 0.5
    return "normal", 1.0


# ─────────────────────── 核心计算 ───────────────────────
def compute(scene: str = DEFAULT_SCENE, x_override=None, bridge=None) -> dict:
    """算一帧 T_drive = M·(−∇Φ)。全部数值来自真源; 算不出就抛, 不返回编的数。"""
    from lerobot.memory.potential_field import MemoryLayerBridge
    from lerobot.manifold.health import health_from_field
    metric, cfg = load_metric()
    br = bridge or MemoryLayerBridge.from_real_data(ROOT)
    x, x_src = (np.asarray(x_override, float)[:3], "显式给定") if x_override is not None else read_x(br)
    phi, contrib = br.compose(x, None)
    g_ = np.asarray(br.grad_raw(x, None), float)[:3]          # 原始 ∇Φ (未归一, 有真实量纲)
    M = np.asarray(metric.g(x), float)                        # 真源度量张量 (dim×dim, 对称正定)
    pd_ok, lmin, lmax = metric.is_positive_definite(x)
    neg = -g_
    # 6D: 前 3 维是转动分量, 后 3 维是平移分量。Φ 只定义在平移子空间 ⇒ 转动分量恒 0 (不是补零凑数)
    grad6 = np.concatenate([np.zeros(ROT_DIM), g_])
    neg6 = np.concatenate([np.zeros(ROT_DIM), neg])
    # 🔴 主参数 M 的**维数必须与被打的向量一致**: dim=3 (位置) 或 dim=6 (位姿)。维数由真源决定 ——
    #    「配置单 → 主参数 M」(tools/config_to_M.py): 插拔任务含腕部翻转 ⇒ dim=6。实测 2026-10-14 16:29
    #    切到插拔任务后 M 变 6×6, 而这里仍拿 3 维 neg 去乘 ⇒ 每帧 ValueError(matmul 3 vs 6), 10Hz 流静默断流
    #    (帧全失败、tap 不落新帧)。修法 = 同维相乘; dim=6 用 6D 向量 [旋转 0,0,0 | 平移 x,y,z] (与 grad6 同布局),
    #    dim=3 逐位保持原行为 (零回归)。
    _dim = int(np.asarray(M).shape[0])
    neg_in = neg6 if _dim == 6 else neg
    tau_vec = M @ neg_in                                       # T = M·(−∇Φ)
    tau6 = tau_vec if _dim == 6 else np.concatenate([np.zeros(ROT_DIM), tau_vec])
    _inv = metric.ginv_mul(x, neg_in)
    tau_inv6 = _inv if _dim == 6 else np.concatenate([np.zeros(ROT_DIM), _inv])
    rep = health_from_field(metric, x)
    H = float(getattr(rep, "H", -1.0))
    status, gain = status_gain(H, getattr(rep, "status", ""))
    act = getattr(br, "_active")(x, None) if hasattr(br, "_active") else None
    t_max, t_max_src = load_t_max(cfg)
    # 规格 §五策略1: 先限幅 ±T_MAX; §五策略2: 再按健康度缩 (warning ×0.5 / critical ×0)
    tau_raw6 = tau6.copy()
    tau_c6 = np.clip(tau6, -t_max, t_max) * gain
    tau_inv6 = tau_inv6 * gain
    clipped = bool(np.any(np.abs(tau_raw6) > t_max + 1e-12))
    # 诊断: 离最近技能谷底的距离 (解释 Φ/∇Φ 为何大 —— 在远离工作区时场本来就强)
    d_tr = None
    try:
        d_tr = float(min(np.linalg.norm(x - np.asarray(f.x_g, float)[:3]) for f in br.fields)) if br.fields else None
    except Exception:                                                             # noqa: BLE001
        d_tr = None
    # 🏷 标识块 (老倪 2026-10-14): 一帧物理量必须自带"我在为谁干活" —— 任务/场景/产品质数/主参数。
    #    真源现算 (tools/ss_identity.py), 取不到写"真源未登记", 绝不用默认值糊。
    try:
        import ss_identity as _ident                                              # noqa: PLC0415
        _idb = _ident.identity(scene=scene, metric_cfg=cfg)
    except Exception as _e:                                                       # noqa: BLE001
        _idb = {"task_id": "真源未登记", "error": "%s: %s" % (type(_e).__name__, _e)}
    return {
        "ts": time.time(), "node": "流形引擎", "scene": scene,
        "identity": _idb,
        "stage": (getattr(act, "stage", "") if act is not None else ""),
        "skill": (getattr(act, "code", "") if act is not None else ""),
        "torque": [float(v) for v in tau_c6],                     # 已限幅+健康度缩 (= 可执行口径)
        "torque_raw": [float(v) for v in tau_raw6],               # ★ 限幅前原始 M·(−∇Φ) (不隐藏)
        "torque_norm": float(np.linalg.norm(tau_c6)),
        "torque_raw_norm": float(np.linalg.norm(tau_raw6)),
        "clipped": clipped, "t_max": float(t_max), "t_max_src": t_max_src,
        "t_max_norm_bound": float(t_max * np.sqrt(ROT_DIM)),   # 逐分量限幅 ⇒ 范数上界 √3·T_MAX (规格 §五)
        "torque_inv": [float(v) for v in tau_inv6],
        "unit": "N·m",
        "metric_tensor": [float(v) for v in M.ravel()],        # 真实 dim² 个 (dim=3 ⇒ 9); 不补零凑 36
        "metric_dim": int(M.shape[0]),
        "metric_M": float(metric.scale), "metric_mode": str(metric.mode),
        "metric_pd_ok": bool(pd_ok), "metric_eig_min": float(lmin), "metric_eig_max": float(lmax),
        "potential_gradient": [float(v) for v in grad6],
        "neg_gradient": [float(v) for v in neg6],
        "phi": float(phi), "phi_contrib": {k: (float(v) if isinstance(v, (int, float)) else v)
                                           for k, v in (contrib or {}).items()},
        "grad_raw_norm": float(np.linalg.norm(g_)),
        "dist_to_trough_m": d_tr,
        "health": H, "status": status, "gain": float(gain),
        "x": [float(v) for v in x], "gates": gates_str(br), "x_source": x_src,
        "source": ("M ← config/calib/zmax_manifold.json (%s, dim=%d, M=%.4f) · "
                   "−∇Φ ← potential_field 解析梯度 (%s) · x ← %s") % (
                      metric.mode, metric.dim, metric.scale, gates_str(br), x_src),
        "unit_note": UNIT_NOTE,
        "channels": {"data_hz": 10.0, "monitor_hz": None, "motor_hz": None,
                     "note": "规格三通道 (1000Hz 电机 / 100Hz 监控 / 10Hz 数据): 本实现只接 10Hz 数据通道; "
                             "100Hz 监控通道与 1000Hz 电机通道**未接** (无相应实时消费者/闭环, 如实标注)"},
        "note": ("T_drive = M·(−∇Φ) · 前 3 维转动分量恒 0: 势场 Φ 只定义在平移子空间 (如实标注, 不补零凑 6 维)"
                 if ROT_DIM == 3 else ""),
    }


# ─────────────────────── 落盘 (单一写入器 + 原子写 + 回读) ───────────────────────
def _pid_owner_alive() -> int | None:
    try:
        with io.open(PID, encoding="utf-8") as f:
            p = int(f.read().strip())
        os.kill(p, 0)
        return p
    except Exception:                                                             # noqa: BLE001
        return None


def publish(payload: dict) -> dict:
    os.makedirs(TAP_DIR, exist_ok=True)
    tp = _tap_path(payload["scene"])
    with io.open(tp, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _trim_tap(tp, int(TAP_MAX_MB * 1024 * 1024))   # 环形上限: 流不落盘无限长
    live = _live_path(payload["scene"])
    tmp = live + ".tmp.%d" % os.getpid()
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, live)
    # 回读 (单一写入器的自证: 落盘的就是算出来的)
    with io.open(live, encoding="utf-8") as f:
        back = json.load(f)
    return {"tap": tp, "live": live, "readback_ok": bool(back.get("ts") == payload["ts"])}


def cmd_once(scene: str) -> int:
    d = compute(scene)
    r = publish(d)
    print(json.dumps({"torque": [round(v, 6) for v in d["torque"]], "torque_norm": round(d["torque_norm"], 6),
                      "torque_raw_norm": round(d["torque_raw_norm"], 3), "clipped": d["clipped"],
                      "t_max": d["t_max"], "dist_to_trough_m": round(d["dist_to_trough_m"] or -1.0, 4),
                      "x_source": d["x_source"],
                      "phi": round(d["phi"], 6), "grad_raw_norm": round(d["grad_raw_norm"], 4),
                      "metric_dim": d["metric_dim"], "metric_M": d["metric_M"],
                      "health": round(d["health"], 4), "status": d["status"], "gain": d["gain"],
                      "gates": d["gates"], "x": [round(v, 4) for v in d["x"]],
                      "readback_ok": r["readback_ok"], "tap": os.path.basename(r["tap"])},
                     ensure_ascii=False, indent=1))
    return 0


def cmd_run(scene: str, hz: float, seconds: float) -> int:
    own = _pid_owner_alive()
    if own:
        print(json.dumps({"started": False, "reason": "已有写入器在跑 (pid %d)" % own}, ensure_ascii=False))
        return 1
    os.makedirs(TAP_DIR, exist_ok=True)
    with io.open(PID, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    from lerobot.memory.potential_field import MemoryLayerBridge
    br = MemoryLayerBridge.from_real_data(ROOT)                 # 只建一次 (建场要读真数据)
    dt = 1.0 / max(1e-6, float(hz))
    t0 = time.time()
    n, errs = 0, []
    # 🔀 2026-10-14: 场景**每 5s 重解析**一次 —— 原来 DEFAULT_SCENE 只在 import 时算一次, 于是"配置中心把
    #    活跃配置切到插拔"之后, 常驻发布器仍然按老场景发 (tap 名/payload.scene/标识块里的场景全是旧的), 必须
    #    手动重启服务才生效 ⇒ 现场表现"我切了任务, 数据空间里还是老场景"。显式指定 (--scene / env) 时不动。
    _scn_lock = bool(os.environ.get("ZMAX_TORQUE_SCENE"))
    _scn, _scn_t = scene, time.time()
    print("▶ 驱动扭矩发布: %.1fHz · %s · tap %s%s" % (
        hz, _scn, _tap_path(_scn), "" if _scn_lock else " · 场景每 5s 跟随活跃配置", ), flush=True)
    try:
        while seconds <= 0 or (time.time() - t0) < float(seconds):
            ts = time.time()
            if not _scn_lock and (time.time() - _scn_t) > 5.0:
                _scn_t = time.time()
                _new = _active_scene()
                if _new and _new != _scn:
                    print("🔀 场景跟随活跃配置: %s → %s · tap %s"
                          % (_scn, _new, _tap_path(_new)), flush=True)
                    _scn = _new
            try:
                d = compute(_scn, bridge=br)
                r = publish(d)
                n += 1
                if n % max(1, int(hz)) == 0:
                    print("  [%5.1fs] ‖T‖=%.3f N·m (raw %.1f%s) · Φ=%.3f · ‖∇Φ‖=%.2f · H=%.3f(%s) · x=%s · rd=%s"
                          % (time.time() - t0, d["torque_norm"], d["torque_raw_norm"],
                             "/限幅" if d["clipped"] else "", d["phi"], d["grad_raw_norm"],
                             d["health"], d["status"], np.round(d["x"], 3).tolist(), r["readback_ok"]), flush=True)
            except Exception as e:                                                # noqa: BLE001
                errs.append(repr(e)[:160])
                if len(errs) <= 3:
                    print("  ⚠️ 第 %d 帧失败: %s" % (n + len(errs), errs[-1]), flush=True)
            time.sleep(max(0.0, dt - (time.time() - ts)))
    finally:
        try:
            os.remove(PID)
        except Exception:                                                          # noqa: BLE001
            pass
    print(json.dumps({"published": n, "errors": errs[:3], "n_errors": len(errs),
                      "tap": _tap_path(scene), "seconds": round(time.time() - t0, 1)}, ensure_ascii=False))
    return 0 if n and not errs else 1


def cmd_status(scene: str) -> int:
    live = _live_path(scene)
    d = json.load(io.open(live, encoding="utf-8")) if os.path.isfile(live) else None
    print(json.dumps({"live": live, "age_s": (round(time.time() - d["ts"], 2) if d else None),
                      "writer_pid": _pid_owner_alive(),
                      "torque_norm": (d or {}).get("torque_norm"), "phi": (d or {}).get("phi"),
                      "health": (d or {}).get("health"), "status": (d or {}).get("status"),
                      "gates": (d or {}).get("gates"), "metric_dim": (d or {}).get("metric_dim"),
                      "source": (d or {}).get("source")}, ensure_ascii=False, indent=1))
    return 0 if d else 1


def cmd_selftest() -> int:
    """自检: 用报文体自带的 M/∇Φ 独立复算 T_drive（含规格限幅）, 与发布值逐位对账 + 正定性/增益一致性。"""
    ok = True
    d = compute(DEFAULT_SCENE)
    M = np.asarray(d["metric_tensor"], float).reshape(d["metric_dim"], d["metric_dim"])
    neg = np.asarray(d["neg_gradient"], float)
    tau = np.asarray(d["torque"], float)
    t_max = float(d["t_max"])
    raw = np.concatenate([np.zeros(ROT_DIM), M @ neg[ROT_DIM:]])
    exp = np.clip(raw, -t_max, t_max) * d["gain"]
    e1 = float(np.max(np.abs(tau - exp))) if tau.size else 9e9
    print("  ① torque == clip(M·(−∇Φ), ±%.0f)·gain (报文体自带 M/∇Φ 独立复算): 最大偏差 %.3e %s"
          % (t_max, e1, "✅" if e1 < 1e-9 else "❌"))
    ok &= e1 < 1e-9
    e1b = float(np.max(np.abs(np.asarray(d["torque_raw"], float) - raw)))
    print("  ①b torque_raw == M·(−∇Φ) (未限幅, 不隐藏): 最大偏差 %.3e %s"
          % (e1b, "✅" if e1b < 1e-9 else "❌"))
    ok &= e1b < 1e-9
    e2 = 0.0
    try:
        mi = np.linalg.inv(M @ np.eye(d["metric_dim"]))
        ninv = np.asarray(d["torque_inv"], float) / (d["gain"] or 1.0)
        e2 = float(np.max(np.abs(ninv[ROT_DIM:] - mi @ neg[ROT_DIM:])))
        print("  ② torque_inv == M⁻¹·(−∇Φ): 最大偏差 %.3e %s" % (e2, "✅" if e2 < 1e-6 else "❌"))
        ok &= e2 < 1e-6
    except Exception as e:                                                        # noqa: BLE001
        print("  ② torque_inv 复算跳过: %s" % repr(e)[:60])
    pd_ok, lmin, lmax = (d["metric_pd_ok"], d["metric_eig_min"], d["metric_eig_max"])
    print("  ③ 度量张量对称正定: %s (λmin=%.4f λmax=%.4f) %s" % (pd_ok, lmin, lmax, "✅" if pd_ok else "❌"))
    ok &= bool(pd_ok)
    want = {"normal": 1.0, "warning": 0.5, "critical": 0.0}.get(d["status"], 1.0)
    print("  ④ 增益与状态一致: status=%s gain=%.1f (期望 %.1f) %s" % (d["status"], d["gain"], want,
                                                                  "✅" if abs(d["gain"] - want) < 1e-12 else "❌"))
    ok &= abs(d["gain"] - want) < 1e-12
    inb = bool(np.max(np.abs(tau)) <= t_max * max(1.0, d["gain"]) + 1e-9)
    print("  ⑤ 限幅生效: 逐分量 |T_i| ≤ T_MAX=%.0f ⇒ ‖T‖ ≤ √3·T_MAX=%.2f (实测 ‖T‖=%.3f, raw=%.1f, clipped=%s) %s"
          % (t_max, t_max * np.sqrt(3), float(np.linalg.norm(tau)), d["torque_raw_norm"], d["clipped"],
             "✅" if inb else "❌"))
    ok &= inb
    print("  ⑥ 真实来源非零: ‖∇Φ_raw‖=%.3f (归一化后会变成 1.0 ⇒ 证明必须用 grad_raw) · Φ=%.4f · 开关 [%s] · x←%s %s"
          % (d["grad_raw_norm"], d["phi"], d["gates"], d["x_source"], "✅" if d["grad_raw_norm"] > 1e-6 else "⚠️(势场全关/在谷底)"))
    print("  ⑦ 诊断: 离最近技能谷底 %.3f m (解释 Φ/∇Φ 量级 —— 远离工作区时场本来就强)" % (d["dist_to_trough_m"] or -1.0))
    print("  自检: %s" % ("✅ 全过" if ok else "❌ 有失败"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="驱动扭矩 T_drive = M·(−∇Φ) → zmax/ss_torque")
    ap.add_argument("cmd", choices=["run", "once", "status", "selftest"])
    ap.add_argument("--scene", default=DEFAULT_SCENE)
    ap.add_argument("--hz", type=float, default=10.0, help="发布频率 (数据通道=10Hz, 规格 1000Hz 电机通道未接)")
    ap.add_argument("--seconds", type=float, default=0.0, help="跑多少秒 (0=直到被停)")
    a = ap.parse_args()
    if a.cmd == "run":
        return cmd_run(a.scene, a.hz, a.seconds)
    if a.cmd == "once":
        return cmd_once(a.scene)
    if a.cmd == "status":
        return cmd_status(a.scene)
    return cmd_selftest()


if __name__ == "__main__":
    raise SystemExit(main())
