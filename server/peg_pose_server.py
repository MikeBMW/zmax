#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""peg_pose_server.py — L2 融合服务: 2D 检测 ⊕ 2D→3D ⊕ 状态反馈 ⇒ 光模块 3D 位姿。

数据源固定为 **D405 彩色+深度 (Orin :8794)** —— 因为手眼外参 handeye_tool1_cam.json 就解在这个相机上,
换相机等于换外参, 会得到"看着对、数值错"的位姿。

端点:
  GET /peg_pose        位姿 JSON (xyz/quat/valid/src/σ/detail + 55D 的 peg_xyz, peg_quat 切片)
  GET /peg_pose.jpg    叠加图: 原点(白点) + 三轴 (X 红 72mm / Y 绿 18.35mm / Z 蓝 8.5mm)
  GET /healthz         帧率/检出/槽号/偏置样本数

启动:
  ./gui-venv311/bin/python tools/peg_pose_server.py --port 8896
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

REL = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(REL, "src/lerobot/policies/left_right/state_space"))

import cv2                                                               # noqa: E402
from perception_fusion6d import (PegPoseFusion, RS_FRAME, RS_DEPTH, RS_INTR, quat_from_R)  # noqa: E402

CAL = os.path.join(REL, "zmax_data/percept/calib/handeye_tool1_cam.json")
_state: dict = {"jpg": b"", "pose": None, "fps": 0.0, "err": ""}
_lock = threading.Lock()


def _get(u: str, t: float = 6.0) -> bytes:
    return urllib.request.urlopen(u, timeout=t).read()


def _proj(pts_base_m, R_cb, t_cb_m, K, dist):
    Km = np.array([[K["fx"], 0, K["cx"]], [0, K["fy"], K["cy"]], [0, 0, 1]], float)
    rv, _ = cv2.Rodrigues(R_cb)
    uv, _ = cv2.projectPoints(np.asarray(pts_base_m, float) * 1000.0, rv, t_cb_m * 1000.0, Km,
                              np.array(dist or [0, 0, 0, 0, 0], float))
    return uv.reshape(-1, 2)


def _draw(img, pose, fus: PegPoseFusion, K, dist):
    if pose is None:
        return
    if pose.get("quat"):
        w, x, y, z = [float(v) for v in pose["quat"]]
        R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                      [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                      [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])
    else:
        R = np.eye(3)
    o = np.array(pose["xyz"], float)
    L, Wd, Hd = 0.072, 0.01835, 0.0085
    # 直接投"状态里的位姿"(不补偏置): 画出来的就是状态空间里的那个数, 网络偏置会以
    # 可见的几十像素偏移暴露出来 —— 宁可看见误差, 也不要画一张"好看但对不上状态"的图。
    pts = np.stack([o, o + R[:, 0] * L, o + R[:, 1] * Wd, o + R[:, 2] * Hd])
    try:
        uv = _proj(pts, fus.R_cb, fus.t_cb, K, dist) if fus.has_extrinsic else None
    except Exception:                                                      # noqa: BLE001
        uv = None
    if uv is None:
        return
    p0 = tuple(int(round(v)) for v in uv[0])
    cv2.circle(img, p0, 5, (255, 255, 255), -1)
    cv2.circle(img, p0, 7, (0, 0, 0), 1)
    for i, col in ((1, (60, 60, 240)), (2, (60, 220, 60)), (3, (240, 170, 60))):
        p1 = tuple(int(round(v)) for v in uv[i])
        cv2.arrowedLine(img, p0, p1, col, 2, cv2.LINE_AA, tipLength=0.22)
    bias = np.asarray(getattr(fus, "bias", np.zeros(3)), float) * 1000.0
    tag = "%s σ%.1fmm  slot%s  bias %.0f,%.0f,%.0fmm" % (
        pose.get("src"), float(pose.get("sigma_mm") or 0),
        pose.get("detail", {}).get("slot"),
        bias[0], bias[1], bias[2])
    cv2.putText(img, tag, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)


def worker(fus: PegPoseFusion, port: int) -> None:
    """CPU 上 YOLO 一帧要 2.2~3.0s (GPU 已被占 7792/8188MB), 所以把"检框"与"算位姿"解耦:
       · 检出(重)  每 YOLO_EVERY 秒刷新一次 2D 框
       · 位姿(轻)  每帧用最新深度 + 最近框重算 ⇒ /peg_pose 的更新率跟取图走 (~5-10Hz)
       托盘静止时框 2s 不刷是够的; 若工件在动, 把 YOLO_EVERY 调小 (代价是节奏变慢)。"""
    from ultralytics import YOLO
    model = YOLO(os.path.join(REL, "models/yolo_peg_live.pt"))
    YOLO_EVERY = 2.0
    t0, n0, t_det, box, conf = time.time(), 0, 0.0, None, 0.0
    while True:
        try:
            img = cv2.imdecode(np.frombuffer(_get(RS_FRAME), np.uint8), cv2.IMREAD_COLOR)
            raw = cv2.imdecode(np.frombuffer(_get(RS_DEPTH), np.uint8), cv2.IMREAD_UNCHANGED)
            K = json.loads(_get(RS_INTR))
            dist = K.get("coeffs") or [0, 0, 0, 0, 0]
            now = time.time()
            if now - t_det >= YOLO_EVERY:
                r = model.predict(img, conf=0.25, device="cpu", imgsz=480, verbose=False)[0]
                if len(r.boxes):
                    b = max(r.boxes, key=lambda x: float(x.conf))
                    box = [float(v) for v in b.xyxy[0]]
                    conf = float(b.conf)
                else:
                    box, conf = None, 0.0
                t_det = time.time()
            pose = None
            if box is not None:
                pose = fus.update({"box": box, "conf": conf}, img, raw, K, dist).to_dict()
                pose["conf"] = round(conf, 3)
                pose["box_age_s"] = round(time.time() - t_det, 1)
            _draw(img, pose, fus, K, dist)
            cv2.putText(img, "det@%.1fs" % YOLO_EVERY, (10, 470), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (200, 200, 200), 1, cv2.LINE_AA)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            n0 += 1
            with _lock:
                _state.update({"pose": pose, "err": ""})
                if ok:
                    _state["jpg"] = buf.tobytes()
                if time.time() - t0 > 5:
                    _state["fps"] = round(n0 / (time.time() - t0), 1)
                    t0, n0 = time.time(), 0
        except Exception as e:                                              # noqa: BLE001
            with _lock:
                _state["err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
            time.sleep(0.5)


def make_handler(fus_holder):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):                                                   # noqa: N802
            p = self.path.split("?")[0]
            with _lock:
                pose, jpg, fps, err = _state["pose"], _state["jpg"], _state["fps"], _state["err"]
            if p == "/healthz":
                d = {"ok": not err, "fps": fps, "err": err,
                     "has_pose": pose is not None,
                     "slot": None if not pose else pose["detail"].get("slot"),
                     "bias_n": None if not pose else pose["detail"].get("bias_n")}
                self._send(200, "application/json", json.dumps(d, ensure_ascii=False).encode())
            elif p == "/peg_pose":
                out = {"ts": round(time.time(), 3), "ok": pose is not None}
                if pose:
                    out.update(pose)
                    xyz = np.array(pose["xyz"], float)
                    q = np.array(pose["quat"], float)
                    out["state55"] = {"peg_xyz@4:7": [round(float(v), 5) for v in xyz],
                                      "peg_quat@51:55": [round(float(v), 5) for v in q],
                                      "quat_norm": round(float(np.linalg.norm(q)), 5)}
                self._send(200, "application/json", json.dumps(out, ensure_ascii=False).encode())
            elif p in ("/peg_pose.jpg", "/"):
                self._send(200, "image/jpeg", jpg or b"")
            else:
                self._send(404, "text/plain", b"404")
    return H


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8896)
    a = ap.parse_args()
    fus = PegPoseFusion(CAL)          # 只为 /peg_pose.jpg 里画三轴时取外参
    threading.Thread(target=worker, args=(fus, a.port), daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(fus))
    print("peg_pose 服务 :%d   /peg_pose  /peg_pose.jpg  /healthz" % a.port, flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
