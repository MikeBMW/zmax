# -*- coding: utf-8 -*-
"""ss_reason — 节点实现正文 (文件名 = 画布节点: ss_reason)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_reason   ·   registry key: ss_reason
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _SS_DIR,
    _load_mod,
    os,
)

def node_ss_reason(ctx):
    """🔍 异常推理器 — 连续否决/阶段卡死 → 异常分类 + 恢复建议 (双击=诊断演示)"""
    log = ctx.get("log")
    try:
        path = os.path.join(_SS_DIR, "planner.py")
        m = _load_mod("state_space.planner", path)          # 正常 import (断点可绑)
        r = m.ExceptionReasoner()
        p = ctx.get("params") or {}
        kind, advice = r.diagnose(
            stage=p.get("stage", "接近"),
            residual=float(p.get("residual", 0.0)),
            contact_p=float(p.get("contact_p", 0.5)),
            dist_h=float(p.get("dist_h", 0.05)),
            dwell_time=float(p.get("dwell_time", 0.0)),
            veto_count=int(p.get("veto_count", 0)),
            max_veto=int(p.get("max_veto", 3)))
        if log:
            log(f"🔍 异常推理器: 阶段={p.get('stage','接近')} 残差={p.get('residual',0.0)} "
                f"接触概率={p.get('contact_p',0.5)}")
            log(f"   → 诊断: {kind or '运行正常'} | {advice}")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 异常推理器演示失败: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_reason
