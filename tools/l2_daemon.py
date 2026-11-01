#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/l2_daemon.py — 薄启动壳 (真实现已迁进主工程)

2026-11-01 老倪「l2_daemon 不能脱离状态空间工程」:
  真实现 → src/lerobot/engineering/exec/daemon.py (随工程走, 迁移 550C 不用记 tools/ 清单)
  本文件只保留一个入口壳, 让 systemd unit / 现场习惯命令 (`python tools/l2_daemon.py`) 照旧能用。

不要在本文件里写逻辑: 写在这里 = 又脱离工程了。
"""
import os
import runpy
import sys

_TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       os.pardir, "src", "lerobot", "engineering", "exec", "daemon.py")
_TARGET = os.path.abspath(_TARGET)

if __name__ == "__main__":
    if not os.path.isfile(_TARGET):
        sys.exit("!! 找不到真实现: %s" % _TARGET)
    sys.argv[0] = _TARGET
    runpy.run_path(_TARGET, run_name="__main__")
