#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""相位连续性检查 —— 证明 SE(3) 相位从 0 单调走到 100%, 没有跳变/回退/卡住。

用法: python tools/rokae/phase_check.py <meas_*.jsonl>
读 meas 里的 "ph"(0~1 路径相位), 判四件事:
  ① 起点≈0, 终点≈1
  ② 回退次数 = 0 (ph 任一拍变小就是跳变)
  ③ 单拍最大前进量 (相对名义步长) —— 有没有"跳一大步"
  ④ 最长"卡住"时长 (ph 连续不变) —— 有没有停一下再走
"""
from __future__ import annotations

import json
import sys


def main(path: str) -> int:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:                                      # noqa: BLE001
                continue
            if isinstance(d.get("ph"), (int, float)) and isinstance(d.get("t"), (int, float)):
                rows.append((float(d["t"]), float(d["ph"])))
    if len(rows) < 10:
        print("样本不足(无 ph 字段?) n=%d" % len(rows))
        return 2
    rows.sort()
    ts = [r[0] for r in rows]
    ph = [r[1] for r in rows]
    steps = [ph[i + 1] - ph[i] for i in range(len(ph) - 1)]
    dts = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    back = [(i, steps[i]) for i in range(len(steps)) if steps[i] < -1e-9]
    holds = []
    run = 1
    for s in steps:
        if abs(s) < 1e-9:
            run += 1
        else:
            holds.append(run)
            run = 1
    holds.append(run)
    fwd = [s for s in steps if s > 0]
    fwd.sort()
    p = lambda q: fwd[min(len(fwd) - 1, int(len(fwd) * q))] if fwd else 0.0
    dur = ts[-1] - ts[0]
    print("文件 %s" % path)
    print("样本 %d · 时长 %.1fs · 名义速率 %.2f %%/s"
          % (len(rows), dur, 100.0 * (ph[-1] - ph[0]) / dur if dur > 0 else 0))
    print("相位 起点 %.4f → 终点 %.4f" % (ph[0], ph[-1]))
    print("回退次数 %d (最大回退 %.2e)" % (len(back), min([s for _, s in back]) if back else 0.0))
    print("单拍前进 p50 %.3e / p99 %.3e / max %.3e (max 出现在 t=%.1fs)"
          % (p(0.5), p(0.99), fwd[-1] if fwd else 0.0,
             ts[[i for i, s in enumerate(steps) if s == (fwd[-1] if fwd else 0)][0] + 1] if fwd else 0.0))
    print("最长卡住 %.2fs (%.0f 样) · 前进拍占比 %.1f%%"
          % (max(holds) * (sorted(dts)[len(dts) // 2] if dts else 0), max(holds),
             100.0 * len(fwd) / max(1, len(steps))))
    ok = (abs(ph[0]) < 0.02 and ph[-1] > 0.995 and not back)
    print("判定: %s" % ("连续 0→100% ✓" if ok else "不连续 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
