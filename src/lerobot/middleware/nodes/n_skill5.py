# -*- coding: utf-8 -*-
"""⑤ 抬起 · SK05  ·  节点 sssk5

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssskill, sslimit
    out out1  → n_moveit
    out out2  → ssphys

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.sssk5.<port>

实现绑定: registry key=`sssk5` · src/lerobot/policies/left_right/state_space/skills/atomic_skills.py:class SK05Lift
执行口径: EXEC_MODE=act · PURE=False (会动设备: 只走数据面, 需 8793 授权后由引擎执行)
"""

NODE_ID = 'sssk5'
NAME = '⑤ 抬起 · SK05'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'act'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1', 'out2']
PORT_LABELS = {}

IMPL_KEY = 'sssk5'
SOURCE = 'src/lerobot/policies/left_right/state_space/skills/atomic_skills.py'
SOURCE_SYMBOL = 'class SK05Lift'
PARAMS = {'state_space': True, 'skill_layer': True, 'skill': {'template': 'SK05', 'stage': '抬起'}, 'desc': '[基础·分段小模型] 原子技能 ⑤ 抬起 (SK05): 固定轨迹模板 — 决策层选定本技能时实时赋值 (阶段目标/速度), 复制模板实例化快速执行 → 输出执行指令给执行器', 'source': 'src/lerobot/policies/left_right/state_space/skills/atomic_skills.py', 'source_symbol': 'class SK05Lift'}

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
        # ⚖ 2026-10-16: 显示**关键路径**上的闸门真值 (引擎内联闸同一拍, 见 gate_truth.py)
        try:
            from lerobot.middleware.nodes import gate_truth as _gt
            _kp = _gt.one_line("抬起")
            LAST_STATUS = "直通 (PURE=False) · " + (_kp or "关键路径闸尚未生成 (引擎未跑 / 帧龄超 5s)")
        except Exception:                                              # noqa: BLE001
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