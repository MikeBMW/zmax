# -*- coding: utf-8 -*-
"""🎛 信号准入与命名策略 —— **唯一一处**决定"哪些信号上屏、叫什么名"。

📚 2026-10-18 老倪:
   「trace 信号太乱、太多废话，精简；每个节点不允许超过 10 个；总 L2 信号不超过 100 个；
     不允许出现 signal 名字模糊不清、表达混乱、直写几个字母、随机分配字母等乱象。整改所有 signal 的命名。」

规则 (硬约束, 由 tools/verify_signal_policy.py 判):
  ① 每个节点 ≤ 10 条 (MAX_PER_NODE)
  ② L2 总信号 ≤ 100 条 (MAX_TOTAL)
  ③ 名字必须表达功能: <量>_<单位> 或明确名词; 禁止 n / v / a / u / o_hat / band_h 这类看不出含义的短名
  ④ 没进本表白名单的信号一律不上屏 (宁缺勿滥; 要看原始字段去文件)

命名约定:
  · 位置/尺寸 mm · 速度 mm/s (mms) · 角度 deg · 力 N · 加速度 mm/s² (mms2) · 比例无后缀
  · 一个信号只表达一个物理量, 不用序号/阶段前缀 (节点名已说明是哪一步)
"""
from __future__ import annotations

MAX_PER_NODE = 10
MAX_TOTAL = 100

# ── 8 个原子技能节点 (接近/对位/下降/抓取/抬起/转移/插入/完成) ───────────────────
# 原始名形如 SK01.approach.v / SK03.descend.F_max ⇒ 按后缀收敛成 5 条功能量
SK_NODES = {"接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"}
# 实际字段名形如 "SK03 下降 · v 速度 mm/s" / "SK03 下降 · err 削出偏差 mm/s"
# ⇒ 用**含义片段**匹配 (不能再按最后一段字母, 那样 a/angle/b/c 会混成一条)
SK_PATTERNS = (
    ("· v 速度", "speed_mms"),                 # 段速度
    ("· s 段行程", "travel_mm"),                # 段行程
    ("· err 削出偏差", "track_err_mms"),        # 跟踪误差
    ("· F_max 力上限", "force_limit_n"),        # 力上限
    ("· a_max 加速度上限", "accel_limit_mms2"), # 加速度上限
)

# ── 其余节点的白名单: 节点显示名 → {原始信号名(或后缀): 功能名} ──────────────────
NODE_ALLOW = {
    "运动规划": {
        "target_x_mm": "target_x_mm", "target_y_mm": "target_y_mm", "target_z_mm": "target_z_mm",
        "target_rx_deg": "target_rx_deg", "target_ry_deg": "target_ry_deg", "target_rz_deg": "target_rz_deg",
        "travel_mm": "travel_mm", "speed_gain": "speed_gain",
    },
    "动作执行器": {
        "exec_phase": "exec_phase",          # 1受理 3下发中 4到位 5完成 9被拦
        "stage_now": "stage_now",            # 当前第几段
        "stage_total": "stage_total",        # 共几段
        "arrive_error_mm": "arrive_error_mm",  # 到位残差
        # 真机实时位姿 (tcp_out/latest.json · 50Hz 真值): 6 个自由度, 全单位化成 mm/deg
        "x": ("pose_x_mm", 1000.0), "y": ("pose_y_mm", 1000.0), "z": ("pose_z_mm", 1000.0),
        "rx": ("pose_rx_deg", 57.29577951308232), "ry": ("pose_ry_deg", 57.29577951308232),
        "rz": ("pose_rz_deg", 57.29577951308232),
    },
    "前馈加速器": {"u_ff": "feedforward_cmd",
                # 🛡 2026-10-18: 前馈/调制/限幅三段本来就是 L2 的主链路, 之前只有 u_ff 一条上屏,
                #   导致 数据空间 里 前馈加速器/动作调制器/安全执行边界 三个 Tx 都看不到实测量。
                "前馈速度_mms": "ff_speed_mms", "前馈速度_x_mms": "ff_vx_mms",
                "前馈速度_y_mms": "ff_vy_mms", "前馈速度_z_mms": "ff_vz_mms"},
    "动作调制器": {"动作调制_mms": "modulated_speed_mms", "动作调制_x_mms": "modulated_vx_mms",
                "动作调制_y_mms": "modulated_vy_mms", "动作调制_z_mms": "modulated_vz_mms",
                "动作调制_夹爪": "gripper_cmd", "阶段限速_mms": "stage_speed_cap_mms"},
    "安全执行边界": {"安全边界_mms": "limited_speed_mms", "安全边界_x_mms": "limited_vx_mms",
                "安全边界_y_mms": "limited_vy_mms", "安全边界_z_mms": "limited_vz_mms"},
    "光学质量检测": {"aoi": "quality_score"},
    "状态校正器": {"state_innovation": "state_innovation_mm"},
    "2D-3D 解算": {"pose3d": "pose3d_valid"},
    "技能词典": {"skill_dict": "skill_count"},
    "肌肉记忆技能库": {"muscle_bank": "muscle_skill_count"},
    "触觉感知": {"tactile": "tactile_force_n"},
    "物理世界": {"physics_world": "physics_world_state"},
}

# 明确不上屏的节点 (不是没数据, 是它们的量属于数学/审计层, 不进 L2 动作 Trace)
BLOCKED_NODES = {
    "SU(2) 统一状态空间", "元数据MOE门控路由", "开放词汇分割", "总装机记忆",
    "自适应状态估计器", "机器人执行器", "融合定位建图", "板坐标系定位", "能力档位",
}


def _suffix(raw: str) -> str:
    """取最后一个点后的字段名 (SK01.approach.v → v)。"""
    return str(raw or "").rsplit(".", 1)[-1]


def decide(tx: str, raw: str):
    """(节点显示名, 原始信号名) → 上屏用的功能名; None = 不上屏。"""
    tx = str(tx or "").strip()
    raw = str(raw or "").strip()
    if not raw or tx in BLOCKED_NODES:
        return None
    if tx in SK_NODES:
        for _pat, _nm in SK_PATTERNS:
            if _pat in raw:
                return _nm
        return None
    table = NODE_ALLOW.get(tx)
    if not table:
        return None
    if raw in table:
        return table[raw]
    return table.get(_suffix(raw))


def decide_topic(topic: str, raw: str):
    """给「信号分析」树用: 由话题+字段名推节点, 再按同一张表判。"""
    try:
        from lerobot.middleware import attribution as _a
        key = "%s.%s" % (str(topic or "").replace("zmax/", ""), raw)
        _d = decide(_a.tx_of(key), raw)
        return _d[0] if isinstance(_d, tuple) else _d
    except Exception:                                                        # noqa: BLE001
        return None


def filter_rows(rows):
    """Trace 行过滤 + 改名 (保持顺序); 同时执行 ≤10/节点、≤100 总数。"""
    out, per_node = [], {}
    seen = set()
    for x in rows:
        tx = str(x.get("tx") or "")
        clean = decide(tx, x.get("raw") or x.get("signal") or "")
        if not clean:
            continue
        _k = 1.0
        if isinstance(clean, tuple):
            clean, _k = clean
        if per_node.get(tx, 0) >= MAX_PER_NODE:
            continue
        k = (tx, clean)
        if k in seen:                       # 同一节点同一功能量只留一行 (重复端口/多话题)
            continue
        if len(out) >= MAX_TOTAL:
            break
        seen.add(k)
        per_node[tx] = per_node.get(tx, 0) + 1
        y = dict(x)
        y["name"] = clean
        y["signal"] = clean
        y["cn"] = clean
        if _k != 1.0:                        # 单位换算 (m→mm / rad→deg): 显示值同步改, 不装原数
            try:
                _v = float(x.get("vraw"))
                y["vraw"] = _v * _k
                y["value"] = ("%.1f" % (_v * _k)) if _k > 100 else ("%.2f" % (_v * _k))
                y["unit"] = "mm" if _k > 100 else "deg"
            except Exception:                                                # noqa: BLE001
                pass
        y["why"] = "信号来源: %s (原始字段 %s)" % (x.get("why") or "", x.get("raw") or "")
        out.append(y)
    return out
