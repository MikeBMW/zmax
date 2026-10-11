#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ar_calib_module.py — AR 场景的**光模块标定能力** (RealSense D435 ↔ base 外参)

老倪 2026-10-11: 「AR场景中, 要有光模块的标定能力, 你要回忆你之前是怎么标定YOLO的, 想好怎么开发 AOI功能」

回忆(为什么这么做): 之前标 YOLO 的口径是 —— **在役权重单点指针**(`models/yolo_peg_live.pt` 软链)+
**同口径真机帧评测**(检出帧率/conf)+「先量在役权重再谈训练」; 标定相机外参则是 **DLT 线性初值 + RQ 分解 + 非线性收细**
+「没外参就不画」。本工具把两者接起来: **YOLO 在 AR 相机里找光模块 → 深度给相机系 3D → 与该模块的 base 真值配对 → 解外参**。

三种用法(都不含新点位运动):
  detect   : 在 RealSense 当前帧里跑在役 YOLO, 报 bbox/conf + 深度给出的相机系 3D (零运动, 现在就可用)
  pair     : 追加一对 (uv=检测框中心, base=TCP 真值) —— 采集时把模块(或夹爪尖)停在**已示教的点位**上
  solve    : ≥5 对 → 用**出厂内参**只解 R,t (DLT 初值) → 落 data/scene/cam_calib.json["rs"] + 重投影 RMS
  selftest : 合成相机自测(证明解算管线对, 不碰真机)

用法:
  gui-venv311/bin/python tools/ar_calib_module.py detect
  gui-venv311/bin/python tools/ar_calib_module.py pair --u 320 --v 240 --base x,y,z   # 或 --tcp-latest
  gui-venv311/bin/python tools/ar_calib_module.py solve
  gui-venv311/bin/python tools/ar_calib_module.py selftest
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
PAIRS = os.path.expanduser("~/zmax/zmax_data/ar_rs/calib_pairs_rs.json")
TCP_JSON = os.path.expanduser("~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json")
MODEL_LINK = os.path.join(ROOT, "models", "yolo_peg_live.pt")


def _yolo():
    """在役权重(软链单点指针) —— 与实时管线/GUI 同源, 不各写一份。"""
    from ultralytics import YOLO
    p = MODEL_LINK if os.path.exists(MODEL_LINK) else None
    if p is None:
        c = sorted(glob.glob(os.path.join(ROOT, "models", "**", "*.pt"), recursive=True))
        p = c[0] if c else None
    if p is None:
        raise SystemExit("找不到在役权重( models/yolo_peg_live.pt 或 models/**.pt )")
    return YOLO(p), p


def detect(conf=0.25, imgsz=640, save=True):
    """RealSense 当前帧里找光模块: bbox/conf + 深度相机系 3D。"""
    import cv2
    import realsense_source as RS
    L = RS.latest()
    img = L["color"]
    if img is None:
        return {"ok": False, "err": "RealSense 没有帧", "err_rs": L.get("err")}
    m, path = _yolo()
    r = m.predict(img, imgsz=imgsz, conf=conf, verbose=False)[0]
    out = {"ok": True, "model": os.path.relpath(path, ROOT), "n": len(r.boxes), "dets": []}
    for b in r.boxes:
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
        cf = float(b.conf[0])
        u, v = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        p3 = RS.deproject(u, v)
        out["dets"].append({"cls": int(b.cls[0]), "conf": round(cf, 3),
                            "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                            "uv": [round(u, 1), round(v, 1)],
                            "cam_xyz_m": (p3.get("xyz_m") if p3.get("ok") else None),
                            "depth_why": (None if p3.get("ok") else p3.get("err"))})
    out["age_s"] = L.get("age_s")
    if save:
        d = os.path.expanduser("~/zmax/zmax_data/ar_rs")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "rs_detect_last.png")
        vis = img.copy()
        for it in out["dets"]:
            x1, y1, x2, y2 = [int(v) for v in it["bbox"]]
            cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(vis, "%.2f" % it["conf"], (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.imwrite(p, vis)
        out["vis"] = p
    return out


def pose(roi=None, use_last_detect=True, draw=True):
    """🥽 **相机系**的 3D 位姿叠加: 把虚拟 3D 坐标架/尺寸框画回真实画面。

    这是「AR 场景里光模块标定能力」的**相机半边**: RealSense 有深度 ⇒ 目标在**相机系**的位置/朝向/尺寸
    是量出来的, 不是猜的(外参那半边要 base 配对, 见 pair/solve)。
    target 选择: ① 近 2s 内的 YOLO 检出框(光模块) → ② 否则取画面中心 ROI(场景平面)。
    输出: 中心(mm) · 尺寸(mm) · 主轴法向 · 平面 RMS · 有效深度占比; 标注图 zmax_data/ar_rs/rs_pose_last.png
    """
    import cv2
    import realsense_source as RS
    L = RS.latest()
    img, dep = L.get("color"), L.get("depth")
    if img is None or dep is None:
        return {"ok": False, "err": "RealSense 没有帧/深度", "err_rs": L.get("err")}
    ci = RS.intrinsics() or {}
    fx, fy, cx0, cy0 = ci.get("fx"), ci.get("fy"), ci.get("ppx"), ci.get("ppy")
    h, w = img.shape[:2]
    target = "plane:场景平面(中心ROI)"
    if use_last_detect:
        try:
            import tcp_ar_server as TAS
            if getattr(TAS, "RS_LAST_DET", None) and (time.time() - TAS.RS_LAST_DET.get("ts", 0) < 2.0) \
                    and TAS.RS_LAST_DET.get("dets"):
                b = TAS.RS_LAST_DET["dets"][0]["bbox"]
                roi = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
                target = "det:光模块(YOLO bbox)"
        except Exception:                                                        # noqa: BLE001
            pass
    if roi is None:
        roi = (int(w * 0.3), int(h * 0.3), int(w * 0.7), int(h * 0.7))
    x1, y1, x2, y2 = roi
    sub = dep[max(0, y1):min(h, y2), max(0, x1):min(w, x2)].astype(np.float32)
    sc = float(ci.get("depth_scale_m", 0.001))
    yy, xx = np.mgrid[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
    m = sub > 0
    n_valid, n_all = int(m.sum()), int(sub.size)
    if n_valid < 200:
        return {"ok": False, "err": "ROI 内有效深度只有 %d/%d 点 —— 对着远景/反光面时正常" % (n_valid, n_all),
                "target": target, "roi": list(roi), "valid_ratio": round(n_valid / max(1, n_all), 3)}
    Z = sub[m] * sc
    X = (xx[m] - cx0) * Z / fx
    Y = (yy[m] - cy0) * Z / fy
    P = np.stack([X, Y, Z], 1)
    mu = P.mean(0)
    Q = P - mu
    # 平面法向 + 面内主轴(PCA)
    _, _, Vt = np.linalg.svd(Q[np.random.default_rng(3).choice(len(Q), min(4000, len(Q)), replace=False)], full_matrices=False)
    nrm = Vt[2]
    if nrm[2] < 0:
        nrm = -nrm                                                               # 法向朝相机
    e1 = Vt[0]
    e2 = np.cross(nrm, e1)
    proj = np.stack([Q @ e1, Q @ e2, Q @ nrm], 1)
    lo, hi = proj.min(0), proj.max(0)
    size_mm = (hi - lo) * 1000.0
    rms_plane = float(np.sqrt((proj[:, 2] ** 2).mean()) * 1000.0)
    ang = float(np.degrees(np.arctan2(e1[1], e1[0])))
    out = {"ok": True, "target": target, "roi": list(roi),
           "cam_center_mm": [round(float(v) * 1000, 1) for v in mu],
           "size_mm": [round(float(v), 1) for v in size_mm],
           "long_axis_az_deg": round(ang, 2),
           "plane_normal": [round(float(v), 4) for v in nrm],
           "plane_rms_mm": round(rms_plane, 2),
           "valid_ratio": round(n_valid / max(1, n_all), 3), "n_pts": n_valid,
           "depth_median_m": round(float(np.median(Z)), 3),
           "intrinsics": {k: ci.get(k) for k in ("fx", "fy", "ppx", "ppy")},
           "note": "相机系(不是 base 系); 外参要 base 配对解出后才能画到 base 上"}
    if draw:
        ax = 0.03                                                                 # 30mm 坐标架
        Rm = np.stack([e1, e2, nrm], 1)
        pts = np.stack([[0, 0, 0], [ax, 0, 0], [0, ax, 0], [0, 0, ax]]) + mu
        uv, _ = cv2.projectPoints(pts.reshape(-1, 1, 3), np.zeros(3), np.zeros(3),
                                  np.array([[fx, 0, cx0], [0, fy, cy0], [0, 0, 1]]), None)
        uv = uv.reshape(-1, 2).astype(int)
        vis = img.copy()
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 220, 255), 1)
        o = tuple(uv[0])
        for i, col in enumerate([(60, 60, 255), (60, 255, 60), (255, 120, 60)]):  # 相机系 X/Y/Z (BGR)
            cv2.arrowedLine(vis, o, tuple(uv[i + 1]), col, 2, tipLength=0.18)
        cv2.putText(vis, "camX", tuple(uv[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 60, 255), 1)
        cv2.putText(vis, "camY", tuple(uv[2]), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 255, 60), 1)
        cv2.putText(vis, "camZ", tuple(uv[3]), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 120, 60), 1)
        txt = "%s  c=(%.0f,%.0f,%.0f)mm  %.0fx%.0fmm  Z=%.2fm" % (
            target.split(":")[0], mu[0] * 1000, mu[1] * 1000, mu[2] * 1000, size_mm[0], size_mm[1], np.median(Z))
        cv2.rectangle(vis, (4, 4), (int(9 * len(txt)) // 2 * 2 + 8, 24), (0, 0, 0), -1)
        cv2.putText(vis, txt, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        d = os.path.expanduser("~/zmax/zmax_data/ar_rs")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "rs_pose_last.png")
        cv2.imwrite(p, vis)
        out["vis"] = p
    return out


def _read_tcp():
    d = json.load(open(TCP_JSON))
    return [float(d["x"]), float(d["y"]), float(d["z"])], round(time.time() - float(d["ts"]), 2)


def pair(u, v, base=None, note=""):
    """追加一对 (uv, base)。base 缺省取 TCP 真值(要求臂停稳, 且模块就在夹爪/吸盘上)。"""
    os.makedirs(os.path.dirname(PAIRS), exist_ok=True)
    d = {"pairs": []}
    if os.path.exists(PAIRS):
        try:
            d = json.load(open(PAIRS, encoding="utf-8"))
        except Exception:                                                        # noqa: BLE001
            d = {"pairs": []}
    age = None
    if base is None:
        base, age = _read_tcp()
        if age > 1.0:
            return {"ok": False, "err": "TCP 真值帧龄 %.2fs >1s(臂可能没在跑或真值断) —— 拒收脏点" % age}
    d["pairs"].append({"uv": [float(u), float(v)], "base": [float(x) for x in base],
                       "tcp_age_s": age, "note": note, "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
    tmp = PAIRS + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, PAIRS)
    return {"ok": True, "n_pairs": len(d["pairs"]), "pair": d["pairs"][-1], "file": PAIRS}


def solve(min_pairs=5, save=True):
    """≥5 对 → 出厂内参下只解 R,t (DLT 初值) → 存 cam_calib.json["rs"]。"""
    import laptop_cam_solve as LS
    import realsense_source as RS
    d = json.load(open(PAIRS, encoding="utf-8")) if os.path.exists(PAIRS) else {"pairs": []}
    pts = d.get("pairs") or []
    if len(pts) < min_pairs:
        return {"ok": False, "err": "只有 %d 对(要 ≥%d): 把模块/夹爪停在**不同位置/高度**的已示教点上多采几对"
                % (len(pts), min_pairs)}
    P3 = [p["base"] for p in pts]
    P2 = [p["uv"] for p in pts]
    A = np.array(P3, float)
    spread = float(np.linalg.norm(A.std(0) * 1000.0))
    ci = RS.intrinsics() or {}
    sol = LS.solve(P3, P2, ci.get("w", 640), ci.get("h", 480),
                   f_fixed=ci.get("fx"), cx=ci.get("ppx"), cy=ci.get("ppy"))
    if sol is None:
        return {"ok": False, "err": "解算失败(退化: 点太集中或共面) —— 换不同高度/左右再采"}
    out = {"ok": True, "rms_px": round(sol["rms_px"], 2), "n": len(P3), "spread_sigma_mm": round(spread, 1),
           "f": sol["f"], "f_fixed": sol.get("f_fixed"), "cx": sol["cx"], "cy": sol["cy"],
           "R": sol["R"], "t": sol["t"], "err_px": [round(e, 2) for e in sol["err_px"]],
           "selftest": bool(LS.selftest(verbose=False)), "dlt_used": bool(sol.get("dlt_used"))}
    if save:
        import tcp_ar_server as TAS                       # 复用它的多相机标定文件写入口
        calib = {"kind": "laptop_cam_calib", "cam": "rs",
                 "model": "pinhole, 焦距/主点=RealSense 出厂内参", "intrinsics_source": "设备出厂内参 (只解 R,t)",
                 "device_intrinsics": {k: ci.get(k) for k in ("fx", "fy", "ppx", "ppy")},
                 "f": sol["f"], "cx": sol["cx"], "cy": sol["cy"],
                 "image_size": [int(ci.get("w", 640)), int(ci.get("h", 480))],
                 "R_base_to_cam": sol["R"], "t_base_to_cam": sol["t"],
                 "rms_px": out["rms_px"], "err_px": out["err_px"], "n_points": len(P3),
                 "spread_sigma_mm": out["spread_sigma_mm"],
                 "solver_selftest": out["selftest"], "dlt_used": out["dlt_used"],
                 "points": [{"uv": p["uv"], "tcp": p["base"], "note": p.get("note")} for p in pts],
                 "method": "光模块/YOLO 自动配对: RealSense 检出模块中心 + 深度 3D ↔ TCP/base 真值 → 解 R,t",
                 "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        out["saved"] = TAS.save_calib("rs", calib)
    return out


def selftest():
    """合成相机自测: 造一个已知 (R,t) + 出厂内参 → 投 6 点 → 反解 → 比 f/RMS (证明管线对)。"""
    import cv2
    import laptop_cam_solve as LS
    rng = np.random.default_rng(7)
    ci = {"fx": 603.4489135742188, "fy": 602.2218627929688, "ppx": 320.1129150390625,
          "ppy": 258.2041015625}
    R_true = cv2.Rodrigues(np.array([2.9, 0.25, -0.4]))[0]
    t_true = np.array([0.05, 0.12, 0.95])
    P3 = np.array([[0.55, 0.10, 0.02], [0.62, 0.18, 0.03], [0.70, 0.05, 0.02],
                   [0.58, 0.22, 0.13], [0.66, 0.14, 0.12], [0.50, 0.16, 0.06]])
    uv, z = LS.project(P3, ci["fx"], R_true, t_true, ci["ppx"], ci["ppy"])
    ok_z = bool((z > 0).all())
    sol = LS.solve(P3.tolist(), uv.tolist(), 640, 480, f_fixed=ci["fx"], cx=ci["ppx"], cy=ci["ppy"])
    Rr = np.array(sol["R"], float)
    dang = float(np.degrees(np.arccos(np.clip((np.trace(Rr.T @ R_true) - 1) / 2, -1, 1))))
    dt = float(np.linalg.norm(np.array(sol["t"], float) - t_true) * 1000)
    return {"ok": bool(ok_z and sol["rms_px"] < 1.0 and dang < 0.5 and dt < 5.0),
            "all_z_positive": ok_z, "rms_px": round(sol["rms_px"], 4),
            "dR_deg": round(dang, 4), "dt_mm": round(dt, 3), "f_used": sol["f"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["detect", "pair", "solve", "selftest", "pairs", "pose"])
    ap.add_argument("--u", type=float); ap.add_argument("--v", type=float)
    ap.add_argument("--base"); ap.add_argument("--note", default=""); ap.add_argument("--min-pairs", type=int, default=5)
    a = ap.parse_args()
    if a.cmd == "detect":
        print(json.dumps(detect(), ensure_ascii=False, indent=1))
    elif a.cmd == "pair":
        base = [float(x) for x in a.base.split(",")] if a.base else None
        print(json.dumps(pair(a.u, a.v, base, a.note), ensure_ascii=False, indent=1))
    elif a.cmd == "solve":
        print(json.dumps(solve(a.min_pairs), ensure_ascii=False, indent=1))
    elif a.cmd == "pose":
        print(json.dumps(pose(), ensure_ascii=False, indent=1))
    elif a.cmd == "pairs":
        d = json.load(open(PAIRS, encoding="utf-8")) if os.path.exists(PAIRS) else {"pairs": []}
        print(json.dumps({"n": len(d.get("pairs") or []), "pairs": d.get("pairs")}, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(selftest(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
