#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""紧急下降: 在当前 XY 纯 -Z 分小步下降(默认 -80mm), 慢速, **关闭 MoveJ 自愈**(被拒就停, 不乱摆)。
   每步核真值; 报警变化/残差超标/掉到地板线 立刻停。只走代理 SDK 腿的既有安全链(precheck+越界保护+包络盒)。"""
import json
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/tools/rokae")
import l2_transport_sdk as T  # noqa: E402

TOTAL_MM = -80.0        # 目标: 下降 80mm (0.3176 → ≈0.2376, 距转移高度 0.1601 还有 78mm 余量)
STEP_MM = -20.0         # 每步 20mm
SPEED = 20.0            # mm/s 标称 ⇒ 实测 ≈2mm/s(1/10), 慢速
FLOOR_Z = 0.210         # 硬地板: 真值 z 低于它就立即停手(留 50mm 余量给转移高度 0.1601)
RETRY = False           # ⛔ 关闭 MoveL→MoveJ 自愈: 被 50102 拒 ⇒ 直接停, 不许关节乱摆

AG = os.path.expanduser("~/zmax/zmax_data/rokae_sdk")
box = T.env_box()
print("  包络盒: %s" % json.dumps(box, ensure_ascii=False)[:120] if box else "  (无包络盒)")


def pose():
    p = T.read_pose()
    return p["pos"], p["quat"], p["age"]


def alarms():
    import json as _j
    try:
        return _j.load(open(os.path.join(AG, "tcp_out", "agent_result.json"), encoding="utf-8")).get("out", {}).get("alarms")
    except Exception:
        return None


p0, _, age = pose()
p_start = tuple(p0)
print("  起点 (%.4f, %.4f, %.4f) 帧龄%.2fs · 目标下降 %.0fmm ⇒ 预计到 z=%.4f" %
      (*p0, age, TOTAL_MM, p0[2] + TOTAL_MM / 1000))

left = TOTAL_MM
step_i = 0
while abs(left) > 0.5:
    step_i += 1
    dz = STEP_MM if abs(left) >= abs(STEP_MM) else left
    left -= dz
    if p0[2] + (TOTAL_MM - left) / 1000 < FLOOR_Z:
        print("  ⛔ 已达硬地板线 %.3f ⇒ 停手" % FLOOR_Z)
        break
    a0 = alarms()
    req = {"cmd": "move-rel", "tag": "l2", "dx": 0.0, "dy": 0.0, "dz": dz,
           "speed": SPEED, "cap_mm": 50.0, "allow_movej_retry": RETRY, "guard_box": box}
    t0 = time.time()
    r = T.send_agent(req, 180.0, lambda m: print("      %s" % str(m)[:150]))
    p1, q1, _ = pose()
    d = (p1[2] - p0[2]) * 1000.0
    a1 = alarms()
    chg = bool(a0 and a1 and a0.get("last_alarm_ts") != a1.get("last_alarm_ts"))
    print("  第 %d 步 dz=%+.0fmm → rc=%s 用时%.1fs · 实测Δz=%+.1fmm · z=%.4f · 报警变化=%s"
          % (step_i, dz, r.get("rc"), time.time() - t0, d, p1[2], chg))
    if r.get("rc") != 0 or chg or abs(d - dz) > 3.0:
        print("  ⛔ 停止: rc=%s / 报警变化=%s / 实测与指令差 %.1fmm ⇒ 不再继续(臂不会自己乱走)"
              % (r.get("rc"), chg, abs(d - dz)))
        print("     判词: %s" % str(r.get("verdict"))[:170])
        break
    p0 = p1
    time.sleep(1.0)

p2, q2, age2 = pose()
print("\n  结束位姿 (%.4f, %.4f, %.4f) 帧龄%.2fs" % (*p2, age2))
print("  本次共下降 %.1fmm · z 从 %.4f → %.4f · 距转移高度(0.1601)还有 %.0fmm"
      % ((p2[2] - p_start[2]) * 1000, p_start[2], p2[2], (p2[2] - 0.1601) * 1000))
