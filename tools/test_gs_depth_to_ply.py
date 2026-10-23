#!/usr/bin/env python3
"""gs_depth_to_ply 自测 —— 造一个已知几何的深度图, 验证反投影数学。

判据必须是可量化的: 
  · 造一堵 z=0.5m 的平面, 左半边提到 z=0.3m
  · 单位位姿 (相机在原点, +Z 向前)
  · 反投影后: 左半点 z 必须恰好 0.300, 右半点 z 必须恰好 0.500 (±1e-3)
  · 图像左半边 (u < cx) 的世界 x 必须为负
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TEST_DIR = "/home/ubuntu/.hermes/cache/scratch/depth_test"
W, H = 640, 480
FX, FY, CX, CY = 394.062, 393.472, 318.444, 238.658
UNIT = 0.0001


def make_fixture():
    import cv2
    os.makedirs(TEST_DIR + "/images", exist_ok=True)
    os.makedirs(TEST_DIR + "/depth", exist_ok=True)

    depth = np.full((H, W), int(0.5 / UNIT), dtype=np.uint16)
    depth[:, :W // 2] = int(0.3 / UNIT)
    cv2.imwrite(TEST_DIR + "/depth/f_0000.png", depth)
    cv2.imwrite(TEST_DIR + "/images/f_0000.jpg", np.full((H, W, 3), 128, np.uint8))

    frames = [{"file": "f_0000.jpg", "T_cam2world": np.eye(4).tolist()}]
    with open(TEST_DIR + "/cameras.json", "w") as f:
        json.dump({"K": [[FX, 0, CX], [0, FY, CY], [0, 0, 1]], "frames": frames}, f)


def read_ply_xyz(path):
    with open(path, "rb") as f:
        data = f.read()
    he = data.index(b"end_header\n") + len(b"end_header\n")
    ln = [l for l in data[:he].decode().split("\n") if l.startswith("element vertex")][0]
    n = int(ln.split()[-1])
    dt = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                   ("r", "u1"), ("g", "u1"), ("b", "u1")])
    pts = np.frombuffer(data[he:he + n * dt.itemsize], dtype=dt)
    return n, np.stack([pts["x"], pts["y"], pts["z"]], axis=1)


def main():
    make_fixture()
    out = TEST_DIR + "/init.ply"
    if os.path.exists(out):
        os.remove(out)

    import subprocess
    r = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "gs_depth_to_ply.py"),
         "--src", TEST_DIR, "--out", out, "--max-points", "200000"],
        capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print("[STDERR]", r.stderr)
        return 1

    n, xyz = read_ply_xyz(out)
    left = xyz[xyz[:, 2] < 0.4]
    right = xyz[xyz[:, 2] >= 0.4]

    print("=== 反向验证 (单位位姿, 相机 +Z 向前) ===")
    print("  点数 %s" % format(n, ","))
    print("  z 范围 %.4f ~ %.4f  (期望 0.3000 ~ 0.5000)"
          % (xyz[:, 2].min(), xyz[:, 2].max()))
    print("  左半 z 均值 %.4f  (期望 0.3000)  %s 点" % (left[:, 2].mean(), format(len(left), ",")))
    print("  右半 z 均值 %.4f  (期望 0.5000)  %s 点" % (right[:, 2].mean(), format(len(right), ",")))
    print("  左半 x 均值 %.4f  (期望 < 0)" % left[:, 0].mean())
    print("  右半 x 均值 %.4f  (期望 > 0)" % right[:, 0].mean())

    checks = [
        ("左半 z == 0.300", abs(left[:, 2].mean() - 0.3) < 1e-3),
        ("右半 z == 0.500", abs(right[:, 2].mean() - 0.5) < 1e-3),
        ("左半 x < 0", left[:, 0].mean() < 0),
        ("右半 x > 0", right[:, 0].mean() > 0),
        # 传了 --max-points 200000 ⇒ 下采样到 20 万是预期行为, 不是丢点
        ("点数 <= max-points 且 > 0", 0 < n <= 200000),
        ("下采样前后都覆盖两侧", len(left) > 1000 and len(right) > 1000),
    ]
    print()
    allok = True
    for name, ok in checks:
        print("  [%s] %s" % ("PASS" if ok else "FAIL", name))
        allok = allok and ok
    print()
    print("✅ 反投影数学正确" if allok else "❌ 有偏差")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
