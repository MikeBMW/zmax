#!/usr/bin/env python3
"""ft_pose_sampler.py — 同时落盘「六维力 + 末端姿态四元数 + 关节」, 用来拟合重力补偿。

为什么需要: 实测同一台臂, 在口沿姿态读到 fx −5.7 / fy −3.9 / fz −15.5 (|F| 17.0N),
回到原点位读 +3.7 / +8.9 / −7.9 —— 说明 getEndTorque 里带着**未补偿的工具重力**,
而且随姿态转。力控判据(接触/入孔)必须先把这块减掉, 否则 17N 的假偏置会把 6N 的接触全淹掉。

跑法 (容器里, 与 ft_direct_sampler 同一镜像; 只读, 不下发任何运动):
    sudo docker run --rm --network host -v ~/zmax/zmax_data/rokae_sdk:/sdk -w /sdk \
        ros:humble-ros-base python3 /sdk/ft_pose_sampler.py --secs 180 --rate 10
输出: /sdk/ft_out/ft_pose_YYYYMMDD.jsonl  每行 {ts, fx,fy,fz, quat(x,y,z,w), joints[6], power, op}
"""
import argparse
import json
import os
import sys
import time
import urllib.request

SDK_DIR = os.environ.get("ZMAX_SDK_DIR", "/sdk")
IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
TRUTH = os.environ.get("ZMAX_TRUTH_URL", "http://127.0.0.1:8797/api/tcp")
sys.path.insert(0, SDK_DIR)
import xcoresdk_python as x  # noqa: E402


def _vals(v):
    if hasattr(v, "get"):
        return [float(t) for t in v.get()]
    if hasattr(v, "content"):
        return [float(t) for t in v.content()]
    return [float(t) for t in v]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=180)
    ap.add_argument("--rate", type=float, default=10)
    a = ap.parse_args()
    out_dir = os.path.join(SDK_DIR, "ft_out")
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, "ft_pose_%s.jsonl" % time.strftime("%Y%m%d"))
    r = x.xMateRobot()
    r.connectToRobot(IP)
    fc = r.forceControl()
    print("[ft+pose] 已连接 %s · 姿态源 %s · 输出 %s" % (IP, TRUTH, fp), flush=True)
    n = 0
    t_end = time.time() + a.secs if a.secs > 0 else 1e18
    while time.time() < t_end:
        t0 = time.time()
        try:
            jtm = x.PyTypeVectorDouble()
            etm = x.PyTypeVectorDouble()
            ctq = x.PyTypeVectorDouble()
            cfo = x.PyTypeVectorDouble()
            ec = {}
            fc.getEndTorque(x.FrameType.world, jtm, etm, ctq, cfo, ec)
            f = _vals(cfo) if len(_vals(cfo)) >= 3 else _vals(etm)[:3]
            d = json.loads(urllib.request.urlopen(TRUTH, timeout=2).read().decode())
            row = {"ts": time.time(), "fx": f[0], "fy": f[1], "fz": f[2],
                   "quat": d.get("quat"), "joints": d.get("joints") or d.get("joint"),
                   "power": str(r.powerState({})), "op": str(r.operationState({}))}
            with open(fp, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
            if n % 50 == 0:
                print("  %d 帧 · fx=%.2f fy=%.2f fz=%.2f · q=%s" % (
                    n, f[0], f[1], f[2], None if not row["quat"] else [round(v, 3) for v in row["quat"]]), flush=True)
        except Exception as e:                                               # noqa: BLE001
            print("  [err]", str(e)[:90], flush=True)
        time.sleep(max(0.0, 1.0 / a.rate - (time.time() - t0)))
    print("[ft+pose] 结束 %d 帧 → %s" % (n, fp), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
