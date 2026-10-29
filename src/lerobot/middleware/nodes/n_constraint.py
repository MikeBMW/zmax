# -*- coding: utf-8 -*-
"""⚖ 物理约束 · 惯性/质量率闸 (SK01-08)  ·  节点 ssphys

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← sssk1
    in  in2   ← sssk2
    in  in3   ← sssk3
    in  in4   ← sssk4
    in  in5   ← sssk5
    in  in6   ← sssk6
    in  in7   ← sssk7
    in  in8   ← sssk8
    out out1  → sslimit
    out out2  → ssinnov
    out out3  → sssensor

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssphys.<port>

实现绑定: registry key=`n_exec` · src/lerobot/policies/left_right/state_space/physics_constraints.py::InertiaLimiter.limit
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ssphys'
NAME = '⚖ 物理约束 · 惯性/质量率闸 (SK01-08)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in3', 'in4', 'in5', 'in6', 'in7', 'in8']
PORTS_OUT = ['out1', 'out2', 'out3']
PORT_LABELS = {}

IMPL_KEY = 'n_exec'
SOURCE = 'src/lerobot/policies/left_right/state_space/physics_constraints.py::InertiaLimiter.limit'
SOURCE_SYMBOL = ''
PARAMS = {'state_space': True, 'physics_gate': True, 'desc': '[基础·分段小模型] 原子技能物理闸: 进技能的 action 先过 ①速度 ②加速度 ③加加速度 ④动量/质量变化率 ⑤位移 五条约束 (每技能自带 m/F/v/a/s/jerk/dm·dt⁻¹, 数值+物理上下限唯一依据 config/calib/zmax_skill_physics.json) ⇒ 削出偏差 error; 小偏差 → 状态校正器, 大偏差 → 融合定位 → 流形引擎顶层补偿', 'source': 'src/lerobot/policies/left_right/state_space/physics_constraints.py::InertiaLimiter.limit', 'skills': {'接近': {'m_kg': 1.2, 'F_max_N': 5.0, 'v_cap_mps': 0.35, 'a_max_mps2': 4.1667, 'jerk_max_mps3': 15.0, 'dmdt_max_kg_s': 0.1, 's_step_m': 0.035, 's_max_m': 0.6, '标定唯一依据': '唯一依据(config/calib/zmax_skill_physics.json)', '唯一依据': '未夹持(只剩夹爪 1.2kg) · F=FORCE_LIMIT 5N'}, '对位': {'m_kg': 1.2, 'F_max_N': 5.0, 'v_cap_mps': 0.12, 'a_max_mps2': 4.1667, 'jerk_max_mps3': 5.143, 'dmdt_max_kg_s': 0.1, 's_step_m': 0.012, 's_max_m': 0.06, '标定唯一依据': '唯一依据(config/calib/zmax_skill_physics.json)', '唯一依据': '未夹持 · F=FORCE_LIMIT 5N'}, '下降': {'m_kg': 1.2, 'F_max_N': 5.0, 'v_cap_mps': 0.09, 'a_max_mps2': 4.1667, 'jerk_max_mps3': 3.857, 'dmdt_max_kg_s': 0.1, 's_step_m': 0.009, 's_max_m': 0.05, '标定唯一依据': '唯一依据(config/calib/zmax_skill_physics.json)', '唯一依据': '未夹持 · F=FORCE_LIMIT 5N (触到即停)'}, '抓取': {'m_kg': 1.28, 'F_max_N': 12.0, 'v_cap_mps': 0.04, 'a_max_mps2': 9.375, 'jerk_max_mps3': 2.25, 'dmdt_max_kg_s': 0.5, 's_step_m': 0.004, 's_max_m': 0.006, '标定唯一依据': '唯一依据(config/calib/zmax_skill_physics.json)', '唯一依据': '夹持建立 m 1.20→1.35 · F=夹爪最大夹持力 12N'}, '抬起': {'m_kg': 1.35, 'F_max_N': 5.0, 'v_cap_mps': 0.3, 'a_max_mps2': 3.7037, 'jerk_max_mps3': 12.857, 'dmdt_max_kg_s': 0.1, 's_step_m': 0.03, 's_max_m': 0.16, '标定唯一依据': '唯一依据(config/calib/zmax_skill_physics.json)', '唯一依据': '已夹持 1.35kg · F=FORCE_LIMIT 5N'}, '转移': {'m_kg': 1.35, 'F_max_N': 5.0, 'v_cap_mps': 0.35, 'a_max_mps2': 3.7037, 'jerk_max_mps3': 15.0, 'dmdt_max_kg_s': 0.1, 's_step_m': 0.035, 's_max_m': 0.6, '标定唯一依据': '唯一依据(config/calib/zmax_skill_physics.json)', '唯一依据': '已夹持 · 平移 · F=FORCE_LIMIT 5N'}, '插入': {'m_kg': 1.35, 'F_max_N': 2.0, 'v_cap_mps': 0.085, 'a_max_mps2': 1.4815, 'jerk_max_mps3': 3.643, 'dmdt_max_kg_s': 0.1, 's_step_m': 0.0085, 's_max_m': 0.02, '标定唯一依据': '唯一依据(config/calib/zmax_skill_physics.json)', '唯一依据': '已夹持 · **金手指保护 ≤2N** (过盈段力控)'}, '完成': {'m_kg': 1.35, 'F_max_N': 2.0, 'v_cap_mps': 0.02, 'a_max_mps2': 1.4815, 'jerk_max_mps3': 2.25, 'dmdt_max_kg_s': 0.1, 's_step_m': 0.002, 's_max_m': 0.002, '标定唯一依据': '唯一依据(config/calib/zmax_skill_physics.json)', '唯一依据': '已夹持 · 保持 · ≤2N'}, '放入': {'m_kg': 1.35, 'F_max_N': 2.0, 'v_cap_mps': 0.06, 'a_max_mps2': 1.4815, 'jerk_max_mps3': 2.571, 'dmdt_max_kg_s': 0.5, 's_step_m': 0.006, 's_max_m': 0.6, '标定唯一依据': '唯一依据(config/calib/zmax_skill_physics.json)', '唯一依据': '摆盘链第7段 · 触底开爪释放 · ≤2N 不压伤'}}, 'big_err_mps': 0.05}

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
