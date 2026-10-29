#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ar_scene_render_server.py — AR 工位场景渲染帧服务 (给 L2 感知当输入帧源)

老倪 2026-10-29: 「要用 AR场景的渲染后的视频作为数据源, 再有 L2的感知节点检测」

## 为什么不能复用 8801 (fw_render_server)
8801 是 `RealStateSpaceSim` + **metaworld peg-insert-side** 的渲染帧 (进程环境里没有
SS_ENV=ar), 机位 corner2 也照不到工位料盘 ⇒ 实测金色模块像素 = 0, 在役 AR 权重
`models/yolo_ar_peg.pt` 在它上面 **0 框** (与工位域不匹配)。
真正"AR 场景"是 `tools/ar_mujoco_env.ArMujocoEnv` (双臂 + 料盘 + 金色光模块)。

## 本服务做什么
  · 加载 ArMujocoEnv（AR 工位真场景, 与 zmax_data/ar_mujoco/ar_env.xml 同源）
  · 专用工作区机位（照住料盘/模块区, 不是 corner2 远景）→ 960×720, 与训练集同口径
  · 每 tick 让模块在工作区内小幅移动 + 机位微抖 ⇒ 帧真的在变(不是同一张图反复发)
  · 落盘真值标注 label.json: 金色像素连通域外接框 = **像素级真值**(与
    tools/ar_mujoco_dataset.py 同一判据), 供训练/对齐/核对, 不是模型预测

接口:
    GET /frame.png   最新一帧 (960×720 PNG)
    GET /status.json 帧号/帧龄/尺寸/均值/金色像素数/耗时(给人核对, 不猜)
    GET /label.json  当前帧的真值框 [x1,y1,x2,y2] + 像素数 + 帧号

用法:
    DISPLAY=:0 MUJOCO_GL=glfw ./gui-venv311/bin/python tools/ar_scene_render_server.py --port 8802 --hz 8
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

STATE = {"png": b"", "n": 0, "ts": 0.0, "mean": None, "gold_px": 0, "box": None,
         "ms": None, "shape": None, "err": None}
LOCK = threading.Lock()


def gold_mask(img):
    """金色模块像素 (sRGB: R 高、B 低) —— 与 tools/ar_mujoco_dataset.py 同一判据。"""
    import numpy as np
    a = np.asarray(img).astype(int)
    if a.ndim == 3 and a.shape[2] == 4:
        a = a[:, :, :3]
    return ((a[:, :, 0] > 120) & (a[:, :, 1] > 85) &
            (a[:, :, 0] - a[:, :, 2] > 40) & (a[:, :, 1] - a[:, :, 2] > 20))


def gold_box(mask, min_px=40, sigma_px=90):
    """最大连通域外接框 (中位数±σ 剔飞点)。返回 ([x1,y1,x2,y2] | None, 像素数)。"""
    import numpy as np
    ys, xs = np.where(mask)
    if len(ys) < min_px:
        return None, int(len(ys))
    mx, my = float(np.median(xs)), float(np.median(ys))
    keep = (np.abs(xs - mx) < sigma_px) & (np.abs(ys - my) < sigma_px)
    if keep.sum() < min_px:
        return None, int(keep.sum())
    xs, ys = xs[keep], ys[keep]
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], int(keep.sum())


def render_loop(hz: float, jitter: bool, seed: int):
    import cv2
    import mujoco
    import numpy as np
    from ar_mujoco_env import ArMujocoEnv

    env = ArMujocoEnv(render_mode="rgb_array", camera_name="corner2")
    model, data = env.model, env.data
    renderer = mujoco.Renderer(model, 720, 960)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [0.52, 0.35, 0.12]
    cam.distance = 0.42
    cam.elevation = -38.0
    cam.azimuth = 110.0

    # 金色模块的 freejoint 索引 (真值就在模型里, 不猜)
    gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "gold_module")
    jid = int(model.body_jntadr[gid]) if gid >= 0 else -1
    qadr = int(model.jnt_qposadr[jid]) if jid >= 0 else -1
    mujoco.mj_forward(model, data)
    base = np.array(data.qpos[qadr:qadr + 3]) if qadr >= 0 else None

    rng = np.random.default_rng(seed)
    n = 0
    period = 1.0 / max(0.5, float(hz))
    while True:
        t0 = time.time()
        try:
            if jitter and base is not None and qadr >= 0:
                ph = n / 12.0
                data.qpos[qadr + 0] = base[0] + 0.012 * np.sin(ph)
                data.qpos[qadr + 1] = base[1] + 0.010 * np.cos(ph * 0.8)
                mujoco.mj_forward(model, data)
                cam.azimuth = 110.0 + 2.0 * np.sin(ph * 0.5)
                cam.elevation = -38.0 + 1.5 * np.cos(ph * 0.6)
            else:
                mujoco.mj_forward(model, data)
            renderer.update_scene(data, cam)
            img = np.asarray(renderer.render())
            m = gold_mask(img)
            box, px = gold_box(m)
            ok, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR),
                                   [cv2.IMWRITE_PNG_COMPRESSION, 3])
            if not ok:
                raise RuntimeError("png encode failed")
            n += 1
            with LOCK:
                STATE.update({"png": buf.tobytes(), "n": n, "ts": time.time(),
                              "mean": round(float(img.mean()), 2), "gold_px": px,
                              "box": box, "shape": list(img.shape),
                              "ms": round((time.time() - t0) * 1000, 1), "err": None})
        except Exception as e:                                               # noqa: BLE001
            with LOCK:
                STATE["err"] = "%s: %s" % (type(e).__name__, e)
        dt = period - (time.time() - t0)
        if dt > 0:
            time.sleep(dt)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):                                              # noqa: D401
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:                                                    # noqa: BLE001
            pass

    def do_GET(self):                                                        # noqa: N802
        p = self.path.split("?")[0]
        with LOCK:
            st = dict(STATE)
        if p in ("/", "/frame.png", "/frame.jpg"):
            if not st["png"]:
                self._send(503, b"no frame yet", "text/plain")
                return
            self._send(200, st["png"], "image/png")
            return
        if p == "/status.json":
            age = (time.time() - st["ts"]) if st["ts"] else None
            body = json.dumps({"ok": st["err"] is None, "n": st["n"],
                               "age_s": round(age, 2) if age is not None else None,
                               "shape": st["shape"], "mean": st["mean"],
                               "gold_px": st["gold_px"], "box": st["box"],
                               "ms": st["ms"], "err": st["err"],
                               "src": "ArMujocoEnv(AR工位) · 工作区机位 · 960x720"},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if p == "/label.json":
            body = json.dumps({"ok": st["box"] is not None, "n": st["n"],
                               "ts": st["ts"], "box": st["box"], "gold_px": st["gold_px"],
                               "note": "金色像素连通域外接框 = 像素级真值 (非模型预测)"},
                              ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8802)
    ap.add_argument("--hz", type=float, default=8.0)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--no-jitter", action="store_true")
    a = ap.parse_args()
    threading.Thread(target=render_loop, args=(a.hz, not a.no_jitter, a.seed),
                     daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    print("🎬 AR 工位渲染帧服务 :%d · %.1fHz · 960x720 · /frame.png /status.json /label.json"
          % (a.port, a.hz), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
