#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📦 采集会话 → 3DGS 数据集 (cameras.json + images/ + depth/)

为什么要有这一步:
  map_recorder_550c.py 采到的是「臂位姿 + 相机帧 + 深度」, 而 3DGS 训练服务 (8814)
  要的是 cameras.json (convention=T_cam2world, OpenCV 光学系) + images/ (+ depth/ 做初始点云)。
  位姿要真值化: 相机装在臂上 ⇒ T_base2cam = T_base2tcp @ T_cam2tool(手眼), T_cam2world = inv。
  只拿 TCP 位姿当相机位姿, 建出来的图会整体偏 244mm 且方向错 (手眼模长就是那个 244.1mm)。

  姿态来源: recorder 现在存 tcp_rpy (rad); 早期会话只有 xyz ⇒ 直接报错, 不静默保障。

用法 (550C):
  python tools/map_build_3dgs_ds.py --session <session dir> --out /tmp/gs_ds --tar /tmp/gs_ds.tar.gz
"""
import argparse
import json
import math
import os
import os.path as osp
import sys
import tarfile

import cv2
import numpy as np

MODELS = os.environ.get("ZMAX_MODELS", "/home/intel/zmax_550c/models")


def rpy_rad_to_R(rx, ry, rz):
    """与 gs_autocap_daemon._rpy_to_R 同约定 (rad 版)."""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return np.array([[cy * cz, cz * sx * sy - cx * sz, cx * cz * sy + sx * sz],
                     [cy * sz, cx * cz + sx * sy * sz, -cz * sx + cx * sy * sz],
                     [-sy, cy * sx, cx * cy]], float)


def load_handeye(path):
    d = json.load(open(path, encoding="utf-8"))
    X = np.array(d["T_cam2tool"], float)
    return X, d


def load_calib(path):
    d = json.load(open(path, encoding="utf-8"))
    K = np.array(d["K"], float).reshape(3, 3)
    dist = np.array(d.get("dist") or [0, 0, 0, 0, 0], float).reshape(-1, 1)
    wh = d.get("image_size") or [640, 480]
    return K, dist, int(wh[0]), int(wh[1]), d


def sharp(jpg_gray):
    return float(cv2.Laplacian(jpg_gray, cv2.CV_64F).var())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tar", default="")
    ap.add_argument("--max-views", type=int, default=320)
    ap.add_argument("--min-gap-mm", type=float, default=12.0, help="相邻保留帧的最小位移")
    ap.add_argument("--min-gap-deg", type=float, default=1.5, help="最小转角 (度)")
    ap.add_argument("--sharp-pct", type=float, default=15.0, help="丢弃清晰度最低的百分比")
    ap.add_argument("--no-undistort", action="store_true")
    # 🔴 2026-11-19 老倪「还是很模糊」的根因之一:
    #   real_cam_calib.json 的 image_size 是 640x480, 而臂上 D405 实际出 1280x720 ⇒
    #   老逻辑把 1280x720 原图按 640x480 的内参去畸变 ⇒ 直接掉一半分辨率。
    #   --native: 以原图尺寸建集 (K 按 s=srcW/calibW 线性放大, dist 是归一化量不用改)。
    ap.add_argument("--native", action="store_true",
                    help="按原图分辨率建集(内参同比放大), 默认关=沿用标定的 640x480")
    # 🔴 2026-11-19 实测: 臂上 D405 出 1280x720(16:9), 而 real_cam_calib.json 是 640x480(4:3) ⇒
    #   比例不一致不能硬放大; 且老逻辑用 640x480 的 map 去 remap 1280x720 原图,
    #   实际只取到了**左上角 640x480 那一块**(与留出真值对比: 左上差 4.4 / 中心差 60.5 / 整幅缩放差 42.7)
    #   ⇒ 训练集一直是画面角落, 插口根本不在里面。改成"居中裁成标定比例 + 内参同比缩放"。
    ap.add_argument("--crop", default="", help="居中裁到 WxH (须与标定同比例), 例 960x720")
    a = ap.parse_args()

    X, hd = load_handeye(osp.join(MODELS, "handeye_state.json"))
    K, dist, cw, ch, cd = load_calib(osp.join(MODELS, "real_cam_calib.json"))
    if a.native:
        _one = None
        for _ln in open(osp.join(a.session, "poses.jsonl"), encoding="utf-8"):
            _r = json.loads(_ln)
            _p = osp.join(a.session, "frames", _r["file"])
            if osp.isfile(_p):
                _im = cv2.imread(_p, cv2.IMREAD_UNCHANGED)
                if _im is not None:
                    _one = (_im.shape[1], _im.shape[0])
                    break
        if _one and _one != (cw, ch):
            _sx, _sy = _one[0] / float(cw), _one[1] / float(ch)
            if abs(_sx - _sy) > 0.02:
                raise SystemExit("原图 %r 与标定 %dx%d 比例不一致, 不敢猜内参" % (_one, cw, ch))
            K = K.copy()
            K[0, 0] *= _sx; K[1, 1] *= _sx; K[0, 2] *= _sx; K[1, 2] *= _sx
            print("[内参] 标定 %dx%d → 原图 %dx%d, K 同比放大 %.3f 倍" % (cw, ch, _one[0], _one[1], _sx))
            cw, ch = _one
        elif _one == (cw, ch):
            print("[内参] 原图就是标定分辨率 %dx%d, 无需放大" % _one)
    if a.crop:
        _cw2, _ch2 = [int(v) for v in a.crop.lower().split("x")]
        _one = None
        for _ln in open(osp.join(a.session, "poses.jsonl"), encoding="utf-8"):
            _r = json.loads(_ln)
            _p = osp.join(a.session, "frames", _r["file"])
            if osp.isfile(_p):
                _im = cv2.imread(_p, cv2.IMREAD_UNCHANGED)
                if _im is not None:
                    _one = (_im.shape[1], _im.shape[0])
                    break
        if not _one:
            raise SystemExit("读不到原图, 不能用 --crop")
        _sx, _sy = _cw2 / float(cw), _ch2 / float(ch)
        if abs(_sx - _sy) > 0.02:
            raise SystemExit("--crop %dx%d 与标定 %dx%d 比例不一致(%.3f vs %.3f)" % (_cw2, _ch2, cw, ch, _sx, _sy))
        _x0, _y0 = (_one[0] - _cw2) // 2, (_one[1] - _ch2) // 2
        K = K.copy()
        K[0, 0] *= _sx; K[1, 1] *= _sy
        K[0, 2] = K[0, 2] * _sx - _x0
        K[1, 2] = K[1, 2] * _sy - _y0
        print("[裁切] 原图 %dx%d → 居中 %dx%d (偏移 %d,%d) · K 同比放大 %.3f" % (
            _one[0], _one[1], _cw2, _ch2, _x0, _y0, _sx))
        cw, ch = _cw2, _ch2
        _crop_box = (_x0, _y0, _cw2, _ch2)
    else:
        _crop_box = None
    if hd.get("ok") not in (True, "True"):
        raise SystemExit("⛔ 手眼标定没通过 (ok=%r), 不能用来建 3DGS" % (hd.get("ok"),))

    recs = []
    for ln in open(osp.join(a.session, "poses.jsonl"), encoding="utf-8"):
        ln = ln.strip()
        if ln:
            recs.append(json.loads(ln))
    if not recs:
        raise SystemExit("⛔ 会话里没有位姿")
    if not recs[0].get("tcp_rpy"):
        raise SystemExit("⛔ 这批会话只有 xyz 没有 rpy ⇒ 做不了手眼变换。"
                         "用新版 map_recorder_550c.py 重采(带 --depth)。")

    # ── 1) 全量算 T_cam2world, 顺手校验手眼模长 ───────────────────────
    allv = []
    for r in recs:
        t = np.array(r["tcp_mm"], float) / 1000.0
        R = rpy_rad_to_R(*r["tcp_rpy"])
        T_tcp = np.eye(4)
        T_tcp[:3, :3], T_tcp[:3, 3] = R, t
        T_cam = T_tcp @ X                                  # base←cam
        # 单位: t 是米, 手眼模长 eye_len 是毫米 ⇒ 这里必须换算成 mm 再比, 否则恒差 1000 倍
        off = float(np.linalg.norm(T_cam[:3, 3] - t)) * 1000.0   # 必须 ≈ |t_mm|
        allv.append({"i": r["i"], "file": r["file"], "tcp_mm": r["tcp_mm"],
                     "tcp_rpy": r["tcp_rpy"], "depth": r.get("depth"),
                     "T_cam2world": np.linalg.inv(T_cam).tolist(), "cam_off_mm": off})
    eye_len = float(np.linalg.norm(np.array(hd["t_mm"], float)))
    offs = [v["cam_off_mm"] for v in allv]
    print("[手眼] |t|=%.1fmm · 逐帧相机-法兰距离 %.1f~%.1fmm (应恒等) · 残差 %.2f/%.2f mm/°" % (
        eye_len, min(offs), max(offs), hd.get("resid_trans_mm_rms"), hd.get("resid_rot_deg_rms")))
    if abs(sum(offs) / len(offs) - eye_len) > 2.0:
        raise SystemExit("⛔ 手眼方向用错: 平均 %.1f ≠ %.1f mm" % (sum(offs) / len(offs), eye_len))

    # ── 2) 清晰度 + 视角抽稀 ────────────────────────────────────────────
    for v in allv:
        g = cv2.imread(osp.join(a.session, "frames", v["file"]), cv2.IMREAD_GRAYSCALE)
        v["sharp"] = sharp(g) if g is not None else 0.0
    sh = sorted(v["sharp"] for v in allv)
    thr = sh[max(0, int(len(sh) * a.sharp_pct / 100.0) - 1)]
    keep = []
    for v in allv:
        if v["sharp"] < thr:
            continue
        if keep:
            dmm = float(np.linalg.norm(np.array(v["tcp_mm"]) - np.array(keep[-1]["tcp_mm"])))
            ddeg = max(abs((v["tcp_rpy"][k] - keep[-1]["tcp_rpy"][k]) * 180.0 / math.pi) for k in range(3))
            if dmm < a.min_gap_mm and ddeg < a.min_gap_deg:
                continue
        keep.append(v)
    if len(keep) > a.max_views:
        step = len(keep) / float(a.max_views)
        keep = [keep[min(int(i * step), len(keep) - 1)] for i in range(a.max_views)]
    print("[抽稀] 原始 %d 帧 → 清晰度阈值 %.1f → 保留 %d 帧" % (len(allv), thr, len(keep)))

    # ── 3) 写数据集 ────────────────────────────────────────────────────
    ds = a.out
    os.makedirs(osp.join(ds, "images"), exist_ok=True)
    os.makedirs(osp.join(ds, "depth"), exist_ok=True)
    map1 = map2 = None
    if not a.no_undistort and float(np.abs(dist).max()) > 0.02:
        map1, map2 = cv2.initUndistortRectifyMap(K, dist, None, K, (cw, ch), cv2.CV_16SC2)
    frames = []
    n_depth = 0
    for n, v in enumerate(keep):
        src = osp.join(a.session, "frames", v["file"])
        img = cv2.imread(src, cv2.IMREAD_COLOR)
        if img is None:
            continue
        if _crop_box is not None:
            _x0, _y0, _w, _h = _crop_box
            img = img[_y0:_y0 + _h, _x0:_x0 + _w]
        if map1 is not None:
            img = cv2.remap(img, map1, map2, cv2.INTER_LINEAR)
        fn = "%05d.jpg" % n
        cv2.imwrite(osp.join(ds, "images", fn), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        dep = osp.join(a.session, "depth", osp.splitext(v["file"])[0] + ".png")
        dep_ok = False
        if osp.exists(dep):
            d16 = cv2.imread(dep, cv2.IMREAD_UNCHANGED)
            if d16 is not None and d16.dtype == np.uint16:
                if map1 is not None:
                    d16 = cv2.remap(d16, map1, map2, cv2.INTER_NEAREST)
                cv2.imwrite(osp.join(ds, "depth", "%05d.png" % n), d16)
                dep_ok = True
                n_depth += 1
        frames.append({"file": fn, "T_cam2world": v["T_cam2world"], "pose": v["tcp_rpy"],
                       "sharp": round(v["sharp"], 1), "depth": dep_ok, "ts": v["ts"] if "ts" in v else 0})
    Kout = K.tolist()
    cam = {"width": cw, "height": ch, "K": Kout, "convention": "T_cam2world",
           "note": "map_build_3dgs_ds: 真机臂位姿 + 手眼 T_cam2tool; K 来自 real_cam_calib(ROS camera_info)",
           "K_src": "real_cam_calib.json %dx%d" % (cw, ch),
           "handeye_applied": True, "handeye_eye_mm": eye_len,
           "dist_undistorted": bool(map1 is not None), "session": a.session,
           "frames": frames}
    json.dump(cam, open(osp.join(ds, "cameras.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[数据集] %s · %d 帧 (深度 %d) · %dx%d · undistort=%s"
          % (ds, len(frames), n_depth, cw, ch, map1 is not None))

    # ── 4) 覆盖度体检: 回答"跑两次够不够" ──────────────────────────────
    P = np.array([np.array(v["tcp_mm"]) for v in keep], float) / 1000.0
    ext = (P.max(0) - P.min(0)) * 1000.0
    vox = set(tuple(np.round(p / 0.03).astype(int)) for p in P)          # 30mm 体素
    near = [min(np.linalg.norm(P[i] - P[j]) for j in range(len(P)) if j != i) for i in range(len(P))]
    cov = {"views": len(frames), "depth_views": n_depth,
           "extent_mm": [round(float(x), 1) for x in ext],
           "voxel30mm": len(vox), "nn_spacing_mm_median": round(float(np.median(near)) * 1000, 1)}
    print("[覆盖] 包围盒 %s mm · 30mm 体素 %d 个 · 最近邻间距中位 %.1fmm" % (
        cov["extent_mm"], len(vox), cov["nn_spacing_mm_median"]))
    json.dump(cov, open(osp.join(ds, "coverage.json"), "w"), ensure_ascii=False, indent=1)

    if a.tar:
        with tarfile.open(a.tar, "w:gz") as tf:
            tf.add(osp.join(ds, "cameras.json"), arcname="cameras.json")
            tf.add(osp.join(ds, "images"), arcname="images")
            if n_depth:
                tf.add(osp.join(ds, "depth"), arcname="depth")
        print("[打包] %s · %.1f MB" % (a.tar, osp.getsize(a.tar) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
