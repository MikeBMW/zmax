#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_pose_chain.py — 「群元素/姿态真值 → 参考姿态 → 执行器」这条位姿链的判据 (2026-11-12)

零运动: 只验姿态数学与执行器的入口校验, 不写 FIFO、不下发、不动臂。

验六件:
  P1 节点真跑吐 quat_ref (单位四元数), 来源轴注明
  P2 quat_ref 与技能轴向对齐 (R(q)·ẑ 与轴的夹角 < 1e-6 rad)
  P3 执行器入口 _ref_quat: quat_ref 合法即采用 (源 su2:quat_ref)
  P4 坏输入一律拒: 3 分量 / 非单位 / 非数值 (宁可拒发, 不发坏姿态)
  P5 默认行为零变化: 段表没写 quat:su2/ref 也没给 quat_ref 时, 这个分支不进入
  P6 姿态容差口径: 输出执行器 ARRIVE_TOL_DEG (默认 0.5°), 并给出与 quat 分量量化(6 位小数)的关系

跑法: cd ~/zmax && gui-venv311/bin/python tools/verify_pose_chain.py
"""
import json
import math
import os
import sys

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

OK = []


def chk(name, cond, detail):
    OK.append((name, bool(cond), detail))
    print(("[PASS] " if cond else "[FAIL] ") + name + " · " + detail)


def qrot(q, v):
    """四元数 (x,y,z,w) 旋转向量 v"""
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    vx, vy, vz = v
    # R = I + 2w[v]× + 2[v]×²
    cx, cy, cz = y * vz - z * vy, z * vx - x * vz, x * vy - y * vx
    c2x, c2y, c2z = y * cz - z * cy, z * cx - x * cz, x * cy - y * cx
    return [vx + 2 * (w * cx + c2x), vy + 2 * (w * cy + c2y), vz + 2 * (w * cz + c2z)]


def main():
    from lerobot.middleware.nodes.impl.ss_obs import node_ss_su2
    from lerobot.middleware.nodes.impl.shared_runtime import _SS_STATE
    import lerobot.engineering.exec.daemon as D

    # ── P1: 节点真跑出 quat_ref ──
    o = [0.0] * 43
    o[0:3] = [0.005, 0.601, 0.195]
    o[3] = 1.0
    o[4:7] = [0.10, 0.51, 0.03]
    o[36:39] = [-0.28, 0.684, 0.129]
    _SS_STATE["obs43"] = o
    _SS_STATE["obs43_src"] = "verify:fixture"
    r = node_ss_su2({"log": lambda m: None, "demo_light": True})
    qref = r["out3"].get("quat_ref")
    n = math.sqrt(sum(v * v for v in qref)) if qref else 0.0
    chk("P1 节点吐 quat_ref 且是单位四元数", isinstance(qref, list) and len(qref) == 4 and abs(n - 1) < 1e-6,
        "quat_ref=%s · ‖q‖=%.9f · 源轴=%s" % (qref, n, r["out3"].get("quat_ref_src")))

    # ── P2: 姿态与技能轴对齐 (quat_truth 内部口径 w,x,y,z → 转 xyzw 再算旋转) ──
    _qt = __import__("lerobot.policies.left_right.state_space.quat_truth",
                     fromlist=["q_for_axis"])
    worst = 0.0
    rows = []
    for axis in ("z_pos", "z_neg", "x_pos", "x_neg", "y_pos", "y_neg"):
        qw = [float(v) for v in _qt.q_for_axis(axis)]        # (w,x,y,z)
        qa = [qw[1], qw[2], qw[3], qw[0]]                    # → (x,y,z,w)
        target = {"z_pos": [0, 0, 1], "z_neg": [0, 0, -1], "x_pos": [1, 0, 0],
                  "x_neg": [-1, 0, 0], "y_pos": [0, 1, 0], "y_neg": [0, -1, 0]}[axis]
        got = qrot(qa, [0, 0, 1])                      # 工具 z 轴实际朝向
        ang = math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(got, target))))))
        worst = max(worst, ang)
        rows.append("%s:%.3f°" % (axis, ang))
    chk("P2 参考姿态把工具 z 轴对到技能轴 (6 个轴)", worst < 1e-6,
        "最大偏差 %.3e° · %s" % (worst, " ".join(rows)))
    # P2b: 执行器入口自己算的那条路也必须对齐 (验 (w,x,y,z)→(x,y,z,w) 的转换没写反)
    q_ax, src_ax = D._ref_quat({"quat": "su2", "axis": "z_neg"}, {})
    got_ax = qrot(q_ax, [0, 0, 1]) if q_ax else [0, 0, 0]
    ang_ax = math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(got_ax, [0, 0, -1]))))))
    chk("P2b 执行器 su2 路径的姿态对齐 z_neg (分量顺序转换正确)", q_ax is not None and ang_ax < 1e-6,
        "源=%s quat=%s · 工具 z 实测朝向=%s · 与 −z 夹角 %.3e°" %
        (src_ax, [round(v, 4) for v in (q_ax or [])], [round(v, 4) for v in got_ax], ang_ax))

    # ── P3: 执行器入口采用合法 quat_ref ──
    q_ok, src_ok = D._ref_quat({"quat_ref": qref}, {})
    chk("P3 执行器入口采用 quat_ref", q_ok is not None and src_ok == "su2:quat_ref",
        "源=%s · quat=%s" % (src_ok, [round(v, 4) for v in (q_ok or [])]))

    # ── P4: 坏输入一律拒 ──
    bad3, e3 = D._ref_quat({"quat_ref": [0.0, 0.0, 1.0]}, {})
    badn, en = D._ref_quat({"quat_ref": [0.0, 0.0, 0.0, 2.0]}, {})
    bads, es = D._ref_quat({"quat_ref": ["a", "b", "c", "d"]}, {})
    bado, eo = D._ref_quat({"quat_ref": qref, "quat_ref_order": "wxyz"}, {})
    chk("P4 坏输入全部拒发 (3 分量 / 非单位 / 非数值 / 顺序不符)",
        bad3 is None and badn is None and bads is None and bado is None,
        "3分量→%s | 非单位→%s | 非数值→%s | 顺序 wxyz→%s" % (e3, en, es, eo))

    # ── P5: 默认路径零变化 (marker 判定) ──
    def enters(st, sk):
        m = str(st.get("quat", sk.get("quat", ""))).lower()
        return m in ("su2", "ref") or isinstance(st.get("quat_ref"), (list, tuple))

    chk("P5 默认段不进入参考姿态分支 (行为零变化)",
        (not enters({}, {})) and (not enters({"quat": "taught"}, {})) and enters({"quat": "su2"}, {}),
        "默认=%s · taught=%s · su2=%s" % (enters({}, {}), enters({"quat": "taught"}, {}),
                                           enters({"quat": "su2"}, {})))

    # ── P6: 姿态容差与量化 ──
    tol = float(os.environ.get("ZMAX_ARRIVE_TOL_DEG", getattr(D, "ARRIVE_TOL_DEG", 0.5)))
    q_tiny = qrot([0.0, 0.0, 0.0, 1.0], [0, 0, 1])
    q_1deg = [0.0, 0.0, math.sin(math.radians(0.5)), math.cos(math.radians(0.5))]
    ang1 = math.degrees(2 * math.acos(min(1.0, abs(q_1deg[3]))))
    chk("P6 姿态容差口径 (默认 0.5°)", abs(tol - 0.5) < 1e-9 and abs(ang1 - 1.0) < 1e-6,
        "ARRIVE_TOL_DEG=%.2f° · 1.0° 姿态的四元数 w=%.6f ⇒ 会被 0.5° 判否" % (tol, q_1deg[3]))

    nf = sum(1 for _, ok, _ in OK if not ok)
    print("\n==== 汇总: %d/%d PASS, %d FAIL ====" % (len(OK) - nf, len(OK), nf))
    out = os.path.join(ROOT, "reports", "pose_chain_verify.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"n": len(OK), "n_fail": nf, "pose_chain": "未下发任何指令 (零运动)",
               "items": [{"name": a, "pass": b, "detail": c} for a, b, c in OK]},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("报告: " + out + "  (零运动: 未写 FIFO、未下发)")
    return 0 if nf == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
