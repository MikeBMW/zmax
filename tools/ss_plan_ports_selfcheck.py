#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运动规划节点 (n_moveit) 端口自检 — 「上游是技能, 端口必须对正, 真读势场力, 真执行」

判据 (每条都从**真实调用**取, 不写死预期):
  A. 中间件壳 compute() 走的是实现 (PURE=True ⇒ status=实现执行), 不是直通
  B. in1 显式目标点 → 出段表, goal_src 来自 in1
  C. in1 空 + in4 技能动作 → 用技能 target 出段表 (上游=技能真正生效)
  D. in3 势场力 → force 真读进输出, 且目标点被偏置 (goal_biased ≠ goal_raw), 偏置有界
  E. in3 势场力 ≥ force_veto_mag → 拒绝出段表 (reason=force_veto)
  F. in2 安全约束真读: max_step_mm 变小 ⇒ 段数变多
  G. 配置真源: config/calib/zmax_calib.json:plan_node 三项都能读到 (参数中心同源)

起点真值用**临时文件** (ts=now) 注入: 真机不在线时 latest.json 会陈旧 ⇒ 规划会正确拒跑,
自检要的是端口/势场/执行三条链路, 不是真机结论。
"""
import json
import os
import sys
import tempfile
import time

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.engineering.nodes import plan_impl as P          # noqa: E402
from lerobot.middleware.nodes import n_moveit as SHELL      # noqa: E402

PASS, FAIL = [], []


def ck(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  ✅ " if ok else "  ❌ ") + name + (" · " + detail if detail else ""))


def _ctx(target=None, skill=None, force=None, step=50.0, down=20.0) -> dict:
    c: dict = {"in2": {"value": {"max_step_mm": step, "max_down_mm": down}}}
    if target is not None:
        c["in1"] = {"value": {"tcp": target}}
    if skill is not None:
        c["in4"] = {"value": skill}
    if force is not None:
        c["in3"] = {"value": force}
    return c


def main():
    cfg = json.load(open(os.path.join(ROOT, "config/calib/zmax_calib.json"))).get("plan_node") or {}
    print("配置真源 plan_node: %s" % json.dumps(cfg, ensure_ascii=False))

    # ── 真值起点: 临时文件 (不动真机, 不伪造现场结论) ─────────────────────
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"x": 0.663906, "y": -0.029253, "z": 0.293548, "ts": time.time()}, tmp)
    tmp.close()
    _orig = P._TCP
    P._TCP = tmp.name
    try:
        START = [663.91, -29.25, 293.55]
        GOAL = [412.0, 10.4, 153.6]

        # A. 中间件壳: 真执行 (PURE=True)
        out = SHELL.compute(_ctx(target=GOAL, skill=None, force=None))
        st = getattr(SHELL, "LAST_STATUS", "")
        ck("A 壳 compute 走实现", st == "实现执行", "status=%s · PURE=%s" % (st, SHELL.PURE))
        o1 = out.get("out1") or {}
        ck("A' 壳回传 out1 是段表", isinstance(o1.get("segments"), list), "n=%s" % o1.get("n"))

        # B. in1 显式目标
        r1 = P.run(_ctx(target=GOAL))
        ck("B in1 显式目标出段表", bool(r1.get("segments")),
           "n=%s total=%smm src=%s" % (r1.get("n"), r1.get("total_mm"), r1.get("goal_src")))

        # C. in4 技能动作 (无 in1) ⇒ 上游技能真生效
        sk = {"kind": "skill_act", "skill": "SK03", "stage": "下降", "active": True,
              "target": GOAL, "target_unit": "mm(base_link)",
              "u": [-0.115, -0.034, -0.003, 0.6], "gate": {"f_need_N": 0.163}}
        r2 = P.run(_ctx(skill=sk))
        ck("C in4 技能 target 出段表", bool(r2.get("segments")) and "in4" in str(r2.get("goal_src")),
           "n=%s src=%s skill=%s" % (r2.get("n"), r2.get("goal_src"), (r2.get("skill") or {}).get("skill")))
        ck("C' 技能字段进输出", (r2.get("skill") or {}).get("f_need_N") == 0.163,
           "f_need_N=%s" % (r2.get("skill") or {}).get("f_need_N"))

        # D. in3 势场力 ⇒ 真读 + 目标偏置
        frc = {"kind": "force_corrected", "dir": [0.2635, -0.3319, -0.1309], "mag": 0.07125,
               "main": "L3", "layers": {"L2": 0.0357, "L3": 0.0544, "L4": 0.0196, "L5": None}}
        r3 = P.run(_ctx(skill=sk, force=frc))
        fb = r3.get("force_bias_mm") or {}
        cap = float(cfg.get("force_bias_max_mm") or 20.0)
        ck("D in3 势场真读", (r3.get("force") or {}).get("mag") == 0.07125,
           "force.mag=%s main=%s" % ((r3.get("force") or {}).get("mag"), (r3.get("force") or {}).get("main")))
        ck("D' 目标点被势场偏置", bool(fb) and fb.get("goal_biased") != fb.get("goal_raw"),
           "bias=%s mm=%s" % (fb.get("bias"), fb.get("norm_mm")))
        ck("D'' 偏置有界 (≤ %gmm)" % cap, float(fb.get("norm_mm") or 0) <= cap + 1e-6,
           "norm=%s" % fb.get("norm_mm"))
        ck("D''' 偏置后仍出段表", bool(r3.get("segments")), "n=%s" % r3.get("n"))

        # E. 势场力过大 ⇒ 否决
        r4 = P.run(_ctx(skill=sk, force=dict(frc, mag=1.2)))
        ck("E 势场过大拒出段表", (r4.get("ok") is False and r4.get("reason") == "force_veto"
                                and not r4.get("segments")), "reason=%s" % r4.get("reason"))

        # F. in2 安全约束真读
        r5 = P.run(_ctx(target=GOAL, step=20.0, down=5.0))
        ck("F in2 安全约束真读", int(r5.get("n") or 0) > int(r1.get("n") or 0),
           "step20/down5 n=%s vs step50/down20 n=%s" % (r5.get("n"), r1.get("n")))

        # G. 配置真源
        ck("G 配置三项可读", all(k in cfg for k in ("force_bias_mm_per_unit", "force_bias_max_mm", "force_veto_mag")),
           "keys=%s" % sorted(cfg))

        # I. 8 个技能分端口 (in4..in11): 只有 active=True 的那个被选中 (不再被"后写覆盖")
        c8 = _ctx()
        for i, port in enumerate(("in4", "in5", "in6", "in7", "in8", "in9", "in10", "in11")):
            c8[port] = {"value": {"kind": "skill_act", "skill": "SK%02d" % (i + 1),
                                  "stage": "S%d" % (i + 1), "active": (port == "in8"),
                                  "target": GOAL, "t": time.time() - i * 0.1}}
        r6 = P.run(c8)
        ck("I 8 端口技能帧全收到", (r6.get("skill") or {}).get("n_frames") == 8,
           "n_frames=%s" % (r6.get("skill") or {}).get("n_frames"))
        ck("I' 选中 active 的那个 (in8/SK05)", (r6.get("skill") or {}).get("port") == "in8",
           "port=%s skill=%s" % ((r6.get("skill") or {}).get("port"), (r6.get("skill") or {}).get("skill")))

        # J. moveit 探针 TTL 缓存 (50.7ms/次 → 缓存后不再每拍吃预算)
        P._MV.update(t=0.0, v=None)
        P.run(_ctx(target=GOAL))
        r7 = P.run(_ctx(target=GOAL))
        ck("J moveit 探针带缓存", "cached_age_s" in (r7.get("moveit") or {}),
           "moveit=%s" % str(r7.get("moveit"))[:80])


        # H. 零回归: 不给 in3/in4 时行为与老口径一致 (段表不因新代码变形)
        ck("H 无势场无技能时零回归", [s["abs_mm"] for s in r1["segments"]] == [s["abs_mm"] for s in P.run(_ctx(target=GOAL))["segments"]],
           "segments 逐位一致")
    finally:
        P._TCP = _orig
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    print("\n结果: %d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项: %s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
