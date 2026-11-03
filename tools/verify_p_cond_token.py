#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_p_cond_token.py — p_cond 进 DiT 条件 token 的零回退判据 (不需要加载整颗模型)

判据 (缺一即不算):
  ① p_cond=None            ⇒ apply_l4_cond 输出与改造前**逐位相同**
  ② p_cond 给了但权重零初始化 ⇒ 输出仍与原输出**逐位相同** (零回退)
  ③ 权重非零 ⇒ 输出确实变化 (通道真参与前向, 不是死代码)
  ④ l4_cond=None 而 p_cond 给了 ⇒ 能单独出一个 token, 且零初始化时不扰动原 token
"""
import os
import sys

import torch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from lerobot.policies.smolvla_lew.action_head import SmolVLALewActionHead as _AH  # noqa: E402

# 只借用方法, 不构造整颗 ActionHead (它要一堆模型参数)
apply_l4 = _AH.apply_l4_cond
apply_p = _AH.apply_p_cond
ensure_p = _AH.ensure_p_cond
ensure_l4 = _AH.ensure_l4_cond


class _Stub:
    """最小替身: 只提供方法用到的属性。"""
    def __init__(self, dim=960, l4d=192):
        self.cross_attention_dim = dim
        self.future_tokens = torch.nn.Linear(4, dim, bias=False)
        self.l4_cond_proj = None
        self.l4_cond_dim = 0
        self.p_cond_proj = None
        self.p_cond_dim = 0
        ensure_l4(self, l4d, out_dim=dim)

    apply_l4_cond = apply_l4
    apply_p_cond = apply_p
    ensure_p_cond = ensure_p
    ensure_l4_cond = ensure_l4


def main() -> int:
    torch.manual_seed(0)
    B, T, D = 2, 5, 960
    toks = torch.randn(B, T, D)
    l4 = torch.randn(192)
    pc = torch.tensor([0.12, -0.34, 0.05])

    st = _Stub()
    base = st.apply_l4_cond(toks, l4)                      # 改造前的唯一路径
    a = st.apply_l4_cond(toks, l4, None)                   # ①
    b = st.apply_l4_cond(toks, l4, pc)                     # ② 零初始化
    print("① p_cond=None  逐位相同: %s" % bool(torch.equal(base, a)))
    print("② p_cond 零初始化 逐位相同: %s  (max|Δ|=%.3e)"
          % (bool(torch.equal(base, b)), float((b - base).abs().max())))

    with torch.no_grad():                                   # ③ 模拟训练后权重非零
        st.p_cond_proj.weight.normal_(0, 0.05)
    c = st.apply_l4_cond(toks, l4, pc)
    print("③ 权重非零后 输出变化: %s  (max|Δ|=%.4f)"
          % (bool(not torch.equal(base, c)), float((c - base).abs().max())))

    st2 = _Stub()                                           # ④ 无 l4_cond, 只有 p_cond
    d0 = st2.apply_l4_cond(toks, None)
    d1 = st2.apply_l4_cond(toks, None, pc)
    print("④ 仅 p_cond: token 数 %d→%d, 零初始化时原 token 不变=%s"
          % (d0.shape[1], d1.shape[1], bool(torch.equal(d0[:, :T], d1[:, :T]))))

    ok = (torch.equal(base, a) and torch.equal(base, b)
          and not torch.equal(base, c) and d1.shape[1] == T + 1
          and torch.equal(d0[:, :T], d1[:, :T]))
    print("判定: %s" % ("通过 (零回退成立, 通道可参与)" if ok else "不通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
