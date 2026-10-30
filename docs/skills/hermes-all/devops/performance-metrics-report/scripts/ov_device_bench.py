#!/usr/bin/env python3
"""OpenVINO 同模型多设备延迟对账 (CPU / GPU / NPU)。

用法:
    OPENVINO_MODEL=/path/model.xml python3 ov_device_bench.py [--iters 20] [--warmup 3]
    python3 ov_device_bench.py /path/model.xml --iters 20

为什么要有这个: 端侧报告里「模型多快」必须落到具体设备。同一颗 IR 实测
CPU 78.9ms / NPU 2.85ms / GPU 1.61ms (差 27~49 倍), 只报一个数等于没说清在哪跑。
跑完还能顺手看出「加速器空转但 CPU 满载」这类错配。

输出: 每设备 mean/median/min/p95 + 折算 fps, 一行一台设备, 可直接贴进报告表格。
不写文件、不改模型, 只读 IR。
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

import numpy as np


def bench(core, model_path: str, device: str, iters: int, warmup: int):
    """返回 dict(device, mean_ms, med_ms, min_ms, p95_ms, fps, error)."""
    out = {"device": device, "error": None}
    try:
        model = core.compile_model(model_path, device)
        iname = model.input(0).get_any_name()
        shape = list(model.input(0).shape)
        for i, d in enumerate(shape):
            if isinstance(d, int) and d <= 0:
                shape[i] = 1
        x = np.random.rand(*shape).astype(np.float32)

        for _ in range(max(0, warmup)):
            model([x])

        ts = []
        for _ in range(iters):
            t0 = time.perf_counter()
            model([x])
            ts.append((time.perf_counter() - t0) * 1000.0)

        ts.sort()
        out.update(
            mean_ms=sum(ts) / len(ts),
            med_ms=statistics.median(ts),
            min_ms=ts[0],
            p95_ms=ts[min(len(ts) - 1, int(round(0.95 * (len(ts) - 1))))],
            fps=1000.0 / statistics.median(ts),
        )
    except Exception as e:  # 设备不可用不该让整次对账失败
        out["error"] = f"{type(e).__name__}: {e}"[:120]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", nargs="?", default=os.environ.get("OPENVINO_MODEL"))
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--devices", default="CPU,GPU,NPU")
    a = ap.parse_args()

    if not a.model or not os.path.exists(a.model):
        print(f"模型不存在: {a.model}", file=sys.stderr)
        return 2

    try:
        import openvino as ov
    except ImportError:
        print("缺 openvino —— 用装了它的那个 venv 的 python 跑本脚本", file=sys.stderr)
        return 2

    core = ov.Core()
    avail = list(core.available_devices)
    print(f"openvino {ov.__version__} | 设备 {avail}")
    print(f"模型   {a.model}")
    print(f"iter   warmup={a.warmup} timed={a.iters}\n")

    rows = []
    for dev in [d.strip() for d in a.devices.split(",") if d.strip()]:
        if not any(x == dev or x.startswith(dev) for x in avail):
            rows.append({"device": dev, "error": "设备不可用"})
            continue
        rows.append(bench(core, a.model, dev, a.iters, a.warmup))

    hdr = f"{'设备':<10}{'均值ms':>10}{'中位ms':>10}{'最快ms':>10}{'P95ms':>10}{'fps':>10}"
    print(hdr)
    print("-" * len(hdr))
    valid = []
    for r in rows:
        if r.get("error"):
            print(f"{r['device']:<10}{r['error']}")
            continue
        valid.append(r)
        print(
            f"{r['device']:<10}{r['mean_ms']:>10.2f}{r['med_ms']:>10.2f}"
            f"{r['min_ms']:>10.2f}{r['p95_ms']:>10.2f}{r['fps']:>10.0f}"
        )

    if len(valid) >= 2:
        fastest = min(valid, key=lambda r: r["med_ms"])
        slowest = max(valid, key=lambda r: r["med_ms"])
        ratio = slowest["med_ms"] / max(1e-9, fastest["med_ms"])
        print(
            f"\n最快 {fastest['device']} {fastest['med_ms']:.2f}ms · "
            f"最慢 {slowest['device']} {slowest['med_ms']:.2f}ms · 差 {ratio:.1f}x"
        )
        print("报告里每行延迟都要带设备名; 只报最慢那个会把板子写错。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
