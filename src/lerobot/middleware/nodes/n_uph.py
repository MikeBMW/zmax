# -*- coding: utf-8 -*-
"""🏭 UPH 节拍循环器  ·  节点 ssuph

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssdata
    out out1  → (未被下游读取)

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssuph.<port>

实现绑定: registry key=`ss_uph` · src/lerobot/engineering/nodes/uph_tact_impl.py:def run
执行口径: EXEC_MODE=pure · PURE=True (口径已逐一验证 ⇒ 允许计算面真跑)
"""

NODE_ID = 'ssuph'
NAME = '🏭 UPH 节拍循环器'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'ss_uph'
SOURCE = 'src/lerobot/engineering/nodes/uph_tact_impl.py'
SOURCE_SYMBOL = 'def run'
PARAMS = {'state_space': True, 'uph_target': 300, 'tact_s': 12.0, 'desc': '[节拍执行源·预存段表驱动] 读 sim_insert 段表(392段/14件) 按 11.42s 节拍推进 → out1 当前动作(a/b/kind) out2 进度/产出 out3 节拍/UPH; 场景已录 ⇒ 不依赖大模型/语言层, 离线可跑; 输出驱动 AR 场景虚拟臂(真机零指令)', 'source': 'src/lerobot/engineering/nodes/uph_tact_impl.py', 'source_symbol': 'def run', 'pure_verified': True, 'impl_key': 'ss_uph'}

# 计算面开关: False = 只走数据面(直通 outN←inN), 不自动执行实现
PURE = True
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
