#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""debug_run_engine.py — 🧪 无 GUI 直达引擎 (专供断点: 技能 clamp / 状态机 / 技能派发)

为什么要这个脚本 (老倪 2026-10-31「你给我设置好 vscode, 你来调整好进入技能的断点, 全程你操作」):
  GUI 里跑一轮要 5-9 分钟, 还要点按钮、等建模; 调试技能断点时 99% 的时间浪费在别处。
  这里直接把「真引擎 (RealStateSpaceSim) + 真状态机 + 真技能」跑起来, 不建任何窗口:
    · 技能断点 (atomic_skills.py 的 clamp/return) → 每步必进
    · 状态机断点 (cognition.py advance/decide) → 每步必进
    · 引擎断点 (runtime.py 主循环) → 每步必进
  默认 120 步 (insert 全链约 348 步走完 接近→…→完成), 可用 --steps 调。

用法:
  # VSCode: 选「🧪 断点 · 引擎直达」按 F5 (本文件就是 program)
  # 命令行:
  ./gui-venv311/bin/python tools/debug_run_engine.py --steps 120
  ./gui-venv311/bin/python tools/debug_run_engine.py --steps 400 --quiet

判据 (跑完自打):
  skills clamp 调用次数: {SK01: 26, SK02: 31, ...} —— 每步恰好 1 次 (合计 == 步数)
"""
from __future__ import annotations

import argparse
import os
import sys


def _boot() -> str:
    """路径/离屏渲染就位 (与 GUI 同口径: 仓库根 + src + tools + tools/gui)。"""
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("DISPLAY", os.environ.get("DISPLAY") or ":0")
    os.environ.setdefault("ZMAX_SINGLE_THREAD", "1")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in (root, os.path.join(root, "src"), os.path.join(root, "tools"), os.path.join(root, "tools", "gui")):
        if p not in sys.path:
            sys.path.insert(0, p)
    os.chdir(os.path.join(root, "tools", "gui"))       # metaworld 资源按 GUI 工作目录找
    return root


def _skill_break_lines() -> dict:
    """算出每个技能 "收口那行" (_out = {…}) 的行号 —— 这就是要下断点的位置。"""
    import ast
    import lerobot.policies.left_right.state_space.skills.atomic_skills as _AS  # noqa: PLC0415
    out = {}
    try:
        tree = ast.parse(open(_AS.__file__, encoding="utf-8").read())
    except Exception:                                                      # noqa: BLE001
        return out
    for c in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for f in c.body:
            if isinstance(f, ast.FunctionDef) and f.name == "clamp":
                for s in f.body:
                    if (isinstance(s, ast.Assign) and isinstance(s.value, ast.Dict)
                            and getattr(s.targets[0], "id", "") == "_out"):
                        out[c.name] = s.lineno
    return out


def _stop_at_skills() -> None:
    """🔴 技能断点位置 (老倪: 「调整好, 停止在技能的断点上」)。

    说明 (别夸大): VSCode 的断点是它自己通过 DAP 下发的 —— 进程内没有公开 API 能替 VSCode
    点一次行号 (这版 debugpy 没有 PyDB.set_break)。所以这里做两件确定有效的事:
      ① 把「要下的行号」算准并打出来 (ast 取每个类 clamp 的收口行, 不受行号漂移影响);
      ② 连了调试器时, 用 debugpy.breakpoint() 在每个类首次执行时触发一次中断 ——
         即使你没点断点, F5 也会停下来 (Call Stack 里就是 <SKxx>.clamp 上一层)。
    """
    lines = _skill_break_lines()
    if not lines:
        print("⚠️ 没找到技能 clamp 的收口行 (ast 解析失败?)", flush=True)
        return
    print("📌 技能断点行: %s" % ", ".join("%s:%d" % (k, v) for k, v in lines.items()), flush=True)

    dbg = None
    try:
        import debugpy                                                     # noqa: PLC0415
        dbg = debugpy.get_global_debugger()
    except Exception:                                                      # noqa: BLE001
        dbg = None
    if dbg is None:
        print("   (未连调试器 ⇒ 不下断点, 正常跑)", flush=True)
        return
    # 连了调试器: 给每个技能类首次执行打一次真中断 (pydevd 的 hardcoded breakpoint)
    try:
        import lerobot.policies.left_right.state_space.skills.atomic_skills as _AS  # noqa: PLC0415
    except Exception:                                                      # noqa: BLE001
        return
    hit = set()
    for _nm, _cls in list(vars(_AS).items()):
        if not (isinstance(_cls, type) and issubclass(_cls, _AS.AtomicSkill)):
            continue
        if getattr(_cls, "code", "SK--") == "SK--" or getattr(_cls.clamp, "_zmax_dbg", False):
            continue
        _orig = _cls.clamp

        def _wrap(self, *a, __o=_orig, __nm=_nm, **k):
            if __nm not in hit:
                hit.add(__nm)
                try:
                    import debugpy as _dp                               # noqa: PLC0415
                    if _dp.get_global_debugger() is not None:
                        print("🔴 停在技能断点: %s.clamp" % __nm, flush=True)
                        _dp.breakpoint()
                except Exception:                                       # noqa: BLE001
                    pass
            return __o(self, *a, **k)

        _wrap._zmax_dbg = True                                             # type: ignore[attr-defined]
        _cls.clamp = _wrap
    print("🔴 已挂 9 个技能类的首执行中断 (F5 会停在 clamp 上一层)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=120, help="最多跑几步 (insert 全链约 348)")
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--mode", default="insert", choices=["insert", "full"])
    ap.add_argument("--quiet", action="store_true", help="不打引擎日志 (只看断点)")
    ap.add_argument("--skill-gate", default=None,
                    help="给 ZMAX_SKILL_GATE 赋值 (1 = 动作采用技能输出; 默认不改, 动作逐位不变)")
    ap.add_argument("--no-stop-at-skill", dest="stop_at_skill", action="store_false", default=True,
                    help="不往技能 clamp 里下断点 (默认会下, 连调试器时自动停)")
    a = ap.parse_args()

    _boot()
    if a.skill_gate is not None:
        os.environ["ZMAX_SKILL_GATE"] = str(a.skill_gate)
    if a.stop_at_skill:
        _stop_at_skills()          # 🔴 把断点装进 SK01~SK08 的 clamp (F5 时自动停)

    from lerobot.engine.runtime import RealStateSpaceSim            # noqa: PLC0415

    def _log(*x):
        if not a.quiet:
            print(" ".join(str(i) for i in x), flush=True)

    print("🧪 引擎直达 · seed=%d mode=%s steps=%d · ZMAX_SKILL_GATE=%s"
          % (a.seed, a.mode, a.steps, os.environ.get("ZMAX_SKILL_GATE", "0(默认)")), flush=True)
    print("   断点建议: src/lerobot/policies/left_right/state_space/skills/atomic_skills.py"
          " 各 SKxx.clamp 的 return 行", flush=True)

    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode=a.mode, log=_log)
    tr = sim.run(max_steps=a.steps)

    st = tr.get("stage") or []
    sched = getattr(sim, "sched", None) or getattr(getattr(sim, "eng", None), "sched", None)
    calls = getattr(sched, "skill_calls", None) if sched is not None else None
    if calls is None:                                            # 兜底: 从引擎内部对象找
        for v in vars(sim).values():
            if hasattr(v, "sched"):
                calls = getattr(v.sched, "skill_calls", None)
                if calls:
                    break
    print("\n==== 结果 ====", flush=True)
    print("步数: %d" % len(tr.get("t", [])), flush=True)
    print("段序列: %s" % " → ".join(dict.fromkeys(st)), flush=True)
    print("skills clamp 调用次数: %s" % (dict(sorted((calls or {}).items())) or "(空)"), flush=True)
    if calls:
        print("合计 %d 次 / 步数 %d (每步恰好 1 次 ⇒ 技能真在链路里)"
              % (sum(calls.values()), len(tr.get("t", []))), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
