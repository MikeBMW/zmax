# -*- coding: utf-8 -*-
"""🌀 相空间安全通道 · 节点 ss_phase_corr  (端口契约, 不含业务逻辑)

老倪 2026-11-20: 人为轨迹在相空间里"强跨相位线" —— 电机持续注入/抽取能量 ⇒
必须用各向异性度规在相空间画出安全管道, 让跨越始终落在物理边界之内。

工程连线 (唯一依据 data/database/zmax/sources/canvas/state_space_obs.json):
    in  in1   ← ss_mani_eng (流形坐标 p / 度规 M) 与 ss_se3_state (SE(3)×S1 记忆)
    out out1  → ssintact (L4 工作安全: τ_safe / 通道判据)

实现: src/lerobot/manifold/phase_corridor.py:PhaseSpaceCorridor
      src/lerobot/middleware/nodes/impl/ss_phase_corr.py:node_ss_phase_corr
执行口径: EXEC_MODE=ro · PURE=True (只产出判据与 τ_safe, 不直接下发动作; 真动须 8793 授权)
"""
from __future__ import annotations

NODE_ID = 'ss_phase_corr'
NAME = '🌀 相空间安全通道 (SE(3)×S1 记忆 + 速度纤维 · V_phase/τ_safe · S¹ 相位门控 · 李雅普诺夫单调)'
LAYER = 'L4'
TYPE = 'model'
EXEC_MODE = 'ro'
PURE = True

PORTS_IN = ['in1']
PORTS_OUT = ['out1']

IMPL_KEY = 'ss_phase_corr'
SOURCE = 'src/lerobot/manifold/phase_corridor.py'
SOURCE_SYMBOL = 'class PhaseSpaceCorridor:'
PARAMS = {
    'desc': '相空间安全通道: z=[e_pose/tol; e_vel/vlim] · V=½‖z‖² · '
            'τ=−α·τ_lim⊙(z_pos+z_vel) · S¹ 相位门控 · α_eff=min(α,λ/2) ⇒ V̇≤−λV',
    'tol_radial_mm': 0.3,
    'tol_axial_mm': 6.0,
    'vlat_mm_s': 50.0,
    'vaxial_mm_s': 300.0,
    'epsilon': 0.30,
    'alpha': 1.5,
    'lam': 2.0,
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
    """一个周期: 取相空间样本 → 算 V/τ/门控 → 发 out1。"""
    global LAST_STATUS
    try:
        from lerobot.engineering import registry as _reg
        if not _reg.get(IMPL_KEY):        # 自注册: 常驻循环进程未必 import 过 library
            from lerobot.middleware.nodes.impl import ss_phase_corr as _impl
            _reg.register(IMPL_KEY, ["相空间安全通道"], "相空间安全通道 (impl)", _impl.node_ss_phase_corr)
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
        val = (getattr(_sr, "_SS_STATE", {}) or {}).get("phase_corr")
        LAST_STATUS = ('✅ V_phase=%.3f τ=%.2f 门控=%s' % (val.get('V_phase', 0.0), val.get('tau_norm', 0.0), val.get('gate'))
                       if val else '⚠️ 相空间样本缺失')
        return {'out1': val}
    except Exception as e:                                              # noqa: BLE001
        LAST_STATUS = '%s: %s' % (type(e).__name__, e)
        return _passthrough(ctx)
