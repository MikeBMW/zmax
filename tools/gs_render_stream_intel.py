#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Intel 侧 3DGS 服务端渲染推流器 —— 4060 只显示，渲染全在 Intel 的 XPU 上做。

老倪 2026-10-25: 「4060 只是显示，而 intel 要渲染好，推流过来」

产出:
  GET /frame.jpg    单帧 (随时取一张, 页面 <img> 定时刷)
  GET /stream.mjpg  MJPEG 连续流
  GET /health       JSON: 帧率/帧龄/高斯数/相机路径/GPU
  GET /path         相机路径点(前端可画)

实现要点:
  · 与训练同口径: normalize(center,S) 来自 train_report.json 的 "normalize";
    viewmat = inv([R | S*(t-center)]) —— 与 gs_train.py 的 viewmat_of 逐字同式。
  · 尺度必须 exp(): params["scales"] 是 log 域 (gs_train.py 的注释警告过, 漏 exp 会整帧恒色)。
  · 相机路径 = 采集位姿的方位角排序后闭环 + 位置线性/姿态 slerp 插值 ⇒ 平滑环绕, 不是硬切帧。
用法 (Intel 上跑):
  /home/intel/gsxpu-venv/bin/python gs_render_stream_intel.py \
      --ply <job>/out/gs.ply --cameras <job>/ds/cameras.json \
      --report <job>/out/train_report.json --port 8816 [--fps 8] [--frames 360]
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

LOCK = threading.Lock()
STATE = {"jpeg": None, "ts": 0.0, "idx": 0, "fps": 0.0, "err": ""}

PLY_DT = {"float": "f4", "float32": "f4", "double": "f8", "uchar": "u1", "uint8": "u1", "int": "i4"}


def read_gs_ply(path):
    """读 gsplat 导出的 .ply: 返回 means(米)/scales_log/opac/quats/sh0/shN（不做激活）。"""
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise SystemExit("不是 ply 文件: %s" % path)
        fmt = None
        n = 0
        props = []
        while True:
            ln = f.readline().decode("ascii", "replace").strip()
            if ln.startswith("format"):
                fmt = ln.split()[1]
            elif ln.startswith("element vertex"):
                n = int(ln.split()[-1])
            elif ln.startswith("property"):
                _, typ, name = ln.split()[:3]
                props.append((name, PLY_DT.get(typ, "f4")))
            elif ln == "end_header":
                break
        if fmt != "binary_little_endian":
            raise SystemExit("只支持 binary_little_endian, 实际 %s" % fmt)
        raw = f.read()
    names = [p[0] for p in props]
    dt = np.dtype([(nm, t) for nm, t in props])
    a = np.frombuffer(raw[:dt.itemsize * n], dtype=dt)
    out = {}
    out["means"] = np.stack([a["x"], a["y"], a["z"]], 1).astype(np.float64)
    out["opac"] = a["opacity"].astype(np.float64)
    out["scales_log"] = np.stack([a["scale_%d" % i] for i in range(3)], 1).astype(np.float64)
    out["quats"] = np.stack([a["rot_%d" % i] for i in range(4)], 1).astype(np.float64)
    dcs = [nm for nm in names if nm.startswith("f_dc_")]
    rests = [nm for nm in names if nm.startswith("f_rest_")]
    out["sh0"] = np.stack([a[x] for x in sorted(dcs, key=lambda s: int(s.split("_")[-1]))], 1).astype(np.float64)[:, None, :]
    if rests:
        K = len(rests) // 3
        sh = np.zeros((n, K, 3), dtype=np.float64)
        for i in range(3):
            for k in range(K):
                sh[:, k, i] = a["f_rest_%d" % (i * K + k)]
        out["shN"] = sh
    else:
        out["shN"] = np.zeros((n, 0, 3), dtype=np.float64)
    return out


def quat_slerp(q0, q1, t):
    q0 = q0 / np.linalg.norm(q0)
    q1 = q1 / np.linalg.norm(q1)
    d = float(np.dot(q0, q1))
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + t * (q1 - q0)
        return q / np.linalg.norm(q)
    th = math.acos(max(-1.0, min(1.0, d)))
    return (math.sin((1 - t) * th) * q0 + math.sin(t * th) * q1) / math.sin(th)


def mat2quat(R):
    m = R
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    return np.array([w, x, y, z])


def quat2mat(q):
    w, x, y, z = q / np.linalg.norm(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def build_path(cams, center, S, n_out):
    """方位角排序 + 闭环插值 ⇒ 平滑环绕路径 [(R(3x3), t(3) 归一化系)]。"""
    # cameras.json 里每帧是 T_cam2world (4x4): R=T[:3,:3] · t=T[:3,3] (世界系相机中心)
    Tm = [np.array(c["T_cam2world"], dtype=float) for c in cams]
    pos = np.array([T[:3, 3] for T in Tm], dtype=float)
    ctr = pos.mean(0)
    az = np.arctan2(pos[:, 1] - ctr[1], pos[:, 0] - ctr[0])
    order = np.argsort(az)
    seq = [Tm[i] for i in order]
    P = pos[order]
    Q = [mat2quat(T[:3, :3]) for T in seq]
    path = []
    for k in range(n_out):
        u = k / n_out * len(seq)
        i = int(u) % len(seq)
        j = (i + 1) % len(seq)
        f = u - int(u)
        t_world = (1 - f) * P[i] + f * P[j]
        q = quat_slerp(Q[i], Q[j], f)
        Rm = quat2mat(q)
        path.append((Rm, S * (t_world - center)))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ply", required=True)
    ap.add_argument("--cameras", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--port", type=int, default=8816)
    ap.add_argument("--fps", type=float, default=8.0)
    ap.add_argument("--frames", type=int, default=300, help="环绕一圈用多少帧")
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument("--width", type=int, default=0, help="0=用建模分辨率")
    a = ap.parse_args()

    import torch
    import gsplat
    from PIL import Image

    cj = json.load(open(a.cameras, encoding="utf-8"))
    rep = json.load(open(a.report, encoding="utf-8"))
    norm = rep.get("normalize") or {}
    center = np.array(norm.get("center") or [0, 0, 0], dtype=float)
    S = float(norm.get("S") or 1.0)
    W0, H0 = int(cj["width"]), int(cj["height"])
    W, H = (a.width, int(a.width * H0 / W0)) if a.width else (W0, H0)
    K = np.array(cj["K"], dtype=float)
    if W != W0:
        K[0] *= W / W0
        K[1] *= H / H0

    P = read_gs_ply(a.ply)
    n = int(P["means"].shape[0])
    dev = "xpu" if hasattr(torch, "xpu") and torch.xpu.is_available() else "cpu"
    means = torch.tensor(S * (P["means"] - center), dtype=torch.float32, device=dev)
    scales = torch.tensor(P["scales_log"] + math.log(S), dtype=torch.float32, device=dev)
    quats = torch.tensor(P["quats"], dtype=torch.float32, device=dev)
    opac = torch.tensor(P["opac"], dtype=torch.float32, device=dev)
    sh0 = torch.tensor(P["sh0"], dtype=torch.float32, device=dev)
    shN = torch.tensor(P["shN"], dtype=torch.float32, device=dev)
    sh_deg = int(round(math.sqrt(shN.shape[1] + 1) - 1))
    Kt = torch.tensor(K, dtype=torch.float32, device=dev).unsqueeze(0)
    print("载入 %d 个高斯 · SH %d · %dx%d · dev=%s" % (n, sh_deg, W, H, dev), flush=True)

    path = build_path(cj["frames"], center, S, a.frames)
    print("相机路径 %d 帧 (方位角排序+闭环插值)" % len(path), flush=True)

    def render_one(i):
        Rm, t = path[i % len(path)]
        Tn = np.eye(4)
        Tn[:3, :3] = Rm
        Tn[:3, 3] = t
        vm = torch.tensor(np.linalg.inv(Tn), dtype=torch.float32, device=dev).unsqueeze(0)
        col = torch.cat([sh0, shN], dim=1)
        with torch.no_grad():
            img, _alpha, _info = gsplat.rasterization(
                means, quats, torch.exp(scales), torch.sigmoid(opac), col,
                viewmats=vm, Ks=Kt, width=W, height=H, sh_degree=sh_deg,
                packed=True, near_plane=0.01)
        rgb = img[0].clamp(0, 1).mul(255).byte().cpu().numpy()
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, format="JPEG", quality=a.quality)
        return buf.getvalue()

    def loop():
        i = 0
        t_prev = time.time()
        while True:
            try:
                jp = render_one(i)
                now = time.time()
                with LOCK:
                    STATE["jpeg"] = jp
                    STATE["ts"] = now
                    STATE["idx"] = i
                    STATE["fps"] = 0.9 * STATE["fps"] + 0.1 * (1.0 / max(1e-3, now - t_prev))
                    STATE["err"] = ""
                t_prev = now
                i += 1
                dt = 1.0 / a.fps - (time.time() - now)
                if dt > 0:
                    time.sleep(dt)
            except Exception as e:                                           # noqa: BLE001
                with LOCK:
                    STATE["err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
                time.sleep(1.0)

    threading.Thread(target=loop, daemon=True).start()

    class H2(BaseHTTPRequestHandler):
        def log_message(self, *args):                                        # noqa: A003
            pass

        def _send(self, code, body, ctype, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):                                                    # noqa: N802
            p = self.path.split("?")[0]
            if p in ("/frame.jpg", "/frame"):
                with LOCK:
                    jp, ts = STATE["jpeg"], STATE["ts"]
                if not jp:
                    return self._send(503, b"still initializing", "text/plain")
                return self._send(200, jp, "image/jpeg", {"X-Frame-Age": "%.2f" % (time.time() - ts)})
            if p in ("/health", "/"):
                with LOCK:
                    d = {"ok": bool(STATE["jpeg"]), "gaussians": n, "w": W, "h": H, "fps": round(STATE["fps"], 1),
                         "age_s": round(time.time() - STATE["ts"], 2) if STATE["ts"] else None,
                         "idx": STATE["idx"], "path_frames": len(path), "dev": dev, "err": STATE["err"]}
                return self._send(200, json.dumps(d, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            if p == "/stream.mjpg":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    last = -1
                    while True:
                        with LOCK:
                            jp, idx = STATE["jpeg"], STATE["idx"]
                        if jp and idx != last:
                            last = idx
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jp))
                            self.wfile.write(jp + b"\r\n")
                        time.sleep(0.02)
                except Exception:                                            # noqa: BLE001
                    return
            return self._send(404, b"no route", "text/plain")

    srv = ThreadingHTTPServer(("0.0.0.0", a.port), H2)
    srv.daemon_threads = True
    print("推流服务: :%d  /frame.jpg  /stream.mjpg  /health" % a.port, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
