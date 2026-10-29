# -*- coding: utf-8 -*-
"""🧩 Feature 功能清单  ·  节点 ssfeat

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssworld
    in  in2   ← ss_mem_share
    out out1  → (未被下游读取)

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssfeat.<port>

实现绑定: registry key=`ss_feature` · src/lerobot/verification/verification_layer.py:FEATURES = [
执行口径: EXEC_MODE=view · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ssfeat'
NAME = '🧩 Feature 功能清单'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'view'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'ss_feature'
SOURCE = 'src/lerobot/verification/verification_layer.py'
SOURCE_SYMBOL = 'FEATURES = ['
PARAMS = {'state_space': True, 'verif_layer': True, 'desc': 'Feature 功能清单: 状态空间系统全部 feature 汇总 (A12/B13/C4/D3/E5/F4/G10/H6; 分级 L2 38/L4 11); 共 57 条自动/半自动断言 · 功能树 113 功能×562 用例 (22 节点); 新增: F-B12 3D视觉引导 / F-B13 触觉反馈闭环 (2026-09-24); 源码 verification_layer.py FEATURES', 'source': 'src/lerobot/verification/verification_layer.py', 'source_symbol': 'FEATURES = ['}

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
