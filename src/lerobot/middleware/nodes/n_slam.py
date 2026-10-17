# -*- coding: utf-8 -*-
"""📡 融合定位建图  ·  节点 sssensor

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssdata
    in  in2   ← ss2d3d
    in  in3   ← sstactile
    in  in4   ← ssaoi
    in  in5   ← ssinnov
    in  in6   ← ssphys
    out out1  → ssintact, ssobs
    out out2  → ss_mani_eng

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.sssensor.<port>

实现绑定: registry key=`ss_sensor` · src/lerobot/policies/left_right/state_space/perception.py:def fuse_sensors
执行口径: EXEC_MODE=view · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'sssensor'
NAME = '📡 融合定位建图'
LAYER = ''
TYPE = 'hardware'
EXEC_MODE = 'view'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in3', 'in4', 'in5', 'in6']
PORTS_OUT = ['out1', 'out2']
PORT_LABELS = {}

IMPL_KEY = 'ss_sensor'
SOURCE = 'src/lerobot/policies/left_right/state_space/perception.py'
SOURCE_SYMBOL = 'def fuse_sensors'
PARAMS = {'state_space': True, 'desc': '[基础·分段小模型·建图] 📡 融合定位建图 = 视觉与触觉融合: 视觉(YOLO目标检测→2D→3D 坐标) + 触觉感知(4D 力/接触) + 外观质量 → 统一状态空间 (43D obs, 供 L2/L3/L4/L5 消费); 新增建图能力: 专用实现 src/lerobot/manifold/localization_mapping.py (ORB 视觉前端 + 机器人位姿真源 tcp_pose + 关键帧/地图点/回环 + 自动加载 auto_start)', 'source': 'src/lerobot/policies/left_right/state_space/perception.py', 'source_symbol': 'def fuse_sensors', 'fuse': '视觉 ⊕ 触觉 ⊕ 外观质量'}

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
