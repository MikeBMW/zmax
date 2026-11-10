# -*- coding: utf-8 -*-
"""verify_camera_scheduler — 用 AR 场景真实轨迹点验证「到区域就开相应感知」。

判据 (全部来自真源, 无手编坐标):
  ① 区域表来自 zmax_data/env_model.json::zones  (工程配置)
  ② 轨迹点来自 8797 /api/traj/named               (AR 页面轨迹真源)
  ③ 相机能力来自 config/calib/camera_registry.json (实测 7 台)
用法: gui-venv311/bin/python tools/verify_camera_scheduler.py
"""
import json
import sys
import urllib.request

sys.path.insert(0, "src")
from lerobot.policies.perception import load_registry, load_zones, perceive_plan, scan_traj  # noqa: E402

OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    print("%s %s%s" % ("✅" if cond else "❌", name, ("  " + detail) if detail else ""))


def get(u):
    try:
        with urllib.request.urlopen(u, timeout=8) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"err": str(e)}


print("=" * 78)
print("① 区域表 (env_model.json 真源)")
zones = load_zones()
for z, v in zones.items():
    b = v["bbox"]
    print("   %-12s n=%-3s x%s y%s z%s" % (z, v.get("n"), b["x"], b["y"], b["z"]))
check("区域表 ≥5 个工程区", len(zones) >= 5, "实得 %d (5 工程 + %d 轨迹派生)" % (
    len(zones), max(0, len(zones) - 5)))
check("5 个工程区齐", all(k in zones for k in
                        ("观察位", "料盘槽位排", "插入工位/夹具", "标定区", "其它")))

print()
print("② 相机注册表 (实测)")
reg = load_registry()
cams = reg["cams"]
for cid, c in cams.items():
    ex = c["extrinsic"]
    lvl = c.get("level")
    print("   %-9s level=%-3s ext=%-13s calibrated=%-5s role=%s" % (
        cid, lvl, ex.get("mode"), c.get("calibrated"), ",".join(c.get("role") or [])))
check("7 台相机", len(cams) == 7)
check("只有 arm 能出 3D", [k for k, v in cams.items()
                          if v["extrinsic"]["mode"] == "tcp_compose"] == ["arm"])

print()
print("③ 区域 → 感知能力 (每区主相机)")
for z in zones:
    c = zones[z]["bbox"]
    center = tuple((c[ax][0] + c[ax][1]) / 2.0 for ax in "xyz")
    plan = perceive_plan(center)
    got = [x["id"] + "/" + ",".join(x["role"]) for x in plan["cams"]]
    print("   %-12s → zone=%-12s guide=%-5s cams=%s" % (z, plan["zone"], plan["guide"], got))
    check("区中心判定回自己: %s" % z, plan["zone"] == z, "得到 %s" % plan["zone"])

print()
print("④ AR 真实轨迹逐点过调度 (8797 /api/traj/named)")
trajs = {}
for k in ("xiaohong", "square", "map", "safe", "real"):
    d = get("http://127.0.0.1:8797/api/traj/named?k=%s" % k)
    pts = d.get("pts") or []
    if pts:
        trajs[k] = (d.get("label") or k, [tuple(float(v) for v in p[:3]) for p in pts],
                    d.get("note") or "")
        print("   取到 %-10s n=%-3d %s" % (k, len(pts), d.get("label") or ""))
    else:
        print("   取到 %-10s n=0   (%s)" % (k, (d.get("note") or "无点")[:60]))
check("至少有 3 条可用轨迹", len(trajs) >= 3, "实得 %d" % len(trajs))

print()
for k, (label, pts, note) in trajs.items():
    r = scan_traj(pts, label=label)
    print("   ── %s  n=%d  区域段数=%d" % (label, r["n_pts"], len(r["segments"])))
    for s in r["segments"]:
        print("      %-12s i %2d→%-2d (%2d点) guide=%-6s %s → %s" % (
            s["zone"], s["from_i"], s["to_i"], s["n_pts"], s["guide"],
            s["p_start"], s["p_end"]))
    check("轨迹有区域输出: %s" % label, len(r["segments"]) >= 1)

print()
print("⑤ 3D 闸门 (uncalibrated 必须被拒)")
from lerobot.policies.perception import can_guide_3d  # noqa: E402
for cid, c in cams.items():
    ok, why = can_guide_3d(c)
    print("   %-9s 3D=%-5s %s" % (cid, ok, why))
check("arm 可出 3D", can_guide_3d(cams["arm"])[0])
check("gold 拒 3D", not can_guide_3d(cams["gold"])[0])
check("surface 拒 3D", not can_guide_3d(cams["surface"])[0])
check("local2 拒 3D", not can_guide_3d(cams["local2"])[0])

print()
print("⑥ 滞回 (边界 20mm 内不抖)")
b = zones["插入工位/夹具"]["bbox"]
edge = (b["x"][1] + 0.010, (b["y"][0] + b["y"][1]) / 2, (b["z"][0] + b["z"][1]) / 2)  # 越界 10mm
z1, how1 = __import__("lerobot.policies.perception.camera_scheduler", fromlist=["zone_of"]).zone_of(
    edge, zones, prev=None)
z2, how2 = __import__("lerobot.policies.perception.camera_scheduler", fromlist=["zone_of"]).zone_of(
    edge, zones, prev="插入工位/夹具", hysteresis_mm=20)
print("   无历史 → %s (%s)" % (z1, how1))
print("   有历史 10mm 外 → %s (%s)" % (z2, how2))
check("滞回生效", z2 == "插入工位/夹具" and "滞回" in how2, how2)

print()
print("=" * 78)
print("PASS %d / FAIL %d" % (len(OK), len(FAIL)))
if FAIL:
    print("失败项:", FAIL)
sys.exit(0 if not FAIL else 1)
