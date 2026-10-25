#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重训完成后自动接管：等 Intel 训练进程退出 → 读指标 → 优于旧版才切换推流 → 出对比图。

老倪口径（2026-10-25）: 「4060 只是显示，而 intel 要渲染好，推流过来」
  · 训练与渲染都在 Intel(XPU)；本机只做显示与归档。
  · **只有指标比在役版本更好才切换**（新模型/功能接入门槛: 有提升非仅不回退）。
  · 切换动作: 换 --ply/--report 重启 Intel 渲染器 ⇒ 页面 /gs/live.jpg 自动变成新图, 无需改页面。

用法: python3 tools/gs_retrain_swap.py --job 20261025_1030_retrain30k --baseline 15.26 [--run]
      不带 --run 只做一次体检(不等待、不切换)。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

HOST = "intel"
JOBS = "/home/intel/gs_train_service_intel/jobs"
STREAM = "/home/intel/zmax_map/tools/gs_render_stream_intel.py"
PY = "/home/intel/gsxpu-venv/bin/python"
ASSETS = "/home/ubuntu/zmax/zmax_data/gs_assets"
LOG = "/home/ubuntu/.hermes/cache/scratch/retrain_swap.log"


def say(msg):
    line = "[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def ssh(cmd, timeout=60):
    p = subprocess.run(["ssh", "-o", "ConnectTimeout=10", HOST, cmd],
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.strip(), p.stderr.strip()[-300:]


def training_alive(job):
    rc, out, _ = ssh("pgrep -fc 'gs_train.py .*%s'" % job)
    try:
        return int(out.strip() or 0) > 0
    except Exception:                                                        # noqa: BLE001
        return False


def report(job):
    rc, out, err = ssh("cat %s/%s/out/train_report.json" % (JOBS, job))
    if rc != 0 or not out.startswith("{"):
        return None, err
    return json.loads(out), ""


def snapshot_stream(job):
    rc, out, _ = ssh("pgrep -f gs_render_stream_intel.py")
    return [int(x) for x in out.split() if x.strip().isdigit()]


def restart_stream(job):
    """换 ply/report 重启 Intel 渲染器（本机只显示, 渲染全在 Intel）。"""
    jd = "%s/%s" % (JOBS, job)
    script = "/tmp/start_gsstream.sh"
    body = ("#!/usr/bin/env bash\n"
            "exec %s %s --ply %s/out/gs.ply --cameras %s/ds/cameras.json "
            "--report %s/out/train_report.json --port 8816 --fps 6 "
            ">> /home/intel/gs_render_stream.log 2>&1\n" % (PY, STREAM, jd, jd, jd))
    tmp = "/home/ubuntu/.hermes/cache/scratch/_start_gsstream.sh"
    open(tmp, "w", encoding="utf-8").write(body)
    subprocess.run(["scp", "-q", tmp, "%s:%s" % (HOST, script)], check=True, timeout=60)
    ssh("chmod +x %s" % script)
    pids = snapshot_stream(job)
    if pids:
        ssh("kill -TERM %s" % " ".join(str(p) for p in pids))
        time.sleep(3)
    ssh("setsid nohup %s < /dev/null > /dev/null 2>&1 & sleep 1; pgrep -fc gs_render_stream_intel.py" % script)
    time.sleep(35)
    rc, out, _ = ssh("curl -s -m 6 http://127.0.0.1:8816/health")
    try:
        h = json.loads(out)
    except Exception:                                                        # noqa: BLE001
        return False, {"raw": out[:200]}
    ok = bool(h.get("ok")) and h.get("gaussians", 0) > 0
    return ok, h


def pull_assets(job):
    remote = "%s/%s/out" % (JOBS, job)
    dst = os.path.join(ASSETS, "intel_" + job)
    os.makedirs(os.path.join(dst, "renders"), exist_ok=True)
    for src, d in (("gs.splat", dst), ("gs.ply", dst), ("train_report.json", dst), ("renders/*", os.path.join(dst, "renders"))):
        subprocess.run(["scp", "-q", "%s:%s/%s" % (HOST, remote, src), d if not src.endswith("*") else d + "/"],
                       timeout=900)
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--baseline", type=float, default=15.26, help="在役版本 holdout PSNR")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    say("观察 job=%s · 基线 PSNR=%.2f" % (a.job, a.baseline))

    if not a.run:
        r, err = report(a.job)
        alive = training_alive(a.job)
        say("训练进程在跑=%s · report=%s %s" % (alive, "有" if r else "无", err))
        if r:
            say("当前 report: %s" % json.dumps({k: r.get(k) for k in ("state", "psnr_holdout_db", "psnr_train_db",
                                                                      "n_gaussians", "steps", "secs")},
                                                ensure_ascii=False))
        return

    last = ""
    while training_alive(a.job):
        r, _ = report(a.job)
        cur = ""
        if r:
            cur = "%s/30000 步" % r.get("steps")
        if cur != last:
            say("训练中… %s" % cur)
            last = cur
        time.sleep(240)

    say("训练进程已退出, 读指标")
    time.sleep(20)
    r, err = report(a.job)
    if not r:
        say("❌ 没有 train_report.json (%s) ⇒ 不切换" % err)
        return
    new = float(r.get("psnr_holdout_db") or 0)
    say("新版本 holdout PSNR=%.2f dB · train=%.2f · 高斯=%s · 步数=%s · %.0fs"
        % (new, float(r.get("psnr_train_db") or 0), r.get("n_gaussians"), r.get("steps"), float(r.get("secs") or 0)))

    if new <= a.baseline:
        say("❌ 新版本没有提升 (%.2f ≤ 基线 %.2f) ⇒ **不切换**, 页面继续推旧版" % (new, a.baseline))
        return

    say("✅ 有提升 (+%.2f dB) ⇒ 归档 + 切换推流" % (new - a.baseline))
    try:
        d = pull_assets(a.job)
        say("归档到 %s" % d)
    except Exception as e:                                                   # noqa: BLE001
        say("⚠️ 归档失败(不影响推流): %s" % str(e)[:160])
    ok, h = restart_stream(a.job)
    say("推流切换 %s · %s" % ("成功" if ok else "失败", json.dumps(h, ensure_ascii=False)[:220]))


if __name__ == "__main__":
    main()
