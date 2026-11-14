#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📐 料盘/槽位可见性表 —— 只做几何, 不训练、不下发。

真源:
  槽位 7 个    data/skills/l2_atomic/taught_points.json: slot1..slot7 (pos + quat/abc)
  轨迹 215 点  tools/web/real_traj_joints.json: frames[i].p / .q
  内参        zmax_data/full_system_20260922/config/calib/zmax_calib.json: camera.K (D435, 640x480)

⚠️ 口径限制(必须写在结论里):
  calib 里 T_base_cam = None（手眼外参**未标定**）⇒ 严格投影做不了。
  本表用"**相机光轴 ≈ 工具轴(-Z)**"近似（D435 装在法兰上、朝工具方向），
  误差量级 = 安装倾角，标定一次 T_tcp_cam 就能换成严格口径。

输出: zmax_data/reports/tray_visibility_<ts>.csv + 终端汇总
"""
import json
import math
import os
import time

REPO = os.path.expanduser("~/zmax")
TAUGHT = os.path.join(REPO, "data", "skills", "l2_atomic", "taught_points.json")
TRAJ = os.path.join(REPO, "tools", "web", "real_traj_joints.json")
CALIB = os.path.join(REPO, "zmax_data", "full_system_20260922", "config", "calib", "zmax_calib.json")
OUTDIR = os.path.join(REPO, "zmax_data", "reports")


def quat_to_R(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def unit(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / n for c in v]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def main():
    tp = json.load(open(TAUGHT, encoding="utf-8"))["points"]
    slots = []
    for k in ("slot1", "slot2", "slot3", "slot4", "slot5", "slot6", "slot7"):
        v = tp.get(k)
        if v and v.get("pos"):
            slots.append((k, [c * 1000.0 for c in v["pos"]]))
    if not slots:
        print("❌ 没有槽位真值(slot1..slot7)")
        return 1

    calib = json.load(open(CALIB, encoding="utf-8"))
    cam = calib["camera"]
    fx, fy, cx, cy = cam["fx"], cam["fy"], cam["cx"], cam["cy"]
    W, H = cam["image_size"]
    # 视场半角(度): 用内参算, 不用猜
    hfov = math.degrees(math.atan((W / 2.0) / fx))
    vfov = math.degrees(math.atan((H / 2.0) / fy))
    fov = min(hfov, vfov)          # 以窄边为准(圆形安全锥)
    T_cam_missing = calib.get("T_base_cam", {}).get("value") is None

    center = [sum(s[1][i] for s in slots) / len(slots) for i in range(3)]
    ys = [s[1][1] for s in slots]
    xs = [s[1][0] for s in slots]
    zs = [s[1][2] for s in slots]
    box = {"x": [min(xs) - 40, max(xs) + 40], "y": [min(ys) - 12, max(ys) + 12],
           "z": [min(zs) - 8, max(zs) + 25]}
    pitch = sorted(ys)
    pitch_mm = [round(pitch[i + 1] - pitch[i], 1) for i in range(len(pitch) - 1)]

    frames = json.load(open(TRAJ, encoding="utf-8"))["frames"]
    rows = []
    for i, f in enumerate(frames):
        p = [c * 1000.0 for c in f["p"]]
        R = quat_to_R(f["q"])
        zaxis = [R[0][2], R[1][2], R[2][2]]      # 工具 Z 轴(工具系 z 在基座系)
        d = [center[k] - p[k] for k in range(3)]
        dist = math.sqrt(dot(d, d))
        if dist < 1e-6:
            continue
        dn = unit(d)
        # 相机朝工具 -Z 还是 +Z: 两个都算, 取更小的(即相机更可能朝向料盘的那个)
        ang_neg = math.degrees(math.acos(max(-1.0, min(1.0, dot([-c for c in zaxis], dn)))))
        ang_pos = math.degrees(math.acos(max(-1.0, min(1.0, dot(zaxis, dn)))))
        ang = min(ang_neg, ang_pos)
        sign = "-Z" if ang_neg <= ang_pos else "+Z"
        # 逐个槽位是否落在视锥内
        vis = []
        for name, sp in slots:
            dv = [sp[k] - p[k] for k in range(3)]
            dd = math.sqrt(dot(dv, dv))
            a = math.degrees(math.acos(max(-1.0, min(1.0, dot([-c for c in zaxis], unit(dv)) if sign == "-Z"
                                                       else dot(zaxis, unit(dv))))))
            if a <= fov and dd <= 1500:
                vis.append(name)
        rows.append({"i": i, "tcp_mm": [round(c, 1) for c in p], "dist_mm": round(dist, 1),
                     "angle_deg": round(ang, 1), "cam_axis": sign, "n_slots": len(vis),
                     "slots": ",".join(vis)})

    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, "tray_visibility_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("i,x_mm,y_mm,z_mm,dist_mm,angle_deg,cam_axis,n_slots,slots\n")
        for r in rows:
            fh.write("%d,%.1f,%.1f,%.1f,%.1f,%.1f,%s,%d,%s\n" % (
                r["i"], r["tcp_mm"][0], r["tcp_mm"][1], r["tcp_mm"][2],
                r["dist_mm"], r["angle_deg"], r["cam_axis"], r["n_slots"], r["slots"]))

    print("=" * 78)
    print("料盘几何(来自示教真值 slot1..slot7)")
    print("  中心      %.1f %.1f %.1f mm" % tuple(center))
    print("  槽间距    %s mm (中位 %.1f)" % (pitch_mm, sorted(pitch_mm)[len(pitch_mm) // 2]))
    print("  包围盒    X %.0f~%.0f  Y %.0f~%.0f  Z %.0f~%.0f mm"
          % (box["x"][0], box["x"][1], box["y"][0], box["y"][1], box["z"][0], box["z"][1]))
    print("  相机      D435 %dx%d · fx=%.1f fy=%.1f · 安全锥(窄边半角) %.1f°" % (W, H, fx, fy, fov))
    if T_cam_missing:
        print("  ⚠️ 手眼外参 T_base_cam = None ⇒ 用「相机光轴≈工具轴」近似, 倾角误差未计")
    print("-" * 78)
    print("215 点可见性(按能看到的槽位数排序, 只列前 18 + 统计)")
    rows_sorted = sorted(rows, key=lambda r: (-r["n_slots"], r["angle_deg"]))
    print("   点号   TCP(mm)                距料盘   偏离轴  光轴  可见  能看到哪些槽")
    for r in rows_sorted[:18]:
        print("  %4d   %6.0f %6.0f %6.0f   %5.0fmm  %4.1f°  %-3s  %d/7  %s" % (
            r["i"], r["tcp_mm"][0], r["tcp_mm"][1], r["tcp_mm"][2],
            r["dist_mm"], r["angle_deg"], r["cam_axis"], r["n_slots"], r["slots"][:44]))
    n_all = sum(1 for r in rows if r["n_slots"] == 7)
    n_some = sum(1 for r in rows if r["n_slots"] > 0)
    print("-" * 78)
    print("统计: 215 点中 · 看全 7 槽 %d 点 · 至少看到 1 槽 %d 点 · 一槽都看不到 %d 点"
          % (n_all, n_some, len(rows) - n_some))
    print("CSV: %s" % out)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
