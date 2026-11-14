#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试: execution.execute() 返回位姿口径 action(dict), 同时兼容老消费方(np.asarray)"""
import sys
import time
import json
import numpy as np

sys.path.insert(0, "/home/ubuntu/zmax/src")
from lerobot.policies.left_right.state_space import execution as EX          # noqa: E402
from lerobot.policies.left_right.state_space import action_bus as AB        # noqa: E402

ok = True


def chk(name, cond, extra=""):
    global ok
    ok = ok and bool(cond)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + extra) if extra else ""))


print("=== A. 正常拍: u=[-0.1158, 0.0115, -0.0294, 0] (直驱)")
ex = EX.RobotExecutor()
a = ex.execute(np.array([-0.11578, 0.011491, -0.029385, 0.0]))
chk("返回 Action(dict)", isinstance(a, dict))
chk("src == ss", a.get("src") == "ss", str(a.get("src")))
chk("有 pose", bool(a.get("pose")), str(a.get("pose") and {k: a["pose"].get(k) for k in ("x", "y", "z", "a", "b", "c")}))
chk("有 joints_deg(6)", len(a.get("joints_deg") or []) == 6 or a.get("joints_deg") is None,
    "%s(%s)" % (a.get("joints_deg"), a.get("joints_src")))
chk("有夹爪字段", "grip_act" in a, "%s mm / %s" % (a.get("grip_mm"), a.get("grip_act")))
arr = np.asarray(a, dtype=float).ravel()
chk("np.asarray 仍给 4 维速度(兼容)", arr.size == 4, str(np.round(arr, 4)))
chk("action[:3] 可切片(兼容 sim.py)", np.asarray(a[:3]).size == 3)

print("=== B. 算错拍: NaN ⇒ 回退 215 点真值")
b = ex.execute(np.array([np.nan, 0.0, 0.0, 0.0]), allow_traj_fallback=True)
chk("src == traj215", b.get("src") == "traj215", str(b.get("src")))
chk("pose = 215 点目标", bool(b.get("pose")), str(b.get("pose") and {k: b["pose"].get(k) for k in ("x", "y", "z", "a", "b", "c")}))
chk("joints_deg 6 维(deg)", len(b.get("joints_deg") or []) == 6, str(b.get("joints_deg")))
chk("np.asarray = 6 维关节(兼容旧回退)", np.asarray(b, dtype=float).ravel().size == 6)
chk("fallback 标注", "traj215" in str(b.get("fallback")), str(b.get("fallback")))

print("=== C. 落后消费方: verification_layer 口径 (shape[0]==4)")
v = np.asarray(EX.RobotExecutor().execute(np.zeros(4)), float)
chk("t_act_dim: shape[0]==4", v.shape[0] == 4, str(v.shape))
v2 = np.asarray(EX.RobotExecutor().execute(np.array([0.1, 0.2, -0.1, 0.5])), float)
chk("t_act_pass: 有限且 4 维", bool(np.isfinite(v2).all()) and v2.shape[0] == 4, str(np.round(v2, 3)))

print("=== D. action_bus.from_action 摊平(唯一出口)")
flat = AB.from_action(b)
chk("摊平出 KEYS", all(k in flat for k in ("src", "x", "y", "z", "a", "b", "c", "j1", "j6")),
    "src=%s i=%s x=%.2f j1=%.2f" % (flat.get("src"), flat.get("i"), flat.get("x") or 0, flat.get("j1") or 0))
flat2 = AB.from_action(a, deny="护栏未放行 mode=shadow ok=0/30")
chk("deny 写进 why", "护栏未放行" in str(flat2.get("why")), str(flat2.get("why"))[:60])

print("=== E. 位姿与机器人读数一致性(同一份 latest.json)")
p = EX.tcp_pose_now()
if p:
    print("  机器人读数 x=%.2f y=%.2f z=%.2f a=%.2f b=%.2f c=%.2f (age %.2fs)"
          % (p["x"], p["y"], p["z"], p["a"], p["b"], p["c"], p["age_s"]))
    if a.get("pose") and a["pose"].get("x") is not None:
        dx = a["pose"]["x"] - p["x"]
        dy = a["pose"]["y"] - p["y"]
        dz = a["pose"]["z"] - p["z"]
        print("  action 位姿  x=%.2f y=%.2f z=%.2f  ⇒ Δ=(%.2f, %.2f, %.2f) mm"
              % (a["pose"]["x"], a["pose"]["y"], a["pose"]["z"], dx, dy, dz))
        expect = np.asarray(a["u"], float)[:3] * 1000.0 * float(a.get("dt_s") or 0.1)
        err = max(abs(dx - expect[0]), abs(dy - expect[1]), abs(dz - expect[2]))
        chk("Δ 位姿 == u*dt (误差<0.02mm)", err < 0.02, "err=%.4f mm" % err)
else:
    print("  ⚠️ 位姿读不到(latest.json 过期/全 0) ⇒ pose 为 None, 不编数(符合口径)")

print("\n%s" % ("全部通过 ✅" if ok else "有失败 ❌"))
sys.exit(0 if ok else 1)
