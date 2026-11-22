#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_yolo_stream.py — 手臂相机 + YOLO 光模块框 的实时推流(独立小服务, 不碰 8791/8793).

为什么单独起进程: 主推流服务 cam_live_stream.py 一起就断现场直播、且授权会失效,
而工位页 station.html 是**热读**的 ⇒ 只要页面里换成这个服务的图, 不用重启主服务。

  GET /arm_yolo.jpg    当前标注帧 (JPEG, 快照模式, 页面每 0.6s 拉一次)
  GET /arm_yolo.mjpg   MJPEG 推流 (可选)
  GET /healthz         状态: 帧率/检出/槽号

检出判据(实测标定, 老倪确认过):
  conf ≥ 0.5 且 框中心连续稳定 ⇒ 有件; 槽号 = (940 − x中心)/116 + 1
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

SRC = os.environ.get("ZMAX_ARM_SRC", "http://127.0.0.1:8791/arm.mjpg")
MODEL = os.environ.get("ZMAX_PEG_MODEL", "/home/ubuntu/zmax/models/yolo_peg_live.pt")
PORT = int(os.environ.get("ZMAX_YOLO_PORT", "8898"))
INFER_EVERY = float(os.environ.get("ZMAX_YOLO_EVERY", "0.35"))
CONF = float(os.environ.get("ZMAX_YOLO_CONF", "0.35"))
X1, DX = 940.5, 116.5          # 槽1 框中心 x 与每槽像素步距(1280 宽下实测) —— 下面按实际宽度折算
W_REF = 1280.0

# ── 光模块坐标系叠加(槽位几何真值 + 手眼外参投影) ─────────────────────────
CAL_FILE = os.environ.get("ZMAX_HANDEYE_CAL",
                          "/home/ubuntu/zmax/zmax_data/percept/calib/handeye_tool1_cam.json")
TRAY_FILE = "/home/ubuntu/zmax/config/points/tray_slots_14.json"
MOD_SLOT = int(os.environ.get("ZMAX_MOD_SLOT", "0"))   # >0 才画模块坐标系; 画了就不再打 YOLO 槽号(下排会被上排公式带偏)
RS_INTR = os.environ.get("ZMAX_RS_INTR", "http://192.168.23.66:8794/intrinsics")
RS_DEPTH = os.environ.get("ZMAX_RS_DEPTH", "http://192.168.23.66:8794/depth.png")
_cal_cache = {"mtime": 0.0, "cal": None, "km": None, "dist": None, "tray": None}


def _httpreq(u, t=5):
    return urllib.request.urlopen(u, timeout=t).read()


def _load_cal():
    try:
        mt = os.path.getmtime(CAL_FILE)
    except OSError:
        return None
    if _cal_cache["cal"] is not None and mt == _cal_cache["mtime"]:
        return _cal_cache
    try:
        c = json.load(open(CAL_FILE))
        if _cal_cache["km"] is None:
            k = json.loads(_httpreq(RS_INTR))
            _cal_cache["km"] = np.array([[k["fx"], 0, k["cx"]], [0, k["fy"], k["cy"]], [0, 0, 1]], float)
            _cal_cache["dist"] = np.array(k.get("coeffs") or [0, 0, 0, 0, 0], float)
        if _cal_cache["tray"] is None:
            _cal_cache["tray"] = json.load(open(TRAY_FILE))
        _cal_cache.update({"mtime": mt, "cal": c})
        return _cal_cache
    except Exception:                                                          # noqa: BLE001
        return None


def _anchor_uv(boxes, img=None):
    """锚点 = 模块上边沿中点(用户定义的原点) = YOLO 检出框的上边沿中点。

    为什么不用灰度暗块/深度近层: 实测两者 bbox 高 200~207px, 而 72mm 模块在此距离只该约 125px
    —— 画面里那个暗块/近层混了阴影与槽口, 拿它当模块会把原点带偏几百像素。
    检测框的上边沿则是模型对"模块"这个目标的判定边界, 口径确定、可复现。
    """
    if not boxes or img is None:
        return None
    b = max(boxes, key=lambda x: float(x.conf))
    x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
    # 模块一端是绿色拉环, 另一端是金手指(连接器)端 ⇒ 原点在金手指端中间 = 检测框下边沿中点
    return ((x1 + x2) / 2.0, float(y2))


def _draw_module_frame(img, anchor_uv=None):
    """把"光模块坐标系"(原点=模块头中心)画到画面上。外参来自手眼标定文件, 精度写在角标里。"""
    cc = _load_cal()
    if not cc or not cc.get("cal"):
        return False
    c = cc["cal"]
    if "rvec" not in c or "tvec" not in c:
        return False
    rvec = np.array(c["rvec"], float).reshape(3, 1)
    tvec = np.array(c["tvec"], float).reshape(3, 1)
    slot = None
    for s in cc["tray"]["slots"]:
        if int(s["id"]) == MOD_SLOT:
            slot = s
            break
    if slot is None:
        return False
    L, W, H = slot["box"]["lx"], slot["box"]["ly"], slot["box"]["lz"]
    # 🔒 原点 = 模块上边沿中间(用户定义): 顶面(z=槽底+H) 的 -Y 长边 的中点
    #    +Y 在图像里朝下(槽1 y=502 投影 v=425, 槽14 y=206 投影 v=207) ⇒ 图像"上"一侧是 -Y
    # 金手指端: 长边(+X)的一端; 这里按槽位真值取 -X 端, 顶面高度, 宽度中点
    o = np.array([slot["x"] - L / 2.0, slot["y"], slot["z"] + H], float)
    Km, dist = cc["km"], cc["dist"]

    # 锚定: 标定的"暗区质心"带系统性阴影偏移(实测垂直 60~65px), 方向/尺度可信, 绝对位置以实时检出为准
    du = dv = 0.0
    uv_o, _ = cv2.projectPoints(o.reshape(1, 3), rvec, tvec, Km, dist)
    if anchor_uv is not None:
        du = anchor_uv[0] - uv_o[0, 0, 0]
        dv = anchor_uv[1] - uv_o[0, 0, 1]

    def proj(pb):
        uv, _ = cv2.projectPoints(np.asarray(pb, float).reshape(1, 3), rvec, tvec, Km, dist)
        return int(uv[0, 0, 0] + du), int(uv[0, 0, 1] + dv)

    # 长方体 8 角 + 12 边
    idx = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
           (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    cb = o + np.array([0.0, W / 2.0, -H / 2.0])     # 体中心(原点在顶面 -Y 长边中点, 不能直接当体中心用)
    pts = [proj(cb + np.array(i) * np.array([L, W, H]) / 2.0) for i in idx]
    if os.environ.get("ZMAX_MOD_BOX", "0") == "1":       # 3D 框默认不画(画面乱), 要开就设 ZMAX_MOD_BOX=1
        for a, b in [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]:
            cv2.line(img, pts[a], pts[b], (235, 160, 60), 2, cv2.LINE_AA)
    # 三轴
    O = proj(o)
    for v, col, nm in (((L * 0.85, 0, 0), (60, 60, 240), "X72"),
                       ((0, W * 3.0, 0), (60, 210, 60), "Y18.35"),
                       ((0, 0, H * 3.2), (240, 170, 60), "Z8.5")):
        q = proj(o + np.array(v))
        cv2.arrowedLine(img, O, q, col, 2, cv2.LINE_AA, tipLength=0.22)
        cv2.putText(img, "模块." + nm, (q[0] + 4, q[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2, cv2.LINE_AA)
    cv2.circle(img, O, 5, (255, 255, 255), -1)
    cv2.putText(img, "原点=金手指端中间 槽%d" % MOD_SLOT,
                (O[0] + 8, O[1] + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, "位置锚定实时检出 · 朝向/尺度按标定(残差 %.1fpx · 偏置 %+.0f,%+.0fpx)"
                % (float(c.get("rms_px") or max(c.get("reproj_px") or [0])), du, dv),
                (10, img.shape[0] - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 200, 240), 1, cv2.LINE_AA)
    return True

_state_lock = threading.Lock()
_state = {"jpg": None, "ts": 0.0, "n": 0, "best": None, "slot": None,
          "fps": 0.0, "err": "", "frames": 0}
_model = None


def _get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO(MODEL)
    return _model


def _draw(img, boxes):
    best = None
    for b in boxes:
        x1, y1, x2, y2 = [int(float(v)) for v in b.xyxy[0]]
        c = float(b.conf)
        col = (60, 220, 60) if c >= 0.5 else (60, 200, 240)
        cv2.rectangle(img, (x1, y1), (x2, y2), col, 3)
        cx = (x1 + x2) // 2
        k = img.shape[1] / W_REF
        slot = int(round((X1 * k - cx) / (DX * k) + 1)) if k > 0 else 0
        tag = "peg %.2f" % c + (("  slot%d" % slot) if (1 <= slot <= 14 and MOD_SLOT == 0) else "")
        cv2.rectangle(img, (x1, max(0, y1 - 26)), (min(img.shape[1], x1 + 12 * len(tag)), max(26, y1)), col, -1)
        cv2.putText(img, tag, (x1 + 4, max(19, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                    (10, 20, 10), 2, cv2.LINE_AA)
        if best is None or c > best[0]:
            best = (c, slot, cx)
    return best


def _worker():
    cap = cv2.VideoCapture(SRC)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    t_last_inf, boxes, t0, n0 = 0.0, [], time.time(), 0
    _anchor = None
    while True:
        ok, img = cap.read()
        if not ok or img is None:
            with _state_lock:
                _state["err"] = "取流失败: %s" % SRC
            time.sleep(0.5)
            cap.release()
            cap = cv2.VideoCapture(SRC)
            continue
        now = time.time()
        if now - t_last_inf >= INFER_EVERY:
            try:
                r = _get_model().predict(img, conf=CONF, device="cpu", verbose=False)[0]
                boxes = list(r.boxes)
                _anchor = _anchor_uv(boxes, img) if MOD_SLOT else None
                best = _draw(img, boxes)
            except Exception as e:                                            # noqa: BLE001
                boxes, best = [], None
                with _state_lock:
                    _state["err"] = "推理失败: %s" % str(e)[:80]
            t_last_inf = now
            with _state_lock:
                _state.update({"n": len(boxes),
                               "best": None if best is None else round(best[0], 2),
                               "slot": None if best is None else (best[1] if 1 <= best[1] <= 14 else None),
                               "err": ""})
        else:
            # 帧间沿用上一次的框(不重算, 保持帧率)
            _draw(img, boxes)
        # 注意: 必须先取锚点再画标注, 否则标注里的深色文字会被算进"模块暗块"
        _draw_module_frame(img, _anchor)
        cv2.putText(img, time.strftime("%H:%M:%S"), (img.shape[1] - 108, img.shape[0] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 2, cv2.LINE_AA)
        ok2, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok2:
            with _state_lock:
                _state["jpg"] = buf.tobytes()
                _state["ts"] = now
                _state["frames"] += 1
                _state["fps"] = round((_state["frames"] - n0) / max(1e-6, now - t0), 1) if now - t0 > 1 else _state["fps"]
                if now - t0 > 5:
                    t0, n0 = now, _state["frames"]


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静音
        return

    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):                                                        # noqa: N802
        p = self.path.split("?")[0]
        if p in ("/arm_yolo.jpg", "/snap.jpg"):
            with _state_lock:
                jpg, ts = _state["jpg"], _state["ts"]
            if not jpg:
                return self._send(503, "text/plain", b"no frame yet")
            return self._send(200, "image/jpeg", jpg,
                              {"X-Frame-Age-S": "%.3f" % max(0.0, time.time() - ts)})
        if p == "/healthz":
            with _state_lock:
                d = {k: v for k, v in _state.items() if k != "jpg"}
            d.update({"src": SRC, "conf": CONF, "age_s": round(time.time() - _state["ts"], 2)
                      if _state["ts"] else None})
            return self._send(200, "application/json; charset=utf-8",
                              json.dumps(d, ensure_ascii=False).encode())
        if p == "/arm_yolo.mjpg":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=fr")
            self.end_headers()
            try:
                while True:
                    with _state_lock:
                        jpg = _state["jpg"]
                    if jpg:
                        self.wfile.write(b"--fr\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                    time.sleep(0.1)
            except Exception:
                return
        return self._send(404, "text/plain", b"not found")


def main() -> int:
    threading.Thread(target=_worker, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("arm_yolo_stream on :%d · src=%s · conf=%.2f · 每 %.2fs 推理一次"
          % (PORT, SRC, CONF, INFER_EVERY), flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
