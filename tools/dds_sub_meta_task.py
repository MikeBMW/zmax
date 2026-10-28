#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧾 订阅 zmax/ss_meta_task —— 「根据任务输出的元任务清单」(5s 周期, 主参数节点出口)

老倪 2026-10-14: 「流形引擎, 需要根据任务, 输出 元任务, 怎么搞? 是在哪个节点输出比较合理? 意图直读么?」

载荷 (唯一依据 = 任务 → 画布节点 → 功能, 由 tools/ss_meta_task.py 现算):
  task_id/task_name  活跃任务 (唯一依据 ss_task_binding.json 的 active_task)
  n / n_all          本任务元任务数 / 全量 (工程 74)
  layers / prio      层分布 (L2/L3/L4-L5/PLAT) · 优先级分布
  fn_ids             功能ID串 (前 12 个, 全量看派生器 --json 或 zmax_data/ss_live/meta_tasks.json)
  src                唯一依据 sha 摘要 (可复核)

用法:
  venvs/dds-venv/bin/python tools/dds_sub_meta_task.py --seconds 14
  venvs/dds-venv/bin/python tools/dds_sub_meta_task.py --json --n 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dds"))
from zmax_node import Node                                             # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=14.0)
    ap.add_argument("--n", type=int, default=0, help="收到 N 条即退出 (0 = 按时长)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    n = Node("ss_meta_task_sub")
    n.sub("ss_meta_task")
    print("📡 订阅 zmax/ss_meta_task … (5s 一条, 等第一条)")
    got, t0, last, ts_list = 0, time.time(), None, []
    while time.time() - t0 < a.seconds:
        for m in (n.take("ss_meta_task", timeout=2.0) or []):
            ts = float(getattr(m, "ts", 0.0) or 0.0)
            if last is not None and abs(ts - last) < 1e-9:
                continue                       # DDS latch 会重复给同一条 ⇒ 只认新 ts
            last = ts
            ts_list.append(ts)
            got += 1
            if a.json:
                print(json.dumps({"ts": ts, "task_id": m.task_id, "task_name": m.task_name,
                                  "n": int(m.n), "n_all": int(m.n_all), "layers": m.layers,
                                  "prio": m.prio, "fn_ids": m.fn_ids, "src": m.src,
                                  "note": m.note}, ensure_ascii=False))
            else:
                print("── 第 %d 条 ts=%.2f" % (got, ts))
                print("   任务: %s %s" % (m.task_id or "(空)", m.task_name or ""))
                print("   元任务: %d 个 (全量 %d) · 层 %s · 优先级 %s"
                      % (int(m.n), int(m.n_all), m.layers or "—", m.prio or "—"))
                if m.fn_ids:
                    print("   功能: %s" % m.fn_ids)
                if m.src:
                    print("   唯一依据: %s" % m.src)
                if m.note:
                    print("   note: %s" % m.note)
        if a.n and got >= a.n:
            break
    if len(ts_list) >= 2:
        gaps = ["%.1fs" % (ts_list[i + 1] - ts_list[i]) for i in range(len(ts_list) - 1)]
        print("周期实测: 相邻间隔 %s (规格 5s)" % ", ".join(gaps))
    print("共收到 %d 条 (%.1fs)" % (got, time.time() - t0))
    return 0 if got else 4


if __name__ == "__main__":
    raise SystemExit(main())
