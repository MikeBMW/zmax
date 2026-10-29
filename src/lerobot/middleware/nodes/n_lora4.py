# -*- coding: utf-8 -*-
"""🎛 L4 · INTACT LoRA 微调 (接在意图解码器后 · 冻结原权重 · 只调 ΔW=(α/r)BA)  ·  节点 ss_lora_l4 · L4

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssz700, ssintact_dec, ss_l5
    in  in2   ← n_intent_direct
    out out1  → ssintact, ssmani_exp
    out out2  → ssmani_c
    out out3  → ssmani_p
    out out4  → ssdec

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ss_lora_l4.<port>

实现绑定: registry key=`ss_lora_l4` · tools/lora_inject.py:def inject_lora
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ss_lora_l4'
NAME = '🎛 L4 · INTACT LoRA 微调 (接在意图解码器后 · 冻结原权重 · 只调 ΔW=(α/r)BA)'
LAYER = 'L4'
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2']
PORTS_OUT = ['out1', 'out2', 'out3', 'out4']
PORT_LABELS = {}

IMPL_KEY = 'ss_lora_l4'
SOURCE = 'tools/lora_inject.py'
SOURCE_SYMBOL = 'def inject_lora'
PARAMS = {'desc': '[L4 微调] INTACT 本域 LoRA: 注入 112 层线性 (r=8/α=16), 从官方 pusht 权重初始化, 数据 optical_insert v6 真机示教; 产物必须 merge 后才可部署 (包装键→Missing key→trained=False 零动作); 现状: 200 步产物 A/B 未证明提升 → 不切在役指针; 2026-09-24 Δu 逐帧诊断定位根因 = 幅值比中位 5.2~5.8× (闸门红线 1.5×) 被 L2 收口闸逐帧否决', 'source': 'tools/lora_inject.py', 'source_symbol': 'def inject_lora', 'status': '保留·接入中 (2026-09-26 老倪: 保留并接入系统; 需 merge 后才生效)', 'todo': True, 'ckpt': 'zmax_data/stable-wm-cache/checkpoints/intact_goal_optical_insert_v6lora_200'}

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
