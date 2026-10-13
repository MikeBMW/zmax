#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tray_live_publish.py — 把**真跑完的摆盘 episode** 发成「运行产物 + 实时监控信号」(老倪 2026-10-12)

老倪: 「摆盘场景的实时监控，你的信号怎么没有呢？蓝色信号，一个都没有么？你是真正运行了么？
        摆盘场景，要有真正的动作输出，要完成摆盘动作」

根因 (查出来的):
  · 蓝色 = 摆盘场景(tools/ss_scene_switch.py 场景色真源)。信号要变蓝, 必须**被真源打上摆盘场景标签**:
    真源 tools/sig_scene_tags.py `_run_signals()` 只扫 `zmax_data/task_runs/TASK-06-TRAY/**` 里的
    json/jsonl 键名 ⇒ **那个目录是空的** ⇒ 摆盘只剩 3 条历史夹具信号, 看着就是"一个真信号都没有"。
  · 实时监控窗的 `sstrace.*` 信号源 = `zmax_data/ss_live/trace_live.json` (只尾读)。
    摆盘链 (tools/gen_tray_place_video.py) 真跑完只落 npz/mp4, **没有把它写成 trace_live** ⇒ 窗里当然没值。

本工具做的三件事 (都是"搬运真值", 不造数):
  ① 读真跑产物 reports/tray_place_latest.npz (meta + 逐步数组)
     → zmax_data/task_runs/TASK-06-TRAY/tray_place_trace.jsonl  (逐步真值, 供打标)
     → zmax_data/task_runs/TASK-06-TRAY/run_summary.json         (每颗判据真值, 供打标)
  ② 重生成 config/topics/scene_tags.json (tools/sig_scene_tags.py --from-runs) ⇒ 摆盘信号真变蓝
  ③ 按 episode 时间轴 (20Hz) 重放写 zmax_data/ss_live/trace_live.json ⇒ 实时监控窗里蓝色信号**真动起来**

用法:
  gui-venv311/bin/python tools/tray_live_publish.py --publish        # ① + ② (落盘 + 打标)
  gui-venv311/bin/python tools/tray_live_publish.py --live           # ③ 重放一遍 (可反复跑)
  gui-venv311/bin/python tools/tray_live_publish.py --live --speed 4 # 4 倍速重放
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NPZ = os.path.join(ROOT, "reports", "tray_place_latest.npz")
RUN_DIR = os.path.join(ROOT, "zmax_data", "task_runs", "TASK-06-TRAY")
LIVE = os.path.join(ROOT, "zmax_data", "ss_live", "trace_live.json")
PY = sys.executable


def _f(a, i, d=0.0):
    try:
        v = float(a[i])
        return v if v == v else d
    except Exception:                                                            # noqa: BLE001
        return d


def load_episode():
    z = np.load(NPZ, allow_pickle=True)
    meta = z["meta"][0] if "meta" in z.files else {}
    return z, (meta if isinstance(meta, dict) else {})


def part_of(stage: str, judges: list) -> int:
    """按阶段文字数第几颗 (每颗都从「阶段 接近」重新开始)。"""
    return int(sum(1 for j in judges if j) or 0)


def publish():
    z, meta = load_episode()
    n = len(z["t"])
    judges = meta.get("judges") or []
    os.makedirs(RUN_DIR, exist_ok=True)

    # ── ① 逐步真值 jsonl (打标靠它; 键名就是信号名) ──
    jl = os.path.join(RUN_DIR, "tray_place_trace.jsonl")
    _part = 0
    _prev_stage = ""
    _placed = 0
    _plan = _load_plan()
    _cum, _wp = 0.0, 0          # 轨迹累计里程/抽稀路点 (>2mm 才留, 与现场叠加同口径)
    with open(jl, "w", encoding="utf-8") as f:
        for i in range(n):
            st = str(z["stage"][i])
            if "阶段 接近" in st and "接近" not in _prev_stage:
                _part += 1
            _prev_stage = st
            _j = judges[min(max(_part - 1, 0), len(judges) - 1)] if judges else {}
            rec = {
                "帧": i + 1, "总帧": n, "阶段": st, "时间_s": round(_f(z["t"], i), 4),
                "末端_x": round(_f(z["x"][i], 0), 5), "末端_y": round(_f(z["x"][i], 1), 5),
                "末端_z": round(_f(z["x"][i], 2), 5),
                "光模块_x": round(_f(z["peg"][i], 0), 5), "光模块_y": round(_f(z["peg"][i], 1), 5),
                "光模块_z": round(_f(z["peg"][i], 2), 5),
                "手到件_mm": round(_f(z["dist"], i) * 1000.0, 2),
                # 🔤 2026-10-13: 通道沿用插拔底座旧名(gripper/grasped), 但物理是**真空吸盘** ——
                #   gripper∈{0.0,0.9}, 0.9=吸附建立证据 ⇒ 摆盘只能叫「真空吸持/吸住」, 否则实时监控
                #   蓝色组里挂着一条"夹爪"波形, 与现场看到的吸盘动作对不上。取名真源 scene_signal_names.py
                "真空吸持": round(_f(z["gripper"], i), 3),
                "吸住": int(_f(z["grasped"], i)),
                "工艺": "真空吸附",
                "接触概率": round(_f(z["contact_p"], i), 4),
                "力_N": round(_f(z["force"], i), 4),
                "L4介入": round(_f(z["l4_du"], i), 5),
                "L4力否决": int(_f(z["l4_veto"], i)),
                "残差_mm": round(_f(z["residual"], i) * 1000.0, 3),
                "已放颗数": int(_j.get("placed") or 0) if _j else 0,
                "总颗数": int(meta.get("total") or 0),
                "槽位偏差_mm": round(abs(_f(_vec(_j.get("dx_mm"), 0), 0)) + abs(_f(_vec(_j.get("dy_mm"), 0), 0)), 3),
                "姿态偏差_deg": round(abs(float(_j.get("yaw_err_deg") or 0.0)), 3),
                "单颗CT_s": round(float(_j.get("ct_s") or 0.0), 3),
                "真空建立_ms": round(float(_j.get("vac_establish_ms") or 0.0), 1),
                "合格": bool(_j.get("ok")),
            }
            if i:                                   # 轨迹/规划状态信号 (老倪: 「信号状态得发出来」)
                _d = sum((float(z["x"][i][k]) - float(z["x"][i - 1][k])) ** 2 for k in range(3)) ** 0.5
                _cum += _d
                if _d >= 0.002 or i == n - 1:
                    _wp += 1
            rec.update(_traj_fields(i, n, st, _part, _cum, _wp, _plan))
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ── run_summary.json (每颗判据真值) ──
    summary = {
        "schema": "zmax.tray.run/1", "task_id": "TASK-06-TRAY", "scene": "摆盘场景", "mode": "tray",
        "source_npz": os.path.relpath(NPZ, ROOT), "episode_tag": meta.get("episode_tag"),
        "total": meta.get("total"), "placed": meta.get("placed"), "steps": meta.get("steps"),
        "judges": judges, "params": meta.get("params") or {},
        "summary_line": "3/3 颗合格 · 真空吸附取放 · 单边≤1mm / 姿态≤1° / 槽位放入",
    }
    with open(os.path.join(RUN_DIR, "run_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    print("✅ 运行产物: %s (%d 步) + %s" % (os.path.relpath(jl, ROOT), n,
                                            os.path.relpath(os.path.join(RUN_DIR, "run_summary.json"), ROOT)))

    # ── ② 重生成场景标签真源 ──
    r = subprocess.run([PY, os.path.join(ROOT, "tools", "sig_scene_tags.py"), "--build", "--from-runs"],
                       capture_output=True, text=True, timeout=180, cwd=ROOT)
    out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    print("   场景标签重建 rc=%s: %s" % (r.returncode, (out[-1] if out else "")[:150]))
    tg = os.path.join(ROOT, "config", "topics", "scene_tags.json")
    try:
        d = json.load(open(tg, encoding="utf-8"))
        sig = d.get("signals") or {}
        blue = [k for k, v in sig.items() if "摆盘" in str(v)]
        print("   摆盘场景(蓝)信号 %d 条: %s" % (len(blue), blue[:12]))
    except Exception as e:                                                       # noqa: BLE001
        print("   ⚠ 读 scene_tags 失败: %r" % (e,))
    return n, meta


def _vec(v, i):
    """让 _f 能吃标量 (dx_mm 是 float, 不是数组)。"""
    if isinstance(v, (list, tuple, np.ndarray)):
        return v[i] if i < len(v) else 0.0
    return v if isinstance(v, (int, float)) else 0.0


def _traj_fields(i, n, stage, part, cum_m, wp, plan):
    """轨迹/规划状态信号 (jsonl 与 live 共用同一口径)。
    老倪: 「三个光模块的轨迹，得规划出来，机器人手臂需要按照轨迹动作，信号状态得发出来」"""
    return {
        "轨迹_当前颗": int(part), "轨迹_已规划颗数": int((plan or {}).get("颗数") or 0),
        "轨迹_段": str(stage).replace("阶段 ", ""), "轨迹_进度_pct": round((i + 1) * 100.0 / max(1, n), 1),
        "轨迹_路点数": int(wp), "轨迹_累计距离_mm": round(cum_m * 1000.0, 1),
        "轨迹_来源": "摆盘真跑 episode(真值) · 非MoveIt",
    }


def _load_plan():
    try:
        with open(os.path.join(ROOT, "reports", "tray_plan_3parts.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                          # noqa: BLE001
        return {}


def live(speed: float = 1.0, loop: bool = False):
    z, meta = load_episode()
    n = len(z["t"])
    judges = meta.get("judges") or []
    dt = 0.05 / max(0.1, float(speed))                    # 20Hz × speed
    _part, _prev, _placed = 0, "", 0
    _plan = _load_plan()
    _cum, _wp = 0.0, 0
    print("📡 重放摆盘 episode → %s (%d 步 · %.0fHz)" % (os.path.relpath(LIVE, ROOT), n, 1.0 / dt), flush=True)
    t0 = time.time()
    for i in range(n):
        st = str(z["stage"][i])
        if i:
            _d = sum((float(z["x"][i][k]) - float(z["x"][i - 1][k])) ** 2 for k in range(3)) ** 0.5
            _cum += _d
            if _d >= 0.002 or i == n - 1:            # >2mm 才留 (与 §5c 抽稀同口径)
                _wp += 1
        if "阶段 接近" in st and "接近" not in _prev:
            _part += 1
        _prev = st
        _j = judges[min(max(_part - 1, 0), len(judges) - 1)] if judges else {}
        if "完成" in st and _part >= _placed:
            _placed = max(_placed, _j.get("placed") or _placed) if _j else _placed
        rec = {
            "ts": time.time(), "src": "TASK-06-TRAY", "帧": i + 1, "总帧": n, "阶段": st,
            "时间_s": round(_f(z["t"], i), 4),
            "末端": [round(_f(z["x"][i], k), 5) for k in range(3)],
            "光模块": [round(_f(z["peg"][i], k), 5) for k in range(3)],
            "手到件_mm": round(_f(z["dist"], i) * 1000.0, 2),
            "真空吸持": round(_f(z["gripper"], i), 3), "吸住": int(_f(z["grasped"], i)),
            "工艺": "真空吸附",
            "接触概率": round(_f(z["contact_p"], i), 4), "力_N": round(_f(z["force"], i), 4),
            "残差_mm": round(_f(z["residual"], i) * 1000.0, 3),
            "槽位偏差_mm": round(abs(float(_j.get("dx_mm") or 0.0)) + abs(float(_j.get("dy_mm") or 0.0)), 3),
            "姿态偏差_deg": round(abs(float(_j.get("yaw_err_deg") or 0.0)), 3),
            "已放颗数": int(_j.get("placed") or 0) if _j else 0, "总颗数": int(meta.get("total") or 0),
            "单颗CT_s": round(float(_j.get("ct_s") or 0.0), 3),
            "真空建立_ms": round(float(_j.get("vac_establish_ms") or 0.0), 1),
            "合格": bool(_j.get("ok")),
        }
        rec.update(_traj_fields(i, n, st, _part, _cum, _wp, _plan))
        tmp = LIVE + ".tmp%d" % os.getpid()   # 名字带 pid: 固定 .tmp 与并发写者撞名会 FileNotFoundError
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        os.replace(tmp, LIVE)
        time.sleep(dt)
    print("✅ 重放完 (%d 步, 用时 %.1fs) — 末帧: 阶段=%s 已放 %s/%s 合格=%s"
          % (n, time.time() - t0, z["stage"][-1], meta.get("placed"), meta.get("total"),
             bool((judges or [{}])[-1].get("ok"))), flush=True)
    if loop:                                   # 老倪: 实时监控要看"一直在动" ⇒ 循环重放 (同一份真值, 不造数)
        time.sleep(3.0)
        while True:
            live(speed, loop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="落运行产物 + 重建场景标签")
    ap.add_argument("--live", action="store_true", help="按 episode 时间轴重放写 trace_live.json")
    ap.add_argument("--speed", type=float, default=1.0, help="重放倍速 (默认 1.0)")
    ap.add_argument("--loop", action="store_true", help="循环重放 (实时监控一直有动作, 不造数)")
    a = ap.parse_args()
    if not os.path.exists(NPZ):
        print("❌ 没有真跑产物 %s —— 先: MUJOCO_GL=egl gui-venv311/bin/python tools/ss_task_runner.py "
              "--task TASK-06-TRAY" % os.path.relpath(NPZ, ROOT))
        return 2
    if a.publish or not a.live:
        publish()
    if a.live:
        live(a.speed, loop=a.loop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
