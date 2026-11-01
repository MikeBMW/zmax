#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建图监工 v2: 每 15s 读状态 + 执行器日志, **每次下发都报上升/下降量**, 上升 >50mm 高声预警;
   报每轮到位偏差与视点数; 建图结束或 90 分钟退出。只读, 不下发任何动作。"""
import json
import os
import re
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/tools/rokae")
import l2_transport_sdk as T  # noqa: E402

ST = os.path.expanduser("~/zmax/zmax_data/gs_map/status.json")
DL = os.path.expanduser("~/zmax/zmax_data/l2_daemon_stdout.log")
GS = os.path.expanduser("~/zmax/zmax_data/gs_assets")
RISE_WARN_MM = 50.0

t0 = time.time()
off = os.path.getsize(DL) if os.path.exists(DL) else 0
last_key = None
rounds, warns, errs = [], [], []


def tail_new():
    global off
    try:
        with open(DL, "rb") as f:
            f.seek(off)
            data = f.read()
            off += len(data)
        return data.decode("utf-8", "replace").splitlines()
    except Exception:                                                            # noqa: BLE001
        return []


print("═══ 建图监工 v2 启动 %s · 天花板 %.4f · 自愈闸门 %s ═══"
      % (time.strftime("%H:%M:%S"), T.taught_z_ceiling(), T.MOVEJ_RETRY), flush=True)
p0 = T.read_pose()
print("  起点 (%.4f, %.4f, %.4f)  只往高处提醒: 上升 > %.0fmm 会高声预警" % (*p0["pos"], RISE_WARN_MM), flush=True)

while time.time() - t0 < 90 * 60:
    for l in tail_new():
        s = str(l)
        m = re.search(r"Δ=\(\s*([-+\d.]+), ([-+\d.]+), ([-+\d.]+)\)mm\s*([↑↓→]?)", s)
        if m and "已下发" in s:
            dz = float(m.group(3))
            if dz > 5:
                tag = "⚠️⚠️ 上升 %.0fmm" % dz
                if dz > RISE_WARN_MM:
                    warns.append("%s %s" % (time.strftime("%H:%M:%S"), tag))
                    tag = "🚨🚨🚨 " + tag + " ← 老倪注意: 这是自动上升, 随时可按停"
                print("      %s | %s" % (time.strftime("%H:%M:%S"), tag), flush=True)
                print("        %s" % s[:165], flush=True)
        if any(w in s for w in ("❌ SDK 腿失败", "🛑", "拒发", "未在")):
            errs.append("%s %s" % (time.strftime("%H:%M:%S"), s[:150]))
            print("      ⚠️ %s" % s[:150], flush=True)
        if "到位(偏差" in s:
            print("      ✓ %s" % s[:130], flush=True)
            rounds.append(s[:130])
        if "采集收工" in s:
            print("      📷 %s" % s[:150], flush=True)
    st = {}
    try:
        st = json.load(open(ST, encoding="utf-8"))
    except Exception:                                                            # noqa: BLE001
        pass
    key = (st.get("running"), str(st.get("status_line"))[:60])
    if key != last_key:
        last_key = key
        print("[%s] running=%s | %s" % (time.strftime("%H:%M:%S"), st.get("running"), str(st.get("status_line"))[:100]), flush=True)
    if st and not st.get("running") and time.time() - t0 > 60:
        break
    time.sleep(15)

print("\n═══ 监工收尾 %s ═══" % time.strftime("%H:%M:%S"), flush=True)
print("  到位记录 %d 条:" % len(rounds), flush=True)
for r in rounds[-10:]:
    print("    %s" % r, flush=True)
print("  上升预警 %d 次:" % len(warns), flush=True)
for w in warns:
    print("    %s" % w, flush=True)
print("  异常 %d 条:" % len(errs), flush=True)
for e in errs[-8:]:
    print("    %s" % e, flush=True)
try:
    ss = sorted([d for d in os.listdir(GS) if d.startswith("map_")], key=lambda d: os.path.getmtime(os.path.join(GS, d)))
    print("  资产目录: %s" % (ss[-3:] or "还没有"), flush=True)
except Exception:                                                                # noqa: BLE001
    pass
print("  臂 (%.4f, %.4f, %.4f)" % (*T.read_pose()["pos"],), flush=True)
