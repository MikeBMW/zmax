#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shadow_live.py — 影子模式: 模型只预测, 不下发。真机正常跑, 边跑边比"模型说的"vs"你实际做的"。

口径与训练完全一致 (tools/live_train_loop.py build()):
    输入  image 96×96 RGB + joints_deg(6)
    输出  action7 = [Δx,Δy,Δz / dt*0.2, Δrx,Δry,Δrz / dt*0.2, 1.0]  → 即"0.2 秒内的位移"
    对照  当前真值 + 模型预测 vs 0.2 秒后的真值  → 逐拍误差 (mm / deg)

零下行: 只读 /api/tcp 与 /arm.mjpg; 不含任何 moveAppend。
输出: zmax_data/shadow_live/shadow_<ts>.jsonl  + 终端滚动中位数
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.request

import numpy as np
import torch
import torch.nn as nn
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from collect_live_dataset import MjpegReader          # noqa: E402

ROOT = "/home/ubuntu/zmax"
CK = os.environ.get("ZMAX_CK", os.path.join(ROOT, "models/live_policy_img.pt"))
API = "http://127.0.0.1:8797/api/tcp"
STREAM = "http://127.0.0.1:8791/arm.mjpg"
SZ = 96
OUT = os.path.join(ROOT, "zmax_data/shadow_live")


class Net(nn.Module):                    # 必须与训练脚本同构
    def __init__(self):
        super().__init__()
        self.c = nn.Sequential(nn.Conv2d(3, 16, 5, 2, 2), nn.ReLU(), nn.Conv2d(16, 32, 5, 2, 2),
                               nn.ReLU(), nn.AdaptiveAvgPool2d(4), nn.Flatten())
        self.f = nn.Sequential(nn.Linear(32 * 16 + 6, 128), nn.SiLU(), nn.Linear(128, 7))

    def forward(self, x, s):
        return self.f(torch.cat([self.c(x), s], 1))


def R_of(a, b, c):
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [[ca * cb, ca * sb * sc - sa * cc, ca * sb * cc + sa * sc],
            [sa * cb, sa * sb * sc + ca * cc, sa * sb * cc - ca * sc],
            [-sb, cb * sc, cb * cc]]


def ang_err(a, b):
    A, B = np.array(R_of(*a)), np.array(R_of(*b))
    tr = float((A.T @ B).trace())
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1) / 2.0))))


def rpy_of(q):
    x, y, z, w = q
    rx = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    ry = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    rz = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return rx, ry, rz


def truth():
    d = json.loads(urllib.request.urlopen(API, timeout=2).read())
    q = d.get("quat") or [0, 0, 0, 1]
    rpy = rpy_of(q[:4]) if len(q) >= 4 else (0.0, 0.0, 0.0)
    j = [math.degrees(float(v)) for v in (d.get("joints") or [])][:6]
    return dict(p=[d["x"] * 1000, d["y"] * 1000, d["z"] * 1000, *rpy], j=j)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    net = Net()
    ck = torch.load(CK, map_location="cpu")          # ckpt 是 {state_dict,size,val_rmse} 包了一层
    net.load_state_dict(ck["state_dict"] if isinstance(ck, dict) and "state_dict" in ck else ck)
    print("ckpt val_rmse %s" % (ck.get("val_rmse") if isinstance(ck, dict) else "?"), flush=True)
    net.eval()
    print("模型: %s" % CK, flush=True)
    mr = MjpegReader(STREAM).start()
    out = os.path.join(OUT, "shadow_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
    errs, n = [], 0
    with open(out, "w", buffering=1) as f:
        while True:
            buf = mr.frame()
            if buf is None:
                time.sleep(0.05); continue
            try:
                t0 = truth()
            except Exception:
                time.sleep(0.1); continue
            im = Image.open(__import__("io").BytesIO(buf)).convert("RGB").resize((SZ, SZ))
            x = torch.tensor((np.asarray(im, np.float32) / 255.0).transpose(2, 0, 1))[None]
            s = torch.tensor(np.asarray(t0["j"], np.float32))[None]
            with torch.no_grad():
                a = net(x, s)[0].tolist()
            time.sleep(0.2)                        # 等 0.2 秒看真值实际走成什么样
            try:
                t1 = truth()
            except Exception:
                continue
            if t1["p"][:3] == t0["p"][:3]:
                continue                            # 臂没动, 不算一拍
            pred = [t0["p"][i] + a[i] for i in range(3)] + [t0["p"][3 + i] + a[3 + i] for i in range(3)]
            e_xyz = math.dist(pred[:3], t1["p"][:3])
            e_ang = ang_err(pred[3:], t1["p"][3:])
            errs.append((e_xyz, e_ang))
            n += 1
            f.write(json.dumps({"ts": t0["p"], "pred": pred, "act": t1["p"],
                                "err_mm": round(e_xyz, 3), "err_deg": round(e_ang, 3)}) + "\n")
            if n % 10 == 0:
                mm = np.median([e[0] for e in errs[-100:]])
                dg = np.median([e[1] for e in errs[-100:]])
                print("[%s] %d 拍 · 中位误差 %.2fmm / %.2f°"
                      % (time.strftime("%H:%M:%S"), n, mm, dg), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
