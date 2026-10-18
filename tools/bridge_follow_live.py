# -*- coding: utf-8 -*-
"""bridge_follow_live.py — 真机「短距离 · 平顺」跟随仿真 v_ff 的方向

老倪 2026-10-18 现场:
  「虽然慢，但是要连续」「不要走那么远，先短距离，平顺的移动；只要方向跟仿真一样就行」

做法 (和之前"一条命令一个目标"完全不同的机制):
  · SDK 腿里开一个**流式线程**: 每 0.2s 往控制器的路径队列**追加** 2mm 小段
    (moveAppend + setDefaultZone 转角区) ⇒ 控制器一路圆滑走, 中间没有"停一下等下一条"
  · 行程被 band_mm 卡死 (默认 20mm): 累计到带宽就不再往外追加, 等方向反过来
  · 方向每 0.2s 从 plan_from_vff.json 的 v_cmd_mms 现取 ⇒ 只跟方向, 不放大行程
  · 速度 10mm/s 硬上限 (agent 侧再收一次)
  · 安全: 授权撤销 / 桥接关 / 方向流超时 / 控制器报警 → agent 立刻 stop()

用法:
  ./gui-venv311/bin/python tools/bridge_follow_live.py            # 带宽 20mm
  ./gui-venv311/bin/python tools/bridge_follow_live.py --band 15 --speed 8
  Ctrl-C 或桥接开关一关 = 立刻停
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
VFF = os.path.join(REPO, "zmax_data", "ss_live", "plan_from_vff.json")
FIFO = os.path.join(REPO, "zmax_data", "rokae_sdk", "cmd_arm.fifo")
DIRF = os.path.join(REPO, "zmax_data", "rokae_sdk", "follow", "dir.json")
STF = os.path.join(REPO, "zmax_data", "rokae_sdk", "follow", "status.json")
LOG = os.path.join(REPO, "zmax_data", "ss_live", "bridge_follow_live.jsonl")
BASE = "http://127.0.0.1:8793"
STOP = {"flag": False}


def _jload(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                    # noqa: BLE001
        return None


def _fifo(req):
    try:
        fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        os.close(fd)
        return True
    except OSError as e:
        print("⚠️ FIFO 写入失败: %s" % e, flush=True)
        return False


def _armed():
    try:
        with urllib.request.urlopen(BASE + "/ctl/status", timeout=3) as r:
            d = json.loads(r.read().decode("utf-8"))
        return bool(d.get("motion_armed")), d
    except Exception:                                                    # noqa: BLE001
        return False, {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--band", type=float, default=20.0, help="总行程带宽 mm (默认 20)")
    ap.add_argument("--speed", type=float, default=10.0, help="速度 mm/s (默认 10, 硬上限 10)")
    ap.add_argument("--step", type=float, default=2.0, help="单点 mm (默认 2)")
    ap.add_argument("--hz", type=float, default=20.0, help="方向流频率 Hz")
    ap.add_argument("--max-s", type=float, default=600.0, help="最长运行秒数 (默认 600)")
    a = ap.parse_args()
    band = max(5.0, min(40.0, a.band))
    speed = max(1.0, min(10.0, a.speed))
    step = max(0.5, min(5.0, a.step))

    ok, st = _armed()
    if not ok:
        print("⛔ 未授权真动 ⇒ 一行都不发。先到 8793 页面点『🔓 授权真动』(二次确认)。", flush=True)
        return 2
    os.makedirs(os.path.dirname(DIRF), exist_ok=True)
    print("🌊 平顺跟随: 带宽 %.0fmm · 速度 %.1fmm/s · 单点 %.1fmm · 方向来自 v_ff"
          % (band, speed, step), flush=True)
    if not _fifo({"cmd": "follow", "on": True, "speed": speed, "band_mm": band,
                  "step_mm": step, "zone_mm": min(10.0, step * 3)}):
        return 3

    def _sig(_s, _f):
        STOP["flag"] = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    t0 = time.time()
    t_status = 0.0
    armed_cache, t_armed = ok, time.time()
    n_lines = 0
    try:
        while not STOP["flag"] and (time.time() - t0) < a.max_s:
            v = _jload(VFF) or {}
            on = bool(v.get("bridge"))
            if time.time() - t_armed > 1.0:                # 授权每秒复查一次
                armed_cache, _s = _armed()
                t_armed = time.time()
            vc = [float(x) for x in (v.get("v_cmd_mms") or [])][:3]
            payload = {"ts": time.time(), "on": on, "armed": armed_cache,
                       "v": vc, "band_mm": band, "speed_mm_s": speed}
            try:
                with open(DIRF + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                os.replace(DIRF + ".tmp", DIRF)
            except Exception:                                          # noqa: BLE001
                pass
            if not armed_cache:
                print("🔒 授权已撤 ⇒ 停", flush=True)
                break
            if not on:
                print("⏹ 桥接开关已关 ⇒ 停", flush=True)
                break
            if time.time() - t_status >= 1.0:
                t_status = time.time()
                s = _jload(STF) or {}
                print("… 追加 %d 点 · 累计到 (%.4f, %.4f, %.4f) · 行程 %.1fmm · 方向流 %.2fs前 · %s"
                      % (s.get("n") or 0, *(list(s.get("commit") or [0, 0, 0])[:3]),
                         s.get("travel_mm") or 0.0, s.get("dir_age_s") or 0.0,
                         (s.get("why") or "-")[:40]), flush=True)
                try:
                    with open(LOG, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts": time.time(), "dir": vc, "status": s},
                                           ensure_ascii=False) + "\n")
                except Exception:                                      # noqa: BLE001
                    pass
                n_lines += 1
            time.sleep(max(0.01, 1.0 / a.hz))
    finally:
        _fifo({"cmd": "follow", "on": False})
        time.sleep(0.6)
        s = _jload(STF) or {}
        print("🛑 已停: 追加 %d 点 · 行程 %smm · 原因: %s"
              % (s.get("n") or 0, s.get("travel_mm"), (s.get("why") or "-")[:60]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
