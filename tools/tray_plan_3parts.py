#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tray_plan_3parts.py — 把真跑摆盘 episode 抽成**三颗光模块各自的轨迹** (老倪 2026-10-12)

老倪: 「三个光模块的轨迹，得规划出来，机器人手臂需要按照轨迹动作，信号状态得发出来」

口径 (别含糊):
· **轨迹来源 = 真跑 episode 的真值** (`reports/tray_place_latest.npz`, TASK-06-TRAY, 3/3 合格 · 2708 步)。
  它不是 MoveIt 规划出来的 —— MoveIt 规划链 (画布 `n_moveit` / 容器 `zmax-moveit` plan-only) 当前
  **没有为摆盘出过轨迹**, 且它的同源闸 (FK(真关节) vs 真 `/robot/tcp_pose` ≤5mm/2°) 在无真机链路时无法通过
  ⇒ 本文件落的是「真机口径的真跑轨迹」, `source` 字段如实写死, 不许冒充 MoveIt 输出。
· 逐颗分段 = 按 `stage` 的**阶段号回退**(颗与颗之间重新从「接近」开始) 或 `dist` 骤升切分; 段名取 episode 里
  的真 stage 名 (接近/对位/下降/抓取/抬起/转移/放下/完成), 不自己编。
· 路点按**空间间隔抽稀** (>2mm 才留, 上限 ~1500/颗) —— 与 §5c 同口径 (不抽稀会把渲染拖死)。
· 只读 + 只写报告/发布信号; **零运动下发**。

用法:
  python tools/tray_plan_3parts.py --plan            # 抽 3 颗轨迹 → reports/tray_plan_3parts.json
  python tools/tray_plan_3parts.py --plan --print    # 顺带打印每颗每段
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
NPZ = os.path.join(ROOT, "reports", "tray_place_latest.npz")
OUT = os.path.join(ROOT, "reports", "tray_plan_3parts.json")

# 摆盘槽位命名 (与 run_summary 里的 judges 顺序一致: 槽1/槽2/槽3)
SLOTS = {0: "槽1", 1: "槽2", 2: "槽3"}


def _col(z, k, i, d=0.0):
    try:
        a = z[k]
        v = a[i]
        if isinstance(v, str):        # 字符串列 (如 stage) 必须先于 __len__ 判, 否则被当序列拆到异常 → 全变默认值
            return str(v)
        if hasattr(v, "__len__"):
            return [float(x) for x in v]
        return float(v)
    except Exception:                                                          # noqa: BLE001
        return d


def _decimate(pts, gap=0.002, cap=1500):
    """按空间间隔抽稀 (米), 上限 cap —— 与现场轨迹叠加同口径。"""
    out = []
    for p in pts:
        if not out or (sum((a - b) ** 2 for a, b in zip(p, out[-1])) ** 0.5) >= gap:
            out.append(p)
    if len(out) > cap:
        step = len(out) / float(cap)
        out = [out[int(i * step)] for i in range(cap)] + [out[-1]]
    return out


def split_parts(z):
    """按 stage 回退切颗: 每颗 = 「接近」出现到下一颗「接近」出现之前。"""
    n = len(z["x"])
    stage = [str(_col(z, "stage", i, "")) for i in range(n)]
    starts = [i for i in range(n) if "接近" in stage[i] and (i == 0 or "接近" not in stage[i - 1])]
    if not starts:
        starts = [0]
    bounds = []
    for k, s in enumerate(starts):
        e = (starts[k + 1] - 1) if k + 1 < len(starts) else n - 1
        bounds.append((s, e))
    return bounds, stage


def segments_of(stage, s, e):
    """该颗内部的段: 连续同 stage 名的区间 (名字直接取 episode 真值)。"""
    segs = []
    cur, beg = stage[s], s
    for i in range(s + 1, e + 1):
        if stage[i] != cur:
            segs.append((cur, beg, i - 1))
            cur, beg = stage[i], i
    segs.append((cur, beg, e))
    return segs


def build(verbose=False):
    import numpy as np
    if not os.path.isfile(NPZ):
        print("✗ 没有真跑 episode: %s (先跑 tools/ss_task_runner.py --task TASK-06-TRAY)" % NPZ)
        return None
    z = np.load(NPZ, allow_pickle=True)
    meta = dict(z["meta"][0]) if "meta" in z.files else {}
    bounds, stage = split_parts(z)
    parts = []
    for k, (s, e) in enumerate(bounds):
        tcp = [_col(z, "x", i, [0, 0, 0]) for i in range(s, e + 1)]
        if isinstance(tcp[0], float):                                          # x 不是 3 维就退到 peg
            tcp = [[float(z["x"][i]), float(z["peg"][i][0]), float(z["peg"][i][1])] for i in range(s, e + 1)]
        dec = _decimate(tcp)
        segs = [{
            "段": nm, "起帧": int(b), "止帧": int(en), "帧数": int(en - b + 1),
            "路点数": len(_decimate(tcp[b - s:en - s + 1])),
            "TCP起": [round(v, 4) for v in tcp[b - s]],
            "TCP止": [round(v, 4) for v in tcp[en - s]],
            "段长_mm": 0.0,      # 真实累加在下面那段统一算 (占位别引用外部循环变量)
        } for nm, b, en in segments_of(stage, s, e)]
        # 段长按真实累加算 (上面那行只占位, 这里老实算)
        for sg in segs:
            b, en = sg["起帧"], sg["止帧"]
            L = 0.0
            for i in range(b, en):
                L += sum((tcp[i - s + 1][j] - tcp[i - s][j]) ** 2 for j in range(3)) ** 0.5
            sg["段长_mm"] = round(L * 1000.0, 2)
        j = (meta.get("judges") or [None] * 3)[k] if isinstance(meta.get("judges"), list) else None
        parts.append({
            "颗号": k + 1, "槽位": SLOTS.get(k, "槽%d" % (k + 1)),
            "起帧": int(s), "止帧": int(e), "帧数": int(e - s + 1),
            "轨迹点数": len(tcp), "抽稀后路点数": len(dec),
            "路径总长_mm": round(sum(sum((tcp[i + 1][j2] - tcp[i][j2]) ** 2 for j2 in range(3)) ** 0.5
                                 for i in range(len(tcp) - 1)) * 1000.0, 2),
            "TCP起点": [round(v, 4) for v in tcp[0]], "TCP终点": [round(v, 4) for v in tcp[-1]],
            "段": segs,
            "判据": ({kk: j.get(kk) for kk in ("dx_mm", "dy_mm", "dz_mm", "yaw_deg", "ct_s", "ok")
                      if isinstance(j, dict) and kk in j} or None),
            "路点": [[round(v, 4) for v in p] for p in dec],
        })
        if verbose:
            print("  %s(第%d颗) 帧 %d-%d · 路点 %d(抽稀 %d) · 路径 %.1fmm"
                  % (parts[-1]["槽位"], k + 1, s, e, len(tcp), len(dec), parts[-1]["路径总长_mm"]))
            for sg in segs:
                print("     %-6s 帧 %5d-%5d · 路点 %3d · %7.2fmm" % (sg["段"], sg["起帧"], sg["止帧"], sg["路点数"], sg["段长_mm"]))
    plan = {
        "source": "真跑 episode 真值 (reports/tray_place_latest.npz) — NOT MoveIt 规划输出",
        "episode": os.path.basename(NPZ), "episode_tag": meta.get("episode_tag"),
        "任务": "TASK-06-TRAY", "场景": "SCN-06-TRAY 摆盘场景(蓝)",
        "总帧": len(z["x"]), "颗数": len(parts),
        "合格": "%s/%s" % (meta.get("placed"), meta.get("total")),
        "moveit": {
            "是否 MoveIt 规划": False,
            "原因": "画布 n_moveit / 容器 zmax-moveit plan-only 未为摆盘出过轨迹; 同源闸 (FK(真关节) vs 真 /robot/tcp_pose ≤5mm/2°) 无真机链路时无法通过",
            "如何跑真 MoveIt 规划": "bash tools/moveit_live_up.sh up  +  python3 tools/moveit_plan_req.py --goal-xyz X Y Z --goal-quat qx qy qz qw --once (目标取本文件里各颗 TCP终点)",
        },
        "parts": parts,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print("✅ 3 颗轨迹规划(真值) → %s" % os.path.relpath(OUT, ROOT))
    for p in parts:
        print("   %s · 第%d颗 · 帧 %d-%d · 抽稀路点 %d · 路径 %.1fmm · 段数 %d · 判据 %s"
              % (p["槽位"], p["颗号"], p["起帧"], p["止帧"], p["抽稀后路点数"], p["路径总长_mm"],
                 len(p["段"]), ("合格" if (p["判据"] or {}).get("ok") else "-")))
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="抽 3 颗轨迹 → reports/tray_plan_3parts.json")
    ap.add_argument("--print", dest="verbose", action="store_true", help="打印每颗每段")
    a = ap.parse_args()
    if a.plan:
        build(a.verbose)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
