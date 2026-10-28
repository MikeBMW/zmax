# -*- coding: utf-8 -*-
"""mapping_autostart.py — 进系统自动加载建图并启动建图程序 (融合定位建图)

老倪口径: 「系统进入自主进化模式, 进入系统后, 你自动加载自动建图功能, 启动建图程序」。

做法 (真实执行, 不是描述):
  start  → 读唯一依据 config/platform/zmax_mapping.json; auto_load=false 则拒绝启动; 否则把建图循环
           **脱离终端**启动 (nohup + setsid), 逐帧抓真图 (8797/snap, 按 interval 节流) → ORB 前端 →
           关键帧/地图点/回环 → 持续写 zmax_data/mapping/mapping_live.json (带帧龄); pid 落 zmax_data/mapping/autostart.pid
  status → pid 存活 + live 唯一依据帧龄 + 建图摘要 (帧/kf/地图点/回环/尺度来源)
  stop   → **按 pid 文件**停 (禁 ps|grep 按名匹配 —— 命令行含名会自杀)
  once   → 只跑一轮并退出 (取证用)

幂等: 已在跑则不重复启动; 已停则 stop 无副作用。
用法: gui-venv311/bin/python tools/mapping_autostart.py {start|status|stop|once} [--n 帧数] [--interval 秒]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
D = os.path.join(ROOT, "zmax_data", "mapping")
PID = os.path.join(D, "autostart.pid")
LIVE = os.path.join(D, "mapping_live.json")
LOG = os.path.join(D, "autostart.log")
MOD = os.path.join(ROOT, "src", "lerobot", "manifold", "localization_mapping.py")
PY = sys.executable or os.path.join(ROOT, "gui-venv311", "bin", "python")


def _alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:                                                            # noqa: BLE001
        return False


def _read_pid():
    try:
        with io.open(PID, encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:                                                            # noqa: BLE001
        return None


def _live():
    try:
        with io.open(LIVE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                            # noqa: BLE001
        return None


def start(n: int, interval: float, cam: str, scene: str) -> int:
    from lerobot.manifold import localization_mapping as LM
    cfg = LM.load_config()
    if not cfg.get("auto_load", True):
        print(json.dumps({"started": False, "reason": "唯一依据 auto_load=false (进系统自动加载被关)"}, ensure_ascii=False))
        return 1
    p = _read_pid()
    if p and _alive(p):
        print(json.dumps({"started": False, "reason": "已在跑 (pid %d)" % p}, ensure_ascii=False))
        return 0
    os.makedirs(D, exist_ok=True)
    cam = cam or cfg.get("cam", "arm")
    scene = scene or cfg.get("scene", "SCN-07-AOI")
    cmd = [PY, MOD, "run", "--n", str(int(n)), "--cam", cam, "--interval", str(float(interval)),
           "--scene", scene, "--rounds", "0"]                    # 0 = 持续跑 (启动建图程序) 直到 stop
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    logf = io.open(LOG, "ab")
    # 脱离终端: start_new_session=True (setsid 等价) ⇒ agent/终端退出也不带走它
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True, env=env)
    with io.open(PID, "w", encoding="utf-8") as f:
        f.write(str(proc.pid))
    time.sleep(3)
    st = {"started": True, "pid": proc.pid, "cmd": " ".join(cmd), "log": LOG,
          "alive": _alive(proc.pid), "config_auto_load": cfg.get("auto_load"),
          "live": _live(), "pid_file": PID}
    print(json.dumps(st, ensure_ascii=False, indent=1))
    return 0


def status() -> int:
    p = _read_pid()
    lv = _live()
    out = {"pid": p, "pid_alive": bool(p and _alive(p)), "pid_file": PID,
           "live": lv,
           "live_age_s": (round(time.time() - lv["ts"], 1) if lv else None),
           "summary": ({k: lv.get(k) for k in ("frames", "keyframes", "map_points", "loops",
                                               "scale_source", "cam", "scene", "source_kind")} if lv else None)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def stop() -> int:
    p = _read_pid()
    if not p:
        print(json.dumps({"stopped": False, "reason": "没有 pid 文件"}, ensure_ascii=False))
        return 0
    if not _alive(p):
        print(json.dumps({"stopped": False, "reason": "pid %d 已不在" % p}, ensure_ascii=False))
        return 0
    os.kill(p, signal.SIGTERM)                     # 按 pid 停, 绝不按进程名匹配
    for _ in range(20):
        if not _alive(p):
            break
        time.sleep(0.3)
    ok = not _alive(p)
    print(json.dumps({"stopped": ok, "pid": p, "still_alive": (not ok)}, ensure_ascii=False))
    return 0 if ok else 1


def once(n: int, interval: float, cam: str, scene: str) -> int:
    from lerobot.manifold import localization_mapping as LM
    r = LM.auto_start(n_frames=n, cam=cam, scene=scene, interval_s=interval)
    print(json.dumps({"source_kind": r.get("source_kind"), "summary": r.get("summary"),
                      "loop": r.get("loop"), "save": r.get("save"), "errors": (r.get("errors") or [])[:2]},
                     ensure_ascii=False, indent=1))
    return 0 if r.get("started") else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="进系统自动加载建图并启动建图程序")
    ap.add_argument("cmd", choices=["start", "status", "stop", "once"])
    ap.add_argument("--n", type=int, default=600, help="本轮建图抓多少帧 (默认 600)")
    ap.add_argument("--interval", type=float, default=0.4, help="抓帧间隔秒 (源刷新 100~500ms ⇒ 勿小于 0.1)")
    ap.add_argument("--cam", default="")
    ap.add_argument("--scene", default="")
    a = ap.parse_args()
    if a.cmd == "start":
        return start(a.n, a.interval, a.cam, a.scene)
    if a.cmd == "status":
        return status()
    if a.cmd == "stop":
        return stop()
    return once(a.n, a.interval, a.cam, a.scene)


if __name__ == "__main__":
    raise SystemExit(main())
