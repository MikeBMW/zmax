# -*- coding: utf-8 -*-
"""🧮 标定诊断测量 · 主参数 M (状态空间结构参数 · 等效惯量)  ·  节点 n_calib_mani

工程连线 (唯一依据 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← sscalib
    in  in2   ← sslat
    out out1  → ss_mani_eng
    out out2  → ssmani_c
    out out3  → ssmani_exp

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.n_calib_mani.<port>

实现绑定: registry key=`n_calib_mani` · src/lerobot/engineering/config_import.py:def import_config_files(
执行口径: EXEC_MODE=pure · PURE=True (口径已逐一验证 ⇒ 允许计算面真跑)
"""

NODE_ID = 'n_calib_mani'
NAME = '🧮 标定诊断测量 · 主参数 M (状态空间结构参数 · 等效惯量)'
LAYER = ''
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1', 'in2']
PORTS_OUT = ['out1', 'out2', 'out3']
PORT_LABELS = {}

IMPL_KEY = 'n_calib_mani'
SOURCE = 'src/lerobot/engineering/config_import.py'
SOURCE_SYMBOL = 'def import_config_files('
PARAMS = {'state_space': True, 'manifold_calib': True, 'kind': 'real', 'role': 'L4 标定层 — 流形引擎主标定参数 M (状态空间结构参数 / 等效惯量)', 'M': 1.0, 'M_default': 1.0, 'M_range': [0.0, 8.0], 'M_unit': '等效惯量尺度 (无量纲归一化; 物理类比 kg, 信息类比 Fisher/Hessian 曲率尺度)', 'M_meaning': 'a = F/M ⇒ Δx = F·dt²/M (有惯性二阶); M→0 ⇒ 无惯性/速度∝力 (旧 GD 过阻尼); M>0 ⇒ 状态带动量, 过渡更平滑、对突变有抑制', 'M_info': '信息论类比: 交叉熵 H(p,q) 度量“用 q 编码 p”的代价; M 是把“信息代价梯度”换成“状态加速度”的单位换算/曲率尺度 (Fisher 信息/Hessian 尺度的单标量代理)', 'M_not_free': 'M 不是拟合出来的自由参数, 而是从流形结构导出的结构参数 (曲率/维度/尺度); 现场以单标量暴露', 'inertia': False, 'inertia_default': False, 'zero_regression': 'inertia=false 或 M≤0 ⇒ 引擎行为与旧版一阶过阻尼逐位相同 (零回归)', 'source': 'src/lerobot/engineering/config_import.py', 'calib_source': 'config/calib/zmax_manifold.json → tools/zmax_params.py::manifold_M()/write_manifold_M()', 'desc': '配置中心(测量/标定/诊断) ←→ 状态空间工程 的唯一收口口; 主参数 M 为唯一主标定标量; 双击/右键真跑两臂对比 (M>0 有惯性 vs M→0 过阻尼)', 'cfg_role': '配置中心 ←→ 状态空间工程 的唯一收口口 (测量/标定/诊断 三视图 + 主参数 M)', 'cfg_entries': {'总工程文件': 'data/database/zmax/zmax_space.proj', '任务绑定': 'config/ss_task_binding.json', '任务配置': 'config/tasks/tasks.json', 'MCD描述': 'config/mcd/zmax_mcd.json', '参数注册表': 'config/mcd/param_registry.json', '模型×工程匹配': 'config/mcd/match_matrix.json', '主参数M能量标定': 'config/calib/zmax_manifold.json#_energy_derivation', '性能指标真源': 'config/platform/zmax_perf_spec.json', '工单': 'config/orders/BS_*.json', '工程库': 'data/database/zmax/zmax_engineering.db'}, 'cfg_snapshot': {'loaded_at': '2026-10-29 17:56:22', 'files_total': 8, 'files_ok': 8, 'orders': 12, 'tasks': 8, 'active_task': 'TASK-07-AOI', 'params_total': 112, 'params_ready': 93, 'params_gap': 19, 'mcd_schema': '', 'project': 'zmax_space.proj', 'project_path': '/home/ubuntu/zmax/data/database/zmax/zmax_space.proj', 'db_ok': True, 'missing': [], 'source': 'src/lerobot/engineering/config_import.py'}, 'measure_view': {'视图': '测量 Measurement (只读)', '测量量': 9, '源': ['zmax_data/rokae_sdk/tcp_out/latest.json', 'zmax_data/rokae_sdk/tcp_out/latest.json#joint', 'io_trace (ssinnov)', 'cognition (contact)', 'io_trace', 'energy_manifold'], '判据': '帧龄 <2s · 唯一依据在且值非空', '命令': 'python3 tools/config_center.py list 工程配置'}, 'calib_view': {'视图': '标定 Calibration (可写)', '可标参数': 15, '主参数M': 'M (G0 结构参数, 非自由拟合) · 范围 [0,8] · inertia 开关', 'M当前值': 3.643, 'M能级': None, 'M标定': 'python3 tools/master_param_m.py --project PROJ-TH-TRAY --write (能量标定: M=1+E_task/E_ref)', '唯一依据': 'config/calib/zmax_manifold.json → tools/zmax_params.py::write_manifold_M()', '命令': 'python3 tools/config_center.py show M'}, 'diagnose_view': {'视图': '诊断 Diagnosis (判得了)', '断言': 57, '故障码': ['MCD-E01', 'MCD-E02', 'MCD-E03', 'MCD-E04', 'MCD-E05'], '站点缺口': ['T_base_cam', 'plane_z'], '命令': 'python3 tools/config_center.py check'}, 'task_layer': {'任务数': 8, '活跃': 'TASK-07-AOI', '段覆盖': 54, '命令': 'python3 tools/ss_task_bind.py', '口径': '一个状态空间工程承载全部任务; 任务=配方段子集+参数覆盖'}, 'source_symbol': 'def import_config_files(', 'cfg_loaded_at': '2026-10-29 17:56:22', 'cfg_files': [{'name': '总工程文件', 'rel': 'data/database/zmax/zmax_space.proj', 'sha256': '6a6a884971cd85d7', 'exists': True}, {'name': '任务绑定', 'rel': 'config/ss_task_binding.json', 'sha256': '578b9d09c9959685', 'exists': True}, {'name': '任务配置', 'rel': 'config/tasks/tasks.json', 'sha256': 'c48a28fc25fd605b', 'exists': True}, {'name': 'MCD描述', 'rel': 'config/mcd/zmax_mcd.json', 'sha256': '449af2c3eb598bc0', 'exists': True}, {'name': '参数注册表', 'rel': 'config/mcd/param_registry.json', 'sha256': '31742c0009de4802', 'exists': True}, {'name': '模型×工程匹配', 'rel': 'config/mcd/match_matrix.json', 'sha256': 'afd078b5496633c6', 'exists': True}, {'name': '主参数M能量标定', 'rel': 'config/calib/zmax_manifold.json', 'sha256': 'da79bdbbbb66763d', 'exists': True}, {'name': '性能指标真源', 'rel': 'config/platform/zmax_perf_spec.json', 'sha256': 'f1114c6402f87654', 'exists': True}, {'name': '工单', 'rel': 'config/orders/BS_*.json', 'sha256': '', 'exists': True}], 'cfg_source': 'src/lerobot/engineering/config_import.py::import_config_files', 'm_role': '配置单 → 主参数 M 的**映射关系** (本节点 = 决策端); 用 M 的功能在流形引擎节点', 'm_source': 'tools/config_to_M.py', 'm_source_symbol': 'def compute_M(', 'm_task': 'TASK-07-AOI', 'm_dim': 3, 'm_mode': 'full', 'm_scale': 3.283, 'm_diag': [20.0, 20.0, 50.0], 'm_components': [4.472135955, 0.0, 4.472135955, 0.0, 0.0, 7.071067812], 'm_gain': None, 'm_energy_level': 'E3 带夹具/高速', 'm_E_task_J': 4.5655, 'm_metric': {'dim': 3, 'mode': 'full', 'diag': [20.0, 20.0, 50.0], 'components': [4.472135955, 0.0, 4.472135955, 0.0, 0.0, 7.071067812], 'gain': None}, 'm_mapping': [{'id': 'R1', 'target': 'dim', 'value': 3, 'rule': '工序含腕部姿态控制(旋转/翻转/姿态/腕部) ⇒ dim=6 (位姿 6 轴); 否则 dim=3 (位置 3 轴)', 'source': 'config/tasks/tasks.json 工序唯一依据 + metric_field 口径 (位置 3 轴 / 位姿 6 轴)', 'evidence': '工序无姿态自由度 ⇒ 位置 3 轴', 'hits': ['工序步骤无姿态控制关键词 ⇒ dim=3']}, {'id': 'R2+R3', 'target': 'mode|diag|components', 'value': 'full', 'rule': '存在平移-姿态 / 图面-深度耦合 ⇒ full; 同类轴公差比 ≥1.25 ⇒ diag; 否则 isotropic', 'source': 'config/platform/zmax_perf_spec.json (工艺公差/耦合指标) + config/tasks/tasks.json 任务配置', 'reason': '存在平移↔姿态/图面↔深度耦合证据 ⇒ 允许非对角分量的 full 度量', 'evidence': ["命中'侧边'", "命中'Δx'", "命中'手眼'", "命中'TSAI'", "命中'闭环'"], 'tolerance_sources': {'x': 'perf_spec#perf.mate_align_repeat=X/Y 各 ≤0.05 (3σ)', 'y': 'perf_spec#perf.mate_align_repeat=X/Y 各 ≤0.05 (3σ)', 'z': 'perf_spec#perf.insert_depth_res=≤0.02 (任务含插装工序 ⇒ 用插深控制分辨率)'}, 'axis_stiffness_raw': {'x': 20.0, 'y': 20.0, 'z': 50.0}, 'axis_tolerance': {'x': 0.05, 'y': 0.05, 'z': 0.02}, 'axis_order': ['x', 'y', 'z'], 'diag': [20.0, 20.0, 50.0], 'components': [4.472135955, 0.0, 4.472135955, 0.0, 0.0, 7.071067812], 'offdiag_note': '非对角(真耦合)分量待现场辨识: 有限差分敏感性 S=∂J/∂参数; 当前置 0 ⇒ 度量退化对角 (与 diag 等价), 结构已就位'}, {'id': 'R4', 'target': 'gain', 'value': None, 'rule': '动态交互场景 ⇒ 需现场辨识 G_k; 系数待标定 (缺省 0 ⇒ 常度量, 零回归)', 'source': "MCD 设计 §6 可辨识性 (有限差分敏感性) ⇒ 标'待标定' + 留实测入口", 'status': '待标定', 'evidence': ['场景 SCN-07-AOI 含实时/闭环交互 ⇒ 需要状态相关度量 G(x)'], 'expected_shape': [3, 3, 3], 'measure_hook': "现场辨识: 扫状态 x_k 量目标函数 J, 有限差分 S=∂J/∂G_k; |S| 落噪声带内 ⇒ 报'本场不可辨识'(不填假数); 写入 metric.gain 后启用"}, {'id': 'R5', 'target': 'scale', 'value': 3.283, 'rule': 'M = 1 + (½·m_eff·v_peak² + m_eff·g·h) / E_ref   →  clamp[0,8]', 'source': 'tools/master_param_m.py 能量标定唯一依据 + config/calib/zmax_calib.json#tool_payload.mass_kg + config/tasks/tasks.json 工序速度', 'project': 'PROJ-LOAD-UNLOAD', 'project_name': '上下料 (料仓/料盘 → 夹具 上料 → 卸料 → 回收)', 'm_eff_kg': 1.535, 'inputs': {'夹具/吸嘴 kg': 1.51, '工件 kg': 0.025, 'v_peak_mps': 0.25, 'stroke_m': 0.3}, 'input_sources': {'夹具/吸嘴': 'config/calib/zmax_calib.json#tool_payload.mass_kg', '工件': '唯一依据: 光模块 QSFP 级 ≈25g (master_param_m 注释)', '峰值速度': '假设(可标定) 继承 PROJ-LOAD-UNLOAD: 假设(可标定): 上下料节拍 ≤8s 下的峰值 ≈0.25 m/s', '行程': '假设(可标定): 上下料工位升降 ≈300mm (待现场确认)'}, 'E_kin_J': 0.048, 'E_pot_J': 4.5175, 'E_task_J': 4.5655, 'E_ref_J': 2.0, 'energy_level': 'E3 带夹具/高速', 'formula': 'M = 1 + (½·m_eff·v² + m_eff·g·h) / E_ref   (E_ref=2.0 J, g=9.81 m/s²)'}], 'm_audit_sha': 'e1e853a6eba6b9f5a3344596ac8cd4a2df6e1d19a98c94b8390b965c42bee01b', 'm_sources': {'tasks': 'config/tasks/tasks.json', 'bind': 'config/ss_task_binding.json', 'perf': 'config/platform/zmax_perf_spec.json', 'reg': 'config/mcd/param_registry.json', 'mcd': 'config/mcd/zmax_mcd.json', 'cc': 'config/cc_snapshot.json'}, 'm_loaded_at': '2026-10-29 17:56:22', 'pure_verified': True}

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
