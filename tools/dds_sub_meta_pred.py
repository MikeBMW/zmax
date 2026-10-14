#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧾 订阅 zmax/ss_meta_pred —— **元任务预测值** (输入=流形引擎驱动扭矩)

老倪 2026-10-14: 「流形引擎要预测每个元任务，将元任务预测的topic，放到信号分析」

载荷 (真源 = zmax_data/ss_live/meta_pred.json, 由 tools/ss_meta_predict.py 现算):
  ts_pred/scene      预测生成时刻 · 场景
  n_meta/n_cand      参与打分元任务数 / 候选总数
  top_ids/top_scores top-k 功能ID 与得分 (一一对应)
  input_src/ok/age   输入真源 (驱动扭矩 tap) · 是否新鲜 · 帧龄
  trained/frozen     是否已训练头 / 是否恒定输入降级 (如实标注, 不假装有预测力)

用法:
  venvs/dds-venv/bin/python tools/dds_sub_meta_pred.py --seconds 20
  venvs/dds-venv/bin/python tools/dds_sub_meta_pred.py --json --n 1
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
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--n", type=int, default=0, help="收到 N 条即退出 (0=按时长)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    n = Node("ss_meta_pred_sub")
    n.sub("ss_meta_pred")
    print("📡 订阅 zmax/ss_meta_pred … (5s 一条, 等第一条)")
    got, t0, last = 0, time.time(), None
    while time.time() - t0 < a.seconds:
        for m in (n.take("ss_meta_pred", timeout=2.0) or []):
            ts = float(getattr(m, "ts", 0.0) or 0.0)
            if last is not None and abs(ts - last) < 1e-9:
                continue                        # DDS latch 重复给同一条 ⇒ 只认新 ts
            last = ts
            got += 1
            d = {"ts": ts, "ts_pred": float(getattr(m, "ts_pred", 0.0) or 0.0),
                 "scene": m.scene, "n_meta": int(m.n_meta), "n_cand": int(m.n_cand),
                 "top_ids": m.top_ids, "top_scores": m.top_scores,
                 "input_src": m.input_src, "input_ok": int(m.input_ok),
                 "input_age_s": float(m.input_age_s), "method": m.method,
                 "trained": int(m.trained), "frozen": int(m.frozen), "note": m.note}
            if a.json:
                print(json.dumps(d, ensure_ascii=False))
            else:
                age = (time.time() - d["ts_pred"]) if d["ts_pred"] else -1
                print("── 第 %d 条 ts=%.2f · 预测帧龄 %.1fs" % (got, ts, age))
                print("   场景: %s · 元任务 %d 个 · 候选 %d" % (d["scene"] or "—", d["n_meta"], d["n_cand"]))
                print("   top: %s" % (d["top_ids"] or "—"))
                print("   得分: %s" % (d["top_scores"] or "—"))
                print("   输入: %s (ok=%d · 帧龄 %.2fs) · 方法 %s"
                      % (d["input_src"] or "—", d["input_ok"], d["input_age_s"], d["method"] or "—"))
                print("   状态: trained=%d frozen=%d %s" % (d["trained"], d["frozen"], ("· " + d["note"]) if d["note"] else ""))
        if a.n and got >= a.n:
            break
    print("共收到 %d 条 (%.1fs)" % (got, time.time() - t0))
    return 0 if got else 4


if __name__ == "__main__":
    raise SystemExit(main())
