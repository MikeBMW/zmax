#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回归判据: 双击启动图标(= tools/gui/launch_studio.sh)后**不得自动开 3D/信号/画布**。
老倪 2026-10-12 定规矩: 「点开启动图标后, 3D场景不要自动启动, 我要先检查任务配置, 然后启动工程」

判据:
  ① 控制台进程起来 (studio.py)
  ② 落到配置中心 —— 日志出现「🚀 开机默认页: config (ZMAX_BOOT_PAGE, 老倪标准打开流程第一步)」
  ③ 启动后 45s 内 **不得**出现标题含「3D场景」或「实时监控」的窗口 (画布不新开窗, 不阻塞判定)
  ④ 残留命令文件 /tmp/zmax_nav_cmd 必须是空 (否则新进程会执行上一轮命令 = 假"自动启动")
"""
import os
import re
import subprocess
import sys
import time

REPO = "/home/ubuntu/zmax"
LOG = "/tmp/studio_launch.log"
BAD = ("3D场景", "实时监控")


def sh(cmd, timeout=60):
    e = dict(os.environ)
    e["DISPLAY"] = ":0"
    try:
        return subprocess.run(cmd, shell=True, cwd=REPO, env=e, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.decode("utf-8", "ignore")
    except Exception as ex:                                                     # noqa: BLE001
        return "ERR %r" % (ex,)


def wins():
    out = sh("wmctrl -l")
    return [ln for ln in out.splitlines() if ln.strip()]


def titles():
    return " | ".join(w.split(" ", 3)[-1] for w in wins())


print("=== ① 关掉在跑的控制台 (按 pid, 不用 pkill 模式匹配) ===")
pids = [p for p in sh("pgrep -f '[s]tudio.py'").split() if p.strip().isdigit()]
print("   现场 pid:", pids or "无")
for p in pids:
    sh("kill %s" % p)
time.sleep(6)
left = [p for p in sh("pgrep -f '[s]tudio.py'").split() if p.strip().isdigit()]
if left:
    print("   还有残留, 强杀:", left)
    for p in left:
        sh("kill -9 %s" % p)
    time.sleep(3)

print("=== ② 先往命令通道塞一条旧命令(模拟上一轮残留) 再启动 ===")
open("/tmp/zmax_nav_cmd", "w").write("open_all\n")
print("   /tmp/zmax_nav_cmd = open_all (残留)")

t0 = time.time()
print("=== ③ 走桌面图标同一条路启动: bash tools/gui/launch_studio.sh ===")
sh("nohup bash tools/gui/launch_studio.sh > /tmp/verify_autostart_launch.log 2>&1 &", timeout=20)
time.sleep(8)
nav = ""
try:
    nav = open("/tmp/zmax_nav_cmd").read().strip()
except Exception:                                                               # noqa: BLE001
    nav = "(文件不存在)"
print("   启动后命令文件内容 = %r  (期望空 ⇒ launch_studio.sh 已清残留)" % nav)

print("=== ④ 等控制台窗口 (最多 9 分钟) ===")
win_at = None
for i in range(54):
    if "XSpace Studio" in sh("wmctrl -l"):
        win_at = int(time.time() - t0)
        print("   控制台窗口已出现 (第 %ds)" % win_at)
        break
    time.sleep(10)
if win_at is None:
    print("❌ FAIL: 9 分钟没等到控制台窗口")
    sys.exit(1)

print("=== ⑤ 窗口刚出现 → 观察 45s 内是否冒出 3D/信号窗 ===")
bad_seen = {}
for i in range(16):
    w = wins()
    for b in BAD:
        if any(b in x for x in w):
            bad_seen.setdefault(b, int(time.time() - t0))
    time.sleep(3)
log = ""
try:
    log = open(LOG, encoding="utf-8", errors="ignore").read()
except Exception:                                                               # noqa: BLE001
    pass
boot = bool(re.search(r"开机默认页: config", log))
print("   当前窗口: %s" % titles())
print("   配置中心落地页日志: %s" % ("✅ 有「开机默认页: config」" if boot else "⚠️ 没有该行"))
print()
ok = True
if bad_seen:
    ok = False
    print("❌ FAIL: 自动开了窗口 → %s (第 %s 秒)" % (list(bad_seen), bad_seen))
else:
    print("✅ PASS: 启动后 45s 内没有 3D/信号窗自动出现")
if nav:
    ok = False
    print("❌ FAIL: 命令通道残留没被清掉 (%r) —— 新进程会执行旧命令" % nav)
else:
    print("✅ PASS: 启动后命令通道为空 (残留已清)")
print("✅ PASS: 落到配置中心 (ZMAX_BOOT_PAGE=config)" if boot else "⚠️ 落地页日志没核对到")
print()
print("判据结论: %s" % ("✅ PASS (双击图标 → 只落配置中心, 需老倪自己检查任务配置后点「🚀 启动工程」)"
                        if ok and boot else "❌ 见上面失败项"))
print("进程: %s" % (sh("pgrep -f '[s]tudio.py'").strip() or "无"))
