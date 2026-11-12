#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_su2_output_provenance.py — 判定「SU2 球上的轨迹 / 状态空间输出」到底是哪一套

机器上同时存在两个 SU(2) 四元数:
  ① 引擎导航点 p  = from_rotvec(bounded_rotvec(z_latent[:3], gain=2))   (ss_engine_loop 每拍)
  ② 场景态 U_scene = U_L2 ⊗ U_L3 ⊗ U_L4 ⊗ U_L5                        (画布 ssobs 节点, 只在内存)
两者共用 S³, 但不是同一个量。本脚本用重算把①钉死, 并指出②的出处 —— 
避免把引擎 p 说成「统一状态空间输出」(那属于假口径)。

跑法: <venv>/bin/python scripts/verify_su2_output_provenance.py
环境: ZMAX_ROOT (默认 ~/zmax) · ZMAX_DATA (默认 $ZMAX_ROOT/zmax_data)
"""
import json
import math
import os
import sys

import numpy as np

REPO = os.path.normpath(os.environ.get("ZMAX_ROOT") or os.path.expanduser("~/zmax"))
LIVE = os.path.join(os.environ.get("ZMAX_DATA") or os.path.join(REPO, "zmax_data"), "ss_live")
GAIN = 2.0


def _j(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    src = os.path.join(LIVE, "engine_latest.json")
    if not os.path.isfile(src):
        print("✗ 没有 %s ⇒ 引擎没在跑, 无从判定" % src)
        return 2
    d = _j(src)
    p = np.asarray(d.get("p") or [], float).ravel()
    z = np.asarray(d.get("z_latent") or [], float).ravel()
    print("快照: cycle=%s ts=%s provider=%s traj_idx=%s/%s"
          % (d.get("cycle"), d.get("ts_str"), d.get("provider"), d.get("idx"), d.get("traj_n")))
    if p.size != 4 or z.size < 3:
        print("✗ p(4 维)/z_latent(≥3 维) 缺失 ⇒ 现场版本对不上, 按代码重查, 不给结论")
        return 2

    sys.path.insert(0, os.path.join(REPO, "src"))
    from lerobot.policies.left_right.state_space.su2 import SU2Element, bounded_rotvec  # noqa: PLC0415

    e = SU2Element.from_rotvec(bounded_rotvec(z[:3], gain=GAIN))
    q = np.array([e.w, e.x, e.y, e.z], float)
    q = q / np.linalg.norm(q)
    diff = float(np.max(np.abs(q - p)))
    print("① 重算 p' = from_rotvec(bounded(z_latent[:3], gain=%.1f)): 最大差 %.2e" % (GAIN, diff))
    print("   p  = %s" % np.round(p, 6).tolist())
    print("   p' = %s   z[:3] = %s" % (np.round(q, 6).tolist(), np.round(z[:3], 6).tolist()))
    if diff <= 1e-5:
        print("   ⇒ 球上那条轨迹就是引擎导航点 p (潜表示前 3 维投影), **不是**统一状态空间 U_scene")
    else:
        print("   ⇒ 重算不等于 p: 代码已变, 以重算为准, 别沿用旧结论")

    print("② z 的诚实来源 (z_source): %s" % (d.get("z_source") or "-"))
    if "PCA" in str(d.get("z_source") or ""):
        print("   ⚠ 本拍输入是内建 PCA 回退 ⇒ 可以画, 但不能说成 'L4 视觉潜表示'")

    rep = os.path.join(REPO, "reports", "su2_state_report.json")
    if os.path.isfile(rep):
        st = (_j(rep).get("understand_last") or {}).get("state") or {}
        th = float(st.get("theta", float("nan")))
        print("③ U_scene (来自 reports/su2_state_report.json · understand_last):")
        print("   θ=%.4f rad |w|=%.4f n̂=%s bloch=%s"
              % (th, math.cos(th / 2.0), np.round(st.get("axis") or [], 3).tolist(),
                 np.round(st.get("bloch") or [], 3).tolist()))
    else:
        print("③ U_scene 不在盘上(只在 GUI 内存) ⇒ 跑 tools/ss_su2_verify.py 生成 %s" % rep)
    print("结论: 两量共用 S³ 但输入/算式不同, 报数必须带名字; 把 p 说成 U_scene = 假口径")
    return 0


if __name__ == "__main__":
    sys.exit(main())
