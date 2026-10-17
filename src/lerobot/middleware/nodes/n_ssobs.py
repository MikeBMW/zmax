# -*- coding: utf-8 -*-
"""🧩 SU(2) 统一状态空间 (二阶特殊酉群)  ·  节点 ssobs

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← sssensor
    out out1  → ssff, ssreason, ssvideo, ss_moe
    out out2  → ssest
    out out3  → ss_mani_eng

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssobs.<port>

实现绑定: registry key=`ss_obs` · src/lerobot/policies/left_right/state_space/su2.py:class SU2UnifiedState
执行口径: EXEC_MODE=view · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ssobs'
NAME = '🧩 SU(2) 统一状态空间 (二阶特殊酉群)'
LAYER = ''
TYPE = 'system'
EXEC_MODE = 'view'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1', 'out2', 'out3']
PORT_LABELS = {}

IMPL_KEY = 'ss_obs'
SOURCE = 'src/lerobot/policies/left_right/state_space/su2.py'
SOURCE_SYMBOL = 'class SU2UnifiedState'
PARAMS = {'state_space': True, 'su2_unified_state': True, 'group': 'SU(2) = {U ∈ C^2x2 : U†U = I, det U = 1}', 'map_law': 'ω = π·tanh(gain·‖v‖)·v̂ (有界映射律, θ<π 不绕圈, 方向保留)', 'blocks': 'L2=43D obs 几何误差 | L3=流形规划(进度/偏离/剩余) | L4=安全动作(u_sat/接触/η) | L5=大模型意图', 'observables': 'θ偏离角 / n̂状态方向 / |w|收敛度 / 逐层剥离贡献 / 层间不可交换性 / Fubini-Study 距离', 'viz_tools': 'Bloch球 + S³分量 + 层贡献 + 反演剥离 + 距离矩阵 + 节点映射 (双击开观测面板)', 'desc': '[统一状态·群] SU(2) 二阶特殊酉群: 原 43D 统一状态向量降为群里的 L2 输入块; 全部层(L2/L3/L4/L5)与全部节点数据按有界映射律映成群元素, 群乘法=层合成(不可交换=层间耦合), 反演剥离读每层贡献; 群恒等元 ⇔ 场景收敛', 'source': 'src/lerobot/policies/left_right/state_space/su2.py', 'source_symbol': 'class SU2UnifiedState'}

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
