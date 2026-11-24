# -*- coding: utf-8 -*-
"""realtime_map.py — 「📡 融合定位建图」节点的实时建图执行体(轻量壳)

分工:
  · 本模块在**节点的每一拍**被调用, 只做三件毫秒级的事: 确保守护活着 / 读状态 / 拼一行日志;
  · 重活(攒帧、建数据集、增量训练 3DGS、发布资产)在 `tools/gs_realtime_map.py` 守护里异步跑。

为什么不在节点里直接训练: 画布常驻循环 ~10Hz, 一轮 3DGS 训练 5~26 分钟, 同步跑会把整拍卡死。
"只要工作就实时建图" 的落地方式 = 节点活着 ⇒ 守护必活 ⇒ 臂一动就攒帧、攒够就训、训完即发布。
"""
from __future__ import annotations

import json
import os
import subprocess
import time

STATUS = os.path.expanduser("~/zmax_data/gs_map/realtime.json")
LOG = os.path.expanduser("~/zmax_data/gs_map/realtime.log")
DAEMON = os.environ.get("ZMAX_RT_MAP_DAEMON", os.path.expanduser("~/zmax_map/tools/gs_realtime_map.py"))
PY = os.environ.get("ZMAX_RT_MAP_PY", "/usr/bin/python3")
LOCK = os.path.expanduser("~/zmax_data/gs_map/.rt_spawn")
STALE_S = float(os.environ.get("ZMAX_RT_MAP_STALE_S", "25"))
RESPAWN_S = float(os.environ.get("ZMAX_RT_MAP_RESPAWN_S", "30"))

_LAST = {"check": 0.0, "st": {}}


def status(fresh_s: float = 1.0) -> dict:
    """读守护状态(带 1s 级缓存, 不让 10Hz 的节点反复读盘)。"""
    t = time.time()
    if t - _LAST["check"] < fresh_s and _LAST["st"]:
        return _LAST["st"]
    try:
        st = json.load(open(STATUS, encoding="utf-8"))
    except Exception:
        st = {}
    _LAST["check"], _LAST["st"] = t, st
    return st


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def healthy() -> bool:
    st = status()
    if not st:
        return False
    if st.get("pid") and not _pid_alive(st["pid"]):
        return False
    return (time.time() - float(st.get("ts_epoch") or 0)) <= STALE_S


def ensure() -> tuple[bool, str]:
    """确保守护在跑。返回 (是否健康, 动作说明)。节流: 最多每 RESPAWN_S 秒尝试拉起一次。"""
    if healthy():
        return True, "alive"
    try:
        if os.path.exists(LOCK) and (time.time() - os.path.getmtime(LOCK)) < RESPAWN_S:
            return False, "throttled"
        open(LOCK, "w").write(str(time.time()))
    except Exception:
        pass
    if not os.path.exists(DAEMON):
        return False, "daemon 脚本不存在: %s" % DAEMON
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as lf:
            lf.write("\n[%s] 节点拉起守护\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
            lf.flush()
            subprocess.Popen([PY, DAEMON], stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
                             start_new_session=True, cwd=os.path.dirname(DAEMON))
        return False, "spawned"
    except Exception as e:                                                  # noqa: BLE001
        return False, "spawn 失败: %r" % (e,)


def line() -> str:
    """给节点日志用的一行人类可读摘要。"""
    st = status()
    if not st:
        return "🗺 实时建图(3DGS): 守护未启动/无状态"
    ph = st.get("phase") or "?"
    n = st.get("frames_now")
    pend = st.get("pending")
    if st.get("error"):
        return "🗺 实时建图(3DGS): ⚠️ %s · %s" % (ph, str(st["error"])[:120])
    if ph == "train":
        return "🗺 实时建图(3DGS): 训练中 · 数据 %s 帧(待训 %s) · %s 步" % (n, pend, st.get("steps"))
    if ph in ("collect", "wait_trainer", "done"):
        return ("🗺 实时建图(3DGS): %s · 帧 %s(待训 %s) · 最近一轮 PSNR %s dB / %s 高斯 / %ss"
                % (ph, n, pend, st.get("psnr_holdout_db") or "-", st.get("n_gaussians") or "-",
                   st.get("seconds") or "-"))
    return "🗺 实时建图(3DGS): %s · 帧 %s" % (ph, n)
