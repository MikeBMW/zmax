# -*- coding: utf-8 -*-
"""信号归属: 这条信号是**哪个节点发的 (Tx)** / 从哪来 (Rx) / 在哪一层 (Layer)。

为什么单独一个模块: 「信号分析」窗口与「全局数据空间 Trace」必须显示同一套 Tx/Rx/Layer
—— 老倪 2026-10-17: 「Trace窗口 Tx Rx 要跟信号分析的 Tx Rx 同步, 你现在显示的不一样;
其它数据也要同步, 你检查」。两边各写一份映射必然漂, 所以真源只留这一份, 两个窗口都调它。

证据链 (每条都能复核, 不猜):
  · sstrace.*   ← zmax_data/ss_live/trace_live.json, 由 3D 场景面板逐帧发布 (ss_dreamview.publish_trace_live)
  · sseng.*     ← engine_trace.json, 由常驻回路 ss_engine_loop 写 (流形引擎节点)
  · gravity.*   ← gravity_trace.json, 由 tools/gravity_trace_pub.py 搬「主参数 M 页」那张表的
                  GravityField 发布 —— 画布里**没有**这个节点 ⇒ Tx 写进程名, 不编节点名。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

# 三份实时文件 ↔ 话题 (Trace 侧按话题取归属, 信号分析侧按文件前缀取归属)
LIVE_PREFIX = {"zmax/ss_state": "sstrace", "zmax/ss_engine": "sseng", "zmax/ss_torque": "gravity"}
LIVE_TOPICS = set(LIVE_PREFIX)

# (键前缀, 画布 node_id 或 None, 无节点时的进程名) —— 顺序要紧: 长的/具体的排前面
OUT_NODE = (
    ("gravity.", None, "gravity_trace_pub.py (万有引力表进程)"),
    ("sseng.势能_phi", "ss_mani_eng", ""),
    ("sseng.梯度范数", "ss_mani_eng", ""),
    ("sseng.动量M", "ss_mani_eng", ""),
    ("sseng.置信度", "ss_mani_eng", ""),
    ("sseng.元任务数", "ss_mani_eng", ""),
    ("sseng.内稳态", "ss_mani_eng", ""),
    ("sseng.顶层补偿", "ss_mani_eng", ""),
    ("sseng.动作调制", "sssched", ""),
    ("sseng.skill闸.", "ssphys", ""),
    ("sseng.潜表示", "ssvlm", ""),
    ("sseng.chunk.", "ss_mani_eng", ""),
    ("sseng.", "ss_mani_eng", ""),
    ("ds.zmax/ss_meta_pred", "n_intent_direct", ""),
    ("ds.zmax/ss_action_chunk", "ss_mani_eng", ""),
    ("sstrace.前馈速度", "ssff", ""),
    ("sstrace.动作调制", "sssched", ""),
    ("sstrace.阶段", "sssched", ""),
    ("sstrace.八阶段序号", "sssched", ""),
    ("sstrace.安全边界", "sslimit", ""),
    ("sstrace.接触概率", "ssinnov", ""),
    ("sstrace.光模块头", "ss2d3d", ""),
    ("sstrace.吸嘴到槽位", "ss2d3d", ""),
    ("sstrace.光模块", "ssyolo", ""),
    ("sstrace.真空吸持", "ssact", ""),
    ("sstrace.夹爪", "ssact", ""),
    ("sstrace.夹持", "sstactile", ""),
    ("sstrace.环境接触", "sstactile", ""),
    ("sstrace.吸附力", "sstactile", ""),
    ("sstrace.光学质量检测", "ssaoi", ""),
    ("sstrace.AOI", "ssaoi", ""),
    ("sstrace.末端", "swworld", ""),
    ("sstrace.", "swworld", ""),
    ("skillphys.", None, "zmax-ss-skill-dispatch (技能派发服务)"),
    ("skill.", None, "zmax-ss-skill-dispatch (技能派发服务)"),
    ("ros./robot/tcp_pose", None, "ros_bridge (Orin ROS2)"),
    ("ros.", None, "ros_bridge (Orin ROS2)"),
    ("ds.", None, "dds_bridge (全局数据空间)"),
    ("yolo.", "ssyolo", ""),
    ("space.", "sssensor", ""),
    ("safety.", "sslimit", ""),
    ("pose.", None, "pose_tap (真机 tcp_pose 50Hz)"),
    ("aoi.", "ssaoi", ""),
    ("光学质量检测.", "ssaoi", ""),
    ("AOI.", "ssaoi", ""),
    ("ar.", None, "ar_l5_understand.py (AR/AOI 信号总线)"),
    ("catalog.", None, "catalog_worker (话题目录)"),
)

# sstrace.* 具体信号 ← 上游来源 (顺序要紧: 长前缀在前)
SS_TRACE_SRC = (
    ("光模块头到孔", "L2 引擎 (孔口 objects3d.json)"),
    ("吸嘴到槽位", "L2 引擎 (槽位 objects3d.json) · 摆盘"),
    ("末端", "/robot/tcp_pose (Orin 50Hz)"),
    ("光模块头", "YOLO 3D 检测 (旁路 JSON)"),
    ("光模块", "YOLO 3D 检测 (旁路 JSON)"),
    ("真空吸持", "/gripper_pos (Orin) · 摆盘=吸附建立(0.9)"),
    ("夹爪", "/gripper_pos (Orin)"),
    ("环境接触", "/robot/force_torque (Orin)"),
    ("吸附力", "/robot/force_torque (Orin) · 摆盘=吸持力"),
    ("夹持", "/robot/force_torque (Orin)"),
)

_NODES = {"sig": None, "map": {}}


def _load_nodes():
    """工程库节点 → 归一显示名 (naming.clean 口径), 工程库变了就重载。"""
    try:
        from lerobot.middleware import db
        from lerobot.middleware import naming
        sig = os.path.getmtime(os.path.join(ROOT, "data/database/zmax/zmax_engineering.db"))
        if _NODES["sig"] == sig and _NODES["map"]:
            return _NODES["map"]
        rows = db.node_rows()
        m = naming.unique_map([(r["node_id"], str(r.get("name") or r["node_id"])) for r in rows])
        _NODES.update(sig=sig, map=m)
        return m
    except Exception:                                                     # noqa: BLE001
        return _NODES["map"]


def _node_layer(node_id):
    try:
        from lerobot.middleware import db
        for r in db.node_rows():
            if r["node_id"] == node_id:
                lay = str(r.get("layer") or "")
                return "SYS" if lay == "meta" else (lay or "—")
    except Exception:                                                     # noqa: BLE001
        pass
    return "SYS"


def _rule(key):
    k = str(key or "")
    for pre, nid, proc in OUT_NODE:
        if k.startswith(pre):
            return nid, proc
    return None, ""


def tx_of(key):
    """Tx: 发送这条信号的节点名; 没有画布节点就写进程名 (不编节点)。"""
    nid, proc = _rule(key)
    if nid:
        nm = _load_nodes().get(nid)
        if nm:
            return nm
    return proc or "本机真值流"


def rx_of(key):
    """Rx: 这条信号的上游来源 (与信号分析窗口同一串字)。"""
    k = str(key or "")
    if k.startswith("ar."):
        return "🥽 AR/AOI 信号总线 · AR 场景"
    if k.startswith("sstrace."):
        n = k[8:]
        for pre, s in SS_TRACE_SRC:
            if n.startswith(pre):
                return s
        return "L2 状态空间引擎 (无话题)"
    if k.startswith("ros."):
        return "Orin ROS2"
    if k.startswith("ds."):
        return "DDS · " + k[3:].split(".")[0]
    if k.startswith("skill.") or k.startswith("skillphys."):
        return "技能派发服务 (每技能最新一拍)"
    if k.startswith("gravity."):
        return "万有引力表 (主参数 M 页)"
    return "本机真值流 (JSON)"


def layer_of(key):
    """Layer: 生产节点所在的层 (L2~L5), 查不到 = SYS。

    特例: gravity.* 的键**自带层** (下降·L2 力大小_mps ⇒ L2; 列L3·合力 ⇒ L3) ——
    那张表每格就是「某层对本元任务的力」, 用键里的层比拿节点层更准。
    """
    k = str(key or "")
    if k.startswith("gravity."):
        _m = re.search(r"(?:·|列)(L[2-5])", k)
        return _m.group(1) if _m else "SYS"
    nid, _proc = _rule(key)
    if nid:
        return _node_layer(nid)
    return "SYS"


# ── 数值/单位口径: 两个窗口必须显示同一串字 ──────────────────────────────
def is_speed(key):
    """速度类信号 (键以 _mps 结尾/开头段) ⇒ 界面按 mm/s 显示。"""
    k = str(key)
    return k.endswith("_mps") or "_mps." in k


def unit_scale(key):
    return 1000.0 if is_speed(key) else 1.0


def fmt_value(v, key):
    """与信号分析窗口同一个格式: 先按单位换算, 再 4 位有效数字 (≥1e5 用 3 位)。"""
    try:
        x = float(v) * unit_scale(key)
    except Exception:                                                     # noqa: BLE001
        return str(v)
    return ("%.4g" % x) if abs(x) < 1e5 else ("%.3g" % x)


def display_unit(key, unit):
    """单位串: 速度键固定 mm/s (真源 m/s ×1000), 其它用登记单位。"""
    if is_speed(key):
        return "mm/s"
    return unit or "—"


def key_of(topic, field):
    """Trace 侧: 话题 + 信号键 → 归属键 (实时三话题才做映射; 其它返回 None)。"""
    pref = LIVE_PREFIX.get(str(topic or ""))
    if not pref:
        return None
    return "%s.%s" % (pref, field)
