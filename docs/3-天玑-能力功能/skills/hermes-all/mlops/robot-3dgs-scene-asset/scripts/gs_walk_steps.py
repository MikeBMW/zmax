#!/usr/bin/env python3
"""走点记账 —— 人工走点采集时的客观“步”清单 (只读, 不下发、不碰臂)

用途: 现场问「我走了几步 / 停够没停够 / 视点为什么不够」时, 用它出清单而不是凭印象。
口径: 每秒读一次 TCP 真值; 位姿在 STABLE_MM 内稳 ≥MIN_STOP_S 秒, 且距上一笔记账点 ≥MIN_STEP_MM
      ⇒ 记一笔“一步”。与建图门的对应关系: 停一次 ≈ +1~2 个独立视点(driver 开训门 30)。
输出: /tmp/gs_walk_steps.jsonl, 一行一步: n / t / xyz_m / xyz_mm / moved_from_prev_mm

跑法: /usr/bin/python3 scripts/gs_walk_steps.py &   (常驻; 走点结束随会话一起收拾)
"""
import json
import os
import time

POSE = os.path.expanduser("~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json")
OUT = "/tmp/gs_walk_steps.jsonl"
STABLE_MM = 3.0        # 稳: 相邻采样位移 < 3mm
MIN_STOP_S = 1.0       # 停: 连续稳 ≥ 1.0s(小于它 = 还在走, 画面/位姿没配稳, 不计)
MIN_STEP_MM = 20.0     # 步: 距上一笔记账点 ≥ 20mm(小于它 = 原地微调, 不算新视点)
TICK = 0.5


def read_pose():
    try:
        d = json.load(open(POSE, encoding="utf-8"))
        return (float(d["x"]), float(d["y"]), float(d["z"]))
    except Exception:
        return None


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5 * 1000.0


def main():
    last_logged = None
    prev = None
    stable_from = None
    n = 0
    while True:
        p = read_pose()
        if p:
            if prev is None or dist(p, prev) >= STABLE_MM:
                stable_from = None                     # 还在动
            else:
                stable_from = stable_from or time.time()
            prev = p
            if stable_from and (time.time() - stable_from) >= MIN_STOP_S:
                if last_logged is None or dist(p, last_logged) >= MIN_STEP_MM:
                    n += 1
                    rec = {"n": n, "t": time.strftime("%H:%M:%S"),
                           "xyz_m": [round(v, 4) for v in p],
                           "xyz_mm": [round(v * 1000, 1) for v in p],
                           "moved_from_prev_mm": (round(dist(p, last_logged), 1) if last_logged else None)}
                    with open(OUT, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    last_logged = p
                    print("[walk] 第 %d 步 %s %s (距上步 %s mm)"
                          % (n, rec["t"], rec["xyz_mm"], rec["moved_from_prev_mm"]), flush=True)
        time.sleep(TICK)


if __name__ == "__main__":
    main()
