#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pt_pose.py — 点位姿态口径的唯一实现 (老倪 2026-10-12: 「配置中心的点, 除了位置, 还得有 a b c, 6 个数字都要记录」)

点位库只存四元数 ⇒ a b c 由四元数按 **RPY(度)** 换算 —— 这套口径原来在
`cam_live_stream._pt_abc_deg`(8793 页面 tooltip) 与 `task_build`(配置中心) 各写了一份,
现在收成一份, 谁都用它, 免得两处算出不同的数(这正是老倪要的"全局数据一致")。

用法:
    from pt_pose import abc_deg, rec_abc, abc_str
    abc_deg([x, y, z, w])        -> [rx°, ry°, rz°] 或 None(读不到就不编)
    rec_abc({"quat": [...], "abc": [...]})  -> 优先用库里的 abc, 没有才现算
    abc_str(rec)                 -> "a=1.234 b=-5.678 c=90.000 °" / "a=— b=— c=—"
"""
from __future__ import annotations

import math
from typing import List, Optional


def abc_deg(quat) -> Optional[List[float]]:
    """四元数(x,y,z,w) → RPY 欧拉角(度) [a, b, c]。读不到返回 None(不编)。"""
    try:
        x, y, z, w = [float(v) for v in list(quat)[:4]]
        n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
        x, y, z, w = x / n, y / n, z / n, w / n
        rx = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
        sy = 2.0 * (w * y - z * x)
        ry = math.copysign(math.pi / 2.0, sy) if abs(sy) >= 1.0 else math.asin(sy)
        rz = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
        return [round(math.degrees(v), 3) for v in (rx, ry, rz)]
    except Exception:                                                           # noqa: BLE001
        return None


def rec_abc(rec) -> Optional[List[float]]:
    """从一条点位记录里取 a b c: 先看记录自己存的 abc(记录时写进去的), 没有才从 quat 现算。"""
    try:
        a = (rec or {}).get("abc")
        if isinstance(a, (list, tuple)) and len(a) == 3:
            return [float(a[0]), float(a[1]), float(a[2])]
    except Exception:                                                           # noqa: BLE001
        pass
    return abc_deg((rec or {}).get("quat"))


def abc_str(rec) -> str:
    """拼成 'a=.. b=.. c=.. °'(读不到就留 —, 不编)。"""
    v = rec_abc(rec)
    return ("a=%.3f b=%.3f c=%.3f °" % (v[0], v[1], v[2])) if v else "a=— b=— c=—"


if __name__ == "__main__":                        # 自检: 恒等四元数 → 全 0; 绕 Z 90° → c=90
    import json
    import sys
    _ok = True
    _r1 = abc_deg([0.0, 0.0, 0.0, 1.0])
    _ok &= (_r1 == [0.0, 0.0, 0.0])
    _r2 = abc_deg([0.0, 0.0, 0.7071068, 0.7071068])
    _ok &= (abs(_r2[2] - 90.0) < 1e-3)
    print("自检: 恒等=%s · 绕Z90°=%s · %s" % (_r1, _r2, "✅" if _ok else "⛔"))
    sys.exit(0 if _ok else 1)
