# -*- coding: utf-8 -*-
"""🛠 L3 技能序列编排  ·  节点 ssskill · L3

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssdata
    in  in2   ← ssz700
    in  in3   ← ssreason
    in  in4   ← n_vlm_llm
    out out1  → n_skill_dict, n_l2_muscle, sssk2, sssk3, sssk4, sssk5, sssk6, sssk7, sssk8

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssskill.<port>

实现绑定: registry key=`ss_skill` · src/lerobot/policies/left_right/state_space/planner.py:class SkillComposer
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ssskill'
NAME = '🛠 L3 技能序列编排'
LAYER = 'L3'
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in3', 'in4']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'ss_skill'
SOURCE = 'src/lerobot/policies/left_right/state_space/planner.py'
SOURCE_SYMBOL = 'class SkillComposer'
PARAMS = {'state_space': True, 'skill_composer': True, 'llm': 'Qwen3-7B (可插拔)', 'desc': '技能编排器 SkillComposer: 五大作业场景定义 (steps→技能序列, performance→参数覆盖默认) / 新型号规格 → 技能序列+力阈值/节拍', 'source': 'src/lerobot/policies/left_right/state_space/planner.py', 'source_symbol': 'class SkillComposer'}

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
