# -*- coding: utf-8 -*-
"""🔷 SE(3)×S1 记忆流形 (8815 · A位置ℝ³ · B轴S² · C四元数S³ · D滚转S¹ · E相位S¹ · 5Hz)  ·  节点 ss_se3_state

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← (工程外注入/无上游)
    out out1  → ss_phase_corr

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ss_se3_state.<port>

实现绑定: (未绑定注册表实现) · src/lerobot/middleware/nodes/impl/ss_se3_state.py:def node_ss_se3_state
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)

⚠️ 本文件只是**端口契约** (端口/话题/执行口径), 不含业务逻辑。一个节点在看三处:
   契约  src/lerobot/middleware/nodes/n_8815.py              ← 就是本文件
   实现  src/lerobot/middleware/nodes/impl/_未绑定.py         ← 取数 → 调算法 → 打标 (改逻辑改这里)
   算法  src/lerobot/middleware/nodes/impl/ss_se3_state.py                                             ← 纯计算 (模型/几何/控制律)
   三处位置可一次问全: lerobot.engineering.sourceview.get_node_triple("ss_se3_state")
"""

NODE_ID = 'ss_se3_state'
NAME = '🔷 SE(3)×S1 记忆流形 (8815 · A位置ℝ³ · B轴S² · C四元数S³ · D滚转S¹ · E相位S¹ · 5Hz)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = ''
SOURCE = 'src/lerobot/middleware/nodes/impl/ss_se3_state.py'
SOURCE_SYMBOL = 'def node_ss_se3_state'
PARAMS = {'state_space': True, 'kind': 'real', 'hz': 5, 'role': '记忆流形入口 — 把昨天落地的 16 维 SE(3)×S1 状态 (A–E) 摆上画布, 下游相空间通道吃它', 'source': 'src/lerobot/middleware/nodes/impl/ss_se3_state.py', 'source_symbol': 'def node_ss_se3_state', 'truth': 'zmax_data/se3/se3_state_live.json (zmax-se3-state.service · 8815 /api/se3)', 'vector16': 'A_pos_mm(3) B_axis_S2(3) B_err(1) C_quat_S3(4) D_roll(1) E_s(1) E_arc_mm(1) E_i(1) M_age(1)', 'desc': 'SE(3)×S1: 位置 ℝ³ · 轴 S² · 四元数 S³ · 滚转 S¹ · 弧长相位 S¹ (只读, 不新增控制通路)'}

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
