#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 engineering/nodes/robot_actuator_impl.py 的 run() 改成转发到 middleware 那份(位姿口径)。

为什么: 两处同名实现并存 ⇒ 迟早漂移(一处出位姿、一处还出速度)。正文只留一份。
"""
import io
import os

P = "/home/ubuntu/zmax/src/lerobot/engineering/nodes/robot_actuator_impl.py"

src = io.open(P, encoding="utf-8").read()
if "def _run_legacy(ctx):" not in src:
    assert "def run(ctx):" in src, "找不到 run(ctx)"
    src = src.replace("def run(ctx):", "def _run_legacy(ctx):", 1)

DELEGATE = '''

def run(ctx):
    """统一出口: 正文在 lerobot.middleware.nodes.impl.robot_actuator_impl(位姿口径 action)。

    2026-11-14 老倪「return action 改成真正的位姿」—— 执行器返回
    pose / joints_deg / grip_* / src, 不再返回 4 维速度; 两份实现并存必然漂移, 故只留一份。
    转发失败(极端情况)才回落本文件历史实现 _run_legacy。
    """
    try:
        from lerobot.middleware.nodes.impl.robot_actuator_impl import run as _run2
        return _run2(ctx)
    except Exception:                                                      # noqa: BLE001
        return _run_legacy(ctx)
'''

if "def run(ctx):" not in src:
    src = src.rstrip("\n") + "\n" + DELEGATE
io.open(P, "w", encoding="utf-8").write(src)
print("ok: 转发已就位 · 行数 %d" % len(src.splitlines()))
