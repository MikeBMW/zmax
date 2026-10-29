# -*- coding: utf-8 -*-
"""🖥 Z700 真机信号 (全信号观测 · 物理世界输出)  ·  节点 ssz700

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← (工程外注入/无上游)
    out out1  → ssllm_in, ssskill, ssintact_dec, n_board_frame, ss_lora_l4, ss_lora_l3
    out out2  → ss_grav_h

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssz700.<port>

实现绑定: registry key=`ss_z700_signals` · tools/gui/ss_bypass_view.py:class Z700SignalsView
执行口径: EXEC_MODE=act · PURE=False (会动设备: 只走数据面, 需 8793 授权后由引擎执行)
"""

NODE_ID = 'ssz700'
NAME = '🖥 Z700 真机信号 (全信号观测 · 物理世界输出)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'act'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1', 'out2']
PORT_LABELS = {}

IMPL_KEY = 'ss_z700_signals'
SOURCE = 'tools/gui/ss_bypass_view.py'
SOURCE_SYMBOL = 'class Z700SignalsView'
PARAMS = {'state_space': True, 'viz_kind': 'z700_signals', 'desc': '[可视化层·回路外] 输入 = 🌍物理世界输出。显示全部真机信号: TCP 位置+姿态四元数+坐标系 · 六关节位置/速度(含关节名) · 六维力/力矩 · 夹爪开度 · 触觉 4D · 机器人电源/运行/报警/急停/碰撞 · 产线阶段 · 采样率与新鲜度 · 缺通道清单; 附状态空间旁路当前阶段/残差/接触概率', 'source': 'tools/gui/ss_bypass_view.py', 'source_symbol': 'class Z700SignalsView'}

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
