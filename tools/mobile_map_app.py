#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mobile_map_app.py — 手机拍视频建图 (Web App, 免安装)

老倪 2026-10-22: 「能建立一个用手机拍摄视频建图的app么」

设计要点 (为什么是 Web App 而不是原生 APK):
  · 免安装跨平台: 安卓/iOS 都能用浏览器直接开, 不用签名打包、不用应用商店
  · 手机浏览器原生支持 <input type="file" accept="video/*" capture="environment">
    ⇒ 直接调后置摄像头录像, 拿到的是真视频文件
  · 产物用 Three.js 在手机里渲染, 手指拖拽旋转/双指缩放

链路 (每一环都用既有实现, 不新造):
  手机拍/选视频 → 上传到 Intel → ffmpeg 抽帧 → tools/mapping/mono_sfm.py
  (纯 OpenCV 的单目 SfM, 不需要 COLMAP, 不需要 CUDA) → 点云 + 轨迹
  → Three.js 在手机上渲染

端口: 8803 (与 8800 推理 / 8801 建图 / 8802 旁路AOI 并列)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

WORK = os.environ.get("ZMAX_MOBILE_MAP_DIR", os.path.expanduser("~/mobile_map"))
JOBS = os.path.join(WORK, "jobs")
os.makedirs(JOBS, exist_ok=True)

SFM = os.environ.get("ZMAX_MONO_SFM", os.path.expanduser("~/zmax_map/tools/mapping/mono_sfm.py"))
PY = os.environ.get("ZMAX_PY", "/usr/bin/python3")

# 手机端页面 (独立文件, 便于改样式不用动后端逻辑)
_HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_PATH = os.environ.get("ZMAX_MOBILE_PAGE", os.path.join(_HERE, "mobile_map_page.html"))


def _page():
    try:
        return open(PAGE_PATH, encoding="utf-8").read()
    except Exception as e:
        return "<h1>缺少页面文件</h1><p>%s</p><p>%s</p>" % (PAGE_PATH, e)

# 任务表 (单机内存态; 落盘 summary.json 做持久证据)
TASKS = {}
LOCK = threading.Lock()


def _job_dir(jid):
    return os.path.join(JOBS, jid)


def _save(jid, d):
    with LOCK:
        TASKS[jid] = d
    try:
        json.dump(d, open(os.path.join(_job_dir(jid), "job.json"), "w"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass


def _load(jid):
    with LOCK:
        if jid in TASKS:
            return TASKS[jid]
    p = os.path.join(_job_dir(jid), "job.json")
    if os.path.exists(p):
        try:
            d = json.load(open(p))
            with LOCK:
                TASKS[jid] = d
            return d
        except Exception:
            pass
    return None


def extract_frames(video, outdir, fps=2, max_frames=150):
    """ffmpeg 抽帧。fps=2 是折中: 手机视频 30fps 全用没必要, 2fps 视差够且快。"""
    os.makedirs(outdir, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", video,
           "-vf", "fps=%s" % fps, "-qscale:v", "3",
           os.path.join(outdir, "f_%04d.jpg")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 抽帧失败: %s" % (r.stderr or "")[-300:])
    frames = sorted(f for f in os.listdir(outdir) if f.lower().endswith(".jpg"))
    if len(frames) > max_frames:
        # 均匀抽稀, 保持时间覆盖
        keep = [frames[int(i * (len(frames) - 1) / (max_frames - 1))] for i in range(max_frames)]
        for f in frames:
            if f not in keep:
                os.remove(os.path.join(outdir, f))
        frames = sorted(keep)
    return len(frames)


def run_sfm(frames_dir, outdir):
    """调既有 mono_sfm.py (纯 OpenCV, Intel 端就是设计目标机器)"""
    cmd = [PY, SFM, "--frames", frames_dir, "--out", outdir, "--max-frames", "200"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError("mono_sfm 失败: %s" % ((r.stderr or "") + (r.stdout or ""))[-400:])
    sp = os.path.join(outdir, "summary.json")
    if not os.path.exists(sp):
        raise RuntimeError("mono_sfm 未产出 summary.json")
    return json.load(open(sp))


def ply_to_json(ply_path, limit=200000):
    """读 mono_sfm 产出的 .ply → [{x,y,z,r,g,b}] 供 Three.js 直接灌 buffer"""
    pts = []
    try:
        with open(ply_path, "rb") as f:
            header = []
            while True:
                ln = f.readline()
                if not ln:
                    break
                header.append(ln.decode("ascii", "ignore").strip())
                if ln.strip() == b"end_header":
                    break
            n = 0
            fmt = "ascii"
            for h in header:
                if h.startswith("element vertex"):
                    n = int(h.split()[-1])
                if "format" in h and "binary" in h:
                    fmt = h
            if "binary" in fmt:
                import struct
                pts = []
                for _ in range(min(n, limit)):
                    buf = f.read(15)      # x,y,z float32 + r,g,b uint8
                    if len(buf) < 15:
                        break
                    x, y, z = struct.unpack("<fff", buf[:12])
                    r, g, b = buf[12], buf[13], buf[14]
                    pts.append([round(x, 4), round(y, 4), round(z, 4), r, g, b])
            else:
                for i, ln in enumerate(f):
                    if i >= limit:
                        break
                    v = ln.split()
                    if len(v) >= 6:
                        pts.append([round(float(v[0]), 4), round(float(v[1]), 4),
                                    round(float(v[2]), 4),
                                    int(float(v[3])), int(float(v[4])), int(float(v[5]))])
    except Exception as e:
        raise RuntimeError("解析 ply 失败: %s" % e)
    return pts


def worker(jid, video_path):
    d = _job_dir(jid)
    job = {"id": jid, "state": "queued", "msg": "排队中", "t0": time.time(),
           "frames": None, "summary": None, "n_points": None, "err": ""}
    _save(jid, job)
    try:
        # ① 抽帧
        job.update(state="extract", msg="抽帧中")
        _save(jid, job)
        fdir = os.path.join(d, "frames")
        n = extract_frames(video_path, fdir)
        job["frames"] = n
        if n < 8:
            raise RuntimeError("视频太短或抽不到帧 (%d 帧) —— 请拍 3 秒以上、边走边拍" % n)

        # ② SfM
        job.update(state="sfm", msg="单目建图中 (%d 帧)" % n)
        _save(jid, job)
        sfm_out = os.path.join(d, "map")
        sm = run_sfm(fdir, sfm_out)
        job["summary"] = sm

        # ③ 点云转 JSON
        ply = os.path.join(sfm_out, "points.ply")
        pts = ply_to_json(ply)
        job["n_points"] = len(pts)
        json.dump(pts, open(os.path.join(d, "points.json"), "w"))

        # ④ 轨迹
        tum = os.path.join(sfm_out, "trajectory.tum")
        traj = []
        if os.path.exists(tum):
            for ln in open(tum):
                v = ln.split()
                if len(v) >= 4:
                    traj.append([round(float(v[1]), 4), round(float(v[2]), 4), round(float(v[3]), 4)])
        json.dump(traj, open(os.path.join(d, "trajectory.json"), "w"))

        job.update(state="done", msg="建图完成",
                   secs=round(time.time() - job["t0"], 1))
    except Exception as e:
        job.update(state="failed", msg="失败", err=str(e),
                   secs=round(time.time() - job["t0"], 1))
    _save(jid, job)
    shutil.rmtree(os.path.join(d, "frames"), ignore_errors=True)   # 帧不长期占盘


def start_job(video_path):
    jid = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
    os.makedirs(_job_dir(jid), exist_ok=True)
    shutil.move(video_path, os.path.join(_job_dir(jid), "input.mp4"))
    threading.Thread(target=worker, args=(jid, os.path.join(_job_dir(jid), "input.mp4")),
                     daemon=True).start()
    return jid


# ────────────────────────── HTTP ──────────────────────────
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _s(self, code, body, ct="text/html; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._s(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        if p in ("/", "/index.html"):
            return self._s(200, _page())
        if p == "/health":
            return self._json({"ok": True, "jobs": len(TASKS),
                               "work": WORK, "sfm": SFM, "sfm_exists": os.path.exists(SFM)})
        if p == "/jobs":
            with LOCK:
                items = sorted(TASKS.values(), key=lambda x: x.get("t0", 0), reverse=True)[:30]
            return self._json({"jobs": [{"id": j["id"], "state": j["state"],
                                         "msg": j.get("msg"), "frames": j.get("frames"),
                                         "n_points": j.get("n_points"),
                                         "secs": j.get("secs")} for j in items]})
        if p == "/job":
            jid = (q.get("id") or [""])[0]
            j = _load(jid)
            if not j:
                return self._json({"error": "无此任务", "id": jid}, 404)
            return self._json(j)
        if p == "/points":
            jid = (q.get("id") or [""])[0]
            fp = os.path.join(_job_dir(jid), "points.json")
            if not os.path.exists(fp):
                return self._json({"error": "点云尚未生成", "id": jid}, 404)
            return self._s(200, open(fp, "rb").read(), "application/json; charset=utf-8")
        if p == "/trajectory":
            jid = (q.get("id") or [""])[0]
            fp = os.path.join(_job_dir(jid), "trajectory.json")
            if not os.path.exists(fp):
                return self._json({"error": "轨迹尚未生成"}, 404)
            return self._s(200, open(fp, "rb").read(), "application/json; charset=utf-8")
        if p == "/topview":
            jid = (q.get("id") or [""])[0]
            fp = os.path.join(_job_dir(jid), "map", "topview.png")
            if not os.path.exists(fp):
                return self._json({"error": "俯视图未生成"}, 404)
            return self._s(200, open(fp, "rb").read(), "image/png")
        # Three.js 本地托管 —— 产线内网没外网, 不能依赖 CDN
        if p.startswith("/lib/"):
            fn = os.path.basename(p)
            fp = os.path.join(_HERE, fn)
            if not os.path.exists(fp):
                return self._json({"error": "无此静态文件", "file": fn}, 404)
            ct = "application/javascript; charset=utf-8" if fn.endswith(".js") else "application/octet-stream"
            body = open(fp, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            return self.wfile.write(body)
        return self._json({"error": "no route", "path": p}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/upload":
            return self._json({"error": "no route"}, 404)
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self._json({"error": "需要 multipart/form-data"}, 400)
        # 从 header 拿 boundary, 不用 cgi (py3.13 已移除)
        try:
            boundary = ctype.split("boundary=")[1].strip().strip('"').encode()
        except IndexError:
            return self._json({"error": "缺 boundary"}, 400)
        clen = int(self.headers.get("Content-Length") or 0)
        if clen <= 0:
            return self._json({"error": "空请求"}, 400)
        if clen > 800 * 1024 * 1024:
            return self._json({"error": "视频超过 800MB, 请调低分辨率或缩短"}, 413)
        body = self.rfile.read(clen)
        parts = body.split(b"--" + boundary)
        vdata = None
        for part in parts:
            if b"name=\"video\"" in part and b"filename=" in part:
                idx = part.find(b"\r\n\r\n")
                if idx > 0:
                    vdata = part[idx + 4:].rstrip(b"\r\n-")
                break
        if not vdata or len(vdata) < 1024:
            return self._json({"error": "没收到视频数据 (或文件过小)"}, 400)
        tmp = os.path.join(WORK, "up_%s.mp4" % uuid.uuid4().hex[:8])
        with open(tmp, "wb") as f:
            f.write(vdata)
        jid = start_job(tmp)
        return self._json({"ok": True, "id": jid, "bytes": len(vdata),
                           "msg": "已收到视频, 开始建图"})


def main():
    ap = __import__("argparse").ArgumentParser()
    ap.add_argument("--port", type=int, default=8803)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), H)
    print("手机建图 App: http://0.0.0.0:%d/  (jobs=%s)" % (a.port, JOBS))
    srv.serve_forever()


if __name__ == "__main__":
    main()
