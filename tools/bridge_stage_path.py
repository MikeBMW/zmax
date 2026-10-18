# -*- coding: utf-8 -*-
"""bridge_stage_path.py — 每个仿真动作发**一条多点路径**, 控制器一口气走完 (不再一顿一顿)

老倪 2026-10-18: 「为什么仿真里的机器人很平顺, 而你的操作是一顿一顿的」

原因 (已实测):
  · 旧做法: 每个阶段只发 **一条 move-rel** (= 一段直线), 走完就停, 等下一个阶段 ⇒ 走一段/停一段
  · 刚验证 (sdk_agent cmd=path): 一次性 append 10 点 × 5mm + **一次** moveStart
    ⇒ 实测一口气走 50.0mm / 2.8s, 中途没有停顿 (PATH DONE 残差 0.0mm)
  · 所以"平顺"的关键是: **把点一次排完再 moveStart**, 而不是一条一条发

这一版:
  · 阶段一变 → 取该阶段位移 (仿真真值每阶段位移 × scale, 缺真值则 u_ff×0.8s)
  · 把这段位移拆成 --npts 个点 (默认 10), 一次下发 → 控制器连续走完这一段
  · 速度 = 位移 / --stage-s (默认 0.8s, 跟仿真一个阶段的时间对齐), 上限 --speed (默认 100mm/s)
  · 包络 anchor ± --band (默认 250mm) 交给腿的实时扫掠闸; 超包络 60% 先回中
  · 授权每拍复查; 桥接开关=总闸; 5 分钟无新阶段自停

用法:
  ./gui-venv311/bin/python tools/bridge_stage_path.py --scale 1.0 --npts 10 --speed 100 --band 250
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
TR = os.path.join(REPO, "zmax_data", "ss_live", "trace_live.json")
VFF = os.path.join(REPO, "zmax_data", "ss_live", "plan_from_vff.json")
FIFO = os.path.join(REPO, "zmax_data", "rokae_sdk", "cmd_arm.fifo")
LOG = os.path.join(REPO, "zmax_data", "ss_live", "bridge_stage_path.jsonl")
PIDF = os.path.join(REPO, "zmax_data", "ss_live", "bridge_path.pid")
BASE = "http://127.0.0.1:8793"


def _j(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                     # noqa: BLE001
        return {}


def _get(p, timeout=3.0):
    with urllib.request.urlopen(BASE + p, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _fifo(req):
    fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
    os.write(fd, (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
    os.close(fd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0, help="仿真位移缩放 (默认 1.0)")
    ap.add_argument("--npts", type=int, default=10, help="每段拆成几个点 (默认 10)")
    ap.add_argument("--stage-s", type=float, default=0.8, help="每段期望耗时 s (默认 0.8)")
    ap.add_argument("--speed", type=float, default=100.0, help="速度上限 mm/s")
    ap.add_argument("--max-seg", type=float, default=60.0, help="单段位移上限 mm (默认 60)")
    ap.add_argument("--band", type=float, default=250.0, help="包络 ±mm")
    ap.add_argument("--max-actions", type=int, default=0, help="0=常驻")
    a = ap.parse_args()

    if not _get("/ctl/status").get("motion_armed"):
        print("⛔ 未授权真动 ⇒ 一行都不发。", flush=True)
        return 2
    p0 = _get("/pose")
    anchor = [float(x) for x in p0["xyz"]]
    gbox = {ax: [anchor[i] - a.band / 1000.0, anchor[i] + a.band / 1000.0] for i, ax in enumerate("xyz")}
    try:
        with open(PIDF, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:                                                     # noqa: BLE001
        pass
    print("🧵 每段一条多点路径: npts=%d · 速度≤%.0fmm/s · 每段≤%.0fmm · 包络±%.0fmm · 锚点(%.4f,%.4f,%.4f)"
          % (a.npts, a.speed, a.max_seg, a.band, *anchor), flush=True)

    prev_truth = None
    _t0 = _j(VFF).get("truth_xyz")
    if isinstance(_t0, (list, tuple)) and len(_t0) >= 3:
        prev_truth = [float(x) * 1000.0 for x in _t0]
    last = str(_j(TR).get("阶段") or "")
    n = 0
    idle = time.time()
    while (a.max_actions == 0) or (n < a.max_actions):
        time.sleep(0.05)
        v = _j(VFF)
        if not v.get("bridge"):
            print("⏹ 桥接开关已关 ⇒ 停 (共 %d 段)" % n, flush=True)
            break
        s = str(_j(TR).get("阶段") or "")
        if not s or s == last:
            if time.time() - idle > 300:
                print("⏹ 5 分钟没有新阶段 ⇒ 停", flush=True)
                break
            continue
        last, idle = s, time.time()
        # 该段位移: 仿真真值位移 × scale (优先), 否则 u_ff × stage_s
        tr = v.get("truth_xyz")
        d = None
        if isinstance(tr, (list, tuple)) and len(tr) >= 3 and prev_truth:
            tv = [float(x) * 1000.0 for x in tr]
            d = [(tv[i] - prev_truth[i]) * a.scale for i in range(3)]
        if d is None:
            u = [float(x) for x in (v.get("u_ff_mms") or [])][:3]
            d = [u[i] * a.stage_s * a.scale for i in range(3)] if len(u) == 3 else None
        if isinstance(tr, (list, tuple)) and len(tr) >= 3:
            prev_truth = [float(x) * 1000.0 for x in tr]
        if not d or max(abs(x) for x in d) < 2.0:
            print("… %-8s 位移太小 (%.1fmm) ⇒ 不动" % (s, max(abs(x) for x in d or [0])), flush=True)
            continue
        if max(abs(x) for x in d) > a.max_seg:
            d = [x * a.max_seg / max(abs(y) for y in d) for x in d]
        cur = [float(x) for x in _get("/pose")["xyz"]]
        off = [(cur[i] - anchor[i]) * 1000.0 for i in range(3)]
        if max(abs(x) for x in off) > a.band * 0.6:                  # 回中
            back = [-x * 0.6 for x in off]
            _fifo({"id": "rc_%d" % int(time.time() * 1000), "cmd": "path",
                   "points": [[back[0] / 10.0, back[1] / 10.0, back[2] / 10.0]] * 10,
                   "speed": min(100.0, a.speed), "zone": 5, "guard_box": gbox})
            print("🔄 回中 %s mm (离锚 %s)" % ([round(x, 1) for x in back], [round(x, 1) for x in off]), flush=True)
        seg = max(abs(x) for x in d)
        spd = max(5.0, min(a.speed, seg / max(0.2, a.stage_s)))
        pts = [[d[0] / a.npts, d[1] / a.npts, d[2] / a.npts] for _ in range(a.npts)]
        if not _get("/ctl/status").get("motion_armed"):
            print("🔒 授权已撤 ⇒ 停", flush=True)
            break
        _fifo({"id": "seg_%d_%d" % (int(time.time() * 1000), n), "cmd": "path",
               "points": pts, "speed": round(spd, 1), "zone": 5, "guard_box": gbox})
        n += 1
        print("🧵 段 %2d · %-8s 位移 %s mm → %d 点 · 速度 %.0fmm/s · 预计 %.1fs (一口气走完)"
              % (n, s, [round(x, 1) for x in d], a.npts, spd, seg / spd), flush=True)
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "stage": s, "disp_mm": d,
                                    "speed_mm_s": spd, "npts": a.npts}, ensure_ascii=False) + "\n")
        except Exception:                                                 # noqa: BLE001
            pass
        time.sleep(min(1.0, seg / spd * 0.8))          # 让它在跑, 但继续盯阶段
    print("✅ 结束 (共 %d 段)" % n, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
