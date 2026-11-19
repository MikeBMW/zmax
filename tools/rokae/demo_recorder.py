#!/usr/bin/env python3
"""demo_recorder.py — 老倪演示一次插拔时的 50Hz 全量记录 (只读, 不下发任何动作)。

为什么要 50Hz: 插入成功那一下的接触/入孔事件只有几十毫秒, 10Hz 会把它平均掉。
今天实测证明"端面接触刚度 ~10N/mm", 入孔瞬间的力跌落是毫秒级的斜坡, 必须高频才抓得住。

落盘每行: {t, tcp[3], rpy[3], f_tool[6], joints[6], op, power}
用法 (容器内):
    python3 /sdk/demo_recorder.py --secs 900 --rate 50
输出: /sdk/logs/demo_YYYYMMDD_HHMMSS.jsonl   结束打印统计
"""
import argparse
import json
import os
import sys
import time

SDK_DIR = os.environ.get("ZMAX_SDK_DIR", "/sdk")
IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
sys.path.insert(0, SDK_DIR)
import xcoresdk_python as x  # noqa: E402


def vals(v):
    if hasattr(v, "get"):
        return [float(t) for t in v.get()]
    if hasattr(v, "content"):
        return [float(t) for t in v.content()]
    return [float(t) for t in v]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=900)
    ap.add_argument("--rate", type=float, default=50)
    a = ap.parse_args()
    d = os.path.join(SDK_DIR, "logs")
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, "demo_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
    r = x.xMateRobot()
    r.connectToRobot(IP)
    fc = r.forceControl()
    b = [x.PyTypeVectorDouble() for _ in range(4)]
    print("[demo] 记录开始 · %.0fHz · %.0fs · %s" % (a.rate, a.secs, fp), flush=True)
    t_end = time.time() + a.secs
    n = 0
    peak = [0.0, 0.0, 0.0]
    with open(fp, "w", encoding="utf-8") as fh:
        while time.time() < t_end:
            t0 = time.time()
            try:
                cp = r.cartPosture(x.CoordinateType.endInRef, {})
                e = {}
                fc.getEndTorque(x.FrameType.tool, b[0], b[1], b[2], b[3], e)
                f = vals(b[3])
                if len(f) < 6:
                    f = (f + [0.0] * 6)[:6]
                j = vals(r.jointPos({}))
                row = {"t": round(time.time(), 4),
                       "tcp": [round(float(v), 6) for v in cp.trans],
                       "rpy": [round(float(v), 6) for v in cp.rpy],
                       "f": [round(v, 3) for v in f[:6]],
                       "j": [round(v, 4) for v in j[:6]],
                       "op": str(r.operationState({})).split(".")[-1]}
                fh.write(json.dumps(row) + "\n")
                n += 1
                for k in range(3):
                    peak[k] = max(peak[k], abs(row["f"][k]))
                if n % 500 == 0:
                    fh.flush()
                    print("  %d 帧 · op=%s · |F|峰值 %.1f/%.1f/%.1f N" % (n, row["op"], *peak), flush=True)
            except Exception as ex:                                          # noqa: BLE001
                print("  [err]", str(ex)[:70], flush=True)
            time.sleep(max(0.0, 1.0 / a.rate - (time.time() - t0)))
    print("[demo] 结束 %d 帧 → %s · 峰值力 %.1f/%.1f/%.1f N" % (n, fp, *peak), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
