# -*- coding: utf-8 -*-
"""逐层**真调用计数** —— 模型引擎窗口「推理中 / 空闲」的真源 (2026-10-14 老倪问诊 L2/L3 显空闲)。

为什么要有这个文件:
  老倪: 「我现在正运行L5功能，为什么模型引擎 L2 L3 显示空闲？」
  查下来 L3 那一格的 inferring 原来**不是 L3 自己的推理计数**, 而是:
    `models_manifest.json` 里 L3 在役条目的 probe = json_age(`dataspace/live.json#topics.ss_action.age_s`)
    —— 即"状态空间引擎动作节拍"的**代理信号** (manifest 自己也注明了是代理, 系统里没有 L3 独立计数)。
  而这个代理的真源当时连字段都没有 (`ss_action` 只有 topic/type/qos/hz, count=0) ⇒ 取不到 ⇒ 恒判"空闲"。
  结果: **跑不跑都显示空闲**, 用户无法从这一格看出"L3 到底有没有被调用"。

本文件的语义 (唯一口径):
  · `count`  = 该层画布节点被**真执行**的累计次数 (runtime.execute_node_logic 在调真函数前 touch 一次)
  · `last_ts`= 最近一次真调用的时刻 (unix 秒)
  · 判"推理中" = 该层在**窗口内计数是否增长** (status_hub 的 json_counter), 与"模型是否加载"无关
  · 演示播放 (demo=True, 不重跑真函数) **不计**, 因为它没真调模型
  ⇒ "空闲" 的正确读法 = 最近窗口内**没有任何属于该层的节点被真跑**, 不是"模型坏了/没加载"。

写入是 best-effort: 任何异常都吞掉 (绝不能让状态统计把节点执行带崩)。
"""
from __future__ import annotations

import json
import os
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PATH = os.environ.get("ZMAX_LAYER_CALLS") or os.path.join(ROOT, "zmax_data/ss_live/layer_calls.json")
LAYERS = ("L2", "L3", "L4", "L5")

_KEY2LAYER = None


def _fallback_layer(key: str) -> str:
    """by_level 里查不到时的兜底 (只按**节点 id** 判, 不猜语义)。"""
    k = str(key or "")
    if k.startswith(("ssmani", "ssintact", "ss_lora_l4", "ss_moe")) or "l4" in k:
        return "L4"
    if k.startswith(("sssched", "ssplan", "ssdit", "ss_head")) or "l3" in k:
        return "L3"
    if k.startswith(("ssyolo", "sam3", "ssaoi", "sssmall")) or "l2" in k:
        return "L2"
    if k.startswith(("ssdsvl", "ssscene", "l5")) or "l5" in k:
        return "L5"
    return ""


def key2layer() -> dict:
    """节点 key → 层 (真源 = nodes/by_level.py 的档位归属表)。"""
    global _KEY2LAYER
    if _KEY2LAYER is None:
        m: dict = {}
        try:
            from .nodes import by_level                              # noqa: PLC0415
            for lv, rows in (by_level.LEVELS_INDEX or {}).items():
                for r in rows:
                    if len(r) > 2 and r[2]:
                        m[str(r[2])] = str(lv)
        except Exception:                                            # noqa: BLE001
            m = {}
        _KEY2LAYER = m
    return _KEY2LAYER


def layer_of(key: str) -> str:
    return key2layer().get(str(key)) or _fallback_layer(key)


def read() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:                                                # noqa: BLE001
        return {}


def touch(key: str, node_name: str = "", layer: str = "") -> str:
    """记录一次**真**节点调用。返回归属层 (空 = 判不出)。besteffort, 不抛异常。"""
    try:
        ly = layer or layer_of(key)
        if not ly:
            return ""
        d = read() or {}
        row = d.get(ly) if isinstance(d.get(ly), dict) else {}
        rec = {"count": int(row.get("count") or 0) + 1, "last_ts": round(time.time(), 3),
               "last_key": str(key), "last_node": str(node_name or "")[:80]}
        d[ly] = rec
        d["_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        d["_source"] = "runtime.execute_node_logic → layer_calls.touch (真调用计数)"
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(PATH), prefix=".layer_calls")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, PATH)
        return ly
    except Exception:                                                # noqa: BLE001
        return ""


def summary() -> str:
    d = read()
    parts = []
    for ly in LAYERS:
        r = d.get(ly) or {}
        age = (time.time() - float(r.get("last_ts") or 0)) if r.get("last_ts") else None
        parts.append("%s=%s%s" % (ly, r.get("count", 0), ("(%.0fs前)" % age) if age is not None else "(无调用)"))
    return " · ".join(parts)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="逐层真调用计数 (模型引擎 推理中/空闲 真源)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--touch", metavar="NODE_KEY", help="手工记一次 (自检用)")
    a = ap.parse_args()
    if a.touch:
        print("归属层:", touch(a.touch) or "(判不出)")
    print(json.dumps(read(), ensure_ascii=False, indent=1) if a.json else summary())
