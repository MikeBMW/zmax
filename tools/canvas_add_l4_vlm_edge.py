#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画布接线: VLM 通用视觉编码器 → 流形引擎 (L4 潜空间的输入边) —— 老倪 2026-10-14

「VLM 通用视觉编码器是输入，流形引擎根据黎曼度规加约束，INTACT 负责意图解码」

做的事: 在画布 sources/canvas/state_space_obs.json 里加一条边
    n_vlm_llm (👁 视觉语言大模型·场景理解) --out1→ ss_mani_eng (🧮 流形引擎) in1
    标签: 通用视觉编码器 → 流形引擎潜表示输入 (L4)
已有同向边 ⇒ 只更新标签 (幂等)。改前备份, 改后回读校验。
"""
from __future__ import annotations

import json
import shutil
import sys
import time

ROOT = "/home/ubuntu/zmax"
CANVAS = ROOT + "/data/database/zmax/sources/canvas/state_space_obs.json"
F, T = "n_vlm_llm", "ss_mani_eng"
LABEL = "通用视觉编码器 → 流形引擎潜表示输入 (L4 潜空间)"


def main() -> int:
    d = json.load(open(CANVAS, encoding="utf-8"))
    links = d["links"]
    bak = "%s.bak_before_l4_edge_%s" % (CANVAS, time.strftime("%Y%m%d_%H%M%S"))
    same = [l for l in links if l.get("f") == F and l.get("t") == T]
    if same:
        old = same[0].get("label")
        same[0]["label"] = LABEL
        same[0]["f_port"] = same[0].get("f_port") or "out1"
        same[0]["t_port"] = same[0].get("t_port") or "in1"
        print("已存在同向边 %s ⇒ 只改标签: %r → %r" % (same[0].get("id"), old, LABEL))
    else:
        nid = "lk_l4_vlm"
        while any(l.get("id") == nid for l in links):
            nid += "x"
        links.append({"id": nid, "f": F, "t": T, "f_port": "out1", "t_port": "in1", "label": LABEL})
        print("新增边: %s  %s --out1→ in1--> %s  (%s)" % (nid, F, T, LABEL))
    shutil.copy2(CANVAS, bak)
    with open(CANVAS, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    chk = json.load(open(CANVAS, encoding="utf-8"))          # 回读校验
    hit = [l for l in chk["links"] if l.get("f") == F and l.get("t") == T]
    print("回读校验: 边数 %d → %d · 命中 %d 条 · 标签=%r" % (
        len(links), len(chk["links"]), len(hit), hit[0]["label"] if hit else None))
    print("备份: %s" % bak)
    return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(main())
