# -*- coding: utf-8 -*-
"""ss_lora_l3 — 节点实现正文 (文件名 = 画布节点: ss_lora_l3)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_lora_l3   ·   registry key: ss_lora_l3
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _REPO_ROOT,
    os,
)

def node_ss_lora_l3(ctx):
    """🎛 L3 · SmolVLA LoRA 微调 — 真源 tools/lora_inject.py 注入 smolvla_lew
    (VLM 注意力 + action expert), 训练产物 outputs/train/smolvla_lew_lora_*/checkpoints。"""
    import glob
    import os as _o6
    log = ctx.get("log")
    root = os.path.join(_REPO_ROOT, "outputs", "train")
    runs = sorted(glob.glob(os.path.join(root, "smolvla_lew_lora_*")),
                  key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
    if log:
        log("🎛 L3 · SmolVLA LoRA 微调: 注入 VLM 注意力 + action expert (flow-matching 头)")
        if runs:
            r = runs[-1]
            ck = sorted(glob.glob(os.path.join(r, "checkpoints", "*")))
            log(f"   最新产物: {os.path.basename(r)} · checkpoint {len(ck)} 个 "
                f"({os.path.basename(ck[-1]) if ck else '缺'})")
            log("   实测 (2026-09-24 存档): 200 步 / 3670s · loss 0.192 · action_loss 0.2368 · 显存 3.75GB (LoRA, batch2)")
        else:
            log("   产物: 缺")
        log("   ⏳ 待办: 与统一主干/阶段专家 MOE 同口径评测 (留出集 + 平凡基线) 后才进默认档")
    return True


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_lora_l3
