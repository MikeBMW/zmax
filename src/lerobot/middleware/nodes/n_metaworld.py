# -*- coding: utf-8 -*-
"""📦 数据源 (AR场景 ⇄ 仿真 ⇄ 真机)  ·  节点 ssdata

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← (工程外注入/无上游)
    out out1  → ssintact, ssvlm, ssyolo, sstactile, ssbypv, ssllm_in, ssskill, ssmode, ssintact_dec, n_dsvl, swds, n_realscene, ss_l5
    out out2  → sssensor, ssuph, ssplan
    out out3  → ss_seg

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssdata.<port>

实现绑定: registry key=`data` · src/lerobot/middleware/nodes/impl/data.py · node_metaworld_data:node_metaworld_data
执行口径: EXEC_MODE=pure · PURE=True (口径已逐一验证 ⇒ 允许计算面真跑)

⚠️ 本文件只是**端口契约** (端口/话题/执行口径), 不含业务逻辑。一个节点在看三处:
   契约  src/lerobot/middleware/nodes/n_metaworld.py              ← 就是本文件
   实现  src/lerobot/middleware/nodes/impl/data.py         ← 取数 → 调算法 → 打标 (改逻辑改这里)
   算法  src/lerobot/middleware/nodes/impl/data.py · node_metaworld_data                                             ← 纯计算 (模型/几何/控制律)
   三处位置可一次问全: lerobot.engineering.sourceview.get_node_triple("ssdata")
"""

NODE_ID = 'ssdata'
NAME = '📦 数据源 (AR场景 ⇄ 仿真 ⇄ 真机)'
LAYER = ''
TYPE = 'hardware'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1', 'out2', 'out3']
PORT_LABELS = {}

IMPL_KEY = 'data'
SOURCE = 'src/lerobot/middleware/nodes/impl/data.py · node_metaworld_data'
SOURCE_SYMBOL = 'node_metaworld_data'
PARAMS = {'src_switch': True, 'src_state': 'AR场景', 'source': 'src/lerobot/middleware/nodes/impl/data.py · node_metaworld_data', 'task': 'peg-insert-side-v3', 'frames': 4800, 'state_dim': 39, 'action_dim': 4, 'policy': 'left_right', 'run_env': True, 'state_space': True, 'desc': '[数据源层] 画布拨钮决定数据源: AR场景(8802 MuJoCo 渲染帧 · 真帧真深度) / 仿真(metaworld 39D) / 真机(4060 只读订阅 Orin)。选 AR 时本节点每拍真取 /frame.png?cam=ar | 端口: out1=场景帧 out2=场景状态(关节/夹爪/相机) out3=图像句柄; PURE=True 走计算面真跑', 'source_symbol': 'node_metaworld_data', 'cam': 'ar3d', 'src_kinds': ['ar', 'metaworld', 'orin'], 'pure_verified': True, 'impl_key': 'data'}

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
