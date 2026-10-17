# -*- coding: utf-8 -*-
"""🎯 INTACT 插拔策略 · 光模块抓取插入 (本域微调 · 零搜索)  ·  节点 swintact

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← swds
    in  in2   ← ssintact
    in  in3   ← sscap
    out out1  → swworld

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.swintact.<port>

实现绑定: registry key=`sw_intact` · src/lerobot/policies/intact/runtime/node.py
执行口径: EXEC_MODE=act · PURE=False (会动设备: 只走数据面, 需 8793 授权后由引擎执行)
"""

NODE_ID = 'swintact'
NAME = '🎯 INTACT 插拔策略 · 光模块抓取插入 (本域微调 · 零搜索)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'act'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in3']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'sw_intact'
SOURCE = 'src/lerobot/policies/intact/runtime/node.py'
SOURCE_SYMBOL = ''
PARAMS = {'desc': '[L4 中间策略] INTACT-JEPA 本域微调权重 (u 口径数据集 optical_insert_v4 训练, 从官方 pusht 权重初始化): 渲染图像+目标帧(解析链成功末帧)+动作历史 → 一次前向出动作块 (零候选搜索 candidate_action_steps=0) → 唯一变换=训练归一化逆运算 a_raw=z·std+mean → 按引擎 u→act 约定下发 (act[:3]=clip(u/K_ACT) · act[3]=CLOSE if u[3]>0.5); 封装 src/lerobot/policies/intact/ · 桥 tools/intact_sw_optical_bridge.py', 'intact': True, 'sw_bridge': True, 'task': 'optical_insert', 'policy': 'intact_goal_optical_insert_v4_s3072 (自动挑最新 epoch)', 'source': 'src/lerobot/policies/intact/runtime/node.py'}

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
