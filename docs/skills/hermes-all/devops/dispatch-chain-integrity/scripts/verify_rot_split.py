"""零运动离线自证: 姿态分步(下发腿自动把"姿态差 > 阈值"的整位姿动作 slerp 成 <=5°/段 原地转身)。

判据: ①每段姿态增量 <= ROT_STEP_DEG(默认 5°); ②留给平移段的残差 <=5°; ③四元数转 rpy 无 NaN;
      ④覆盖真实点位对 + 大角度极端(90/150/179°)。
用法: python3 scripts/verify_rot_split.py   (仓库根跑; 退出码 0 = 全过)

改动下发腿里的 ROT_SPLIT / 阈值 / slerp 后必跑; 它验数学与门限, 不碰设备。
"""
import importlib.util
import itertools
import json
import math
import sys

SPEC = "/home/ubuntu/zmax/tools/rokae/l2_transport_sdk.py"
PTS = "/home/ubuntu/zmax/data/skills/l2_atomic/space_points.json"

spec = importlib.util.spec_from_file_location("leg", SPEC)
leg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(leg)

pts = json.load(open(PTS))["points"]
named = {k: v["quat"] for k, v in pts.items() if v.get("quat")}
print("点库: %s" % sorted(named))
print("ROT_SPLIT=%s | 触发阈值 %.1f° | 单段上限 %.1f°\n"
      % (leg.ROT_SPLIT, leg.ROT_SPLIT_DEG, leg.ROT_STEP_DEG))


def qz(deg):
    h = math.radians(deg) / 2.0
    return [0.0, 0.0, math.sin(h), math.cos(h)]


cases = [("%s->%s" % (a, b), named[a], named[b])
         for a, b in itertools.combinations(sorted(named), 2)]
cases += [("合成 90", [0, 0, 0, 1], qz(90)), ("合成 150", [0, 0, 0, 1], qz(150)),
          ("合成 179", [0, 0, 0, 1], qz(179)), ("合成 6(不触发)", [0, 0, 0, 1], qz(6))]

bad = 0
for name, qa, qb in cases:
    ang = leg.quat_angle_deg(qb, qa)
    if not (leg.ROT_SPLIT and ang > leg.ROT_SPLIT_DEG):
        print("  %-16s 姿态差 %6.1f° => 不拆(直发) OK" % (name, ang))
        continue
    n = int(math.ceil(ang / leg.ROT_STEP_DEG))
    prev, mx, nan = list(qa), 0.0, False
    for i in range(1, n):
        qi = leg.quat_slerp(qa, qb, i / float(n))
        mx = max(mx, leg.quat_angle_deg(qi, prev))
        nan = nan or any(not math.isfinite(v) for v in leg.quat2rpy(*qi))
        prev = qi
    resid = leg.quat_angle_deg(qb, prev)
    ok = (mx <= leg.ROT_STEP_DEG + 1e-6) and (resid <= leg.ROT_STEP_DEG + 1e-6) and not nan
    bad += 0 if ok else 1
    print("  %-16s 姿态差 %6.1f° => 拆 %2d 段 | 最大单段 %5.2f° | 平移段残差 %5.2f° %s"
          % (name, ang, n - 1, mx, resid, "OK" if ok else "FAIL"))

print("\n结果: %s" % ("OK 全部达标 (每段 <=5° | 平移段 <=5° | 无 NaN)" if bad == 0
                     else "FAIL %d 例不达标" % bad))
sys.exit(1 if bad else 0)
