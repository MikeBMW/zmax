#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_evolution_550.py — 550A(4060) ⇄ 550C(Intel) 进化同步的单一收口 (无人值守, 零依赖, 可人工跑)

老倪 2026-10-25: 「同步进化550A 和 550C, 550C 要自主进化」

它每轮只做四件事, 每件都留可复核的输出:
  ① 550C 侧进化器**去重**: 同一进化器只留最老的一个进程 —— 实测发现 zmax_evolve_intel 有 3 个
     实例(2 个在 19:27 同时起), symmetry_evolve 也有 3 条日志交错写同一个 ledger, 互相抢 CPU/写文件。
  ② 550C 侧**保活**: 该跑的进化器一个都不能少(hjepa_mr / se3_gravity / symmetry / zmax_evolve_intel),
     少了就按原来的命令行重新拉起(用 setsid, 不受 ssh 断开影响)。
  ③ 550A 侧**自己进化**: 有界步数训 geometric branch(hjepa_mr_train_550a.py), 产物落 ckpt。
  ④ **同步**: 把 550C 的 symmetry_best.json 拉回并按 MARGIN 采纳(pull_symmetry_params.py)。

用法: python3 tools/sync_evolution_550.py [--dry-run] [--json]
退出码: 0 = 本轮正常(含"没有可采纳的提升"); 非零 = 有真故障需要人看。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

REPO = "/home/ubuntu/zmax"
VENV = os.path.join(REPO, "gui-venv311", "bin", "python")
STATE = os.path.join(REPO, "zmax_data", "runtime", "evolution_sync.json")
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "ConnectTimeout=12", "-p", "18822", "intel@127.0.0.1"]

# 进化器: 名字 → (进程匹配串, 用于重启的完整命令行)
EVOLVERS = [
    ("symmetry",   "symmetry_evolve.py",
     "cd /home/intel/zmax_550c && setsid nohup /home/intel/train_venv/bin/python -u "
     "tools/symmetry_evolve.py >> /home/intel/evolve/symmetry_evolve.log 2>&1 < /dev/null &"),
    ("hjepa_mr",   "hjepa_mr/evolve.py", None),      # 由既有 while 循环保活, 这里只统计
    ("se3_gravity", "se3_gravity/evolve.py", None),
    ("zmax_evolve", "zmax_evolve_intel.py", None),
]

DEDUP = ["symmetry_evolve.py", "zmax_evolve_intel.py"]      # 这两类实测会起多份, 必须归并


def sh(cmd, timeout=90, shell=False):
    try:
        return subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def intel(cmd, timeout=60):
    return sh(SSH + [cmd], timeout=timeout)


def intel_ok():
    r = intel("hostname")
    return r.returncode == 0


def counts():
    """返回 {名字: [pid...]} (按进程名匹配, 只统计 >0 的)"""
    r = intel("ps -eo pid,etimes,cmd --no-headers | grep -E 'symmetry_evolve|hjepa_mr/evolve|"
              "se3_gravity/evolve|zmax_evolve_intel' | grep -v grep")
    out = {k: [] for k, _, _ in EVOLVERS}
    for ln in (r.stdout or "").splitlines():
        parts = ln.split(None, 2)
        if len(parts) < 3:
            continue
        pid, etimes, cmd = parts[0], parts[1], parts[2]
        for name, pat, _ in EVOLVERS:
            if pat in cmd and "bash -lc" not in cmd:
                try:
                    out[name].append((int(etimes), pid))
                except ValueError:
                    pass
    # 按存活时间降序: 最老的排第一
    for k in out:
        out[k].sort(reverse=True)
    return out


def dedup(c, dry=False):
    killed = []
    for pat in DEDUP:
        name = next(n for n, p, _ in EVOLVERS if p == pat)
        pids = c.get(name) or []
        if len(pids) <= 1:
            continue
        keep = pids[0][1]
        for _, pid in pids[1:]:
            if not dry:
                intel("kill %s" % pid, timeout=20)
            killed.append((name, pid, keep))
    return killed


def main():
    dry = "--dry-run" in sys.argv
    as_json = "--json" in sys.argv
    rep = {"t": time.time(), "t_str": time.strftime("%Y-%m-%d %H:%M:%S"), "dry": dry, "steps": {}}

    if not intel_ok():
        rep["ok"] = False
        rep["why"] = "550C(Intel) 不可达 (18822 隧道)"
        print("⚠️ 550C 不可达: 18822 隧道断 (systemctl restart zmax-orin-intel-fwd)")
        return 2

    c = counts()
    rep["steps"]["counts_before"] = {k: len(v) for k, v in c.items()}

    killed = dedup(c, dry)
    rep["steps"]["dedup_killed"] = killed
    if killed and not dry:
        time.sleep(1)
        c = counts()

    # 保活: symmetry 缺了就补(命令行是它自己的历史口径); 其余交给既有 while 循环
    started = []
    if not c.get("symmetry") and not dry:
        for name, pat, cmd in EVOLVERS:
            if pat == "symmetry_evolve.py" and cmd:
                intel(cmd, timeout=30)
                started.append("symmetry")
        time.sleep(2)
        c = counts()
    rep["steps"]["started"] = started
    rep["steps"]["counts_after"] = {k: len(v) for k, v in c.items()}

    # 550A 侧进化: 有界步数训几何分支(有真实帧才跑)
    a = sh([VENV, os.path.join(REPO, "tools", "hjepa_mr_train_550a.py"), "--steps", "120"],
           timeout=600)
    ok_a = "__RESULT__" in (a.stdout or "")
    rep["steps"]["550a_train_ok"] = ok_a
    if ok_a:
        try:
            rep["steps"]["550a_result"] = json.loads((a.stdout or "").split("__RESULT__", 1)[1])
        except Exception:                                                       # noqa: BLE001
            pass
    else:
        rep["steps"]["550a_train_err"] = (a.stdout or a.stderr or "")[-300:]

    # 同步: 拉 550C 最优 → 采纳(只在真更强时)
    p = sh(["/usr/bin/python3", os.path.join(REPO, "tools", "pull_symmetry_params.py")], timeout=120)
    rep["steps"]["adopt_out"] = (p.stdout or "").strip()[-400:]
    rep["steps"]["adopt_rc"] = p.returncode

    rep["ok"] = bool(ok_a) and p.returncode == 0
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE + ".tmp", "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
        os.replace(STATE + ".tmp", STATE)
    except Exception:                                                           # noqa: BLE001
        pass

    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print("进化同步 %s" % rep["t_str"])
        print("  550C 进化器: %s" % rep["steps"]["counts_after"])
        if killed:
            print("  归并重复实例: %s" % killed)
        if started:
            print("  补拉: %s" % started)
        print("  550A 训练: %s" % ("OK" if ok_a else "FAIL " + str(rep['steps'].get('550a_train_err'))[:120]))
        print("  采纳: %s" % rep["steps"]["adopt_out"].splitlines()[-1] if rep["steps"]["adopt_out"] else "  采纳: -")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
