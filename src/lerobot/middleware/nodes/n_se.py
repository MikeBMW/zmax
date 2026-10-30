# -*- coding: utf-8 -*-
"""🌍 万有引力 · SE(3) 几何阻抗 + H=K+U (力场仲裁)  ·  节点 ss_grav_h

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssvlm
    in  in2   ← ssintact
    in  in3   ← ssdec
    in  in4   ← sssched
    in  in5   ← sslimit
    in  in6   ← ssz700
    out out1  → n_moveit
    out out2  → n_exec

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ss_grav_h.<port>

实现绑定: registry key=`ss_grav_h` · src/lerobot/manifold/state_space_energy.py:class StateSpaceHamiltonian
执行口径: EXEC_MODE=pure · PURE=True (口径已逐一验证 ⇒ 允许计算面真跑)
"""

NODE_ID = 'ss_grav_h'
NAME = '🌍 万有引力 · SE(3) 几何阻抗 + H=K+U (力场仲裁)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2', 'in3', 'in4', 'in5', 'in6']
PORTS_OUT = ['out1', 'out2']
PORT_LABELS = {}

IMPL_KEY = 'ss_grav_h'
SOURCE = 'src/lerobot/manifold/state_space_energy.py'
SOURCE_SYMBOL = 'class StateSpaceHamiltonian'
PARAMS = {'state_space': True, 'gravity_field': True, 'kind': 'real', 'role': '全层力场仲裁 — 势能 U 决定允许方向, 动能 K 决定代价, H=K+U 判被动性', 'formula_U': 'U = ½·ξ_eᵀ K ξ_e + Σ_l ½·s_l·ξ_eᵀ K ξ_e  (Σ_l s_l = 1) + U_grav', 'formula_K': 'K = ½·ξᵀ Λ ξ,  Λ = diag(m,m,m,Ix,Iy,Iz)', 'formula_H': 'H = K + U ;  ξ̇ = Λ⁻¹(F − Bξ) ;  Ḣ = −ξᵀBξ ≤ 0 (交叉项精确抵消)', 'formula_F': 'F_l = s_l·K ξ_e  (逐层力) ;  Σ_l F_l = K ξ_e (恒等式)', 'K_diag': '平移 [k_lat,k_lat,k_ax]=[80,80,400] N/m · 旋转 [2,2,10] N·m/rad', 'layer_share': 'L2 0.30 · L3 0.25 · L4 0.30 · L5 0.15 (Σ=1)', 'mass_kg': 3.643, 'inertia': '[0.020,0.020,0.012] kg·m² (DEFAULT, 真机标定后由 config/calib/hamiltonian.json 覆盖)', 'alpha': 0.15, 'gravity_G': '未配置 ⇒ U_grav 记 0 (不造数)', 'source': 'src/lerobot/manifold/state_space_energy.py', 'source_symbol': 'class StateSpaceHamiltonian', 'reuse': 'se3_impedance.py(potential/pose_error/K_INSERT) · se3_gravity_provider.py(_rpy_to_T) · lie_intent.py(se3_exp/log)', 'measured': '12/12 判据 PASS: U(2cm)=0.080000J · K(0.1m/s)=0.018215J · H 1200 步单调不增 7.999e-02→8.006e-10 · Ḣ 解析 vs 数值 相对差 0.070% · 末端残余 0.0013mm', 'spec_target': 'Ḣ≤0 (被动) · ΣF_l=F 残差<1e-12 · 层动作横向>60° veto', 'caveat': '惯量/质量为默认标定值(DEFAULT, 非真机实测); 无 G 配置时引力项=0; 力矩通道默认关, 需 L2 显式授权', 'desc': '万有引力=势场: 每层动作只保留沿 −∇U 的分量(横向>60°否决), 输出 u=[F;M] 与能量 H=K+U; 被动性由 Ḣ=−ξᵀBξ 结构保证', 'pure_verified': True}

# 计算面开关: False = 只走数据面(直通 outN←inN), 不自动执行实现
PURE = True
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


def compute_n_se(ctx):
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


# 🔎 2026-10-31 老倪「Call Stack 要能看出是哪个画布节点」: 真名是 compute_n_se (帧名可见),
#   中间件接口名仍叫 compute (Node.compute 找 module.compute, 别名保持兼容)。
compute = compute_n_se
