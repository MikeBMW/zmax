# -*- coding: utf-8 -*-
"""intact — 节点实现正文 (文件名 = 画布节点: intact)。

从 nodes/library.py 迁出 (2026-11-10 06:38)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_intact   ·   registry key: intact
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _intact_service,
    _intact_skill_ctx,
    _paths,
)

def node_intact(ctx):
    """🎯 INTACT 策略 (L4) — 零搜索 意图→动作 (**数据源直接接入 metaworld**)

    老倪 2026-09-13: "将 INTACT 接入到 L4 层 … INTACT 代码迁移到 src/lerobot 的 policies 文件夹 …
    数据源直接接入 metaworld, 输出接一个 decoder, 再进 L3"。
      · 策略实现 = src/lerobot/policies/intact/ (modeling_intact.py · IntactPolicy)
      · 桥       = src/lerobot/policies/intact/runtime/model_adapter.py (跨 venv 子进程 → INTACT-JEPA venv)
      · 数据源   = metaworld 真环境 (MT1 peg-insert-side-v3, 真渲染帧 224² + 39D 现场读)
      · 编排     = src/lerobot/policies/intact/service.py (本节点只调它, 自己不碰桥/证据)
    双击 → 真跑一步并打印诊断; 模型未就绪诚实标 trained=False (绝不返回假动作冒称成功)。

    🔴 2026-10-29 老倪「INTACT 模型用上了没有」: 原来返回 True ⇒ 壳判"非 dict" → 直通,
    下游永远拿不到东西; 而且 run_once 不传 skill_ctx ⇒ ckpt 的 skill 通道硬闸直接 raise
    ("checkpoint was trained with a skill channel (skill_dim>0) but info['skill_ctx'] was not
    provided")。现在补 skill_ctx + 返回真业务字典 (实测热态 32ms/次, 首拍加载 ~9.7s)。
    """
    log = ctx.get("log") or (lambda *a, **k: None)
    root = ctx.get("root") or _paths.REPO_ROOT
    try:
        svc = _intact_service(root)
        sk = _intact_skill_ctx(ctx, "")
        rep = svc.run_once(stage="", decode=False, skill_ctx=sk,
                           write_evidence=False, log=log)
        _d = dict(rep.diagnostics or {})
        return {"kind": "intact", "trained": bool(rep.trained), "policy": str(rep.policy),
                "chunk_shape": list(rep.chunk_shape), "source": str(rep.source),
                "ckpt": _d.get("ckpt_realpath"), "ckpt_bytes": _d.get("ckpt_bytes"),
                "skill_ctx_dim": (int(sk.size) if sk is not None else 0)}
    except Exception as e:
        log(f"❌ INTACT 节点执行失败: {type(e).__name__}: {e}")
        return {"kind": "intact", "trained": False, "err": "%s: %s" % (type(e).__name__, e)}


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_intact
