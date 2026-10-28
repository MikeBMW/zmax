#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧮 订阅 zmax/ss_engine —— 流形引擎**常驻周期回路**的每周期输出

老倪 2026-10-14: 「常驻循环在周期性调，由状态空间工程调用，流形引擎是全系统的核心，
怎么只是调用一次呢？改」

判读口径:
  · cycle 单调递增  ⇒ 回路**真在按周期跑** (停住/掉线立刻看出来)
  · provider       ⇒ 状态源: traj(状态空间工程轨迹唯一依据) / state_file(外部实时源)
  · traj_idx/traj_n/replay ⇒ 吃到轨迹第几帧 (走完一圈标 replay=1)
  · calib          ⇒ 标定来源 (标定文件 / 现场拟合 / 未标定占位) —— 不夸大
  · hom_mode/gain/veto ⇒ 内稳态层当时的状态
  · M/inertia      ⇒ 主参数 M 与是否二阶(有惯性)演化 (唯一依据 config/calib/zmax_manifold.json)

用法:
  venvs/dds-venv/bin/python tools/dds_sub_ss_engine.py --seconds 6      # 看 ~50 帧 + 实测周期
  venvs/dds-venv/bin/python tools/dds_sub_ss_engine.py --json --n 5     # 判据用 (机器可读)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dds"))
from zmax_node import Node                                             # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--n", type=int, default=0, help="收到 N 条即退出 (0 = 按时长)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    n = Node("ss_engine_sub")
    n.sub("ss_engine")
    print("📡 订阅 zmax/ss_engine … (等第一条: 需要 tools/ss_engine_loop.py 在跑)")
    got, t0, last, ts_list, cycles = 0, time.time(), None, [], []
    while time.time() - t0 < a.seconds:
        for m in (n.take("ss_engine", timeout=2.0) or []):
            ts = float(getattr(m, "ts", 0.0) or 0.0)
            c = int(getattr(m, "cycle", 0) or 0)
            if last is not None and (abs(ts - last) < 1e-9 or c == (cycles[-1] if cycles else -1)):
                continue                                # DDS latch/重复投递 ⇒ 只认新的 cycle
            last, _ = ts, ts_list.append(ts)
            cycles.append(c)
            got += 1
            if a.json:
                print(json.dumps({"ts": ts, "cycle": c, "hz": m.hz, "step_ms": m.step_ms,
                                  "provider": m.provider, "traj_at": m.traj_at, "idx": m.traj_idx,
                                  "n": m.traj_n, "replay": m.replay, "M": m.M, "inertia": m.inertia,
                                  "calib": m.calib, "task_id": m.task_id, "project": m.project,
                                  "phi": m.phi, "grad_norm": m.grad_norm, "action_norm": m.action_norm,
                                  "hom_mode": m.hom_mode, "hom_gain": m.hom_gain, "note": m.note},
                                 ensure_ascii=False))
            else:
                print("── 第 %d 条 · 周期 #%d · ts=%.2f" % (got, c, ts))
                print("   状态源: %s · 轨迹 %s 第 %d/%d 帧%s"
                      % (m.provider or "?", m.traj_at or "?", m.traj_idx + 1, m.traj_n,
                         " (回放)" if m.replay else ""))
                print("   Φ=%+.4f · ‖∇Φ‖=%.2f · ‖a‖=%.3f · step %.2fms · 标定: %s"
                      % (m.phi, m.grad_norm, m.action_norm, m.step_ms, m.calib or "?"))
                print("   M=%.4f%s · 任务 %s · 工程 %s · 内稳态 %s(gain %.2f)%s"
                      % (m.M, " (惯性)" if m.inertia else "", m.task_id or "?", m.project or "?",
                         m.hom_mode or "-", m.hom_gain, " ⛔veto" if m.hom_veto else ""))
                if m.note:
                    print("   note: %s" % m.note)
        if a.n and got >= a.n:
            break
    if len(ts_list) >= 2:
        gaps = [ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1)]
        dcs = [cycles[i + 1] - cycles[i] for i in range(len(cycles) - 1)]
        print("周期实测: 时间间隔 中位 %.3fs / 最大 %.3fs · cycle 步长 中位 %d / 最大 %d · 共 %d 条"
              % (sorted(gaps)[len(gaps) // 2], max(gaps), sorted(dcs)[len(dcs) // 2], max(dcs), got))
    else:
        print("共收到 %d 条 (%.1fs)" % (got, time.time() - t0))
    return 0 if got else 4


if __name__ == "__main__":
    raise SystemExit(main())
