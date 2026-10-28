#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🩺 位姿真值中继: Orin SDK 桥 /status → 本机 zmax_data/rokae_sdk/tcp_out/latest.json

为什么需要 (2026-10-25 现场):
  · 本机 `rokae_tcp_sampler` 容器 CrashLoop(无产线路由, `RuntimeError: network: network connection`),
    `latest.json` 冻在 16:11 ⇒ ① AR 页「规划已 362 分钟」不许执行 ② l2_daemon 每单都被
    「位姿读不到(直读失败且常驻缓存过期)」拒 ③ traj_exec 观测定到位全失效。
  · 唯一活着的位姿源是 Orin 的 SDK 桥 (`:39061/status`, 口径 endInRef, 20~50Hz)。
  · 本脚本把它搬到本机那份"唯一依据文件"上, 口径/字段与采样器**逐字一致**, 只把 src 标成中继, 好追溯。

口径:
  · 原子写 (tmp + rename) 防读到半截 JSON
  · 桥断了就不写(宁可让文件变旧 ⇒ 下游按 stale 处理), 绝不拿旧值刷 ts 冒充新鲜
  · rpy → quat 用 ZYX 欧拉(与本机采样器同一约定)
"""
import json
import math
import os
import sys
import time
import urllib.request

BRIDGE = os.environ.get("ZMAX_BRIDGE_URL") or "http://127.0.0.1:39071"
OUT = os.environ.get("ZMAX_POSE_OUT") or "/home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/latest.json"
PERIOD = float(os.environ.get("ZMAX_POSE_RELAY_HZ") or 2.0)


def rpy_to_quat(rx, ry, rz):
    """ZYX: R = Rz(rz)·Ry(ry)·Rx(rx)"""
    cx, sx = math.cos(rx / 2.0), math.sin(rx / 2.0)
    cy, sy = math.cos(ry / 2.0), math.sin(ry / 2.0)
    cz, sz = math.cos(rz / 2.0), math.sin(rz / 2.0)
    return [
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
        cx * cy * cz + sx * sy * sz,
    ]


def fetch():
    with urllib.request.urlopen(BRIDGE + "/status", timeout=3) as r:
        d = json.loads(r.read().decode())
    s = d.get("status") or {}
    e = s.get("endInRef") or []
    if len(e) < 6:
        raise ValueError("endInRef 不足 6 位: %s" % (e,))
    qx, qy, qz, qw = rpy_to_quat(float(e[3]), float(e[4]), float(e[5]))
    return {
        "ts": time.time(),
        "t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "x": float(e[0]), "y": float(e[1]), "z": float(e[2]),
        "rx": float(e[3]), "ry": float(e[4]), "rz": float(e[5]),
        "qx": qx, "qy": qy, "qz": qz, "qw": qw,
        "frame": "base_link",
        "src": "orin_sdk_bridge/endInRef (relay, no DDS)",
        "joint": [float(v) for v in (s.get("jointPos") or [])][:12],
    }


def write_atomic(obj):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, OUT)


def main():
    n = 0
    last_err = ""
    while True:
        t0 = time.time()
        try:
            write_atomic(fetch())
            n += 1
            if n % 60 == 1:
                print("[%s] 已中继 %d 次 · %s" % (time.strftime("%H:%M:%S"), n, OUT), flush=True)
        except Exception as e:                                              # noqa: BLE001
            msg = str(e)[:90]
            if msg != last_err:
                print("[%s] ⚠️ 取位姿失败(不写旧值): %s" % (time.strftime("%H:%M:%S"), msg), flush=True)
                last_err = msg
        time.sleep(max(0.0, PERIOD - (time.time() - t0)))


if __name__ == "__main__":
    sys.exit(main())
