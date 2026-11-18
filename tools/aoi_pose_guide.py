#!/usr/bin/env python3
"""AOI 3D 位姿引导服务 —— 供状态空间「光学质量检测」节点调用 (端口 8795)。

背景 / 为什么要有这一层
────────────────────────────────────────────────────────────────
10082 的服务在产线机 192.168.23.23 上, 它只做「拍一张 → 判 OK/NG」, 返回的是
`{count, defects, verdict}`, **不含任何几何量**: 不告诉你 19 根金手指在哪、
偏了多少像素、机器人该往哪挪。所以「金手指检测请求就是 10082 的 api」这件事,
在本机侧必须由一个**引导层**承担:

    POST /api/aoi/gold_guide   ← 调用方(状态空间节点 / 8797 / 手工)只发这一个请求
         │
         ├─→ POST 192.168.23.23:10082/capture_detect   (触发真检, 产线口径)
         ├─→ GET  192.168.23.23:10082/picture?grab=1   (取这一帧原图 2448x2048)
         ├─→ 19 根定位 (条带 + 列剖面 + 首尾等距修正)
         └─→ 偏差 → 毫米 → **目标位姿**, 一次返回

也就是: 外部看起来「金手指检测 API 会自动返回位姿」, 实际是本服务把 10082 的
判决接口 + 图像接口 + 几何解算缝在一起。

几何闭环为什么要 probe 两段
────────────────────────────────────────────────────────────────
把 328 px 换成多少毫米, 取决于 AOI 相机在该工位的 mm/px, 这个系数**没有标定值**
(实测估 0.0118~0.0177 mm/px, 相差 50%), 而且世界 Y 轴正负对应屏幕左右要看相机朝向。
猜错就是反着走、越走越偏, 所以:

    mode=probe   先只走 ±PROBE_MM(2mm), 记录 probe 前/后的金手指中心 x
    mode=solve   用这次 Δpx 算出 k(mm/px) 和 axis_sign, 再算终值
    mode=auto    有标定就 solve, 没标定就 probe

标定结果落在 zmax_data/calib/gold_pose_guide.json, 之后所有请求直接 solve。

安全
────────────────────────────────────────────────────────────────
· 只算不动的服务: 本服务**绝不下发运动**, 只返回 pose_target, 由调用方(8797)决定是否下发。
· 单次补偿上限 max_step_mm(默认 8mm), 超了就分多次, 不一次跳。
· 只允许单轴补偿(默认 Y), x/z 与姿态原样回传, 避免姿态动到插入/夹持。
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

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

AOI_HOST = os.environ.get("ZMAX_AOI_HOST") or "192.168.23.23"
AOI_PORT = int(os.environ.get("ZMAX_AOI_PORT") or 10082)
CALIB_PATH = os.environ.get("ZMAX_GOLD_GUIDE_CALIB") or os.path.join(
    REPO, "zmax_data", "calib", "gold_pose_guide.json")
SHOT_DIR = os.environ.get("ZMAX_GOLD_GUIDE_SHOT") or os.path.join(
    REPO, "zmax_data", "aoi_guide_shots")

# 19 根模板(来自老倪手画 19 根的线性拟合实测, 见 /tmp/gold_boxes_echo.json 的分析)
TPL = {"n": 19, "w": 54.5, "h": 68.0, "pitch": 70.84, "dy_per": 0.925}
PROBE_MM = 2.0
LOCK = threading.Lock()


# ─────────────────────────── 10082 通讯 ───────────────────────────
def aoi_capture_detect(timeout=25):
    """触发一次真检(产线口径 POST /capture_detect)。"""
    req = urllib.request.Request(
        "http://%s:%d/capture_detect" % (AOI_HOST, AOI_PORT),
        data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "zmax-aoi-guide"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


def aoi_last_result(timeout=12):
    try:
        req = urllib.request.Request(
            "http://%s:%d/last_result" % (AOI_HOST, AOI_PORT),
            headers={"User-Agent": "zmax-aoi-guide"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except Exception as e:                                                # noqa: BLE001
        return {"err": "%s: %s" % (type(e).__name__, e)}


def aoi_frame(grab=True, timeout=20):
    """取一帧原图(2448x2048 BGR)。grab=1 会现场抓一帧, 不重复抓则省节拍。"""
    url = "http://%s:%d/picture?grab=%d" % (AOI_HOST, AOI_PORT, 1 if grab else 0)
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-aoi-guide"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


# ─────────────────────────── 19 根定位 ───────────────────────────
def locate19(bgr):
    """返回 19 根框 + 诊断。算法给 18 根/间距不齐, 用「首尾中心等距 + 模板宽高」修正。"""
    import cam_live_stream as C

    r = C._gold_annot_auto(bgr, live_band=True)
    raw = r.get("boxes") or []
    H, W = bgr.shape[:2]
    diag = {"algo_n": len(raw), "algo_pitch": r.get("pitch"), "img_w": W, "img_h": H}
    if not raw:
        return [], diag
    bs = sorted(raw, key=lambda b: b[0])
    f, l = bs[0], bs[-1]
    c0, c1 = (f[0] + f[2]) / 2.0, (l[0] + l[2]) / 2.0
    y0, y1 = (f[1] + f[3]) / 2.0, (l[1] + l[3]) / 2.0
    n = TPL["n"]
    step = (c1 - c0) / (n - 1)
    dy = (y1 - y0) / (n - 1)
    w, h = TPL["w"], TPL["h"]
    boxes = []
    for i in range(n):
        cx, cy = c0 + step * i, y0 + dy * i
        boxes.append([int(round(cx - w / 2)), int(round(cy - h / 2)),
                      int(round(cx + w / 2)), int(round(cy + h / 2))])
    diag.update({"c0": round(c0, 1), "c1": round(c1, 1), "pitch": round(step, 2),
                 "dy": round(dy, 3), "n": len(boxes)})
    return boxes, diag


def measure(bgr=None, grab=True):
    """拍一张 + 定位 19 根, 返回中心/间距/框。"""
    if bgr is None:
        bgr = aoi_frame(grab=grab)
    if bgr is None:
        return {"ok": False, "msg": "取图失败(AOI 10082 无响应)"}
    boxes, diag = locate19(bgr)
    if not boxes:
        return {"ok": False, "msg": "19 根定位失败(条带内无周期峰)", "diag": diag}
    cx = sum((b[0] + b[2]) / 2.0 for b in boxes) / len(boxes)
    cy = sum((b[1] + b[3]) / 2.0 for b in boxes) / len(boxes)
    return {"ok": True, "n": len(boxes), "center_px": [round(cx, 1), round(cy, 1)],
            "pitch_px": diag["pitch"], "boxes": boxes, "diag": diag,
            "img": [int(bgr.shape[1]), int(bgr.shape[0])]}


# ─────────────────────────── 标定 ───────────────────────────
def calib_load():
    try:
        with open(CALIB_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                     # noqa: BLE001
        return {}


def calib_save(d):
    os.makedirs(os.path.dirname(CALIB_PATH), exist_ok=True)
    with open(CALIB_PATH, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)


def _pose_out(pose, d_mm, axis):
    """单轴平移后的目标位姿(mm + rad 原样回传, 只改一个平移分量)。"""
    p = dict(pose or {})
    try:
        p[axis.lower()] = round(float(p.get(axis.lower(), 0.0)) + d_mm, 3)
    except Exception:                                                     # noqa: BLE001
        pass
    return p


def guide(req):
    """主入口: 一次请求 → 测量 → 偏差 → 目标位姿。"""
    with LOCK:
        mode = str(req.get("mode") or "auto").lower()
        pose = req.get("pose") or {}
        axis = str(req.get("axis") or "Y").upper()
        target_px = float(req.get("target_px") or 0)
        max_step = float(req.get("max_step_mm") or 8.0)
        tol_px = float(req.get("tol_px") or 20.0)
        calib = calib_load()

        # ① 触发检测 + 取图 + 定位
        det = {}
        try:
            det["trigger"] = aoi_capture_detect()
        except Exception as e:                                            # noqa: BLE001
            det["trigger_err"] = "%s: %s" % (type(e).__name__, e)
        det["verdict"] = aoi_last_result()
        m = measure(grab=True)
        if not m.get("ok"):
            return {"ok": False, "stage": "measure", "msg": m.get("msg"),
                    "detect": det, "diag": m.get("diag")}

        W = m["img"][0]
        if target_px <= 0:
            target_px = W / 2.0
        off_px = m["center_px"][0] - target_px          # >0 = 金手指在中心右侧
        out = {"ok": True, "ts": time.time(), "mode": mode, "axis": axis,
               "measure": {"n": m["n"], "center_px": m["center_px"],
                           "pitch_px": m["pitch_px"], "img": m["img"]},
               "target_px": round(target_px, 1), "off_px": round(off_px, 1),
               "detect": {"verdict": (det.get("verdict") or {}).get("verdict"),
                          "count": (det.get("verdict") or {}).get("count")},
               "converged": abs(off_px) <= tol_px}
        if out["converged"]:
            out.update({"act": "hold", "d_mm": 0.0, "pose_target": pose,
                        "note": "已经居中(偏差 %.1f px ≤ %.0f), 不需要动" % (off_px, tol_px)})
            return out

        # ② 没标定 → 先 probe
        k = calib.get("k_mm_px")
        sgn = calib.get("axis_sign")
        if mode == "probe" or (mode == "auto" and (not k or sgn is None)):
            d = PROBE_MM
            out.update({"act": "probe", "d_mm": d, "pose_target": _pose_out(pose, sgn * d if sgn else d, axis),
                        "probe_prev": calib.get("probe") or {},
                        "note": ("没有 mm/px 标定, 先沿 %s 轴走 %.1fmm 试探方向与比例; "
                                 "走完再发 mode=solve" % (axis, d))})
            calib["probe"] = {"t": time.time(), "center_px": m["center_px"],
                              "pose": pose, "d_mm": d, "axis": axis, "off_px": round(off_px, 1)}
            calib_save(calib)
            return out

        # ③ 有标定 → 直接算终值
        d_total = off_px * float(k) * (float(sgn) if sgn is not None else 1.0)
        if abs(d_total) > max_step:
            d_total = max_step * (1 if d_total > 0 else -1)
            out["clipped"] = True
        out.update({"act": "move", "d_mm": round(d_total, 3),
                    "pose_target": _pose_out(pose, d_total, axis),
                    "calib": {"k_mm_px": k, "axis_sign": sgn, "src": CALIB_PATH},
                    "note": ("偏 %.1f px, k=%.5f mm/px, sign=%+g ⇒ 沿 %s 走 %+.2f mm%s"
                             % (off_px, float(k), float(sgn), axis, d_total,
                                " (已按上限 %.1fmm 截断)" % max_step if out.get("clipped") else ""))})
        return out


def solve_probe(pose, axis="Y"):
    """用上一次 probe 的前后测量算 k 与 sign, 写入标定。"""
    with LOCK:
        calib = calib_load()
        pr = calib.get("probe") or {}
        if not pr:
            return {"ok": False, "msg": "没有 probe 记录, 先发 mode=probe 并让机器人走完"}
        m = measure(grab=True)
        if not m.get("ok"):
            return {"ok": False, "stage": "measure", "msg": m.get("msg")}
        c_prev = float(pr["center_px"][0])
        c_now = float(m["center_px"][0])
        dpix = c_now - c_prev
        d_mm = float(pr.get("d_mm") or PROBE_MM)
        if abs(dpix) < 1.0:
            return {"ok": False, "msg": "走 %.1fmm 后画面几乎没变(Δ%.2fpx), 检查是否真的动了" % (d_mm, dpix),
                    "center_px": m["center_px"], "prev": pr.get("center_px")}
        k = abs(d_mm) / abs(dpix)                    # mm per px
        sgn = 1 if (dpix < 0 and d_mm > 0) or (dpix > 0 and d_mm < 0) else -1
        calib.update({"k_mm_px": round(k, 6), "axis_sign": int(sgn), "axis": axis.upper(),
                      "solved_at": time.strftime("%F %T"), "probe_dpix": round(dpix, 2),
                      "probe_d_mm": d_mm})
        calib.pop("probe", None)
        calib_save(calib)
        return {"ok": True, "k_mm_px": round(k, 6), "axis_sign": sgn,
                "probe": {"center_prev": c_prev, "center_now": c_now, "dpix": round(dpix, 2),
                          "d_mm": d_mm},
                "msg": ("标定完成: %.5f mm/px, 屏幕左 = %s%s 轴"
                        % (k, "+" if sgn > 0 else "-", axis.upper()))}


# ─────────────────────────── HTTP ───────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):                                    # noqa: A003
        sys.stderr.write("[guide] " + (fmt % args) + "\n")

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode("utf-8", "ignore")) if n else {}
        except Exception:                                                 # noqa: BLE001
            return {}

    def do_GET(self):                                                     # noqa: N802
        p = self.path.split("?")[0]
        if p in ("/health", "/api/aoi/guide/health"):
            return self._send(200, {"ok": True, "svc": "aoi-pose-guide",
                                    "aoi": "%s:%d" % (AOI_HOST, AOI_PORT),
                                    "calib": calib_load(), "ts": time.time()})
        if p in ("/api/aoi/guide/calib", "/calib"):
            return self._send(200, {"ok": True, "calib": calib_load(), "path": CALIB_PATH})
        return self._send(404, {"ok": False, "msg": "not found", "path": p})

    def do_POST(self):                                                    # noqa: N802
        p = self.path.split("?")[0]
        body = self._body()
        try:
            if p in ("/api/aoi/gold_guide", "/gold_guide", "/api/aoi/guide"):
                return self._send(200, guide(body))
            if p in ("/api/aoi/guide/solve", "/solve"):
                return self._send(200, solve_probe(body.get("pose") or {},
                                                   body.get("axis") or "Y"))
            if p in ("/api/aoi/guide/calib", "/calib"):
                with LOCK:
                    c = calib_load()
                    c.update({k: body[k] for k in ("k_mm_px", "axis_sign") if k in body})
                    c["set_at"] = time.strftime("%F %T")
                    calib_save(c)
                return self._send(200, {"ok": True, "calib": calib_load()})
        except Exception as e:                                            # noqa: BLE001
            return self._send(500, {"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
        return self._send(404, {"ok": False, "msg": "not found", "path": p})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8795)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    os.makedirs(SHOT_DIR, exist_ok=True)
    print("[aoi-pose-guide] 10082=%s:%d calib=%s port=%d" % (AOI_HOST, AOI_PORT, CALIB_PATH, a.port),
          flush=True)
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
