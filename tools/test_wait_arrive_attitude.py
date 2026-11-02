#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""到位判据(位置+姿态)离线自检 — 不需要真机, 不碰执行器。

老倪 2026-11-02「只有位置, 能保证姿态么」⇒ wait_arrive 加了姿态判据。
本脚本用**注入的假真值**验证四条口径, 每条都断言, 失败即非零退出:

  A. 位置到 + 姿态一致          ⇒ ok=True,  ang≈0
  B. 位置到 + 姿态差 3° (> 0.5°) ⇒ ok=False, att=out_of_tol (位置对了也不许报到位)
  C. 不给 target_q (老行为)      ⇒ ok=True,  att=unchecked
  D. 给了 target_q 但真值没姿态   ⇒ ok=False, att=unverified (fail-closed: 不认到位, 不冒充)
  E. 同上 + ZMAX_ARRIVE_ATT_FAILOPEN=1 ⇒ ok=True, att=unverified (现场显式放行, 仍标未验)

用法: ./gui-venv311/bin/python tools/test_wait_arrive_attitude.py [--tol-deg 0.5]
"""
from __future__ import annotations

import argparse
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.engineering.exec import daemon as D          # noqa: E402

TARGET = [0.5, -0.2, 0.3]                                 # 米 (daemon 内部口径)
Q0 = [0.0, 0.0, 0.0, 1.0]


def _rot_z(deg):
    """绕 z 轴转 deg 的四元数 [x,y,z,w]"""
    h = math.radians(deg) / 2.0
    return [0.0, 0.0, math.sin(h), math.cos(h)]


def _mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def _case(name, pos, quat, target_q, want_ok, want_att, tol_deg=0.5):
    D._pose_best = lambda: (list(pos), (list(quat) if quat else None), "direct")
    ok, err, src = D.wait_arrive(TARGET, tol_mm=2.0, timeout_s=1.3,
                                 target_q=target_q, tol_deg=tol_deg)
    att = D.WAIT_LAST.get("att")
    ang = D.WAIT_LAST.get("angle_deg")
    good = (bool(ok) == want_ok) and (att == want_att)
    print("%s %-26s ok=%-5s att=%-11s ang=%-7s err=%-5s src=%s"
          % ("PASS" if good else "FAIL", name, ok, att,
             ("%.2f" % ang) if ang is not None else "None",
             ("%.2f" % err) if err is not None else "None", src))
    if not good:
        print("     期望 ok=%s att=%s" % (want_ok, want_att))
    return good


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol-deg", type=float, default=0.5)
    a = ap.parse_args()
    t = a.tol_deg
    print("姿态容差 %.2f° · 位置容差 2.0mm · 超时 1.3s (每一轮 sleep 0.5s)" % t)
    res = [
        _case("A 位置到+姿态一致", TARGET, Q0, Q0, True, "ok", t),
        _case("B 位置到+姿态差 3°", TARGET, _mul(Q0, _rot_z(3.0)), Q0, False, "out_of_tol", t),
        _case("C 不给 target_q (老行为)", TARGET, _mul(Q0, _rot_z(3.0)), None, True, "unchecked", t),
        _case("D 给 target_q 但无姿态真值", TARGET, None, Q0, False, "unverified", t),
    ]
    os.environ["ZMAX_ARRIVE_ATT_FAILOPEN"] = "1"
    res.append(_case("E 无姿态真值+显式放行", TARGET, None, Q0, True, "unverified", t))
    os.environ.pop("ZMAX_ARRIVE_ATT_FAILOPEN", None)
    print("\n结果: %d PASS / %d FAIL" % (sum(res), len(res) - sum(res)))
    return 0 if all(res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
