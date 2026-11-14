#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_realtime_map.py —— 兼容壳（**已无逻辑**）

2026-11-14 老倪: 「所有训练代码，无论是实时建图还是离线建图，代码逻辑都在建图融合节点，
                550A 550B 550C 都要有相同的代码。」

这个文件原来自带一套"攒帧→建数据集→训练→发布"的实现，与节点包里的 realtime_map.py 是
**两份逻辑**（改一处漏一处，现场表现为"节点说在训、实际没训"）。现在统一收口到：
    <repo>/src/lerobot/policies/left_right/state_space/map_fusion.py
本文件只负责找到那份模块并把 argv 交给它的 daemon_main()，systemd 仍可照旧 ExecStart 这里。
"""
from __future__ import annotations

import os
import sys

CAND = [os.environ.get("MAP_FUSION_SRC", ""),
        "/home/intel/zmax_550c/src/lerobot/policies/left_right/state_space",
        os.path.expanduser("~/zmax_550c/src/lerobot/policies/left_right/state_space"),
        os.path.expanduser("~/zmax/src/lerobot/policies/left_right/state_space")]
for c in CAND:
    if c and os.path.isdir(c) and os.path.isfile(os.path.join(c, "map_fusion.py")):
        sys.path.insert(0, c)
        break
else:
    print("❌ 找不到 map_fusion.py（用 MAP_FUSION_SRC 指定 state_space 目录）", file=sys.stderr)
    sys.exit(2)

import map_fusion                                                          # noqa: E402

if __name__ == "__main__":
    sys.exit(map_fusion.daemon_main())
