# -*- coding: utf-8 -*-
"""中文短名 (≤5 字) —— Trace 的 Name 列用。

老倪 2026-10-17: 「trace窗口都是 signal, 改成 Name列, 你根据状态空间工程, 给出中文名字,
   不要超过5个字, signal列是信号的对应的英文字符串, 是程序里的真实信号变量」

口径:
  · Name = **中文名** (按状态空间工程的节点/话题语义, ≤5 字), 不是 topic 字符串
  · Signal = 程序里的真实变量名 (DDS 载荷字段名), 原样, 不翻译不改写
  · 同一节点两个出口时, 第二路加数字后缀 ("统一状态2"), 仍 ≤5 字
  · 名字必须唯一到"能看懂是哪一路数据"; 校验见 verify_cn_names.py
"""
from __future__ import annotations

# 画布节点 → 中文短名 (全部 ≤5 字)
NODE_CN = {
    "n_board_frame": "板坐标",
    "n_calib_mani": "标定测量",
    "n_dsvl": "场景理解",
    "n_eng_mem": "工程记忆",
    "n_hil": "人机在环",
    "n_intent_bundle": "意图丛",
    "n_intent_direct": "元任务",
    "n_l2_muscle": "肌肉库",
    "n_mem_links": "跨层连接",
    "n_moveit": "运动规划",
    "n_realscene": "场景叠加",
    "n_skill_dict": "技能词典",
    "n_vlm_llm": "视觉语言",
    "n_web_agent": "Web桥",
    "ss2d3d": "位姿解算",
    "ss3d_view": "3D视图",
    "ss_l5": "自动标注",
    "ss_lora_l3": "L3微调",
    "ss_lora_l4": "L4微调",
    "ss_mani_eng": "流形引擎",
    "ss_mem_field": "势场",
    "ss_mem_l2": "肌肉回放",
    "ss_mem_l3": "序列记忆",
    "ss_mem_l4": "工作安全",
    "ss_mem_share": "记忆中枢",
    "ss_moe": "MOE门控",
    "ss_seg": "开放分割",
    "ssact": "执行器",
    "ssaoi": "光学检测",
    "ssbypv": "旁路视图",
    "sscalib": "标定层",
    "sscap": "能力档位",
    "ssdata": "数据源",
    "ssdec": "动作头",
    "ssest": "状态估计",
    "ssfeat": "特征清单",
    "ssff": "前馈加速",
    "ssff_hist": "前馈直方",
    "ssinnov": "状态校正",
    "ssintact": "L4安全",
    "ssintact_dec": "意图解码",
    "sslat": "潜空流形",
    "sslimit": "安全限幅",
    "ssllm": "序列规划",
    "ssllm_in": "任务指令",
    "ssmani_c": "接触流形",
    "ssmani_exp": "流形专家",
    "ssmani_p": "性能流形",
    "ssmode": "运行档",
    "ssobs": "统一状态",
    "ssphys": "物理约束",
    "sspred": "动力学",
    "ssreason": "异常推理",
    "sssched": "动作调制",
    "sssensor": "融合定位",
    "sssk1": "接近",
    "sssk2": "对位",
    "sssk3": "下降",
    "sssk4": "抓取",
    "sssk5": "抬起",
    "sssk6": "转移",
    "sssk7": "插入",
    "sssk8": "完成",
    "ssskill": "技能序列",
    "sstactile": "触觉",
    "ssvideo": "仿真波形",
    "ssvideo2": "操作视频",
    "ssvlm": "VLM编码",
    "ssworld": "物理世界",
    "ssyolo": "目标检测",
    "ssz700": "真机信号",
    "swds": "渲染图像",
    "swintact": "插拔策略",
    "swvideo": "渲染视频",
    "swworld": "引擎环境",
}

# DDS 注册表里的话题 (zmax/<key>) → 中文短名
TOPIC_CN = {
    "ss_state": "统一状态", "ss_action": "动作指令", "ss_action_chunk": "动作块",
    "ss_calib": "标定值", "ss_infer": "推理状态", "ss_diag": "诊断", "ss_test": "自检",
    "ss_plan": "规划", "ss_energy": "能量", "ss_torque": "扭矩", "ss_engine": "引擎",
    "ss_stage": "阶段", "ss_macro": "总装", "ss_manifold_step": "流形步",
    "ss_meta_task": "元任务", "ss_meta_pred": "元预测", "ss_skill_phys": "技能物理",
    "link_value": "连线值", "heartbeat": "心跳", "hw_state": "硬件状态",
    "train_prog": "训练进度", "deploy_cmd": "部署指令", "ss_canvas_node": "画布节点",
    "ss_nodes": "节点表", "ss_config_names": "配置名", "ss_driving_torque": "驱动扭矩",
}
for _i in range(1, 9):
    TOPIC_CN.setdefault("skill_sk0%d" % _i, "技能0%d" % _i)

_MAX = 5


def cn_of(topic: str, port: str = "") -> str:
    """topic → 中文短名 (≤5 字)。不认识就退回 topic 尾段, 不硬编中文。"""
    t = str(topic or "")
    if t.startswith("ss.node."):
        rest = t[len("ss.node."):]
        nid, _p = (rest.rsplit(".", 1) + [""])[:2] if "." in rest else (rest, "")
        base = NODE_CN.get(nid)
        if base:
            return _fit(base, _p or port)
        return (nid or t)[:_MAX]
    key = t.split("/")[-1].strip()
    if key == "out":
        return "单步输出"
    base = TOPIC_CN.get(key)
    if base:
        return base[:_MAX]
    return (key or t)[:_MAX]


def _fit(base: str, port: str) -> str:
    """多出口 (out2 / out3 …) 加数字后缀, 总长仍 ≤5。"""
    import re
    m = re.fullmatch(r"out(\d+)", str(port or ""))
    if m and int(m.group(1)) > 1:
        return (base[:_MAX - 1] + m.group(1))[:_MAX]
    return base[:_MAX]


# 常见信号字段 → 中文名 (≤5 字); 没收录的走后缀规则, 再退回所属节点的中文名
FIELD_CN = {
    "grasp_prob": "抓取概率", "prob": "概率", "conf": "置信度", "confidence": "置信度",
    "u_ff": "前馈动作", "action": "动作", "action6": "关节动作", "chunk": "动作块",
    "state": "状态向量", "state_2": "状态2", "qpos": "关节位姿", "qvel": "关节速度",
    "tcp_x": "末端X", "tcp_y": "末端Y", "tcp_z": "末端Z",
    "tcp_x_mm": "末端X", "tcp_y_mm": "末端Y", "tcp_z_mm": "末端Z",
    "tcp_pose": "末端位姿", "plane_z": "平面Z", "residual": "残差",
    "loss": "损失", "gain": "增益", "gain_obs_pct": "观测增益", "gain_act_pct": "动作增益",
    "step": "步数", "total": "总步数", "pct": "进度", "progress": "进度",
    "uptime_s": "运行时长", "age_s": "数据龄", "latency_ms": "时延",
    "temp_c": "温度", "power_w": "功率", "util_pct": "利用率", "mem_used_mb": "已用内存",
    "disk_free_gb": "剩余磁盘", "cpu_util_pct": "CPU占用",
    "torque": "扭矩", "force": "力", "mass": "质量", "inertia": "惯量",
    "energy": "能量", "phi": "势场值", "intent": "意图", "skill": "技能",
    "stage": "阶段", "phase": "相位", "mode": "模式", "ok": "成功标志",
}

_SUFFIX_CN = [
    ("_prob", "概率"), ("_conf", "置信度"), ("_deg", "角度"), ("_mm", "位置"),
    ("_nm", "扭矩"), ("_pct", "百分比"), ("_ms", "耗时"), ("_hz", "频率"),
    ("_kg", "质量"), ("_gain", "增益"), ("_loss", "损失"), ("_err", "误差"),
    ("_s", "时长"), ("_x", "X"), ("_y", "Y"), ("_z", "Z"),
]


def cn_of_signal(field: str, topic: str = "") -> str:
    """信号字段 → 中文名 (≤5 字): 精确表 > 后缀规则 > 所属节点中文名。"""
    f = str(field or "").strip()
    key = f.lower()
    if key in FIELD_CN:
        return FIELD_CN[key][:_MAX]
    for suf, cn in _SUFFIX_CN:
        if key.endswith(suf):
            base = cn_of(topic)
            # 只允许"节点名 + 量纲"在 5 字内; 装不下就只留量纲 (节点在 Tx 列, 不丢信息)
            return base + cn if len(base) + len(cn) <= _MAX else cn
    return cn_of(topic)


def cn_of_node(node_id: str, fallback: str = "") -> str:
    return NODE_CN.get(str(node_id), (fallback or str(node_id))[:_MAX])


def audit() -> list:
    """返回不合规项 (超长/重复), 供 verify_cn_names.py 用。"""
    bad = []
    for k, v in list(NODE_CN.items()) + list(TOPIC_CN.items()):
        if len(v) > _MAX:
            bad.append("%s → %s (%d 字)" % (k, v, len(v)))
    from collections import Counter
    dup = [k for k, n in Counter(NODE_CN.values()).items() if n > 1]
    if dup:
        bad.append("节点中文名重复: %s" % dup)
    return bad
