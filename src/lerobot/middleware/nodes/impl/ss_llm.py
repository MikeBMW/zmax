# -*- coding: utf-8 -*-
"""ss_llm — 节点实现正文 (文件名 = 画布节点: ss_llm)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_llm   ·   registry key: ss_llm
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _SS_DIR,
    _SS_STATE,
    _llm_context_text,
    _load_mod,
    os,
    time,
)

def node_ss_llm(ctx):
    """🧠 任务规划器 — 指令 → 技能Token序列 → 下发状态机 (慢决策, 回路外; 双击=规划演示)"""
    log = ctx.get("log")
    try:
        path = os.path.join(_SS_DIR, "planner.py")
        m = _load_mod("state_space.planner", path)          # 正常 import (断点可绑)
        p = m.TaskPlanner()
        # 🔌 2026-10-28 老倪「具体是哪个函数负责输入」: 原来只读 ctx["params"] —— 引擎里根本没有这个键
        #   (Node.step: ctx = self.pull() = {port: {value,age_s,fresh}}), 所以永远取默认「插入光模块」,
        #   上游 ssllm_in / n_vlm_llm / ss_mem_share 四条入线一条都没被消费。现在三级回落:
        #   ① 节点参数 instruction/task_input (GUI 演示可传) ② 入边 in1 (引擎真链路) ③ ssllm_in 写的共享态
        _p = ctx.get("params") or {}
        _ins_in = None
        for _port in ("in1", "in2"):
            _v = (ctx.get(_port) or {}).get("value")
            if isinstance(_v, dict):
                for _k in ("instruction", "task_input", "text", "cmd", "intent"):
                    if _v.get(_k):
                        _ins_in = str(_v[_k])
                        break
            elif isinstance(_v, str) and _v.strip():
                _ins_in = _v.strip()
            if _ins_in:
                break
        ins = (_p.get("instruction") or _p.get("task_input") or _ins_in
               or _SS_STATE.get("instruction") or "插入光模块")
        _ctx_txt = _llm_context_text()          # 场景理解 + 总装记忆上下文 (真实读, 取不到如实说)
        if log and _ctx_txt:
            log(f"   📥 规划上下文: {_ctx_txt[:200]}")
        tokens = p.plan(ins)
        names = []
        for t in tokens:
            for s in p.skills.values():
                if s["tokens"]["id"] == t:
                    names.append(s["name"])
                    break
        if log:
            log(f"🧠 任务规划器: 「{ins}」 → 技能序列 (共 {len(tokens)} 步)")
            for i, (t, nm) in enumerate(zip(tokens, names), 1):
                log(f"   {i}. {t}  {nm}")
            log(f"   📚 Token 序列已下发 🧭动作调制器 (慢决策 · 回路外, 状态机握否决权)")
        # 🔌 2026-10-28: 原来 return True ⇒ 引擎判「实现返回非 dict → 直通」, out1 永远 None,
        #   下游 sssched / ssuph 一条 token 都收不到。现在真发总线。
        _outs = {"out1": {"instruction": ins, "tokens": tokens, "names": names,
                          "n": len(tokens), "src": "TaskPlanner.plan", "t": time.time()}}
        if log:
            log(f"📤 已发 out1: {len(tokens)} 个技能 token {tokens[:4]}")
        return _outs
    except Exception as e:
        if log:
            log(f"⚠️ 任务规划器演示失败: {e}")
        return {"out1": None}


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_llm
