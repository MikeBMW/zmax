# -*- coding: utf-8 -*-
"""realtime_map.py —— 兼容壳（**已无逻辑**）

2026-11-14 老倪: 「所有训练代码…代码逻辑都在建图融合节点，550A 550B 550C 都要有相同的代码。」

原来这个文件里有一套"确保守护活着/读状态/写日志"的实现，和 tools/gs_realtime_map.py 里那套
"攒帧→建数据集→训练→发布"是**两份逻辑**（一份在节点包里、一份在 tools 里），改一处漏一处。
现在全部收口到同目录的 `map_fusion.py`：本文件只做转发，保留旧名字给历史 import 用。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import map_fusion as _mf                                                    # noqa: E402

status = _mf.status
healthy = _mf.healthy
ensure = _mf.ensure
line = _mf.line
tick = _mf.tick
daemon_main = _mf.daemon_main
offline = _mf.offline


def main() -> int:
    return _mf.main()


if __name__ == "__main__":
    sys.exit(main())
