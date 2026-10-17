# -*- coding: utf-8 -*-
"""🧲 总装机记忆 · 势场联络 (L2/L3/L4 势场 → 意图 −∇Φ)  ·  节点 ss_mem_field · L2

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ss_mem_l4, ss_mem_l3, ss_mem_l2
    out out1  → sssched

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ss_mem_field.<port>

实现绑定: registry key=`ss_mem_field` · src/lerobot/memory/potential_field.py
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ss_mem_field'
NAME = '🧲 总装机记忆 · 势场联络 (L2/L3/L4 势场 → 意图 −∇Φ)'
LAYER = 'L2'
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'ss_mem_field'
SOURCE = 'src/lerobot/memory/potential_field.py'
SOURCE_SYMBOL = ''
PARAMS = {'state_space': True, 'mem_field': True, 'desc': '[总装机记忆·势场联络] L2 肌肉记忆: 每条技能冠军轨迹→技能势场 Φ_SK (谷底=真跑末点 · σ=谷宽 · 触发/速度上限取技能库真值) · L3 工艺流程记忆: 按真实段时长(真跑帧数)加权组合→流程势场 Φ_process(x,t), 谷底随时序从 SK01 连续移到 SK07 · L4 物理工作空间记忆: Φ_process + 障碍场(孔壁/台面 引擎现场几何) + 世界模型预测项 · 输出 −∇Φ = 意图(方向/速率/技能/置信) 给 L4 INTACT 链按层叠加(blend_action)。逐层开关 = data/memory/memory_layers.json (默认全关=零干预, 逐步打开)。源码 src/lerobot/memory/potential_field.py · 节点 mem_nodes.node_ss_mem_field', 'source': 'src/lerobot/memory/potential_field.py'}

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


def compute(ctx):
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
        try:
            res = fn(ctx)                       # 约定: 接 ctx 的实现
        except TypeError:
            res = fn()                          # 老实现: 无参
        if isinstance(res, dict):
            LAST_STATUS = "实现执行"
            return {k: v for k, v in res.items() if k in PORTS_OUT}
        LAST_STATUS = "实现返回非 dict → 直通"
        return _passthrough(ctx)
    except Exception as e:                                          # noqa: BLE001
        LAST_STATUS = "实现异常(%s: %s) → 直通" % (type(e).__name__, e)
        return _passthrough(ctx)
