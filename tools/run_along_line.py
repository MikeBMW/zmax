#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_along_line.py — 让 tool1(模块头) 沿三维视图里画的一条直线, 从一端走到另一端

老倪 2026-10-18: 「让机器人的 tool1 模块头, 沿着 小红 的一端 移动到 另一端」

做法
  1. 只读核对: /ctl/status ⇒ 必须 armed + automatic + idle + 无报警/急停, 否则一行不发
  2. 读 SDK 真值位姿 (endInRef) 当起点
  3. 生成一条**多点路径** (实测: 控制器一次 moveStart 只执行队列前 ~18 个 MoveL 点, 长路径会中途停住
     ⇒ 默认按 90mm 分块接力, 一块走完再发下一块): 起点 → 线的 A 端(过渡) → 沿 A→B 均匀取 n 点 ⇒ 一次 moveStart 连续走完
  4. 围栏闸: 路过的那条线本身就是围栏(离它 < 余量 就算撞), 所以本次只豁免它的名字,
     其它围栏照样拦; 无论成败退出前都把豁免恢复
  5. 速度默认 20mm/s, 硬上限 100mm/s
用法
  ./gui-venv311/bin/python tools/run_along_line.py --name 小红 --speed 20 --npts 40          # 真动
  ./gui-venv311/bin/python tools/run_along_line.py --name 小红 --dry-run                     # 只算不发
"""
import argparse
import json
import os
import sys
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(REPO, "tools"))
FIFO = os.path.join(REPO, "zmax_data", "rokae_sdk", "cmd_arm.fifo")
CTL = "http://127.0.0.1:8793"


def _get(path, timeout=4):
    with urllib.request.urlopen(CTL + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def status():
    s = _get("/ctl/status")
    rb = s.get("robot") or {}
    return s, rb


def preflight():
    s, rb = status()
    bad = []
    if not s.get("motion_armed"):
        bad.append("未授权 (motion_armed=false) —— 动作授权只从 8793 给")
    if rb.get("mode") != "automatic":
        bad.append("不是自动模式 (%s)" % rb.get("mode"))
    if rb.get("operation") not in ("idle", "Idle", None):
        bad.append("机器人不空闲 (%s)" % rb.get("operation"))
    if rb.get("estop"):
        bad.append("急停中")
    if rb.get("has_error"):
        bad.append("有报警: %s" % (rb.get("error_reason") or rb.get("error_code")))
    return (not bad), bad, s, rb


def send(req, wait=90.0):
    """写 FIFO → 等 SDK agent 回执 (它按 id 回)"""
    rid = req.setdefault("id", "line_%d" % int(time.time() * 1000))
    fd = os.open(FIFO, os.O_WRONLY)
    try:
        os.write(fd, (json.dumps(req) + "\n").encode())
    finally:
        os.close(fd)
    # 回执在 SDK agent 自己的 jsonl 里 (zmax_data/rokae_sdk/logs/agent_YYYYMMDD.jsonl), 不在 evid 目录
    lg = os.path.join(REPO, "zmax_data", "rokae_sdk", "logs",
                      "agent_%s.jsonl" % time.strftime("%Y%m%d"))
    t0 = time.time()
    while time.time() - t0 < wait:
        try:
            with open(lg, encoding="utf-8") as f:
                for line in f:
                    if rid not in line:
                        continue
                    d = json.loads(line)
                    if d.get("id") == rid:
                        return d
        except Exception:                                                   # noqa: BLE001
            pass
        time.sleep(0.2)
    return {"id": rid, "verdict": "TIMEOUT 等回执 (%.0fs)" % wait}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="小红", help="要沿着的直线元素的名字")
    ap.add_argument("--id", default="", help="按 id 指定 (页面 Follow 按钮走这个)")
    ap.add_argument("--speed", type=float, default=20.0, help="mm/s (1~100)")
    ap.add_argument("--npts", type=int, default=40, help="直线段上取几个点 (点越多越平顺)")
    ap.add_argument("--zone", type=float, default=5.0, help="过渡区 mm (越小越贴线, 停顿越多)")
    ap.add_argument("--reverse", action="store_true", help="从 B 端走到 A 端")
    ap.add_argument("--chunk", type=float, default=0.0,
                    help="分块长度 mm (0=整条一次下发)。实测控制器一次只执行队列前 ~18 点, 长路径会中途停住 ⇒ 默认按 100mm 分块接力")
    ap.add_argument("--from-here", action="store_true",
                    help="末端已经在这条线上时, 从最近点续走 (不退回 A 端)")
    ap.add_argument("--loops", type=int, default=0,
                    help="来回走 N 次 (2N 段)。一次性下发 2N 个端点 (<=18 点不触控制器队列上限), zone 混合 ⇒ 端点不停")
    ap.add_argument("--dry-run", action="store_true", help="只算不发")
    a = ap.parse_args()

    import fence_store as FS
    items = FS.listing()["items"]
    it = None
    if a.id:
        it = next((x for x in items if x["id"] == a.id), None)
    if it is None:
        it = next((x for x in items if x["name"] == a.name), None)
    if not it or it["type"] != "line":
        print("⛔ 没找到直线元素 (id=%s name=%s)" % (a.id, a.name))
        return 2
    A, B = list(it["p1"]), list(it["p2"])
    if a.reverse:
        A, B = B, A
    ok, bad, s, rb = preflight()
    print("机器人: mode=%s op=%s armed=%s estop=%s 报警=%s"
          % (rb.get("mode"), rb.get("operation"), s.get("motion_armed"),
             rb.get("estop"), rb.get("has_error")))
    if not ok:
        print("⛔ 前置条件不满足 ⇒ 一行都不发:")
        for b in bad:
            print("   ·", b)
        _write_status("error", it, a, err="; ".join(bad))
        return 3

    pose = _get("/pose")
    cur = [float(x) for x in pose["xyz"]]
    print("起点 TCP(真值) = [%.1f, %.1f, %.1f] mm" % tuple(x * 1000 for x in cur))
    print("目标直线「%s」A=[%.0f, %.0f, %.0f] → B=[%.0f, %.0f, %.0f] mm"
          % (a.name, A[0] * 1000, A[1] * 1000, A[2] * 1000, B[0] * 1000, B[1] * 1000, B[2] * 1000))
    line_mm = 1000.0 * sum((B[i] - A[i]) ** 2 for i in range(3)) ** 0.5
    appr_mm = 1000.0 * sum((A[i] - cur[i]) ** 2 for i in range(3)) ** 0.5
    print("过渡 %.1fmm + 沿线 %.1fmm = %.1fmm · 速度 %.0fmm/s ⇒ 约 %.0fs"
          % (appr_mm, line_mm, appr_mm + line_mm, a.speed, (appr_mm + line_mm) / max(1.0, a.speed)))

    # 若已经贴在这条线上, 就从最近点续走 (不必退回 A 端)
    if a.from_here:
        v = [B[i] - A[i] for i in range(3)]
        L2 = sum(x * x for x in v) or 1e-9
        tt = max(0.0, min(1.0, sum((cur[i] - A[i]) * v[i] for i in range(3)) / L2))
        foot = [A[i] + v[i] * tt for i in range(3)]
        off = 1000.0 * sum((cur[i] - foot[i]) ** 2 for i in range(3)) ** 0.5
        if off < 20.0:
            A = foot
            print("↪ 末端已在线附近 (偏离 %.1fmm), 从 y=%.0fmm 处续走" % (off, A[1] * 1000))

    # 绝对目标点: 过渡段 + 直线段
    abs_pts = [cur]
    if appr_mm > 2.0:                           # 需要过渡才插点; 已经在 A 端/线上就别插零位移点
        for k in range(1, 9):
            t = k / 8.0
            abs_pts.append([cur[i] + (A[i] - cur[i]) * t for i in range(3)])
    for k in range(1, a.npts + 1):              # 沿线: A → B
        t = k / float(a.npts)
        abs_pts.append([A[i] + (B[i] - A[i]) * t for i in range(3)])

    if a.loops and a.loops > 0:
        # 来回 N 次: 起点先归到 A(或最近的端点), 之后每段一个端点 ⇒ 2N 个点一次性下发
        v = [B[i] - A[i] for i in range(3)]
        L2 = sum(x * x for x in v) or 1e-9
        tt = max(0.0, min(1.0, sum((cur[i] - A[i]) * v[i] for i in range(3)) / L2))
        near = [A[i] + v[i] * tt for i in range(3)]
        off = 1000.0 * sum((cur[i] - near[i]) ** 2 for i in range(3)) ** 0.5
        if off < 25.0 and tt > 0.5:            # 停在 B 端 ⇒ 先去 A
            start_pt, first = B, A
        elif off < 25.0:                        # 停在 A 端 ⇒ 先去 B
            start_pt, first = A, B
        else:                                   # 不在线上 ⇒ 先归位到近端
            start_pt = A if tt < 0.5 else B
            first = B if tt < 0.5 else A
        pts2 = [start_pt]
        tgt = first
        for k in range(2 * a.loops):
            pts2.append(list(tgt))
            tgt = A if tgt is B else B
        abs_pts = pts2
        total_mm = 1000.0 * sum(
            sum((abs_pts[k][i] - abs_pts[k - 1][i]) ** 2 for i in range(3)) ** 0.5
            for k in range(1, len(abs_pts)))
        print("🔁 来回 %d 次 (%d 段) · 共 %.1fmm · 速度 %.0fmm/s ⇒ 约 %.0fs"
              % (a.loops, 2 * a.loops, total_mm, a.speed, total_mm / max(1.0, a.speed)))

    # 围栏闸: 只豁免这条线本身
    hit = FS.check_points(abs_pts[1:])
    if hit.get("hit"):
        names = {h["name"] for h in (hit["first"]["by"] if hit.get("first") else [])}
        others = names - {a.name}
        if others:
            print("⛔ 路径会撞到别的围栏 %s ⇒ 不发" % sorted(others))
            return 4
        print("⚠ 路径贴着「%s」本身走 ⇒ 本次运行临时停用它 (退出时自动恢复)" % a.name)
    if a.dry_run:
        print("DRY-RUN: 共 %d 个点, 前 3 个: %s" % (len(abs_pts), [[round(v * 1000) for v in p] for p in abs_pts[:3]]))
        return 0

    # 转成"相对当前位姿"的增量 (do_path 从发送瞬间的真值位姿累加)
    deltas = []
    for k in range(1, len(abs_pts)):
        d = [abs_pts[k][i] - abs_pts[k - 1][i] for i in range(3)]
        deltas.append([round(d[0] * 1000.0, 2), round(d[1] * 1000.0, 2), round(d[2] * 1000.0, 2)])

    # 分块: 每块累计位移不超过 --chunk (0 = 整条)
    chunks, cur_chunk, acc = [], [], 0.0
    lim = a.chunk if a.chunk and a.chunk > 1 else 1e9
    for d in deltas:
        seg = (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5
        if cur_chunk and acc + seg > lim:
            chunks.append(cur_chunk); cur_chunk, acc = [], 0.0
        cur_chunk.append(d); acc += seg
    if cur_chunk:
        chunks.append(cur_chunk)

    was = it.get("enabled", True)
    try:
        if hit.get("hit"):
            FS.update(it["id"], enabled=False)
        print("▶ 路径 %d 点 · 分 %d 块 · %.0fmm/s · zone %.0fmm"
              % (len(deltas), len(chunks), a.speed, a.zone))
        for ci, ck in enumerate(chunks):
            p0 = [float(x) for x in _get("/pose")["xyz"]]
            out = send({"cmd": "path", "points": ck, "speed": a.speed, "zone": a.zone,
                        "id": "line_%d_%d" % (int(time.time()), ci)},
                       wait=max(30.0, sum((d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5 for d in ck)
                                / max(1.0, a.speed) + 20.0))
            time.sleep(0.6)
            p1 = [float(x) for x in _get("/pose")["xyz"]]
            got = 1000 * sum((p1[i] - p0[i]) ** 2 for i in range(3)) ** 0.5
            print("   块 %d/%d: %d 点 · 走 %.1fmm · 收尾 [%.0f, %.0f, %.0f] · %s"
                  % (ci + 1, len(chunks), len(ck), got, p1[0] * 1000, p1[1] * 1000, p1[2] * 1000,
                     (out.get("verdict") or "")[:60]))
            ok_done = "PATH DONE" in (out.get("verdict") or "")
            # 来回跑的净位移本来就接近 0 (回到起点), 不能拿净位移判"没动"
            if got < 1.0 and not ok_done:
                print("   ⚠ 这一块没动 ⇒ 停下, 不叠队")
                break
    finally:
        if hit.get("hit") and was:
            FS.update(it["id"], enabled=True)
            print("「%s」已恢复启用" % a.name)

    end = [float(x) for x in _get("/pose")["xyz"]]
    d = [1000 * (end[i] - cur[i]) for i in range(3)]
    print("终点 TCP = [%.1f, %.1f, %.1f] mm · 实际位移 [%.1f, %.1f, %.1f] mm"
          % (end[0] * 1000, end[1] * 1000, end[2] * 1000, d[0], d[1], d[2]))
    errA = 1000 * sum((end[i] - A[i]) ** 2 for i in range(3)) ** 0.5
    errB = 1000 * sum((end[i] - B[i]) ** 2 for i in range(3)) ** 0.5
    print("离 A 端 %.1fmm · 离 B 端 %.1fmm" % (errA, errB))
    _write_status("done", it, a, end=end, errs=(errA, errB))
    return 0


def _write_status(state, it, a, end=None, errs=None, err=""):
    """给页面轮询用: zmax_data/ar_rs/follow_status.json"""
    try:
        p = os.path.join(REPO, "zmax_data", "ar_rs", "follow_status.json")
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:                                                   # noqa: BLE001
            d = {}
        d.update({"state": state, "id": it.get("id"), "name": it.get("name"),
                  "loops": a.loops, "speed": a.speed,
                  "at": time.strftime("%F %T")})
        if end:
            d["end_xyz_mm"] = [round(x * 1000, 1) for x in end]
        if errs:
            d["err_a_mm"], d["err_b_mm"] = round(errs[0], 1), round(errs[1], 1)
        if err:
            d["err"] = err
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:                                                       # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(main())
