#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分辨"同步接错" vs "没覆盖": 同一帧渲三种视角, 用黑像素占比说话。

A 当前实时位姿(位置+姿态都取手臂)
B 当前实时**位置** + 最近采集帧的**姿态**   → 若 B 正常 ⇒ 位置没问题, 是姿态方向没采集过
C 最近采集帧的完整位姿(位置+姿态)          → 若 C 正常 ⇒ 采集数据本身可用

判据: 黑像素占比(<16)与平均亮度。渲染器总说"跟相机没对上"时, 这三张一比就知道错在哪一层。

用法: python gs_view_triage.py --job <dir> --ply <ply> --handeye <json> --pose <json>
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, "/home/intel/zmax_map/tools")
sys.path.insert(0, "/home/ubuntu/zmax/tools")
from gs_render_stream_intel import read_gs_ply  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--ply", default="")
    ap.add_argument("--handeye", default="/home/intel/zmax_map/models/handeye_state.json")
    ap.add_argument("--pose", default="/tmp/arm_tcp_pose.json")
    ap.add_argument("--outdir", default="/tmp/gs_triage")
    a = ap.parse_args()

    import torch
    import gsplat
    from PIL import Image

    cj = json.load(open(os.path.join(a.job, "ds/cameras.json"), encoding="utf-8"))
    rep = json.load(open(os.path.join(a.job, "out/train_report.json"), encoding="utf-8"))
    norm = rep["normalize"]
    center = np.array(norm["center"], dtype=float)
    S = float(norm["S"])
    W, H = int(cj["width"]), int(cj["height"])
    K = np.array(cj["K"], dtype=float)
    ply = a.ply or os.path.join(a.job, "out/gs_pruned.ply")

    P = read_gs_ply(ply)
    dev = "xpu" if torch.xpu.is_available() else "cpu"
    means = torch.tensor(S * (P["means"] - center), dtype=torch.float32, device=dev)
    scales = torch.tensor(P["scales_log"] + math.log(S), dtype=torch.float32, device=dev)
    quats = torch.tensor(P["quats"], dtype=torch.float32, device=dev)
    opac = torch.tensor(P["opac"], dtype=torch.float32, device=dev)
    col = torch.cat([torch.tensor(P["sh0"], dtype=torch.float32, device=dev),
                     torch.tensor(P["shN"], dtype=torch.float32, device=dev)], dim=1)
    sh_deg = int(round(math.sqrt(P["shN"].shape[1] + 1) - 1))
    Kt = torch.tensor(K, dtype=torch.float32, device=dev).unsqueeze(0)

    def q2R(q):
        x, y, z, w = q
        n = math.sqrt(x*x + y*y + z*z + w*w); x, y, z, w = x/n, y/n, z/n, w/n
        return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                         [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                         [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

    X = np.array(json.load(open(a.handeye, encoding="utf-8"))["T_cam2tool"], float)
    d = json.load(open(a.pose, encoding="utf-8"))
    Tb = np.eye(4); Tb[:3, :3] = q2R(d["q"]); Tb[:3, 3] = np.array(d["t"])
    Tc_live = np.linalg.inv(Tb @ X)

    # 最近采集帧(按相机中心距离)
    def center_of(Tcw):
        return -Tcw[:3, :3].T @ Tcw[:3, 3]
    cams = [(np.array(f["T_cam2world"], float), f["file"]) for f in cj["frames"]]
    c_live = center_of(Tc_live)
    dists = [np.linalg.norm(center_of(T) - c_live) for T, _ in cams]
    k = int(np.argmin(dists))
    Tc_near = cams[k][0]
    print("实时相机中心 %s mm" % np.round(c_live*1000, 0).tolist())
    print("最近采集帧 #%d (%s) 距离 %.0f mm" % (k, cams[k][1], dists[k]*1000))
    ang = math.degrees(math.acos(max(-1, min(1, float((Tc_live[:3, :3].T @ np.array([0, 0, 1.0]))
                                                       @ (Tc_near[:3, :3].T @ np.array([0, 0, 1.0])))))))
    print("两者光轴夹角 %.1f°" % ang)

    os.makedirs(a.outdir, exist_ok=True)

    def render(Tcw, tag):
        Tn = np.eye(4)
        Tn[:3, :3] = Tcw[:3, :3]
        Tn[:3, 3] = S * (Tcw[:3, 3] - center)
        vm = torch.tensor(np.linalg.inv(Tn), dtype=torch.float32, device=dev).unsqueeze(0)
        with torch.no_grad():
            img, _, _ = gsplat.rasterization(means, quats, torch.exp(scales), torch.sigmoid(opac), col,
                                             viewmats=vm, Ks=Kt, width=W, height=H,
                                             sh_degree=sh_deg, packed=True, near_plane=0.01)
        r = img[0].clamp(0, 1).mul(255).byte().cpu().numpy()
        g = r.mean(2)
        black = float((g < 16).mean() * 100)
        p = os.path.join(a.outdir, "v_%s.jpg" % tag)
        Image.fromarray(r).save(p, quality=88)
        print("  %-28s 亮度 %5.1f · 黑像素 %5.1f%% · %s" % (tag, float(g.mean()), black, p))
        return float(g.mean()), black

    print("\n三种视角:")
    A = render(Tc_live, "A_live")
    # B: 实时**位置** + 最近采集帧的**姿态**(相机中心 = 实时位, 旋转 = 采集位)
    #    相机中心 c 与 T_cam2world 的关系: c = -R^T t  ⇒  t = -R c
    R_b = Tc_near[:3, :3].copy()
    Tb_rot = np.eye(4)
    Tb_rot[:3, :3] = R_b
    Tb_rot[:3, 3] = -R_b @ c_live
    B = render(Tb_rot, "B_livepos_nearrot")
    C = render(Tc_near, "C_nearest_full")

    print("\n判据: A 暗/B 亮 ⇒ 姿态方向没采集; A≈B≈C 都暗 ⇒ 模型质量/覆盖整体不足; C 亮 ⇒ 数据本身能渲")
    print("  A 亮度 %.1f · B 亮度 %.1f · C 亮度 %.1f" % (A[0], B[0], C[0]))


if __name__ == "__main__":
    main()
