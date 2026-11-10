# -*- coding: utf-8 -*-
"""gen_camera_registry — 从三个真源生成相机注册表 (可复现, 不手编)。

真源:
  ① config/calib/zmax_calib.json        内参 K / dist / 标定状态
  ② models/handeye_state.json           腕相机手眼 T_cam2tool (残差/视图数)
  ③ 8971... 应为 8797 /api/cams         各相机实测分辨率/在线/深度 (在线才取, 离线用已知常量)

为什么要有生成器:
  config/ 是软链到 data/database (gitignore) ⇒ 注册表 JSON 不进版本库。
  换机器/重建环境时靠本脚本重生成, 不许手抄数值。

用法: gui-venv311/bin/python tools/gen_camera_registry.py [--host http://127.0.0.1:8797]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "config", "calib", "camera_registry.json")

# 固定相机的已知规格 (摄像头物理属性, 不是标定值)
KNOWN = {
    "gold":      {"size": [900, 332],  "label": "🔍 金手指检测相机 (工控机 OPT 10082·判据图)"},
    "gold_raw":  {"size": [1400, None], "label": "🔍 金手指检测·整板原图 (10082)"},
    "surface":   {"size": [1280, 1280], "label": "🧪 表面检测相机 (工控机 OPT 10083)"},
    "local2":    {"size": [1280, 720],  "label": "📺 MAXHUB 顶摄中央相机 1280×720"},
    "local":     {"size": [640, 480],   "label": "💻 本机 USB 内置相机 640×480"},
    "rs":        {"size": [640, 480],   "label": "🎥 本机 USB RealSense D435 (彩色+深度)"},
    "arm":       {"size": [640, 480],   "label": "🦾 机器人臂上 RealSense D405 (Orin)"},
}

ZONES_FOR = {
    "arm": ["料盘槽位排", "插入工位/夹具", "标定区", "观察位"],
    "gold": ["观察位"], "gold_raw": ["观察位"], "surface": ["观察位"],
    "local2": ["料盘槽位排", "插入工位/夹具", "其它"],
    "rs": ["其它"], "local": [],
}


def probe(host):
    try:
        with urllib.request.urlopen(host + "/api/cams", timeout=5) as r:
            return (json.loads(r.read().decode("utf-8")) or {}).get("cams") or {}
    except Exception:  # noqa: BLE001
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:8797")
    a = ap.parse_args()

    calib = json.load(open(os.path.join(REPO, "config", "calib", "zmax_calib.json"), encoding="utf-8"))
    he_path = os.path.join(REPO, "models", "handeye_state.json")
    he = json.load(open(he_path, encoding="utf-8")) if os.path.exists(he_path) else {}
    live = probe(a.host)
    K = calib["camera"]

    reg = {
        "_doc": "分布式感知相机注册表 —— 唯一依据。extrinsic.mode=uncalibrated 的相机只准出 2D, 代码硬拒 3D。",
        "_gen": "tools/gen_camera_registry.py",
        "_generated_from": ["config/calib/zmax_calib.json", "models/handeye_state.json",
                            "%s/api/cams (实测样本 %d 台)" % (a.host, len(live))],
        "cams": {},
        "_rules": {
            "3d_guard": "extrinsic.mode not in {tcp_compose, fixed_matrix} ⇒ 拒 3D, 只出 2D",
            "handoff": "主相机目标点在副相机内可检出且两两差 <10mm 才交接, 否则停并报",
            "hysteresis_mm": 20, "xcheck_veto_mm": 10,
        },
    }

    for cid, spec in KNOWN.items():
        lv = live.get(cid) or {}
        w, h = spec["size"]
        if lv.get("w"):
            w = lv["w"]
        has_depth = bool(lv.get("depth")) or cid in ("arm", "rs")
        entry = {"label": lv.get("label") or spec["label"], "kind": "fixed",
                 "intrinsic": {"size": [w, h], "_src": "%s/api/cams" % a.host},
                 "depth": {"src": "realsense", "unit_mm": 0.1, "max_age_s": 0.5} if has_depth else None,
                 "role": ["quality"] if cid.startswith(("gold", "surface")) else
                         (["debug"] if cid == "local" else ["overview"]),
                 "level": "L0",
                 "coverage": {"zones": ZONES_FOR.get(cid, [])},
                 "calibrated": False,
                 "online_at_gen": lv.get("online")}
        if cid == "arm":
            entry["kind"] = "eye_in_hand"
            entry["intrinsic"] = {"fx": K["fx"], "fy": K["fy"], "cx": K["cx"], "cy": K["cy"],
                                  "dist": K["dist"], "size": [640, 480], "_src": "zmax_calib.json camera"}
            if he.get("ok"):
                entry["extrinsic"] = {"mode": "tcp_compose", "T_cam2tool": he["T_cam2tool"],
                                      "t_mm": he["t_mm"], "resid_mm_rms": he["resid_trans_mm_rms"],
                                      "resid_deg_rms": he["resid_rot_deg_rms"],
                                      "views": len(he.get("views") or []),
                                      "_src": "models/handeye_state.json",
                                      "_formula": "T_base_cam = T_base_tool(TCP真值) @ T_cam2tool"}
                entry["role"] = ["localize", "guide"]
                entry["level"] = "L2"
                entry["calibrated"] = True
            else:
                entry["extrinsic"] = {"mode": "uncalibrated", "_reason": "handeye_state.json 缺失或未成功"}
        else:
            entry["extrinsic"] = {"mode": "uncalibrated",
                                  "_reason": "T_base_cam=null; 可用 4 非共线示教点 PnP 解(零运动)"
                                  if cid in ("local2", "rs") else "固定工位相机, 未标 T_base_aoi"}
        reg["cams"][cid] = entry

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)

    print("写出 %s (%d B)" % (OUT, os.path.getsize(OUT)))
    for cid, c in reg["cams"].items():
        print("  %-9s level=%-3s ext=%-13s calibrated=%s" % (
            cid, c["level"], c["extrinsic"]["mode"], c["calibrated"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
