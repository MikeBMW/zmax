#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_train_service.py — 3DGS 训练服务 (跑在 4060, 有 CUDA)

为什么要单独一个服务:
  3DGS 训练硬依赖 CUDA (gsplat), Intel 的 Arc 核显跑不了。
  手机 App 在 Intel (抽帧 + 单目 SfM 都在 Intel 侧, 纯 numpy/OpenCV),
  SfM 出位姿后把数据集送到这里训, 训完把 .splat 拿回去给手机渲染。

铁律:
  · 必须走 tools/run_gs_train.sh (cuda-shim 环境), 直接调 python 会
    报 'NoneType' object has no attribute 'CameraModelType'
  · 串行训练 (4060 只有 8G 显存, 不许并发)
  · 产物落盘, 任务记录写 job.json 做证据

端点:
  GET  /health              服务与 CUDA 状态
  GET  /job?id=xxx          任务状态
  GET  /splat?id=xxx        下载 .splat (手机渲染用)
  GET  /render?id=xxx&n=1   看训练出的渲染图 (PNG)
  POST /train               提交数据集 (multipart: dataset.tar.gz)
"""
from __future__ import annotations

import io
import json
import os
import glob
import os.path as osp
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.expanduser("~/gs_train_service")
JOBS = osp.join(ROOT, "jobs")
RUNNER = "/home/ubuntu/zmax/tools/run_gs_train.sh"
DEPTH2PLY = "/home/ubuntu/zmax/tools/gs_depth_to_ply.py"
os.makedirs(JOBS, exist_ok=True)

TASKS = {}
LOCK = threading.Lock()
QUEUE = threading.Semaphore(1)      # 串行: 一次只训一个


def _jd(jid):
    return osp.join(JOBS, jid)


def _save(jid, d):
    with LOCK:
        TASKS[jid] = d
    try:
        json.dump(d, open(osp.join(_jd(jid), "job.json"), "w"), ensure_ascii=False, indent=1)
    except Exception:
        pass


def _load(jid):
    with LOCK:
        if jid in TASKS:
            return TASKS[jid]
    p = osp.join(_jd(jid), "job.json")
    if osp.exists(p):
        try:
            d = json.load(open(p))
            with LOCK:
                TASKS[jid] = d
            return d
        except Exception:
            pass
    return None


def _unpack(tar_bytes, dest):
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        for m in tf.getmembers():
            # 防路径穿越
            if m.name.startswith("/") or ".." in m.name.split("/"):
                raise RuntimeError("压缩包里有非法路径: %s" % m.name)
        tf.extractall(dest)
    return dest


def _find_dataset(dest):
    """数据集根 = 含 cameras.json 的目录"""
    for dp, _, fns in os.walk(dest):
        if "cameras.json" in fns:
            return dp
    raise RuntimeError("压缩包里找不到 cameras.json")


def worker(jid, ds_root, steps):
    d = _jd(jid)
    job = {"id": jid, "state": "queued", "msg": "排队等 GPU", "t0": time.time(),
           "steps": steps, "psnr": None, "n_gaussians": None, "err": "",
           "splat_bytes": None, "secs": None}
    _save(jid, job)
    QUEUE.acquire()
    try:
        job.update(state="training", msg="3DGS 训练中 (%d 步)" % steps)
        _save(jid, job)
        out = osp.join(d, "out")
        os.makedirs(out, exist_ok=True)
        cmd = [RUNNER, "--data", ds_root, "--out", out, "--steps", str(steps)]
        # 有深度就反投影成初始点云。gs_train.py 没初始点云时会在"相机前 0.28m"摆一个
        # 0.30x0.30x0.20m 的随机盒子, 和真实场景毫无关系, 全靠训练去纠正 ⇒ PSNR 卡 14~15。
        depth_dir = osp.join(ds_root, "depth")
        init_ply = osp.join(d, "init.ply")
        if osp.isdir(depth_dir) and (glob.glob(osp.join(depth_dir, "*.png"))
                                     or glob.glob(osp.join(depth_dir, "*.raw"))):
            try:
                dp = subprocess.run(
                    [sys.executable, DEPTH2PLY, "--src", ds_root, "--out", init_ply],
                    capture_output=True, text=True, timeout=900)
                if dp.returncode == 0 and osp.exists(init_ply):
                    cmd += ["--init-ply", init_ply]
                    job["init_source"] = "depth"
                    job["init_ply_mb"] = round(os.path.getsize(init_ply) / 1048576, 2)
                    _save(jid, job)
                else:
                    job["init_source"] = "random_box"
                    job["init_note"] = ("深度反投影失败: %s"
                                        % ((dp.stderr or dp.stdout or "")[-300:]))
                    _save(jid, job)
            except Exception as e:
                job["init_source"] = "random_box"
                job["init_note"] = "深度反投影异常: %s" % str(e)[:300]
                _save(jid, job)
        else:
            job["init_source"] = "random_box"
            job["init_note"] = "数据集无 depth/ 目录, 沿用旧的随机盒初始化"
            _save(jid, job)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        if r.returncode != 0:
            tail = ((r.stdout or "") + (r.stderr or ""))[-600:]
            raise RuntimeError("训练失败: %s" % tail)
        rep_p = osp.join(out, "train_report.json")
        if not osp.exists(rep_p):
            raise RuntimeError("训练未产出 train_report.json")
        rep = json.load(open(rep_p))
        splat = osp.join(out, "gs.splat")
        job.update(state="done", msg="训练完成",
                   psnr=round(float(rep.get("psnr_holdout_db") or 0), 2),
                   n_gaussians=rep.get("n_gaussians"),
                   splat_bytes=os.path.getsize(splat) if osp.exists(splat) else 0,
                   train_secs=round(float(rep.get("seconds") or 0), 1),
                   secs=round(time.time() - job["t0"], 1))
    except Exception as e:
        job.update(state="failed", msg="失败", err=str(e), secs=round(time.time() - job["t0"], 1))
    finally:
        QUEUE.release()
    _save(jid, job)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _s(self, code, body, ct="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, o, c=200):
        self._s(c, json.dumps(o, ensure_ascii=False))

    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        if p == "/health":
            gpu = ""
            try:
                gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,utilization.gpu",
                                      "--format=csv,noheader"], capture_output=True, text=True,
                                     timeout=10).stdout.strip()
            except Exception as e:
                gpu = "nvidia-smi 失败: %s" % e
            return self._json({"ok": True, "gpu": gpu, "runner_exists": osp.exists(RUNNER),
                               "busy": QUEUE._value == 0, "jobs": len(TASKS)})
        if p == "/job":
            j = _load((q.get("id") or [""])[0])
            return self._json(j) if j else self._json({"error": "无此任务"}, 404)
        # 机械臂 TCP 真值 —— Intel 采集守护进程要配位姿, 但 Intel 上没有 ROS/没有 ROKAE SDK,
        # 所以由 4060 读唯一依据文件暴露成 HTTP (只读, 不碰下发链)
        if p == "/pose":
            fp = os.path.expanduser("~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json")
            try:
                with open(fp) as f:
                    d = json.load(f)
                # 🔴 不能用 d["ts"] 算 age: NTP 回拨 8h 导致位姿时间戳是"未来",
                #    age 变负数, stale 永远为假 ⇒ 用到陈旧位姿还以为新鲜。
                #    唯一依据新鲜度只看文件 mtime。
                age = time.time() - os.path.getmtime(fp)
                d["age_s"] = round(age, 3)
                d["stale"] = age > 3.0
                d["age_src"] = "file_mtime"
                return self._json(d)
            except Exception as e:
                return self._json({"error": "读位姿失败: %s" % e, "stale": True}, 503)
        if p == "/splat":
            jid = (q.get("id") or [""])[0]
            fp = osp.join(_jd(jid), "out", "gs.splat")
            if not osp.exists(fp):
                return self._json({"error": "splat 未生成"}, 404)
            return self._s(200, open(fp, "rb").read(), "application/octet-stream")
        if p == "/render":
            jid = (q.get("id") or [""])[0]
            n = int((q.get("n") or ["1"])[0])
            rd = osp.join(_jd(jid), "out", "renders")
            if not osp.isdir(rd):
                return self._json({"error": "无渲染图"}, 404)
            fs = sorted(f for f in os.listdir(rd) if f.endswith(".png"))
            if not fs:
                return self._json({"error": "无渲染图"}, 404)
            return self._s(200, open(osp.join(rd, fs[min(n, len(fs) - 1)]), "rb").read(), "image/png")
        return self._json({"error": "no route", "path": p}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/train":
            return self._json({"error": "no route"}, 404)
        ct = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ct:
            return self._json({"error": "需要 multipart/form-data"}, 400)
        try:
            boundary = ct.split("boundary=")[1].strip().strip('"').encode()
        except IndexError:
            return self._json({"error": "缺 boundary"}, 400)
        clen = int(self.headers.get("Content-Length") or 0)
        if clen <= 0:
            return self._json({"error": "空请求"}, 400)
        if clen > 900 * 1024 * 1024:
            return self._json({"error": "数据集超过 900MB"}, 413)
        body = self.rfile.read(clen)
        steps = 1000
        data = None
        for part in body.split(b"--" + boundary):
            if b'name="steps"' in part:
                idx = part.find(b"\r\n\r\n")
                if idx > 0:
                    try:
                        steps = int(part[idx + 4:].strip().split(b"\r\n")[0])
                    except Exception:
                        pass
            elif b'name="dataset"' in part and b"filename=" in part:
                idx = part.find(b"\r\n\r\n")
                if idx > 0:
                    data = part[idx + 4:].rstrip(b"\r\n-")
        if not data:
            return self._json({"error": "没收到 dataset"}, 400)
        jid = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        jd = _jd(jid)
        os.makedirs(jd, exist_ok=True)
        try:
            _unpack(data, osp.join(jd, "ds"))
            ds_root = _find_dataset(osp.join(jd, "ds"))
        except Exception as e:
            return self._json({"error": str(e)}, 400)
        threading.Thread(target=worker, args=(jid, ds_root, steps), daemon=True).start()
        return self._json({"ok": True, "id": jid, "bytes": len(data), "steps": steps,
                           "msg": "已收数据集, 开始训练"})


def main():
    ap = __import__("argparse").ArgumentParser()
    ap.add_argument("--port", type=int, default=8804)
    a = ap.parse_args()
    print("3DGS 训练服务: http://0.0.0.0:%d/  (runner=%s)" % (a.port, RUNNER))
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
