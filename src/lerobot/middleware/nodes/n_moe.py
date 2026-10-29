# -*- coding: utf-8 -*-
"""🧬 元数据MOE门控路由  ·  节点 ss_moe

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssobs
    in  in2   ← ssvlm
    out out1  → ssmani_exp
    out out2  → sssched
    out out3  → ss_mani_eng

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ss_moe.<port>

实现绑定: (未绑定注册表实现) · tools/stage_moe_backbone.py:class StageMoE
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ss_moe'
NAME = '🧬 元数据MOE门控路由'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2']
PORTS_OUT = ['out1', 'out2', 'out3']
PORT_LABELS = {}

IMPL_KEY = ''
SOURCE = 'tools/stage_moe_backbone.py'
SOURCE_SYMBOL = 'class StageMoE'
PARAMS = {'desc': '[L4 认知主干 · 数据空间根的元数据层 2026-10-13 老倪改名] 元数据MOE门控路由: ① 元数据 = 整个系统的数据库根服务 (基础核心组成; 玻色子型=场/连续量, 费米子型=离散实体), ② 数据空间每个 topic = 由元数据组合成的原子/分子/有机物 (映射规则表), ③ 全息系统 = 整体算子可由 topic 子集复现 (实测秩/误差), ④ 硬先验门控路由 = 7 阶段→7 专家 1:1 (单射), 实现源码 tools/meta_moe_router.py; 原 7 专家 SigLIP 768d 冻结主干 + skill_ctx 阶段概率路由能力保留', 'source': 'tools/stage_moe_backbone.py', 'source_symbol': 'class StageMoE', 'status': '在役 (2026-09-26 会话四: 修 8 阶段覆盖 + 零回退逐位同; ckpt 真加载 7 专家)', 'todo': True, 'ckpt': 'zmax_data/stable-wm-cache/checkpoints/stage_moe/moe.pt (351MB)', 'meta_layer_src': 'tools/meta_moe_router.py', 'renamed_from': '阶段专家MOE门控路由', 'renamed_at': '2026-10-13'}

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
