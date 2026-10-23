#!/usr/bin/env python3
"""端到端验证: 带深度数据集 → 训练服务 → 确认用深度初始化。

造 20 帧小数据集 (彩色 + 16位深度 + cameras.json, 相机沿 +X 缓慢平移),
POST 给 :8804, 检查 job 的 init_source 是否为 depth, 并对比随机盒初始化的 PSNR。
"""
import io
import json
import os
import sys
import tarfile
import time
import urllib.request

import numpy as np

OUT = "/home/ubuntu/.hermes/cache/scratch/e2e_depth"
W, H = 640, 480
FX, FY, CX, CY = 394.062, 393.472, 318.444, 238.658
UNIT = 0.0001
N = 20


def build():
    import cv2
    ds = os.path.join(OUT, "ds")
    os.makedirs(ds + "/images", exist_ok=True)
    os.makedirs(ds + "/depth", exist_ok=True)
    frames = []
    for i in range(N):
        # 相机沿 +X 平移, 每帧 1cm, 朝向不变 (和成功案例的采集模式一致)
        T = np.eye(4)
        T[0, 3] = i * 0.01
        fn = "f_%04d.jpg" % i
        # 彩色: 造一个随视角平移的棋盘 (有结构, 便于看 PSNR 差异)
        img = np.zeros((H, W, 3), np.uint8)
        shift = i * int(0.01 / 0.5 * FX)   # 0.5m 处 1cm 位移对应的像素
        for x in range(0, W, 40):
            img[:, (x + shift) % W: (x + shift) % W + 20] = 200
        cv2.imwrite(os.path.join(ds, "images", fn), img)
        # 深度: 一堵 0.5m 平面
        d = np.full((H, W), int(0.5 / UNIT), np.uint16)
        cv2.imwrite(os.path.join(ds, "depth", fn[:-4] + ".png"), d)
        frames.append({"file": fn, "T_cam2world": T.tolist()})
    json.dump({"K": [[FX, 0, CX], [0, FY, CY], [0, 0, 1]], "frames": frames},
              open(ds + "/cameras.json", "w"))
    # 打包
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(ds, arcname="ds")
    return buf.getvalue()


def submit(tar_bytes, steps):
    req = urllib.request.Request(
        "http://127.0.0.1:8804/train?steps=%d" % steps,
        data=tar_bytes,
        headers={"Content-Type": "application/gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def wait(jid, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with urllib.request.urlopen("http://127.0.0.1:8804/job?id=%s" % jid, timeout=20) as r:
            d = json.loads(r.read())
        if d.get("state") in ("done", "failed"):
            return d
        time.sleep(15)
    return {"state": "timeout"}


def main():
    tb = build()
    print("[info] 数据集 %.1f KB, %d 帧" % (len(tb) / 1024, N))
    j = submit(tb, 3000)
    jid = j.get("id") or j.get("job_id")
    print("[info] 提交 job %s" % jid)

    d = wait(jid)
    print("\n=== 结果 ===")
    print("  state        %s" % d.get("state"))
    print("  init_source  %s   ← 必须是 depth" % d.get("init_source"))
    print("  init_note    %s" % (d.get("init_note") or "-"))
    print("  init_ply_mb  %s" % d.get("init_ply_mb"))
    print("  PSNR         %s dB" % d.get("psnr"))
    print("  高斯数       %s" % d.get("n_gaussians"))
    print("  耗时         %ss" % d.get("secs"))

    ok = d.get("state") == "done" and d.get("init_source") == "depth"
    print()
    print("✅ 深度链路端到端打通" if ok else "❌ 未生效")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
