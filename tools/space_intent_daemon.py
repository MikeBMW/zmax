#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""space_intent_daemon.py —— 空间点智能体 · 影子守护进程

老倪 2026-11-27：「全程都在影子模式，你要根据实际数据，自主进化」
                   「我要所有代码，所有服务，都与空间点连接起来」

做三件事（全程只读，绝不下发运动）：
  1. 5Hz 读机械臂实时位姿（复用 cam_live_stream._rokae_pose，同源 endInRef）；
  2. 喂给 SpaceIntent.tick() ⇒ 到点判定 + 能力记账（shadow=True）；
  3. 把「位姿 + 命中点 + 能力请求 + 实际判定结果」写进空间轨迹日志，
     供后续自主进化（哪些点总误命中、哪些能力从没触发、哪些点从不被访问）。

额外：每 tick 顺手把 AOI 的最近判决也记进来（10082/10083 /last_result），
      这样"到金手指点→判 fail"这种因果对能在数据里对上。

用法：
    python tools/space_intent_daemon.py --hz 5
    # 环境变量
    ZMAX_SPACE_SHADOW=1       影子（默认）
    ZMAX_SPACE_LIVE=0         设 1 才允许真调（且需外部授权）
    ZMAX_SPACE_INTENTS=...    注册表路径
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

ROOT = os.environ.get("ZMAX_ROOT")
if not ROOT:
    _d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isdir(os.path.join(_d, "tools")) and os.path.isdir(os.path.join(_d, "config")):
            ROOT = _d
            break
        _d = os.path.dirname(_d)
ROOT = ROOT or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ZMAX_ROOT", ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from lerobot.app.workcell.space_intent import SpaceIntent        # noqa: E402

AOI_HOST = os.environ.get("ZMAX_AOI_HOST", "192.168.23.23")
AOI_PORTS = {"gold": 10082, "surface": 10083}
OUT_DIR = os.path.join(ROOT, "zmax_data", "space_intent")
os.makedirs(OUT_DIR, exist_ok=True)

_state = {"verdict": {}, "last_aoi": {}, "aoi_age": {}}


def _get_pose():
    """读实时位姿：优先 cam_live_stream._rokae_pose（含 Orin 桥回退）。返回 (xyz, abc_deg, stale, src) 或 (None,)*4。"""
    try:
        import cam_live_stream as cls                                 # noqa: WPS433
        p = cls._rokae_pose() or {}
        if p.get("xyz"):
            return p.get("xyz"), p.get("abc_deg"), bool(p.get("stale")), str(p.get("src") or "")[:40]
    except Exception:                                                  # noqa: BLE001
        pass
    # 兜底：直接读 tcp_out/latest.json
    for cand in (os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json"),
                 os.path.expanduser("~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json")):
        try:
            d = json.load(open(cand, encoding="utf-8"))
            xyz = [d.get("x"), d.get("y"), d.get("z")]
            if all(v is not None for v in xyz):
                import math
                abc = [None if d.get(k) is None else round(math.degrees(d[k]), 3)
                       for k in ("rx", "ry", "rz")]
                age = time.time() - os.path.getmtime(cand)
                return xyz, abc, age > 10.0, "latest.json(%.0fs)" % age
        except Exception:                                              # noqa: BLE001
            continue
    return None, None, True, ""


def _get_aoi(target: str, timeout: float = 1.0):
    """读 AOI 最近判决（不触发拍照）。返回精简 dict 或 None。"""
    port = AOI_PORTS.get(target)
    if not port:
        return None
    url = "http://%s:%d/last_result" % (AOI_HOST, port)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "zmax-space"}),
                                    timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:                                                  # noqa: BLE001
        return None
    res = d.get("result") or {}
    return {
        "msg": d.get("msg"),
        "verdict": res.get("verdict"),
        "n": res.get("n"),
        "ng": res.get("ng"),
        "judge_ok": res.get("judge_ok"),
        "t": d.get("t"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--live", action="store_true", help="真调模式（默认影子）")
    args = ap.parse_args()

    shadow = not (args.live and os.environ.get("ZMAX_SPACE_LIVE") == "1")
    si = SpaceIntent(shadow=shadow)
    print("[space_intent] 注册表 %s | %d 个点 | shadow=%s | hz=%.1f" % (
        si.path, len(si.points), si.shadow, args.hz), flush=True)
    print("[space_intent] 日志 %s" % si.log_path, flush=True)

    period = 1.0 / max(0.2, args.hz)
    n = 0
    arrived_prev = ""
    tick_i = 0
    while True:
        t0 = time.time()
        tick_i += 1

        xyz, abc, stale, src = _get_pose()
        if not xyz or stale:
            if tick_i % 60 == 0:
                print("[space_intent] 位姿不可用(stale=%s src=%s)，等待…" % (stale, src), flush=True)
            time.sleep(period)
            continue

        r = si.tick(xyz, abc)
        n += 1

        # 命中点的 AOI 判决顺手记进来（因果对：到点 → 判什么）
        hit = r.get("hit") or {}
        role = hit.get("role") or ""
        target = "gold" if role == "aoi_gold" else ("surface" if role == "aoi_surface" else "")
        aoi = _get_aoi(target) if target else None
        if aoi:
            r["aoi"] = aoi

        # 只在"状态变化"时打一行到 stdout，避免刷屏（老倪不喜欢刷屏）
        cur = "%s|%s" % (r.get("verdict"), hit.get("name", ""))
        if cur != arrived_prev:
            print("[space_intent] %s → %s%s%s" % (
                time.strftime("%H:%M:%S"), r.get("verdict"),
                (" " + hit.get("name")) if hit.get("name") else "",
                (" fired=" + ",".join(f.get("kind") or "?" for f in r.get("fired") or []))
                if r.get("fired") else ""), flush=True)
            arrived_prev = cur

        # 每 100 拍（约 20s）报一次总览
        if n % 100 == 0:
            snap = si.snapshot()
            fired = {k: v["fires"] for k, v in snap["points"].items() if v["fires"]}
            print("[space_intent] 已跑 %d 拍 | 触发过的点: %s" % (
                n, fired or "（尚无）"), flush=True)

        dt = time.time() - t0
        time.sleep(max(0.0, period - dt))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[space_intent] 停止", flush=True)
