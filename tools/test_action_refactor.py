#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试: execute() 输出**真正下发**的 action(位姿口径), 并且兼容老消费方 np.asarray。

两条口径(2026-11-14 起):
  · 直驱闸放行   ⇒ src=ss     · np.asarray 给 4 维速度
  · 闸未放行     ⇒ src=traj215 · np.asarray 给 6 维关节(215 点回放) —— 与机器人真值同一点
关掉换口径: ZMAX_EXEC_EFFECTIVE=0
"""
import os
import sys

import numpy as np

sys.path.insert(0, "/home/ubuntu/zmax/src")
from lerobot.policies.left_right.state_space import execution as EX          # noqa: E402
from lerobot.policies.left_right.state_space import action_bus as AB        # noqa: E402

ok = True


def chk(name, cond, extra=""):
    global ok
    ok = ok and bool(cond)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + extra) if extra else ""))


print("=== A. 直驱口径(ZMAX_EXEC_EFFECTIVE=0 强制不换口径)")
os.environ["ZMAX_EXEC_EFFECTIVE"] = "0"
ex = EX.RobotExecutor()
a = ex.execute(np.array([-0.11578, 0.011491, -0.029385, 0.0]))
chk("返回 Action(dict)", isinstance(a, dict))
chk("src == ss", a.get("src") == "ss", str(a.get("src")))
chk("有 pose", bool(a.get("pose")), str(a.get("pose") and {k: a["pose"].get(k) for k in ("x", "y", "z", "a", "b", "c")}))
chk("np.asarray 给 4 维速度", np.asarray(a, dtype=float).ravel().size == 4, str(np.round(np.asarray(a, float), 4)))
chk("action[:3] 可切片", np.asarray(a[:3]).size == 3)

print("=== B. 算错拍: NaN ⇒ 回退 215 点真值")
b = ex.execute(np.array([np.nan, 0.0, 0.0, 0.0]), allow_traj_fallback=True)
chk("src == traj215", b.get("src") == "traj215", str(b.get("src")))
chk("pose = 215 点目标", bool(b.get("pose")))
chk("joints_deg 6 维", len(b.get("joints_deg") or []) == 6)
chk("np.asarray = 6 维关节", np.asarray(b, dtype=float).ravel().size == 6)
chk("fallback 有标注", bool(b.get("fallback")), str(b.get("fallback")))

print("=== C. 默认口径(ZMAX_EXEC_EFFECTIVE=1): 直驱闸未放行 ⇒ action 就是 215 点")
os.environ.pop("ZMAX_EXEC_EFFECTIVE", None)
c = ex.execute(np.array([0.0, 0.0, 0.0, 0.0]))
if c.get("src") == "traj215":
    chk("src == traj215(闸未放行, 与真实下发一致)", True, "i=%s" % c.get("i"))
    chk("6 维关节", np.asarray(c, float).ravel().size == 6)
    chk("带 dd_u 溯源", "dd_u" in c, str(c.get("dd_u")))
    p = EX.tcp_pose_now() or {}
    cp = c.get("pose") or {}
    if p.get("x") is not None and cp.get("x") is not None:
        d = np.array([cp["x"] - p["x"], cp["y"] - p["y"], cp["z"] - p["z"]])
        chk("与机器人实测差 < 5mm(同一执行点)", float(np.abs(d).max()) < 5.0, "Δ=%s mm" % np.round(d, 2))
else:
    chk("src == ss(闸放行)", True, "i=%s" % c.get("i"))

print("=== D. action_bus.from_action 摊平(唯一出口)")
flat = AB.from_action(c)
chk("摊平出 KEYS", all(k in flat for k in ("src", "x", "y", "z", "a", "b", "c", "j1", "j6")),
    "src=%s i=%s x=%.2f j1=%.2f" % (flat.get("src"), flat.get("i"), flat.get("x") or 0, flat.get("j1") or 0))
flat2 = AB.from_action(a, deny="护栏未放行 mode=shadow ok=0/30")
chk("deny 写进 why", "护栏未放行" in str(flat2.get("why")), str(flat2.get("why"))[:60])

print("=== E. 位姿一致性(同一份 latest.json)")
p = EX.tcp_pose_now()
if p:
    print("  机器人读数 x=%.2f y=%.2f z=%.2f a=%.2f b=%.2f c=%.2f (age %.2fs)"
          % (p["x"], p["y"], p["z"], p["a"], p["b"], p["c"], p["age_s"]))
    ap = a.get("pose") or {}
    if ap.get("x") is not None:
        dx, dy, dz = ap["x"] - p["x"], ap["y"] - p["y"], ap["z"] - p["z"]
        print("  A(直驱) 位姿 Δ=(%.2f, %.2f, %.2f) mm" % (dx, dy, dz))
        u = np.asarray(a.get("u") or [], float)
        if u.size == 3:
            exp = u * 1000.0 * float(a.get("dt_s") or 0.1)
            err = max(abs(dx - exp[0]), abs(dy - exp[1]), abs(dz - exp[2]))
            chk("A: Δ == u*dt (误差<0.05mm)", err < 0.05, "err=%.4f mm" % err)
else:
    print("  ⚠️ 位姿读不到 ⇒ 不编数")

print("\n%s" % ("全部通过 ✅" if ok else "有失败 ❌"))
sys.exit(0 if ok else 1)
