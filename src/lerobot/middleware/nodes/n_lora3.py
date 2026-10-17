# -*- coding: utf-8 -*-
"""🎛 L3 · SmolVLA LoRA 微调 · 接入中  ·  节点 ss_lora_l3 · L3

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssz700, ss_l5
    out out1  → ssvlm

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ss_lora_l3.<port>

实现绑定: registry key=`ss_lora_l3` · tools/lora_inject.py:class LoRALinear
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ss_lora_l3'
NAME = '🎛 L3 · SmolVLA LoRA 微调 · 接入中'
LAYER = 'L3'
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'ss_lora_l3'
SOURCE = 'tools/lora_inject.py'
SOURCE_SYMBOL = 'class LoRALinear'
PARAMS = {'desc': '[L3 微调] SmolVLA 本域 LoRA: VLM 注意力 + action expert (flow-matching 头) 注入, batch2 / LoRA; 实测 200 步 / 3670s · loss 0.192 · action_loss 0.2368 · 显存 3.75GB; ⏳ 待办: 与统一主干/阶段专家 MOE 同口径评测后才进默认档', 'source': 'tools/lora_inject.py', 'source_symbol': 'class LoRALinear', 'status': '保留·接入中 (2026-09-26 老倪: 保留并接入系统; 需 merge 后才生效)', 'todo': True, 'ckpt': 'outputs/train/smolvla_lew_lora_200r4/checkpoints'}

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
