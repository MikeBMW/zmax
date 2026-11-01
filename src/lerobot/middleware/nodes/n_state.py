# -*- coding: utf-8 -*-
"""🧩 SU(2) 统一状态空间 (二阶特殊酉群)  ·  节点 ssobs

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← sssensor
    out out1  → ssff, ssreason, ssvideo, ss_moe, n_geoplan
    out out2  → ssest
    out out3  → ss_mani_eng

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssobs.<port>

实现绑定: registry key=`ss_obs` · src/lerobot/policies/left_right/state_space/su2.py:class SU2UnifiedState
执行口径: EXEC_MODE=view · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

import os

NODE_ID = 'ssobs'
NAME = '🧩 SU(2) 统一状态空间 (二阶特殊酉群)'
LAYER = ''
TYPE = 'system'
EXEC_MODE = 'view'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1', 'out2', 'out3']
PORT_LABELS = {}

IMPL_KEY = 'ss_obs'
SOURCE = 'src/lerobot/policies/left_right/state_space/su2.py'
SOURCE_SYMBOL = 'class SU2UnifiedState'
PARAMS = {'state_space': True, 'su2_unified_state': True, 'group': 'SU(2) = {U ∈ C^2x2 : U†U = I, det U = 1}', 'map_law': 'ω = π·tanh(gain·‖v‖)·v̂ (有界映射律, θ<π 不绕圈, 方向保留)', 'blocks': 'L2=43D obs 几何误差 | L3=流形规划(进度/偏离/剩余) | L4=安全动作(u_sat/接触/η) | L5=大模型意图', 'observables': 'θ偏离角 / n̂状态方向 / |w|收敛度 / 逐层剥离贡献 / 层间不可交换性 / Fubini-Study 距离', 'viz_tools': 'Bloch球 + S³分量 + 层贡献 + 反演剥离 + 距离矩阵 + 节点映射 (双击开观测面板)', 'desc': '[统一状态·群] SU(2) 二阶特殊酉群: 原 43D 统一状态向量降为群里的 L2 输入块; 全部层(L2/L3/L4/L5)与全部节点数据按有界映射律映成群元素, 群乘法=层合成(不可交换=层间耦合), 反演剥离读每层贡献; 群恒等元 ⇔ 场景收敛', 'source': 'src/lerobot/policies/left_right/state_space/su2.py', 'source_symbol': 'class SU2UnifiedState'}

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


# 🧩 理想档 (2026-11-01 老倪「先让状态空间发出理想的值」):
#   不在节点里另造一套 43D 语义 —— 直接调 engineering/nodes/ideal_obs.py,
#   它把「工艺动作表」(geo_plan_impl.build_ideal_plan: 112 步/45.05s/4件/320UPH) 的
#   当前步翻成 43D 观察量 (米), 通道划分与 su2.py::obs43_geometry 同一口径。
#   out1 = 43D (下游 ssff/ssreason/ss_moe/n_geoplan 照旧吃), out2/out3 带同一帧的
#   SU(2) 群元素与元信息 (段号/动作/UPH), 逐拍落 ss_live/ss_obs_ideal.json 供核对。
# src/lerobot/middleware/nodes/n_state.py → 上五层 = 仓库根 (少一层就写到 src/zmax_data 里, 静默不落盘)
_IDEAL_LIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))), "zmax_data", "ss_live", "ss_obs_ideal.json")


def _ideal_compute(ctx):
    """理想档一个周期: 工艺动作 → 43D 统一状态向量。"""
    global LAST_STATUS
    import json as _j
    import time as _t
    from lerobot.engineering.nodes import geo_plan_impl as _G              # noqa: PLC0415
    from lerobot.engineering.nodes import ideal_obs as _IO                 # noqa: PLC0415
    doc = _G.build_ideal_plan(h=8)
    obs, meta = _IO.frame(doc)
    try:
        from lerobot.policies.left_right.state_space import su2 as _su2    # noqa: PLC0415
        grp = _su2.encode_obs43(obs)
        # SU2Element 只有 w/x/y/z (__slots__) —— theta 是 property 不是方法, 取标量四元数即可
        elem = {"w": round(float(grp.w), 6), "x": round(float(grp.x), 6),
                "y": round(float(grp.y), 6), "z": round(float(grp.z), 6)}
    except Exception as _e:                                                # noqa: BLE001
        elem = {"err": "%s: %s" % (type(_e).__name__, _e)}
    try:
        _tmp = _IDEAL_LIVE + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as _fh:
            _j.dump(dict(meta, obs=[round(float(x), 6) for x in obs], su2=elem,
                         ts=_t.time()), _fh, ensure_ascii=False)
        os.replace(_tmp, _IDEAL_LIVE)
    except Exception:                                                      # noqa: BLE001
        pass
    LAST_STATUS = ("理想 43D: 步 %d/%d %s · %.0f UPH · e=%.1fmm"
                   % (meta["step_i"], meta["step_n"], meta["action"], meta["uph"],
                      _err_mm(obs)))
    return {"out1": {"value": {"obs": [float(x) for x in obs], "dim": int(obs.size),
                               "src": "ssobs 理想档(工艺动作→43D)", "t_str": meta["t_str"]},
                     "age_s": 0.0, "fresh": True},
            "out2": {"value": elem, "age_s": 0.0, "fresh": True},
            "out3": {"value": meta, "age_s": 0.0, "fresh": True}}


def _vec(x):
    try:
        return list(x)
    except Exception:                                                      # noqa: BLE001
        return [0.0, 0.0, 1.0]


def _err_mm(obs):
    try:
        import numpy as _np
        from lerobot.policies.left_right.state_space import su2 as _su2
        return float(_np.linalg.norm(_su2.obs43_geometry(obs)) * 1000.0)
    except Exception:                                                      # noqa: BLE001
        return -1.0


def compute(ctx):
    """一个周期: ctx 来自总线 → 返回要发回总线的输出。

    PURE=False 时只做直通 (数据面), 不调用真实现 —— 避免未验证/未授权的节点被自动执行。
    理想档 (env ZMAX_SS_IDEAL=1 / params.ideal) 优先: 发 43D 理想观察量。
    """
    global LAST_STATUS
    try:
        from lerobot.engineering.nodes import ideal_obs as _IO2            # noqa: PLC0415
        if _IO2.ideal_on(ctx):
            return _ideal_compute(ctx)
    except Exception as _e:                                                # noqa: BLE001
        LAST_STATUS = "理想档不可用(%s) → 走原路" % _e
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
        # 🔴 2026-10-29: 实现层需要知道"自己是哪个节点" —— 同一实现服务多个节点时靠这个分派
        #   (如 node_ss_mani 同时服务 ssmani_c 接触流形 / ssmani_p 性能流形, 只看 ctx["name"])。
        #   原来 ctx 里只有端口 (in1→{"value":…}), 常驻循环里实现拿到 name="" ⇒ 直接 return False。
        #   这里补元信息: 键名不与端口冲突 (端口是 inN/outN), 且不参与 _passthrough 取数。
        _mctx = dict(ctx)
        _mctx.setdefault("name", NAME)
        _mctx.setdefault("params", dict(PARAMS))
        _mctx.setdefault("id", NODE_ID)
        _mctx.setdefault("_node", {"id": NODE_ID, "name": NAME, "params": dict(PARAMS),
                                   "ports_in": list(PORTS_IN), "ports_out": list(PORTS_OUT)})
        try:
            res = fn(_mctx)                     # 约定: 接 ctx 的实现
        except TypeError:
            res = fn()                          # 老实现: 无参
        if isinstance(res, dict):
            LAST_STATUS = "实现执行"
            _out = {k: v for k, v in res.items() if k in PORTS_OUT}
            if not _out and PORTS_OUT:
                # 实现返回的是**业务结果字典**(键是 M/ok/progress 这类, 不是端口名)
                # ⇒ 整块当首端口的值发出去, 不能过滤成空 dict 把数据丢掉
                # (2026-10-29: 流形引擎族就是这样, 原来 out 恒为空, 下游永远拿不到)
                _out = {PORTS_OUT[0]: res}
            return _out
        LAST_STATUS = "实现返回非 dict → 直通"
        return _passthrough(ctx)
    except Exception as e:                                          # noqa: BLE001
        LAST_STATUS = "实现异常(%s: %s) → 直通" % (type(e).__name__, e)
        return _passthrough(ctx)
