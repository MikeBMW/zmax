#!/usr/bin/env python3
"""守望 out_cov1114_24k 训练完成 → 发布成 8793 的 3DGS 资产(gsview 下拉可见)。

老倪 2026-11-14: 「B. 新的训练结果放到 http://10.163.146.76:8793/station 我看看」

判据(避免上次 4 小时的坑): train_report.json 存在 且 没有该 out 目录的 gs_train 进程。
发布 = 在 ~/zmax/zmax_data/gs_assets/<ASSET>/ 放 gs.splat
      (cam_live_stream._gs_assets() 按 gs.splat mtime 倒序列出, /gsview 下拉自动出现)
同时把 train_report.json 与一张渲染/GT 对照图放进资产目录, 让页面左侧能直接看到数字。
"""
import json
import os
import subprocess
import time

HOST = "intel@192.168.23.70"
OUT = "/home/intel/zmax_data/gs_rt/out_cov1114_24k"
DS = "/home/intel/zmax_data/gs_rt/ds_cov1114"
ASSET = "cov1114_24k"
DST = os.path.expanduser("~/zmax/zmax_data/gs_assets/" + ASSET)
MARK = "/tmp/gs_watch_cov24k.done"
POLL_S = 300


def sh(cmd, t=900):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)


def log(msg):
    print("[%s] %s" % (time.strftime("%F %T"), msg), flush=True)


def remote(cmd, t=120):
    q = cmd.replace("'", "'\"'\"'")
    r = sh("ssh -o BatchMode=yes -o ConnectTimeout=10 %s '%s'" % (HOST, q), t)
    return (r.stdout or "") + (r.stderr or "")


def done():
    cmd = ('test -f %s/train_report.json && echo REPORT_OK; '
           'pgrep -af "gs_train[.]py" | grep -v pgrep | grep -c "out_cov1114_24k" || true') % OUT
    txt = remote(cmd)
    if "REPORT_OK" not in txt:
        return False, {}
    lines = [x for x in txt.strip().splitlines() if x.strip()]
    try:
        still = int(lines[-1])
    except (ValueError, IndexError):
        still = 0
    if still > 0:
        return False, {}
    try:
        return True, json.loads(remote("cat %s/train_report.json" % OUT))
    except Exception:                                                       # noqa: BLE001
        return False, {}


def scp(remote_path, local_path):
    r = sh("scp -q -o BatchMode=yes %s:%s %s" % (HOST, remote_path, local_path), 900)
    return r.returncode == 0 and os.path.exists(local_path)


def publish(rep):
    os.makedirs(DST, exist_ok=True)
    ok = scp(OUT + "/gs.splat", os.path.join(DST, "gs.splat"))
    if not ok:
        log("❌ scp gs.splat 失败")
        return False
    with open(os.path.join(DST, "train_report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1)
    # 最新渲染帧 + 一张 GT, 拼左右对照(带数字), 图上自带证据
    lst = remote("ls -t %s/renders/*.png 2>/dev/null | head -1" % OUT).strip()
    gt = remote("ls -t %s/images/*.png 2>/dev/null | head -1; "
                "ls -t %s/images/*.jpg 2>/dev/null | head -1" % (DS, DS)).strip().splitlines()
    render_local = ""
    if lst:
        render_local = "/tmp/gs_cov24k_render.png"
        scp(lst.splitlines()[0], render_local)
    gt_local = ""
    if gt:
        gt_local = "/tmp/gs_cov24k_gt" + os.path.splitext(gt[0])[1]
        scp(gt[0], gt_local)
    if render_local and gt_local:
        try:
            import cv2
            import numpy as np
            a = cv2.imread(render_local)
            b = cv2.imread(gt_local)
            if a is not None and b is not None:
                h = 480
                a = cv2.resize(a, (int(a.shape[1] * h / a.shape[0]), h))
                b = cv2.resize(b, (int(b.shape[1] * h / b.shape[0]), h))
                cv = np.zeros((h + 46, a.shape[1] + b.shape[1] + 8, 3), np.uint8)
                cv[:] = (18, 18, 18)
                cv[46:, :a.shape[1]] = a
                cv[46:, a.shape[1] + 8:] = b
                txt = "MODEL RENDER  PSNR %.2f dB (vs 17.22 in-service)" % (rep.get("psnr_holdout_db") or 0)
                cv2.putText(cv, txt, (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 1, cv2.LINE_AA)
                cv2.putText(cv, "GROUND TRUTH", (a.shape[1] + 16, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 1, cv2.LINE_AA)
                cv2.imwrite(os.path.join(DST, "compare.png"), cv)
        except Exception as e:                                              # noqa: BLE001
            log("对照图拼装失败: %r" % (e,))
    with open(MARK, "w", encoding="utf-8") as fh:
        json.dump({"asset": ASSET, "psnr_holdout_db": rep.get("psnr_holdout_db"),
                   "n_gaussians": rep.get("n_gaussians"), "steps": rep.get("steps"),
                   "published_at": time.strftime("%F %T")}, fh, ensure_ascii=False, indent=1)
    log("✅ 已发布资产 %s · PSNR %.2f dB · 高斯 %s"
        % (ASSET, rep.get("psnr_holdout_db") or 0, rep.get("n_gaussians")))
    log("   看: http://10.163.146.76:8793/gsview?a=%s (station 页 3DGS 窗口下拉里也会出现)" % ASSET)
    return True


def main():
    log("守望开始: %s/train_report.json (每 %ds 查一次)" % (OUT, POLL_S))
    while not os.path.exists(MARK):
        ok, rep = done()
        if ok:
            log("训练完成: %s" % json.dumps({k: rep.get(k) for k in
                                            ("steps", "n_gaussians", "psnr_holdout_db", "seconds")},
                                           ensure_ascii=False))
            publish(rep)
            return 0
        time.sleep(POLL_S)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
