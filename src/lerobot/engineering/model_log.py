# -*- coding: utf-8 -*-
"""模型加载台账 (老倪 2026-10-31: 「终端里我要看到加载每个模型的说明，到底是不是加载了」)

一行说清五件事：哪一层 · 哪个模型 · 权重从哪来 · 存在/大小 · 真加载成功没 + 耗时。
只做**记录**，不改变任何加载行为；调用方一律用 try/except 包住，台账写不出来也不许影响加载。

用法（加载点加载完成后调一次即可，同一 (layer,name,path) 只打一次）：
    from lerobot.engineering.model_log import note
    t0 = time.time(); pol = ...from_pretrained(ck); ...
    note("L3", "SmolVLA-LEW", ck, True, detail="参数量 507M · 设备 cpu", elapsed=time.time()-t0)

    note("L2", "YOLO 视觉", weights, os.path.isfile(weights), detail="缺权重 → 视觉链路会退回真值/报未检出")
"""
from __future__ import annotations

import os

_SEEN: set = set()


def _mb(path: str) -> str:
    try:
        b = os.path.getsize(path)
    except OSError:
        return "-"
    if os.path.isdir(path):
        tot = 0
        for r, _d, fs in os.walk(path):
            for f in fs:
                try:
                    tot += os.path.getsize(os.path.join(r, f))
                except OSError:
                    pass
        b = tot
    return "%.1fMB" % (b / 1e6) if b < 1e9 else "%.2fGB" % (b / 1e9)


def note(layer: str, name: str, path, ok: bool, detail: str = "", elapsed: float | None = None,
         force: bool = False) -> str:
    """打一行模型台账；返回这一行的文本（方便调用方顺手 log 到 GUI）。"""
    key = (layer, name, str(path))
    if key in _SEEN and not force:
        return ""
    _SEEN.add(key)
    p = str(path or "")
    shown = p
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if p.startswith(root):
        shown = p[len(root) + 1:]
    if len(shown) > 78:
        shown = "…" + shown[-77:]
    head = "[模型] %-3s %-16s ← %s" % (layer, name, shown)
    if p and not os.path.exists(p) and "/" in p and not p.startswith("/"):
        _exists, _size = "HF仓库id", "-"
    else:
        _exists, _size = ("是" if os.path.exists(p) else "否"), _mb(p)
    tail = " · 存在=%s · 大小=%s · %s" % (_exists, _size, "加载 OK" if ok else "未加载/失败")
    if elapsed is not None:
        tail += " · %.2fs" % elapsed
    if detail:
        tail += " · " + detail
    line = head + tail
    print(line, flush=True)
    return line


def reset() -> None:
    """测试用: 允许同一模型再打一次。"""
    _SEEN.clear()
