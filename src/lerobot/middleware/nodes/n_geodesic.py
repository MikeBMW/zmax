# -*- coding: utf-8 -*-
"""🧭 测地线规划引导  ·  节点 n_geoplan

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssobs
    out out1  → sslimit
    out out2  → sssched

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.n_geoplan.<port>

实现绑定: registry key=`n_geoplan` · src/lerobot/engineering/nodes/geo_plan_impl.py:run
执行口径: EXEC_MODE=act · PURE=False (会动设备: 只走数据面, 需 8793 授权后由引擎执行)
"""

NODE_ID = 'n_geoplan'
NAME = '🧭 测地线规划引导'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'act'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1', 'out2']
PORT_LABELS = {'in1': 'obs 43D', 'in2': '目标点(可选)', 'out1': '3D 引导位姿', 'out2': '块 chunk[H,4]'}

IMPL_KEY = 'n_geoplan'
SOURCE = 'src/lerobot/engineering/nodes/geo_plan_impl.py'
SOURCE_SYMBOL = 'run'
PARAMS = {'state_space': True, 'geo_chunk': {'H': 8, 'latent': 16, 'state_dim': 43, 'manifold': 'SU(2)', 'M': 3.643, 'decode': 'ridge (readout + readout_b, 硬限幅)'}, 'role': '运动规划支 (与前馈 MLP 并列, 进加权)', 'desc': 'obs43 → ManifoldEngine.project(潜空间) → 目标点(本段目标槽 obs[36:39]) → navigator.compute_geodesic(H 步, 指数映射+slerp) → readout ridge 解码(限幅) → 块 chunk[H,4]。与块流水线 tools/ss_chunk_pipeline.py::_chunk 逐行同源; 只出块, 不下发、不碰授权。注意: 与 n_moveit (MoveIt 关节空间规划, 在原子技能之后) 不是同一个节点。源码 src/lerobot/engineering/nodes/geo_plan_impl.py', 'source': 'src/lerobot/engineering/nodes/geo_plan_impl.py', 'source_symbol': 'run', '_port_labels': {'in1': 'obs 43D', 'in2': '目标点(可选)', 'out1': '3D 引导位姿', 'out2': '块 chunk[H,4]'}, 'guide': {'target': '视觉3D 孔口(obs[36:39]) / 模块(obs[4:7])', 'hover_mm': 40, 'v_cap': 0.35, 'dt': 0.1, 'pose': 'pos_mm + quat(obs[24:33] 旋转矩阵) + 进给轴', 'check': '测地线方向与几何方向 cos, <0.3 时几何主导并标注'}}

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


def compute_n_geodesic(ctx):
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


# 🔎 2026-10-31 老倪「Call Stack 要能看出是哪个画布节点」: 真名是 compute_n_geodesic (帧名可见),
#   中间件接口名仍叫 compute (Node.compute 找 module.compute, 别名保持兼容)。
compute = compute_n_geodesic
