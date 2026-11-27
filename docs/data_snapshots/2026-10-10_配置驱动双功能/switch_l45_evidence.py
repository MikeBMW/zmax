# -*- coding: utf-8 -*-
"""切换配置证据 (带 L5/L4 逐层): 交替跑 插拔↔摆盘, 每轮抓
  ①真源回读 active_task + 文件 sha 变化 ②L5 计划(阶段链/工序/力上限/节拍/目标) ③L4 逐层计数 ④档位 ⑤判据结果。

用法: python switch_l45_evidence.py [轮数]
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = "/home/ubuntu/zmax"
BIND = os.path.join(ROOT, "config/ss_task_binding.json")
PY = os.path.join(ROOT, "gui-venv311/bin/python")
RUNNER = os.path.join(ROOT, "tools/ss_task_runner.py")
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 2
SEQ = [("TASK-01-FW", "insert", []), ("TASK-06-TRAY", "tray", ["--modules", "3"])] * ROUNDS


def sha():
    return hashlib.sha256(open(BIND, "rb").read()).hexdigest()[:12]


def active():
    return json.load(open(BIND, encoding="utf-8")).get("active_task")


rows = []
for i, (tid, mode, extra) in enumerate(SEQ, 1):
    s0 = sha()
    cmd = [PY, RUNNER, "--task", tid, "--no-video"] + extra
    t0 = time.time()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800)
    out = p.stdout or ""
    s1, act = sha(), active()

    l5 = re.search(r"🧠 L5 下指令 \[([^\]]+)\] mode=(\S+) · 阶段链 (\d+) 段: ([^\n]+)", out)
    proc = re.search(r"工序: ([^\n]+)", out)
    force = re.search(r"力上限 ([\d.]+)N", out)
    goal = re.search(r"目标数值: ([^\n]+)", out)
    l4 = re.search(r"🛡 L4 \[([^\]]+)\] 帧(\d+) · 限速(\d+) · 力否决\(仿真尺度\)(\d+) · 超真机力上限帧(\d+) · "
                   r"z下限(\d+) · INTACT平滑(\d+) · DiT精炼(\d+) · 力上限([\d.]+)N", out)
    sw = re.search(r"⚙️ 档位: ([^\n]+)", out)
    try:
        rep = json.load(open(os.path.join(ROOT, "reports", "ss_task_run_%s_latest.json" % tid), encoding="utf-8"))
    except Exception:                                                     # noqa: BLE001
        rep = {}
    ce = rep.get("config_effect") or {}
    mods = (rep.get("result") or {}).get("per_module") or []
    ok = bool(mods) and all(("完成" in m) or ("✅ 合格" in m) for m in mods)
    l45r = rep.get("l45") or {}
    l4r = (l45r.get("L4") or {}) if isinstance(l45r, dict) else {}
    l5r = (l45r.get("L5") or {}) if isinstance(l45r, dict) else {}
    rows.append(dict(round=i, task=tid, mode=mode,
                     active_before=(ROOT and None) or None or (rows[-1]["active_after"] if rows else None),
                     active_after=act, sha_before=s0, sha_after=s1, sha_changed=(s0 != s1),
                     chain=ce.get("chain"), mode_report=ce.get("mode"),
                     l5_task=(l5.group(1) if l5 else None), l5_mode=(l5.group(2) if l5 else None),
                     l5_stages=(int(l5.group(3)) if l5 else None),
                     l5_chain=(l5.group(4).strip() if l5 else None),
                     l5_steps=(proc.group(1).strip() if proc else None),
                     l5_force=(l5r.get("force_cap_n") or (force.group(1) if force else None)),
                     l5_goals=(goal.group(1).strip() if goal else None),
                     l4_frames=(l4r.get("frames") or (int(l4.group(2)) if l4 else None)),
                     l4_speedlim=(l4r.get("speed_lim") if l4r else (int(l4.group(3)) if l4 else None)),
                     l4_forceveto=(l4r.get("force_veto") if l4r else (int(l4.group(4)) if l4 else None)),
                     l4_overspec=(l4r.get("over_spec") if l4r else (int(l4.group(5)) if l4 else None)),
                     l4_slew=(l4r.get("intact_slew") if l4r else (int(l4.group(7)) if l4 else None)),
                     l4_dit=(l4r.get("dit_smooth") if l4r else (int(l4.group(8)) if l4 else None)),
                     l45_in_report=bool(l45r),
                     result_line=(mods[0][:70] if mods else None),
                     switches=(sw.group(1).strip() if sw else None),
                     verdict=("通过" if ok else "未通过"), seconds=round(time.time() - t0, 1)))
    print("轮%d %-13s active=%s sha %s→%s  L5 %s段/力%sN  L4 帧%s 限速%s 力否决%s 平滑%s 精炼%s  %s (%.1fs)"
          % (i, tid, act, s0, s1, rows[-1]["l5_stages"], rows[-1]["l5_force"], rows[-1]["l4_frames"],
             rows[-1]["l4_speedlim"], rows[-1]["l4_forceveto"], rows[-1]["l4_slew"], rows[-1]["l4_dit"],
             rows[-1]["verdict"], rows[-1]["seconds"]), flush=True)

out_json = "/tmp/shots/switch_l45_evidence.json"
json.dump(rows, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n✅ 台账: %s" % out_json)
sw_ok = all(r["active_after"] == r["task"] for r in rows)
fn_ok = all(r["chain"] and r["mode_report"] == r["mode"] for r in rows)
l45_ok = all(r["l4_frames"] and r["l5_stages"] for r in rows)
dif = all(r["l5_stages"] != rows[0]["l5_stages"] for r in rows[1::2])
print("  切换到位=%s · 功能跟着换=%s · L4/L5 每轮都在跑=%s · 两任务 L5 阶段链不同=%s"
      % (sw_ok, fn_ok, l45_ok, dif))
