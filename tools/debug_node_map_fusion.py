#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""debug_node_map_fusion.py —— 只跑「📡 融合定位建图」节点的**建图入口**，给 VSCode 断点用。

为什么单独一个 runner:
  - 断点要停在节点入口，但整台机的常驻画布循环(ss_canvas_loop)一跑就是 10Hz 全节点，
    调试时既慢又会被别的节点噪声干扰；
  - 这里只 import 节点函数、造一个最小 ctx（log 打到终端），调一次 node_ss_s1，
    ⇒ 断点必命中、变量就是真实节点拿到的那一份。

用法（VSCode: 选配置「🧪 断点 · 融合定位建图节点入口」再 F5）:
  ZMAX_DEBUG_MAPFUSION=1 python tools/debug_node_map_fusion.py
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.path.join(REPO, "src")
for p in (SRC, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)


def log(msg: str) -> None:
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def main() -> int:
    from lerobot.engineering.nodes import library as nodes          # noqa: WPS433

    fn = getattr(nodes, "node_ss_s1", None)
    if fn is None:
        log("❌ library.py 里没有 node_ss_s1（融合定位建图节点）")
        return 2
    ctx = {"name": "融合定位建图", "log": log, "images": {}}
    log("进入 node_ss_s1(ctx) · 门控 ZMAX_DEBUG_MAPFUSION=%s"
        % os.environ.get("ZMAX_DEBUG_MAPFUSION", "0"))
    out = fn(ctx)
    log("节点返回: %r" % (out,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
