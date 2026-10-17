# -*- coding: utf-8 -*-
"""节点显示名归一 (Tx/Rx 列只放"这个节点叫什么", 不放层级/徽标/解释)。

老倪 2026-10-17: 「Tx Rx 两列, 显示节点的名字, 你显示的太乱了, 怎么 L5 L4 都冒出来了?
   还有横向箭头; 改清晰, 只要这个节点的名字; 你全局搜索一下, 规范名称」

画布里的节点全名是**给人看的长名**, 带徽标 emoji、层前缀 (L2~L5)、序号 (①..⑧)、
SK 编号、" · " 后的解释、括号注释、甚至 "→ 下游" 说明。放进 20 来列宽的表格里就是灾难。

口径 (只做显示, 不改画布真源):
    ① 去掉 emoji / 变体选择符
    ② 去掉开头层前缀: L1~L5 / meta
    ③ 去掉开头圈号 ①..⑳ 与 SK 编号
    ④ 在 "(" / "（" / "→" / "->" 处截断 (后面都是解释或下游说明)
    ⑤ " · " / " + " 只取第一段 (主名); "->" 与 "↔" 归一为 "·"? 不 —— 直接截断
    ⑥ 折叠空白, 去尾部标点

    clean("🧿 DeepSeek-V4-Flash · 场景理解 (L5 大模型主路)")  → "DeepSeek-V4-Flash"
    clean("🧿 L5 · 视觉语言自动标注 → L2/L3/L4 监督 → 自动训练") → "视觉语言自动标注"
    clean("④ 抓取 · SK04")                                      → "抓取"
    clean("🥇 L4 · 工作安全 + 物理世界导航 (记忆: 前额叶)")       → "工作安全"

重复名处理: `unique_map()` 给重名节点补 "(短id)", 保证 Tx/Rx 里的名字能唯一定位到节点。
"""
from __future__ import annotations

import re

_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u20E3]")
_LAYER = re.compile(r"^\s*(?:L[1-5]|meta)\b[\s·:：\-—]*", re.I)
_CIRCLE = re.compile(r"^[\u2460-\u2473\u3251-\u325F]{1,3}\s*[·.:：\-]?\s*")
_SK = re.compile(r"\bSK[\-\s]?\d+\b", re.I)
# 只在"空格 + 括号/箭头"处截断: 保留 SU(2)、2D→3D 这类名字本体, 砍掉 " (L4 主路)" / " → 下游" 说明
_CUT = re.compile(r"\s+[（(]|\s+(?:→|->|=>|⇒)\s+|[（(](?=[^)）]*[)）]\s*$)")
_SEP = re.compile(r"\s*[·•|｜]\s*|\s+\+\s+")
_TAIL = re.compile(r"[\s·•,，;；:：\-—]+$")


def clean(name, fallback: str = "") -> str:
    """节点长名 → 纯名字 (不截字, 只去装饰)。空结果回退 fallback。"""
    t = _EMOJI.sub("", str(name or "")).strip()
    t = _LAYER.sub("", t)                                  # L5 · / L2 前缀
    t = _CIRCLE.sub("", t)                                 # ① / 1. 前缀
    t = _CUT.split(t, 1)[0]                                # 括号/箭头之后全丢掉
    t = _SEP.split(t, 1)[0]                                # 只取主名 (第一段)
    t = _SK.sub("", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = t.replace("→", "-").replace("->", "-").replace("⇒", "-")   # 名字里也不留横箭头 (老倪嫌乱)
    t = _TAIL.sub("", t)
    return t or _EMOJI.sub("", str(name or "")).strip() or fallback


def unique_map(pairs, sep: str = " · ") -> dict:
    """{id: 长名} → {id: 显示名}; 重名的补 "(短id)" 以便 Tx/Rx 能唯一指向。"""
    out, seen = {}, {}
    for nid, full in pairs:
        base = clean(full, fallback=str(nid))
        seen[base] = seen.get(base, 0) + 1
        out[nid] = base
    for nid, full in pairs:
        base = out[nid]
        if seen.get(base, 0) > 1:
            out[nid] = "%s (%s)" % (base, nid)
    return out
