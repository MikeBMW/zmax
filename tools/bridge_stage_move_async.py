# -*- coding: utf-8 -*-
"""bridge_stage_move_async.py — 异步版: 仿真一进入新阶段就立刻下发, 不等回执

老倪 2026-10-18: 「改」—— 把 1.66s/动作压到跟仿真同拍 (~1s/动作)。

为什么异步是安全的:
  · 下发的是 **move-rel (dx,dy,dz)**, 执行腿在**真正执行那一刻**才用实测位姿算目标
    ⇒ 排队的命令不会因为位姿变了而算错 (这是相对量, 不是绝对目标点)
  · 每条都带 guard_box = 锚点 ± --band, 腿每 0.15s 拿真值比一次, 出界立刻 stop()
  · 授权每拍复查 (8793 motion_armed), 撤了就不再下发
  · 偏移超过包络 60% 时插一条"回中"命令 (同样走 guard_box)

节奏: 阶段切换 → 150ms 窗口取 u_ff 均值定方向 → 立即下发 → 不等回执继续盯下一拍
      动作间的实测位移用"上一拍下发时的位姿 vs 现在位姿"算出来, 不打乱节奏。

用法:
  ./gui-venv311/bin/python tools/bridge_stage_move_async.py --step 15 --speed 100 --band 40
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
LOG = os.path.join(REPO, "zmax_data", "ss_live", "bridge_stage_move_async.jsonl")
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


def _stage():
    return str(_j(TR).get("阶段") or "")


def _uff():
    u = [float(x) for x in (_j(VFF).get("u_ff_mms") or [])][:3]
    return u if len(u) == 3 else [0.0, 0.0, 0.0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=15.0, help="无真值时的保底位移 mm")
    ap.add_argument("--scale", type=float, default=0.5, help="仿真真值位移的缩放 (默认 0.5)")
    ap.add_argument("--max-step", type=float, default=45.0, help="单拍位移上限 mm (默认 45, 腿硬上限 50)")
    ap.add_argument("--speed", type=float, default=100.0, help="速度 mm/s")
    ap.add_argument("--band", type=float, default=120.0, help="锚点周围硬包络 ±mm")
    ap.add_argument("--settle", type=float, default=0.15, help="阶段窗口采样 s")
    ap.add_argument("--min-gap", type=float, default=0.30, help="两次下发最小间隔 s")
    ap.add_argument("--max-actions", type=int, default=40, help="0=常驻")
    a = ap.parse_args()

    if not _get("/ctl/status").get("motion_armed"):
        print("⛔ 未授权真动 ⇒ 一行都不发。", flush=True)
        return 2
    p0 = _get("/pose")
    anchor = [float(x) for x in p0["xyz"]]
    gbox = {ax: [anchor[i] - a.band / 1000.0, anchor[i] + a.band / 1000.0] for i, ax in enumerate("xyz")}
    print("⚡ 异步跟随: 每动作 %.0fmm@%.0fmm/s · 包络 ±%.0fmm · 不等回执 · 锚点 (%.4f, %.4f, %.4f)"
          % (a.step, a.speed, a.band, *anchor), flush=True)

    # 🛑 常驻跑: 桥接开关(plan_from_vff.bridge)一关就停 —— 这是现场的"总闸"
    PIDF = os.path.join(REPO, "zmax_data", "ss_live", "bridge_async.pid")
    try:
        with open(PIDF, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:                                                     # noqa: BLE001
        pass
    st_truth = {"prev": None}
    _tr0 = _j(VFF).get("truth_xyz")
    if isinstance(_tr0, (list, tuple)) and len(_tr0) >= 3:
        st_truth["prev"] = [float(x) * 1000.0 for x in _tr0]
    last, n, t_next = _stage(), 0, 0.0
    pend = None                      # 上一拍: (stage, cmd, pose_at_dispatch, ts)
    idle_since = time.time()
    while (a.max_actions == 0) or (n < a.max_actions):
        time.sleep(0.05)
        if not _j(VFF).get("bridge"):
            print("⏹ 桥接开关已关 ⇒ 停 (共下发 %d 拍)" % n, flush=True)
            break
        s = _stage()
        if not s or s == last or time.time() < t_next:
            if time.time() - idle_since > 300:
                print("⏹ 5 分钟没有新阶段 ⇒ 停", flush=True)
                break
            continue
        idle_since = time.time()
        last = s
        t_end = time.time() + a.settle
        vs = []
        while time.time() < t_end:
            vs.append(_uff())
            time.sleep(0.02)
        m = [sum(v[i] for v in vs) / max(1, len(vs)) for i in range(3)]
        mag = sum(x * x for x in m) ** 0.5
        if mag < 2.0:
            print("… %-8s 速度 %.1fmm/s 太小 ⇒ 不动" % (s, mag), flush=True)
            continue
        u = [x / mag for x in m]
        cur = [float(x) for x in _get("/pose")["xyz"]]
        # 先结上一拍的实测位移
        if pend:
            dp = [round((cur[i] - pend[2][i]) * 1000.0, 1) for i in range(3)]
            print("   ↳ 上一拍 %-6s 命令 %s → 实测 %s mm (间隔 %.2fs)"
                  % (pend[0], [round(x, 1) for x in pend[1]], dp, time.time() - pend[3]), flush=True)
            pend = None
        # 回中
        off = [(cur[i] - anchor[i]) * 1000.0 for i in range(3)]
        if max(abs(x) for x in off) > a.band * 0.6:
            back = [-x * 0.6 for x in off]
            _fifo({"id": "rc_%d" % int(time.time() * 1000), "cmd": "move-rel", "tag": "bridge",
                   "dx": round(back[0], 2), "dy": round(back[1], 2), "dz": round(back[2], 2),
                   "speed": min(100.0, a.speed), "cap_mm": min(50.0, a.max_step), "guard_box": gbox})
            print("🔄 回中 %s mm (离锚 %s)" % ([round(x, 1) for x in back],
                                              [round(x, 1) for x in off]), flush=True)
        # 🎯 位移来源改成**仿真真值**的每阶段实际位移 × scale
        #    实测(20s): 积分位姿只有 X19/Y4/Z33mm, 而真值是 X211/Y41/Z41mm
        #    —— 这就是"没看到横向移动"的根: 15mm 沿法向分配后 Y 只剩 2~6mm。
        tr = _j(VFF).get("truth_xyz")
        truth = [float(x) * 1000.0 for x in tr] if isinstance(tr, (list, tuple)) and len(tr) >= 3 else None
        if truth and st_truth.get("prev"):
            dv = [truth[i] - st_truth["prev"][i] for i in range(3)]
            mag_dv = max(abs(x) for x in dv)
            if mag_dv > a.max_step:              # 跨阶段跳变收一档
                dv = [x * a.max_step / mag_dv for x in dv]
            d = [x * a.scale for x in dv]
        else:
            d = [u[i] * a.step for i in range(3)]
        st_truth["prev"] = truth or st_truth.get("prev")
        scale = 1.0
        for i in range(3):
            room = a.band - abs((cur[i] - anchor[i]) * 1000.0)
            if abs(d[i]) > 1e-6 and (cur[i] - anchor[i]) * d[i] > 0:
                scale = min(scale, max(0.0, room / abs(d[i])))
        d = [x * scale for x in d]
        if max(abs(x) for x in d) > a.max_step:                # 单拍上限
            d = [x * a.max_step / max(abs(v) for v in d) for x in d]
        if max(abs(x) for x in d) < 2.0:
            print("🚧 %-8s 已到包络边界 ⇒ 跳过" % s, flush=True)
            continue
        if not _get("/ctl/status").get("motion_armed"):
            print("🔒 授权已撤 ⇒ 停", flush=True)
            break
        _fifo({"id": "stg_%d_%d" % (int(time.time() * 1000), n), "cmd": "move-rel", "tag": "bridge",
               "dx": round(d[0], 2), "dy": round(d[1], 2), "dz": round(d[2], 2),
               "speed": min(100.0, a.speed), "cap_mm": min(50.0, a.max_step), "guard_box": gbox})
        n += 1
        print("⚡ 动作 %2d · %-8s 方向(%+.2f,%+.2f,%+.2f) → 命令(%+.1f,%+.1f,%+.1f)mm@%.0f (不等回执)"
              % (n, s, u[0], u[1], u[2], d[0], d[1], d[2], a.speed), flush=True)
        pend = (s, d, cur, time.time())
        t_next = time.time() + a.min_gap
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "stage": s, "u": u, "cmd_mm": d,
                                    "pose": cur, "speed_mm_s": a.speed},
                                   ensure_ascii=False) + "\n")
        except Exception:                                                 # noqa: BLE001
            pass
    if pend:
        cur = [float(x) for x in _get("/pose")["xyz"]]
        dp = [round((cur[i] - pend[2][i]) * 1000.0, 1) for i in range(3)]
        print("   ↳ 最后一拍 %-6s 命令 %s → 实测 %s mm" % (pend[0], [round(x, 1) for x in pend[1]], dp), flush=True)
    print("✅ 下发 %d 个动作 (异步, 未等回执)" % n, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
