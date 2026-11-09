# -*- coding: utf-8 -*-
"""n_dsvl — 节点实现正文 (文件名 = 画布节点: n_dsvl)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_dsvl   ·   registry key: n_dsvl
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _ctx_params,
    _vlm_ask_async,
    _vlm_brief,
    _vlm_ctx,
    _vlm_frame,
)

def node_dsvl(ctx):
    """🧿 DeepSeek-V4-Flash 视觉语言 (人机在环) — 后台线程判读当前画面, 结果写 _SS_STATE 并落盘

    数据通道: 环境帧/引擎真图/真机帧 (in1~in3) + MES 工单 (in4) → 场景判读 → 场景理解层 👁 → LLM 层。
    右键 = tools/gui/vlm_panel.py 判读结果窗口 (字段表/实时画面/历史)。
    人机在环红线: 本节点只产出『判读+建议』, 不产生任何机械臂动作指令。
    """
    log = ctx.get("log")
    try:
        ins = _ctx_params(ctx).get("instruction", "插入光模块")
        img, src, meta = _vlm_frame()
        if img is None:
            if log:
                log("🧿 DeepSeek-V4-Flash: ⚠️ 无可用画面 (真机帧不在 / 仿真帧未采样) — 不判读")
            return False
        _cx = dict(_vlm_ctx(ctx), instruction=ins)
        st = _vlm_ask_async("describe", img, _cx, log)
        if log:
            log(f"🧿 DeepSeek-V4-Flash (deepseek-flash · Vision): 画面 {meta.get('frame')} "
                f"({meta.get('frame_src')}) → 场景判读 (后台线程); 右键本节点可打开判读结果窗口")
            _sg = _cx.get("seg") or {}
            if _sg:
                log("   🧩 输入选项·开放词汇分割(SAM3): %d 实例 · 类别=%s · 选中 %s · 帧=%s%s → 已进判读上下文" % (
                    _sg.get("n_instances", 0), (_sg.get("labels") or "-"), _sg.get("n_selected"),
                    _sg.get("frame_src") or "-",
                    (" · 掩膜3D %d 组" % len(_sg.get("mask3d_base") or {})) if _sg.get("mask3d_base") else ""))
            else:
                log("   🧩 输入选项·开放词汇分割(SAM3): 本帧无 (🖼 分割节点未跑 / 结果过期) — 判读只用画面")
            r = (st or {}).get("result") or {}
            if st.get("pending"):
                log("   ⏳ 判读中 (Cold start 60~134s, 缓存命中 ~1s) — 结果下一拍显示")
            elif r.get("ok"):
                log(f"   ✅ {_vlm_brief(r.get('json'))}")
            else:
                log(f"   ⚠️ {r.get('why')}")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ DeepSeek 判读节点失败: {type(e).__name__}: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_dsvl
