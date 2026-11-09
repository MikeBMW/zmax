# -*- coding: utf-8 -*-
"""intact_dec — 节点实现正文 (文件名 = 画布节点: intact_dec)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_intact_dec   ·   registry key: intact_dec
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _intact_service,
    _intact_skill_ctx,
    _paths,
)

def node_intact_dec(ctx):
    """🎯 INTACT 意图解码器 (L4 → L3) — 把 L4 的意图/潜空间解码成 L3 能吃的条件。

    老倪 2026-09-13 架构: metaworld 数据源 → INTACT 策略 (ssintact) → **本解码器** → L3。
    两路输出 (每路都带来源标注, 失败不给假值):
      A) u_ff 先验 (4D, 引擎 u 空间) —— 量纲逆运算 act×K_ACT (K_ACT 现读引擎源码), 无需标定
      B) L3 条件向量 (流形坐标)     —— 需要标定映射 models/intact_l3_map.json;
                                      未标定 → 拒绝返回并计数 (不写死映射 = 不假接入)
    L3 侧消费: 引擎 SS_L4_INTACT=1 时按权重 w 注入 (w=0 / 未设 = 与现状**逐位相同**)。
    ⚙️ 实现已下沉 policy 层: lerobot/policies/intact/service.py (IntactIntentService.run_once)
    """
    log = ctx.get("log") or (lambda *a, **k: None)
    mod = ctx.get("module")
    root = ctx.get("root") or _paths.REPO_ROOT
    try:
        svc = _intact_service(root)
        _stage = str(ctx.get("stage") or "")
        sk = _intact_skill_ctx(ctx, _stage)
        rep = svc.run_once(stage=_stage, decode=True, skill_ctx=sk,
                           write_evidence=True, log=log)
        if mod is not None:
            try:
                mod._intact_dec = rep.to_panel()
            except Exception:                                              # noqa: BLE001
                pass
        _d = dict(rep.diagnostics or {})
        _cond = rep.l4_cond
        try:
            import numpy as _np
            _cond = [round(float(x), 5) for x in _np.asarray(_cond, dtype=float).ravel()[:8]] \
                if _cond is not None else None
        except Exception:                                                  # noqa: BLE001
            _cond = None
        return {"kind": "intact_dec", "trained": bool(rep.trained), "policy": str(rep.policy),
                "u_ff": [round(float(x), 6) for x in (rep.u_ff if rep.u_ff is not None else [])],
                "u_ff_source": str(rep.u_ff_source or ""),
                "l4_cond_head8": _cond,
                "l4_cond_dim": (int(_np.asarray(rep.l4_cond).size) if rep.l4_cond is not None else 0),
                "weight": (float(rep.weight) if rep.weight is not None else 0.0),
                "reason": str(rep.reason or ""),
                "chunk_shape": list(rep.chunk_shape), "source": str(rep.source),
                "ckpt": _d.get("ckpt_realpath")}
    except Exception as e:
        log(f"❌ INTACT 解码器执行失败: {type(e).__name__}: {e}")
        return {"kind": "intact_dec", "trained": False, "err": "%s: %s" % (type(e).__name__, e)}


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_intact_dec
