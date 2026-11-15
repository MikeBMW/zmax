#!/usr/bin/env python3
"""l2_probe.py — 215 点回放期间边跑边采: L2 检测 + 深度 + 位姿 三联 (2026-11-15)

为什么: 静态抓一帧检不出不代表 L2 不行 —— 215 点里只有接近/抓取段（idx≈90~130）
        画面里才有光模块。必须**跟着回放跑**, 记录每个点位能不能检出, 才有真结论。

产出 (每帧一行 jsonl):
  ts · cursor(回放点位) · tcp_mm · det{cls,conf,xyxy} · depth(bbox中心深度) · img路径(仅检出帧存)
汇总: zmax_data/ss_live/l2_probe_summary.json
  · 检出段分布 (哪些 idx 区间有检出)
  · 每类别最高/中位 conf
  · 可用于训练的帧数

用法: ./gui-venv311/bin/python tools/l2_probe.py --seconds 1200
"""
from __future__ import annotations
import argparse, json, os, sys, time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
OUTDIR = os.path.join(REPO, "zmax_data", "ss_live", "l2_probe")
JL = os.path.join(OUTDIR, "frames.jsonl")
SUM = os.path.join(REPO, "zmax_data", "ss_live", "l2_probe_summary.json")
# 双路相机 (2026-11-15 老倪: 手臂相机和中央相机都要用)
#   local = 中央相机 1280x720: 料盘/废料盘的光模块都在这个视野里  ← 找工件
#   arm   = 臂上 D435 640x480 : 与 8795 深度同源同分辨率          ← 算 3D
CAMS = {"local": "http://127.0.0.1:8791/snapshot/local.jpg",
        "arm":   "http://127.0.0.1:8791/snapshot/arm.jpg"}
CAM = CAMS["local"]        # 默认(保持兼容); 用 --cam 覆盖
DEPTH_CAM = "arm"          # 只有 arm 与深度同源(640x480), 反投影内参也只对 640x480 成立
DEPTH = "http://192.168.23.66:8795/depth.png"      # D405 原始 16bit/0.1mm (2026-11-15 接)
DEPTH_SCALE_M = 0.0001
AR = "http://127.0.0.1:8797/api/arm/step_traj/status"
BRIDGE = "http://192.168.23.66:39061/status"


def _get(url, timeout=6):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _getj(url, timeout=6):
    return json.loads(_get(url, timeout).decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=1200)
    ap.add_argument("--every", type=float, default=1.0)
    ap.add_argument("--weights", default="models/yolo_peg_live.pt")
    ap.add_argument("--conf", type=float, default=0.15)
    ap.add_argument("--cam", default="local", choices=list(CAMS),
                    help="local=中央相机(找工件) / arm=臂相机(有深度)")
    a = ap.parse_args()
    _cam_url = CAMS[a.cam]
    _do_depth = (a.cam == DEPTH_CAM)

    import cv2
    import numpy as np
    from ultralytics import YOLO

    os.makedirs(OUTDIR, exist_ok=True)
    m = YOLO(os.path.join(REPO, a.weights) if not os.path.isabs(a.weights) else a.weights)
    names = m.names
    print("[l2_probe] 权重 %s 类别 %s · conf>=%.2f · 每 %.1fs 一帧"
          % (a.weights, list(names.values()), a.conf, a.every), flush=True)

    t_end = time.time() + a.seconds
    n = n_det = 0
    hits = []                       # 有检出的帧摘要
    conf_by_cls = {}
    seen_idx = {}

    while time.time() < t_end:
        n += 1
        rec = {"ts": time.time(), "n": n, "cam": a.cam}
        try:
            st = _getj(AR)
            rec["cursor"] = st.get("cursor")
            rec["running"] = st.get("running")
        except Exception as e:                                          # noqa: BLE001
            rec["cursor_err"] = str(e)[:60]
        try:
            b = _getj(BRIDGE).get("status") or {}
            e = b.get("endInRef") or []
            rec["tcp_mm"] = [round(v * 1000, 1) for v in e[:3]] if len(e) >= 3 else None
        except Exception as e:                                          # noqa: BLE001
            rec["tcp_err"] = str(e)[:60]

        try:
            raw = _get(_cam_url)
            im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if im is not None:
                r = m.predict(im, conf=a.conf, imgsz=1280, verbose=False)[0]
                dets = []
                for bx in r.boxes:
                    cls = names[int(bx.cls)]
                    cf = float(bx.conf)
                    xy = [round(float(x), 1) for x in bx.xyxy[0]]
                    dets.append({"cls": cls, "conf": round(cf, 4), "xyxy": xy})
                    conf_by_cls.setdefault(cls, []).append(cf)
                rec["det"] = dets
                rec["n_det"] = len(dets)
                if dets:
                    n_det += 1
                    cur = rec.get("cursor")
                    if cur is not None:
                        seen_idx.setdefault(int(cur), 0)
                        seen_idx[int(cur)] += 1
                    # 深度: bbox 中位 (仅 arm 与深度同源)
                    try:
                        if not _do_depth: raise RuntimeError("skip-depth")
                        dr = _get(DEPTH, 8)
                        dim = cv2.imdecode(np.frombuffer(dr, np.uint8), cv2.IMREAD_UNCHANGED)
                        if dim is not None and dim.ndim == 2:
                            h, w = dim.shape[:2]
                            x1, y1, x2, y2 = [int(v) for v in dets[0]["xyxy"]]
                            x1, x2 = max(0, min(w - 1, x1)), max(0, min(w - 1, x2))
                            y1, y2 = max(0, min(h - 1, y1)), max(0, min(h - 1, y2))
                            roi = dim[y1:y2 + 1, x1:x2 + 1]
                            vv = roi[roi > 0]
                            if vv.size:
                                z10 = float(np.median(vv))          # 0.1mm 计数
                                rec["depth_mm"] = round(z10 / 10.0, 1)
                                rec["depth_px_n"] = int(vv.size)
                                # 反投影到相机系 (给 L5 用)
                                fx, fy, cx0, cy0 = 394.06, 393.47, 318.44, 238.66
                                zm = z10 * DEPTH_SCALE_M
                                u, vt = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                                if 0.05 < zm < 3.0:
                                    rec["xyz_cam_m"] = [round((u - cx0) * zm / fx, 4),
                                                        round((vt - cy0) * zm / fy, 4),
                                                        round(zm, 4)]
                    except Exception as e:                              # noqa: BLE001
                        rec["depth_err"] = "%s: %s" % (type(e).__name__, str(e)[:50])
                    fn = os.path.join(OUTDIR, "hit_%06d_c%s.jpg" % (n, rec.get("cursor", -1)))
                    open(fn, "wb").write(raw)
                    rec["img"] = fn
                    hits.append({"n": n, "cursor": rec.get("cursor"), "tcp_mm": rec.get("tcp_mm"),
                                 "det": dets, "img": fn})
        except Exception as e:                                          # noqa: BLE001
            rec["cam_err"] = "%s: %s" % (type(e).__name__, str(e)[:60])

        with open(JL, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        if n % 20 == 0:
            print("[l2_probe] 帧 %d · 有检出 %d · 已存 %d 图"
                  % (n, n_det, len(hits)), flush=True)
        time.sleep(max(0.0, a.every))

    summary = {
        "ts": time.time(), "frames": n, "frames_with_det": n_det,
        "hit_rate": round(n_det / max(1, n), 3),
        "conf_by_cls": {k: {"n": len(v), "max": round(max(v), 4),
                            "median": round(float(sorted(v)[len(v) // 2]), 4)}
                        for k, v in conf_by_cls.items()},
        "idx_with_det": sorted(seen_idx.items()),
        "n_images": len(hits),
        "weights": a.weights, "conf_th": a.conf,
    }
    json.dump(summary, open(SUM, "w"), ensure_ascii=False, indent=1)
    print("\n[l2_probe] 汇总:", json.dumps(summary, ensure_ascii=False)[:400], flush=True)
    print("[l2_probe] 落盘 %s / %s" % (JL, SUM), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
