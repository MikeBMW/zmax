# -*- coding: utf-8 -*-
"""状态空间节点基类 —— 每个 node 的"输入输出代码"都在这里收口。

一个 Node 实例 = 画布上的一个模块:
    spec         端口/参数/实现绑定 (来自工程 JSON)
    module       生成出来的节点模块 (src/lerobot/middleware/nodes/*.py) —— 可打开、可改
    step()       ① 从**总线**取输入 ② 交给模块的 compute(ctx) ③ 结果发回**总线**

数据面 (总线) 与计算面 (compute) 分离:
    * 数据面永远通: 输入没到也能跑 (值=None+age), 输出一定发 (带 status)
    * 计算面默认 **直通/不自动执行实现**: 会动设备的节点 (exec_mode=act) 与
      未逐个验证过口径的节点不许在无人授权时跑, 只有模块里 ``PURE = True`` 才会调用真实现。
      这是老倪的"未证明提升不得进默认档"在节点级的口径。
"""
from __future__ import annotations

import importlib
import time

from .bus import topic as _topic


class Node:
    def __init__(self, spec, bus, module=None):
        self.spec = spec
        self.bus = bus
        self.module = module or self._load_module()
        self.params = dict(spec.params or {})
        self.dst_map = {}          # out_port → [(下游节点id, 下游输入口)]  ← 工程连线即路由表
        self.last_status = ""
        self.last_trace = {}

    # ── 装配 ──────────────────────────────────────────────────────────
    def _load_module(self):
        """导入生成出来的节点模块 (missing 不炸: 用内置直通, 并在 status 里写明)。"""
        name = "lerobot.middleware.nodes.%s" % self.spec.module_name
        try:
            return importlib.import_module(name)
        except Exception as e:                                        # noqa: BLE001
            self.last_status = "模块缺失: %s (%s)" % (name, e)
            return None

    def topic(self, port):
        return _topic(self.spec.id, port)

    # ── 输入 / 输出 ───────────────────────────────────────────────────
    def pull(self):
        """从总线取输入: {port: {"value":..., "age_s":..., "fresh":bool}}"""
        out = {}
        now = time.time()
        for p in self.spec.inputs:
            v, ts = self.bus.latest(self.topic(p))
            age = (now - ts) if ts else -1.0
            out[p] = {"value": v, "age_s": round(age, 3), "fresh": bool(ts and age <= 5.0)}
        return out

    def push(self, outs):
        """发到总线: ① 本节点输出话题 ② 按工程连线转发到下游节点的输入话题。

        ② 是"输入到 DDS 总线"的落地 —— 每条连线上都有一个**真实话题**(下游的 in 口),
        所以外部既能看到上游输出, 也能直接对下游输入注入(等价于上游发了一帧)。
        """
        sent, routed = {}, 0
        for p, v in (outs or {}).items():
            if p not in self.spec.outputs:
                continue                       # 模块不许往未声明端口写
            sent[p] = self.bus.publish(self.topic(p), v)
            for dst_id, dst_port in self.dst_map.get(p, []):
                if self.bus.publish(_topic(dst_id, dst_port), v):
                    routed += 1
        self.last_routed = routed
        return sent

    # ── 计算 (模块可覆盖) ─────────────────────────────────────────────
    def compute(self, ctx):
        if self.module is not None and hasattr(self.module, "compute"):
            try:
                outs = self.module.compute(ctx)
                if isinstance(outs, dict):
                    self.last_status = getattr(self.module, "LAST_STATUS", "compute")
                    return outs
                self.last_status = "compute 返回非 dict → 直通"
            except Exception as e:                                    # noqa: BLE001
                self.last_status = "compute 异常(%s: %s) → 直通" % (type(e).__name__, e)
        else:
            self.last_status = self.last_status or "无模块 → 直通"
        return self._passthrough(ctx)

    def _passthrough(self, ctx):
        """默认数据面: out1←in1, out2←in2 … (端口序号对齐); 缺输入发 None。"""
        outs = {}
        for i, op in enumerate(self.spec.outputs):
            ip = self.spec.inputs[i] if i < len(self.spec.inputs) else None
            item = ctx.get(ip) if ip else None
            outs[op] = (item or {}).get("value")
        return outs

    def step(self):
        """一个周期: 取数 → 计算 → 发数。返回可打印的 trace。"""
        t0 = time.time()
        ctx = self.pull()
        outs = self.compute(ctx)
        sent = self.push(outs)
        tr = {
            "id": self.spec.id, "name": self.spec.name, "layer": self.spec.layer,
            "in": {k: v["value"] for k, v in ctx.items()},
            "in_age": {k: v["age_s"] for k, v in ctx.items()},
            "out": outs, "sent": sent,
            "status": self.last_status, "mode": self.spec.exec_mode,
            "ms": round((time.time() - t0) * 1000.0, 2),
        }
        self.last_trace = tr
        return tr

    # ── 给界面 / 右键用 ───────────────────────────────────────────────
    def manifest(self):
        m = self.spec.manifest()
        try:
            m["module_file"] = (self.module.__file__ if self.module is not None else "")
        except Exception:                                             # noqa: BLE001
            m["module_file"] = ""
        return m
