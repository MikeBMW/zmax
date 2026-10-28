# -*- coding: utf-8 -*-
"""运动规划  ·  节点 n_moveit

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← sssk1, sssk2, sssk3, sssk4
    in  in2   ← sssk5, sssk6, sssk7, sssk8, ssdec
    in  in3   ← ss_grav_h
    out out1  → n_exec

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.n_moveit.<port>

实现绑定: registry key=`n_moveit`
执行口径: EXEC_MODE=act · PURE=False (会动设备: 只走数据面, 需 8793 授权后由引擎执行)
"""

NODE_ID = 'n_moveit'
NAME = '运动规划'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'act'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in3']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'n_moveit'
SOURCE = 'src/lerobot/engineering/nodes/plan_impl.py'
SOURCE_SYMBOL = 'def run'
PARAMS = {'layer': 'L2', 'role': '意图/技能 → 段表 (规划); 不下发、不碰执行器', 'backends': ['orin_sdk_bridge (xCoreSDK 直连, 默认/效率优先)', 'ros2_srv (兼容现有 /move_pose)'], 'sdk_bridge': 'http://192.168.23.66:39061', 'controller': '192.168.23.160', 'safety': 'Δ守卫 · 向下限幅 · dry-run 默认 · 现场闸门', 'src': 'src/lerobot/arm/arm_control.py', 'parity': 'SDK vs ROS2 关节最大偏差 0.91 µrad (2026-09-26 实测)', 'bridge_vff': False, 'bridge_vff_cap_mms': 10.0, 'bridge_vff_deadband_mms': 3.0, 'bridge_vff_src': 'SS-EPI-CORNER 仿真 v_ff (只取方向)', 'bridge_vff_cap_hard_mms': 10.0, 'station_link': True}

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
