#!/usr/bin/env python3
"""run_engine_debug.py — **全流程调试入口**: 真跑状态空间闭环 (8 段全走), 断点落在每个技能自己身上

老倪 2026-11-01: 「全流程 debug, 选哪个配置?」
  · 看**闭环九个技能**怎么过通道 ⇒ 用本入口 (VSCode 配置「🔵 通道 · 引擎全流程」)
  · 看**整个 GUI/画布/播放**那条链 ⇒ 用配置「🧪 断点 · 整个 GUI」

本入口 = `lerobot.engine.runtime.quick_run()` (真引擎: metaworld 物理 + 八阶段状态机 + L2 收口),
不是画画。九个技能每段都会调 `clamp()` → `corridor_dbg()` → `corridor_finish()`, 断点就停在
`src/lerobot/policies/left_right/state_space/skills/atomic_skills.py` 对应技能那一行。

用法
  ./gui-venv311/bin/python tools/run_engine_debug.py                     # 1 集 seed 101 (默认)
  ./gui-venv311/bin/python tools/run_engine_debug.py --seed 100 --episodes 1
  ZMAX_CORRIDOR_BREAK=下降 ./gui-venv311/bin/python tools/run_engine_debug.py   # 只停「下降」
  ZMAX_SKILL_GATE=1 ./gui-venv311/bin/python tools/run_engine_debug.py  # 技能输出真替换动作

VSCode: 选「🔵 通道 · 引擎全流程 (闭环 9 技能逐个停)」→ F5; 停在第一个技能后 F5 继续 = 下一个技能。
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description="状态空间闭环全流程调试 (九个技能真跑)")
    ap.add_argument("--seed", type=int, default=101)
    ap.add_argument("--episodes", type=int, default=1)
    ap.add_argument("--vision", action="store_true", help="开 R1 视觉感知 (每 25 步一次 YOLO, 慢)")
    ap.add_argument("--vision-every", type=int, default=25)
    ap.add_argument("--gate", default=None, help="ZMAX_SKILL_GATE (1=技能输出真替换动作)")
    ap.add_argument("--corridor", default=None, help="ZMAX_CORRIDOR (0=关通道, 对照用)")
    a = ap.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.join(root, "src") not in sys.path:
        sys.path.insert(0, os.path.join(root, "src"))
    if a.gate is not None:
        os.environ["ZMAX_SKILL_GATE"] = str(a.gate)
    if a.corridor is not None:
        os.environ["ZMAX_CORRIDOR"] = str(a.corridor)

    from lerobot.engine.runtime import quick_run  # noqa: PLC0415

    print("🔎 全流程调试: seed=%d · %d 集 · 视觉=%s · ZMAX_CORRIDOR=%s · ZMAX_SKILL_GATE=%s"
          % (a.seed, a.episodes, "开" if a.vision else "关",
             os.environ.get("ZMAX_CORRIDOR", "1"), os.environ.get("ZMAX_SKILL_GATE", "0")), flush=True)
    print("   断点: atomic_skills.py 各技能 clamp 收口 (corridor_dbg) —— 每技能本进程停一次;"
          " ZMAX_CORRIDOR_BREAK=SK03/下降 才每拍都停", flush=True)
    quick_run(n_episodes=a.episodes, seed_base=a.seed, vision=a.vision, vision_every=a.vision_every)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
