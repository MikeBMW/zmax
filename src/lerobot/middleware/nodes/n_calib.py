# -*- coding: utf-8 -*-
"""🧮 标定层 · 引力-斥力-动作  ·  节点 sscalib

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ss2d3d
    out out1  → sslat
    out out2  → ss_mani_eng
    out out3  → n_calib_mani

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.sscalib.<port>

实现绑定: registry key=`ss_calib` · src/lerobot/calibration/calibration_layer.py:class CalibrationLayer
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'sscalib'
NAME = '🧮 标定层 · 引力-斥力-动作'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1', 'out2', 'out3']
PORT_LABELS = {}

IMPL_KEY = 'ss_calib'
SOURCE = 'src/lerobot/calibration/calibration_layer.py'
SOURCE_SYMBOL = 'class CalibrationLayer'
PARAMS = {'state_space': True, 'calib_layer': True, 'desc': '[L4 标定·地图校准 回路外] 引力(快速动作标定: Kp+阶段限速) — 斥力(状态预测标定: 卡尔曼/接触/否决) — 动作(新: DiT action 输出标定量, 输入见 ssdec 连线); 潜空间域已独立至「🧮 潜空-流形」节点 (L4 流形输入); 源码 calibration_layer.py', 'source': 'src/lerobot/calibration/calibration_layer.py', 'source_symbol': 'class CalibrationLayer'}

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
