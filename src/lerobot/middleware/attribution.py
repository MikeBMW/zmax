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
from functools import lru_cache

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

# 三份实时文件 ↔ 话题 (Trace 侧按话题取归属, 信号分析侧按文件前缀取归属)
LIVE_PREFIX = {
    "zmax/ss_state": "sstrace", "zmax/ss_engine": "sseng", "zmax/ss_torque": "gravity",
    # 2026-10-17: 技能物理量/派发/位姿/状态/安全/YOLO/数据空间也进了全局快照 ⇒ 同一套归属规则
    "zmax/ss_skill": "skill", "zmax/ss_skill_phys": "skillphys",
    "zmax/tcp_pose": "pose", "zmax/tcp_state": "state", "zmax/vl_safety": "safety",
    "zmax/yolo_det": "yolo", "zmax/dataspace_live": "space", "zmax/ar_aoi": "ar",
    # ⚙️ 2026-10-18: 执行器实时状态 (l2_daemon 5Hz) —— 节点 n_exec, L2
    "zmax/ss_exec": "ss_exec",
    "zmax/plan_live": "planlive",
}
LIVE_TOPICS = set(LIVE_PREFIX)

# 📚 2026-10-17 老倪: 「所有的 Topic, 都在 L2~L5 层定义, Tx Rx 节点都是 L2~L5 层的 node 节点,
#   与状态空间的工程都是同一个数据源, 保证 node 的严格相同」
#   ⇒ 本机真值流 (zmax_data/ss_live/*.json) 的每个前缀, 都归到工程里**真正拥有这份数据**的节点;
#     归属关系写在这里, 由工程库 node_id 解释层与显示名 —— 不另造节点, 也不拿进程名顶上。
#     space (zmax/dataspace_live 是探针自己的快照, 不是总线信号) ⇒ 无节点, 不进 Trace。
PREFIX_OWNER = {
    "sstrace": "ssest",        # 3D 插拔场景状态 (末端/光模块/夹持) ← 自适应状态估计器 L2
    "ss_exec": "n_exec",       # ⚙️ 执行器实时状态 (2026-10-18 新增节点) L2
    "planlive": "n_moveit",    # 🧭 段表 = 运动规划节点的输出 (2026-10-18)
    "sseng": "ss_mani_eng",    # 流形引擎周期回路出口 (势能/动量M/动作调制) L4
    "gravity": "n_calib_mani",  # 万有引力表 = 标定诊断测量·主参数 M 的力矩阵 L4
    "pose": "ssest",           # 真机 tcp_pose tap → 状态估计 L2
    "state": "ssest",          # 真机 tcp_state tap → 状态估计 L2
    "yolo": "ssyolo",          # YOLO 目标检测 L2
    "safety": "sslimit",       # 安全执行边界 (项目内 meta 节点, 有层就有归属)
    "ar": "ssaoi",             # AR/AOI 信号总线 → 光学质量检测 L2
    "space": None,             # 数据空间探针快照: 不是总线话题, 不入 Trace
}

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
    # 🧭 2026-10-17 老倪: 「实际上也没有连线啊, 没有这个连接」—— 闭环内部算出来的量, 归到真正算它的
    #   L2 节点 (估计器/校正器) 或真正写这份快照的进程 (3D 回放), 不再一律糊成 catch-all「Z-MAX 引擎」。
    ("sstrace.估计", "ssest", ""),
    ("sstrace.残差", "ssinnov", ""),
    ("sstrace.净接触", "ssinnov", ""),
    ("sstrace.帧", None, "ss_dreamview (3D 场景回放)"),
    ("sstrace.总帧", None, "ss_dreamview (3D 场景回放)"),
    ("sstrace.时间_s", None, "ss_dreamview (3D 场景回放)"),
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
# 📚 仅存档: 当年各信号的取数来源 (2026-10-17 老倪要求 Rx 全部清空, 下表不再参与显示)
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
        for _f in (tx_of, layer_of, rx_of):        # 工程库变了 ⇒ 归属缓存作废
            try:
                _f.cache_clear()
            except Exception:                                             # noqa: BLE001
                pass
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


# 🔧 原子技能 (L2): 画布上真有这 8 个节点 ——「① 接近 · SK01」…「⑧ 完成 · SK08」。
#   老倪 2026-10-17: 「信号分析窗口, 怎么没有 L2 级别, 原子技能功能 的输出信号? 例如 SK01 节点呢?」
#   原来 skill./skillphys. 统一落到进程名 zmax-ss-skill-dispatch + SYS 层 ⇒ 按 L2 过滤就看不见了。
SKILL_STAGE = (("接近", "SK01"), ("对位", "SK02"), ("下降", "SK03"), ("抓取", "SK04"),
               ("抬起", "SK05"), ("转移", "SK06"), ("插入", "SK07"), ("完成", "SK08"))


def skill_stage_of(key):
    """从键里认出是哪个原子技能: 'skill.转移.action_x' / 'skillphys.SK01 接近 · …' ⇒ SK0x。"""
    k = str(key or "")
    if not k.startswith(("skill.", "skillphys.", "skill_dispatch.")):
        return None
    m = re.search(r"SK0([1-8])", k)
    if m:
        return "SK0" + m.group(1)
    for name, sk in SKILL_STAGE:
        if name in k:
            return sk
    return None


def _nodes_by_name():
    """{SK0x: (显示名, 层)} —— 从工程库节点名里认 '① 接近 · SK01' 这种。

    📚 2026-10-17 老倪: 「与状态空间的工程都是同一个数据源，保证 node 的严格相同」
    ⇒ 显示名统一走 naming.unique_map (面板/Trace/数据空间同一个词表, 且 75 个节点一一对应),
      不再这里另拼 "① 接近 · SK01" —— 那是工程库原名, 与其它面板显示名不同源。
    """
    out = {}
    try:
        from lerobot.middleware import db, naming
        _rows = db.node_rows()
        _clean = naming.unique_map([(r.get("node_id"), r.get("name")) for r in _rows])
        for r in _rows:
            nm = str(r.get("name") or "")
            m = re.search(r"(SK0[1-8])\s*$", nm)      # 只认阶段节点本身, 不认 "(SK01-08)" 这种说明
            if m:
                lay = str(r.get("layer") or "")
                out[m.group(1)] = (_clean.get(r.get("node_id")) or nm,
                                   "L2" if lay == "meta" else (lay or "L2"))
    except Exception:                                                     # noqa: BLE001
        pass
    return out



@lru_cache(maxsize=1)
def _node_ports():
    """节点端口话题 → (node_id, port, dir, peers)。真源 config/platform/dds_topic_types.json。

    老倪 2026-10-17: 「moveit 节点输出的信号呢? topic 怎么不在 trace L2 层里?」
    根因: ss.node.<id>.<port> 没有归属规则 ⇒ layer_of() 一律 SYS, 而 Trace 已把 SYS 删了 ⇒ 整行消失。
    """
    import json as _j
    path = os.path.join(ROOT, "config/platform/dds_topic_types.json")
    try:
        with open(path, encoding="utf-8") as f:
            nodes = (_j.load(f) or {}).get("nodes") or {}
    except Exception:                                                    # noqa: BLE001
        return {}
    m = {}
    for nid, rec in nodes.items():
        for port, pr in (rec.get("ins") or {}).items():
            t = pr.get("topic") or ("ss.node.%s.%s" % (nid, port))
            m[t] = (nid, port, "in", tuple(pr.get("producers") or ()))
        for port, pr in (rec.get("outs") or {}).items():
            t = pr.get("topic") or ("ss.node.%s.%s" % (nid, port))
            m[t] = (nid, port, "out", tuple(pr.get("consumers") or ()))
    return m


def port_of(key):
    """'ss.node.n_moveit.out1' / 'ss.node.n_moveit.out1.code' → (nid, port, dir, peers) 或 None。"""
    k = str(key or "")
    if not k.startswith("ss.node."):
        return None
    parts = k.split(".")
    if len(parts) < 4:
        return None
    t = ".".join(parts[:4])
    return _node_ports().get(t)


def _peer_name(pid):
    """'ssact.out1' → 画布节点名 (没有就用节点 id / 进程名, 不编)。"""
    nid = str(pid or "").split(".")[0]
    nm = _load_nodes().get(nid)
    if nm:
        return nm
    try:
        from lerobot.middleware import cn_names
        return cn_names.cn_of_node(nid, nid)
    except Exception:                                                    # noqa: BLE001
        return nid


def _rule(key):
    k = str(key or "")
    _p = port_of(k)
    if _p:
        return _p[0], ""                      # ss.node.* 端口话题 ⇒ 归属到该节点 (Layer/Tx/Rx 全套)
    for pre, nid, proc in OUT_NODE:
        if k.startswith(pre):
            return nid, proc
    return None, ""


@lru_cache(maxsize=16384)
def tx_of(key):
    """Tx: 发送这条信号的工程节点名; 没有节点写 "—" (绝不写进程名)。"""
    # 明确不属于工程的前缀 (如 space = 数据空间探针自己的快照) ⇒ 直接不给 Tx ⇒ 层 SYS ⇒ 不进 Trace
    if PREFIX_OWNER.get(str(key or "").split(".", 1)[0], "__none__") is None:
        return "—"
    _st = skill_stage_of(key)
    if _st:
        _nm = _nodes_by_name().get(_st, ("", ""))[0]
        if _nm:
            return _nm
    _p = port_of(key)
    if _p:
        _nid, _port, _dir, _peers = _p
        if _dir == "in" and _peers:
            _u = list(dict.fromkeys(_peers))                              # 去重: 工程里 ssff.out1 的
            return " / ".join(_peer_name(x) for x in _u[:4])              # consumers 写了两遍同一个
        return _load_nodes().get(_nid) or _nid                          # 出端口: 本节点
    # 本机真值流前缀: 先按 PREFIX_OWNER 认工程节点 (真值流不是画布端口, 但数据有归属)
    # 先看字段级规则 (sstrace.前馈速度 → 前馈加速器 这种具体归属), 规则里没节点才用前缀属主
    nid, proc = _rule(key)
    _own = PREFIX_OWNER.get(str(key).split(".", 1)[0], "__none__")
    if nid:
        nm = _load_nodes().get(nid)
        if nm:
            return nm
    # _own 已在上面取过 (可能为 None = 明确不入 Trace)
    if _own:
        _nm = _load_nodes().get(_own)
        if _nm:
            return _nm
    # 仍然没有工程节点 ⇒ "—" (绝不拿进程名冒充; 进程名只留在 source_of 的"来源")
    return "—"


@lru_cache(maxsize=16384)

@lru_cache(maxsize=1)
def _sk_node_id_by_stage():
    """{SK0x: node_id} —— 阶段 → 工程节点 (名字以 SK0x 结尾的那个)。"""
    out = {}
    try:
        from lerobot.middleware import db
        for r in db.node_rows():
            m = re.search(r"(SK0[1-8])\s*$", str(r.get("name") or ""))
            if m:
                out[m.group(1)] = r.get("node_id")
    except Exception:                                                     # noqa: BLE001
        pass
    return out


def _sk_node_id(stage):
    return _sk_node_id_by_stage().get(stage)


def rx_of(key):
    """Rx: 这条信号的上游/下游节点 (与信号分析窗口同一串字)。"""
    k = str(key or "")
    # 原子技能: skill.* 不是端口键, 但它落到的 SK 节点有真连线 ⇒ Rx 取该节点的出端口下游
    _st = skill_stage_of(k)
    if _st:
        _nid = _sk_node_id(_st)
        if _nid:
            try:
                from lerobot.middleware import db
                for _r in db.node_rows():
                    if _r.get("node_id") != _nid:
                        continue
                    _peers = []
                    for _o in (_r.get("outs") or []):
                        _peers.extend(_o.get("to") or [])
                    _u = list(dict.fromkeys(_peers))
                    if _u:
                        return " / ".join(_peer_name(x) for x in _u[:4])
            except Exception:                                                 # noqa: BLE001
                pass
    # ⚙️ 2026-10-18 老倪: 「l2_daemon 也要做一个节点，我要看到」——
    #   执行器实时状态 ss_exec.* 不是端口键, 但归属节点 n_exec 的出端口有真连线 (n_exec.out1 → 机器人执行器)
    #   ⇒ Rx 取该节点的下游; 没有连线就仍是 "—"(不编)。
    if k.startswith(("ss_exec.", "planlive.")):
        try:
            from lerobot.middleware import db as _db2
            for _r in _db2.node_rows():
                if _r.get("node_id") != ("n_exec" if k.startswith("ss_exec.") else "n_moveit"):
                    continue
                _peers = []
                for _o in (_r.get("outs") or []):
                    _peers.extend(_o.get("to") or [])
                _u2 = list(dict.fromkeys(_peers))
                if _u2:
                    return " / ".join(_peer_name(x) for x in _u2[:4])
        except Exception:                                                # noqa: BLE001
            pass
    _p = port_of(k)
    if _p:
        _nid, _port, _dir, _peers = _p
        if _dir == "out" and _peers:
            _u = list(dict.fromkeys(_peers))
            return " / ".join(_peer_name(x) for x in _u[:4])              # 出端口: 下游接收节点
        if _dir == "in":
            return _load_nodes().get(_nid) or _nid                        # 入端口: 本节点收

    # 📚 2026-10-17 老倪: 「万有引力表进程，怎么能在 Tx 的发送节点呢？也没有万有引力这个节点啊」
    #   Tx/Rx 两列都只放**画布上的真节点名**; 总线/进程/服务这类标签不进这两列 (它们不是节点,
    #   也不是画布连线), 没有真连线一律 "—"。同一口径同样套用下面的 ros./ds./skill./gravity.。
    if k.startswith("ar."):
        return "—"
    if k.startswith("sstrace."):
        # 🚫 2026-10-17 老倪: 「实际上也没有连线啊 … 都清掉」
        #   3D 插拔场景这一族信号 (sstrace.*) 在画布上没有一条实连线 ⇒ Rx 全部空着, 不写来源。
        #   SS_TRACE_SRC 只作历史存档 (知道当年这些数是从哪路取的), **不进 Rx 显示**。
        return "—"
    if k.startswith("ros."):
        return "—"
    if k.startswith("ds."):
        return "—"
    if k.startswith("skill.") or k.startswith("skillphys."):
        return "—"
    if k.startswith("gravity."):
        return "—"
    # 📚 2026-10-17 老倪: 「Tx Rx 节点都是 L2~L5 层的 node 节点」⇒ Rx 只认真连线;
    #   没有上游节点就 "—", 不再回落到 "本机真值流 (JSON)" 这种非节点字符串。
    return "—"


@lru_cache(maxsize=16384)
@lru_cache(maxsize=8192)
def source_of(key):
    """这条信号的**实际出处** (总线/进程/服务/DDS 路由)。

    老倪 2026-10-17: 「万有引力表进程，怎么能在 Tx 的发送节点呢？也没有万有引力这个节点啊」
    ⇒ Tx/Rx 只放画布节点名; 出处这类说明只进行 tooltip 的「来源:」, 不再冒充节点。
    """
    k = str(key or "")
    if k.startswith("ar."):
        return "🥽 AR/AOI 信号总线 · AR 场景"
    if k.startswith("ros."):
        return "Orin ROS2"
    if k.startswith("ds."):
        return "DDS · " + k[3:].split(".")[0]
    if k.startswith("skill.") or k.startswith("skillphys."):
        return "技能派发服务 (每技能最新一拍)"
    if k.startswith("gravity."):
        return "万有引力表 (主参数 M 页)"
    if k.startswith("sstrace."):
        return SS_TRACE_SRC or "3D 场景回放 (ss_dreamview)"
    if port_of(k):
        return "画布端口 (工程库)"
    return "本机真值流 (JSON)"


@lru_cache(maxsize=1)
def _name_layer():
    """{显示名: 层} —— 由工程库 + naming 生成, 与 Tx 显示的字符串同一份词表。"""
    try:
        from lerobot.middleware import db, naming
        _rows = db.node_rows()
        _c = naming.unique_map([(r.get("node_id"), r.get("name")) for r in _rows])
        out = {}
        for r in _rows:
            nm = _c.get(r["node_id"]) or ""
            if not nm:
                continue
            lay = str(r.get("layer") or "")
            # 8 个原子技能节点在工程库里是 meta 容器, 但信号层归 L2 (与 _nodes_by_name 同口径)
            # 只对"阶段节点"本身 (名字以 SK0x 结尾) 把 meta 归一成 L2;
            # 「⚖ 物理约束 · 惯性/质量率闸 (SK01-08)」这种**不是**阶段节点, 仍是 meta (可视化/约束层)
            if lay == "meta" and re.search(r"SK0[1-8]\s*$", str(r.get("name") or "")):
                lay = "L2"
            out[nm] = lay
        return out
    except Exception:                                                     # noqa: BLE001
        return {}


def layer_of(key):
    """Layer: 生产节点所在的层 (L2~L5), 查不到 = SYS。

    特例: gravity.* 的键**自带层** (下降·L2 力大小_mps ⇒ L2; 列L3·合力 ⇒ L3) ——
    那张表每格就是「某层对本元任务的力」, 用键里的层比拿节点层更准。
    """
    k = str(key or "")
    # 📚 2026-10-17 老倪: 「Tx Rx 节点都是 L2~L5 的 node 节点, 保证 node 的严格相同」
    #   ⇒ Layer 必须和 Tx 是同一个节点算出来的 (以前两条路径各查各的, 会出现
    #     "Tx=Z-MAX 引擎(L4) 但 Layer=L2" 这种自相矛盾)。
    _nm = str(tx_of(k)).split(" / ")[0].strip()
    _lay = _name_layer().get(_nm)
    if _lay:
        return "SYS" if _lay == "meta" else _lay
    # 真值流: 层 = 拥有这份数据的工程节点的层 (与 Tx 同一节点, 不许两头不一致)
    _own = PREFIX_OWNER.get(k.split(".", 1)[0], "__none__")
    if _own != "__none__":
        if not _own:
            return "SYS"                      # 无归属 (如数据空间探针快照) ⇒ SYS ⇒ Trace 不显示
        return _node_layer(_own)
    if k.startswith("gravity."):
        _m = re.search(r"(?:·|列)(L[2-5])", k)
        return _m.group(1) if _m else "SYS"
    _st = skill_stage_of(key)
    if _st:
        return _nodes_by_name().get(_st, ("", "L2"))[1]
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
    """Trace 侧: 话题 + 信号键 → 归属键。

    节点端口话题 (ss.node.<id>.<port>) 也返回归属键 ⇒ Trace 的 Layer/Tx/Rx 与信号分析同口径,
    否则 in 口会被写成"本节点发的"、out 口 Rx 空 (老倪 2026-10-17 问的就是 out1 看不见/归属不对)。
    """
    t = str(topic or "")
    if t.startswith("ss.node.") and len(t.split(".")) >= 4:
        return ".".join(t.split(".")[:4])
    pref = LIVE_PREFIX.get(t)
    if not pref:
        return None
    return "%s.%s" % (pref, field)

# ─────────────────────────────────────────────────────────────────────────────
# 📚 2026-10-17 老倪: 「数据空间和信号分析这两个独立窗口…只保留 L2 层的 topic, 删除其它层的
#   topic; 信号也只能显示 L2 层的信号 (signal 是 topic 的组成单元); Tx Rx 节点只能是 L2 层节点,
#   其它层都删掉」+「Rx 怎么还有 物理约束呢? 也没有这个节点啊; 前馈直方图是可视化层」。
#
#   ⇒ 这两个窗口的**显示口径**在这里收一次口, 面板不各自写判断:
#     · 行层必须是 L2
#     · Tx 必须是 L2 节点 (没有 L2 归属的行直接不显示, 不是显示 "—")
#     · Rx 只保留 L2 节点, 一个都没有就 "—" (meta/可视化层的节点不许出现在 Tx/Rx)
#   注意: 这只是"这两个窗口"的显示过滤, 工程库/画布本身一行没删。
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def l2_names():
    """{L2 节点显示名} —— 由工程库 + naming 生成。"""
    return {nm for nm, lay in _name_layer().items() if lay == "L2"}


def names_l2(txt):
    """把 "A / B / C" 里非 L2 的名字删掉 (其它层都删); 一个不剩 ⇒ "—"。"""
    keep = [p.strip() for p in str(txt or "").split(" / ") if p.strip() in l2_names()]
    return " / ".join(keep) if keep else "—"


def tx_l2(key):
    """L2 窗口的 Tx: 只留 L2 节点。

    规则节点不是 L2 (例如 sstrace.末端_* 的规则指向 Z-MAX 引擎 L4) 但该真值流有 L2 属主
    (自适应状态估计器) 时, 用 L2 属主 —— 这两份数据本来就是喂给 L2 状态估计的。
    """
    tx = str(tx_of(key))
    keep = [p.strip() for p in tx.split(" / ") if p.strip() in l2_names()]
    if keep:
        return " / ".join(keep)
    own = PREFIX_OWNER.get(str(key or "").split(".", 1)[0])
    if own:
        nm = _load_nodes().get(own) or ""
        if nm in l2_names():
            return nm
    return "—"


def layer_l2(key):
    """L2 窗口显示的层: 能显示就是 L2, 否则回落到真实层。"""
    return "L2" if tx_l2(key) != "—" else layer_of(key)


def show_in_l2_link(key):
    """数据空间 Trace: **Tx 和 Rx 都必须是 L2 节点** —— Rx 空的横杠行整条不显示。

    📚 2026-10-17 老倪: 「有个 —— 444 个, 没有分类的横杠, 不属于 L2, 在数据空间中, 全删掉」
    """
    try:
        return tx_l2(key) != "—" and rx_l2(key) != "—"
    except Exception:                                                     # noqa: BLE001
        return False


def topic_in_l2(prefix):
    """话题级: 这个数据源话题在这两个窗口里要不要显示 (只看 L2)。"""
    pre = str(prefix or "")
    if pre in ("skill", "skillphys"):
        return True            # 技能话题按阶段落到 8 个 L2 阶段节点 (行级再逐条判)
    own = PREFIX_OWNER.get(pre, "__none__")
    if own is None:
        return False
    if not own:
        return False
    nm = _load_nodes().get(own) or ""
    return nm in l2_names()


def rx_l2(key):
    """Rx 只留 L2 节点; 没有就 "—" (非 L2 的连线对象不显示)。"""
    rx = str(rx_of(key))
    keep = [p.strip() for p in rx.split(" / ") if p.strip() in l2_names()]
    return " / ".join(keep) if keep else "—"


def show_in_l2(key):
    """信号分析窗口: Tx 落到 L2 节点就显示 (Rx 允许 "—", 表示这条信号在画布上没有 L2 连线)。"""
    try:
        return tx_l2(key) != "—"
    except Exception:                                                     # noqa: BLE001
        return False

# ───────────────────────── 话题语义类型 (2026-10-18) ─────────────────────────
# 老倪: 「out1 in1 根本看不出来是什么意思。全局搜索，signal 要能表达出这个信号的基本含义」
# 端口名是画布机械名 (out1/in1)，人要的是"这条线运的是什么东西" ⇒ 类型是真源 (mw_topic.type)。
_TYPE_BY_TOPIC = None


def type_of_topic(topic):
    """话题全名 → 语义类型 (如 zmax::MotionPlan)。查不到返回 ''。"""
    global _TYPE_BY_TOPIC
    if _TYPE_BY_TOPIC is None:
        m = {}
        try:
            from lerobot.middleware import db as _db      # 本模块只在函数里导入 db (无模块级 db)
            for r in _db.topics():
                tp = str(r.get("topic") or "")
                if tp:
                    m[tp] = str(r.get("type") or "")
        except Exception:                                                # noqa: BLE001
            m = {}
        _TYPE_BY_TOPIC = m
    return _TYPE_BY_TOPIC.get(str(topic), "")
