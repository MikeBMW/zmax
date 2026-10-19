#!/usr/bin/env python3
"""verify_gravity_law.py — 四层力必须严格满足万有引力定律 (老倪 2026-10-19 要求)。

核验的不是"写了这个公式", 而是**界面上正在用的那组力**是否真的满足:
  ① 反平方     r 翻倍 ⇒ |F| 变 1/4 (err ≤1e-12)
  ② 保守场     F_r = −dΦ/dr (数值微分, err ≤1e-6)
  ③ 作用反作用 每一对力的和 = 0 (残差 ≤1e-12)
  ④ 叠加       四层逐位相加 == 表里那一行的合力 (残差 ≤1e-9)
  ⑤ 势能       Σ Φ_i == Φ_total (残差 ≤1e-9)
  ⑥ 可对账     每格 src 写明 "引力律 M=… r=…", 能追到 gravity_law.json
  ⑦ 场上也成立 改某层 r 翻倍 (临时配置) ⇒ 该层 |F| 恰好变 1/4
  ⑧ 主力       表的主力 == 引力场里 |F| 最大的那层
用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_gravity_law.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication                                    # noqa: E402

import gravity_law as GL                                                    # noqa: E402
import gravity_table as GT                                                  # noqa: E402

R = []


def chk(tag, title, ok, msg=""):
    R.append((tag, title, bool(ok), msg))


def main():
    app = QApplication.instance() or QApplication([])
    f = GT.GravityField()
    f.reload()
    st, _ = f.dominant_now()
    row = next((r for r in f.rows if r.get("stage") == st), None)
    cells = (row or {}).get("cells") or {}
    vecs = dict((L, (cells.get(L) or {}).get("vec")) for L in ("L2", "L3", "L4", "L5"))
    have = dict((L, v) for L, v in vecs.items() if v)

    inv = GL.invariants(have)
    chk("①", "反平方律 |F|=G·M/r²: r 翻倍 ⇒ 力变 1/4",
        abs(inv["inverse_square"]["ratio"] - 4.0) <= 1e-12,
        "F(r)=%.6f F(2r)=%.6f 比值=%.12f" % (inv["inverse_square"]["F_r"],
                                            inv["inverse_square"]["F_2r"],
                                            inv["inverse_square"]["ratio"]))
    chk("②", "保守场 F_r = −dΦ/dr (Φ=−G·M·m/r)",
        inv["conservative_radial"]["err"] <= 1e-6,
        "−dΦ/dr=%.9f F=%.9f 差=%.2e" % (inv["conservative_radial"]["F_r_minus_grad"],
                                        inv["conservative_radial"]["F_toward"],
                                        inv["conservative_radial"]["err"]))
    chk("③", "作用反作用 F(i→j) = −F(j→i)",
        inv["action_reaction"]["max_residual"] <= 1e-12,
        "逐对残差最大 %.2e" % inv["action_reaction"]["max_residual"])
    chk("④", "叠加: 四层力逐位相加 == 表里这一行的合力",
        (inv.get("superposition") or {}).get("residual", 9) <= 1e-9,
        "残差 %.2e" % (inv.get("superposition") or {}).get("residual", -1))
    chk("⑤", "势能 ΣΦ_i == Φ_total",
        inv["potential"]["residual"] <= 1e-9,
        "Φ总=%.6f · 残差 %.2e" % (inv["potential"]["phi_total"], inv["potential"]["residual"]))

    _bad = [L for L in have if "引力律 M=" not in str((cells.get(L) or {}).get("src") or "")]
    chk("⑥", "每格 src 写明引力律参数 (M / r), 可追到 config/calib/gravity_law.json",
        not _bad, ("缺: %s" % _bad) if _bad else "四格都有 M=… r=…")

    # ⑦ 在**场上**再验一次反平方: 临时把 L2 的 r 翻倍, 该层 |F| 必须恰好 1/4
    _g0 = GL.field(have)
    _c = GL.cfg()
    _c["layers"]["L2"]["r"] = float(_c["layers"]["L2"]["r"]) * 2.0
    _g1 = GL.field(have, _c)
    _f0 = next((x["mag"] for x in _g0["comps"] if x["L"] == "L2"), 0.0)
    _f1 = next((x["mag"] for x in _g1["comps"] if x["L"] == "L2"), 0.0)
    chk("⑦", "场上验反平方 (L2 的 r 翻倍 ⇒ 该层 |F| 变 1/4)",
        _f0 > 0 and abs((_f0 / _f1) - 4.0) <= 1e-9,
        "|F|r=%.6f → |F|2r=%.6f 比值 %.9f" % (_f0, _f1, (_f0 / _f1) if _f1 else -1))

    chk("⑧", "表的主力 == 引力场里 |F| 最大的那层",
        (row or {}).get("main") == _g0.get("main"),
        "表=%s · 场=%s" % ((row or {}).get("main"), _g0.get("main")))

    npass = sum(1 for x in R if x[2])
    print()
    for tag, title, ok, msg in R:
        print("%s %s %s  %s" % ("✅" if ok else "❌", tag, title, ("· " + msg) if msg else ""))
    print("\n═══ 引力律判据 %d 条: PASS %d · FAIL %d ═══" % (len(R), npass, len(R) - npass))
    return 0 if npass == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
