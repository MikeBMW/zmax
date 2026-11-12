#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_su2_layers.py — 「统一状态空间」出口与自适应权重/预测先行的判据 (2026-11-12)

验五件事 (每件给数, 不给结论):
  A 出口去重: out1(kind=obs43) 与 out2(kind=su2_layers) 不再逐字段相等, out2 带四层明细
  B 零回归: 四层权重全 1 时, 加权场景 θ 与旧 compose_scene 逐位相同 (差 = 0)
  C 权重自适应三档: L5 新鲜/半衰/过期/缺失 四态 → 权重 1 / 0.5 / 0 / 0, 且场景 θ 随之变
  D 预测先行: 平稳推进段残差小, 阶段突变拍残差跳高 (同一序列内同口径)
  E 剥离自洽: 加权后逐层剥离残余 ≈ 0 (群运算仍闭合)

跑法: cd ~/zmax && gui-venv311/bin/python tools/verify_su2_layers.py
"""
import json
import os
import sys

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from lerobot.policies.left_right.state_space import su2 as S            # noqa: E402
from lerobot.middleware.nodes.impl.ss_obs import node_ss_su2, compute_layer_weights  # noqa: E402
from lerobot.middleware.nodes.impl.shared_runtime import _SS_STATE      # noqa: E402

OK = []


def chk(name, cond, detail):
    OK.append((name, bool(cond), detail))
    print(("[PASS] " if cond else "[FAIL] ") + name + " · " + detail)


class FakeMod:
    """给节点喂"引擎轨迹帧": _ss_tr 每个键是逐拍序列, _ss_round 是当前拍"""
    _trace_nodes = False          # 关键: 否则 execute_node_logic 会逐行 trace (假失败)

    def __init__(self, tr):
        self._ss_tr = tr
        self._ss_round = 0


def obs43(peg, hole=(-0.28, 0.684, 0.129)):
    o = [0.0] * 43
    o[0:3] = [0.005, 0.601, 0.195]
    o[3] = 1.0
    o[4:7] = list(peg)
    o[36:39] = list(hole)
    o[39:43] = [0.0, 0.31, 0.89, -0.22]
    return o


def main():
    N = 14
    prog = [i / (N - 1.0) for i in range(N)]
    u_sat = [0.10] * N
    contact = [0.10 + 0.05 * i for i in range(N)]   # 0.10→0.75, 全程不饱和 (饱和会被一阶预测判成事件)
    dperp = [0.002] * N
    dperp[10] = 0.030          # 第 11 拍: 阶段突变 (法向偏离突然变大)
    tr = {"t": list(range(N)), "mani_progress": prog, "mani_dperp": dperp,
          "mani_rem": [max(0.0, 0.02 - 0.0015 * i) for i in range(N)],
          "mani_eta": [0.1 + 0.02 * i for i in range(N)],
          "u_sat": u_sat, "contact_p": contact}
    mod = FakeMod(tr)

    # ───────────── A/B/E: 出口 + 零回归 + 剥离 ─────────────
    # 固定一份 obs43 缓存 ⇒ L2 每拍同一份观测, 只有 L3/L4 随引擎帧变化 (可归因)
    _SS_STATE["obs43"] = obs43((0.10, 0.51, 0.03))
    _SS_STATE["obs43_src"] = "verify:fixture"
    o = node_ss_su2({"log": lambda m: None, "module": mod, "demo_light": True})
    o1, o2, o3 = o["out1"], o["out2"], o["out3"]
    chk("A1 out1 仍是 43D 观测体", o1["kind"] == "obs43" and o1["dim"] == 43,
        "kind=%s dim=%s same_frame_as_L2=%s" % (o1["kind"], o1["dim"], o1.get("same_frame_as_L2")))
    chk("A2 out2 改为分层结构体 (不再复制 43D)",
        o2["kind"] == "su2_layers" and set(o2["layers"]) == {"L2", "L3", "L4", "L5"} and o1 != o2,
        "kind=%s 层=%s out1==out2? %s" % (o2["kind"], list(o2["layers"]), o1 == o2))
    chk("A3 out2 每层带 θ/方向/可观测/权重/贡献",
        all(k in o2["layers"]["L2"] for k in ("theta", "axis", "visibility", "weight", "contribution")),
        "L2=%s" % json.dumps(o2["layers"]["L2"], ensure_ascii=False))
    chk("A4 out1 与 out2 一起带权重与判读",
        "weights" in o2 and "weights" in o3 and "predict" in o3,
        "权重=%s" % o2["weights"])

    frame = {k: tr[k][0] for k in ("mani_progress", "mani_dperp", "mani_rem", "mani_eta", "u_sat", "contact_p")}
    layers = S.encode_layers(frame, obs43((0.10, 0.51, 0.03)))
    sc0 = S.compose_scene(layers)
    sc1, lw = S.scene_with_weights(layers, {"L2": 1, "L3": 1, "L4": 1, "L5": 1})
    chk("B1 零回归: 全权重 1 == 旧 compose", abs(sc1.theta() - sc0.theta()) < 1e-12 and
        abs(sc1.visibility() - sc0.visibility()) < 1e-12,
        "θ 差=%.2e |w| 差=%.2e" % (abs(sc1.theta() - sc0.theta()), abs(sc1.visibility() - sc0.visibility())))
    peel = S.peel_layers(lw, sc1)
    chk("E1 加权后剥离残余 ≈ 0 (float 累加, 非结构误差)", peel["_residual"]["theta"] < 1e-6,
        "残余 θ=%.2e rad (= %.2e 度)" % (peel["_residual"]["theta"],
                                         __import__("math").degrees(peel["_residual"]["theta"])))

    # ───────────── C: 权重自适应三档 (L5 新鲜/半衰/过期/缺失) ─────────────
    w_fresh, r_fresh = compute_layer_weights(frame, obs43((0.1, 0.51, 0.03)), {"age_s": 0.0})
    w_half, _ = compute_layer_weights(frame, obs43((0.1, 0.51, 0.03)), {"age_s": 30.0})
    w_stale, _ = compute_layer_weights(frame, obs43((0.1, 0.51, 0.03)), {"age_s": 120.0})
    w_none, _ = compute_layer_weights(frame, obs43((0.1, 0.51, 0.03)), None)
    chk("C1 L5 四态权重 1 / 0.5 / 0 / 0",
        (w_fresh["L5"], w_half["L5"], w_stale["L5"], w_none["L5"]) == (1.0, 0.5, 0.0, 0.0),
        "新鲜=%s 半衰(30s)=%s 过期(120s)=%s 缺失=%s" %
        (w_fresh["L5"], w_half["L5"], w_stale["L5"], w_none["L5"]))
    # L5 有意图时, 权重 0 → 1 必须改变场景 θ (否则权重是摆设)
    fr5 = dict(frame, L5_intent=[0.3, -0.2, 0.9])
    L5l = S.encode_layers(fr5, obs43((0.1, 0.51, 0.03)))
    s_w0, _ = S.scene_with_weights(L5l, {"L2": 1, "L3": 1, "L4": 1, "L5": 0.0})
    s_w1, _ = S.scene_with_weights(L5l, {"L2": 1, "L3": 1, "L4": 1, "L5": 1.0})
    chk("C2 L5 权重 0→1 真的改场景 (权重不是摆设)",
        abs(s_w1.theta() - s_w0.theta()) > 1e-6,
        "θ %.4f (w=0) → %.4f (w=1) · Δ=%.4f" % (s_w0.theta(), s_w1.theta(), abs(s_w1.theta() - s_w0.theta())))

    # ───────────── D: 预测先行 —— 同一序列里平稳段 vs 突变拍 ─────────────
    rows = []
    for i in range(N):
        mod._ss_round = i
        oo = node_ss_su2({"log": lambda m: None, "module": mod, "demo_light": True})
        rows.append((i, oo["out3"]["predict"]["residual_deg"], oo["out2"]["layers"]))
    resid = [r[1] for r in rows]
    steady = [x for x in resid[2:10] if x is not None]
    jump = resid[10] if len(resid) > 10 else None
    chk("D1 平稳段预测残差小", len(steady) > 0 and max(steady) < 5.0,
        "第 3~10 拍残差=%s" % [None if x is None else round(x, 2) for x in resid[2:10]])
    chk("D2 突变拍残差跳高 (事件信号真的能出)",
        jump is not None and steady and jump > max(steady) * 2,
        "第 11 拍(法向偏离突变) 残差=%s vs 平稳最大 %s" %
        (None if jump is None else round(jump, 2), None if not steady else round(max(steady), 2)))
    chk("D3 预测只读: 出口没有任何下发字段", not any(
        k in json.dumps(o["out3"]) for k in ("u_exec", "move_pose", "cmd", "action")),
        "out3 键=%s" % list(o["out3"]))

    n_fail = sum(1 for _, ok, _ in OK if not ok)
    print("\n==== 汇总: %d/%d PASS, %d FAIL ====" % (len(OK) - n_fail, len(OK), n_fail))
    out = os.path.join(ROOT, "reports", "su2_layers_verify.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"n": len(OK), "n_fail": n_fail,
               "items": [{"name": n, "pass": p, "detail": d} for n, p, d in OK]},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("报告: " + out)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
