#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""debug_55d_output.py — 55D 统一状态向量的「实际输出」调试驱动器

老倪 2026-11-13: 「定义一个断点, 停在 55D 的输出 return, 我看看实际的输出」

断点位置 (源码绝对路径 + 行号):
    /home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/unified_state55.py
    UnifiedState55D.fuse()  末尾 `return x` 前一行 (breakpoint(), 由 ZMAX_DEBUG_55D=1 控制)

用法:
    · VSCode: 打开上面那个文件, F5 选「🧪 断点 · 55D 输出」→ 停住后看变量 x / v / t / e
    · 命令行: ZMAX_DEBUG_55D=1 python tools/debug_55d_output.py      (会掉进 pdb)
    · 只看数不停: python tools/debug_55d_output.py --no-break

它跑三种真实口径, 每次都会进 fuse():
    ① 实况帧 — 从在役 state jsonl 最后一行取 tcp / tcp_quat (真值), 其余通道无来源则 0 并在输出里标明
    ② CAD 几何夹具 — 光模块头 (0.10,0.51,0.03) / 孔位 (-0.28,0.684,0.129) (与 verify_su2_layers 同源)
    ③ 满通道 — 额外喂 温度 36.4 / 关节电流 (验证 12 维扩展走的是"有名有姓"的通道)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.policies.left_right.state_space.unified_state55 import (   # noqa: E402
    UnifiedState55D, SLICE, OBS55_DIM, EXTRA_SEGMENTS,
)

LIVE_STATE = os.path.join(ROOT, "zmax_data", "ss_live", "state_20261112.jsonl")


def _quat_to_rot9(q):
    """四元数 (w,x,y,z) → 行优先 3x3 展平的 9 维 (接在 [24:33] 的 TCP 旋转段)。"""
    q = np.asarray(q, dtype=float).ravel()
    if q.size == 4:
        n = np.linalg.norm(q)
        q = q / n if n > 1e-9 else np.array([1.0, 0, 0, 0])
    w, x, y, z = q
    r = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])
    return r.ravel()


def live_visual39():
    """实况口径: 从在役 state jsonl 最后一行取 tcp / tcp_quat → 填 39D 里有的段。"""
    v = np.zeros(39, dtype=float)
    live = []
    if not os.path.exists(LIVE_STATE):
        return v, live, "state jsonl 不存在"
    last = None
    with open(LIVE_STATE, "rb") as f:                     # 文件大 (84MB): 只读尾部 8KB
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 8192))
        tail = f.read().decode("utf-8", "ignore").strip().splitlines()
    for ln in reversed(tail):
        if ln.startswith("{"):
            try:
                last = json.loads(ln)
                break
            except Exception:                              # noqa: BLE001
                continue
    if not last:
        return v, live, "尾部无完整 JSON 行"
    tcp = last.get("tcp")
    if isinstance(tcp, (list, tuple)) and len(tcp) >= 3:
        v[0:3] = np.asarray(tcp[:3], float)
        live.append("tcp_p[0:3]")
    q = last.get("tcp_quat")
    if isinstance(q, (list, tuple)) and len(q) == 4:
        v[24:33] = _quat_to_rot9(q)
        live.append("TCP旋转[24:33]")
    # 🔴 实测这行 jsonl 里 robot_status 是**字符串**(JSON 套 JSON), 关节在顶层 jpos/jvel
    j = last.get("jpos")
    if isinstance(j, (list, tuple)) and len(j) >= 6:
        v[12:18] = np.asarray(j[:6], float)
        live.append("关节角[12:18]")
    jv = last.get("jvel")
    if isinstance(jv, (list, tuple)) and len(jv) >= 6:
        v[18:24] = np.asarray(jv[:6], float)
        live.append("关节速[18:24]")
    return v, live, "state_20261112.jsonl 最后一行"


def cad_visual39():
    """CAD 几何夹具: 光模块头 / 孔位 (与 tools/verify_su2_layers.py 同一组常数)。"""
    v = np.zeros(39, dtype=float)
    v[0:3] = (0.10, 0.51, 0.03)          # tcp_p
    v[3] = 1.0                            # 夹爪标量 (夹紧)
    v[4:7] = (0.10, 0.51, 0.03)           # 工件 xyz (光模块)
    v[7:10] = (0.0, 0.0, 0.0)             # 相对位移
    v[24:33] = _quat_to_rot9((1, 0, 0, 0))# TCP 旋转 = 单位
    v[33:36] = (-0.28, 0.684, 0.129)      # 目标位
    v[36:39] = (-0.28, 0.684, 0.129)      # 孔位
    return v


def show(tag, x, us):
    print("\n===== %s =====" % tag)
    print("  return x  →  shape=%s dtype=%s  ‖x‖=%.6f" % (x.shape, x.dtype, float(np.linalg.norm(x))))
    print("  非零维: %s" % [int(i) for i in np.nonzero(np.abs(x) > 1e-12)[0]])
    for seg in ("tcp_p", "grip_scalar", "peg_xyz", "hole_xyz", "grasp", "contact"):
        if seg in SLICE:
            s = SLICE[seg]
            print("    [%2d:%2d] %-16s %s" % (s.start, s.stop, seg,
                                              np.array2string(x[s], precision=4, max_line_width=200)))
    print("  按名取几何误差 peg−hole = %s" % np.array2string(
        us.get("peg_xyz", x) - us.get("hole_xyz", x), precision=4))
    print("  参数化后 12 维扩展 (43:55) 非零通道: %s"
          % [s.name for s in EXTRA_SEGMENTS if np.any(np.abs(x[s.start:s.stop]) > 1e-12)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-break", action="store_true", help="不设断点 (只打印数字)")
    ap.add_argument("--once", action="store_true", help="只跑第 ① 种口径")
    a = ap.parse_args()
    if a.no_break:
        os.environ.pop("ZMAX_DEBUG_55D", None)
    else:
        os.environ["ZMAX_DEBUG_55D"] = "1"

    us = UnifiedState55D()

    v_live, live_ch, src = live_visual39()
    print("① 实况帧来源: %s · 有真值的段: %s" % (src, live_ch or "无"))
    x1 = us.fuse(v_live, np.zeros(4))
    show("① 实况帧 (tactile=0: 现场无触觉通道)", x1, us)
    if a.once:
        return 0

    v_cad = cad_visual39()
    x2 = us.fuse(v_cad, np.array([1.0, 1.0, 0.0, 0.0]))
    show("② CAD 几何夹具 (pegged 在位)", x2, us)

    x3 = us.fuse(v_cad, np.array([1.0, 0.0, 0.0, 0.0]),
                 extra={"temperature": 36.4})
    show("③ 满通道 (触觉 grasp + 温度 36.4)", x3, us)

    print("\n结论: 前 43 维 = 39 视觉本体 + 4 触觉 (老口径逐位不变); 43:55 = 12 维预留, 只在显式给 extra 时非零。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
