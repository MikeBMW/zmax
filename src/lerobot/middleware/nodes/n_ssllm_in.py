# -*- coding: utf-8 -*-
"""📝 任务指令 · MES/自然语言  ·  节点 ssllm_in

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssdata
    in  in3   ← ssz700
    out out1  → n_dsvl, ssllm

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssllm_in.<port>

实现绑定: registry key=`ss_llm_in` · src/lerobot/policies/left_right/state_space/planner.py:class TaskPlanner
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ssllm_in'
NAME = '📝 任务指令 · MES/自然语言'
LAYER = ''
TYPE = 'hardware'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in3']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'ss_llm_in'
SOURCE = 'src/lerobot/policies/left_right/state_space/planner.py'
SOURCE_SYMBOL = 'class TaskPlanner'
PARAMS = {'state_space': True, 'task_input': True, 'desc': '大模型层·输入: MES 工单/自然语言指令 + **场景图通道** (in1 仿真 metaworld 渲染帧 / in2 引擎真图 / in3 真机帧与位姿) → 视觉大模型(SceneVLM: 本地 Qwen2.5-VL-3B 或 API) 场景理解 → 🧠任务规划器 (planner.py); 无模型时规则回退并如实标注', 'source': 'src/lerobot/policies/left_right/state_space/planner.py', 'source_symbol': 'class TaskPlanner'}

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
