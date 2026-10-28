#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ss_engine_loop.py — 判据: 流形引擎**常驻周期回路**真的在按周期调 step

老倪 2026-10-14: 「常驻循环在周期性调，由状态空间工程调用，流形引擎是全系统的核心，怎么只是调用一次呢？改」

判据 (全部实测, 不看声明):
  ① 常驻单元 zmax-ss-engine-loop 在跑 (systemctl is-active)
  ② cycle 单调递增 (2s 内涨 ≥ 8) ⇒ 回路**真在按周期调**
  ③ tap 最后一帧新鲜 (帧龄 < 3s) 且字段齐 (p/action/phi/M/provider/traj_n/task_id)
  ④ 每周期 step 耗时 > 0 且势场真生效 (Φ/‖∇Φ‖ 不全为 0 —— `goal_point` 设错时实测恒 0)
  ⑤ 状态源是**唯一依据** (轨迹文件在位 · obs 43 维 · src 写明来源; 无源时空转并明说)
  ⑥ 单写入器 (只有一个 ss_engine_loop 进程, 且与 pid 锁一致)
  ⑦ DDS topic zmax/ss_engine 真收到 (dds-venv 订阅 ≥2 条且 cycle 递增)
  ⑧ 由**状态空间工程**驱动: 帧里的 project/task_id 与唯一依据文件当前值一致

用法: gui-venv311/bin/python tools/verify_ss_engine_loop.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS = os.path.join(ROOT, "zmax_data", "ss_live", "engine_loop_status.json")
TAP_DIR = os.environ.get("ZMAX_SS_ENGINE_TAP_DIR") or "/dev/shm/zmax_ss_engine"
TRAJ = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "ss_traj_last.json")
BINDING = os.path.join(ROOT, "config", "ss_task_binding.json")
PROJ = os.path.join(ROOT, "data", "database", "zmax", "zmax_space.proj")
UNIT = "zmax-ss-engine-loop.service"

R = []


def chk(name: str, ok: bool, detail: str = "", fatal: bool = False) -> None:
    R.append({"check": name, "ok": bool(ok), "detail": detail})
    print("%s %-46s %s" % ("✅" if ok else "❌", name, detail[:150]))
    if fatal and not ok:
        raise SystemExit(sum(1 for x in R if not x["ok"]))


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                        # noqa: BLE001
        return d


def newest_tap():
    if not os.path.isdir(TAP_DIR):
        return None
    c = [os.path.join(TAP_DIR, f) for f in os.listdir(TAP_DIR) if f.startswith("engine_") and f.endswith(".jsonl")]
    return max(c, key=os.path.getmtime) if c else None


def last_line(p):
    try:
        with open(p, "rb") as fh:
            fh.seek(max(0, os.path.getsize(p) - 262144))
            lines = [ln for ln in fh.read().decode("utf-8", "replace").splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else None
    except Exception:                                                        # noqa: BLE001
        return None


def main() -> int:
    # ① 单元
    try:
        act = subprocess.run(["systemctl", "is-active", UNIT], capture_output=True, text=True).stdout.strip()
    except Exception as e:                                                   # noqa: BLE001
        act = "err:%s" % e
    chk("① 常驻单元 active", act == "active", "%s → %s" % (UNIT, act))

    # ② cycle 递增
    s0 = _j(STATUS, {}) or {}
    c0 = int(s0.get("cycles") or 0)
    time.sleep(2.0)
    s1 = _j(STATUS, {}) or {}
    c1 = int(s1.get("cycles") or 0)
    chk("② cycle 单调递增 (2s 涨 ≥8)", c1 - c0 >= 8, "cycles %d → %d (+%d)" % (c0, c1, c1 - c0))
    chk("② 实测频率 ≥ 8Hz", float(s1.get("hz_target") or 0) >= 8 and (c1 - c0) >= 8,
        "hz_target=%s · 2s 内 %d 周期" % (s1.get("hz_target"), c1 - c0))

    # ③ tap 新鲜 + 字段齐
    tp = newest_tap()
    d = last_line(tp) if tp else None
    age = (time.time() - os.path.getmtime(tp)) if tp else -1.0
    chk("③-1 tap 在位", bool(tp) and d is not None, "%s" % (os.path.relpath(tp, ROOT) if tp else "无"))
    chk("③-2 帧新鲜 (<3s)", age >= 0 and age < 3.0, "帧龄 %.2fs" % age)
    need = ("p", "action", "phi", "grad_norm", "M", "provider", "traj_n", "task_id", "cycle", "ms")
    miss = [k for k in need if not d or k not in d]
    chk("③-3 载荷字段齐", not miss, "缺: %s" % (miss or "无"))

    # ④ step 真跑: 耗时>0 且势场非全零 (goal_point 没设时实测 Φ≡0/∇Φ≡0)
    ms = float((d or {}).get("ms") or 0.0)
    phi = abs(float((d or {}).get("phi") or 0.0))
    gn = abs(float((d or {}).get("grad_norm") or 0.0))
    chk("④-1 每周期 step 耗时 > 0", ms > 0, "%.3f ms/步" % ms)
    phi_any = False
    if tp:
        try:                                                                 # noqa: SIM105
            with open(tp, encoding="utf-8") as fh:
                tail = fh.readlines()[-200:]
            phi_any = any(abs(float(json.loads(x).get("phi") or 0.0)) > 1e-9 for x in tail if x.strip())
        except Exception:                                                    # noqa: BLE001
            pass
    chk("④-2 势场真生效 (Φ 非恒 0)", phi_any or gn > 1e-9, "Φ=%.6f ‖∇Φ‖=%.6f" % (phi, gn))

    # ⑤ 状态源唯一依据
    tr = _j(TRAJ, {}) or {}
    obs = tr.get("obs") or []
    chk("⑤-1 轨迹唯一依据在位", bool(obs), "%s · %d 帧" % (os.path.relpath(TRAJ, ROOT), len(obs)))
    chk("⑤-2 obs 维数 = 43", bool(obs) and len(obs[0]) == 43, "dim=%s" % (len(obs[0]) if obs else "?"))
    chk("⑤-3 唯一依据写明来源", bool(tr.get("src")), str(tr.get("src"))[:90])

    # ⑥ 单写入器 (自己读 /proc/*/cmdline 数进程 —— 用 `grep ss_engine_loop` 会把**检查命令自身**
    #    也算进去 ⇒ 实测误报「进程数=4」。)
    me, dad = os.getpid(), os.getppid()
    procs = []
    for p in os.listdir("/proc"):
        if not p.isdigit() or int(p) in (me, dad):
            continue
        try:
            with open("/proc/%s/cmdline" % p, "rb") as fh:
                cl = fh.read().decode("utf-8", "replace").replace("\x00", " ")
        except Exception:                                                    # noqa: BLE001
            continue
        if "ss_engine_loop.py" in cl and " run" in cl:
            procs.append("%s:%s" % (p, cl.split("ss_engine_loop.py")[0].strip().split("/")[-1]))
    out = str(len(procs))
    pidf = os.path.join(ROOT, "zmax_data", "ss_live", "engine_loop.pid")
    pidx = ""
    try:
        pidx = open(pidf, encoding="utf-8").read().strip()
    except Exception:                                                        # noqa: BLE001
        pass
    chk("⑥ 单写入器 (1 个进程 + pid 锁)", out == "1" and bool(pidx), "进程数=%s · pid锁=%s" % (out, pidx or "无"))

    # ⑦ DDS 真收到
    dds_py = os.path.join(ROOT, "venvs", "dds-venv", "bin", "python")
    sub = os.path.join(ROOT, "tools", "dds_sub_ss_engine.py")
    frames = []
    if os.path.isfile(dds_py):
        try:
            pr = subprocess.run([dds_py, sub, "--seconds", "3", "--json"], capture_output=True, text=True, timeout=90)
            frames = [json.loads(x) for x in pr.stdout.splitlines() if x.strip().startswith("{")]
        except Exception:                                                    # noqa: BLE001
            frames = []
    cyc = [int(f.get("cycle") or 0) for f in frames]
    chk("⑦ DDS zmax/ss_engine 真收到 ≥2 条", len(frames) >= 2, "收到 %d 条" % len(frames))
    chk("⑦ cycle 在 DDS 上单调递增", len(cyc) >= 2 and all(cyc[i + 1] > cyc[i] for i in range(len(cyc) - 1)),
        "cycle %s" % (cyc[:4] or "无"))

    # ⑧ 由状态空间工程驱动 (帧里的工程/任务 == 唯一依据当前值)
    b = _j(BINDING, {}) or {}
    p = _j(PROJ, {}) or {}
    want_task = str(b.get("active_task") or "")
    want_proj = str(p.get("name") or "")
    chk("⑧ 帧内 task_id == 绑定唯一依据", str((d or {}).get("task_id") or "") == want_task,
        "帧=%s / 唯一依据=%s" % ((d or {}).get("task_id"), want_task))
    chk("⑧ 帧内 project == 工程唯一依据", str((d or {}).get("project") or "") == want_proj,
        "帧=%s / 唯一依据=%s" % ((d or {}).get("project"), want_proj))

    bad = [x for x in R if not x["ok"]]
    print("\n判据: %d/%d PASS%s" % (len(R) - len(bad), len(R),
                                    ("" if not bad else " · 未过: " + ", ".join(x["check"] for x in bad))))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
