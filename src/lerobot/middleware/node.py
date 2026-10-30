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
import os
import time

from .bus import topic as _topic

# 被 ZMAX_NODE_PURE_ALL 调试闸覆写成 PURE=True 的节点模块全名 (审计/取证用)
NODE_PURE_FLIPPED = set()


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
        """导入生成出来的节点模块 (missing 不炸: 用内置直通, 并在 status 里写明)。

        🔬 全局调试闸 (2026-10-31 老倪「所有画布节点都要可以进断点」):
            节点模块的铁律是 ``if not PURE: return 直通``——PURE=False 的 59 个节点
            永远不调用 IMPL_KEY 对应的真实现, 于是**断点不可能命中**。
            置 ZMAX_NODE_PURE_ALL=1 ⇒ 加载时把该模块的 PURE 覆写成 True,
            80 个节点一律走计算面, 任意节点都能断在真实现里。
            默认关闭(产线安全); 只影响本进程内节点, 不动文件、不动设备下发
            (真机动作走 l2_daemon + 8793 授权, 与这里无关)。
        """
        name = "lerobot.middleware.nodes.%s" % self.spec.module_name
        try:
            mod = importlib.import_module(name)
        except Exception as e:                                        # noqa: BLE001
            self.last_status = "模块缺失: %s (%s)" % (name, e)
            return None
        if os.environ.get("ZMAX_NODE_PURE_ALL", "0") == "1" and getattr(mod, "PURE", None) is not True:
            try:
                setattr(mod, "PURE", True)   # compute_* 每拍按模块全局读 PURE ⇒ 下一拍即生效
                NODE_PURE_FLIPPED.add(name)
            except Exception:                                        # noqa: BLE001
                pass
        return mod

    def topic(self, port):
        # 话题名以工程库 mw_topic 为准 (落库真源); 库不可用时才回落到字符串拼法
        _m = getattr(self.bus, "topic_map", None) or {}
        return _m.get((self.spec.id, port)) or _topic(self.spec.id, port)

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
    def _make_log(self):
        """给实现用的 ctx['log']: 去重(同文 30s 一次) + 前缀节点 id。

        2026-10-31: 库里的实现普遍写 `log = ctx["log"]` 然后 `if log: log(...)`,
        而 step() 的 ctx 只有端口 ⇒ 一调就 KeyError('log'), 节点看着"实现异常→直通",
        断点能进但永远在异常分支上 (实测 ss2d3d/ssmode/sstactile/swds/swintact/swvideo/swworld)。
        这里给一个安全的默认实现, 不改任何一个节点的口径。
        """
        last = {"t": 0.0, "msg": ""}

        def _log(msg):
            s = str(msg)
            now = time.time()
            if s == last["msg"] and now - last["t"] < 30.0:
                return
            last.update(t=now, msg=s)
            print("[%s] %s" % (self.spec.id, s[:300]), flush=True)

        return _log

    def compute(self, ctx):
        if self.module is not None and hasattr(self.module, "compute"):
            # 实现约定: ctx[port] = {"value",...}; "log" 是可选便捷键 (见 _make_log)
            ctx = dict(ctx)
            ctx.setdefault("log", self._make_log())
            try:
                outs = self.module.compute(ctx)
                if isinstance(outs, dict):
                    self.last_status = getattr(self.module, "LAST_STATUS", "compute")
                    return outs
                self.last_status = "compute 返回非 dict → 直通"
            except KeyError as e:                                     # noqa: BLE001
                _k = str(e).strip("'\"")
                if _k == "module":
                    # 控制台型实现 (library.py 里的老 node_*) 要运行时对象 ctx["module"] (带 on_xxx() 方法);
                    # 画布循环里没有这个对象, 也不该造假 ⇒ 如实标注, 不静默直通。
                    self.last_status = "实现是控制台型(需 ctx['module'] 运行时对象), 画布循环不提供 → 直通"
                else:
                    self.last_status = "compute 异常(KeyError: %s) → 直通" % _k
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
