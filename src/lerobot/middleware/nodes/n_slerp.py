# -*- coding: utf-8 -*-
"""🧭 测地线块规划 · 指数映射+slerp (H=8)  ·  节点 n_geoplan

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssobs
    out out1  → sssched

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.n_geoplan.<port>

实现绑定: registry key=`n_geoplan` · src/lerobot/engineering/nodes/geo_plan_impl.py:run
执行口径: EXEC_MODE=act · PURE=False (会动设备: 只走数据面, 需 8793 授权后由引擎执行)
"""

NODE_ID = 'n_geoplan'
NAME = '🧭 测地线块规划 · 指数映射+slerp (H=8)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'act'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1']
PORT_LABELS = {'in1': 'obs 43D', 'out1': '块 chunk[H,4]'}

IMPL_KEY = 'n_geoplan'
SOURCE = 'src/lerobot/engineering/nodes/geo_plan_impl.py'
SOURCE_SYMBOL = 'run'
PARAMS = {'state_space': True, 'geo_chunk': {'H': 8, 'latent': 16, 'state_dim': 43, 'manifold': 'SU(2)', 'M': 3.643, 'decode': 'ridge (readout + readout_b, 硬限幅)'}, 'role': '运动规划支 (与前馈 MLP 并列, 进加权)', 'desc': 'obs43 → ManifoldEngine.project(潜空间) → 目标点(本段目标槽 obs[36:39]) → navigator.compute_geodesic(H 步, 指数映射+slerp) → readout ridge 解码(限幅) → 块 chunk[H,4]。与块流水线 tools/ss_chunk_pipeline.py::_chunk 逐行同源; 只出块, 不下发、不碰授权。注意: 与 n_moveit (MoveIt 关节空间规划, 在原子技能之后) 不是同一个节点。源码 src/lerobot/engineering/nodes/geo_plan_impl.py', 'source': 'src/lerobot/engineering/nodes/geo_plan_impl.py', 'source_symbol': 'run', '_port_labels': {'in1': 'obs 43D', 'in2': '目标点(可选)', 'out1': '块 chunk[H,4]'}}

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
