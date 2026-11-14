#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_dispatch_main.py — **调度主程序** (统一状态空间 · 工厂调度入口)

老倪 2026-11-14:「启动程序不应该是一个纯 tick 循环, 应该是状态机」「状态机放在动作调制节点,
对应小脑基底节的状态, 工厂调度」。

结构 (三层, 各司其职, 不再混在一起):
   ① 主程序 = 本文件          : 起手建/取**进程级状态机单例**, 打状态集合与策略表, 装每拍钩子
   ② 状态机 = state_space/scheduler_fsm.py::DispatchFSM
                              : 13 个工厂状态 + 每状态策略(层配比/限速/力否决) + 证据守卫
   ③ 执行腿 = tools/ss_canvas_loop.py (当作引擎 import, 不单独当入口)
                              : 10Hz 逐节点 tick, 调制器每拍用状态机给出的策略融合+过闸

为什么状态机不在这里 new 而是 get_fsm(): 调制器是**每拍新建**的(safety_limit_impl:252),
状态若跟着它 new 就永远停在「接近」; 状态是进程级事实, 必须单例 (见 scheduler_fsm.get_fsm)。

用法:
    ./gui-venv311/bin/python tools/ss_dispatch_main.py                # 默认 mode=insert
    SS_MODE=full ./gui-venv311/bin/python tools/ss_dispatch_main.py   # 插拔+AOI 闭环
    VSCode: 选「🧠 后端工程 · 状态空间常驻循环」F5 (= 本文件)
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (os.path.join(_ROOT, "src"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 状态机与仲裁器默认开 (要对照旧行为: ZMAX_FSM=0 ZMAX_ORCH=0)
os.environ.setdefault("ZMAX_FSM", "1")
os.environ.setdefault("ZMAX_ORCH", "1")

from lerobot.policies.left_right.state_space.scheduler_fsm import (   # noqa: E402
    STATES, POLICY, get_fsm)
import ss_canvas_loop as engine                                      # noqa: E402  执行腿


def main() -> int:
    mode = os.environ.get("SS_MODE", "insert")
    fsm = get_fsm(mode=mode)
    fsm._dump()                                   # 初始状态先落盘, 页面第一眼就能看到

    print("🧠 调度主程序 · 状态机入口 (工厂调度)")
    print("   状态集合 (%d): %s" % (len(STATES), " → ".join(STATES)))
    print("   模式: %s · 状态机: %s · 仲裁器: %s"
          % (mode, os.environ.get("ZMAX_FSM"), os.environ.get("ZMAX_ORCH")))
    print("   每状态策略(层配比 L3/L4/L2 · 限速 m/s · 力否决 N):")
    for s in STATES:
        p = POLICY[s]
        print("     %-7s L3 %.2f L4 %.2f L2 %.2f · v≤%.3f · Fveto %.0fN"
              % (s, p["w_L3"], p["w_L4"], p["w_L2"], p["v_cap"], p["f_veto_n"]))
    print("   执行腿: tools/ss_canvas_loop.py (10Hz 逐节点) — 状态机只做调度, 动作仍过物理闸")
    sys.stdout.flush()

    last = [fsm.state]
    t_state = [time.time()]

    def hook(n_tick, traces):
        """每拍: 状态机的状态变化 → 一行取证 (不刷屏, 只在切换时打)"""
        st = fsm.state
        if st == last[0]:
            return
        p = fsm.policy()
        if n_tick % 50 == 0 or True:
            print("🔀 tick=%d 状态 %s → %s · %s | L3 %.2f L4 %.2f L2 %.2f · v≤%.3f"
                  % (n_tick, last[0], st, fsm.last_reason,
                     p["w_L3"], p["w_L4"], p["w_L2"], p["v_cap"]))
            sys.stdout.flush()
        last[0] = st
        t_state[0] = time.time()

    engine.TICK_HOOK = hook
    engine.main()                    # 阻塞: 10Hz 逐节点执行(引擎), 每拍回调上面的 hook
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n停止")
