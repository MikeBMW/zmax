# -*- coding: utf-8 -*-
"""l5_loop — 节点实现正文 (文件名 = 画布节点: l5_loop)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_l5_loop   ·   registry key: l5_loop
"""

def node_l5_loop(module=None, log=print, **kw):
    """🧿 L5 标注→训练闭环 — 只读状态 (安全: 不在"节点逻辑"对话框里误触发长跑训练)

    真正的启动入口 = 画布 🧭 能力档位节点选 **L5** + 点 ▶运行
    (simulink_module.on_l5_annotate_train → 后台异步 subprocess
     tools/l5_annotate_train_loop.py --run)。
    真源: 标注 tools/auto_annotate.py(6 路实拍→VLM) → 监督数据
          → 训练 tools/joint_train_all.py / tools/yolo_annot_train.py
          → LoRA 合并 tools/merge_lora_ckpt.py
    状态: ~/zmax/zmax_data/l5_loop/state.json (CLI 与画布徽章同源)
    """
    import json
    p = "/home/ubuntu/zmax/zmax_data/l5_loop/state.json"
    try:
        st = json.load(open(p, encoding="utf-8"))
    except Exception as e:                                                      # noqa: BLE001
        log(f"🧿 L5 闭环: 尚无运行记录 ({p}: {type(e).__name__}) — 选 L5 档后点 ▶运行")
        return False
    log(f"🧿 L5 闭环: {st.get('status')} · 阶段 {st.get('stage')} · 完成 {st.get('stages_done')}")
    for k, v in (st.get("results") or {}).items():
        log(f"   {'✅' if v.get('ok') else '❌'} {k}: {v.get('reason') or v.get('secs')}")
    return True


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_l5_loop
