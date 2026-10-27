#!/usr/bin/env python3
"""轨迹5「实时」直线 → 3 段斜线 MoveL 执行 (当前 TCP → 准备点, 260.8mm)

为什么不走 traj_from_named.py: 它对骨架点做**轴对齐拆段**(先Z再X再Y) ⇒ 斜线被执行成阶梯。
老倪 2026-10-26 明确要「走直线」⇒ 这里走 l2_daemon FIFO + abs_mm(绝对目标),
每条 = 一条真斜线 MoveL 到等分点, 单段 ≤90mm(实测 >100mm 会被控制器零位移丢弃)。

用法:
  python3 exec_straight_line.py --dry     # 只算+打印目标, 不写 FIFO (零运动)
  python3 exec_straight_line.py           # 真发 (要求 ctl_auth armed)
"""
import argparse
import json
import math
import os
import sys
import time

REPO = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(REPO, "tools"))

FIFO = os.path.join(REPO, "zmax_data/l2_cmd.fifo")
LATEST = os.path.join(REPO, "zmax_data/rokae_sdk/tcp_out/latest.json")
LOG = os.path.join(REPO, "zmax_data/l2_daemon_stdout.log")
TARGET_MM = (522.269, -176.989, 273.561)      # 准备点 (点位台账)
MAX_SEG_MM = 90.0                              # 单段上限 (实测 >100mm 零位移)
ARRIVE_TOL_MM = 8.0
SPEED_UNITS = 1070                             # 名义 100mm/s ≈ 实得 10mm/s


def read_tcp():
    d = json.load(open(LATEST, encoding="utf-8"))
    age = time.time() - os.path.getmtime(LATEST)
    return [d["x"] * 1000.0, d["y"] * 1000.0, d["z"] * 1000.0], age


def plan_segments(cur, tgt, max_seg=MAX_SEG_MM):
    """按弧长等分: 每段 ≤max_seg, 中间点严格落在直线 上 (不改变形状)。"""
    L = math.dist(cur, tgt)
    n = max(1, int(math.ceil(L / max_seg)))
    pts = [[cur[k] + (tgt[k] - cur[k]) * i / n for k in range(3)] for i in range(n + 1)]
    return pts, n, L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--speed", type=float, default=SPEED_UNITS)
    a = ap.parse_args()

    cur, age = read_tcp()
    if age > 2.0:
        raise SystemExit("⛔ 位姿真值帧龄 %.1fs > 2s ⇒ 起点不可信, 拒发" % age)
    pts, n, L = plan_segments(cur, TARGET_MM)
    print("起点(真值) = [%.2f, %.2f, %.2f] mm  帧龄 %.2fs" % (cur[0], cur[1], cur[2], age))
    print("终点(准备点) = [%.2f, %.2f, %.2f] mm" % TARGET_MM)
    print("直线距离 = %.1f mm ⇒ 拆 %d 段 (单段 %.1fmm ≤ %.0fmm)" % (L, n, L / n, MAX_SEG_MM))
    for i in range(n):
        print("  段%d: [%.1f,%.1f,%.1f] → [%.1f,%.1f,%.1f]" % (
            i + 1, pts[i][0], pts[i][1], pts[i][2], pts[i + 1][0], pts[i + 1][1], pts[i + 1][2]))

    if a.dry:
        print("\n[DRY] 不写 FIFO。真发去掉 --dry")
        return

    import ctl_auth
    au = ctl_auth.info()
    print("\n授权: armed=%s left=%.0fs epoch=%s" % (au.get("armed"), au.get("left_s") or 0, au.get("epoch")))
    if not au.get("armed"):
        raise SystemExit("⛔ 未授权 ⇒ 不写 FIFO")
    epoch = au.get("epoch")

    off = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    with open(FIFO, "w", encoding="utf-8") as f:
        for i in range(n):
            seg = {"skill": "L2.forward", "d_mm": round(L / n, 1),
                   "abs_mm": [round(v, 2) for v in pts[i + 1]],
                   "speed": a.speed, "auth_epoch": epoch, "src": "traj_exec",
                   "note": "轨迹5直线 %d/%d → 准备点" % (i + 1, n)}
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")
            f.flush()
            time.sleep(0.12)
            print("  ✍ 写入 FIFO: 段%d → %.2f,%.2f,%.2f" % (i + 1, *pts[i + 1]))
    print("✅ %d 段已一次性写入 (不逐段等位, 由执行器自己排队)" % n)

    # 只观察真值, 不干预
    t0 = time.time()
    last = None
    while time.time() - t0 < 240:
        time.sleep(3)
        try:
            p, ag = read_tcp()
        except Exception:
            continue
        d = math.dist(p, TARGET_MM)
        if last is None or math.dist(p, last) > 0.3:
            print("  [%5.1fs] TCP=[%.1f,%.1f,%.1f] 距目标 %.1fmm 帧龄 %.2fs"
                  % (time.time() - t0, p[0], p[1], p[2], d, ag))
            last = p
        if d <= ARRIVE_TOL_MM and ag < 2.0:
            print("🎯 到位: 距准备点 %.1fmm ≤ %.0fmm (用时 %.1fs)" % (d, ARRIVE_TOL_MM, time.time() - t0))
            break
    else:
        p, _ = read_tcp()
        print("⚠️ 240s 内未到位, 当前 [%.1f,%.1f,%.1f] 距目标 %.1fmm" % (p[0], p[1], p[2], math.dist(p, TARGET_MM)))

    print("\n=== 执行器日志新行 ===")
    with open(LOG, encoding="utf-8", errors="replace") as f:
        f.seek(off)
        for line in f:
            if any(k in line for k in ("受理", "拒绝", "已下发", "腿", "到位", "残差", "被拦", "⛔", "🛑")):
                print("  " + line.rstrip()[:200])


if __name__ == "__main__":
    main()
