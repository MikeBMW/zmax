#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_posttrain_feishu.py —— 等 550C 那轮长训练跑完, 自动「发布资产 + 发图到飞书」。

老倪 2026-11-13: 「那好，训练完时，把训练好的图，发到飞书端。」

为什么不是定个 cron 猜时间: 训练 12000 步在 550C(XPU)上跑 ~2 小时, 时长随负载浮动。
这里直接盯 train_report.json 落盘 + 训练进程消失, 见到就算完成, 立刻:
  ① 拉 gs.splat / train_report.json / holdout 渲染图 + 对应原图
  ② 拼一张左右对照图(左=模型渲染, 右=原图), 图上一律标清楚数字
  ③ 发布成 8793 的资产(map_big_<ts>/), /gsview 下拉里能直接选
  ④ 用 tools/feishu_send.py 发图 + 文字(含 PSNR/步数/高斯数/链接), 并回读 message_id 当证据

判据(不夸大): PSNR 报的是 train_report.json 里 psnr_holdout_db 的原值; 图是模型自己渲的留出视角,
不是拍的, 也不是截图。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

REPO = "/home/ubuntu/zmax"
HOST = "intel"
OUT_NAME = os.environ.get("GS_OUT_NAME", "out_big_205138")
REMOTE_OUT = "/home/intel/zmax_data/gs_rt/" + OUT_NAME
ASSET_NAME = os.environ.get("GS_ASSET_NAME", "map_big_" + OUT_NAME.split("_")[-1])
ASSET_DIR = os.path.join(REPO, "zmax_data", "gs_assets", ASSET_NAME)
WORK = "/home/ubuntu/.hermes/cache/scratch/gs_posttrain"
CHAT = "oc_c0b4048546145c5c581ddd1a9e8f565d"          # dataworld 群(仓库 feishu_send 的默认上报群)
SEND = os.path.join(REPO, "tools", "feishu_send.py")
PY = os.path.join(REPO, "gui-venv311", "bin", "python")


def sh(cmd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def remote(cmd: str, timeout: int = 120) -> str:
    r = sh("ssh -o BatchMode=yes -o ConnectTimeout=10 %s '%s'" % (HOST, cmd.replace("'", "'\"'\"'")), timeout)
    return (r.stdout or "") + (r.stderr or "")


def log(msg: str) -> None:
    print("[%s] %s" % (time.strftime("%F %T"), msg), flush=True)


def train_done() -> tuple[bool, dict]:
    """完成判据: report 落盘 且 没有 gs_train 进程在跑。

    🔴 2026-11-14 04:56 踩坑(浪费 4 小时): 原写法 `pgrep -af 'gs_train.py' | grep -c out_big_205138`
       会**匹配到自己这条 ssh/bash 命令行**(里面同时含 "gs_train.py" 和 "out_big_205138"),
       于是永远判"还在跑", 训练 22:05 就完成了, 守望却等到 4 小时超时。
       修法: 模式里用 `[.]` 断开自身匹配, 并显式排除 pgrep/grep/bash 自身。
    """
    txt = remote("test -f %s/train_report.json && echo REPORT_OK; "
                 "pgrep -af 'zmax_map/tools/gs_train[.]py' | grep -v pgrep | grep -c 'out_big_205138' || true"
                 % REMOTE_OUT)
    ok = "REPORT_OK" in txt
    running = txt.strip().splitlines()[-1:] or ["0"]
    try:
        still = int(running[0])
    except ValueError:
        still = 0
    if not ok:
        return False, {}
    if still > 0:
        return False, {}
    r = sh("ssh -o BatchMode=yes %s 'cat %s/train_report.json'" % (HOST, REMOTE_OUT), 60)
    try:
        return True, json.loads(r.stdout)
    except Exception:
        return False, {}


def fetch(paths: list[str]) -> list[str]:
    os.makedirs(WORK, exist_ok=True)
    out = []
    for p in paths:
        dst = os.path.join(WORK, os.path.basename(p))
        r = sh("scp -q -o BatchMode=yes %s:%s %s" % (HOST, p, dst), 180)
        out.append(dst if r.returncode == 0 and os.path.exists(dst) else "")
    return out


def make_compare(render: str, gt: str, report: dict, dst: str) -> bool:
    """左=模型渲染 右=原图, 顶部标注数字。标数字是为了让图上自带证据, 不用别人猜。"""
    try:
        import cv2
        import numpy as np
    except Exception as e:                                                    # noqa: BLE001
        log("没有 cv2, 拼不了对照图: %r" % (e,))
        return False
    a = cv2.imread(render)
    b = cv2.imread(gt)
    if a is None or b is None:
        return False
    h = 480
    a = cv2.resize(a, (int(a.shape[1] * h / a.shape[0]), h))
    b = cv2.resize(b, (int(b.shape[1] * h / b.shape[0]), h))
    gap = 8
    canvas = np.zeros((h + 46, a.shape[1] + b.shape[1] + gap, 3), np.uint8)
    canvas[:] = (18, 18, 18)
    canvas[46:, :a.shape[1]] = a
    canvas[46:, a.shape[1] + gap:] = b
    psnr = report.get("psnr_holdout_db")
    txt_l = "MODEL RENDER  PSNR %.2f dB" % (psnr or 0)
    txt_r = "GROUND TRUTH (camera)"
    for txt, x in ((txt_l, 8), (txt_r, a.shape[1] + gap + 8)):
        cv2.putText(canvas, txt, (x, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (240, 240, 240), 1, cv2.LINE_AA)
    ok = cv2.imwrite(dst, canvas)
    return bool(ok)


def publish(report_path: str, splat: str) -> bool:
    os.makedirs(ASSET_DIR, exist_ok=True)
    # 🖼 渲染图也要进资产目录: /gs_render.png 是按"最新资产的 renders/holdout_00.png"取的,
    #    只发 gs.splat 会让工位页那格继续显示上一份的老图(2026-11-14 实测踩过)。
    rdir = os.path.join(ASSET_DIR, "renders")
    os.makedirs(rdir, exist_ok=True)
    for n in ("holdout_00.png", "holdout_00_gt.png"):
        src = os.path.join(WORK, n)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(rdir, n))
    ok = True
    for src, name in ((splat, "gs.splat"), (report_path, "train_report.json")):
        if not src or not os.path.exists(src):
            ok = False
            continue
        shutil.copy2(src, os.path.join(ASSET_DIR, name))
    log("资产已发布: %s (gs.splat %s)" % (ASSET_DIR, os.path.getsize(os.path.join(ASSET_DIR, "gs.splat")) if os.path.exists(os.path.join(ASSET_DIR, "gs.splat")) else "缺"))
    return ok


def send_feishu(image: str, text: str) -> dict:
    cmd = [PY, SEND, "--text", text, "--chat", CHAT]
    if image:
        cmd += ["--image", image]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    try:
        return json.loads(tail[0])
    except Exception:
        return {"ok": False, "raw": (r.stdout or "")[-400:] + (r.stderr or "")[-400:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--max-wait-h", type=float, default=4.0)
    ap.add_argument("--no-send", action="store_true", help="只做发布+拼图, 不发飞书(自测用)")
    a = ap.parse_args()

    t0 = time.time()
    log("盯着 %s 的训练结果 (最长 %.1f 小时)" % (REMOTE_OUT, a.max_wait_h))
    while True:
        done, rep = train_done()
        if done:
            break
        if time.time() - t0 > a.max_wait_h * 3600:
            log("等超时, 退出")
            return 2
        time.sleep(a.interval)

    psnr = rep.get("psnr_holdout_db")
    psnr_tr = rep.get("psnr_train_db")
    steps = rep.get("steps")
    ng = rep.get("n_gaussians")
    log("训练完成: PSNR留出 %.2f / 训练 %.2f · %s 步 · %s 高斯" % (psnr or 0, psnr_tr or 0, steps, ng))

    files = fetch([REMOTE_OUT + "/train_report.json", REMOTE_OUT + "/gs.splat",
                   REMOTE_OUT + "/renders/holdout_00.png", REMOTE_OUT + "/renders/holdout_00_gt.png"])
    rep_local, splat, rnder, gt = files
    publish(rep_local, splat)

    img = ""
    if rnder and gt:
        img = os.path.join(WORK, "compare_%s.png" % OUT_NAME)
        if make_compare(rnder, gt, rep, img):
            log("对照图: %s" % img)
        else:
            img = ""

    url = "http://10.163.146.76:8793/gsview?a=" + ASSET_NAME
    text = ("🧭 3DGS 建图完成（550C XPU 训练）\n"
            "资产: %s\n"
            "PSNR 留出 %.2f dB · 训练视角 %.2f dB\n"
            "%s 步 · %s 个高斯\n"
            "左=模型渲染(留出视角) 右=相机原图\n"
            "查看: %s" % (ASSET_NAME, psnr or 0, psnr_tr or 0, steps, ng, url))
    res = {"ok": False, "skipped": True} if a.no_send else send_feishu(img, text)
    log("飞书: %s" % json.dumps(res, ensure_ascii=False)[:300])

    out = os.path.join(REPO, "zmax_data", "reports", "gs_posttrain_%s.json" % OUT_NAME)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"job": OUT_NAME, "asset": ASSET_NAME, "psnr_holdout_db": psnr, "psnr_train_db": psnr_tr,
               "steps": steps, "n_gaussians": ng, "compare_png": img, "url": url, "feishu": res,
               "t": time.strftime("%F %T")}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("结果已记: %s" % out)
    return 0 if not a.no_send or res.get("skipped") else (0 if res.get("ok") else 1)


if __name__ == "__main__":
    sys.exit(main())
