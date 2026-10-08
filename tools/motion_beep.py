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
# 🆕 2026-10-08 老倪: 「也可以抬升, 但要慢一些, 而且要发出警报声音」—— 抬升专用警报:
#   判据 = TCP 真值 z 分量在涨(dz/dt > LIFT_UP_MM_S)。任何路径的抬升(8793 页面 / AOI 伺服 / GUI 原子技能)
#   都会经过真值 ⇒ 都覆盖; 不动执行器, 只在监控侧发声。文件丢了会现场自愈重生成(安全件不能静默失效)。
WAV_LIFT = os.path.join(REPO, "zmax_data", "lift_alarm.wav")
LIFT_UP_MM_S    = 0.30      # 上升速度阈值(mm/s) —— 低于它算持平/噪声
LIFT_ALARM_GAP_S = 1.60     # 抬升中警报间隔(每声 ~1.41s 长, 间隔 1.6s ⇒ 连续提醒且不叠音)
# 🆕 2026-10-08 老倪: 「移动的时候, 要发出警报声音」 —— 实验性移动(动臂试探视角)要求**只要是移动就响警报**,
#    而不是常规提示音。用**文件开关**(不改代码即可现场热切): 存在 ~/zmax/zmax_data/beep_force_alarm ⇒
#    移动期间一律播 lift_alarm.wav(与抬升警报同一个音, 间隔同上); 文件删掉即恢复"移动响提示音"。
FORCE_ALARM_FLAG = os.path.join(REPO, "zmax_data", "beep_force_alarm")
LOG = os.path.join(REPO, "zmax_data", "motion_beep.log")

MOVE_SPEED_MM_S = 0.8      # 判定"在动"的**平移**速度阈值(mm/s)
# 🆕 2026-10-08 实测踩坑: 只判平移 ⇒ **原地纯旋转(A/B/C/J6 姿态微调)位移 0mm, 一声不响**
#    (现场实测: 执行器报"位移 0mm · 姿态差 3.0°", 警报脚本判"静止" ⇒ 老倪要求的"移动就响警报"落空)。
#    姿态轴也必须有判据: 角速度 > 阈值就算在动。噪声实测 ~1e-6 rad 级 ⇒ 0.25°/s 有 50 倍余量。
ANG_SPEED_DEG_S = 6.0
# ⚠️ 2026-10-08 21:30 修正(老倪现场: 「总有警报声音但没移动, 是误报么?」): 0.25°/s 太低 ——
#   位姿真值(tcp_out/latest.json)在**完全静止**时的姿态抖动就达 ~0.86°/s(实测日志 0.00mm/s · 0.86°/s),
#   直接把阈值顶穿 ⇒ 没动也一直响警报。姿态判据只能抓"快的原地旋转", 慢转(≈0.4°/s, speed=8~20)其实分辨不了 ——
#   要"慢转也报警"必须用**指令侧**信号(执行器/8793 的 in-motion 状态), 不能靠位姿求导。     # 判定"在动"的**姿态**角速度阈值(deg/s)
STOP_HOLD_S     = 2.5      # 速度低于阈值持续这么久 → 判"停"(迟滞; 段间小停顿不掐音)
TICK_GAP_MAX_S  = 1.8      # 最慢(1mm/s 级)时的间隔
TICK_GAP_MIN_S  = 0.12     # 最快时的间隔(蜂鸣式)
TICK_GAP_K      = 1.8      # 间隔 = K / 速度(mm/s) ⇒ **高频对应快速**(老倪 2026-10-08)
FAST_TONE_MM_S  = 5.0      # ≥5mm/s 用高音(1050Hz), 否则低音(660Hz)
AMP             = 0.78     # 幅度(78%) — 老倪「再音量大一些」
POLL_HZ         = 8.0


def _ang_deg(qa, qb):
    """两个四元数之间的夹角(度) —— 与 l2_transport_sdk 同式: 2*acos(|dot|)。"""
    d = abs(sum(float(a) * float(b) for a, b in zip(qa, qb)))
    return math.degrees(2.0 * math.acos(min(1.0, d)))


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


def make_lift_alarm(path):
    """抬升警报: 880Hz x3 短促脉冲 + 6Hz 颤音(比提示音更"扎耳", 一次 ~1.9s); 已存在则不覆盖。"""
    if os.path.isfile(path):
        return
    sr = 44100
    frames = bytearray()
    for _k in range(3):
        n = int(sr * 0.35)
        for i in range(n):
            t = i / sr
            fade = min(1.0, i / (0.012 * sr), (n - i) / (0.012 * sr))
            s = (math.sin(2 * math.pi * 880.0 * t) + 0.4 * math.sin(2 * math.pi * 1760.0 * t)) / 1.4
            v = s * 0.95 * fade * (0.75 + 0.25 * math.sin(2 * math.pi * 6.0 * t))
            frames += int(max(-1.0, min(1.0, v)) * 32767).to_bytes(2, "little", signed=True)
        frames += b"\x00\x00" * int(sr * 0.18)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(bytes(frames))


def player():
    for c in ("paplay", "pw-play", "aplay"):
        if subprocess.run(["which", c], capture_output=True).returncode == 0:
            return c
    return None


def main():
    make_tick(WAV_SLOW, 660.0)
    make_tick(WAV_FAST, 1050.0)
    make_lift_alarm(WAV_LIFT)
    pl = player()
    if not pl:
        log("❌ 找不到放音程序(paplay/pw-play/aplay) ⇒ 退出")
        return 2
    log("移动提示音启动 · 播放器=%s · 幅度%.0f%% · 阈值 %.1fmm/s · 间隔=%.1f/速度(%.2f~%.1fs) 高频=快"
        % (pl, AMP * 100, MOVE_SPEED_MM_S, TICK_GAP_K, TICK_GAP_MIN_S, TICK_GAP_MAX_S))

    import l2_transport_sdk as T

    prev_pos, prev_t, prev_quat = None, None, None
    vema = 0.0
    vz_ema = 0.0
    moving = False
    lifting = False
    below_since = None
    last_tick = 0.0
    last_alarm = 0.0
    proc = None
    proc_alarm = None
    errs = 0
    dt = 1.0 / POLL_HZ
    _forced_log = None
    while True:
        t0 = time.time()
        _forced = os.path.exists(FORCE_ALARM_FLAG)      # 文件开关: 移动即警报
        age = 99.0                      # 读失败时保持"不发声"(宁可不响, 不谎报在动)
        try:
            a = T.read_pose()
            pos = [float(v) for v in a["pos"]]
            quat = [float(v) for v in (a.get("quat") or [0.0, 0.0, 0.0, 1.0])]
            age = float(a.get("age") or 0.0)
        except Exception as e:
            errs += 1
            if errs in (1, 50, 500):
                log("⚠️ 位姿读失败(%d 次): %s ⇒ 保持静音" % (errs, e))
            pos = None
            quat = None
        now = time.time()
        if pos is not None and prev_pos is not None and age < 1.0:
            d = math.dist(pos, prev_pos) * 1000.0
            dt_real = max(1e-3, now - prev_t)
            v = d / dt_real
            vema = v if vema == 0.0 else (0.6 * v + 0.4 * vema)     # 平滑, 免抖动
            # 🆕 抬升判定: 只看 z 分量在涨(与"水平移动"区分开, 抬升要专门的警报音)
            vz = (pos[2] - prev_pos[2]) * 1000.0 / dt_real
            vz_ema = vz if vz_ema == 0.0 else (0.6 * vz + 0.4 * vz_ema)
            was_lifting = lifting
            lifting = vz_ema > LIFT_UP_MM_S
            if lifting and not was_lifting:
                log("🚨 检测到抬升 (vz %.2fmm/s) —— 切抬升警报音" % vz_ema)
            elif was_lifting and not lifting:
                log("⬇️ 抬升结束 —— 回到常规提示音")
            _ang_v = _ang_deg(quat, prev_quat) / dt_real if prev_quat else 0.0
            if (v > MOVE_SPEED_MM_S) or (_ang_v > ANG_SPEED_DEG_S):
                below_since = None
                if not moving:
                    moving = True
                    log("▶️ 检测到移动 (%.2fmm/s · %.2f°/s%s) —— 开始提示音"
                        % (v, _ang_v, " · 原地旋转" if v <= MOVE_SPEED_MM_S else ""))
            else:
                if below_since is None:
                    below_since = now
                elif moving and (now - below_since) > STOP_HOLD_S:
                    moving = False
                    log("⏸ 已静止 —— 停止提示音")
        if pos is not None:
            prev_pos, prev_t = pos, now
            prev_quat = quat
        gap = max(TICK_GAP_MIN_S, min(TICK_GAP_MAX_S, TICK_GAP_K / max(vema, 0.4)))
        # 🆕 抬升中 或 强制模式下的任何移动: 只响专用警报(不用常规提示音, 免得两种声音混在一起听不清)
        _alarm_mode = bool(lifting or (_forced and moving))
        if _forced != _forced_log:
            _forced_log = _forced
            log("🔔 强制警报开关 = %s (移动即播警报音 %s)" % (_forced, os.path.basename(WAV_LIFT)))
        if _alarm_mode and (now - last_alarm) >= LIFT_ALARM_GAP_S:
            last_alarm = now
            log("🚨 警报 ♪ (%s, vz %.2fmm/s)" % ("抬升" if lifting else "强制-移动", vz_ema))
            try:
                if proc_alarm is None or proc_alarm.poll() is not None:
                    proc_alarm = subprocess.Popen([pl, WAV_LIFT],
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                log("⚠️ 警报放不出声: %s" % e)
        if (not _alarm_mode) and moving and (now - last_tick) >= gap:
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
