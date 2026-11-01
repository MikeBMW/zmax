#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_modulator_ports.py — 「动作调制器」是否真的有作用 (离线, 不动真机)

判据:
  ① 九路端口真读: in6(前馈) 有值 ⇒ u_ff 用它; 只有 in9(测地线块) ⇒ 用它; 两路都没有 ⇒ 明确跳过
  ② 输出是业务字典 (不再是 True ⇒ 壳直通)
  ③ 阶段限速只削幅不改方向 (方向余弦 ≈1)
  ④ 残差异常 ⇒ 否决 (输出归零) 且给 why
  ⑤ 夹爪通道单独算 (gripper_cmd), 不被平移限速带走
  ⑥ 端口口径记录可回读 (in6/in9/in8/in4 用了哪个, 落 out2.ports)
"""
import json
import os
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

import numpy as np                                                    # noqa: E402

from lerobot.engineering.nodes import safety_limit_impl as SL         # noqa: E402

ROWS = []


def ck(tag, name, ok, detail=""):
    ROWS.append((tag, ok, name, detail))
    print(("  ✅ " if ok else "  ❌ ") + "%s %s — %s" % (tag, name, detail))


def call(ports, name="🧭 动作调制器"):
    ctx = {"name": name}
    for k, v in ports.items():
        ctx[k] = {"value": v, "age_s": 0.05, "fresh": True}
    return SL.run(ctx)


def main() -> int:
    # ① 前馈优先
    o = call({"in6": {"u": [0.30, 0.00, 0.00, 1.0]},
              "in9": {"chunk0": [0.05, 0.00, 0.00, 1.0]}})
    u = (o.get("out1") or {}).get("u")
    ck("①a", "in6 前馈优先", bool(u) and abs(u[0]) >= 0.05
       and (o["out2"]["ports"]["u_ff"] or "").startswith("in6"),
       "u=%s u_ff 端口=%s" % (u, o["out2"]["ports"]["u_ff"]))

    # 只有 in9 ⇒ 用测地线块
    o = call({"in9": {"chunk0": [0.20, 0.00, 0.00, 1.0]}})
    ck("①b", "只有 in9 (测地线块) 也能驱动",
       bool((o.get("out1") or {}).get("u")) and (o["out2"]["ports"]["u_ff"] or "").startswith("in9"),
       "u=%s 端口=%s" % ((o.get("out1") or {}).get("u"), o["out2"]["ports"]["u_ff"]))

    # 两路都没有 ⇒ 明确跳过, 不装生效
    o = call({})
    ck("①c", "无前馈 ⇒ 明确跳过 (why 说清)",
       (o.get("out1") or {}).get("kind") == "modulator_skipped"
       and "缺前馈" in ((o.get("out1") or {}).get("why") or ""),
       "%s · %s" % ((o.get("out1") or {}).get("kind"), (o.get("out1") or {}).get("why", "")[:52]))

    # ② 业务字典 (不是 True)
    o = call({"in6": {"u": [0.2, 0.1, 0.0, 1.0]}})
    ck("②", "输出业务字典 (不再 True 直通)", isinstance(o, dict) and "out1" in o
       and isinstance(o["out1"], dict), "keys=%s" % sorted(o.keys()))

    # ③ 只削幅不改方向
    o = call({"in6": {"u": [0.60, 0.60, 0.0, 1.0]}})       # 幅值 0.85 > 阶段上限
    o1 = o["out1"]
    ck("③", "阶段限速只削幅 (方向余弦≈1)", abs(o1["dir_cos"] - 1.0) < 0.02
       and o1["amp_ratio"] <= 1.001,
       "dir_cos=%.3f amp_ratio=%.3f u=%s" % (o1["dir_cos"], o1["amp_ratio"], o1["u"][:3]))

    # ④ 残差异常 ⇒ 否决
    o = call({"in6": {"u": [0.2, 0.0, 0.0, 1.0]}, "in8": {"residual": [9.0, 9.0, 9.0, 0]}})
    o1 = o["out1"]
    ck("④", "残差异常 ⇒ 否决 (输出归零)", o1.get("u") is not None
       and float(np.linalg.norm(o1["u"][:3])) < 1e-6 and ("否决" in str(o1.get("stage"))),
       "stage=%s u=%s" % (o1.get("stage"), o1.get("u")[:3] if o1.get("u") else None))

    # ⑤ 夹爪通道独立
    o = call({"in6": {"u": [0.0, 0.0, 0.0, 0.0]}})
    g = (o.get("out2") or {}).get("gripper")
    ck("⑤", "夹爪通道单独算 (gripper_cmd)", g is not None and 0.0 <= float(g) <= 1.0,
       "gripper=%s" % g)

    # ⑥ 端口口径可回读
    o = call({"in9": {"chunk0": [0.1, 0.0, 0.0, 1.0]}, "in8": {"u_fb": [0.01, 0, 0, 0]},
              "in4": {"contact_p": 0.42}})
    p = (o.get("out2") or {}).get("ports") or {}
    ck("⑥", "端口口径可回读 (in9/in8/in4)", str(p.get("u_ff", "")).startswith("in9")
       and str(p.get("u_fb", "")).startswith("in8") and str(p.get("cp", "")).startswith("in4"),
       "ports=%s" % json.dumps(p, ensure_ascii=False))

    # ⑦ 链路贯通: 调制器 out1 → 安全边界 in1
    #    7a 调制器已把 0.9 削到阶段上限 (≈0.24) ⇒ 边界在 limit 0.6 内**原样放行**
    #    7b 手工给一个超 limit 的向量 ⇒ 边界必须压到 0.6 (证明限幅真咬)
    o = call({"in6": {"u": [0.9, -0.9, 0.2, 1.0]}})
    u_mod = (o.get("out1") or {}).get("u") or []
    ob = SL.run({"name": "🛡 安全执行边界 (饱和限幅)", "in1": {"value": o["out1"]}})
    ob1 = ob.get("out1") or {}
    u_sat = ob1.get("u_sat") or []
    ok_a = (bool(u_sat) and np.allclose(u_sat[:3], u_mod[:3], atol=1e-4)
            and ob1.get("u_src") == "in1(动作调制器)")
    ob2 = SL.run({"name": "🛡 安全执行边界 (饱和限幅)", "in1": {"value": {"u": [0.9, 0.0, 0.0, 1.0]}}})
    u_sat2 = (ob2.get("out1") or {}).get("u_sat") or []
    ok_b = bool(u_sat2) and abs(float(u_sat2[0]) - 0.6) < 1e-6
    ck("⑦", "链路贯通: 调制器→安全边界(in1); 超限被压到 0.6",
       ok_a and ok_b,
       "7a 调制后 %.3f 在限内原样放行=%s · 7b 0.9→%.2f" % (
           float(np.linalg.norm(u_mod[:3])) if u_mod else -1, ok_a,
           u_sat2[0] if u_sat2 else -1))

    npass = sum(1 for r in ROWS if r[1])
    print("\n判据: PASS %d / FAIL %d" % (npass, len(ROWS) - npass))
    out = {"ok": npass == len(ROWS), "pass": npass, "total": len(ROWS),
           "rows": [{"tag": t, "ok": o_, "name": n, "detail": d_} for t, o_, n, d_ in ROWS]}
    os.makedirs(os.path.join(ROOT, "zmax_data", "eval"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "zmax_data", "eval", "verify_modulator_ports.json"), "w"),
              ensure_ascii=False, indent=1)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
