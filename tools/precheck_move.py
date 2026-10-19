#!/usr/bin/env python3
"""移动前硬边界预检 —— 三维视图里的 3 个长方体是墙, 不许碰。

老倪 2026-10-19 现场: 「三维视图的 3 个长方体, 不要碰到了, 那是边界」
（此前一次转身命令差点扫到上横梁: 没预检就发指令）

用法:
  python3 tools/precheck_move.py                      # 只查当前姿态
  python3 tools/precheck_move.py --to 700,200,420     # 再查"到目标点的直线路径"
  python3 tools/precheck_move.py --to ... --abc ...   # 目标姿态也带上(仅记录)

判据: 臂的每一段连杆(含 tool1 轴线与夹爪 120mm 包络) + 目标直线路径采样点,
      到每个 box(外扩 margin_mm)的距离必须 > 0; 任何一处 <=0 ⇒ FAIL, 不许发运动指令。
"""
import json
import math
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ss_fk_xms5 import fk                                    # noqa: E402

SDK_DIR = "/sdk"
ROBOT_IP = os.environ.get("ROKAE_IP", "192.168.23.160")
AR_API = "http://127.0.0.1:8797/api/fence"
GRIP_ENVELOPE_MM = 120.0      # 夹爪+模块从 tool1 原点往外的包络长度


def load_boxes():
    d = json.load(urllib.request.urlopen(AR_API, timeout=8))
    margin = float(d.get("margin_mm") or 10.0)
    out = []
    for it in d.get("items") or []:
        if it.get("type") != "box" or not it.get("enabled"):
            continue
        p1 = [v * 1000.0 for v in it["p1"]]
        p2 = [v * 1000.0 for v in it["p2"]]
        lo = [min(p1[i], p2[i]) - margin for i in range(3)]
        hi = [max(p1[i], p2[i]) + margin for i in range(3)]
        out.append({"name": it.get("name") or it.get("id"), "lo": lo, "hi": hi})
    return out, margin


def dist_point_box(p, lo, hi):
    """点到 box 的距离; 在内部返回负的"最浅穿透深度" """
    if all(lo[i] <= p[i] <= hi[i] for i in range(3)):
        return -min(min(p[i] - lo[i], hi[i] - p[i]) for i in range(3))
    d = []
    for i in range(3):
        if p[i] < lo[i]:
            d.append(lo[i] - p[i])
        elif p[i] > hi[i]:
            d.append(p[i] - hi[i])
        else:
            d.append(0.0)
    return math.sqrt(sum(x * x for x in d))


def seg_samples(a, b, step=10.0):
    n = max(1, int(math.ceil(math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3))) / step)))
    return [[a[i] + (b[i] - a[i]) * k / n for i in range(3)] for k in range(n + 1)]


def read_joints():
    """读实时关节角 + TCP: 用遥测桥落的文件(零运动, 不连控制器)。

    注意: latest.json 的 ts 受 NTP 回拨影响(比本机慢 8h), 新鲜度一律按文件 mtime 判。
    """
    p = os.path.join(HERE, "..", "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
    d = json.load(open(p, encoding="utf-8"))
    q = [float(v) for v in (d.get("joint") or [])][:6]
    if len(q) < 6 or all(abs(v) < 1e-9 for v in q):
        raise SystemExit("关节角全 0 ⇒ 遥测陈旧, 不做预检(先确认真值源)")
    tcp = [float(d["x"]) * 1000.0, float(d["y"]) * 1000.0, float(d["z"]) * 1000.0]
    age = time.time() - os.path.getmtime(p)
    return q, tcp, age


def arm_polylines(q):
    """返回 [(名字, [点...])] —— 关节链每段 + tool1 轴线/夹爪包络"""
    names = ["base", "link1", "link2", "link3", "link4", "link5", "link6", "tool1"]
    pts = [[0.0, 0.0, 0.0]]                                   # base 原点
    for n in names[1:]:
        try:
            _R, t = fk(q, upto=n)                             # fk 返回 (R, t)
            pts.append([v * 1000.0 for v in t])
        except Exception:                                     # noqa: BLE001
            pass
    pts = [p for p in pts if p]
    lines = []
    for i in range(len(pts) - 1):
        lines.append(("连杆 %d" % i, [pts[i], pts[i + 1]]))
    # tool1 -> 夹爪包络末端(沿最后一段方向外延)
    if len(pts) >= 2:
        a, b = pts[-2], pts[-1]
        v = [b[i] - a[i] for i in range(3)]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        tip = [b[i] + v[i] / n * GRIP_ENVELOPE_MM for i in range(3)]
        lines.append(("夹爪包络", [b, tip]))
    return lines


def main():
    to = None
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--to" and i + 1 < len(argv):
            to = [float(x) for x in argv[i + 1].split(",")]
    boxes, margin = load_boxes()
    q, tcp, age = read_joints()
    print("关节角(rad) =", [round(v, 4) for v in q])
    print("TCP 真值    = [%.1f, %.1f, %.1f] mm  (帧龄 %.1fs)" % (tcp[0], tcp[1], tcp[2], age))
    if age > 3.0:
        print("⚠ 遥测帧龄 %.1fs > 3s ⇒ 结果仅供参考, 别当实时" % age)
    print("硬边界 %d 个 (外扩 margin %.0fmm)" % (len(boxes), margin))

    lines = arm_polylines(q)
    if to:
        lines.append(("到目标的直线", seg_samples(tcp, to, 10.0)))

    worst = (1e9, "", None)
    bad = []
    for name, pts in lines:
        if len(pts) == 2:
            samples = seg_samples(pts[0], pts[1], 10.0)
        else:
            samples = pts
        for b in boxes:
            dmin = min(dist_point_box(p, b["lo"], b["hi"]) for p in samples)
            if dmin < worst[0]:
                worst = (dmin, name, b["name"])
            if dmin <= 0:
                bad.append((name, b["name"], dmin))
            print("  %-10s vs %-20s 最小距离 %8.1f mm %s" % (
                name, b["name"], dmin, "🔴 侵入" if dmin <= 0 else ""))

    print("\n最小余量: %.1f mm (%s vs %s)" % worst)
    if bad:
        print("❌ FAIL —— 有 %d 处侵入, 不许发运动指令" % len(bad))
        for n, bn, d in bad:
            print("   · %s 侵入 %s %.1fmm" % (n, bn, -d))
        return 2
    print("✅ PASS —— 所有连杆/路径都在 %d 个硬边界之外" % len(boxes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
