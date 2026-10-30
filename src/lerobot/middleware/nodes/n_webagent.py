# -*- coding: utf-8 -*-
"""🌐 Web 智能体桥 · 远程提示词  ·  节点 n_web_agent

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← n_eng_mem
    out out1  → n_dsvl

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.n_web_agent.<port>

实现绑定: registry key=`n_web_agent` · src/lerobot/policies/left_right/state_space/web_agent_bridge.py:class WebAgentBridge (dispatch/poll_once/watch)
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'n_web_agent'
NAME = '🌐 Web 智能体桥 · 远程提示词'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'n_web_agent'
SOURCE = 'src/lerobot/policies/left_right/state_space/web_agent_bridge.py'
SOURCE_SYMBOL = 'class WebAgentBridge (dispatch/poll_once/watch)'
PARAMS = {'state_space': True, 'web_agent': True, 'readonly': True, 'transport': 'ECS 中转 /api/relay/agent/{prompt,reply,status} (游标式 append-only jsonl, 只读幂等)', 'poll_s': 5, 'endpoints': {'web→本机': 'POST /api/relay/agent/prompt {text} → 本机 5s 轮询 GET /api/relay/agent/prompt?after=N', '本机→web': 'POST /api/relay/agent/reply → web GET /api/relay/agent/reply?after=N'}, 'funcs': ['help', 'status', 'canvas', 'reports', 'memory', 'skills', 'sim', 'net', 'aoi', 'robot_read', 'feishu'], 'redline': '只读白名单: 提示词命中动作类关键词(插入/抓取/夹爪/移动/拍照/示教…) → 拒答+记审计, 不转发', 'desc': '[L5 人机在环] web 上的 agent 用**自然语言提示词**远程调用状态空间的**只读功能**(状态/画布/报告/记忆/技能/仿真自检/网络/AOI 只读判决/真机只读信号/飞书通知), 并把执行结果回执到 web; 动作类提示词一律拒答 (老倪红线: 不动真机)。画布侧: 入=工程记忆能力清单, 出=提示词意图 → L5 场景理解(DeepSeek); 回执不经画布(中转副作用)。', 'source': 'src/lerobot/policies/left_right/state_space/web_agent_bridge.py', 'source_symbol': 'class WebAgentBridge (dispatch/poll_once/watch)'}

# 计算面开关: False = 只走数据面(直通 outN←inN), 不自动执行实现
PURE = False
LAST_STATUS = ""


def manifest():
    """给画布/面板: 这个节点的输入输出与实现位置。"""
    return {
        "id": NODE_ID, "name": NAME, "layer": LAYER, "exec_mode": EXEC_MODE,
        "ports_in": list(PORTS_IN), "ports_out": list(PORTS_OUT),
        "impl_key": IMPL_KEY, "source": SOURCE, "source_symbol": SOURCE_SYMBOL,
        "pure": PURE,
    }


def _passthrough(ctx):
    """默认数据面: out1←in1, out2←in2 … (端口序号对齐); 缺输入 → None。"""
    outs = {}
    for i, op in enumerate(PORTS_OUT):
        ip = PORTS_IN[i] if i < len(PORTS_IN) else None
        outs[op] = (ctx.get(ip) or {}).get("value") if ip else None
    return outs


def compute_n_webagent(ctx):
    """一个周期: ctx 来自总线 → 返回要发回总线的输出。

    PURE=False 时只做直通 (数据面), 不调用真实现 —— 避免未验证/未授权的节点被自动执行。
    """
    global LAST_STATUS
    if not PURE:
        LAST_STATUS = "直通 (PURE=False: 只走数据面)"
        return _passthrough(ctx)
    try:
        from lerobot.engineering import registry as _reg
        info = _reg.get(IMPL_KEY) or {}
        fn = info.get("fn")
        if not callable(fn):
            LAST_STATUS = "直通 (实现未注册: %s)" % IMPL_KEY
            return _passthrough(ctx)
        # 🔴 2026-10-29: 实现层需要知道"自己是哪个节点" —— 同一实现服务多个节点时靠这个分派
        #   (如 node_ss_mani 同时服务 ssmani_c 接触流形 / ssmani_p 性能流形, 只看 ctx["name"])。
        #   原来 ctx 里只有端口 (in1→{"value":…}), 常驻循环里实现拿到 name="" ⇒ 直接 return False。
        #   这里补元信息: 键名不与端口冲突 (端口是 inN/outN), 且不参与 _passthrough 取数。
        _mctx = dict(ctx)
        _mctx.setdefault("name", NAME)
        _mctx.setdefault("params", dict(PARAMS))
        _mctx.setdefault("id", NODE_ID)
        _mctx.setdefault("_node", {"id": NODE_ID, "name": NAME, "params": dict(PARAMS),
                                   "ports_in": list(PORTS_IN), "ports_out": list(PORTS_OUT)})
        try:
            res = fn(_mctx)                     # 约定: 接 ctx 的实现
        except TypeError:
            res = fn()                          # 老实现: 无参
        if isinstance(res, dict):
            LAST_STATUS = "实现执行"
            _out = {k: v for k, v in res.items() if k in PORTS_OUT}
            if not _out and PORTS_OUT:
                # 实现返回的是**业务结果字典**(键是 M/ok/progress 这类, 不是端口名)
                # ⇒ 整块当首端口的值发出去, 不能过滤成空 dict 把数据丢掉
                # (2026-10-29: 流形引擎族就是这样, 原来 out 恒为空, 下游永远拿不到)
                _out = {PORTS_OUT[0]: res}
            return _out
        LAST_STATUS = "实现返回非 dict → 直通"
        return _passthrough(ctx)
    except Exception as e:                                          # noqa: BLE001
        LAST_STATUS = "实现异常(%s: %s) → 直通" % (type(e).__name__, e)
        return _passthrough(ctx)


# 🔎 2026-10-31 老倪「Call Stack 要能看出是哪个画布节点」: 真名是 compute_n_webagent (帧名可见),
#   中间件接口名仍叫 compute (Node.compute 找 module.compute, 别名保持兼容)。
compute = compute_n_webagent
