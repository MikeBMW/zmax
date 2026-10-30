# -*- coding: utf-8 -*-
"""🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)  ·  节点 ss_mani_eng

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← sssensor, n_vlm_llm
    in  in2   ← ssobs
    in  in3   ← sscalib
    in  in4   ← sslat
    in  in5   ← ss_moe
    in  in6   ← n_calib_mani
    out out1  → n_intent_direct, ssintact_dec
    out out2  → ssmani_exp
    out out3  → ssmani_c
    out out4  → ssmani_p
    out out5  → sssched

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ss_mani_eng.<port>

实现绑定: registry key=`ss_mani_eng` · src/lerobot/manifold/manifold_engine.py:class ManifoldEngine
执行口径: EXEC_MODE=pure · PURE=True (口径已逐一验证 ⇒ 允许计算面真跑)
"""

NODE_ID = 'ss_mani_eng'
NAME = '🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in3', 'in4', 'in5', 'in6']
PORTS_OUT = ['out1', 'out2', 'out3', 'out4', 'out5']
PORT_LABELS = {}

IMPL_KEY = 'ss_mani_eng'
SOURCE = 'src/lerobot/manifold/manifold_engine.py'
SOURCE_SYMBOL = 'class ManifoldEngine'
PARAMS = {'state_space': True, 'manifold_engine': True, 'kind': 'real', 'role': 'L4 核心内核 — 高维状态→低维流形, 流形上 表征/投影/度量/导航/反馈', 'api': 'project() · navigate() · gradient_flow() · feedback_update() · step() · query()', 'pipeline': '编码(Encoder/PCA) → 投影(ManifoldProjector) → 度量+梯度(MetricCalculator) → 导航(Navigator 测地线) → 反馈(FeedbackLoop 有界)', 'manifolds_ready': 'euclidean · sphere · torus · so3 · se3 · su2 · latent_flat', 'manifolds_planned': 'calabi_yau(Ricci-flat 度量未实现) · hyperbolic(未实现) — 仅登记, 不造数', 'source': 'src/lerobot/manifold/manifold_engine.py', 'source_symbol': 'class ManifoldEngine', 'reuse': 'su2.py(群) · lie_intent.py(SO3/SE3) · manifold_layer.py(接触/性能势能) · fiber_bundle.py(提升) — 复用既有真件', 'measured': '端到端 0.056ms/帧 · 投影 0.019ms · 测地线T=16 0.24ms · 约束违例 1.1e-16 · 上限 ~3500Hz (真跑引擎轨迹实测)', 'spec_target': '延迟<10ms · 投影<1ms · 测地线<50ms · >100Hz — 全部达标', 'caveat': '解码器(岭回归)只在标定分布内可信 (训练段逐维相关 0.76~0.94; 未见段 R² 负) → 跨段须重标定', 'desc': 'L4 核心内核: 把高维状态自动约束为低维流形, 在流形上做测地线导航/梯度流/有界反馈; 输出意图与动作建议', 'core': True, 'core_color': '#FFC53D', 'core_role': '系统核心 (流形引擎)', 'pure_verified': True}

# 计算面开关: False = 只走数据面(直通 outN←inN), 不自动执行实现
import os as _os
# 🧪 2026-10-30 流形引擎有效性对照实验: 关掉它跑一组基线, 与开着同口径比。
#   ZMAX_MANI_ENG_OFF=1 ⇒ 直通 (n_manifold 不调用 manifold_engine), 段表/执行链完全不变。
PURE = _os.environ.get("ZMAX_MANI_ENG_OFF", "0") != "1"
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


def compute_n_manifold(ctx):
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


# 🔎 2026-10-31 老倪「Call Stack 要能看出是哪个画布节点」: 真名是 compute_n_manifold (帧名可见),
#   中间件接口名仍叫 compute (Node.compute 找 module.compute, 别名保持兼容)。
compute = compute_n_manifold
