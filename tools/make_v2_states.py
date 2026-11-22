#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_v2_states.py —— 为 8815「E · 相位 ∈ S¹」生成 239 点工艺状态序列(状态边界由几何定, 名字由我标)

为什么要有这个文件:
  8815 原来把「停点表」直接当状态序列用(每个停点 = 一行状态), 结果是
  #99 工作点 与 #100 插入 同坐标(819,227,190)/同弧长(1008.4mm) → 环上出现一个长度 0 的缝,
  而且行名是"落点"不是"动作段"(插入那一段其实是从 #93 压到 #99)。

  这里改成真正的**工艺段**: 每一行 = [i0,i1] 连续帧的一段动作, 边界取轨迹上的
  真实拐点(停点 / 最深退让 / 最低点 / 速度档切换), 全段首尾相接覆盖 0..238。

口径(与 239 点表 real_traj_joints_v2.json 一致):
  #0 起于初始位 → #31 抓取点停 1s → 抬到 #51 → 搬到 #64 扫码停 → 移到 #91 对位停
  → #93 对位微进停 → 15mm/s 压到 #99(工作点, 819,227,190 最深) → 退到 #114(721,225,228 最深退让)
  → 再进并下压到 #128(813,230,188 全段最低) → #128–#133 孔内 1mm 来回微调
  → #133 起 100mm/s 退到 #154 离开 → #199 废料点 → #234 回程 → #238 收在初始位。

用法:
  ./gui-venv311/bin/python tools/make_v2_states.py            # 写 zmax_data/rokae_sdk/phase_states_v2.json
  ./gui-venv311/bin/python tools/make_v2_states.py --print    # 只打印不写
"""
from __future__ import annotations

import argparse
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(REPO, "zmax_data", "rokae_sdk")
OUT = os.path.join(SDK, "phase_states_v2.json")

# (i0, i1, 名称, 颜色, 归类)
#   边界怎么来的: 停点(#31/#51/#64/#91/#93/#99/#154/#199/#234)取停点帧;
#   无停点的拐点取实测几何(#114 退让最深 / #128 全段最低 / #133 微调结束), 见文件头。
STATES = [
    # 🔴 老倪 2026-11-21 现场纠正:
    #   ①「还没到最低的抓取点就显示抬升了」→ #32(z=113, 全段最低) 单独算"抓取", 抬升从 #33 起
    #   ②「扫码就一个点, 然后才是 接近, 再对位, 顺序分开」→ #64 单独"扫码", #65–90 "接近", #91–92 "对位"
    #   ③「抬升点又早了」→ 抓取必须把最低点两边都含住(z 121→113→117, 即 #31–#33),
    #      抬升从 #34 起(z=130 已经确实在升), 光靠 #32 一个点, 最近帧一到 #33 就显示抬升 = 看着"没到底就抬了"
    (0,   30,  "接近抓取点",   "#37d0ff", "transfer"),   # 初始位 → 槽7 上方
    (31,  33,  "抓取",         "#3ddc84", "grasp"),      # 最低点窗口 #31(z121)–#32(113)–#33(117)
    (34,  50,  "抬升",         "#3ddc84", "lift"),       # #34 起 z 130→264 确认在升
    (51,  63,  "搬运到扫码位", "#37d0ff", "transfer"),   # #51 → #63
    (64,  64,  "扫码",         "#ffd166", "scan"),       # #64 (755,29,271) 就一个点
    (65,  90,  "接近",         "#37d0ff", "transfer"),   # #65 → 插口上方 #90
    (91,  92,  "对位",         "#ffb020", "align"),      # #91 对位点 / #93 对位微进 之间
    (93,  98,  "插入到底",     "#ff9f1c", "contact"),    # 15mm/s 压到 #99 = 工作点
    (99,  113, "退让",         "#a371f7", "retract"),    # 退到 #114 (721,225,228)
    # 🔴 老倪 2026-11-21 现场纠正: 「二次插入下压, 不对, 是拔出; 没有孔内微调」
    #    #114–#133 是**拔出**这一段(含最后 1mm 来回), 不是一个独立状态 ——
    #    拆成两行时, 真机在那个来回里前后抖, 高亮方框会上下跳; 合成一行就不跳了。
    (114, 133, "拔出",         "#ff9f1c", "retract"),    # #114 → #133 (X 回抽, 收尾 810→806)
    (134, 153, "退出",         "#3ddc84", "retract"),    # #134 起 100mm/s → #154 离开
    (154, 198, "送往废料点",   "#37d0ff", "transfer"),   # → #199 废料点
    (199, 233, "回程",         "#37d0ff", "transfer"),   # → #234 回程
    (234, 238, "回初始位",     "#8fa3b3", "transfer"),   # → #238 收尾
]


def build() -> dict:
    tj = json.load(open(os.path.join(SDK, "real_traj_joints_v2.json"), encoding="utf-8"))
    fr = tj["frames"]
    n = len(fr)
    P = [[c * 1000.0 for c in f["p"][:3]] for f in fr]
    s_mm, cum = [0.0], 0.0
    for a, b in zip(P, P[1:]):
        cum += sum((b[k] - a[k]) ** 2 for k in range(3)) ** 0.5
        s_mm.append(cum)

    # 覆盖性/连续性自检: 必须 0..n-1 首尾相接, 不然环上会漏一段
    assert STATES[0][0] == 0, "第一个状态必须从 #0 起"
    assert STATES[-1][1] == n - 1, f"最后一个状态必须收到 #{n-1}, 现在是 #{STATES[-1][1]}"
    for (a0, b0, *_), (a1, b1, *_) in zip(STATES, STATES[1:]):
        assert b0 + 1 == a1, f"状态不连续: #{b0} → #{a1}"

    out = []
    for i0, i1, nm, col, kind in STATES:
        seg = sum(((P[k + 1][0] - P[k][0]) ** 2 + (P[k + 1][1] - P[k][1]) ** 2 +
                   (P[k + 1][2] - P[k][2]) ** 2) ** 0.5 for k in range(i0, i1))
        out.append({"i0": i0, "i1": i1, "n_pts": i1 - i0 + 1, "name": nm, "color": col,
                    "kind": kind, "s_mm": round(seg, 1),
                    "p0": [round(v) for v in P[i0]], "p1": [round(v) for v in P[i1]]})
    return {"src": "real_traj_joints_v2.json", "n_frames": n, "len_mm": round(s_mm[-1], 1),
            "n_states": len(out), "states": out}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="show", action="store_true")
    a = ap.parse_args()
    d = build()
    if not a.show:
        json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"n_frames": d["n_frames"], "n_states": d["n_states"], "out": OUT,
                      "states": [[s["i0"], s["i1"], s["name"], s["color"]] for s in d["states"]]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
