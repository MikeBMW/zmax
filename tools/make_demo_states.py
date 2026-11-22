#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_demo_states.py — 把现场演示(episode_000004)的真机位姿序列做成 8815 看板可读的
demo 轨迹 + 工艺状态, 让看板显示「老倪实际走的那一遍」, 而不是旧的 239 点试验轨迹。

数据源: zmax_data/live_ds/episode_000004/data/frames.jsonl (30Hz 真值, 30k+ 帧)
做法:
  1. 取演示窗口 (从槽2抓取前到回初始位)
  2. 按弧长等间隔重采样 (~500 点, 与 239 点表同一套结构)
  3. 按"离哪个已知点位最近"给每帧打标签, 连续同类合并成状态段
输出: zmax_data/rokae_sdk/{real_traj_demo.json, phase_states_demo.json}
"""
from __future__ import annotations

import json
import os

import numpy as np

ROOT = "/home/ubuntu/zmax"
SDK = os.path.join(ROOT, "zmax_data/rokae_sdk")
SRC = os.path.join(ROOT, "zmax_data/live_ds/episode_000004/data/frames.jsonl")

LM = [  # (名字, 位置mm, 颜色) —— 现场演示里出现过的点位
    ("槽2抓取", [649, 450, 110], "#37d0ff"),
    ("扫码", [755, 29, 271], "#a78bfa"),
    ("插入到底", [819, 227, 190], "#f472b6"),
    ("等待检测", [720, 225, 228], "#fbbf24"),
    ("钩拉环解锁", [806, 230, 189], "#34d399"),
    ("金手指检测1", [493, 134, 696], "#60a5fa"),
    ("翻转→金手指检测2", [493, 129, 701], "#818cf8"),
    ("侧面点1", [415, -378, 537], "#22d3ee"),
    ("侧面点2", [411, -403, 535], "#22d3ee"),
    ("侧面点3", [408, -422, 535], "#22d3ee"),
    ("侧面点4", [394, -372, 543], "#22d3ee"),
    ("下盘放料", [648, -193, 118], "#4ade80"),
    ("回初始位", [663, -29, 292], "#94a3b8"),
]
TOL = 22.0
STEP_MM = 6.0


def main() -> int:
    rows = [json.loads(l) for l in open(SRC)]
    P = np.array([r["pose7"][:3] for r in rows])
    R = np.array([r["pose7"][3:6] for r in rows])
    T = np.array([r["ts"] for r in rows])

    # 演示窗口: 从第一次接近槽2(距 649,450,110 <30mm) 前 8 秒, 到末尾
    d2 = np.linalg.norm(P - [649, 450, 110], axis=1)
    # 🔴 锚 = 最后一次"下盘放料"(演示的收尾动作), 再往前找最近一次槽2抓取 ⇒ 正好一圈。
    #    (不能用"第一次进槽2": 文件里含前面几圈试跑, 会把两圈都框进来)
    def _last_run(mask):
        r = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(int), [0]])) != 0).reshape(-1, 2)
        return r
    _d3 = np.linalg.norm(P - np.array([648.1, -192.9, 118.1]), axis=1)
    _r3 = _last_run(_d3 < 25)
    _end = int(_r3[-1][1]) if len(_r3) else len(P) - 1
    _d2b = np.linalg.norm(P[:max(1, _end)] - np.array([649, 450, 110]), axis=1)
    _r2 = _last_run(_d2b < 30)
    k = int(_r2[-1][0]) if len(_r2) else max(0, _end - 5000)
    _end_i = min(len(P), _end + 200)
    i0 = max(0, k)          # 正好从"槽2抓取"那一拍起, 之前属上一圈, 不要
    # 🔴 之后我自己回放槽2/扫码/插入时, ep4 采集器还在录 ⇒ 必须按时间切断,
    #    只留"老倪现场演示"那一段 (默认 12:05, 我那轮回放从这里之后才开始)。
    import datetime as _dt
    _cut = os.environ.get("ZMAX_DEMO_CUT") or "2026-11-22T12:05:00"
    _cts = _dt.datetime.fromisoformat(_cut).timestamp()
    _keep = int((T <= _cts).sum())
    if 0 < _keep < len(T):
        print("[切断] 演示窗口 %d 帧, 之后 %d 帧(我的回放)丢弃" % (_keep, len(T) - _keep), flush=True)
        P, R, T = P[:_keep], R[:_keep], T[:_keep]
    if _end_i < len(T):
        P, R, T = P[:_end_i], R[:_end_i], T[:_end_i]     # 收在"下盘放料"后 20s, 不含之后待机

    # 弧长等间隔重采样
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    keep, target = [0], STEP_MM
    for i in range(1, len(P)):
        if s[i] >= target:
            keep.append(i)
            target = s[i] + STEP_MM
    if keep[-1] != len(P) - 1:
        keep.append(len(P) - 1)
    Pk, Rk, Tk = P[keep], R[keep], T[keep]
    t0 = Tk[0]

    frames = [{"i": i, "t": round(float(Tk[i] - t0), 3), "j": [], "p": [round(float(v), 1) for v in Pk[i]],
               "rpy": [round(float(v), 4) for v in Rk[i]]} for i in range(len(Pk))]

    # 打标签: 直接在**原始帧**上找"停留段"(速度<3mm/s 且 >=0.6s), 再把停留段映射到重采样索引。
    # 之前按"重采样点是否停在点位附近"判断失败: 停留期间弧长不动, 重采样根本不在停留里落点(实测 287 点
    # 只有 72 点在点位 30mm 内, 且都落在进出运动上), 结果 13 个点位只认出 5 段。
    sp = np.linalg.norm(np.diff(P, axis=0), axis=1) / np.maximum(np.diff(T), 1e-3)
    still = np.concatenate([sp < 3.0, [False]])
    runs, j = [], 0
    while j < len(P):
        if still[j]:
            k2 = j
            while k2 < len(P) and still[k2]:
                k2 += 1
            if T[min(k2, len(T) - 1)] - T[j] >= 0.6:
                runs.append((j, k2 - 1))
            j = k2
        else:
            j += 1

    def nearest_lm(p):
        best, bd = None, 1e9
        for name, q, col in LM:
            dd = float(np.linalg.norm(p - np.array(q)))
            if dd < bd:
                best, bd = (name, col), dd
        return (best, bd) if best and bd < 40.0 else ((None, None), 1e9)

    vis = []                                  # (i_start_resampled, i_end_resampled, name, color, dur)
    for a, b in runs:
        (name, col), dd = nearest_lm(P[(a + b) // 2])
        if name is None:
            continue
        ia = int(np.searchsorted(keep, a, side="right") - 1)
        ib = int(np.searchsorted(keep, b, side="right") - 1)
        ia, ib = max(0, ia), min(len(Pk) - 1, max(ib, ia))
        if ia == 0 and ib == 0:
            continue                      # 首个单帧段是重采样毛刺(演示起点), 不进状态表
        vis.append((ia, ib, name, col, round(float(T[b] - T[a]), 1)))

    states, cur_i = [], 0
    for ia, ib, name, col, dur in vis:
        if ia > cur_i:
            states.append(dict(i0=cur_i, i1=ia - 1, n_pts=ia - cur_i, name="搬运→" + name, color="#64748b",
                               kind="transfer",
                               s_mm=round(float(s[keep[ia - 1]] - s[keep[cur_i]]), 1),
                               p0=[round(float(v), 1) for v in Pk[cur_i]],
                               p1=[round(float(v), 1) for v in Pk[ia - 1]], dur_s=round(float(Tk[ia - 1] - Tk[cur_i]), 1)))
        states.append(dict(i0=ia, i1=ib, n_pts=ib - ia + 1, name=name, color=col, kind="op",
                           s_mm=round(float(s[keep[ib]] - s[keep[ia]]), 1),
                           p0=[round(float(v), 1) for v in Pk[ia]],
                           p1=[round(float(v), 1) for v in Pk[ib]], dur_s=dur))
        cur_i = ib + 1
    if cur_i < len(Pk):
        states.append(dict(i0=cur_i, i1=len(Pk) - 1, n_pts=len(Pk) - cur_i, name="回初始位", color="#94a3b8",
                           kind="transfer",
                           s_mm=round(float(s[keep[-1]] - s[keep[cur_i]]), 1),
                           p0=[round(float(v), 1) for v in Pk[cur_i]],
                           p1=[round(float(v), 1) for v in Pk[-1]], dur_s=round(float(Tk[-1] - Tk[cur_i]), 1)))

    traj = dict(n_frames=len(frames), dur_s=round(float(Tk[-1] - t0), 2),
                src="现场演示 episode_000004 (30Hz 真值, 弧长 %.0fmm 重采样)" % STEP_MM,
                frames=frames)
    st = dict(src="tools/make_demo_states.py · 按实测点位 22mm 内打标签", n_frames=len(frames),
              len_mm=round(float(s[keep[-1]]), 1), n_states=len(states), states=states)
    # 🔴 顺序纠正(老倪 11-22: 「扫码之后是插入, 你先改好」):
    #    钩位(806,230,189) 离插到底(819,227,190) 只有 13mm, 30mm 半径匹配会把"插入"
    #    误标成"钩拉环解锁" ⇒ 按**工序先后**纠正: 扫码~等待检测之间一律是插入,
    #    其中最靠右(x 最大)的那个 dwell 才是"插入到底", 其余是搬运/接近。
    _ks = next((k for k, s in enumerate(states) if s["name"] == "扫码"), None)
    _kw = next((k for k, s in enumerate(states) if s["name"] == "等待检测"), None)
    if _ks is not None and _kw is not None and _kw > _ks:
        _win = [k for k in range(_ks, _kw) if "钩拉环" in states[k]["name"]]
        if _win:
            _deep = max(_win, key=lambda k: float(Pk[states[k]["i0"]][0]))
            for k in _win:
                states[k]["name"] = "插入到底" if k == _deep else "搬运→插入"
                states[k]["color"] = "#37d0ff" if k == _deep else "#64748b"
                states[k]["kind"] = "op" if k == _deep else "move"
    # 同名相邻段合并 + 完全重复段(同一 i0/i1 同名)丢弃 —— 演示里同一位置会停两次
    _m = []
    for s in states:
        if _m and s["name"] == _m[-1]["name"] and s["i0"] <= _m[-1]["i1"] + 1:
            _m[-1]["i1"] = max(_m[-1]["i1"], s["i1"])
            _m[-1]["n_pts"] = _m[-1]["i1"] - _m[-1]["i0"] + 1
        elif _m and s["name"] == _m[-1]["name"] and s["i0"] == _m[-1]["i0"]:
            continue
        else:
            _m.append(s)
    states = _m
    json.dump(traj, open(os.path.join(SDK, "real_traj_demo.json"), "w"), ensure_ascii=False)
    json.dump(st, open(os.path.join(SDK, "phase_states_demo.json"), "w"), ensure_ascii=False, indent=1)
    print("frames %d · 总弧长 %.0fmm · 状态段 %d" % (len(frames), st["len_mm"], len(states)))
    for v in states:
        print("  %3d-%-3d %-22s %5.0fmm" % (v["i0"], v["i1"], v["name"], v["s_mm"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
