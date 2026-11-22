#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_demo_cycle.py — 从 ep4 原始采集里重建"老倪现场演示的那一圈", 出 8815 看板用的
demo 轨迹 + 工艺状态, **保证几何与状态索引同源同基**(之前用"缩放对齐"把段错位了)。

窗口: 默认 11:44:30 ~ 11:57:30 (演示那一圈); 之后我自己回放的动作也在 ep4 里, 必须排掉。
分段: 速度 <3mm/s 且 ≥0.6s = 停在某点; 用 30mm 半径匹配已确认点位; 中间算搬运。
纠序: 钩位(806,230,189)离插到底(819,227,190) 仅 13mm ⇒ 扫码~等待检测之间一律算"插入",
      其中最靠右的那一段才是"插入到底"。
用法: ./gui-venv311/bin/python tools/build_demo_cycle.py
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import shutil

import numpy as np

ROOT = "/home/ubuntu/zmax"
SDK = os.path.join(ROOT, "zmax_data/rokae_sdk")
EP = os.path.join(ROOT, "zmax_data/live_ds/episode_000004/data/frames.jsonl")
T0 = os.environ.get("ZMAX_DEMO_T0") or "2026-11-22T11:44:30"
T1 = os.environ.get("ZMAX_DEMO_T1") or "2026-11-22T11:57:30"
STEP_MM = float(os.environ.get("ZMAX_DEMO_STEP") or 20)

# 已确认点位 (老倪现场口述 + 真值): 名字, 位置, 颜色
LM = [
    ("槽2抓取", (649, 450, 110), "#37d0ff"),
    ("扫码", (754.6, 28.8, 271.4), "#a78bfa"),
    ("插入到底", (818.6, 226.8, 190.6), "#37d0ff"),
    ("等待检测", (720.6, 225.4, 227.9), "#f59e0b"),
    ("钩拉环解锁", (806.1, 230.1, 188.8), "#ef4444"),
    ("金手指检测1", (492.8, 134.4, 696.0), "#22d3ee"),
    ("金手指检测点2", (493.3, 129.4, 701.4), "#22d3ee"),   # 老倪 11-22: 第15步就叫"金手指检测点2"
    ("侧面点1", (415.3, -378.0, 537.3), "#84cc16"),
    ("侧面点2", (411.4, -403.4, 535.0), "#84cc16"),
    ("侧面点3", (408.0, -421.7, 535.0), "#84cc16"),
    ("侧面点4", (394.4, -372.3, 542.8), "#84cc16"),
    ("下盘放料", (648.1, -192.9, 118.1), "#3ddc84"),
    ("回初始位", (663.9, -29.3, 293.5), "#94a3b8"),
]


def main() -> int:
    t0 = dt.datetime.fromisoformat(T0).timestamp()
    t1 = dt.datetime.fromisoformat(T1).timestamp()
    rows = []
    for line in open(EP):
        r = json.loads(line)
        if t0 <= r["ts"] <= t1:
            rows.append(r)
    if len(rows) < 100:
        print("✗ 窗口内帧太少: %d (检查 T0/T1)" % len(rows))
        return 2
    P = np.array([r["pose7"][:3] for r in rows], float)
    R = np.array([r["pose7"][3:6] for r in rows], float)
    T = np.array([r["ts"] for r in rows], float)
    print("窗口 %.0f~%.0f · %d 帧" % (t0, t1, len(P)), flush=True)

    # 等弧长重采样
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    keep, nxt = [0], STEP_MM
    for i in range(1, len(s)):
        if s[i] >= nxt:
            keep.append(i)
            nxt = s[i] + STEP_MM
    if keep[-1] != len(s) - 1:
        keep.append(len(s) - 1)
    Pk, Rk, Tk = P[keep], R[keep], T[keep]
    total = float(s[-1]) if len(s) else 0.0
    print("重采样 %d 点 · 弧长 %.0fmm" % (len(Pk), total), flush=True)

    # 停留段
    sp = np.linalg.norm(np.diff(P, axis=0), axis=1) / np.maximum(np.diff(T), 1e-3)
    still = np.concatenate([sp < 3.0, [False]])
    dwell = np.zeros(len(P), bool)
    j = 0
    while j < len(P):
        if still[j]:
            k = j
            while k < len(P) and still[k]:
                k += 1
            if T[min(k, len(T) - 1)] - T[j] >= 0.6:
                dwell[j:k] = True
            j = k
        else:
            j += 1

    idx = np.searchsorted(keep, np.arange(len(P)), side="right") - 1
    states, prev_end, k = [], 0, 0
    runs = []
    while k < len(P):
        if dwell[k]:
            e = k
            while e < len(P) and dwell[e]:
                e += 1
            mid = (k + e) // 2
            best, bd = None, 1e9
            for name, q, col in LM:
                d = float(np.linalg.norm(P[mid] - np.array(q, float)))
                if d < bd:
                    best, bd = (name, col), d
            if bd <= 30.0:
                runs.append((int(idx[k]), int(idx[min(e, len(P) - 1)]), best[0], best[1], bd))
            k = e
        else:
            k += 1
    # 同名相邻合并
    merged = []
    for r in runs:
        if merged and r[2] == merged[-1][2]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], r[1]), r[2], r[3], min(merged[-1][4], r[4]))
        else:
            merged.append(list(r) and tuple(r))
    print("停留点 %d 个:" % len(merged), flush=True)
    for r in merged:
        print("   i %3d-%-3d %-14s 距点 %.1fmm" % (r[0], r[1], r[2], r[4]), flush=True)

    # 组装状态: 段间 = 搬运→下一个点
    for n, (ia, ib, name, col, _d) in enumerate(merged):
        if ia > prev_end:
            # 老倪 11-22: 「插入到底之后, 是**后退**等待检测」⇒ 去等待位的转移叫"后退"
            # 老倪 11-22: 插入到底→"后退"等待检测; 等待检测→"移动"钩拉环解锁
            # 老倪 11-22 逐段口述: 插入到底→"后退"等待检测 · 等待检测→"移动"钩拉环解锁 ·
            #                   拉环解锁之后→"移动"金手指检测点1
            # 老倪 11-22 最终口径: **所有转移段都叫"移动"**, 只有插入到底→等待位叫"后退"
            _v = ("后退→" if name == "等待检测"
                  else "移动→")
            _t = _v + name
            states.append(dict(i0=prev_end, i1=ia - 1, name=_t, color="#64748b", kind="move"))
        states.append(dict(i0=ia, i1=ib, name=name, color=col, kind="op"))
        prev_end = ib + 1
    if prev_end <= len(Pk) - 1:
        states.append(dict(i0=prev_end, i1=len(Pk) - 1, name="回初始位", color="#94a3b8", kind="move"))

    # 🔴 顺序纠正: 扫码 ~ 等待检测 之间一律是"插入"(钩位离插到底只有 13mm, 会被误匹配)
    ks = next((i for i, s in enumerate(states) if s["name"] == "扫码"), None)
    kw = next((i for i, s in enumerate(states) if s["name"] == "等待检测"), None)
    if ks is not None and kw is not None and kw > ks:
        win = [i for i in range(ks, kw) if "钩拉环" in states[i]["name"]]
        for i in win:
            ia, ib = states[i]["i0"], states[i]["i1"]
            deep = max(Pk[ia:ib + 1], key=lambda p: p[0])[0] >= 812
            states[i]["name"] = "插入到底" if (deep and ib - ia <= 2) else "搬运→插入到底"
            states[i]["color"] = "#37d0ff" if states[i]["name"] == "插入到底" else "#64748b"
            states[i]["kind"] = "op" if states[i]["name"] == "插入到底" else "move"

    # 老倪 11-22: 扫码之后一律叫"移动"(去插孔/去钩位/去金手指都是移动);
    # 只有"插入到底→等待位"那一段按他说的叫"后退"。
    _k_scan = next((i for i, s in enumerate(states) if s["name"] == "扫码"), None)
    if _k_scan is not None:
        for s in states:      # 全段统一: 搬运→ ⇒ 移动→ (等待检测 已经是"后退→", 不受影响)
            if s["name"].startswith("搬运→"):
                s["name"] = "移动→" + s["name"][len("搬运→"):]
    # 老倪 11-22: 「第一步是初始点, 不是搬运」⇒ 开头必须有"初始点"这一段(窗口起点就是初始位)
    if states and states[0]["name"] == "回初始位" and states[0]["i1"] - states[0]["i0"] <= 1:
        states[0]["name"] = "初始点"
        states[0]["color"] = "#94a3b8"
    elif states and not states[0]["name"].startswith("初始点"):
        states.insert(0, dict(i0=0, i1=0, name="初始点", color="#94a3b8", kind="op"))
    # 🔴 操作点(停顿)原来常常只占 1 帧 ⇒ 真机停在该点上时, 投影会被相邻"移动"段抢走,
    #    页面看着就是"这个点不同步"(老倪 11-22 点名 侧面点4)。给不足 3 帧的操作点补到 3 帧,
    #    帧从**前一段移动**里借, 不越界也不重叠。
    for _i, _s in enumerate(states):
        if _s["kind"] == "op" and _s["i1"] - _s["i0"] < 2:
            _need = 2 - (_s["i1"] - _s["i0"])
            if _i > 0 and (states[_i-1]["i1"] - states[_i-1]["i0"] + 1) - _need >= 1:
                states[_i-1]["i1"] -= _need
                _s["i0"] -= _need
    for s in states:
        s["i0"], s["i1"] = int(s["i0"]), int(s["i1"])
        s["n_pts"] = s["i1"] - s["i0"] + 1
        s["dur_s"] = round(float(Tk[s["i1"]] - Tk[s["i0"]]), 1)
        s["s0"] = round(float(s["i0"] / max(1, len(Pk) - 1)), 6)
        s["s1"] = round(float((s["i1"] + 1) / max(1, len(Pk))), 6)

    traj = {"n_frames": len(Pk), "dur_s": round(float(Tk[-1] - Tk[0]), 1),
            "src": "ep4 现场演示一圈 %s~%s" % (T0, T1),
            "frames": [{"i": i, "p": [round(float(v), 1) for v in Pk[i]],
                        "rpy": [round(float(v), 4) for v in Rk[i]],
                        "t": round(float(Tk[i] - Tk[0]), 3)} for i in range(len(Pk))]}
    json.dump(traj, open(os.path.join(SDK, "real_traj_joints_demo.json"), "w"), ensure_ascii=False)
    json.dump({"src": traj["src"], "n_frames": len(Pk), "len_mm": round(total, 1),
               "n_states": len(states), "states": states},
              open(os.path.join(SDK, "phase_states_demo.json"), "w"), ensure_ascii=False, indent=1)
    sv = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(Pk, axis=0), axis=1))])
    tot = float(sv[-1]) or 1.0
    # 🔴 相位表必须**带 p**(每个重采样点的 xyz): 服务端算"真机投影到轨迹哪一帧"就是用
    #    phase["frames"][j]["p"] —— 只写 s/s_mm 会让它拿到空点, 投影出"距 574 米"的鬼值。
    json.dump({"summary": {"len_mm": round(tot, 1)},
               "frames": [{"s": round(float(v / tot), 6), "s_mm": round(float(v), 1),
                           "p": [round(float(x), 1) for x in Pk[i]]} for i, v in enumerate(sv)]},
              open(os.path.join(SDK, "traj_phase_demo.json"), "w"))
    hopf = []
    for i in range(len(Pk)):
        a, b, c = Rk[i]
        ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
        M = [[ca * cb, ca * sb * sc - sa * cc, ca * sb * cc + sa * sc],
             [sa * cb, sa * sb * sc + ca * cc, sa * sb * cc - ca * sc],
             [-sb, cb * sc, cb * cc]]
        n = [M[0][2], M[1][2], M[2][2]]
        hopf.append({"i": i, "n": [round(v, 5) for v in n],
                     "phi": round(math.degrees(math.atan2(n[1], n[0])), 2)})
    json.dump({"src": "由 rpy 现算", "n_frames": len(hopf), "frames": hopf},
              open(os.path.join(SDK, "traj_hopf_demo.json"), "w"))
    shutil.copy(os.path.join(SDK, "real_traj_joints_demo.json"),
                os.path.join(ROOT, "tools/web/real_traj_joints_demo.json"))
    print("写入: %d 帧 · %d 段 · 弧长 %.0fmm" % (len(Pk), len(states), tot), flush=True)
    for n, s in enumerate(states, 1):
        print("  %2d %3d-%-3d %-16s %5.1fs" % (n, s["i0"], s["i1"], s["name"], s["dur_s"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
