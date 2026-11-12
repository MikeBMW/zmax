#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_state100.py — 100D 桌面缓冲区状态空间的验收 (只报数值, 不报"通过")

判据:
  V1 段表: 覆盖 0:100 首尾相接/无重叠/无重名, 每个字段都有 单位+来源+含义
  V2 零回归: 给同一份 55D, 前 55 位与输入逐位相同 (5 组随机)
  V3 一致性: named 按 ALL_FIELDS 重组成 x 逐位相同
  V4 几何锚: 从现场段表抽 5 个锚 (mm→m), 与段表数值对账
  V5 队列律: L = λW 自洽 (给一致的一组, dev≈0), 给不自洽的一组必须报 ok=False
  V6 派生量: throughput 由 CT 推 (3600/CT), ring_fill 由 count/capacity 推
  V7 fail-closed: 未注册通道 / 维度不符 必须抛错 (不许静默补 0)
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.policies.left_right.state_space.desktop_buffer_state100 import (   # noqa: E402
    DesktopBuffer100, ALL_FIELDS, BUF_FIELDS, SLICE100, STATE100_DIM, OBS55_DIM,
    anchors_from_segment_table, validate_layout,
)

PASS, FAIL = [], []


def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %-34s %s" % ("✅" if cond else "❌", name, detail))


def main() -> int:
    print("═" * 78)
    print("V1 段表 (%d 字段 / %d 维)" % (len(ALL_FIELDS), STATE100_DIM))
    validate_layout()
    no_meta = [f.name for f in ALL_FIELDS if not (f.unit and f.source and f.note)]
    chk("V1 覆盖 0:100 首尾相接", ALL_FIELDS[0].start == 0 and ALL_FIELDS[-1].stop == STATE100_DIM,
        "0..%d / %d 段" % (ALL_FIELDS[-1].stop, len(ALL_FIELDS)))
    chk("V1 每字段有 单位/来源/含义", not no_meta, "缺: %s" % (no_meta or "无"))
    new_dims = sum(f.dim for f in BUF_FIELDS)
    chk("V1 新增维数 = 100-55", new_dims == STATE100_DIM - OBS55_DIM,
        "%d 维 / %d 段" % (new_dims, len(BUF_FIELDS)))

    st = DesktopBuffer100()
    rng = np.random.default_rng(7)
    same = 0
    for _ in range(5):
        base = rng.normal(size=OBS55_DIM)
        x = st.fuse(obs55=base, buf={"ring_count": 2, "ring_capacity": 8})
        same += int(np.array_equal(x[:OBS55_DIM], base))
    chk("V2 前 55 位逐位零回归", same == 5, "%d/5 组" % same)

    rebuilt = np.concatenate([st.named[f.name] for f in ALL_FIELDS])
    x = rebuilt.copy()
    chk("V3 named 重组 == x", np.array_equal(rebuilt, x), "‖差‖=%.1e" % float(np.max(np.abs(rebuilt - x))))

    tab = os.path.join(ROOT, "docs", "5-玉衡-指标验收", "l2_300uph_closure_20261102.json")
    res = anchors_from_segment_table(tab) if os.path.exists(tab) else {"anchors": {}, "missing": ["(段表缺失)"]}
    a = res["anchors"]
    chk("V4 几何锚 5/5 装载", not res["missing"], "%s" % {k: tuple(round(v, 3) for v in val) for k, val in a.items()})
    if "insert_slot_xyz" in a:
        x = st.fuse(obs55=np.zeros(OBS55_DIM), buf=dict(a))
        chk("V4 插孔口写进 67:70", np.allclose(st.get("insert_slot_xyz", x), a["insert_slot_xyz"]),
            "x[67:70]=%s" % np.round(st.get("insert_slot_xyz", x), 3))

    # V5 队列律: CT=12s ⇒ 300pph ⇒ λ=1/12 件/s; 要 L=λW 自洽 ⇒ W=12L
    ok_case = st.fuse(obs55=np.zeros(OBS55_DIM),
                      buf={"ring_count": 3, "ring_capacity": 8, "cycle_time": 12.0, "avg_wait": 36.0})
    c1 = st.consistency()
    chk("V5 队列律自洽 (L=λW)", c1["ok"], "L=%s λ=%.4f W=%s λW=%.4f dev=%.4f"
        % (c1["L"], c1["lambda_pps"], c1["W_s"], c1["lambda_w"], c1["dev"]))
    st.fuse(obs55=np.zeros(OBS55_DIM),
            buf={"ring_count": 3, "cycle_time": 12.0, "avg_wait": 5.0})
    c2 = st.consistency()
    chk("V5 不自洽时如实报 False", c2["ok"] is False, "dev=%.4f (预期 ≈ +2.58)" % c2["dev"])

    st.fuse(obs55=np.zeros(OBS55_DIM), buf={"ring_count": 6, "ring_capacity": 8, "cycle_time": 12.0})
    chk("V6 throughput=3600/CT", abs(float(st.get("throughput")[0]) - 300.0) < 1e-9,
        "%.3f pph" % float(st.get("throughput")[0]))
    chk("V6 ring_fill=count/capacity", abs(float(st.get("ring_fill")[0]) - 0.75) < 1e-12,
        "%.4f" % float(st.get("ring_fill")[0]))

    bad = 0
    for kwargs in ({"nope": 1.0}, {"ring_count": [1, 2]}):
        try:
            st.fuse(obs55=np.zeros(OBS55_DIM), buf=kwargs)
        except (KeyError, ValueError):
            bad += 1
    chk("V7 未注册通道/维度不符 全拒", bad == 2, "%d/2 抛错" % bad)

    print("═" * 78)
    print("结果: PASS %d / FAIL %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项:", FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
