# -*- coding: utf-8 -*-
"""🌍 Z-MAX 引擎 · 光模块插拔真物理 (模型动作真下发 env.step)  ·  节点 swworld

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← swintact
    in  in2   ← ssworld, n_realscene
    out out1  → swds
    out out2  → swvideo

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.swworld.<port>

实现绑定: registry key=`sw_world` · tools/intact_sw_optical_bridge.py:def 
执行口径: EXEC_MODE=act · PURE=False (会动设备: 只走数据面, 需 8793 授权后由引擎执行)
"""

NODE_ID = 'swworld'
NAME = '🌍 Z-MAX 引擎 · 光模块插拔真物理 (模型动作真下发 env.step)'
LAYER = ''
TYPE = 'hardware'
EXEC_MODE = 'act'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2']
PORTS_OUT = ['out1', 'out2']
PORT_LABELS = {}

IMPL_KEY = 'sw_world'
SOURCE = 'tools/intact_sw_optical_bridge.py'
SOURCE_SYMBOL = 'def '
PARAMS = {'desc': '[L4 硬件层] Z-MAX 六层引擎 RealStateSpaceSim (metaworld peg-insert-side-v3 真接触/夹持/插入动力学): 每步接收 INTACT 模型动作 → env.step 真下发 (引擎既有直驱入口 _direct_act, 不经解析控制器) → 逐帧渲染回数据源; 同 seed 另跑解析链对照(插入 + 插→拔→AOI 全链)作可达性基线; 出 480² 逐帧 mp4 存 reports/intact_sw/video', 'sw_bridge': True, 'sim': True, 'env': 'metaworld/peg-insert-side-v3 (RealStateSpaceSim)', 'source': 'tools/intact_sw_optical_bridge.py', 'source_symbol': 'def '}

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
