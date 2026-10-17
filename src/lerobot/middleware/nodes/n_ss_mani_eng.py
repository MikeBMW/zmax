# -*- coding: utf-8 -*-
"""🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)  ·  节点 ss_mani_eng

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
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
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
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
PARAMS = {'state_space': True, 'manifold_engine': True, 'kind': 'real', 'role': 'L4 核心内核 — 高维状态→低维流形, 流形上 表征/投影/度量/导航/反馈', 'api': 'project() · navigate() · gradient_flow() · feedback_update() · step() · query()', 'pipeline': '编码(Encoder/PCA) → 投影(ManifoldProjector) → 度量+梯度(MetricCalculator) → 导航(Navigator 测地线) → 反馈(FeedbackLoop 有界)', 'manifolds_ready': 'euclidean · sphere · torus · so3 · se3 · su2 · latent_flat', 'manifolds_planned': 'calabi_yau(Ricci-flat 度量未实现) · hyperbolic(未实现) — 仅登记, 不造数', 'source': 'src/lerobot/manifold/manifold_engine.py', 'source_symbol': 'class ManifoldEngine', 'reuse': 'su2.py(群) · lie_intent.py(SO3/SE3) · manifold_layer.py(接触/性能势能) · fiber_bundle.py(提升) — 复用既有真件', 'measured': '端到端 0.056ms/帧 · 投影 0.019ms · 测地线T=16 0.24ms · 约束违例 1.1e-16 · 上限 ~3500Hz (真跑引擎轨迹实测)', 'spec_target': '延迟<10ms · 投影<1ms · 测地线<50ms · >100Hz — 全部达标', 'caveat': '解码器(岭回归)只在标定分布内可信 (训练段逐维相关 0.76~0.94; 未见段 R² 负) → 跨段须重标定', 'desc': 'L4 核心内核: 把高维状态自动约束为低维流形, 在流形上做测地线导航/梯度流/有界反馈; 输出意图与动作建议', 'core': True, 'core_color': '#FFC53D', 'core_role': '系统核心 (流形引擎)'}

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
