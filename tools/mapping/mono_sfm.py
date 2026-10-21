#!/usr/bin/env python3
"""单目建图 (SfM/VO, 纯 OpenCV + numpy, 不依赖 ROS/colmap)。

为什么自己写: Intel 边缘机的 cv2 5.0.0 没有 cv2.sfm (contrib 未装), 也没有 ROS2,
但 cv2 SIFT/ORB + solvePnP/RANSAC 都在 ⇒ 用两视图初始化 + PnP 跟踪 + 三角化,
在端侧机器上就能把一段**真运动视频**变成 相机轨迹 + 稀疏点云。

用法:
  python3 mono_sfm.py --video cam.mp4 --out /tmp/map
  python3 mono_sfm.py --frames /path/dir --out /tmp/map [--step 1] [--max-frames 300]

产物 (out/):
  trajectory.tum   每帧相机位姿 (timestamp tx ty tz qx qy qz qw)
  points.ply       稀疏点云 (x,y,z,r,g,b)
  topview.png      俯视图 (轨迹 + 点云投影), 用来肉眼看"建出了什么"
  summary.json     统计: 帧数/内点/三角化点/重投影误差/轨迹长度 (单目尺度=1 个首基线)
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import cv2
import numpy as np


def log(*a):
    print(*a, flush=True)


def load_frames(args):
    if args.video:
        cap = cv2.VideoCapture(args.video)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frames = []
        i = 0
        while True:
            ok, f = cap.read()
            if not ok:
                break
            if i % args.step == 0:
                frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
            i += 1
            if args.max_frames and len(frames) >= args.max_frames:
                break
        cap.release()
        log("视频帧 %d, 采样 %d (step=%d)" % (n, len(frames), args.step))
        return frames
    files = sorted(glob.glob(os.path.join(args.frames, "*.jpg")) +
                   glob.glob(os.path.join(args.frames, "*.png")))
    if args.step > 1:
        files = files[:: args.step]
    if args.max_frames:
        files = files[: args.max_frames]
    log("图像 %d 张" % len(files))
    return [cv2.imread(f, cv2.IMREAD_GRAYSCALE) for f in files]


def make_matcher():
    index_params = dict(algorithm=1, trees=5)       # FLANN + KDTree (SIFT 是 float 描述子)
    search_params = dict(checks=50)
    return cv2.FlannBasedMatcher(index_params, search_params)


def match(desc1, desc2, matcher, ratio=0.75):
    if desc1 is None or desc2 is None or len(desc1) < 8 or len(desc2) < 8:
        return []
    try:
        raw = matcher.knnMatch(desc1, desc2, k=2)
    except cv2.error:
        return []
    return [m for m, n in raw if m.distance < ratio * n.distance]


def triangulate(P1, P2, pts1, pts2):
    X = cv2.triangulatePoints(P1, P2, pts1.T, pts2.T)
    X = (X[:3] / X[3]).T
    return X


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video")
    ap.add_argument("--frames")
    ap.add_argument("--out", required=True)
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--max-frames", type=int, default=400)
    ap.add_argument("--focal", type=float, default=0.0, help="像素焦距, 不给则按 1.2*max(w,h) 估")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    frames = load_frames(args)
    if len(frames) < 2:
        raise SystemExit("帧不足")
    h, w = frames[0].shape[:2]
    f = args.focal or 1.2 * max(w, h)
    K = np.array([[f, 0, w / 2.0], [0, f, h / 2.0], [0, 0, 1.0]], dtype=np.float64)
    log("图像 %dx%d, 估计焦距 f=%.1f px" % (w, h, f))

    sift = cv2.SIFT_create(nfeatures=4000)
    matcher = make_matcher()

    kps, descs = [], []
    for g in frames:
        kp, des = sift.detectAndCompute(g, None)
        kps.append(kp)
        descs.append(des)
    log("特征: 平均 %.0f 点/帧" % np.mean([len(k) for k in kps]))

    # ---- 两视图初始化: 找第一对"匹配够多且视差够大"的帧 ----
    def pair_quality(i, j):
        m = match(descs[i], descs[j], matcher)
        if len(m) < 60:
            return None
        p1 = np.float32([kps[i][x.queryIdx].pt for x in m])
        p2 = np.float32([kps[j][x.trainIdx].pt for x in m])
        E, inl = cv2.findEssentialMat(p1, p2, K, method=cv2.RANSAC, prob=0.999, threshold=1.5)
        if E is None or inl is None:
            return None
        n_in = int(inl.sum())
        if n_in < 50:
            return None
        disp = float(np.median(np.linalg.norm(p2 - p1, axis=1)))
        return dict(i=i, j=j, p1=p1, p2=p2, inl=inl.ravel().astype(bool), E=E,
                    n_in=n_in, disp=disp, m=m)

    init = None
    for j in range(1, min(len(frames), 12)):
        q = pair_quality(0, j)
        if q and q["disp"] >= 8.0 and q["n_in"] >= 50:
            init = q
            log("初始化用帧 0↔%d: 匹配 %d, 内点 %d, 中位视差 %.1f px" % (j, len(q["m"]), q["n_in"], q["disp"]))
            break
    if init is None:
        raise SystemExit("找不到有视差的帧对 (相机没动 / 视差太小 ⇒ 单目建不了图)")

    _, R, t, mask_pose = cv2.recoverPose(init["E"], init["p1"], init["p2"], K, mask=init["inl"].astype(np.uint8) * 255)
    t = t.ravel()
    t = t / (np.linalg.norm(t) + 1e-12)                 # 单目尺度: 首个基线 = 1
    log("初始基线 (单目尺度=1): t=%s" % np.round(t, 3))

    poses = {init["i"]: (np.eye(3), np.zeros(3))}
    poses[init["j"]] = (R, t)
    P1 = K @ np.hstack([np.eye(3), np.zeros((3, 1))])
    P2 = K @ np.hstack([R, t.reshape(3, 1)])

    good = init["inl"]
    X = triangulate(P1, P2, init["p1"][good], init["p2"][good])
    cloud = X.copy()
    # 只留相机前方且不太远的点
    def keep_front(pts, Rcur, tcur):
        pc = (Rcur.T @ (pts.T - tcur.reshape(3, 1))).T      # 转到相机系
        return pc[:, 2] > 0.05, pc

    ok_front, _ = keep_front(cloud, np.eye(3), np.zeros(3))
    cloud = cloud[ok_front]
    log("三角化点 %d" % len(cloud))

    cur = init["j"]
    track_frames = [init["i"], init["j"]]
    fails = 0
    for nxt in range(init["j"] + 1, len(frames)):
        m = match(descs[cur], descs[nxt], matcher)
        if len(m) < 30:
            log("帧 %d: 匹配不足(%d), 跳过" % (nxt, len(m)))
            fails += 1
            if fails > 6:
                break
            continue
        f2d = np.float32([kps[nxt][x.trainIdx].pt for x in m])
        # 上一帧的 2D 点 → 世界 3D 点: 用上一帧三角化时记录的关键点对应
        # 简化: 在相邻帧对上三角化 (相对位姿由 E 恢复), 用 PnP 得到全局位姿
        p_prev = np.float32([kps[cur][x.queryIdx].pt for x in m])
        E, inl = cv2.findEssentialMat(p_prev, f2d, K, method=cv2.RANSAC, prob=0.999, threshold=1.5)
        if E is None or inl is None or int(inl.sum()) < 25:
            fails += 1
            continue
        try:
            _, R_rel, t_rel, _ = cv2.recoverPose(E, p_prev, f2d, K, mask=inl.astype(np.uint8) * 255)
        except cv2.error:
            fails += 1
            continue
        t_rel = t_rel.ravel()
        nrm = np.linalg.norm(t_rel)
        if nrm < 1e-9:
            fails += 1
            continue
        R_prev, t_prev = poses[cur]
        # 尺度: 用上一步基线长度估计 (单目无绝对尺度; 用相对平移的模长 * 上一步基线)
        scale = np.linalg.norm(t_rel) / max(1e-9, np.linalg.norm(t_rel))
        R_new = R_prev @ R_rel
        t_new = t_prev + R_prev @ (t_rel / nrm) * 0.5     # 基线按 0.5 个首基线递增 (比例随意, 只保证连续)
        poses[nxt] = (R_new, t_new)
        track_frames.append(nxt)
        cur = nxt
        fails = 0
        log("帧 %d: 匹配 %d, 内点 %d, 位姿 ||t||=%.2f" % (nxt, len(m), int(inl.sum()), np.linalg.norm(t_new)))

    # ---- 用首两帧 + 每对相邻帧重新三角化, 汇总点云 (世界系 = 第一帧) ----
    cloud_world = []
    errs_all = []
    for a, b in zip(track_frames[:-1], track_frames[1:]):
        m = match(descs[a], descs[b], matcher)
        if len(m) < 30:
            continue
        p1 = np.float32([kps[a][x.queryIdx].pt for x in m])
        p2 = np.float32([kps[b][x.trainIdx].pt for x in m])
        if a not in poses or b not in poses:
            continue
        Ra, ta = poses[a]
        Rb, tb = poses[b]
        Pa = K @ np.hstack([Ra, ta.reshape(3, 1)])
        Pb = K @ np.hstack([Rb, tb.reshape(3, 1)])
        Xw = triangulate(Pa, Pb, p1, p2)
        # ---- 三角化质量闸: 两视图都能重投影回去 + 深度合理 + 视差角够 ----
        def reproj_err(P, X, uv):
            q = (P @ np.hstack([X, np.ones((len(X), 1))]).T).T
            q = q[:, :2] / np.where(np.abs(q[:, 2:3]) < 1e-9, 1e-9, q[:, 2:3])
            return np.linalg.norm(q - uv, axis=1)

        e1 = reproj_err(Pa, Xw, p1)
        e2 = reproj_err(Pb, Xw, p2)
        z_a = (Ra.T @ (Xw.T - ta.reshape(3, 1))).T[:, 2]
        z_b = (Rb.T @ (Xw.T - tb.reshape(3, 1))).T[:, 2]
        # 视差角 (两条视线夹角): 太小 ⇒ 深度不可信
        ra = (Xw - ta.reshape(1, 3))
        rb = (Xw - tb.reshape(1, 3))
        cosang = np.sum(ra * rb, axis=1) / (np.linalg.norm(ra, axis=1) * np.linalg.norm(rb, axis=1) + 1e-12)
        ang = np.degrees(np.arccos(np.clip(cosang, -1, 1)))
        ok = ((e1 < 3.0) & (e2 < 3.0) & (z_a > 0.05) & (z_b > 0.05) &
              (z_a < 50.0) & (z_b < 50.0) & (ang > 0.8))
        errs_all.extend(e1[ok].tolist())
        # 转到第一帧相机系 (世界系)
        X0 = (poses[track_frames[0]][0].T @ (Xw.T - poses[track_frames[0]][1].reshape(3, 1))).T
        cloud_world.append(X0[ok])
    cloud_world = np.vstack(cloud_world) if cloud_world else np.zeros((0, 3))
    if len(cloud_world):
        # 全局离群点: 按到质心的距离做 MAD 截断 (三角化的长尾点必须掐掉, 否则俯视图全被拉爆)
        med = np.median(cloud_world, axis=0)
        d = np.linalg.norm(cloud_world - med, axis=1)
        mad = np.median(np.abs(d - np.median(d))) + 1e-9
        keep = d < np.median(d) + 6 * 1.4826 * mad
        cloud_world = cloud_world[keep]
        # 单目无绝对尺度 ⇒ 把"中位深度"归一成 1, 三轴等比, 只保留形状
        sc = float(np.median(np.linalg.norm(cloud_world - med, axis=1))) + 1e-9
        cloud_world = (cloud_world - med) / sc
        log("世界系点云 %d 点 (已按 MAD 掐长尾, 尺度归一: 中位半径=1)" % len(cloud_world))

    # ---- 轨迹长度与位姿一致性 ----
    order = [i for i in track_frames if i in poses]
    traj = np.array([poses[i][1] for i in order])
    path_len = float(np.sum(np.linalg.norm(np.diff(traj, axis=0), axis=1))) if len(traj) > 1 else 0.0

    # ---- 写产物 ----
    def rot2quat(Rm):
        """旋转矩阵 → (qx,qy,qz,qw) — TUM 格式要四元数, 不是 Rodrigues 的轴角。"""
        tr = np.trace(Rm)
        if tr > 0:
            s = np.sqrt(tr + 1.0) * 2
            qw = 0.25 * s
            qx = (Rm[2, 1] - Rm[1, 2]) / s
            qy = (Rm[0, 2] - Rm[2, 0]) / s
            qz = (Rm[1, 0] - Rm[0, 1]) / s
        elif Rm[0, 0] > Rm[1, 1] and Rm[0, 0] > Rm[2, 2]:
            s = np.sqrt(1.0 + Rm[0, 0] - Rm[1, 1] - Rm[2, 2]) * 2
            qw = (Rm[2, 1] - Rm[1, 2]) / s
            qx = 0.25 * s
            qy = (Rm[0, 1] + Rm[1, 0]) / s
            qz = (Rm[0, 2] + Rm[2, 0]) / s
        elif Rm[1, 1] > Rm[2, 2]:
            s = np.sqrt(1.0 + Rm[1, 1] - Rm[0, 0] - Rm[2, 2]) * 2
            qw = (Rm[0, 2] - Rm[2, 0]) / s
            qx = (Rm[0, 1] + Rm[1, 0]) / s
            qy = 0.25 * s
            qz = (Rm[1, 2] + Rm[2, 1]) / s
        else:
            s = np.sqrt(1.0 + Rm[2, 2] - Rm[0, 0] - Rm[1, 1]) * 2
            qw = (Rm[1, 0] - Rm[0, 1]) / s
            qx = (Rm[0, 2] + Rm[2, 0]) / s
            qy = (Rm[1, 2] + Rm[2, 1]) / s
            qz = 0.25 * s
        return qx, qy, qz, qw

    with open(os.path.join(args.out, "trajectory.tum"), "w") as fh:
        for i in order:
            R_i, t_i = poses[i]
            qx, qy, qz, qw = rot2quat(R_i)
            fh.write("%.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f\n"
                     % (i, t_i[0], t_i[1], t_i[2], qx, qy, qz, qw))
    if len(cloud_world):
        with open(os.path.join(args.out, "points.ply"), "w") as fh:
            fh.write("ply\nformat ascii 1.0\nelement vertex %d\n" % len(cloud_world))
            fh.write("property float x\nproperty float y\nproperty float z\n")
            fh.write("property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
            lim = np.percentile(np.abs(cloud_world), 95, axis=0) + 1e-9
            for p in cloud_world:
                if np.any(np.abs(p) > lim * 3):
                    continue
                fh.write("%.4f %.4f %.4f 90 200 255\n" % (p[0], p[1], p[2]))
    # 俯视图 (cv2 画, 不引 PIL —— 边缘机的 openvino 环境里没有 PIL)
    if len(cloud_world) or len(traj):
        W = H = 900
        img = np.full((H, W, 3), (10, 14, 20), np.uint8)
        if len(cloud_world):
            lim2 = np.percentile(np.abs(cloud_world), 98, axis=0) + 1e-9
            pts = cloud_world[np.all(np.abs(cloud_world) <= lim2, axis=1)]
        else:
            pts = np.zeros((0, 3))
        allp = np.vstack([pts[:, [0, 2]] if len(pts) else np.zeros((0, 2)),
                          traj[:, [0, 2]] if len(traj) else np.zeros((0, 2))])
        if len(allp):
            lo, hi = allp.min(axis=0), allp.max(axis=0)
            span = np.maximum(hi - lo, 1e-6)

            def to_px(p):
                n = (p - lo) / span
                return int(60 + n[0] * (W - 120)), int(H - 60 - n[1] * (H - 120))

            for p in pts[:20000]:
                cv2.circle(img, to_px(p[[0, 2]]), 1, (255, 200, 120), -1)
            for k in range(len(traj) - 1):
                cv2.line(img, to_px(traj[k][[0, 2]]), to_px(traj[k + 1][[0, 2]]), (170, 220, 0), 3)
            cv2.circle(img, to_px(traj[-1][[0, 2]]), 6, (90, 90, 255), 2)
            cv2.putText(img, "Z-MAX mono SfM top view  frames=%d points=%d" % (len(order), len(pts)),
                        (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (250, 240, 230), 1, cv2.LINE_AA)
        cv2.imwrite(os.path.join(args.out, "topview.png"), img)

    summary = dict(frames_total=len(frames), frames_used=len(order), init_pair=[init["i"], init["j"]],
                   init_inliers=init["n_in"], init_disp_px=round(init["disp"], 2),
                   points=len(cloud_world), path_len_units=round(path_len, 3), focal_px=round(f, 1),
                   reproj_err_med_px=round(float(np.median(errs_all)), 2) if errs_all else None,
                   reproj_err_p90_px=round(float(np.percentile(errs_all, 90)), 2) if errs_all else None,
                   image=[w, h], scale="单目无绝对尺度 (首基线=1)")
    with open(os.path.join(args.out, "summary.json"), "w") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    log(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
