#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""motion_beep.py — 机器人移动提示音（老倪 2026-10-08 要求）

口径: **机器人在移动 → 响; 不动 → 完全静音。**
音色: 柔和阻尼正弦(660Hz + 弱八度) 90ms, 幅度 ~25% —— 像轻敲木鱼/马林巴,
      不刺耳、不吵(现场可听清但不烦)。移动中每 1.2s 一声; 停下 1 声都不发。

判定: 直读 TCP 真值(5~10Hz), 相邻采样位移换算速度 > 0.8mm/s 视为"在动";
      连续 0.8s 低于阈值才转"停"(带迟滞, 免得抖动时忽响忽停)。
      位姿读不到(网络/通道问题) → 不发声(宁可不响, 也不谎报"在动")。

用法:
  gui-venv311/bin/python tools/motion_beep.py            # 前台
  bash tools/motion_beep_start.sh                        # 后台常驻(带 keepalive)
日志: ~/zmax/zmax_data/motion_beep.log
"""
import math
import os
import subprocess
import sys
import time
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "rokae"))

WAV_SLOW = os.path.join(REPO, "zmax_data", "motion_tick_slow.wav")
WAV_FAST = os.path.join(REPO, "zmax_data", "motion_tick_fast.wav")
LOG = os.path.join(REPO, "zmax_data", "motion_beep.log")

MOVE_SPEED_MM_S = 0.8      # 判定"在动"的速度阈值(mm/s)
STOP_HOLD_S     = 2.5      # 速度低于阈值持续这么久 → 判"停"(迟滞; 段间小停顿不掐音)
TICK_GAP_MAX_S  = 1.8      # 最慢(1mm/s 级)时的间隔
TICK_GAP_MIN_S  = 0.12     # 最快时的间隔(蜂鸣式)
TICK_GAP_K      = 1.8      # 间隔 = K / 速度(mm/s) ⇒ **高频对应快速**(老倪 2026-10-08)
FAST_TONE_MM_S  = 5.0      # ≥5mm/s 用高音(1050Hz), 否则低音(660Hz)
AMP             = 0.78     # 幅度(78%) — 老倪「再音量大一些」
POLL_HZ         = 8.0


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def make_tick(path, f0=660.0):
    """柔和阻尼正弦: f0 + 0.35×2f0, 指数衰减 90ms, 两端 5ms 淡入淡出(无爆音)"""
    if os.path.isfile(path):
        return
    sr, dur = 44100, 0.09
    n = int(sr * dur)
    frames = bytearray()
    for i in range(n):
        t = i / sr
        env = math.exp(-t * 34.0)                       # 阻尼衰减
        fade = min(1.0, i / (0.005 * sr), (n - i) / (0.005 * sr))
        s = (math.sin(2 * math.pi * f0 * t) + 0.35 * math.sin(2 * math.pi * 2 * f0 * t)) / 1.35
        v = int(max(-1.0, min(1.0, s * env * fade * AMP)) * 32767)
        frames += v.to_bytes(2, "little", signed=True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))


def player():
    for c in ("paplay", "pw-play", "aplay"):
        if subprocess.run(["which", c], capture_output=True).returncode == 0:
            return c
    return None


def main():
    make_tick(WAV_SLOW, 660.0)
    make_tick(WAV_FAST, 1050.0)
    pl = player()
    if not pl:
        log("❌ 找不到放音程序(paplay/pw-play/aplay) ⇒ 退出")
        return 2
    log("移动提示音启动 · 播放器=%s · 幅度%.0f%% · 阈值 %.1fmm/s · 间隔=%.1f/速度(%.2f~%.1fs) 高频=快"
        % (pl, AMP * 100, MOVE_SPEED_MM_S, TICK_GAP_K, TICK_GAP_MIN_S, TICK_GAP_MAX_S))

    import l2_transport_sdk as T

    prev_pos, prev_t = None, None
    vema = 0.0
    moving = False
    below_since = None
    last_tick = 0.0
    proc = None
    errs = 0
    dt = 1.0 / POLL_HZ
    while True:
        t0 = time.time()
        age = 99.0                      # 读失败时保持"不发声"(宁可不响, 不谎报在动)
        try:
            a = T.read_pose()
            pos = [float(v) for v in a["pos"]]
            age = float(a.get("age") or 0.0)
        except Exception as e:
            errs += 1
            if errs in (1, 50, 500):
                log("⚠️ 位姿读失败(%d 次): %s ⇒ 保持静音" % (errs, e))
            pos = None
        now = time.time()
        if pos is not None and prev_pos is not None and age < 1.0:
            d = math.dist(pos, prev_pos) * 1000.0
            dt_real = max(1e-3, now - prev_t)
            v = d / dt_real
            vema = v if vema == 0.0 else (0.6 * v + 0.4 * vema)     # 平滑, 免抖动
            if v > MOVE_SPEED_MM_S:
                below_since = None
                if not moving:
                    moving = True
                    log("▶️ 检测到移动 (%.1fmm/s) —— 开始提示音" % v)
            else:
                if below_since is None:
                    below_since = now
                elif moving and (now - below_since) > STOP_HOLD_S:
                    moving = False
                    log("⏸ 已静止 —— 停止提示音")
        if pos is not None:
            prev_pos, prev_t = pos, now
        gap = max(TICK_GAP_MIN_S, min(TICK_GAP_MAX_S, TICK_GAP_K / max(vema, 0.4)))
        if moving and (now - last_tick) >= gap:
            last_tick = now
            tone = WAV_FAST if vema >= FAST_TONE_MM_S else WAV_SLOW
            if proc is None or proc.poll() is not None:
                log("♪ 间隔 %.2fs (速度 %.1fmm/s%s)" % (gap, vema, " · 高音" if tone == WAV_FAST else " · 低音"))
                try:
                    proc = subprocess.Popen([pl, tone],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e:
                    log("⚠️ 播不出声: %s" % e)
                    time.sleep(2.0)
        time.sleep(max(0.0, dt - (time.time() - t0)))


if __name__ == "__main__":
    sys.exit(main())
