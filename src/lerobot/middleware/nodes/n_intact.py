# -*- coding: utf-8 -*-
"""🎯 INTACT (L4) · 工作安全 + 物理世界导航  ·  节点 ssintact · L4

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssdata
    in  in2   ← sssensor
    in  in3   ← ssff
    in  in4   ← sscap
    in  in5   ← ss_lora_l4
    out out1  → swintact

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssintact.<port>

实现绑定: registry key=`intact` · src/lerobot/policies/intact/service.py:def run_once(
执行口径: EXEC_MODE=view · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ssintact'
NAME = '🎯 INTACT (L4) · 工作安全 + 物理世界导航'
LAYER = 'L4'
TYPE = 'model'
EXEC_MODE = 'view'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in3', 'in4', 'in5']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'intact'
SOURCE = 'src/lerobot/policies/intact/service.py'
SOURCE_SYMBOL = 'def run_once('
PARAMS = {'desc': '[L4 策略] INTACT (zju3dv/INTACT-JEPA, MIT) 意图-动作: 共享 local/goal 动作律 + 四槽语法 [z, m_t, z⊙m_t, A(a_{t-1})] → 一次前向直接出 action chunk (**零候选搜索**, 无 CEM); **数据源直接接入 metaworld** (MT1 peg-insert-side-v3, 真渲染帧 224² + 39D 现场读); 🧩 **三路入线口径** (2026-09-16 老倪「L2 应与 L4 兼容」): in1 = 数据源真帧+39D; in2 = L2 感知融合状态 (YOLO→2D→3D→融合定位建图, L4 引擎路径 vision=True 时生效); in3 = L2 前馈蒸馏 MLP 的 u_ff (L4 档 SS_USE_MLP=1 时真身参与, 否则装配期被解析覆盖); 输出 → 意图解码器 ssintact_dec → L3; 实现 src/lerobot/policies/intact/modeling_intact.py (2026-09-13 从 manifold/intact_node 迁移) · 设计 docs/design/zmax_l4_intact_policy.md\n\n🗂 代码落位 (v5.5.43 编排已下沉 policy 层): 编排 service.py (run_once) · 策略壳 modeling_intact.py · 节点 runtime/node.py', 'expert': True, 'state_space': True, 'intact': True, 'data_source': 'metaworld', 'decoder': 'ssintact_dec', 'source': 'src/lerobot/policies/intact/service.py', 'source_symbol': 'def run_once(', 'source_note': '编排 service.py (run_once) · 策略壳 modeling_intact.py · 节点 runtime/node.py'}

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
