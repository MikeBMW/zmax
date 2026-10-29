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
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
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
PARAMS = {'state_space': True, 'manifold_calib': True, 'kind': 'real', 'role': 'L4 标定层 — 流形引擎主标定参数 M (状态空间结构参数 / 等效惯量)', 'M': 1.0, 'M_default': 1.0, 'M_range': [0.0, 8.0], 'M_unit': '等效惯量尺度 (无量纲归一化; 物理类比 kg, 信息类比 Fisher/Hessian 曲率尺度)', 'M_meaning': 'a = F/M ⇒ Δx = F·dt²/M (有惯性二阶); M→0 ⇒ 无惯性/速度∝力 (旧 GD 过阻尼); M>0 ⇒ 状态带动量, 过渡更平滑、对突变有抑制', 'M_info': '信息论类比: 交叉熵 H(p,q) 度量“用 q 编码 p”的代价; M 是把“信息代价梯度”换成“状态加速度”的单位换算/曲率尺度 (Fisher 信息/Hessian 尺度的单标量代理)', 'M_not_free': 'M 不是拟合出来的自由参数, 而是从流形结构导出的结构参数 (曲率/维度/尺度); 现场以单标量暴露', 'inertia': False, 'inertia_default': False, 'zero_regression': 'inertia=false 或 M≤0 ⇒ 引擎行为与旧版一阶过阻尼逐位相同 (零回归)', 'source': 'src/lerobot/engineering/config_import.py', 'calib_source': 'config/calib/zmax_manifold.json → tools/zmax_params.py::manifold_M()/write_manifold_M()', 'desc': '配置中心(测量/标定/诊断) ←→ 状态空间工程 的唯一收口口; 主参数 M 为唯一主标定标量; 双击/右键真跑两臂对比 (M>0 有惯性 vs M→0 过阻尼)', 'cfg_role': '配置中心 ←→ 状态空间工程 的唯一收口口 (测量/标定/诊断 三视图 + 主参数 M)', 'cfg_entries': {'性能指标唯一依据': 'config/platform/zmax_perf_spec.json', '主参数M能量标定': 'config/calib/zmax_manifold.json#_energy_derivation', 'mcd_描述': 'config/mcd/zmax_mcd.json', '参数注册表': 'config/mcd/param_registry.json', '模型×工程匹配': 'config/mcd/match_matrix.json', '任务配置': 'config/tasks/tasks.json', '任务绑定': 'config/ss_task_binding.json', '工单目录': 'config/orders/ (BS_*.json)', '工程文件': 'data/database/zmax/zmax_space.proj', '站点标定': 'config/calib/zmax_calib.json', '流形标定': 'config/calib/zmax_manifold.json'}, 'cfg_snapshot': {'mcd_schema': 'zmax-mcd/1.0', 'mcd_generated_at': '2026-10-14 15:00:16', 'params_total': 112, 'params_ready': 92, 'params_gap': 20, 'by_domain': {'工程配置': 9, '性能配置': 64, '功能配置': 3, '模型配置': 36}, 'gaps': ['T_base_cam', 'plane_z', 'cell_geometry.points', 'safety.saturate', 'safety.veto_th', 'perf.D_INSERT_mm', 'perf.cycle_s', 'feature.cap_level', 'feature.dbc_version', 'model.arch_mode', 'model.third_party', 'perf.contact_pressure', 'perf.mate_life', 'perf.coplanarity', 'perf.conn_mate_force', 'perf.mtbf', 'perf.anomaly_recovery', 'perf.cleanliness', 'perf.temp_hum', 'perf.noise'], 'tasks': 7, 'active_task': 'TASK-01-FW', 'orders': 5, 'assertions': 57, 'assertions_auto': 47, 'by_level': {'L2': 38, 'L3': 8, 'L4': 11}, 'models_matched': '9/10', 'models_blocked': ['L4.intact'], 'site_missing': ['T_base_cam', 'plane_z', 'cell_geometry.points'], 'project': {'file': 'data/database/zmax/zmax_space.proj', 'canvas_md5': 'a7ced3e515509537b044d872e326168e', 'nodes': 91, 'links': 204}, 'node_readback_at': None, 'perf_metrics': {'总条数': 58, '分组': [['A', 12], ['B', 8], ['C', 10], ['D', 12], ['E', 8], ['F', 8]], '目标值待确认': 9, '口径': '指标定义+目标值/规格; 实测值待验收阶段填入 (不以设计值冒充实测值)'}, 'master_M': {'M': 3.643, 'inertia': False, '能级': None, 'E_task_J': None, '公式': None, '项目': '—'}}, 'measure_view': {'视图': '测量 Measurement (只读)', '测量量': 9, '源': ['zmax_data/rokae_sdk/tcp_out/latest.json', 'zmax_data/rokae_sdk/tcp_out/latest.json#joint', 'io_trace (ssinnov)', 'cognition (contact)', 'io_trace', 'energy_manifold'], '判据': '帧龄 <2s · 唯一依据在且值非空', '命令': 'python3 tools/config_center.py list 工程配置'}, 'calib_view': {'视图': '标定 Calibration (可写)', '可标参数': 15, '主参数M': 'M (G0 结构参数, 非自由拟合) · 范围 [0,8] · inertia 开关', 'M当前值': 3.643, 'M能级': None, 'M标定': 'python3 tools/master_param_m.py --project PROJ-TH-TRAY --write (能量标定: M=1+E_task/E_ref)', '唯一依据': 'config/calib/zmax_manifold.json → tools/zmax_params.py::write_manifold_M()', '命令': 'python3 tools/config_center.py show M'}, 'diagnose_view': {'视图': '诊断 Diagnosis (判得了)', '断言': 57, '故障码': ['MCD-E01', 'MCD-E02', 'MCD-E03', 'MCD-E04', 'MCD-E05'], '站点缺口': ['T_base_cam', 'plane_z', 'cell_geometry.points'], '命令': 'python3 tools/config_center.py check'}, 'task_layer': {'任务数': 7, '活跃': 'TASK-01-FW', '段覆盖': 52, '命令': 'python3 tools/ss_task_bind.py', '口径': '一个状态空间工程承载全部任务; 任务=配方段子集+参数覆盖'}, 'source_symbol': 'def import_config_files(', 'cfg_loaded_at': '2026-10-14 17:40:48', 'cfg_files': [{'name': '总工程文件', 'rel': 'data/database/zmax/zmax_space.proj', 'sha256': '859951b97932d742', 'exists': True}, {'name': '任务绑定', 'rel': 'config/ss_task_binding.json', 'sha256': 'c0cc794a29873532', 'exists': True}, {'name': '任务配置', 'rel': 'config/tasks/tasks.json', 'sha256': '316d258c57b2de45', 'exists': True}, {'name': 'MCD描述', 'rel': 'config/mcd/zmax_mcd.json', 'sha256': 'b7fb51be1ebdc543', 'exists': True}, {'name': '参数注册表', 'rel': 'config/mcd/param_registry.json', 'sha256': 'e4bd4ff992f9f054', 'exists': True}, {'name': '模型×工程匹配', 'rel': 'config/mcd/match_matrix.json', 'sha256': 'c0975b334974bac5', 'exists': True}, {'name': '主参数M能量标定', 'rel': 'config/calib/zmax_manifold.json', 'sha256': 'c1daa6fdf659d5ca', 'exists': True}, {'name': '性能指标唯一依据', 'rel': 'config/platform/zmax_perf_spec.json', 'sha256': '1bb010da5a848cc0', 'exists': True}, {'name': '工单', 'rel': 'config/orders/BS_*.json', 'sha256': '', 'exists': True}], 'cfg_source': 'src/lerobot/engineering/config_import.py::import_config_files', 'm_role': '配置单 → 主参数 M 的**映射关系** (本节点 = 决策端); 用 M 的功能在流形引擎节点', 'm_source': 'tools/config_to_M.py', 'm_source_symbol': 'def compute_M(', 'm_task': 'TASK-01-FW', 'm_dim': 6, 'm_mode': 'diag', 'm_scale': 3.643, 'm_diag': [10.0, 10.0, 50.0, 10.0, 10.0, 10.0], 'm_components': None, 'm_gain': None, 'm_energy_level': 'E3 带夹具/高速', 'm_E_task_J': 5.285, 'm_metric': {'dim': 6, 'mode': 'diag', 'diag': [10.0, 10.0, 50.0, 10.0, 10.0, 10.0], 'components': None, 'gain': None}, 'm_mapping': [{'id': 'R1', 'target': 'dim', 'value': 6, 'rule': '工序含腕部姿态控制(旋转/翻转/姿态/腕部) ⇒ dim=6 (位姿 6 轴); 否则 dim=3 (位置 3 轴)', 'source': 'config/tasks/tasks.json 工序唯一依据 + metric_field 口径 (位置 3 轴 / 位姿 6 轴)', 'evidence': '工序要求腕部姿态控制 ⇒ 位姿 6 轴', 'hits': ["step[翻转]: 命中'旋转' ← 腕部旋转180°(150°/s), 模块标签面朝下, 金手指面朝上"]}, {'id': 'R2+R3', 'target': 'mode|diag|components', 'value': 'diag', 'rule': '存在平移-姿态 / 图面-深度耦合 ⇒ full; 同类轴公差比 ≥1.25 ⇒ diag; 否则 isotropic', 'source': 'config/platform/zmax_perf_spec.json (工艺公差/耦合指标) + config/tasks/tasks.json 任务配置', 'reason': '同类轴公差比 5.00 ≥ 1.25 ⇒ 各轴刚度不等 ⇒ diag 度量', 'evidence': ['ε_xy=0.1 mm · ε_z=0.02 mm ⇒ 比 5.00'], 'tolerance_sources': {'x': 'tasks.steps[对位].desc=视觉定位QSFP插座导向槽, 末端移动到(X=2.5,Y=0,Z=1.26), 偏差<0.1mm', 'y': 'tasks.steps[对位].desc=视觉定位QSFP插座导向槽, 末端移动到(X=2.5,Y=0,Z=1.26), 偏差<0.1mm', 'z': 'perf_spec#perf.insert_depth_res=≤0.02 (任务含插装工序 ⇒ 用插深控制分辨率)', 'rx': 'perf_spec#perf.mate_angle_repeat=≤0.10 (绕插轴/俯仰)', 'ry': 'perf_spec#perf.mate_angle_repeat=≤0.10 (绕插轴/俯仰)', 'rz': 'perf_spec#perf.mate_angle_repeat=≤0.10 (绕插轴/俯仰)'}, 'axis_stiffness_raw': {'x': 10.0, 'y': 10.0, 'z': 50.0, 'rx': 10.0, 'ry': 10.0, 'rz': 10.0}, 'axis_tolerance': {'x': 0.1, 'y': 0.1, 'z': 0.02, 'rx': 0.1, 'ry': 0.1, 'rz': 0.1}, 'axis_order': ['x', 'y', 'z', 'rx', 'ry', 'rz'], 'diag': [10.0, 10.0, 50.0, 10.0, 10.0, 10.0], 'components': None}, {'id': 'R4', 'target': 'gain', 'value': None, 'rule': '动态交互场景 ⇒ 需现场辨识 G_k; 系数待标定 (缺省 0 ⇒ 常度量, 零回归)', 'source': "MCD 设计 §6 可辨识性 (有限差分敏感性) ⇒ 标'待标定' + 留实测入口", 'status': '待标定', 'evidence': ['场景 SCN-01-FW 含实时/闭环交互 ⇒ 需要状态相关度量 G(x)'], 'expected_shape': [6, 6, 6], 'measure_hook': "现场辨识: 扫状态 x_k 量目标函数 J, 有限差分 S=∂J/∂G_k; |S| 落噪声带内 ⇒ 报'本场不可辨识'(不填假数); 写入 metric.gain 后启用"}, {'id': 'R5', 'target': 'scale', 'value': 3.643, 'rule': 'M = 1 + (½·m_eff·v_peak² + m_eff·g·h) / E_ref   →  clamp[0,8]', 'source': 'tools/master_param_m.py 能量标定唯一依据 + config/calib/zmax_calib.json#tool_payload.mass_kg + config/tasks/tasks.json 工序速度', 'project': 'PROJ-LOAD-UNLOAD', 'project_name': '上下料 (料仓/料盘 → 夹具 上料 → 卸料 → 回收)', 'm_eff_kg': 1.535, 'inputs': {'夹具/吸嘴 kg': 1.51, '工件 kg': 0.025, 'v_peak_mps': 1.0, 'stroke_m': 0.3}, 'input_sources': {'夹具/吸嘴': 'config/calib/zmax_calib.json#tool_payload.mass_kg', '工件': '唯一依据: 光模块 QSFP 级 ≈25g (master_param_m 注释)', '峰值速度': "工序唯一依据 step[分拣] 命中'1.0m/s' (tasks.json)", '行程': '假设(可标定): 上下料工位升降 ≈300mm (待现场确认)'}, 'E_kin_J': 0.7675, 'E_pot_J': 4.5175, 'E_task_J': 5.285, 'E_ref_J': 2.0, 'energy_level': 'E3 带夹具/高速', 'formula': 'M = 1 + (½·m_eff·v² + m_eff·g·h) / E_ref   (E_ref=2.0 J, g=9.81 m/s²)'}], 'm_audit_sha': 'c9c9cd505ac03650bc9ea71bbc0563c8b811c352678f6f640e0a11ddfd040b8a', 'm_sources': {'tasks': 'config/tasks/tasks.json', 'bind': 'config/ss_task_binding.json', 'perf': 'config/platform/zmax_perf_spec.json', 'reg': 'config/mcd/param_registry.json', 'mcd': 'config/mcd/zmax_mcd.json', 'cc': 'config/cc_snapshot.json'}, 'm_loaded_at': '2026-10-14 16:55:49'}

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
