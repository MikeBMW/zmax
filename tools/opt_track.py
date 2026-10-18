#!/usr/bin/env python3
"""👁 盯着光模块: 边动边记「臂相机看到的光模块」与「tool1 位置」的关系。

每次采样写一行 JSONL:
  ts · tcp(base mm) · abc(deg) · 模块中心 base(mm) · 模块中心在 tool1 系(mm) ·
  距离(mm) · 尺寸(mm) · 2D 框 · 置信

同时更新 summary JSON(给页面/终端看):
  采样数/失败数 · 模块在 base 系的离散度(世界固定则≈0) · 模块相对 tool1 的均值与标准差

用法: ./gui-venv311/bin/python tools/opt_track.py --sec 300 --hz 3
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import opt_box3d as OB                                                     # noqa: E402

REPO = os.path.expanduser("~/zmax")
OUT_DIR = os.path.join(REPO, "zmax_data", "ar_rs")
POSE_URL = os.environ.get("ZMAX_POSE_URL", "http://127.0.0.1:8793/pose")
FRAME_URLS = [os.environ.get("ZMAX_ARM_FRAME", "http://192.168.23.66:8792/frame.jpg"),
              "http://127.0.0.1:8797/snap/arm.jpg"]


def _get(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _pose():
    return json.loads(_get(POSE_URL, 6))


def _frame():
    err = None
    for u in FRAME_URLS:
        try:
            b = _get(u, 6)
            img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
            if img is not None and img.size:
                return img, u
        except Exception as e:                                             # noqa: BLE001
            err = "%s: %s" % (type(e).__name__, e)
    raise RuntimeError("取不到臂相机帧 (%s)" % err)


def _R_abc(a, b, c):
    ca, sa = math.cos(a), math.sin(a)
    cb, sb = math.cos(b), math.sin(b)
    cc, sc = math.cos(c), math.sin(c)
    return (np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]]) @
            np.array([[cb, 0, sb], [0, 1, 0], [-sb, 0, cb]]) @
            np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec", type=float, default=300.0, help="录多久(秒)")
    ap.add_argument("--hz", type=float, default=3.0)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    tag = ("_" + a.tag) if a.tag else ""
    jl_path = os.path.join(OUT_DIR, "opt_track_%s%s.jsonl" % (stamp, tag))
    sm_path = os.path.join(OUT_DIR, "opt_track_live.json")
    os.makedirs(OUT_DIR, exist_ok=True)
    f = open(jl_path, "w", encoding="utf-8")
    print("盯光模块开始 · %s · %.1fHz · 上限 %.0fs" % (jl_path, a.hz, a.sec), flush=True)

    n = nfail = 0
    mods, rels, tcps = [], [], []
    t0 = time.time()
    step = 1.0 / max(0.5, a.hz)
    while time.time() - t0 < a.sec:
        ts = time.time()
        rec = {"ts": round(ts, 3), "t": time.strftime("%H:%M:%S")}
        try:
            pose = _pose()
            img, src = _frame()
            r = OB.build(img, pose)
            xyz = [round(v * 1000, 1) for v in pose["xyz"]]
            abc = [round(math.degrees(v), 2) for v in pose["abc_rad"]]
            rec.update({"tcp_mm": xyz, "abc_deg": abc, "frame_src": src,
                        "pose_age_s": pose.get("age_s")})
            if r.get("ok"):
                pm = np.array(r["center_base_mm"], float)
                # 模块在 tool1 系: p_tool = R^T (p_base - t_tcp)
                R = _R_abc(*pose["abc_rad"])
                t_tcp = np.array(xyz, float)
                rel = R.T @ (pm - t_tcp)
                rec.update({"module_base_mm": r["center_base_mm"],
                            "module_tool1_mm": [round(v, 1) for v in rel],
                            "dist_mm": r["dist_mm"], "dims_mm": r["dims_mm"],
                            "box2d": r["box2d"], "box2d_det": r.get("box2d_det"),
                            "clipped": r.get("clipped") or [], "refine": r.get("refine"),
                            "conf": r["conf"], "cls": r["class"],
                            "vis_px": round(r["box2d"][3] - r["box2d"][1], 1)})
                mods.append(pm)
                rels.append(rel)
                tcps.append(t_tcp)
                n += 1
            else:
                rec["err"] = r.get("err")
                nfail += 1
        except Exception as e:                                             # noqa: BLE001
            rec["err"] = "%s: %s" % (type(e).__name__, e)
            nfail += 1
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        sm = {"ok": True, "jsonl": jl_path, "n_ok": n, "n_fail": nfail,
              "span_s": round(time.time() - t0, 1), "last": rec}
        if len(mods) >= 2:
            M = np.array(mods)
            Rs = np.array(rels)
            sm["module_base_mean_mm"] = [round(v, 1) for v in M.mean(0)]
            sm["module_base_spread_mm"] = [round(v, 1) for v in (M.max(0) - M.min(0))]
            sm["module_rel_tool1_mean_mm"] = [round(v, 1) for v in Rs.mean(0)]
            sm["module_rel_tool1_std_mm"] = [round(v, 2) for v in Rs.std(0)]
            T = np.array(tcps)
            sm["tcp_travel_mm"] = [round(v, 1) for v in (T.max(0) - T.min(0))]
        with open(sm_path, "w", encoding="utf-8") as g:
            json.dump(sm, g, ensure_ascii=False)
        time.sleep(max(0.0, step - (time.time() - ts)))
    f.close()

    M = np.array(mods) if mods else np.zeros((0, 3))
    Rs = np.array(rels) if rels else np.zeros((0, 3))
    print("\n采样 %d 成功 / %d 失败 · 时长 %.0fs" % (n, nfail, time.time() - t0))
    if len(M) >= 2:
        print("模块 base 均值 %s · 极差 %s mm  (固定在台上 ⇒ 极差应≈0)"
              % (np.round(M.mean(0), 1), np.round(M.max(0) - M.min(0), 1)))
        print("模块相对 tool1 均值 %s · 标准差 %s mm"
              % (np.round(Rs.mean(0), 1), np.round(Rs.std(0), 2)))
        print("TCP 行程 %s mm" % np.round(np.array(tcps).max(0) - np.array(tcps).min(0), 1))
    print("记录: %s" % jl_path)


if __name__ == "__main__":
    main()
