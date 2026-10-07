#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_watch.py — 建图期间的后台哨兵 (2026-10-07 SDK 执行腿首跑)

每 20s 记一条: 轮次/步骤/状态行/当前位置/授权剩余/腿证据条数; 异常或结束即退出。
输出: ~/zmax/zmax_data/gs_map/watch.log (末尾 40 行即全过程摘要)
"""
import json
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/tools/rokae")
import l2_transport_sdk as T                                                        # noqa: E402

ROOT = os.path.expanduser("~/zmax/zmax_data/gs_map")
STATUS = os.path.join(ROOT, "status.json")
RUNLOG = os.path.join(ROOT, "run.log")
WATCH = os.path.join(ROOT, "watch.log")
DAEMON = os.path.expanduser("~/zmax/zmax_data/l2_daemon.log")
DONE = os.path.join(ROOT, "watch.done")

T0 = time.time()
MAX_S = float(os.environ.get("GSWATCH_MAX_S", "3300"))
last = {"step": None, "line": None, "daemon": 0, "log": 0}
w = open(WATCH, "a", encoding="utf-8")


def say(s):
    line = "[%s +%4.0fs] %s" % (time.strftime("%H:%M:%S"), time.time() - T0, s)
    w.write(line + "\n")
    w.flush()
    print(line, flush=True)


def tail_new(path, key, n=6):
    try:
        lines = open(path, encoding="utf-8", errors="ignore").readlines()
    except OSError:
        return []
    out = [l.rstrip("\n") for l in lines[last[key]:]][:n]
    last[key] = len(lines)
    return out


say("哨兵起: 盯 %s (最长 %.0f 分钟)" % (STATUS, MAX_S / 60))
try:
    st0 = json.load(open(STATUS, encoding="utf-8"))
    say("起始状态: %s" % json.dumps(st0, ensure_ascii=False)[:300])
except Exception as e:                                                              # noqa: BLE001
    say("状态文件读不到: %s" % e)
last["daemon"] = len(open(DAEMON, encoding="utf-8", errors="ignore").readlines())
try:
    last["log"] = max(0, len(open(RUNLOG, encoding="utf-8", errors="ignore").readlines()) - 2)
except OSError:
    last["log"] = 0

bad, polls = 0, 0
while time.time() - T0 < MAX_S:
    time.sleep(20)
    polls += 1
    try:
        st = json.load(open(STATUS, encoding="utf-8"))
    except Exception as e:                                                          # noqa: BLE001
        say("⚠️ 状态文件读失败: %s" % str(e)[:80])
        continue
    try:
        p = T.read_pose()
        pos = "%0.4f,%0.4f,%0.4f(龄%.1fs)" % (p["pos"][0], p["pos"][1], p["pos"][2], p["age"])
    except Exception as e:                                                          # noqa: BLE001
        pos = "读不到(%s)" % str(e)[:40]
    arm = ""
    try:
        d = json.loads(open("/home/ubuntu/zmax/zmax_data/ctl_auth.json", encoding="utf-8").read())
        arm = "授权剩%.0fs" % max(0, float(d.get("until") or 0) - time.time())
    except Exception:                                                               # noqa: BLE001
        pass
    say("轮%s 步骤=%s %s | TCP %s | %s" % (st.get("round") or st.get("i") or "-",
        st.get("step"), str(st.get("status_line"))[:90], pos, arm))
    for l in tail_new(RUNLOG, "log", 3):
        say("  运行日志> %s" % l[:150])
    for l in tail_new(DAEMON, "daemon", 4):
        if "SDK 腿" in l or "被拦" in l or "拒" in l:
            say("  执行器> %s" % l[:170])
            if "被拦" in l or "拒发" in l or "失败" in l:
                bad += 1
    if not st.get("running"):
        say("✅ 结束(running=false): step=%s status=%s" % (st.get("step"), str(st.get("status_line"))[:120]))
        break
    if bad >= 3:
        say("⛔ 连续 %d 次下发被拦/失败 ⇒ 停哨兵并叫你" % bad)
        break
else:
    say("⏰ 哨兵到点(%s), 建图状态: %s" % (time.strftime("%H:%M:%S"), json.dumps(st, ensure_ascii=False)[:200]))

try:
    st = json.load(open(STATUS, encoding="utf-8"))
    k = [x for x in (st.get("log") or [])][-6:]
    say("最后 6 条运行日志:")
    for l in k:
        say("  · %s" % str(l)[:170])
except Exception:                                                                   # noqa: BLE001
    pass
say("哨兵退出")
open(DONE, "w", encoding="utf-8").write(json.dumps({"t": time.strftime("%F %T"), "polls": polls}, ensure_ascii=False))
w.close()
