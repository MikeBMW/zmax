#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_dataset.py — 把 gs_capture 采集会话做成 3DGS 数据集 (位姿已知, 不用 COLMAP/SfM)

链路(每一环都有真源, 不猜):
  图像  = 臂上 D405 的 Orin 高速 JPEG 通道 (640x480 bgr8)
  内参  = models/real_cam_calib.json (ROS camera_info 出厂内参 K + 5 参畸变; 去畸变用 getOptimalNewCameraMatrix(alpha=0))
  外参  = T_base_cam = T_base_tcp · T_cam2tool
            · T_base_tcp 逐帧来自 rokae_sdk/tcp_out/latest.json (ROKAE SDK 直读 endInRef, 页面同源)
            · T_cam2tool 来自 handeye_state.json (TSAI, 残差 0.06mm/0.0046° RMS)
  选帧  = 6D 位姿最远点贪心(平移+朝向都要分散) —— 上万帧里大量是同一视角连拍, 全喂进去只是白烧 GPU

输出: <out>/images/*.jpg(去畸变) + <out>/cameras.json(每帧 4x4 T_cam2world + 内参, OpenCV 光学系 x右y下z前)
      + <out>/transforms.json(nerfstudio 风格, 供别的工具读) + <out>/meta.json

用法:
  python3 tools/gs_dataset.py --session ~/zmax/zmax_data/gs_scan/scan_XXXX --out ~/zmax/zmax_data/gs_data/scan_XXXX \
      [--max-frames 300] [--min-gap-ms 40] [--undistort-keep-all]
"""
from __future__ import annotations
import argparse, json, math, os, shutil, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIB = os.path.join(ROOT, "models/real_cam_calib.json")
HANDEYE = os.path.expanduser("~/zmax/zmax_data/handeye_state.json")


def quat_to_R(x, y, z, w):
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]], float)


def T_of(pos, quat):
    T = np.eye(4)
    T[:3, :3] = quat_to_R(*quat)
    T[:3, 3] = pos
    return T


def _slerp(q0, q1, a):
    q0 = np.array(q0, float); q1 = np.array(q1, float)
    d = float(np.dot(q0, q1))
    if d < 0:
        q1 = -q1; d = -d
    if d > 0.9995:
        q = q0 + a * (q1 - q0)
    else:
        th0 = math.acos(max(-1.0, min(1.0, d))); th = th0 * a
        q2 = q1 - q0 * d; q2 /= max(np.linalg.norm(q2), 1e-12)
        q = q0 * math.cos(th) + q2 * math.sin(th)
    return (q / max(np.linalg.norm(q), 1e-12)).tolist()


def _pose_at(rows, t):
    """在 rows(按时间升序) 上取时刻 t 的位姿(位置线性、姿态 slerp)。t 超出范围时夹到端点。"""
    if not rows:
        return None
    if t <= rows[0]["t"]:
        return rows[0]
    if t >= rows[-1]["t"]:
        return rows[-1]
    lo = 0
    for i in range(1, len(rows)):
        if rows[i]["t"] >= t:
            lo = i - 1
            break
    a, b = rows[lo], rows[lo + 1]
    w = 0.0 if b["t"] <= a["t"] else (t - a["t"]) / (b["t"] - a["t"])
    pos = [a["pos"][k] + w * (b["pos"][k] - a["pos"][k]) for k in range(3)]
    return {"file": a["file"], "t": t, "pos": pos, "quat": _slerp(a["quat"], b["quat"], w),
            "gap_ms": round(a["gap_ms"] + w * (b["gap_ms"] - a["gap_ms"]), 2), "ts": a.get("ts")}


def load_frames(session, min_gap_ms, hash_file=None, dedup=True, latency_ms=0.0):
    """读会话帧表。dedup=True 时按**图像内容(md5)**去重:
    🔴 本机采集实测的坑 —— 取图端点(/frame.jpg)的有效帧率远低于 8Hz 取图率, 同一张图会被
    连续取到十几次, 而每次取图都记了一个**不同的 TCP 位姿**。若不去重, 数据集里会出现
    "同一张图配十几个不同位姿"的矛盾监督 ⇒ 连训练视角都拟合不上(实测训练视角 PSNR 卡在 16dB,
    留出 11~13dB, 低于"填常数"平凡基线)。去重后每张唯一图只保留一个位姿。
    位姿取"该图首次出现的时刻 - latency_ms"(图像内容对应的时刻; 取图延迟用 --latency-ms 估)。"""
    fp = os.path.join(os.path.expanduser(session), "frames.jsonl")
    out = []
    for ln in open(fp, encoding="utf-8"):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if not r.get("file"):
            continue
        t_img = r.get("t_mono_fetch1") or 0.0
        p = r.get("pose_after") or r.get("pose_before")
        if not (isinstance(p, dict) and all(k in p for k in ("x", "y", "z", "qx", "qy", "qz", "qw"))):
            continue
        tw = r.get("t_wall") or [0.0]
        gap_ms = abs(float(tw[0]) - float(p.get("ts") or tw[0])) * 1000.0   # 位姿龄(wall 钟, 与取图同轮)
        if gap_ms > min_gap_ms:
            continue
        out.append({"file": r["file"], "t": t_img,
                    "pos": [float(p["x"]), float(p["y"]), float(p["z"])],
                    "quat": [float(p[k]) for k in ("qx", "qy", "qz", "qw")],
                    "gap_ms": round(gap_ms, 2), "ts": p.get("ts"),
                    "md5": r.get("md5"), "dup": bool(r.get("dup"))})
    if not dedup:
        return out

    h = {}
    if hash_file and os.path.exists(hash_file):
        for ln in open(hash_file, encoding="utf-8"):
            parts = ln.split()
            if len(parts) >= 2:
                h[os.path.basename(parts[-1])] = parts[0]
    if not h:
        print("⚠️ 没有图像 md5 表(--hash-file), 无法去重; 去重是质量的关键, 请先生成")
        return out
    groups, seen = [], {}
    for e in out:
        # 新采集器直接带 md5(内容没变不落盘); 老会话没有 ⇒ 退回外部 hash 表
        k = e.get("md5") or h.get(e["file"], "?" + e["file"])
        if k in seen:
            groups[seen[k]].append(e)
        else:
            seen[k] = len(groups)
            groups.append([e])
    ded = []
    for g in groups:
        first = g[0]
        if latency_ms:
            p2 = _pose_at(out, first["t"] - latency_ms / 1000.0)
            if p2:
                first = dict(first, pos=p2["pos"], quat=p2["quat"])
        ded.append(first)
    print("去重: 取图 %d 次 → 唯一图像 %d 张 (重复率 %.1f%%)"
          % (len(out), len(ded), 100.0 * (1 - len(ded) / max(1, len(out)))))
    return ded


def select(frames, T_tool_cam, max_frames):
    """6D 最远点贪心: 先挑位姿离群最远的, 再逐步挑离已选集合最远的。"""
    if max_frames <= 0 or len(frames) <= max_frames:
        return list(range(len(frames)))
    C = []
    for f in frames:
        T = T_of(np.array(f["pos"]), f["quat"]) @ T_tool_cam
        C.append(T)
    pos = np.array([T[:3, 3] for T in C])
    fwd = np.array([T[:3, :3] @ np.array([0, 0, 1.0]) for T in C])     # 光轴方向
    ctr = pos.mean(0)
    score = np.linalg.norm(pos - ctr, axis=1)
    sel = [int(np.argmax(score))]
    dmin = np.full(len(C), 1e9)
    while len(sel) < max_frames:
        i = sel[-1]
        dp = np.linalg.norm(pos - pos[i], axis=1)
        da = 1.0 - np.clip(fwd @ fwd[i], -1, 1)          # 朝向差(0~2)
        d = dp + 0.15 * da
        dmin = np.minimum(dmin, d)
        nxt = int(np.argmax(dmin))
        if dmin[nxt] <= 0:
            break
        sel.append(nxt)
    return sorted(sel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-frames", type=int, default=300)
    ap.add_argument("--min-gap-ms", type=float, default=40.0)
    ap.add_argument("--jpeg-quality", type=int, default=95)
    ap.add_argument("--hash-file", default="/home/ubuntu/zmax/zmax_data/gs_assets/scan_hashes.txt",
                    help="图像 md5 表(md5sum 输出), 用于按内容去重")
    ap.add_argument("--no-dedup", action="store_true", help="关闭去重(只做对照, 不建议)")
    ap.add_argument("--latency-ms", type=float, default=0.0,
                    help="取图延迟补偿: 位姿取 t_first - latency (图像内容对应的时刻)")
    args = ap.parse_args()

    import cv2
    calib = json.load(open(CALIB, encoding="utf-8"))
    K = np.array(calib["K"], float).reshape(3, 3)
    dist = np.array(calib["dist"], float).reshape(-1)
    W, H = int(calib["image_size"][0]), int(calib["image_size"][1])
    he = json.load(open(HANDEYE, encoding="utf-8"))
    T_tool_cam = np.array(he["T_cam2tool"], float).reshape(4, 4)      # cam→tool
    print("内参 K fx=%.2f fy=%.2f cx=%.2f cy=%.2f · dist=%s · %dx%d" % (K[0, 0], K[1, 1], K[0, 2], K[1, 2], list(np.round(dist, 5)), W, H))
    print("手眼 T_cam2tool 残差 %.3fmm / %.4f° (session %s)" % (he.get("resid_trans_mm_rms", -1), he.get("resid_rot_deg_rms", -1), he.get("session")))

    frames = load_frames(args.session, args.min_gap_ms, hash_file=args.hash_file,
                         dedup=not args.no_dedup, latency_ms=args.latency_ms)
    if not frames:
        print("❌ 会话里没有可用帧"); return 2
    p = np.array([f["pos"] for f in frames])
    print("会话 %s: 可用帧 %d · 位姿跨度 x%.1fmm y%.1fmm z%.1fmm"
          % (os.path.basename(os.path.normpath(args.session)), len(frames),
             np.ptp(p[:, 0]) * 1000, np.ptp(p[:, 1]) * 1000, np.ptp(p[:, 2]) * 1000))

    sel = select(frames, T_tool_cam, args.max_frames)
    print("选帧: %d → %d (6D 位姿最远点贪心)" % (len(frames), len(sel)))

    out = os.path.expanduser(args.out)
    idir = os.path.join(out, "images")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(idir, exist_ok=True)
    Knew, roi = cv2.getOptimalNewCameraMatrix(K, dist, (W, H), 0, (W, H))
    print("去畸变后内参 fx=%.2f fy=%.2f cx=%.2f cy=%.2f · 有效区 %s" % (Knew[0, 0], Knew[1, 1], Knew[0, 2], Knew[1, 2], roi))
    src = os.path.join(os.path.expanduser(args.session), "frames")
    recs = []
    n_bad = 0
    for n, i in enumerate(sel):
        f = frames[i]
        img = cv2.imread(os.path.join(src, f["file"]))
        if img is None:
            n_bad += 1
            continue
        und = cv2.undistort(img, K, dist, None, Knew)
        name = "img_%05d.jpg" % n
        cv2.imwrite(os.path.join(idir, name), und, [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality])
        T = T_of(np.array(f["pos"]), f["quat"]) @ T_tool_cam        # T_cam2world(base)
        recs.append({"file": name, "src": f["file"], "t": f["t"],
                     "T_cam2world": [list(map(float, row)) for row in T],
                     "pos": list(map(float, T[:3, 3]))})
    json.dump({"convention": "T_cam2world (base_link) · OpenCV 光学系 x右 y下 z前 · 未转 nerfstudio 的 OpenGL 系",
               "K": [list(map(float, r)) for r in Knew], "width": W, "height": H,
               "dist_removed": True, "frames": recs},
              open(os.path.join(out, "cameras.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # nerfstudio 风格(OpenGL 系: y 上, z 后) —— 给别的工具用
    flip = np.diag([1.0, -1.0, -1.0, 1.0])
    nsf = {"fl_x": float(Knew[0, 0]), "fl_y": float(Knew[1, 1]), "cx": float(Knew[0, 2]), "cy": float(Knew[1, 2]),
           "w": W, "h": H, "k1": 0.0, "k2": 0.0, "p1": 0.0, "p2": 0.0, "camera_model": "PINHOLE",
           "frames": [{"file_path": "images/" + r["file"],
                       "transform_matrix": [list(map(float, row)) for row in
                                            (np.array(r["T_cam2world"]) @ flip)]} for r in recs]}
    json.dump(nsf, open(os.path.join(out, "transforms.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    q = np.array([r["pos"] for r in recs])
    meta = {"session": os.path.abspath(os.path.expanduser(args.session)), "n_frames_used": len(recs),
            "n_bad_images": n_bad, "max_frames": args.max_frames, "K": [list(map(float, r)) for r in Knew],
            "dedup": (not args.no_dedup), "latency_ms": args.latency_ms, "n_unique_images": len(frames),
            "handeye_session": he.get("session"), "resid_trans_mm_rms": he.get("resid_trans_mm_rms"),
            "bbox_min": [float(v) for v in q.min(0)], "bbox_max": [float(v) for v in q.max(0)],
            "spread_mm": [float(v) for v in ((q.max(0) - q.min(0)) * 1000)],
            "note": "位姿已知重建(无 SfM); 视差基线 = 上表 spread_mm —— 太小则只能重建出浅浮雕, 做不出完整环境资产"}
    json.dump(meta, open(os.path.join(out, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 数据集 → %s" % out)
    print("   images/ %d 张(去畸变) · cameras.json · transforms.json · meta.json" % len(recs))
    print("   相机位姿包围盒 %s mm (视差基线)" % [round(v, 1) for v in meta["spread_mm"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
