# -*- coding: utf-8 -*-
"""🧠 流形专家预测器 (JEPA: 潜空间→流形→动作)  ·  节点 ssmani_exp

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssvlm, ss_lora_l4
    in  in2   ← ss2d3d
    in  in4   ← ss_moe
    in  in5   ← ss_mani_eng
    in  in6   ← n_calib_mani
    out out1  → ssmani_c, ssmani_p

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssmani_exp.<port>

实现绑定: registry key=`ss_pred` · src/lerobot/manifold/predictor_layer.py:class WorldModelPredictor
执行口径: EXEC_MODE=view · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ssmani_exp'
NAME = '🧠 流形专家预测器 (JEPA: 潜空间→流形→动作)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'view'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in4', 'in5', 'in6']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'ss_pred'
SOURCE = 'src/lerobot/manifold/predictor_layer.py'
SOURCE_SYMBOL = 'class WorldModelPredictor'
PARAMS = {'desc': "[专家·世界模型 L4] **入线两条意图通道**: ①活跃口径 z7 = 引擎几何潜空间 R7 + 引擎几何意图 (target−peg_head), 来自 📐 2D→3D 解算; ②z_t 口径 = INTACT 潜空间 192 + 意图增量 m_int=δ(z_goal−z_t), 来自 🎯 INTACT 意图解码器 (该口径 LOSO R² 全负未启用, 但解码器的 m_int 仍作为门控/存在性条件参与, w=m_int_weight×SS_L4_INTENT_LINE_W×ready) · JEPA predictor 链路: LatentPredictor (z_t+a_t→z') → ManifoldReadout (接触/性能流形坐标 6 维, 真值对齐) → StateSpaceActionHead (流形→4D 动作); 源码 src/lerobot/manifold/predictor_layer.py", 'expert': True, 'state_space': True, 'source': 'src/lerobot/manifold/predictor_layer.py', 'source_symbol': 'class WorldModelPredictor'}

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


def compute_n_jepa(ctx):
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


# 🔎 2026-10-31 老倪「Call Stack 要能看出是哪个画布节点」: 真名是 compute_n_jepa (帧名可见),
#   中间件接口名仍叫 compute (Node.compute 找 module.compute, 别名保持兼容)。
compute = compute_n_jepa
