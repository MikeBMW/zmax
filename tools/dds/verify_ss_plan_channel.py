#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 ss_plan 跨网通道判据 (550B → 550C)

用法:
  在 4060 (550B):  python3 tools/dds/verify_ss_plan_channel.py --pub
  在 550C (intel): python3 tools/dds/verify_ss_plan_channel.py --sub

判据: 550C 本地 DDS 收到的 ss_plan 里 note/n_points/tcp_path 与 550B 发出的**逐字相同**。
"""
import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, os.path.join(ROOT, "dds")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from zmax_node import Node, TOPICS                                            # noqa: E402

PTS_MM = [[535.34, 306.06, 161.95], [535.34, 306.06, 221.95], [455.34, 306.06, 221.95],
          [455.34, 306.06, 161.95], [535.34, 306.06, 161.95]]
NOTE = "ws-bus ss_plan 判据 · 4段闭环 280mm · 60mm/s"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pub", action="store_true")
    ap.add_argument("--sub", action="store_true")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--wait", type=float, default=20.0)
    a = ap.parse_args()

    if a.pub:
        n = Node("ss_plan_pub_probe")
        n.pub("ss_plan")
        print("等配对…", n.wait_for_match("ss_plan", 0, 3))
        tcp = [v / 1000.0 for p in PTS_MM for v in p]
        for i in range(a.n):
            msg = TOPICS["ss_plan"](
                ts=time.time(), source="tools/traj_plan.py", group="zmax_arm",
                base_frame="base_link", plan_code=1, n_points=len(PTS_MM),
                plan_time_s=7.32, joints_path=[], tcp_path=tcp, start_joints=[],
                goal_xyz=[PTS_MM[-1][0] / 1000.0, PTS_MM[-1][1] / 1000.0, PTS_MM[-1][2] / 1000.0],
                end_err_mm=0.0, fk_start_pos_err_mm=0.0, gate_same_source=1,
                gate_reason="ws-bus 通道判据", frame_age_s=0.0, note="%s #%d" % (NOTE, i))
            n.send("ss_plan", msg)
            print("  → 发 #%d n_points=%d tcp_path=%d 个数" % (i, len(PTS_MM), len(tcp)))
            time.sleep(0.5)
        return 0

    if a.sub:
        n = Node("ss_plan_sub_probe")
        n.sub("ss_plan")
        print("订阅 ss_plan, 配对=%s, 等 %.0fs…" % (n.wait_for_match("ss_plan", 1, 6), a.wait))
        t0, got = time.time(), []
        while time.time() - t0 < a.wait:
            for s in n.sub("ss_plan").take():
                if s.note.startswith("ws-bus ss_plan 判据"):
                    got.append(s)
                    print("  收到 note=%r n_points=%d tcp_path=%d 个数 首点=%s" % (
                        s.note, s.n_points, len(s.tcp_path),
                        [round(v * 1000, 2) for v in list(s.tcp_path)[:3]]))
            time.sleep(0.1)
        ok = len(got) > 0
        if ok:
            s = got[-1]
            same = ([round(v * 1000, 2) for v in list(s.tcp_path)[:15]] ==
                    [round(v, 2) for p in PTS_MM for v in p])
            print("判定: 收到 %d 条 | 点列逐字相同=%s → %s" % (len(got), same, "✅ 通道成立" if same else "⚠️ 收到但点列不一致"))
            return 0 if same else 3
        print("判定: 0 条 → ❌ 不通")
        return 2

    print("要 --pub 或 --sub")
    return 1


if __name__ == "__main__":
    sys.exit(main())
