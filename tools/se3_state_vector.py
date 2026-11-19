#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""se3_state_vector.py — 把 8815 看板上的 A–E 五层算法落成"状态空间可吃的状态向量"。

为什么做这件事(2026-11-19 夜, 老倪: 「把 8815 这个页面的所有算法落地到状态空间流程, 让流形引擎真正用起来」):
  8815 的看板本身是把真值投影到五个几何层上, 但它是**网页**, 状态空间图里没有节点真吃这些量。
  本脚本把同一份真值(/api/se3)按层拆成定长向量 + 命名表, 每 5Hz 写一份, 供:
    · 画布节点直接读 JSON(不改造画布接线, 先有真数据再谈接线)
    · 流形引擎 / L2 收口闸 用同一口径取 s 相位与轴误差(避免各处自己算)

五层 → 向量(layout 固定, 改版必须升 schema):
  A 位置 ∈ ℝ³       tcp_mm(3)                     底空间, 直接是 base 系毫米
  B 轴   ∈ S²       n(3) + axis_err_deg(1)        工具轴方向 + 与最近示教点轴的夹角
  C 四元数 ∈ S³     quat(4) + hopf(s2_axis 由 n 给出, 这里只存 S³ 原量)
  D 滚转 ∈ S¹       phi_deg(1) → 弧度             Hopf 纤维上的滚转
  E 相位 ∈ S¹       s(1) + s_mm(1) + nearest_i(1)  弧长相位 + 最近点编号
  元数据            age_s, ts, n_pts, L_open_mm, seam_mm, speed

用法:
  python3 tools/se3_state_vector.py --once         # 打一份到 stdout(自检)
  python3 tools/se3_state_vector.py --loop --hz 5  # 常驻写盘(默认 5Hz)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.request

API = os.environ.get("ZMAX_SE3_API", "http://127.0.0.1:8815/api/se3")
OUT_DIR = os.environ.get("ZMAX_SE3_OUT", "zmax_data/se3")
SCHEMA = "zmax.se3_state.v1"

LAYOUT = [
    ("A_pos_mm", 3),            # 0..2
    ("B_axis_S2", 3),           # 3..5
    ("B_axis_err_deg", 1),      # 6
    ("C_quat_S3", 4),           # 7..10
    ("D_roll_rad", 1),          # 11
    ("E_phase_s", 1),           # 12  归一化相位 [0,1)
    ("E_arc_mm", 1),            # 13  弧长
    ("E_nearest_i", 1),         # 14  最近示教点编号
    ("M_age_s", 1),             # 15
]                                # 合计 16 维


def fetch(timeout=3.0):
    with urllib.request.urlopen(API, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def to_vector(d):
    pos = [float(v) for v in d.get("tcp_mm", [0, 0, 0])][:3]
    nb = d.get("nearest") or {}
    n = [float(v) for v in nb.get("n", [0, 0, 0])][:3]
    quat = [float(v) for v in d.get("quat", [0, 0, 0, 1])][:4]
    phi = math.radians(float(d.get("phi_deg", 0.0)))
    s = float(nb.get("s", 0.0))
    vec = (pos + n + [float(d.get("axis_err_deg", 0.0))] + quat +
           [phi, s, float(nb.get("s_mm", 0.0)), float(nb.get("i", -1)), float(d.get("age_s", -1))])
    names = []
    for nm, k in LAYOUT:
        names += ["%s[%d]" % (nm, j) if k > 1 else nm for j in range(k)]
    assert len(vec) == len(names) == 16, (len(vec), len(names))
    return vec, names


def pack(d):
    vec, names = to_vector(d)
    nb = d.get("nearest") or {}
    sm = (d.get("summary") or {})
    return {
        "schema": SCHEMA,
        "ts": d.get("ts"),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "svc": d.get("svc"), "truth_src": d.get("truth_src"),
        # —— 分层: 每层单独一份, 画布节点按层取, 不用自己拆 ——
        "A": {"pos_mm": [round(v, 2) for v in vec[0:3]], "space": "R^3"},
        "B": {"axis_S2": [round(v, 4) for v in vec[3:6]], "axis_err_deg": round(vec[6], 2),
              "space": "S^2  方向单位向量 + 与最近示教点轴的夹角"},
        "C": {"quat_S3": [round(v, 4) for v in vec[7:11]], "space": "S^3  单位四元数",
              "hopf_note": "Hopf 映射到 S² 的纤维点即 B.axis; 滚转见 D"},
        "D": {"roll_rad": round(vec[11], 4), "roll_deg": round(math.degrees(vec[11]), 2), "space": "S^1"},
        "E": {"s": round(vec[12], 6), "arc_mm": round(vec[13], 2), "nearest_i": int(vec[14]),
              "space": "S^1  弧长相位(wrap: ds=((s2-s1+0.5) mod 1)-0.5)",
              "state": nb.get("state"), "phi_deg_note": "与 D.roll 同源, 相位环上表示"},
        "meta": {"age_s": round(vec[15], 3), "n_pts": sm.get("n"),
                 "L_open_mm": sm.get("L_open_mm"), "seam_mm": sm.get("seam_mm"),
                 "s_214": sm.get("s_214"), "dup_pairs": sm.get("dup_pairs")},
        "vector": [round(v, 4) for v in vec],
        "names": names,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--out", default=OUT_DIR)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    live = os.path.join(a.out, "se3_state_live.json")
    hist = os.path.join(a.out, "se3_state_history.jsonl")

    def tick(i=0):
        d = fetch()
        p = pack(d)
        tmp = live + ".tmp"
        with open(tmp, "w") as f:
            json.dump(p, f, ensure_ascii=False)
        os.replace(tmp, live)
        with open(hist, "a") as f:
            f.write(json.dumps({"ts": p["ts"], "vector": p["vector"], "s": p["E"]["s"],
                                "i": p["E"]["nearest_i"], "age_s": p["meta"]["age_s"]},
                               ensure_ascii=False) + "\n")
        return p

    if a.once:
        p = tick()
        print("schema", p["schema"], "· 16 维向量:", p["vector"])
        for lay in ("A", "B", "C", "D", "E"):
            print("  %s %s" % (lay, json.dumps(p[lay], ensure_ascii=False)[:150]))
        print("→ %s" % live)
        return 0
    if a.loop:
        dt = 1.0 / max(a.hz, 0.5)
        n = 0
        while True:
            try:
                tick(n)
                n += 1
            except Exception as e:                                            # noqa: BLE001
                print("warn", type(e).__name__, str(e)[:80], flush=True)
            time.sleep(dt)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
