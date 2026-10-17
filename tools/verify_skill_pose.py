# -*- coding: utf-8 -*-
"""判据: 原子技能的位姿信号必须是**真实、在动、可追溯**的。

老倪 2026-10-17: 「信号分析的信号是真实的么? 3D 场景的光模块都已经抓起来了, 而且插拔成功了,
   但是为什么我现在看到的这几个信号一直不变呢, 例如抓取的 x 位置, 接近的 x 位置」

病史: tap 位姿 state_*.jsonl 停更 30+ 小时 ⇒ _read_pose 按"不许拿旧位姿当现在"一律填 -1.0
      ⇒ 8 个技能的 x/y/z 全是常量 -1。修法: 停更时回落 3D 场景真值 trace_live.json(末端_x/y/z, m→mm),
      冻结快照不用; 并且位置与"在职"解耦 (在职只决定 v/a/s/err)。
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
FAIL = []


def ck(name, ok, info=""):
    print(("%s %s" % ("✅" if ok else "❌", name)) + ((" · " + str(info)) if info else ""))
    if not ok:
        FAIL.append(name)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


sp1 = load(os.path.join(LIVE, "skill_phys.json"))
time.sleep(3.0)
sp2 = load(os.path.join(LIVE, "skill_phys.json"))
tl = load(os.path.join(LIVE, "trace_live.json"))

sk1 = (sp1.get("skills") or {})
sk2 = (sp2.get("skills") or {})
pose2 = sp2.get("pose") or {}

ck("位置不是 -1 占位", all(isinstance((sk2.get(k) or {}).get("x"), (int, float))
                          and (sk2.get(k) or {}).get("x") != -1.0 for k in ("SK01", "SK04")),
   {k: (sk2.get(k) or {}).get("x") for k in ("SK01", "SK04")})
_moved = [k for k in sk1 if isinstance(sk1[k], dict)
          and isinstance(sk1[k].get("x"), (int, float)) and isinstance(sk2[k].get("x"), (int, float))
          and abs(sk2[k]["x"] - sk1[k]["x"]) > 1e-6]
ck("3s 内位置在变 (不是冻结值)", bool(_moved),
   "变了 %d 个技能, 例 SK01 %s→%s" % (len(_moved), sk1.get("SK01", {}).get("x"),
                                    sk2.get("SK01", {}).get("x")))
ck("位姿标了出处 (可审计)", bool((sk2.get("SK01") or {}).get("pose_src")),
   (sk2.get("SK01") or {}).get("pose_src"))
ck("位姿帧龄新鲜 (<2s)", float(pose2.get("pose_age_s") or 999) < 2.0, pose2.get("pose_age_s"))

_ex, _ey, _ez = tl.get("末端_x"), tl.get("末端_y"), tl.get("末端_z")
_dx = abs(float(pose2.get("x") or 0) - float(_ex) * 1000.0) if _ex is not None else 999
ck("技能位姿 == 3D 场景末端 (同源, ≤30mm)", _dx <= 30.0,
   "pos %.1f vs 场景 %.1f mm" % (float(pose2.get("x") or 0), float(_ex or 0) * 1000.0))

_tap = sorted([p for p in os.listdir(LIVE) if p.startswith("state_") and p.endswith(".jsonl")])
_tap_age = (time.time() - os.path.getmtime(os.path.join(LIVE, _tap[-1]))) if _tap else 1e9
_src = str((sk2.get("SK01") or {}).get("pose_src") or "")
if _tap_age > 5.0:
    ck("tap 停更时明确回落并标注", _src.startswith("trace_live"), "tap 龄 %.0fs · src %s" % (_tap_age, _src))
else:
    ck("tap 新鲜时用 tap", _src.startswith("tap"), _src)

# 界面上确实在动: 面板两拍读值
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("DISPLAY", ":0")
from PyQt5.QtWidgets import QApplication                          # noqa: E402
app = QApplication.instance() or QApplication([])
from canoe_graphic import CanoeGraphicWidget                      # noqa: E402

w = CanoeGraphicWidget()
w.show()
t0 = time.time()
while time.time() - t0 < 3.0:
    app.processEvents()
    time.sleep(0.05)


def _val(key):
    out = [None]

    def _wk(x):
        for i in range(x.childCount()):
            ch = x.child(i)
            if ch.childCount():
                _wk(ch)
            elif str(ch.data(0, 0x0100) or "") == key and out[0] is None:
                out[0] = ch.text(3)
    _wk(w.tree.invisibleRootItem())
    return out[0]


_k1 = _val("skillphys.SK01 接近 · x 位置 mm")
t = time.time()
while time.time() - t < 3.0:
    app.processEvents()
    time.sleep(0.05)
_k2 = _val("skillphys.SK01 接近 · x 位置 mm")
ck("界面 SK01 x 有值且在变", _k1 not in (None, "-", "—") and _k1 != _k2,
   "%s → %s" % (_k1, _k2))

print("\n%s" % ("✅ 全部通过" if not FAIL else "❌ 失败: %s" % FAIL))
sys.exit(0 if not FAIL else 1)
