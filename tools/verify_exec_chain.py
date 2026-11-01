#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_exec_chain.py — 画布执行链顺序判据 (真源回读, 只读不改)

老倪 2026-11-01 定序:
    规划引导 → 动作调制 → 安全执行 → 技能 → 运动规划 → 动作执行器 → 机器人执行器

判据:
  ① 主链 6 段连线全部存在且端口正确 (geoplan→sssched→sslimit→sssk→n_moveit→n_exec→ssact)
  ② 8 个技能一一对应进 运动规划 in4..in11 (不是 in1/in2)
  ③ 安全执行 out1 → 8 个技能 in1 (端口统一, 不能 sssk1 走 in2)
  ④ 安全执行 out3 (单步/向下限) → 运动规划 in2 (不是 in1: in1 是目标点)
  ⑤ 没有"跳过安全执行/动作调制"的短路: 技能的上游只能是 sslimit
  ⑥ 三份节点文件头写的执行链与本判据同口径
  ⑦ 画布真源与 flows/ 符号链接指向同一份 (别改到副本上)
"""
import json
import os
import sys

ROOT = "/home/ubuntu/zmax"
CANVAS = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
CHAIN = "规划引导 → 动作调制 → 安全执行 → 技能 → 运动规划 → 动作执行器 → 机器人执行器"
ROWS = []


def ck(tag, name, ok, detail=""):
    ROWS.append((tag, ok, name, detail))
    print(("  ✅ " if ok else "  ❌ ") + "%s %s — %s" % (tag, name, detail))


def main() -> int:
    d = json.load(open(CANVAS, encoding="utf-8"))
    L = d["links"]

    def has(f, fp, t, tp):
        return any(e["f"] == f and e["f_port"] == fp and e["t"] == t and e["t_port"] == tp for e in L)

    pair = [("n_geoplan", "out2", "sssched", "in9"),
            ("sssched", "out1", "sslimit", "in1"),
            ("sslimit", "out1", "sssk1", "in1"),
            ("sssk1", "out1", "n_moveit", "in4"),
            ("n_moveit", "out1", "n_exec", "in1"),
            ("n_exec", "out1", "ssact", "in1")]
    bad = ["%s.%s→%s.%s" % p for p in pair if not has(*p)]
    ck("①", "主链 6 段端口全对", not bad, "缺/错: %s" % (bad or "无"))

    bad2 = []
    for i in range(1, 9):
        if not has("sssk%d" % i, "out1", "n_moveit", "in%d" % (i + 3)):
            bad2.append(i)
    ck("②", "8 技能 → 运动规划 in4..in11", not bad2, "缺: %s" % (bad2 or "无"))

    bad3 = []
    for i in range(1, 9):
        srcs = [e for e in L if e["t"] == "sssk%d" % i and e["f"] == "sslimit"]
        if not any(e["f_port"] == "out1" and e["t_port"] == "in1" for e in srcs):
            bad3.append(i)
    ck("③", "安全执行 out1 → 8 技能 in1", not bad3, "端口不统一: %s" % (bad3 or "无"))

    ok4 = has("sslimit", "out3", "n_moveit", "in2") and not any(
        e["f"] == "sslimit" and e["f_port"] == "out3" and e["t"] == "n_moveit" and e["t_port"] == "in1" for e in L)
    ck("④", "安全约束 out3 → 运动规划 in2", ok4, "out3 目标端口应为 in2 (in1 是目标点)")

    # ⑤ 一个口一个上游: in1 只接安全执行(动作), in2 只接 L3 编排(这一段跑什么)
    bad5 = []
    for i in range(1, 9):
        t = "sssk%d" % i
        ups1 = {e["f"] for e in L if e["t"] == t and e["t_port"] == "in1"}
        ups2 = {e["f"] for e in L if e["t"] == t and e["t_port"] == "in2"}
        if ups1 != {"sslimit"}:
            bad5.append("%s.in1←%s(应仅 sslimit)" % (t, sorted(ups1)))
        if ups2 != {"ssskill"}:
            bad5.append("%s.in2←%s(应仅 ssskill)" % (t, sorted(ups2)))
    ck("⑤", "技能 in1←安全执行·in2←L3编排 (一□一上游)", not bad5, "%s" % (bad5 or "无"))

    files = ["robot_actuator_impl.py", "exec_dispatch_impl.py", "safety_limit_impl.py"]
    miss = []
    for f in files:
        p = os.path.join(ROOT, "src/lerobot/engineering/nodes", f)
        if CHAIN not in open(p, encoding="utf-8").read():
            miss.append(f)
    ck("⑥", "节点文件头执行链同口径", not miss, "未同步: %s" % (miss or "无"))

    real = os.path.realpath(os.path.join(ROOT, "flows/state_space_obs.json"))
    ok7 = os.path.realpath(CANVAS) == real
    ck("⑦", "flows 链接指向同一份真源", ok7, "realpath=%s" % real.replace(ROOT, "<repo>"))

    npass = sum(1 for r in ROWS if r[1])
    print("\n执行链: " + CHAIN)
    print("判据: PASS %d / FAIL %d" % (npass, len(ROWS) - npass))
    return 0 if npass == len(ROWS) else 1


if __name__ == "__main__":
    sys.exit(main())
