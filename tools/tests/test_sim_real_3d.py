#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sim&Real 页「3D 场景编辑器 · 主视图」判据 (2026-10-10 老倪)。

老倪原话: 「simulink 画布的 3D 视图那个按钮，哪里去了？找回来。仿真可视化的功能很重要。
          场景 Sim&Real 功能区，应该有个主要的可视化编辑界面，跟 simulink 画布的 3D 视图同源，
          可以编辑 3D 场景」

判据 (全 offscreen 真建控件, 不打桩 UI 结构):
  ① 页内第一块内容 = 「3D 场景编辑器 · 主视图」卡, 有 打开/档位L2L3L4/抓快照 五个按钮
  ② 点页内主按钮 → 真调画布 open_ss_3d(on_top=True); 档位按钮真带 level
  ③ **同源取证**: 画布工具栏「🧭 3D 视图」与页内按钮打到**同一个** open_ss_3d
  ④ 兜底不崩: 没开 3D 时抓快照 / 画布未就绪时点打开 → 只提示不崩
  ⑤ 视觉证据: 主视图卡真渲染 PNG (老倪要看得到, 不只看打印)
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")]

from PyQt5.QtWidgets import QApplication, QPushButton, QWidget            # noqa: E402

app = QApplication(sys.argv)

import sim_real_page as SR                                               # noqa: E402
import simulink_module as SM                                             # noqa: E402

FAIL = []


def chk(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + str(msg), flush=True)
    if not cond:
        FAIL.append(msg)


def _btn(body, sub):
    for b in body.findChildren(QPushButton):
        if sub in b.text():
            return b
    return None


print("判据 ① Sim&Real 页主视图卡 (与画布 3D 同源)", flush=True)


class FakeWin(QWidget):
    def __init__(self):
        super().__init__()
        self.simulink = None


called = []


class FakeCanvas:
    """替身画布: 只提供 open_ss_3d (与真 SimulinkModule 同名同签名)"""

    def open_ss_3d(self, on_top=True, level=None):
        called.append((on_top, level))
        return True


w = FakeWin()
w.simulink = FakeCanvas()
body = SR.build_body(w)
texts = [b.text() for b in body.findChildren(QPushButton)]
chk(_btn(body, "打开 3D 场景编辑器") is not None,
    f"页内有「🧭 打开 3D 场景编辑器」主按钮 (页内共 {len(texts)} 个按钮)")
for _lv in ("L2", "L3", "L4"):
    chk(_btn(body, _lv) is not None, f"有档位按钮 {_lv}")
chk(_btn(body, "抓取快照") is not None, "有「📷 抓取快照」按钮 (同一 GL 上下文, 不新开第二个 3D 视图)")

print("判据 ② 页内按钮 → 真调画布 open_ss_3d", flush=True)
_btn(body, "打开 3D 场景编辑器").click()
app.processEvents()
chk(bool(called) and called[-1] == (True, None), f"点主按钮 → open_ss_3d(on_top=True, level=None) 实测 {called[-1:]}")
_btn(body, "L3").click()
app.processEvents()
chk(called[-1] == (True, "L3"), f"点档位按钮 L3 → level='L3' 实测 {called[-1]}")

print("判据 ③ 同源: 画布工具栏「🧭 3D 视图」与页内按钮同一入口", flush=True)
_hit = []
_REAL_OPEN3D = SM.SimulinkModule.open_ss_3d            # 存真实现, 判据⑥ 要拿它真建窗口
SM.SimulinkModule.open_ss_3d = lambda self, *a, **k: _hit.append(k.get("level"))
m = SM.SimulinkModule()
app.processEvents()
_b = getattr(m, "btn_ss_3d", None)
chk(_b is not None and "3D 视图" in _b.text(), f"画布工具栏有「🧭 3D 视图」按钮 (文本={_b.text() if _b else '无'})")
chk(bool(_b) and _b.isVisibleTo(m), "「🧭 3D 视图」已挂进工具栏布局 (曾是 43b233d 精简时漏挂的 bug)")
_b.click()
app.processEvents()
chk(bool(_hit), f"工具栏按钮 → 同一个 open_ss_3d (实测 {_hit})")
SM.SimulinkModule.open_ss_3d = _REAL_OPEN3D            # 还原真实现 (否则判据⑥ 打的是替身)

print("判据 ④ 兜底不崩 (没开 3D / 画布未就绪)", flush=True)
try:
    _btn(body, "抓取快照").click()
    app.processEvents()
    chk(True, "没开 3D 时点抓快照: 只提示不崩")
except Exception as ex:                                                   # noqa: BLE001
    chk(False, f"没开 3D 时点抓快照崩了: {ex!r}")
try:
    w.simulink = None
    _btn(body, "打开 3D 场景编辑器").click()
    app.processEvents()
    chk(True, "画布未就绪时点「打开 3D」: 只提示不崩")
except Exception as ex:                                                   # noqa: BLE001
    chk(False, f"画布未就绪时点「打开 3D」崩了: {ex!r}")

print("判据 ⑤ 视觉证据 (主视图卡真渲染)", flush=True)
try:
    shots = "/home/ubuntu/.hermes/cache/scratch/shots"
    os.makedirs(shots, exist_ok=True)
    p = os.path.join(shots, "sim_real_3d_card.png")
    body.resize(1100, 900)
    body.show()
    app.processEvents()
    body.grab().save(p)
    from PIL import Image
    im = Image.open(p).convert("RGB")
    px = list(im.getdata())
    gold = sum(1 for r, g, b in px if r > 180 and 120 < g < 220 and b < 120)
    chk(gold > 150, f"主视图卡真渲染出金色元素 (金色像素 {gold}) → {p}")
except Exception as ex:                                                   # noqa: BLE001
    chk(False, f"渲染取证失败: {ex!r}")

print("判据 ⑥ 真建 3D 视图 → 场景编辑面板真挂上 (2026-10-10 sys 局部名 bug 回归钉死)", flush=True)
try:
    import contextlib                                                      # noqa: E402
    import io                                                              # noqa: E402

    m3 = SM.SimulinkModule()
    m3._log = lambda *a, **k: None
    m3._qmsg_info = lambda *a, **k: None
    try:                                    # 优先真 episode (与操作视频同源的轨迹, 字段齐全)
        from ss_dreamview import load_episode
        _ep, _meta = load_episode()
    except Exception:                                                      # noqa: BLE001
        _ep = None
    m3._ss_tr = _ep if _ep else {"x": [0.0, 0.1, 0.2], "y": [0.0, 0.1, 0.2],
                                 "z": [0.0, 0.0, 0.1], "gripper": [0.0, 0.0, 0.0]}
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        m3.open_ss_3d(on_top=False)
    app.processEvents()
    _ws = [x for x in (getattr(m3, "_ss_3d_windows", None) or []) if x is not None]
    _out = _buf.getvalue()
    chk("挂载失败" not in _out,
        f"open_ss_3d 不再报「3D场景编辑挂载失败」 (实测 stdout: {_out.strip().splitlines()[:1] or '空'})")
    _att = getattr(_ws[0], "_scene_edit_attacher", None) if _ws else None
    chk(_att is not None and getattr(_att, "panel", None) is not None,
        "3D 视图真挂上「🗂 场景编辑」面板 ⇒ 可在 3D 里检出/编辑/显隐/新增对象 "
        f"(attacher={'有' if _att is not None else '无'}, panel={'有' if getattr(_att, 'panel', None) is not None else '无'})")
except Exception as ex:                                                   # noqa: BLE001
    chk(False, f"真建 3D 视图取证失败: {ex!r}")

print(("❌ 失败 %d 项: %s" % (len(FAIL), FAIL)) if FAIL
      else "✅ 全部通过 — Sim&Real「3D 场景编辑器 · 主视图」与画布 3D 视图同源", flush=True)
sys.stdout.flush()
os._exit(1 if FAIL else 0)
