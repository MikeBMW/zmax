#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夹爪开爪哨兵 —— 只「等闸门放行」, 不动任何闸门。

用法: 后台跑 6 分钟。快层裁决一变 safe(全局相机有画面了)就自动走 8793 授权通道
发**一次** L2.grip_open, 然后把 8793 回执 + 执行器原始行记进日志。
"""
import json
import os
import time
import urllib.request

FAST = "/home/ubuntu/zmax/zmax_data/vl_safety_fast.json"
DAEMON_LOG = "/home/ubuntu/zmax/zmax_data/l2_daemon_stdout.log"
LOG = "/home/ubuntu/zmax/zmax_data/gripper_sentinel_%s.log" % time.strftime("%Y%m%d_%H%M%S")
DEADLINE = time.time() + 360


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def off_before():
    try:
        return os.path.getsize(DAEMON_LOG)
    except OSError:
        return 0


def tail_new(off):
    try:
        with open(DAEMON_LOG, "rb") as f:
            f.seek(off)
            return f.read().decode("utf-8", "replace").strip().splitlines()
    except OSError:
        return []


log("哨兵启动: 盯 %s 的 safe 字段; 一放行就发一次 L2.grip_open(speed=8, arm=1); 上限 6 分钟" % FAST)
sent = False
while time.time() < DEADLINE and not sent:
    try:
        d = json.load(open(FAST))
    except Exception as e:                                              # noqa: BLE001
        log("读快层裁决失败: %s" % e)
        time.sleep(1)
        continue
    if d.get("safe"):
        off = off_before()
        log("✅ 快层放行 (why=%s) ⇒ 发 L2.grip_open" % d.get("why"))
        body = json.dumps({"skill": "L2.grip_open", "speed": 8, "arm": 1}).encode()
        req = urllib.request.Request("http://127.0.0.1:8793/ctl/move", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                log("8793 回执: %s" % r.read().decode()[:700])
        except Exception as e:                                          # noqa: BLE001
            log("8793 请求失败: %s" % e)
        sent = True
        for _ in range(12):
            time.sleep(2)
            new = tail_new(off)
            if any(("GripperSrv_Response" in ln or "受理:" in ln) for ln in new):
                break
        for ln in tail_new(off)[-8:]:
            log("执行器: %s" % ln)
        break
    time.sleep(1)
if not sent:
    log("⏰ 超时: 6 分钟内快层一直未放行(local 仍是黑帧 mean=%s) —— 没有下发" %
        (json.load(open(FAST)).get("per_cam", {}).get("local", {}).get("mean")))
log("日志: %s · 哨兵退出" % LOG)
