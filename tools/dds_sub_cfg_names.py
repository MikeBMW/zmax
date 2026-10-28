#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧮 订阅 zmax/ss_cfg_names —— 主参数节点「已加载的配置名称」(字符串, 5s 周期)

老倪 2026-10-14: 「那主参数节点, 需要发出 加载的配置名称的 topic, 字符串就可以, 周期可以是5秒」

载荷 (唯一依据 = 画布节点 n_calib_mani 的 params.cfg_entries / cfg_loaded_at):
  names     已加载配置名称, 以 " · " 连接的一整串 (不含路径/哈希/计数)
  loaded_at 主参数节点上次真加载的时刻 (供判帧龄; 节点记录陈旧时 note 里会写明)
  source    名称的唯一依据位置 · note 说明

用法:
  venvs/dds-venv/bin/python tools/dds_sub_cfg_names.py --seconds 14   # 收 2~3 条 (5s 一条)
  venvs/dds-venv/bin/python tools/dds_sub_cfg_names.py --json --n 2   # 判据用 (机器可读)
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
    n = Node("ss_cfg_names_sub")
    n.sub("ss_cfg_names")
    print("📡 订阅 zmax/ss_cfg_names … (5s 一条, 等第一条)")
    got, t0, last, ts_list = 0, time.time(), None, []
    while time.time() - t0 < a.seconds:
        for m in (n.take("ss_cfg_names", timeout=2.0) or []):
            ts = float(getattr(m, "ts", 0.0) or 0.0)
            if last is not None and abs(ts - last) < 1e-9:
                continue                       # DDS latch 会重复给同一条 ⇒ 只认新 ts
            last = ts
            ts_list.append(ts)
            got += 1
            if a.json:
                print(json.dumps({"ts": ts, "names": m.names, "loaded_at": m.loaded_at,
                                  "source": m.source, "note": m.note}, ensure_ascii=False))
            else:
                print("── 第 %d 条 ts=%.2f" % (got, ts))
                print("   配置名称: %s" % (m.names or "(空)"))
                if m.loaded_at:
                    print("   加载时刻: %s" % m.loaded_at)
                if m.source:
                    print("   唯一依据: %s" % m.source)
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
