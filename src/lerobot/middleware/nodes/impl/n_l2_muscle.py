# -*- coding: utf-8 -*-
"""n_l2_muscle — 节点实现正文 (文件名 = 画布节点: n_l2_muscle)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_n_l2_muscle   ·   registry key: n_l2_muscle
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _L2M_CACHE,
    _REPO_ROOT,
    _SS_STATE,
    _load_mod,
    os,
    time,
)

def node_n_l2_muscle(ctx):
    """💪 L2 肌肉记忆技能库 (光模块抓放循环) — 读**真实技能 JSON** + ROS2 桥**只读**状态。
    真执行: data/skills/l2_muscle/*.json (技能定义) + tools/l2_ros2_bridge.py (仅查询)。
    ⚠ 只读纪律: 本节点**不调** run_step/cmd_move → 不下发任何真机动作 (动作须人工授权)。"""
    log = ctx.get("log") or (lambda *a: None)
    try:
        import glob as _g
        import json as _json
        pr = ctx.get("params") or {}
        sk = str(pr.get("skill") or os.path.join(_REPO_ROOT, "data", "skills", "l2_muscle",
                                                 "光模块_抓放循环_v1.json"))
        if not os.path.isfile(sk):
            cands = sorted(_g.glob(os.path.join(_REPO_ROOT, "data", "skills", "l2_muscle", "*.json")))
            if not cands:
                log("⚠ L2 肌肉记忆技能库: 无技能 JSON → 未固化任何标杆")
                return False
            sk = cands[0]
        d = _json.load(open(sk, encoding="utf-8"))
        steps = d.get("steps") or d.get("points") or []
        log(f"💪 L2 肌肉记忆技能库 · {os.path.basename(sk)}")
        log(f"   技能 {d.get('id')} · 层 {d.get('layer')} · 类型 {d.get('kind')} · 段数 {len(steps)}")
        for i, s in enumerate(steps[:10], 1):
            txt = s if isinstance(s, str) else " · ".join(
                f"{k}={s[k]}" for k in list(s)[:4]) if isinstance(s, dict) else str(s)
            log(f"   {i}. {txt}")
        if d.get("params"):
            log(f"   ⚙ 参数: {_json.dumps(d['params'], ensure_ascii=False)[:160]}")
        # ROS2 桥: **只读**查询 (有界超时, 避免卡 GUI); Orin 不在线则如实报
        # 🚦 2026-11-01: 原每拍都跑 `timeout 6 ros2 topic echo` (上限 10s), Orin 不在位时整圈被它吃掉
        #   (py-spy 15 次采样 8 次停在本节点) ⇒ 常驻循环里按节拍查询 (ZMAX_L2M_EVERY_S, 默认 30s), 超时 3s。
        _now = time.time()
        _in_loop = bool(os.environ.get("ZMAX_CANVAS_HZ"))
        _every = float(os.environ.get("ZMAX_L2M_EVERY_S") or (30.0 if _in_loop else 0.0))
        if _now - _L2M_CACHE["t"] < _every:
            return True
        _L2M_CACHE["t"] = _now
        try:
            bp = os.path.join(_REPO_ROOT, "tools", "l2_ros2_bridge.py")
            bm = _load_mod("zmax_l2_ros2_bridge", bp)        # 正常 import (断点可绑)
            o = bm.sh("timeout 3 ros2 topic echo --once /robot_status 2>/dev/null | head -2",
                      float(os.environ.get("ZMAX_L2M_TIMEOUT_S") or 4.0))
            ok = bool(str(o).strip())
            log(f"   🔌 ROS2 桥 (只读): {'在线 · ' + str(o).strip()[:120] if ok else '无响应 (Orin 未连/未起)'}"
                f" · 桥文件 {os.path.basename(bp)}")
            _SS_STATE["l2_muscle_ros2"] = ok
        except Exception as e:                                                 # noqa: BLE001
            log(f"   🔌 ROS2 桥 (只读): 查询失败 {type(e).__name__}")
        return True
    except Exception as e:                                                     # noqa: BLE001
        log(f"⚠️ L2 肌肉记忆技能库失败: {type(e).__name__}: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_n_l2_muscle
