# -*- coding: utf-8 -*-
"""ss_limit — 节点实现正文 (文件名 = 画布节点: ss_limit)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_s3   ·   registry key: ss_limit
"""

def node_ss_s3(ctx):
    """🧭 动作调制器 / 🛡 安全执行边界 —— 薄壳: 真实现在 nodes/safety_limit_impl.py::run

    端口包装: run 的每个分支返回的是扁平 dict (ok/value/why/clipped/pose_mm…),
    但画布声明了 out1→n_exec.in2(限幅后的动作) 等 11 个端口 ⇒ 原来全部读到 None
    (2026-11-10 实测)。这里统一补包装, 不改任何限幅逻辑。
    """
    from .safety_limit_impl import run as _run
    _r = _run(ctx)
    if not isinstance(_r, dict):
        return _r
    if any(str(k).startswith("out") for k in _r):
        return _r
    _b = dict(_r)
    _o = {"out1": dict(_b), "out2": dict(_b), "out3": dict(_b), "ok": _r.get("ok", True)}
    _o.update(_r)                      # 扁平原键保留, 老消费者不断
    return _o


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_s3
