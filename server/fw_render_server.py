#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fw_render_server.py — 插拔场景(insert)渲染帧 HTTP 服务 (给 VLM 编码器 / pipeline 当输入帧源)

老倪 2026-10-15: 「信息连接是核心, 要保证插拔环境的渲染图像进入 VLM, 被流形引擎的结构感知到」

为什么要有它: 现场相机不在位 (8791 各快照 503, 8797/snap 返 0 字节) ⇒ 10Hz 回路里 `--encoder l4`
/ `--pipeline` 拿不到新鲜帧。本服务用**引擎自己的渲染器** (RealStateSpaceSim._render_frame,
与 tools/pipeline_closure_run.py 同一口径的"真输入=引擎渲染帧") 持续渲染插拔场景, 落盘 + HTTP 提供:
    GET /frame.png   → 最新一帧 (PNG)
    GET /status.json → 帧号/帧龄/尺寸/均值-标准差/渲染来源 (给人核对, 不猜)

用法: ./gui-venv311/bin/python tools/fw_render_server.py --port 8799 --hz 2
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
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

STATE = {"png": b"", "n": 0, "ts": 0.0, "mean": None, "std": None, "shape": None,
         "step": None, "err": None}


def _render_loop(hz: float, seed: int, mode: str, steps_per_tick: int = 4):
    try:
        import cv2
        import numpy as np
        from state_space_sim_real import RealStateSpaceSim

        def _fresh():
            s = RealStateSpaceSim(seed=seed, vision=False, mode=mode, log=lambda *x: None)
            s.run(max_steps=8)
            return s

        sim = _fresh()
        step = 8
        while True:
            t0 = time.time()
            try:
                # 🔴 2026-10-15 老倪「怎么就循环耗时有信号, 别的没有信号」——真根因:
                #   RealStateSpaceSim.run() 每次进来都 `_reset(seed)` ⇒ 原来每秒 run(1) 拿到的永远是
                #   "第 0/1 步"的**同一张图**(实测连取 4 帧 md5 全同) ⇒ VLM 潜表示/φ/梯度/置信 全冻住。
                #   改成 resume=True 接着走 (每个 tick 推进 N 步, 走完重置) ⇒ 渲染帧真的在变。
                tr = sim.run(max_steps=steps_per_tick, resume=True)
                step += steps_per_tick
                _done = bool(tr.get("done") and tr["done"][-1]) if isinstance(tr, dict) else False
                if _done or step % 1000 == 0:               # 一轮走完 → 重开 (保持"活着"的渲染流)
                    sim = _fresh()
                    step = 8
            except Exception:                                                        # noqa: BLE001
                try:
                    sim = _fresh()
                    step = 8
                except Exception:                                                    # noqa: BLE001
                    pass
            try:
                img = np.asarray(sim._render_frame())
            except Exception as e:                                                   # noqa: BLE001
                STATE["err"] = "%s: %s" % (type(e).__name__, e)
                time.sleep(1.0 / max(0.1, hz))
                continue
            ok, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
            if ok:
                STATE.update(png=buf.tobytes(), n=STATE["n"] + 1, ts=time.time(),
                             mean=float(img.mean()), std=float(img.std()), shape=list(img.shape),
                             step=step, err=None)
            time.sleep(max(0.0, 1.0 / max(0.1, hz) - (time.time() - t0)))
    except Exception as e:                                                           # noqa: BLE001
        STATE["err"] = "%s: %s" % (type(e).__name__, e)
        print("❌ 渲染线程失败: %s" % STATE["err"], flush=True)


class H(BaseHTTPRequestHandler):
    def log_message(self, *_a):                                                      # 静音
        pass

    def do_GET(self):                                                                # noqa: N802
        if self.path.startswith("/frame.png"):
            if not STATE["png"]:
                self.send_response(503); self.end_headers(); self.wfile.write(b"warming up"); return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(STATE["png"])))
            self.end_headers(); self.wfile.write(STATE["png"]); return
        if self.path.startswith("/status.json"):
            d = {"n": STATE["n"], "age_s": (round(time.time() - STATE["ts"], 2) if STATE["ts"] else None),
                 "shape": STATE["shape"], "mean": STATE["mean"], "std": STATE["std"],
                 "episode_step": STATE.get("step"),
                 "src": "RealStateSpaceSim._render_frame() · mode=%s (插拔场景渲染帧, 与 pipeline_closure_run 同口径)"
                        % (getattr(self, "_mode", "insert")), "err": STATE["err"]}
            b = json.dumps(d, ensure_ascii=False).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
        self.send_response(404); self.end_headers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--hz", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--mode", default="insert")
    ap.add_argument("--steps-per-tick", type=int, default=4,
                    help="每 tick 推进的仿真步数 (帧真的在动; 老倪 2026-10-15)")
    ap.add_argument("--seconds", type=float, default=0.0, help="0=常驻")
    a = ap.parse_args()
    t = threading.Thread(target=_render_loop, args=(a.hz, a.seed, a.mode, a.steps_per_tick), daemon=True)
    t.start()
    for _ in range(120):                                # 等首帧 (最多 60s)
        if STATE["png"] or STATE["err"]:
            break
        time.sleep(0.5)
    print("🎬 插拔场景渲染帧服务 http://127.0.0.1:%d/frame.png (首帧 %d B, err=%s)"
          % (a.port, len(STATE["png"]), STATE["err"]), flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    if a.seconds > 0:
        threading.Thread(target=lambda: (time.sleep(a.seconds), srv.shutdown()), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    print("✅ 渲染帧服务退出 (共 %d 帧)" % STATE["n"], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
