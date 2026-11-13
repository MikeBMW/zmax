# -*- coding: utf-8 -*-
"""把录制的真实轨迹导出成"关节角真值"回放帧 —— 保姿态(含翻面), 不靠位置 IK。

为什么要有这一步:
  AR 页原来的『📍 右臂跑真实轨迹』是**位置 IK**(ikTool1 只匹配 xyz), 姿态是求解器自己挑的,
  所以真机那段翻面/转腕在仿真里完全没有 —— 实测录制里累计转动 959°、单步最大 24.3°,
  只按 xyz 回放等于把这 959° 全丢了。

真源: zmax_data/pose_records/<rec>/poses.jsonl —— 每行 = 50Hz 位姿真值, 字段含
      x,y,z · qx,qy,qz,qw · joint[12](前 6 = 关节角, 弧度) · speed_mm_s · moving
  这是 SDK 直读(endInRef)的真值, 不是反解出来的。

产出: tools/web/real_traj_joints.json (8797 只服务 tools/web 下的静态文件, zmax_data 是 404)

跑法:  ./gui-venv311/bin/python tools/real_traj_joints.py --rec rec_20261111_181020
       ./gui-venv311/bin/python tools/real_traj_joints.py --rec ... --rdp  # 与 182 点对齐(默认)
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECS = os.path.join(REPO, "zmax_data", "pose_records")
OUT = os.path.join(REPO, "tools", "web", "real_traj_joints.json")
POS_MM = 8.0          # 相邻回放帧最大位移
ROT_DEG = 3.0         # 或单帧转动超过这个也插点(姿态保真优先)


def load_poses(rec_dir):
    rows = []
    for ln in open(os.path.join(rec_dir, "poses.jsonl"), encoding="utf-8"):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if "x" not in d or "joint" not in d:
            continue
        j = list(d["joint"])[:6]
        if len(j) != 6:
            continue
        rows.append({"ts": float(d.get("ts") or 0.0), "p": [d["x"], d["y"], d["z"]],
                     "q": [d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")], "j": j,
                     "mv": bool(d.get("moving")), "sp": float(d.get("speed_mm_s") or 0.0)})
    rows.sort(key=lambda r: r["ts"])
    return rows


def quat_ang(a, b):
    """两个四元数之间的夹角(度)。"""
    a = np.asarray(a, float); b = np.asarray(b, float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    d = abs(float(np.dot(a, b)) / (na * nb))
    return float(np.degrees(2.0 * np.arccos(min(1.0, d))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rec", default="", help="录制目录名, 默认取最新")
    ap.add_argument("--traj-name", default="真实轨迹", help="FENCES 里那条 points 元素的名字前缀(对齐 182 点用)")
    ap.add_argument("--all", action="store_true", help="导出全部样本(不按 182 点对齐)")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    if a.rec:
        rec_dir = os.path.join(RECS, a.rec)
    else:
        cands = [d for d in glob.glob(os.path.join(RECS, "rec_*")) if os.path.isdir(d)]
        rec_dir = max(cands, key=os.path.getmtime)
    rows = load_poses(rec_dir)
    if len(rows) < 3:
        raise SystemExit("poses.jsonl 样本不足: %s" % rec_dir)
    P = np.array([r["p"] for r in rows], float)

    # ① 回放帧: 全量样本做 "位移/转角双闸" 抽稀 —— 姿态变化优先(位置不动但转腕也要留点)
    keep = [0]
    last = 0
    for i in range(1, len(rows)):
        dp = float(np.linalg.norm(P[i] - P[last])) * 1000.0
        dr = quat_ang(rows[i]["q"], rows[last]["q"])
        if dp >= POS_MM or dr >= ROT_DEG:
            # 段内补点: 相邻保留帧之间若位移太大, 线性补中间样本(避免 215mm 一步跳)
            if dp > 30.0:
                n = int(np.ceil(dp / POS_MM))
                step = (i - last) / float(n)
                k = last
                for _ in range(1, n):
                    k = last + int(round(step * _))
                    if k < i and k > keep[-1]:
                        keep.append(k)
            keep.append(i)
            last = i
    if keep[-1] != len(rows) - 1:
        keep.append(len(rows) - 1)

    frames = []
    # ③ 只留运动段: 录制里 270s 大部分是静止(5Hz), 全量回放等于看它坐着
    idx = [i for i, r in enumerate(rows) if r["mv"] or r["sp"] > 1.0]
    if not idx:
        idx = list(range(len(rows)))
    seg = set(idx)
    for i in list(idx):                      # 运动前后各带 1 帧, 让起停有位姿
        for k in (i - 1, i + 1):
            if 0 <= k < len(rows):
                seg.add(k)
    keep = [i for i in keep if i in seg] or sorted(seg)

    t0 = rows[keep[0]]["ts"]
    walls = []
    for i in keep:
        r = rows[i]
        walls.append({"p": [round(v, 6) for v in r["p"]],
                      "q": [round(float(v), 6) for v in r["q"]],
                      "j": [round(float(v), 6) for v in r["j"]],
                      "wall": r["ts"] - t0})
    # 静止间隙压缩到 0.25s: 真机是"走-停-走", 回放保留顺序与真实运动速度, 只压掉干等的空档
    tt = 0.0
    for k, w in enumerate(walls):
        if k:
            gap = w["wall"] - walls[k - 1]["wall"]
            tt += min(gap, 0.25) if gap > 0.25 else gap
        frames.append({"p": w["p"], "q": w["q"], "j": w["j"], "t": round(tt, 3)})

    # ② 校验统计(如实报, 不许美化)
    dP = np.linalg.norm(np.diff(P, axis=0), axis=1) * 1000.0
    rot_total = sum(quat_ang(rows[i]["q"], rows[i - 1]["q"]) for i in range(1, len(rows)))
    fj = np.array([f["j"] for f in frames], float)
    jstep = np.degrees(np.abs(np.diff(fj, axis=0))).max() if len(fj) > 1 else 0.0
    fp = np.array([f["p"] for f in frames], float)
    fstep = np.linalg.norm(np.diff(fp, axis=0), axis=1) * 1000.0 if len(fp) > 1 else np.array([0.0])
    crot = sum(quat_ang(frames[i]["q"], frames[i - 1]["q"]) for i in range(1, len(frames)))
    out = {"src_rec": os.path.basename(rec_dir), "src_file": os.path.join(rec_dir, "poses.jsonl"),
           "n_samples": len(rows), "n_frames": len(frames), "dur_s": round(frames[-1]["t"], 2),
           "path_mm": round(float(fstep.sum()), 1), "rot_total_deg": round(float(crot), 1),
           "rot_source_deg": round(rot_total, 1),
           "max_pos_step_mm": round(float(fstep.max()), 1), "max_joint_step_deg": round(float(jstep), 2),
           "note": "joint/q 为 SDK 真值; 只留运动段并压缩静止空档; 相邻帧位移/转角双闸抽稀",
           "unit": {"p": "m", "j": "rad", "t": "s"},
           "frames": frames}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps({k: out[k] for k in ("src_rec", "n_samples", "n_frames", "dur_s", "path_mm",
                                         "rot_total_deg", "max_pos_step_mm", "max_joint_step_deg")},
                     ensure_ascii=False, indent=1))
    print("out: %s (%.1f KB)" % (a.out, os.path.getsize(a.out) / 1024.0))


if __name__ == "__main__":
    main()
