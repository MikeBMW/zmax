#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_store_daemon.py — 把本机真值文件并成一份**统一信号库** (zmax_data/dataspace/signals.db)。

老倪 2026-10-17: 「Trace 窗口的 signal, 与信号分析的 signal, 都要来自统一的数据库」

链路:  zmax_data/ss_live/*.json + 其它 host_sources 文件
          └─ live_signals.topics_from_files()   (唯一的读取口径, 不做第二套解析)
               └─ src/lerobot/dataspace/signal_store.write_snapshot()   (单事务整份替换)
                    └─ signals.db   ← Trace 窗口 / 信号分析窗口 只读这个库

用法:
  ./gui-venv311/bin/python tools/signal_store_daemon.py --hz 2            # 前台
  nohup ./gui-venv311/bin/python tools/signal_store_daemon.py --hz 2 &    # 后台
单实例: 有 pidfile (zmax_data/dataspace/signal_store.pid) 且进程活着就拒绝启动。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), os.path.dirname(os.path.abspath(__file__))]
os.environ.setdefault("ZMAX_REPO", ROOT)

PID = os.path.join(ROOT, "zmax_data", "dataspace", "signal_store.pid")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=2.0, help="落库频率 (默认 2Hz)")
    ap.add_argument("--force", action="store_true", help="忽略已有实例")
    a = ap.parse_args()

    if os.path.isfile(PID) and not a.force:
        try:
            old = int(open(PID).read().strip() or 0)
        except Exception:                                                    # noqa: BLE001
            old = 0
        if old and old != os.getpid() and _alive(old):
            print(f"已有 signal_store 在跑 (pid {old}) → 退出")
            return 0
    os.makedirs(os.path.dirname(PID), exist_ok=True)
    open(PID, "w").write(str(os.getpid()))

    from lerobot.middleware import live_signals as LS
    from lerobot.dataspace import signal_store as SS
    SS.init()

    period = 1.0 / max(0.2, a.hz)
    n_cycles = 0
    last = 0.0
    print(f"📚 统一信号库: {SS.DB} · {a.hz}Hz · pid {os.getpid()}", flush=True)
    try:
        while True:
            t0 = time.time()
            try:
                snap = LS.topics_from_files()
                n = SS.write_snapshot(snap)
                n_cycles += 1
                if n_cycles % 20 == 1:
                    print(f"  #{n_cycles} 话题 {len(snap)} · 信号 {n} · "
                          f"{1000 * (time.time() - t0):.1f}ms", flush=True)
                last = time.time()
            except Exception as e:                                            # noqa: BLE001
                print(f"⚠️ 落库失败: {type(e).__name__}: {e}", flush=True)
            dt = period - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)
    except KeyboardInterrupt:
        pass
    finally:
        if last:
            print(f"停止 · 最后成功写入 {time.time() - last:.1f}s 前", flush=True)
        try:
            if open(PID).read().strip() == str(os.getpid()):
                os.remove(PID)
        except Exception:                                                     # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
