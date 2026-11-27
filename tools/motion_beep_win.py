#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""motion_beep_win.py — Windows 版机器人移动提示音。

原 tools/motion_beep.py 依赖 paplay/pw-play/aplay(Linux 音频) + l2_transport_sdk(ROS 腿),
在 Windows 工位机上起不来 ⇒ 移动时没有任何提示音。这个精简版用 winsound.Beep,
数据源改用已经稳定的 HTTP 位姿接口 (8793/pose, 5Hz 刷新):

  在动(速度 > 阈值)      → 660Hz 慢滴 / 速度更快 → 1050Hz 快滴
  z 在涨(抬升)          → 880Hz 三声颤音(专用警报)
  不动                   → 完全静音
  位姿读不到/过期         → 静音(宁可不响, 不谎报"在动")

用法: python tools/motion_beep_win.py
日志: zmax_data/motion_beep_win.log
"""
import json
import os
import sys
import threading
import time
import urllib.request

POSE_URL = os.environ.get("ZMAX_BEEP_POSE_URL") or "http://127.0.0.1:8793/pose"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(REPO, "zmax_data", "motion_beep_win.log")

MOVE_SPEED_MM_S = float(os.environ.get("ZMAX_BEEP_SPEED", "3.0"))   # 判定"在动"的阈值
FAST_SPEED_MM_S = float(os.environ.get("ZMAX_BEEP_FAST", "25.0"))   # 更快一档的阈值
LIFT_SPEED_MM_S = float(os.environ.get("ZMAX_BEEP_LIFT", "1.5"))    # z 上涨判定
TICK_MIN_S = 0.12
TICK_MAX_S = 1.2
FREQ_SLOW = 660
FREQ_FAST = 1050
FREQ_LIFT = 880


def log(msg):
    line = "%s %s" % (time.strftime("%F %T"), msg)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def beep(freq, ms):
    try:
        import winsound
        threading.Thread(target=lambda: winsound.Beep(int(freq), int(ms)), daemon=True).start()
    except Exception:
        pass


def get_pose():
    try:
        with urllib.request.urlopen(POSE_URL, timeout=1.5) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        if d.get("stale"):
            return None
        xyz = d.get("xyz") or []
        if len(xyz) < 3:
            return None
        return float(xyz[0]), float(xyz[1]), float(xyz[2])
    except Exception:
        return None


def main():
    log("Windows 移动提示音启动 · 位姿源=%s · 阈值 %.1fmm/s · 快档 %.1f · 抬升 %.1f"
        % (POSE_URL, MOVE_SPEED_MM_S, FAST_SPEED_MM_S, LIFT_SPEED_MM_S))
    prev, prev_t = None, None
    last_tick = 0.0
    last_lift = 0.0
    while True:
        t0 = time.time()
        p = get_pose()
        if p is None:
            prev, prev_t = None, None
            time.sleep(0.4)
            continue
        if prev is not None and prev_t:
            dt = max(t0 - prev_t, 1e-3)
            dist = ((p[0] - prev[0]) ** 2 + (p[1] - prev[1]) ** 2 + (p[2] - prev[2]) ** 2) ** 0.5
            v = dist / dt
            vz = (p[2] - prev[2]) / dt
            now = time.time()
            if vz > LIFT_SPEED_MM_S:
                # 抬升: 三声颤音
                if now - last_lift > 0.9:
                    for k in range(3):
                        threading.Timer(0.12 * k, lambda: beep(FREQ_LIFT, 90)).start()
                    last_lift = now
            elif v > MOVE_SPEED_MM_S:
                gap = max(TICK_MIN_S, min(TICK_MAX_S, 30.0 / max(v, 1e-3)))
                if now - last_tick >= gap:
                    beep(FREQ_FAST if v > FAST_SPEED_MM_S else FREQ_SLOW, 90)
                    last_tick = now
        prev, prev_t = p, t0
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log("异常退出: %r" % (e,))
        sys.exit(1)
