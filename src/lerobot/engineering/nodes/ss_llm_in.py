# -*- coding: utf-8 -*-
"""ss_llm_in — 节点实现正文 (文件名 = 画布节点: ss_llm_in)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_llm_in   ·   registry key: ss_llm_in
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _SS_STATE,
    _VLM,
    _ctx_params,
    _vlm_ask_async,
    _vlm_ctx,
    _vlm_frame,
)

def node_ss_llm_in(ctx):
    """📝 任务指令 — MES 工单/自然语言 + **场景图 (环境通道)** → VLM 场景理解 → 任务规划器 (planner.py)

    数据通道 (老倪 2026-09-19「增加一条从环境到本节点的数据通道, 这个节点要能看到场景」):
      in1 = 场景图: 真机最新帧 (D405 旁路同刻) 或 仿真 metaworld 渲染帧, 由 _vlm_frame() 按可用性选
      指令 = params.instruction (MES 工单 / 自然语言)
    模型 = SceneVLM: 本地 Qwen2.5-VL-3B worker (无需 key) 或 SS_VLM_URL+SS_VLM_KEY (OpenAI 兼容 API)
    输出 = _SS_STATE["scene_vlm"] (结构化场景) + _SS_STATE["llm_next_action"] (标定/操作建议) → 下游可读
    🚫 无模型时只给**规则回退摘要**并如实标注 —— 不假装有视觉理解 (老倪红线)
    """
    log = ctx.get("log")
    try:
        # 🔌 2026-10-28: 画布参数键叫 task_input(见节点参数), 代码原来只认 instruction ⇒ 填了不生效
        _cp = _ctx_params(ctx)
        ins = _cp.get("instruction") or _cp.get("task_input") or "插入光模块"
        _SS_STATE["instruction"] = ins
        img, src, meta = _vlm_frame()
        _VLM["img"] = dict({"src": src}, **meta)
        if img is None:
            if log:
                log("📝 任务指令: 「%s」 → 已下发 🧠任务规划器 (planner.py) · ⚠️ 场景图通道无数据 "
                    "(真机帧不在 / 仿真帧未采样)" % ins)
            return True
        st = _vlm_ask_async("describe", img, _vlm_ctx(ctx), log)
        if log:
            log("📝 任务指令: 「%s」 · 场景图 = %s (%s%s)" % (
                ins, meta.get("frame"), meta.get("frame_src"),
                (", 帧龄 %ss" % meta["frame_age_s"]) if meta.get("frame_age_s") is not None else ""))
            r = (st or {}).get("result") or {}
            if st.get("pending"):
                log("   🖼🧠 已把场景图发给视觉大模型 (后台线程, 不阻塞画布) — 结果下一拍打印")
            elif r.get("ok"):
                log("   → 场景理解已就绪, 已下发 🧠任务规划器 (planner.py)")
        return True
    except Exception as e:
        if log:
            log("⚠️ 任务指令处理失败: %s" % e)
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_llm_in
