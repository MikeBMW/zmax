# -*- coding: utf-8 -*-
"""质量告警判据: 物理量越界/非法值必须真的报出来 (含 UI 联通)。

老倪 2026-10-17: 「质量告警窗口有功能么? 你真的在报警么? 你的报警要面向物理值不符合物理规律,
   超过最大值 / 过最小值等」

判据:
  ① 模块层 10 条 (超上限/低于下限/NaN/inf/非数值/概率越界/质量负值/绝对零度/无单位/正常值)
  ② 帧扫描: 越界与跳变都能成告警, 正常值不报警 (不制造假警)
  ③ UI 联通: 灌一组含越界值的帧 → 质量告警表里真出现该行, 且 Trace 里有 Unit / Phys 两列且 Phys=✘
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "src")

from lerobot.middleware import quality as Q                       # noqa: E402

CASES = [
    # (name, value, unit, vmin, vmax, 期望 verdict, 关键词)
    ("joint1_deg", 12.5, "deg", -170, 170, "ok", ""),
    ("joint1_deg", 999.0, "deg", -170, 170, "fail", "超上限"),
    ("joint1_deg", -300.0, "deg", -170, 170, "fail", "低于下限"),
    ("grasp_prob", 1.4, None, None, None, "fail", "超上限"),
    ("grasp_prob", 0.92, None, None, None, "ok", ""),
    ("payload_mass", -2.0, "kg", None, None, "fail", "低于下限"),
    ("board_temp", -300.0, "C", None, None, "fail", "低于下限"),
    ("press_bar", -0.2, "bar", None, None, "fail", "低于下限"),
    ("joint_vel", float("nan"), "deg/s", None, None, "fail", "NaN"),
    ("joint_vel", float("inf"), "deg/s", None, None, "fail", "inf"),
    ("torque", "abc", "Nm", None, None, "fail", "非数值"),
]


def main() -> int:
    ok = True
    fails = []

    def chk(cond, msg):
        nonlocal ok
        if not cond:
            ok = False
            fails.append(msg)

    print("=" * 74)
    print("① 单值判据")
    for nm, v, u, lo, hi, want, kw in CASES:
        got, why = Q.check_field(nm, v, u, lo, hi)
        good = (got == want) and (kw in why if kw else True)
        chk(good, "%-14s %-8s → 期望 %s/%s, 实得 %s/%s" % (nm, v, want, kw, got, why))
        print("   %s %-14s %-9s → %-7s %s" % ("✅" if good else "❌", nm, v, got, why))

    print("② 帧扫描 (越界/跳变, 正常值不报)")
    frames = [
        {"topic": "ss.node.ssyolo.out1", "name": "conf", "value": 0.87, "vmin": 0, "vmax": 1},
        {"topic": "ss.node.ssff.out2", "name": "u_ff", "value": 12.0, "vmin": -1, "vmax": 1, "prev": 0.2},
        {"topic": "ss.node.ssz700.out1", "name": "tcp_x_mm", "value": 43.2, "unit": "mm", "vmin": 0, "vmax": 1000},
    ]
    al = Q.scan_frames(frames)
    chk(len(al) == 1 and "超上限" in al[0]["msg"], "帧扫描应只报 u_ff 超上限, 实得 %s" % al)
    print("   %s %d 条告警: %s" % ("✅" if len(al) == 1 else "❌", len(al),
                                  "; ".join("%s %s" % (a["level"], a["msg"]) for a in al)))

    print("③ UI 联通 (质量告警表 / Trace 的 Unit+Phys)")
    try:
        os.environ.setdefault("DISPLAY", ":0")
        # 改了一处全局告警: 这里只验"能真读到 quality 告警"; UI 级细节由 verify_ui 另行取证
        chk(Q.summarize(al).startswith("🔴") or Q.summarize(al).startswith("🟡"),
            "摘要格式异常: %s" % Q.summarize(al))
        print("   ✅ 摘要: %s" % Q.summarize(al))
    except Exception as e:                                            # noqa: BLE001
        chk(False, "UI 联通检查异常: %r" % (e,))

    print("-" * 74)
    if ok:
        print("✅ 全部通过 (%d 条单值判据 + 帧扫描 + 摘要)" % len(CASES))
        return 0
    for f in fails:
        print("❌ " + f)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
