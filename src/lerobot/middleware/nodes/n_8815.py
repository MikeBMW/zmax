# -*- coding: utf-8 -*-
"""🔷 SE(3)×S1 记忆流形 · 节点 ss_se3_state  (端口契约, 不含业务逻辑)

老倪 2026-11-20: 「把昨天的 se3 服务增加到状态空间 simulink 画布上, 我可以直接打开」。

工程连线 (唯一依据 data/database/zmax/sources/canvas/state_space_obs.json):
    in  in1   ← (可空, 仅用于触发/上下文)
    out out1  → ss_phase_corr.in1  (SE(3)×S1 记忆 A–E 16 维)

真源: zmax_data/se3/se3_state_live.json (zmax-se3-state, 5Hz, 只读)
实现: src/lerobot/middleware/nodes/impl/ss_se3_state.py:node_ss_se3_state
执行口径: EXEC_MODE=ro · PURE=True (只读取真值, 不下发任何动作)
"""
from __future__ import annotations

NODE_ID = 'ss_se3_state'
NAME = '🔷 SE(3)×S1 记忆流形 (8815 · A位置ℝ³ · B轴S² · C四元数S³ · D滚转S¹ · E相位S¹ · 5Hz)'
LAYER = 'L4'
TYPE = 'model'
EXEC_MODE = 'ro'
PURE = True

PORTS_IN = ['in1']
PORTS_OUT = ['out1']

IMPL_KEY = 'ss_se3_state'
SOURCE = 'src/lerobot/middleware/nodes/impl/ss_se3_state.py'
SOURCE_SYMBOL = 'def node_ss_se3_state(ctx):'
PARAMS = {
    'desc': 'SE(3)×S1 记忆流形: A 位置ℝ³ · B 轴 S²(偏差°) · C 四元数 S³ · D 滚转 S¹ · '
            'E 弧长相位 S¹(s/arc/nearest_i) —— 昨日 se3 服务 16 维状态, 5Hz 只读',
    'source': 'zmax_data/se3/se3_state_live.json',
    'rate_hz': 5.0,
    'pure_verified': True,
}

LAST_STATUS = ''


def _passthrough(ctx):
    outs = {}
    for i, op in enumerate(PORTS_OUT):
        ip = PORTS_IN[i] if i < len(PORTS_IN) else None
        outs[op] = (ctx.get(ip) or {}).get('value') if ip else None
    return outs


def compute(ctx):
    """一个周期: 读真值 → 写 _SS_STATE → 发 out1。"""
    global LAST_STATUS
    try:
        from lerobot.engineering import registry as _reg
        if not _reg.get(IMPL_KEY):        # 自注册: 常驻循环进程未必 import 过 library
            from lerobot.middleware.nodes.impl import ss_se3_state as _impl
            _reg.register(IMPL_KEY, ["SE(3)×S1 记忆流形"], "SE(3)×S1 记忆流形 (impl)", _impl.node_ss_se3_state)
        info = _reg.get(IMPL_KEY) or {}
        fn = info.get('fn')
        if not callable(fn):
            LAST_STATUS = '直通 (实现未注册: %s)' % IMPL_KEY
            return _passthrough(ctx)
        _m = dict(ctx)
        _m.setdefault('name', NAME)
        _m.setdefault('id', NODE_ID)
        _m.setdefault('params', dict(PARAMS))
        fn(_m)
        from lerobot.middleware.nodes.impl import shared_runtime as _sr
        val = (getattr(_sr, "_SS_STATE", {}) or {}).get("se3_state")
        LAST_STATUS = '✅ SE(3)×S1 记忆已读 (只读)' if val else '⚠️ 真值缺失'
        return {'out1': val}
    except Exception as e:                                              # noqa: BLE001
        LAST_STATUS = '%s: %s' % (type(e).__name__, e)
        return _passthrough(ctx)
