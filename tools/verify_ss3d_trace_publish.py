#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ss3d_trace_publish.py — 判据: 状态空间 ▶运行 时 3D 面板被逐帧喂帧 ⇒ 轨迹快照在写
⇒ 实时监控·信号分析 波形跟着动 (老倪 2026-10-12「信号分析运行啊，动起来」)

真根因(实测): open_ss_3d 有**三条出口**, 其中「把 Sim&Real 页内嵌的 live DreamView 拎成独立窗口」
这条是**提前 return** 的 —— 唯一没登记进 `_ss_3d_windows` 的路径。而 `_ss_tick` 每 tick 只遍历
`_ss_3d_windows` 调 `set_frame(idx)`, 3D 面板又是 `trace_live.json` 的**唯一发布者**
(`ss_dreamview.publish_trace_live`) ⇒ 不喂它 = 快照不写 = 信号分析永远停在"停下的那一刻"。

跑法: gui-venv311/bin/python tools/verify_ss3d_trace_publish.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

OK, FAIL = [], []


def ck(name, cond, info=""):
    (OK if cond else FAIL).append(name)
    print("  %s %s   ← %s" % ("✅" if cond else "❌", name, info))


class _Fake3D:
    """替身 3D 面板: 只记调用, 不做 GL。"""

    def __init__(self):
        self.tr = None
        self.module = None
        self.title = None
        self.set_traj_calls = []
        self.shown = False
        self._cam_watch = None

    def setParent(self, *a):
        pass

    def setWindowFlags(self, *a):
        pass

    def setWindowTitle(self, t):
        self.title = t

    def resize(self, *a):
        pass

    def show(self):
        self.shown = True

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def set_trajectory(self, tr):
        self.tr = tr
        self.set_traj_calls.append(tr)


class _FakeSelf:
    def __init__(self, tr):
        self._ss_tr = tr
        self._ss_3d_windows = []
        self.logs = []

    def _log(self, m):
        self.logs.append(str(m))


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])                        # noqa: F841
    import simulink_module as SM
    import ss_dreamview as DV

    src = open(os.path.join(ROOT, "tools", "gui", "simulink_module.py"), encoding="utf-8").read()

    # ① 真源同一份: 3D 发布者写的路径 == 信号分析读的路径
    ck("① 发布者与信号分析读同一个 trace_live.json",
       DV.SS_TRACE_LIVE.replace("\\", "/").endswith("zmax_data/ss_live/trace_live.json")
       and "zmax_data/ss_live/trace_live.json" in src,
       DV.SS_TRACE_LIVE)

    # ② 复用分支(提前 return) 必须登记 —— 这是本次修的 bug
    fake = _Fake3D()
    tr = {"t": [0, 1], "x": [[0, 0, 0], [1, 1, 1]]}
    me = _FakeSelf(tr)
    saved = DV.live_dreamview
    DV.live_dreamview = lambda: fake
    try:
        got = SM.SimulinkModule.open_ss_3d(me, on_top=False)
    finally:
        DV.live_dreamview = saved
    ck("② 复用分支返回了那个 live 窗口", got is fake)
    ck("②b 它被登记进 _ss_3d_windows(修前为空 ⇒ 不喂帧)",
       me._ss_3d_windows == [fake], "len=%d" % len(me._ss_3d_windows))
    ck("②c 绑定了 module(3D 上的 ▶运行/⏹停止 = 同一引擎)", fake.module is me)
    ck("②d 已把 self._ss_tr 推给窗口(set_trajectory)",
       fake.set_traj_calls and fake.set_traj_calls[0] is tr)
    ck("②e 窗口标题 = 3D场景", fake.title == "3D场景", str(fake.title))
    ck("②f 登记动作留了日志(可审计)", any("登记" in x for x in me.logs), me.logs[-1:] )

    # ③ _real_finish 播放前把**本轮**轨迹推给在册窗口
    i = src.find("def _real_finish")
    body = src[i:i + 3000]
    ck("③ _real_finish 有 本轮轨迹→3D 窗口 的推行", "set_trajectory(tr)" in body
       and "_ss_3d_windows" in body)

    # ④ _ss_tick 每 tick 喂帧 (前提成立才有意义)
    j = src.find("def _ss_tick")
    ck("④ _ss_tick 每 tick 对在册窗口 set_frame(idx)",
       "_ss_3d_windows" in src[j:j + 6000] and "set_frame(idx)" in src[j:j + 6000])

    # ⑤ 发布者确实挂在 3D 渲染路径上 (HUD 更新里 publish)
    k = open(os.path.join(ROOT, "tools", "gui", "ss_dreamview.py"), encoding="utf-8").read()
    ck("⑤ publish_trace_live 在 3D HUD 更新路径里被调用",
       "publish_trace_live({" in k and "同一帧数值落快照" in k)
    ck("⑤b 节流键名不算错(帧 与 frame 不同名也不影响: 键不同 ⇒ 恒不相等 ⇒ 总是写)",
       '"帧": int(i)' in k, "见 publish_trace_live 的 dedupe 分支")

    print("\n%s  (%d PASS / %d FAIL)" % ("★ 全部通过 ✓" if not FAIL else "✗ 有失败项", len(OK), len(FAIL)))
    return 0 if not FAIL else 2


if __name__ == "__main__":
    raise SystemExit(main())
