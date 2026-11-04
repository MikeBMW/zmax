# -*- coding: utf-8 -*-
"""内容 6 — 每个功能的方框图（55 个节点，数据源 reports/r5_nodes_full.json）"""
import json

NODES = json.load(open("/home/ubuntu/zmax/reports/r5_nodes_full.json", encoding="utf-8"))
LAYER_CN = {"基础层": "基础层 L2", "决策层": "决策层 L3", "认知层": "认知层 L4", "任务层": "任务层 L5"}

CONTENT = [
    {"k": "section", "num": 0.55, "t": "每个功能的方框图（55 个节点）",
     "desc": "一个功能一页：左边是上游给它的输入、右边是它交给下游的输出，中间是这个功能本体；条数与连线来自状态空间画布的接口定义。",
     "items": ["基础层 30 页：物理世界 → 执行器 → 收口 → 规划/动力学 → SK01-SK08 → 限幅/调制/阻抗 → 估计链 → 流形/记忆 → 感知",
               "决策层 5 页：Flow-Matching 动作头、VLM 编码、LoRA、长序规划、L3 编排",
               "认知层 11 页：流形引擎、INTACT 解码/LoRA、JEPA、接触/性能流形、标定、势场",
               "任务层 9 页：场景理解（VLM/DeepSeek）、MES、HIL、异常推理、自动标注"]},
]


import re as _re
_EMOJI = _re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u2190-\u21FF]+")


def _clean(x: str) -> str:
    return _EMOJI.sub("", (x or "").replace("…", "")).strip()


for _n in NODES:
    _tag = f"0.55 方框图 · {_n['layer']}"
    CONTENT.append({
        "k": "nodeblock",
        "ch": _tag,
        "t": f"{LAYER_CN.get(_n['layer'], _n['layer'])} · {_n['i']}/{_n['total']} 位 · {_clean(_n['name'])[:18]}",
        "name": _clean(_n["name"])[:26],
        "desc": _clean(_n["desc"])[:120],
        "ins": [{"peer": _clean(e["peer"]), "sig": _clean(e["sig"])} for e in _n["ins"]],
        "outs": [{"peer": _clean(e["peer"]), "sig": _clean(e["sig"])} for e in _n["outs"]],
        "tick": _clean(_n["tick"]),
        "code": _clean(_n["code"]),
    })
