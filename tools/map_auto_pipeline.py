#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🤖 老倪手动拖臂 → 自动建 3DGS (无人值守一段式)

老倪 2026-10-26:「我来拖动，你建图」
  他在示教/拖动模式下手动带臂扫场, 我这边: 采集器一直在记帧+深度+位姿;
  这个脚本盯着位姿流, **停手 120 秒**且新增帧够数 ⇒ 自动收尾:
    ① 停采集器  ② 抽稀成数据集(位姿+深度, 手眼变换)  ③ 提交 8814 训练  ④ 等训练完出 .splat/.ply
  进度全写 /tmp/drag_pipeline.log (一行 JSON 一个事件), 训练完再回传 splat 给 8793 发布。

用法:
  python tools/map_auto_pipeline.py --session <sessions/xxx> --idle-sec 120 --min-frames 80 --steps 5000
"""
import argparse
import glob
import json
import os
import os.path as osp
import subprocess
import sys
import time
import urllib.request


def log(ev, **kw):
    rec = {"t": time.strftime("%H:%M:%S"), "ev": ev}
    rec.update(kw)
    with open("/tmp/drag_pipeline.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), flush=True)


def n_frames(sess):
    try:
        return len(os.listdir(osp.join(sess, "frames")))
    except Exception:                                                            # noqa: BLE001
        return 0


def last_pose(sess):
    p = osp.join(sess, "poses.jsonl")
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4000))
            lines = [x for x in f.read().decode("utf-8", "replace").splitlines() if x.strip()]
        return json.loads(lines[-1])
    except Exception:                                                            # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--idle-sec", type=float, default=120.0)
    ap.add_argument("--min-frames", type=int, default=80)
    ap.add_argument("--max-wait-sec", type=float, default=3600.0)
    ap.add_argument("--steps", type=int, default=5000)
    ap.add_argument("--min-gap-mm", type=float, default=8.0)
    ap.add_argument("--min-gap-deg", type=float, default=1.0)
    a = ap.parse_args()

    log("start", session=a.session, idle_sec=a.idle_sec, min_frames=a.min_frames)
    t0 = time.time()
    last_n, last_change, cur = 0, time.time(), None
    while True:
        n = n_frames(a.session)
        p = last_pose(a.session)
        # 🔴 用**位姿是否真的在动**判"停手", 不能用帧数增长:
        #    采集器不动也会一直按 10Hz 记同样的位姿 ⇒ 帧数永远在涨 ⇒ 永远等不到 idle(实测踩过)。
        moved = False
        if p and cur:
            dmm = max(abs(p["tcp_mm"][k] - cur["tcp_mm"][k]) for k in range(3))
            drd = max(abs((p["tcp_rpy"][k] if p.get("tcp_rpy") else 0)
                          - (cur["tcp_rpy"][k] if cur.get("tcp_rpy") else 0)) for k in range(3))
            moved = (dmm > 5.0) or (drd > 0.035)          # 5mm 或 2°
        if p and (cur is None or moved):
            last_change = time.time()
        cur = p or cur
        if n != last_n:
            last_n = n
        idle = time.time() - last_change
        if n >= a.min_frames and idle >= a.idle_sec:
            log("idle_detected", frames=n, idle_s=round(idle, 1),
                last_tcp=(cur or {}).get("tcp_mm"))
            break
        if time.time() - t0 > a.max_wait_sec:
            log("timeout", frames=n, idle_s=round(idle, 1))
            if n < a.min_frames:
                log("abort", why="帧数不足 %d < %d" % (n, a.min_frames))
                return 2
            break
        if int(idle) % 30 == 0:
            time.sleep(1.5)
        time.sleep(3.0)

    # ① 停采集器 (只停指向这个 session 的)
    try:
        out = subprocess.run(["pgrep", "-af", "map_recorder_550c.py"], capture_output=True,
                             text=True, timeout=10).stdout.strip().splitlines()
        for ln in out:
            if a.session in ln or "traj3d" in ln or "drag" in ln:
                pid = int(ln.split()[0])
                os.kill(pid, 15)
                log("recorder_stopped", pid=pid)
                time.sleep(1.5)
    except Exception as e:                                                       # noqa: BLE001
        log("recorder_stop_fail", err=str(e)[:120])

    # ② 建数据集
    ds = "/home/intel/zmax_550c/zmax_data/mapping/ds_" + osp.basename(a.session)
    tarball = "/tmp/%s.tar.gz" % osp.basename(a.session)
    cmd = ["/home/intel/train_venv/bin/python",
           "/home/intel/zmax_550c/tools/map_build_3dgs_ds.py",
           "--session", a.session, "--out", ds, "--tar", tarball,
           "--min-gap-mm", str(a.min_gap_mm), "--min-gap-deg", str(a.min_gap_deg),
           "--max-views", "400"]
    env = dict(os.environ, ZMAX_MODELS="/home/intel/zmax_550c/models")
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=900)
    tail = (r.stdout or "")[-600:] + (r.stderr or "")[-400:]
    log("dataset", rc=r.returncode, tail=tail)
    if r.returncode != 0:
        return 3

    # ③ 提交训练
    boundary = "----zmaxdrag"
    body = []
    for k, v in (("steps", str(a.steps)),):
        body.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                     % (boundary, k, v)).encode())
    data = open(tarball, "rb").read()
    body.append(("--%s\r\nContent-Disposition: form-data; name=\"dataset\"; filename=\"ds.tar.gz\"\r\n"
                 "Content-Type: application/gzip\r\n\r\n" % boundary).encode() + data + b"\r\n")
    body.append(("--%s--\r\n" % boundary).encode())
    req = urllib.request.Request("http://127.0.0.1:8814/train", data=b"".join(body),
                                 headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
    jid = None
    try:
        j = json.loads(urllib.request.urlopen(req, timeout=300).read())
        jid = j.get("id")
        log("train_submitted", jid=jid, bytes=len(data), steps=a.steps)
    except Exception as e:                                                       # noqa: BLE001
        log("train_submit_fail", err=str(e)[:200])
        return 4

    # ④ 等训练完
    t1 = time.time()
    while time.time() - t1 < 3600:
        time.sleep(20)
        try:
            j = json.loads(urllib.request.urlopen(
                "http://127.0.0.1:8814/job?id=%s" % jid, timeout=20).read())
        except Exception:                                                        # noqa: BLE001
            continue
        if j.get("state") in ("done", "error"):
            log("train_done", **{k: j.get(k) for k in
                                 ("state", "psnr", "n_gaussians", "splat_bytes", "secs", "err")})
            out = "/home/intel/gs_train_service_intel/jobs/%s/out" % jid
            log("artifacts", splat=osp.join(out, "gs.splat"),
                report=osp.join(out, "train_report.json"),
                renders=sorted(glob.glob(osp.join(out, "renders", "*.png")))[:3])
            return 0
        if int(time.time() - t1) % 120 < 21:
            log("training", msg=j.get("msg"), state=j.get("state"))
    log("train_timeout", jid=jid)
    return 5


if __name__ == "__main__":
    sys.exit(main())
