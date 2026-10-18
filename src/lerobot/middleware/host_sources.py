# -*- coding: utf-8 -*-
"""本机真值文件 → 信号字段: **唯一一份**读法。

为什么: 数据空间 Trace 与「信号分析」必须看到同一批信号 (名字/条数/数值)。
两边各写一遍解析 ⇒ 技能物理量这类"嵌套 + 中文标签"的源必然漂 (老倪 2026-10-17:
「信号分析里 L2 信号 Tx 是 ① 接近 · SK01 有十多个, Trace 里 L2 Tx 接近就没有, 信号要数据同步」)。

口径:
  · gravity  (万有引力表) → 直取 s 键, 不过 flatten (94 条, flatten 48 键会截断)
  · skillphys(原子技能物理量) → skills.SK01..08 × 物理量标签 (136 条, 同上不能截断)
  · ar       (AR/AOI 总线) → 直取 s 键, 去掉元数据
  · 其它     → flatten_json (深度 3 / 48 键上限, 与历史口径一致)
"""
from __future__ import annotations

import json
import os
import time

ROOT = os.environ.get("ZMAX_REPO") or "/home/ubuntu/zmax"

# (前缀, 文件, 数据空间话题名) —— 顺序即界面顺序; 前三路由 live_signals 的实时快照接管
FILES = (
    ("sstrace", "zmax_data/ss_live/trace_live.json", "zmax/ss_state"),
    ("sseng", "zmax_data/ss_live/engine_trace.json", "zmax/ss_engine"),
    ("gravity", "zmax_data/ss_live/gravity_trace.json", "zmax/ss_torque"),
    ("skill", "zmax_data/ss_live/skill_latest.json", "zmax/ss_skill"),
    ("skillphys", "zmax_data/ss_live/skill_phys.json", "zmax/ss_skill_phys"),
    ("pose", "zmax_data/rokae_sdk/tcp_out/latest.json", "zmax/tcp_pose"),
    ("state", "zmax_data/rokae_sdk/tcp_out/state.json", "zmax/tcp_state"),
    ("safety", "zmax_data/vl_safety_fast.json", "zmax/vl_safety"),
    ("yolo", "zmax_data/ss_bypass/yolo_detections.json", "zmax/yolo_det"),
    ("space", "zmax_data/dataspace/live.json", "zmax/dataspace_live"),
    ("ar", "zmax_data/ar_live/ar_aoi_live.json", "zmax/ar_aoi"),
    # 📚 2026-10-18 老倪: 「l2_daemon 也要做一个节点，我要看到」—— 执行器真值 5Hz
    ("ss_exec", "zmax_data/ss_live/exec_state.json", "zmax/ss_exec"),
    # 🧭 2026-10-18: 段表 (plan 节点 n_moveit 的输出真值)
    ("planlive", "zmax_data/runtime/plan/plan_latest.json", "zmax/plan_live"),
)

# 原子技能物理量: 键名 = "<SK号> <阶段> · <物理量> <单位>"
_SKILL_FIELDS = (
    ("x", "x 位置 mm"), ("y", "y 位置 mm"), ("z", "z 位置 mm"),
    ("v_mms", "v 速度 mm/s"), ("a_mms2", "a 加速度 mm/s²"), ("s_mm", "s 段行程 mm"),
    ("angle", "angle 姿态角 deg"), ("err_mms", "err 削出偏差 mm/s"),
    ("v_cap", "v_cap 限速 m/s"), ("a_max", "a_max 加速度上限 m/s²"),
    ("jerk_max", "jerk_max 加加速度上限 m/s³"),
    ("s_step", "s_step 单拍位移上限 m"), ("s_max", "s_max 段行程上限 m"),
    ("m_kg", "m 运动质量 kg"), ("f_max", "F_max 力上限 N"),
    ("a", "a 姿态角 rx deg"), ("b", "b 姿态角 ry deg"), ("c", "c 姿态角 rz deg"),
    ("在职", "在职 1=在0=不在"), ("step", "step 块内拍号"), ("pose_age_s", "位姿帧龄 s"),
)


def flatten_json(d, prefix="", out=None, depth=0, cap=48):
    """JSON 数值叶子 → {key: float} (与画布/信号分析历史口径一致: 深度 3、48 键封顶)。"""
    if out is None:
        out = {}
    if depth > 3 or len(out) >= cap:
        return out
    if isinstance(d, dict):
        for k, v in d.items():
            flatten_json(v, f"{prefix}{k}.", out, depth + 1, cap)
    elif isinstance(d, (list, tuple)):
        for i, v in enumerate(list(d)[:16]):
            flatten_json(v, f"{prefix}{i}.", out, depth + 1, cap)
    elif isinstance(d, bool):
        out[prefix.rstrip(".")] = 1.0 if d else 0.0
    elif isinstance(d, (int, float)):
        out[prefix.rstrip(".")] = float(d)
    return out


def read(prefix, raw):
    """该文件的信号字段 {名字: 值} —— 两个窗口都调它, 不许各写一遍。"""
    if not isinstance(raw, dict):
        return {}
    if prefix == "gravity" and isinstance(raw.get("s"), dict):
        return {str(k): float(v) for k, v in raw["s"].items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if prefix == "skillphys" and isinstance(raw.get("skills"), dict):
        out = {}
        for code, rec in sorted(raw["skills"].items()):
            if not str(code).startswith("SK") or not isinstance(rec, dict):
                continue                       # "_元" 是元数据, 不是信号
            tag = "%s %s" % (code, str(rec.get("stage") or ""))
            for k, lab in _SKILL_FIELDS:
                v = rec.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out["%s · %s" % (tag, lab)] = float(v)
        return out
    # 🧭 2026-10-18 老倪: 「运动规划这些信号…感觉没啥用呢?」——
    #   原来整份段表 flatten 出 21 条 (含 t / segs.N.id / segs.N.service 这类恒等值), 屏幕全是噪音。
    #   这里只出**能回答问题的 11 条**: 几段/多远/多快(页面vs实际)/有没有被限速/是不是人工回点/每段多远/数据多新。
    # 🧭 2026-10-18 老倪: 「signal 的命名全错了，要表达出这个信号的功能，全部重改」
    #   命名规则: 名词说明"是什么量", 后缀 _mm/_mms 说明单位; 不再用 n / v_page / seg1 这种看不出功能的短名。
    #   · 分段距离按**动作角色**归类 (抬升/横移/下落), 而不是按序号 —— 序号说不出它在干什么。
    # 🎯 2026-10-18 老倪: 「不就是 plan 一个目标点么」+「位姿是 6 自由度, 角度呢」——
    #   plan = 目标位姿 6 自由度 + 总路程 + 速度保留几成; 帧龄走 Trace 自己的列, 不再单列信号(重复占资源)。
    if prefix == "planlive":
        _req, _real = raw.get("req_speed_mm_s"), raw.get("speed_mm_s_actual")
        _o = {"target_x_mm": raw.get("target_x_mm"), "target_y_mm": raw.get("target_y_mm"),
              "target_z_mm": raw.get("target_z_mm"),
              "target_rx_deg": raw.get("target_rx_deg"), "target_ry_deg": raw.get("target_ry_deg"),
              "target_rz_deg": raw.get("target_rz_deg"),
              "travel_mm": raw.get("lin_total_mm"),
              "speed_kept_pct": (round(100.0 * float(_real) / float(_req), 1) if _req else None)}
        return {k: float(v) for k, v in _o.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if prefix == "ss_exec":
        _o = {"exec_phase": raw.get("phase_code"), "stage_now": raw.get("seg"), "stage_total": raw.get("n_seg"),
              "arrive_error_mm": raw.get("residual_mm")}
        return {k: float(v) for k, v in _o.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if prefix in ("ar", "sskill") and isinstance(raw.get("s"), dict):
        meta = ("ts", "t", "age", "meta", "groups", "schema")
        return {str(k): float(v) for k, v in raw["s"].items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
                and str(k).split(".")[0] not in meta}
    return flatten_json(raw, "", {}, 0, 48)


def read_file(prefix, rel, ttl=0.0):
    """读文件 → {fields, ts, age_s} (ttl>0 时按 ttl 缓存)。"""
    p = os.path.join(ROOT, rel)
    try:
        st = os.stat(p)
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:                                                       # noqa: BLE001
        return None
    fields = read(prefix, raw)
    ts = raw.get("ts") if isinstance(raw.get("ts"), (int, float)) else st.st_mtime
    return {"fields": fields, "ts": float(ts), "age_s": round(max(0.0, time.time() - st.st_mtime), 2)}


def topics(now=None):
    """{topic: {fields, ts, age_s, prefix}} —— 数据空间侧的全部本机真值话题。"""
    out = {}
    for prefix, rel, topic in FILES:
        got = read_file(prefix, rel)
        if not got or not got["fields"]:
            continue
        out[topic] = dict(got, prefix=prefix)
    return out
