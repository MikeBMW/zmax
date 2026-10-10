#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stop_check.py — 收尾核查(不自伤): 我的后台命令是否已停 / 臂是否还在动 / 能否取消"""
import json
import os
import subprocess
import time

f = '/home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/latest.json'
d = json.load(open(f))
p0 = [d['x'], d['y'], d['z']]
time.sleep(3)
d = json.load(open(f))
p1 = [d['x'], d['y'], d['z']]
v = [(p1[i] - p0[i]) / 3.0 * 1000 for i in range(3)]
spd = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
print("TCP=%s 帧龄=%.2fs 速度≈%.2f mm/s → %s" % (
    [round(x, 4) for x in p1], time.time() - d['ts'], spd,
    "仍在动(慢速上升)" if spd > 0.03 else "已静止"))
try:
    st = json.load(open('/tmp/st2.json'))
    r = st.get('robot', {})
    print("控制器: power=%s operation=%s mode=%s has_error=%s" % (
        r.get('power'), r.get('operation'), r.get('mode'), r.get('has_error')))
except Exception as e:
    print("状态读失败:", e)
# 我的 python 残留(排除本进程/父链)
me = os.getpid()
out = subprocess.run(["ps", "-eo", "pid,ppid,etimes,cmd"], capture_output=True, text=True).stdout
mine = []
for ln in out.splitlines():
    if ("gui-venv311/bin/python" in ln or "aoi_surface" in ln) and "stop_check" not in ln:
        pr = ln.split(None, 3)
        if pr and pr[0].isdigit() and int(pr[0]) != me:
            mine.append(ln.strip()[:150])
print("我的残留进程 %d 个:" % len(mine))
for m in mine[:8]:
    print("   ", m)
