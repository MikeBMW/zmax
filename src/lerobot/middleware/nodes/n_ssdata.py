# -*- coding: utf-8 -*-
"""📦 metaworld 数据源  ·  节点 ssdata

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← (工程外注入/无上游)
    out out1  → ssintact, ssvlm, ssyolo, sstactile, ssbypv, ssllm_in, ssskill, ssmode, ssintact_dec, n_dsvl, swds, n_realscene, ss_l5
    out out2  → sssensor
    out out3  → ss_seg

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssdata.<port>

实现绑定: registry key=`data` · metaworld
执行口径: EXEC_MODE=act · PURE=False (会动设备: 只走数据面, 需 8793 授权后由引擎执行)
"""

NODE_ID = 'ssdata'
NAME = '📦 metaworld 数据源'
LAYER = ''
TYPE = 'hardware'
EXEC_MODE = 'act'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1', 'out2', 'out3']
PORT_LABELS = {}

IMPL_KEY = 'data'
SOURCE = 'metaworld'
SOURCE_SYMBOL = ''
PARAMS = {'src_switch': True, 'src_state': '插拔场景', 'source': 'metaworld', 'task': 'peg-insert-side-v3', 'frames': 4800, 'state_dim': 39, 'action_dim': 4, 'policy': 'left_right', 'run_env': True, 'state_space': True, 'desc': '[数据源层] 运行环境数据源: 仿真(metaworld 39D/4D 演示) ⇄ 真机(4060 远程只读订阅 Orin: TCP位姿+姿态/六关节/六维力/夹爪/机器人状态/图像) — 点节点上的「仿真/真机」拨钮或右键菜单切换; 双击=按当前模式运行真实模型 (🚀训练/📷推理)'}

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
