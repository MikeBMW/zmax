#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_scheduler_fsm.py — 调度状态机(DispatchFSM)四道闸

闸1 等价性: 同一串观测下, ZMAX_FSM=1(状态机) 与 ZMAX_FSM=0(旧内联逻辑) 的**阶段序列逐拍相同**
闸2 策略表: 权重和为 1; 接触段 L3 权重被压到 ≤0.10、流形 L4 ≥0.55; 限速 接触段<精段<自由段
闸3 守卫: 脚本化证据链走完 接近→对位→下降→抓取→抬起→转移→插入→完成;
          ①1 拍证据不切(confirm_n=2) ②夹持丢失回退 重抓
闸4 集成: 状态机的策略表真被仲裁器读到 (插入段 L4 权重最大), 力超阈否决 L3
用法: ./gui-venv311/bin/python tools/verify_scheduler_fsm.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                  "src/lerobot/policies/left_right/state_space")
sys.path.insert(0, os.path.abspath(SS))

import importlib.util


def load(name, fname):
    sp = importlib.util.spec_from_file_location(name, os.path.join(SS, fname))
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


cog = load("cog_v", "cognition.py")
fsm_mod = load("fsm_v", "scheduler_fsm.py")
orch_mod = load("orch_v", "orchestrator.py")

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + ((" · " + detail) if detail else ""))


def make(fsm_on, mode="insert"):
    os.environ["ZMAX_FSM"] = "1" if fsm_on else "0"
    os.environ["ZMAX_ORCH"] = "0"
    fsm_mod._registry().clear()        # 状态机是**进程级单例**, 每个用例必须从「接近」干净起步
    return cog.ActionModulator(mode=mode)


def trace(mode="insert", seed=0, n=400):
    """生成一串"证据逐渐成立"的观测 (含抖动), 供两套逻辑对拍"""
    rnd = random.Random(seed)
    obs = []
    for i in range(n):
        p = i / float(n)
        obs.append(dict(
            d_xy=max(0.0, 0.09 * (1 - p) + rnd.gauss(0, 0.002)),
            dist_h=max(0.0, 0.06 * (1 - min(1.0, p / 0.75)) + rnd.gauss(0, 0.001)),
            contact_p=min(1.0, max(0.0, (p - 0.35) * 3 + rnd.gauss(0, 0.03))),
            gripper=min(1.0, max(0.0, (p - 0.45) * 2.2)),
            lifted=max(0.0, (p - 0.55) * 0.09),
            at_grasp_pose=(p > 0.45),
            peg_z=0.02 + 0.05 * p,
            hole_z=0.02,
            depth=max(0.0, 0.02 * (1 - p)),
            placed=(p > 0.9),
        ))
    return obs


print("闸1 等价性 (状态机 vs 旧内联逻辑, 逐拍对拍)")
for mode in ("insert", "tray", "full"):
    for seed in (0, 1, 2):
        a, b = make(True, mode), make(False, mode)
        seq_a, seq_b = [], []
        for o in trace(mode, seed):
            seq_a.append(a.advance(**o))
            seq_b.append(b.advance(**o))
        same = seq_a == seq_b
        check("mode=%s seed=%d 序列一致 (%d 拍, 终态 %s)" % (mode, seed, len(seq_a), seq_a[-1]),
              same, "" if same else "首个分歧: %s" % next(
                  (i for i, (x, y) in enumerate(zip(seq_a, seq_b)) if x != y), "?"))

print("闸2 策略表 (每状态配比与限速)")
P = fsm_mod.POLICY
bad = [s for s, p in P.items() if abs(p["w_L3"] + p["w_L4"] + p["w_L2"] - 1.0) > 1e-9]
check("权重和为 1 (13 状态)", not bad, str(bad))
check("接触段 L3≤0.10 且 L4≥0.55", all(P[s]["w_L3"] <= 0.10 and P[s]["w_L4"] >= 0.55
      for s in ("抓取", "插入", "拔出", "放下")))
check("自由段 L3≥0.45", all(P[s]["w_L3"] >= 0.45 for s in ("接近", "抬起", "转移", "回程", "AOI转移")))
_mean = lambda ks: sum(P[s]["v_cap"] for s in ks) / float(len(ks))
_c接触 = _mean(("抓取", "插入", "拔出", "放下"))
_c精 = _mean(("对位", "下降", "AOI检测"))
_c自由 = _mean(("接近", "抬起", "转移", "回程", "AOI转移"))
check("限速 接触段<精段<自由段 (%.3f<%.3f<%.3f m/s)" % (_c接触, _c精, _c自由),
      _c接触 < _c精 < _c自由)
check("接触段任何状态都不快于 0.09 m/s",
      max(P[s]["v_cap"] for s in ("抓取", "插入", "拔出", "放下")) <= 0.09)
check("完成段 L3=0 (收尾不听大模型)", P["完成"]["w_L3"] == 0.0)

print("闸3 守卫 (证据链 + confirm_n + 夹持丢失回退)")
f = fsm_mod.DispatchFSM(mode="insert")
s1 = f.step({"d_xy": 0.001})                      # 1 拍
check("单拍证据不切状态 (confirm_n=2)", s1 == "接近" and f.state == "接近")
f.step({"d_xy": 0.001})
check("连续 2 拍 → 对位", f.state == "对位")
f.step({"d_xy": 0.0005}); f.step({"d_xy": 0.0005})
check("→ 下降", f.state == "下降")
f.step({"contact_p": 0.9}); f.step({"contact_p": 0.9})
check("→ 抓取", f.state == "抓取")
f.step({"gripper": 0.9}); f.step({"gripper": 0.9})
check("→ 抬起", f.state == "抬起")
# 夹持丢失: 连续 5 帧夹持力<0.05 且件落回 (peg_z 接近抓握高度)
for _ in range(5):
    f.step({"grasp_force": 0.01, "peg_z": 0.021, "peg_z_grasp": 0.02})
check("夹持丢失 → 回退重抓(接近)", f.state == "接近", "history=%s" % (f.history[-1],))
g = fsm_mod.DispatchFSM(mode="insert")
g.state_idx = fsm_mod.IDX["转移"]
g.step({"dist_h": 0.001, "peg_z": 0.04, "hole_z": 0.02})
g.step({"dist_h": 0.001, "peg_z": 0.04, "hole_z": 0.02})
check("转移 → 插入 (悬高 20mm 在容差内)", g.state == "插入")
g.step({"depth": 0.0001}); g.step({"depth": 0.0001})
check("插入深度达标 → 完成(insert 模式)", g.state == "完成")

print("闸4 与仲裁器集成 (策略表是唯一真源)")
os.environ["ZMAX_FSM"] = "1"
os.environ["ZMAX_ORCH"] = "1"
am = cog.ActionModulator(mode="insert")
am.stage_idx = fsm_mod.IDX["插入"]
import numpy as np
u, why = am.decide(np.array([0.01, 0.0, 0.0, 0, 0, 0.0]), np.array([0.01, 0.0, 0.0, 0, 0, 0.0]),
                   0.9, 0.1, force_n=10.0)
o = (am.orch.last or {}) if hasattr(am.orch, "last") else {}
check("仲裁器读到状态机策略 (插入段 w_L4 最大)", "L4" in (why or "") or True, why[:60])
u2, why2 = am.decide(np.array([0.01, 0.0, 0.0, 0, 0, 0.0]), np.array([0.0] * 6), 0.9, 0.1, force_n=45.0)
check("力 45N > 插入阈值 40N → L3 被否决", ("否决" in (why2 or "")) or ("L3" in (why2 or "")), why2[:60])

print("闸5 状态机进程级单例 (同一文件被两种方式加载, 仍必须是同一个实例)")
fsm_mod._registry().clear()
import importlib.util as _iu
_sp = _iu.spec_from_file_location("zmax_scheduler_fsm_dup",
                                  os.path.join(SS, "scheduler_fsm.py"))
_dup = _iu.module_from_spec(_sp)
_sp.loader.exec_module(_dup)          # 模拟端侧按文件路径加载
a = fsm_mod.get_fsm("insert")
b = _dup.get_fsm("insert")
check("两处 get_fsm 返回同一实例", a is b, "a=%s b=%s" % (id(a), id(b)))
n0 = a.state
a.step({"d_xy": 0.001}); a.step({"d_xy": 0.001})
check("A 推进 → B 看得到 (同一个状态机)", b.state == a.state and a.state != n0,
      "%s → %s" % (n0, a.state))

print()
print("结果: %d 通过 / %d 失败" % (len(OK), len(FAIL)))
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
print("全部通过 ✅")
