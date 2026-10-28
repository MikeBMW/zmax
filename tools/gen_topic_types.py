# -*- coding: utf-8 -*-
"""生成 topic 语义类型注册表 → config/platform/dds_topic_types.json

背景 (老倪 2026-10-17 原话):
    「topic 的 type 太随意…一个 topic 是有明确的数据意义的, 至少有一个主要的发送 Tx 节点,
      例如 前馈加速器 你的 topic 类型是 SSNodePort, 这根本看不出有什么含义;
      将 topic 的类型重新命名, 要与主要的发送节点关联上, 能看出主要的数据意义;
      有的节点只是复用, 你要根据状态空间工程全局检查所有 topic」

口径:
    1) 类型名由 **主要发送节点 (primary Tx)** 决定, 名字用节点语义的英文, 不用端口序号糊弄。
    2) 一个节点有多个出口时: out1 → Stem, out2 → Stem2 (若节点声明了 PORT_LABELS 语义, 用语义词)。
    3) 入端口不自己造类型: 取它唯一上游的类型; 多个上游 (fan-in) → Stem+In, 并记下生产者清单。
    4) DDS 线上信封仍是 zmax::SSNodePort (JSON 载荷); 这里的 type 是**数据语义类型**, 不是 IDL 结构名。

跑法: ./gui-venv311/bin/python tools/gen_topic_types.py          # 写 JSON
      ./gui-venv311/bin/python tools/gen_topic_types.py --check  # 只校验, 不改盘
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "platform" / "dds_topic_types.json"

# 节点 → (语义英文词干, 中文名, 出口语义覆盖)
#   说明: 词干要能一眼看出"这条数据是什么", 所以按节点的**功能**取名, 不按节点 id。
NODES = {
    "n_board_frame":   ("BoardFrame",        "板坐标系定位",        {}),
    "n_calib_mani":    ("CalibDiag",         "标定诊断测量",        {}),
    "n_dsvl":          ("SceneUnderstanding", "DeepSeek 场景理解",  {}),
    "n_eng_mem":       ("EngineeringMemory", "工程记忆",            {}),
    "n_hil":           ("HumanInLoop",       "HIL 人机在环",        {}),
    "n_intent_bundle": ("IntentBundle",      "意图丛",              {}),
    "n_intent_direct": ("MetaTaskPrediction", "元任务预测",         {}),
    "n_l2_muscle":     ("MuscleSkillBank",   "肌肉记忆技能库",      {}),
    "n_mem_links":     ("MemoryLinks",       "跨层连接",            {}),
    # 📚 2026-10-18 老倪: 「将 moveit 节点更改为 plan 节点」—— out1 现在是**段表** (PlanSegments)
    "n_moveit":        ("PlanSegments",     "运动规划 (plan)",     {}),
    # 📚 2026-10-18 老倪: 「l2_daemon 也要做一个节点，我要看到」—— 执行器出口: 命令/结果
    "n_exec":          ("Exec",             "动作执行器 (l2_daemon)", {"out1": "ActuationCommand", "out2": "ExecResult"}),
    "n_realscene":     ("RealSceneOverlay",  "真实场景叠加",        {}),
    "n_skill_dict":    ("SkillDictionary",   "技能词典",            {}),
    "n_vlm_llm":       ("VlmSceneText",      "视觉语言场景理解",    {}),
    "n_web_agent":     ("WebAgentBridge",    "Web 智能体桥",        {}),
    "ss2d3d":          ("Pose3D",            "2D→3D 解算",          {}),
    # 🌍 2026-10-25: SE(3) 几何阻抗 / H=K+U 力场仲裁节点 (已在画布与 library.py 注册, 表里漏了 ⇒ 生成器直接报缺节点)
    "ss_grav_h":       ("GravityImpedance",  "万有引力 SE(3) 阻抗",  {}),
    "ss3d_view":       ("View3D",            "3D 视图",             {}),
    "ss_l5":           ("L5AutoLabel",       "L5 自动标注训练",     {}),
    "ss_lora_l3":      ("L3LoraAdapter",     "L3 LoRA 微调",        {}),
    "ss_lora_l4":      ("L4LoraAdapter",     "L4 LoRA 微调",        {}),
    "ss_mani_eng":     ("ManifoldEngine",    "流形引擎",            {}),
    "ss_mem_field":    ("PotentialField",    "总装势场",            {}),
    "ss_mem_l2":       ("L2MuscleRecall",    "L2 肌肉记忆",         {}),
    "ss_mem_l3":       ("L3SequencePlan",    "L3 长程序列",         {}),
    "ss_mem_l4":       ("L4WorkSafety",      "L4 工作安全",         {}),
    "ss_mem_share":    ("SharedMemoryHub",   "总装记忆中枢",        {}),
    "ss_moe":          ("MoeRouting",        "MOE 门控路由",        {}),
    "ss_seg":          ("OpenVocabSeg",      "开放词汇分割",        {}),
    # 🏭 2026-10-28: UPH 节拍循环器 (数据源层·预存段表驱动 · 不依赖大模型/语言层)
    "ssuph":           ("UphTact",           "UPH 节拍循环",        {"out1": "UphTactSegment"}),
    "ssact":           ("RobotAction",       "机器人执行动作",      {}),
    "ssaoi":           ("OpticalInspection", "光学质量检测",        {}),
    "ssbypv":          ("BypassView",        "旁路可视化",          {}),
    "sscalib":         ("CalibLayer",        "标定层",              {}),
    "sscap":           ("CapabilityLevel",   "能力档位",            {}),
    "ssdata":          ("MetaworldData",     "metaworld 数据",      {}),
    "ssdec":           ("ActionChunk",       "Flow-Matching 动作头", {"out1": "ActionChunkCmd"}),
    "ssest":           ("StateEstimate",     "状态估计",            {}),
    "ssfeat":          ("FeatureCatalog",    "Feature 清单",        {}),
    "ssff":            ("Feedforward",       "前馈加速器",          {"out1": "FeedforwardProbe", "out2": "FeedforwardAction"}),
    "ssff_hist":       ("FeedforwardHist",   "前馈激活直方图",      {}),
    "ssinnov":         ("StateInnovation",   "状态校正",            {}),
    "ssintact":        ("IntactPolicy",      "INTACT 策略",         {}),
    "ssintact_dec":    ("IntactIntent",      "INTACT 意图解码",     {}),
    "sslat":           ("LatentManifold",    "潜空-流形",           {}),
    "sslimit":         ("SafetyLimit",       "安全执行边界",        {}),
    "ssllm":           ("L3Planner",         "L3 长程序列规划",     {}),
    "ssllm_in":        ("TaskInstruction",   "任务指令",            {}),
    "ssmani_c":        ("ContactManifold",   "接触流形",            {}),
    "ssmani_exp":      ("ManifoldExpert",    "流形专家预测",        {}),
    "ssmani_p":        ("PerformanceManifold", "性能流形",          {}),
    "ssmode":          ("RunMode",           "训练/推理档",         {}),
    "ssobs":           ("UnifiedState",      "SU(2) 统一状态",      {}),
    "ssphys":          ("PhysicsGuard",      "物理约束",            {}),
    "sspred":          ("DynamicsPrediction", "先验动力学预测",     {}),
    "ssreason":        ("AnomalyReasoning",  "异常推理",            {}),
    "sssched":         ("ActionModulator",   "动作调制",            {"out1": "ModulatedAction"}),
    "sssensor":        ("SensorFusion",      "融合定位建图",        {}),
    "sssk1":           ("SkillApproach",     "① 接近",              {}),
    "sssk2":           ("SkillAlign",        "② 对位",              {}),
    "sssk3":           ("SkillDescend",      "③ 下降",              {}),
    "sssk4":           ("SkillGrasp",        "④ 抓取",              {}),
    "sssk5":           ("SkillLift",         "⑤ 抬起",              {}),
    "sssk6":           ("SkillTransfer",     "⑥ 转移",              {}),
    "sssk7":           ("SkillInsert",       "⑦ 插入",              {}),
    "sssk8":           ("SkillDone",         "⑧ 完成",              {}),
    "ssskill":         ("SkillSequence",     "技能序列编排",        {}),
    "sstactile":       ("Tactile",           "触觉感知",            {}),
    "ssvideo":         ("SimWaveform",       "仿真波形",            {}),
    "ssvideo2":        ("OperationVideo",    "操作视频",            {}),
    "ssvlm":           ("VlmEmbedding",      "VLM 视觉编码",        {}),
    "ssworld":         ("PhysicsWorld",      "物理世界",            {}),
    "ssyolo":          ("YoloDetections",    "YOLO 目标检测",       {}),
    "ssz700":          ("RobotSignals",      "Z700 真机信号",       {}),
    "swds":            ("RenderImages",      "渲染图像源",          {}),
    "swintact":        ("PlugPolicy",        "插拔策略",            {}),
    "swvideo":         ("RenderVideo",       "渲染视频",            {}),
    "swworld":         ("EngineEnv",         "Z-MAX 引擎环境",      {}),
}


def type_of(node_id: str, port: str, stem: str, override: dict) -> str:
    """out 端口 → 语义类型名。out1 用 Stem; out2 起用 Stem2/Stem3 (或端口语义覆盖)。"""
    if port in override:
        return "zmax::" + override[port]
    m = re.fullmatch(r"out(\d+)", port)
    if m and int(m.group(1)) == 1:
        return "zmax::" + stem
    if m:
        return "zmax::" + stem + m.group(1)            # out2/out3 → Stem2/Stem3
    return "zmax::" + stem                            # 非 outN 的辅助口 (如 bypass_out) → 仍用节点语义



def _port_cn(nid: str, module: str) -> dict:
    """节点模块里的 PORT_LABELS (中文语义) → {port: 中文}; 没声明就空。"""
    f = ROOT / "src" / "lerobot" / "middleware" / "nodes" / ("%s.py" % (module or ("n_" + nid)))
    if not f.exists():
        f = ROOT / "src" / "lerobot" / "middleware" / "nodes" / ("n_%s.py" % nid)
    try:
        t = f.read_text(encoding="utf-8")
        m = re.search(r"PORT_LABELS\s*=\s*(\{.*?\})\n", t, re.S)
        return ast.literal_eval(m.group(1)) if m else {}
    except Exception:                                                    # noqa: BLE001
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    from lerobot.middleware import db                                   # noqa: PLC0415

    nodes = db.node_rows()
    missing = [n["node_id"] for n in nodes if n["node_id"] not in NODES]
    if missing:
        print("❌ 注册表缺节点: %s" % missing, flush=True)
        return 2

    # ① 出口类型
    types = {}                      # (node, port) -> dict
    by_node = {}
    for n in nodes:
        nid = n["node_id"]
        stem, cn, ov = NODES[nid]
        by_node[nid] = {"stem": stem, "cn": cn, "layer": n.get("layer"), "name": n["name"],
                        "outs": {}, "ins": {}}
        for o in n["outs"]:
            t = type_of(nid, o["port"], stem, ov)
            _cn = (_port_cn(nid, n.get("module")) or {}).get(o["port"]) or ""
            by_node[nid]["outs"][o["port"]] = {"type": t, "topic": o["topic"],
                                               "cn": _cn, "consumers": o["to"]}
            types[(nid, o["port"])] = t

    # ② 入口类型: 按**真实连线**取上游出口类型 (画布连线带 f_port/t_port, 不能只看节点)
    _by_in = {}
    for l in db.links():
        _by_in.setdefault((l["t"], l["t_port"]), []).append((l["f"], l["f_port"]))
    for n in nodes:
        nid = n["node_id"]
        stem, cn, ov = NODES[nid]
        for i in n["ins"]:
            ups = _by_in.get((nid, i["port"])) or []
            up_types = []
            for (u, up_port) in ups:
                t = types.get((u, up_port))
                if t:
                    up_types.append(t)
            uniq = sorted(set(up_types))
            if len(uniq) == 1:
                t, origin = uniq[0], "upstream"          # 唯一上游 ⇒ 直接用它的类型 (同一个数据)
            else:
                t = "zmax::" + stem + "In"               # fan-in / 外部输入 ⇒ 自己的入类型
                origin = "fan-in" if len(uniq) > 1 else "external"
            _icn = (_port_cn(nid, n.get("module")) or {}).get(i["port"]) or ""
            by_node[nid]["ins"][i["port"]] = {
                "type": t, "topic": i["topic"], "cn": _icn, "origin": origin,
                "producers": ["%s.%s" % (u, p2) for (u, p2) in ups]}
            types[(nid, i["port"])] = t

    doc = {
        "_doc": "topic 语义类型注册表 (真源)。type 由主要发送节点决定; DDS 线上信封仍为 zmax::SSNodePort (JSON 载荷)。",
        "_gen": "tools/gen_topic_types.py",
        "_counts": {"nodes": len(nodes),
                    "outs": sum(len(v["outs"]) for v in by_node.values()),
                    "ins": sum(len(v["ins"]) for v in by_node.values())},
        "nodes": by_node,
    }

    text = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if a.check:
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        print(("✅ 注册表与工程一致" if text == old else "❌ 注册表已过期, 需重跑 gen_topic_types.py"))
        return 0 if text == old else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print("✅ 写出 %s · %d 节点 / %d 出口 / %d 入口" % (OUT.relative_to(ROOT), len(nodes),
                                                     doc["_counts"]["outs"], doc["_counts"]["ins"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
