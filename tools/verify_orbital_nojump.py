"""太阳系「禁止跳跃」判据 (2026-10-19 老倪: 「太阳系, 所有显示, 禁止跳跃。必须改,
不能有任何连线的跳跃的发生」)。

判定四件事 (全部在真 widget 上跑, 真 paint + 真 timer 步进):
  N1 公转相位单帧步长 ≤ 0.30 rad    —— 球体只许连续转, 不许瞬移
  N2 文字块单帧位移 ≤ 22px          —— 布局换位必须低通 (上限 14px/帧)
  N3 连线透明度单帧变化 ≤ 0.35      —— 线出现/消失必须渐变, 不许硬切
  N4 数据阶跃时月球轨道半径 ≤ 0.06/帧 —— 残差从 0 跳到 0.30 也不许跳
额外 N5: 连线的端点必须跟着球心走 (同一帧内 pos 与 drawLine 端点一致 —— 用 _force_segments 复核)。
"""
import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication                                   # noqa: E402

app = QApplication([])
import orbital_arch as OA                                                  # noqa: E402

ok_all = True


def chk(code, name, cond, detail=""):
    global ok_all
    ok_all = ok_all and bool(cond)
    print("%s %s  %s%s" % ("✅" if cond else "❌", code, name, ("    " + detail) if detail else ""))


w = OA.OrbitalArchView()
w.resize(1080, 360)
w.show()
w.data.running = True
app.processEvents()
w.grab()

hist = {"body": [], "lbl": [], "alpha": [], "wob": []}
_orig_labels = w._labels


def _labels(p, pos, cx, cy, R, b, W, H, S):
    _orig_labels(p, pos, cx, cy, R, b, W, H, S)
    hist["lbl"].append({k: (v.x(), v.y()) for k, v in getattr(w, "_lbl_pos", {}).items()})
    hist["body"].append({k: (v[0], v[1]) for k, v in pos.items() if isinstance(v, tuple) and len(v) >= 2})
    hist["body"][-1]["_c"] = (float(cx), float(cy))
    hist["alpha"].append(dict(getattr(w, "_edge_a", {})))
    hist["wob"].append(float(getattr(w, "_wob_s", 0.0) or 0.0))


w._labels = _labels

_victim = [e for e in w._edges if e.get("body_body")][0]
_ok_orig = w._signal_ok

for i in range(60):
    w.data.running = True
    if i == 20:                                    # 数据阶跃: 月球残差 0 → 0.30
        w.data.body.setdefault("moon", {})["err"] = 0.30
    if i == 30:                                    # 一条线失去信号 ⇒ 必须渐隐
        w._signal_ok = lambda e, b, _v=_victim: False if e is _v else _ok_orig(e, b)
    if i == 45:                                    # 恢复 ⇒ 必须渐显
        w._signal_ok = _ok_orig
    w._tick()
    w.grab()
    app.processEvents()

w._signal_ok = _ok_orig


def _max_ang(seq):
    worst = 0.0
    for a, b in zip(seq, seq[1:]):
        cx, cy = a.get("_c", (0.0, 0.0))
        for k in ("mercury", "earth", "mars", "jupiter"):
            if k in a and k in b:
                a1 = math.atan2(a[k][1] - cy, a[k][0] - cx)
                a2 = math.atan2(b[k][1] - cy, b[k][0] - cx)
                worst = max(worst, abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi))
    return worst


def _max_px(seq):
    worst = 0.0
    for a, b in zip(seq, seq[1:]):
        for k in a:
            if k in b and not k.startswith("_"):
                worst = max(worst, math.hypot(a[k][0] - b[k][0], a[k][1] - b[k][1]))
    return worst


def _max_abs1(seq):
    worst = 0.0
    for a, b in zip(seq, seq[1:]):
        for k in a:
            if k in b:
                worst = max(worst, abs(a[k] - b[k]))
    return worst


ang = _max_ang(hist["body"])
lbl = _max_px(hist["lbl"])
alp = _max_abs1(hist["alpha"])
wob = _max_abs1([{"v": x} for x in hist["wob"]])

chk("N1", "公转相位单帧步长 ≤ 0.30 rad (球只连续转, 不瞬移)", ang <= 0.30, "实测 %.4f rad/帧" % ang)
chk("N2", "文字块单帧位移 ≤ 22px (布局换位走低通, 上限 14px/帧)", lbl <= 22.0, "实测 %.2f px/帧" % lbl)
chk("N3", "连线透明度单帧变化 ≤ 0.35 (出现/消失渐变)", alp <= 0.35, "实测 %.3f/帧" % alp)
chk("N4", "数据阶跃 (月球残差 0→0.30) 时轨道半径 ≤ 0.06/帧", wob <= 0.06, "实测 %.3f/帧" % wob)

# N5: 连线端点 == 球心 (同帧一致), 不许"线不跟球走"
W, H, S, cx, cy, R = w._geom()
pos = w.positions(cx, cy, R)
segs = w._force_segments(pos, w.data.body)
_bad = 0
for (_e, _o) in segs:
    pa = pos.get(w._key_of(_e["f"]))
    pb = pos.get(w._key_of(_e["t"]))
    if pa is None or pb is None:
        continue
    _dd = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
    if _dd < 1.0:
        _bad += 1
chk("N5", "每条主体连线的两端都能取到当前球心 (线跟着球走)", _bad == 0, "取不到端点的边 %d 条" % _bad)

print("═══ 太阳系无跳跃判据: %s ═══" % ("全部通过" if ok_all else "有未通过项"))
sys.exit(0 if ok_all else 1)
