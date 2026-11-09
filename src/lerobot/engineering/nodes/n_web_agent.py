# -*- coding: utf-8 -*-
"""n_web_agent — 节点实现正文 (文件名 = 画布节点: n_web_agent)。

从 nodes/library.py 迁出 (2026-11-10 06:38)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_web_agent   ·   registry key: n_web_agent
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _SS_DIR,
    _WA_CACHE,
    os,
    time,
)

def node_web_agent(ctx):
    """🌐 Web 智能体桥 · 远程提示词 — 拉取 web agent 提示词 → **只读功能白名单**派发 → 回执

    真源: src/lerobot/policies/left_right/state_space/web_agent_bridge.py::WebAgentBridge
    通道: ECS 中转 /api/relay/agent/{prompt,reply,status} (游标式 append-only jsonl, 只读幂等)
    红线 (老倪 2026-09-25): 提示词命中动作类关键词 → 拒答 + 记审计; 本节点**不下发任何机械臂动作**
    可调功能 (能力语义): help/status/canvas/reports/memory/skills/sim/net/aoi/robot_read/feishu
    """
    log = ctx.get("log")
    try:
        import sys as _s
        if _SS_DIR not in _s.path:
            _s.path.insert(0, _SS_DIR)
        # 🚦 2026-11-01: 每拍 poll_once(timeout=8) 会在链路慢时把整圈吃掉 (py-spy 实测停在 urlopen)
        #    ⇒ 常驻循环里按节拍轮询 (ZMAX_WEBAGENT_EVERY_S, 默认 10s), 超时压到 2s。
        _now = time.time()
        _in_loop = bool(os.environ.get("ZMAX_CANVAS_HZ"))
        _every = float(os.environ.get("ZMAX_WEBAGENT_EVERY_S") or (10.0 if _in_loop else 0.0))
        if _now - _WA_CACHE["t"] < _every:
            return True
        _WA_CACHE["t"] = _now
        from web_agent_bridge import WebAgentBridge
        b = WebAgentBridge()
        if log:
            log("🌐 Web 智能体桥: 轮询 ECS 中转 /agent/prompt → 只读功能派发 → 回执")
        r = b.poll_once(timeout=float(os.environ.get("ZMAX_WEBAGENT_TIMEOUT_S") or 2.0))
        items = r.get("processed") or []
        if log:
            log(f"  ← 本轮处理 {len(items)} 条 (游标={r.get('cursor')} · 队列待处理 {r.get('pending', 0)})")
            for it in items[:6]:
                log(f"    #{it.get('seq')} [{it.get('func')}] {'✅' if it.get('ok') else '🚫'} {str(it.get('text'))[:70]}")
            if not items:
                log("  (无新提示词 — 桥已就绪; web 侧 POST /api/relay/agent/prompt 即达)")
        return bool(r.get("ok", True))
    except Exception as e:                                            # noqa: BLE001
        if log:
            log(f"❌ Web 智能体桥执行失败: {type(e).__name__}: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_web_agent
