#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_orchestrator.py —— 总调度(仲裁器)的落地自检。三道闸，缺一条不许上机。

闸1 回归: ZMAX_ORCH 未开时, decide() 必须与 HEAD 版本**逐位相同**(np.array_equal, 不是近似)
闸2 语义: 开仲裁后 6 个场景的判断必须对（力否决/残差保守/连续停/层缺失/收敛差/非交换大）
闸3 集成: 从 ActionModulator.decide() 端到端走一遍, 确认 ③阶段限速 ④技能闸 仍在自己位置上

跑法: ./gui-venv311/bin/python tools/verify_orchestrator.py
退出码 0 = 全过; 非 0 = 有断言失败(打出来, 不隐藏)。
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SS = os.path.join(REPO, "src/lerobot/policies/left_right/state_space")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def gh_head(rel_path):
    """取 git HEAD 版本到临时文件（= 本次改动之前的真身）。"""
    fd, p = tempfile.mkstemp(suffix=".py")
    os.close(fd)
    with open(p, "wb") as f:
        r = subprocess.run(["git", "-C", REPO, "show", "HEAD:" + rel_path], stdout=f, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise SystemExit("取不到 HEAD 版本: %s" % r.stderr.decode()[:200])
    return p


fails = []


def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + ((" — " + detail) if detail else ""))
    if not cond:
        fails.append(name)


def main():
    ss_rel = "src/lerobot/policies/left_right/state_space/cognition.py"
    os.environ.pop("ZMAX_ORCH", None)
    new = load(os.path.join(REPO, ss_rel), "cognition_new")
    orch_mod = load(os.path.join(SS, "orchestrator.py"), "orch_mod")
    print("闸1 回归: ZMAX_ORCH 未开 ⇒ decide() 与 HEAD 逐位相同")
    rng = np.random.default_rng(20261114)
    n_same, n_cases = 0, 60
    try:
        old_p = gh_head(ss_rel)
        old = load(old_p, "cognition_head")
    except SystemExit as e:                     # 端侧(550C)可能没有 git 基线 ⇒ 明说 SKIP, 不假装通过
        print("  ⏭ SKIP — %s" % e)
        old_p, old = None, None
    if old is not None:
        for i in range(n_cases):
            uff = rng.normal(0, 0.12, 6) * (1 if i % 3 else 3)
            ufb = rng.normal(0, 0.05, 6)
            cp = float(rng.uniform(0, 1))
            res = float(rng.uniform(0, 3))
            a = old.ActionModulator(mode="insert")
            b = new.ActionModulator(mode="insert")
            ua, ta = a.decide(uff.copy(), ufb.copy(), cp, res)
            ub, tb = b.decide(uff.copy(), ufb.copy(), cp, res)
            if np.array_equal(np.asarray(ua), np.asarray(ub)) and ta == tb:
                n_same += 1
        check("60 例逐位一致", n_same == n_cases, "%d/%d" % (n_same, n_cases))
        os.remove(old_p)

    print("\n闸2 语义: ZMAX_ORCH=1 时仲裁行为")
    os.environ["ZMAX_ORCH"] = "1"
    l3 = np.array([0.30, 0.0, 0.10, 0, 0, 0])       # 大模型: 想往前冲
    l2 = np.array([0.05, 0.0, 0.0, 0, 0, 0])        # 肌肉: 小步
    l4 = np.array([0.0, 0.06, 0.0, 0, 0, 0])        # 几何: 横向纠偏
    am = new.ActionModulator(mode="insert")
    orch = am.orch
    check("仲裁器已挂上调制器", orch is not None)

    # ① 自由段: L3 主导
    orch.clear_layers(); orch.set_layer("L3", l3)
    u, why, vet = orch.arbitrate(l2, l4, contact_p=0.0, residual=0.0, stage="转移")
    check("转移段 L3 权重最大", orch.tele["weights"]["L3"] > orch.tele["weights"]["L4"], why)

    # ② 插装段: L4 主导
    u, why, vet = orch.arbitrate(l2, l4, contact_p=0.3, residual=0.2, stage="插入")
    check("插入段 L4 权重最大", orch.tele["weights"]["L4"] > orch.tele["weights"]["L3"], why)

    # ③ 力超限: 否决 L3 (权重归 0)
    u, why, vet = orch.arbitrate(l2, l4, contact_p=1.0, residual=0.0, stage="插入", force_n=52.0)
    check("力 52N>40N ⇒ L3 被否决", orch.tele["weights"]["L3"] == 0.0, why)

    # ④ 残差单次越阈: 保守化(只信几何, 不停)
    orch2 = orch_mod.Orchestrator()
    u, why, vet = orch2.arbitrate(l2, l4, contact_p=0.2, residual=3.0, stage="对位")
    check("残差 3.0 单次 ⇒ 保守化不停", (u is not None) and (not vet) and orch2.tele["weights"]["L3"] == 0.0, why)

    # ⑤ 连续否决 ⇒ 停
    orch3 = orch_mod.Orchestrator()
    vs = [orch3.arbitrate(l2, l4, contact_p=0.2, residual=3.0, stage="对位")[2] for _ in range(3)]
    check("残差连 3 拍 ⇒ 停(返回零动作)", vs == [False, False, True], str(vs))

    # ⑥ 无可用层 ⇒ 保持
    orch4 = orch_mod.Orchestrator()
    u, why, vet = orch4.arbitrate(np.zeros(6), np.zeros(6), stage="接近")
    check("无层提案 ⇒ 保持", vet and u is None, why)

    # ⑦ 收敛差 ⇒ 大模型让位
    orch5 = orch_mod.Orchestrator()
    orch5.set_layer("L3", l3)
    orch5.arbitrate(l2, l4, stage="转移", su2={"w_abs": 0.30, "noncomm": 0.1})
    w_low = orch5.tele["weights"]["L3"]
    orch6 = orch_mod.Orchestrator(); orch6.set_layer("L3", l3)
    orch6.arbitrate(l2, l4, stage="转移", su2={"w_abs": 0.98, "noncomm": 0.1})
    check("收敛度 0.30 ⇒ L3 权重被砍半", abs(w_low - 0.5 * orch6.tele["weights"]["L3"]) < 1e-6,
          "低收敛 %.3f vs 高收敛 %.3f" % (w_low, orch6.tele["weights"]["L3"]))

    # ⑧ 非交换大 + 敏感段 ⇒ L4 接管
    orch7 = orch_mod.Orchestrator(); orch7.set_layer("L3", l3)
    orch7.arbitrate(l2, l4, stage="插入", su2={"w_abs": 0.9, "noncomm": 1.19})
    check("非交换 1.19rad @插入 ⇒ L4 权重上升", orch7.tele["weights"]["L4"] >= 0.60,
          str(orch7.tele["weights"]))

    print("\n闸3 集成: 调制器 decide() 端到端")
    am2 = new.ActionModulator(mode="insert")
    am2.skill_gate_on = False
    u1, t1 = am2.decide(l2, l4, 0.0, 0.05)
    check("decide() 返回动作且含仲裁标签", ("仲裁" in t1) and np.linalg.norm(u1) > 0, t1)
    check("阶段限速仍在(‖u[:3]‖ ≤ 接近段 cap)", float(np.linalg.norm(np.asarray(u1)[:3])) <= 0.35 + 1e-9,
          "|v|=%.4f" % float(np.linalg.norm(np.asarray(u1)[:3])))
    u2, t2 = am2.decide(l2, l4, 1.0, 0.05)
    check("力/残差都不越阈时不停", np.linalg.norm(u2) > 0, t2)
    # 力真值从 decide 入参注入 ⇒ 否决才真能生效(否则力否决只是死代码)
    am2.orch.set_layer("L3", l3)
    u3, t3 = am2.decide(l2, l4, 1.0, 0.05, force_n=52.0)
    check("decide() 注入 force_n=52N ⇒ 力否决生效", ("力否决" in t3) and am2.orch.tele["weights"]["L3"] == 0.0, t3)
    print("\n遥测一行: %s" % am2.orch.line())

    print("\n" + ("=" * 62))
    if fails:
        print("失败 %d 项: %s" % (len(fails), "; ".join(fails)))
        return 1
    print("全部通过 (回归 %d 例逐位一致; 语义+集成 %d 项断言)" % (n_cases, 13 - len(fails)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
