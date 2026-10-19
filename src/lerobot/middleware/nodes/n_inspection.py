# -*- coding: utf-8 -*-
"""🔍 光学质量检测  ·  节点 ssaoi

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
    in  in1   ← ssyolo
    out out1  → sssched, sssensor

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.ssaoi.<port>

实现绑定: registry key=`ss_aoi`
执行口径: EXEC_MODE=pure · PURE=False (数据面直通; 逐个验证口径后再置 True)
"""

NODE_ID = 'ssaoi'
NAME = '🔍 光学质量检测'
LAYER = 'L2'          # 2026-10-19 老倪: 光学质量检测归 L2 (感知原语, 与 🎯 YOLO / 🧩 分割同级)
                      #   能力落 L2(图像 → 质量判决), 意图落 L5, 不进 L3/L4。
TYPE = 'model'
EXEC_MODE = 'pure'

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = ['in1']
PORTS_OUT = ['out1']
PORT_LABELS = {}

IMPL_KEY = 'ss_aoi'
SOURCE = ''
SOURCE_SYMBOL = ''
PARAMS = {'target': '金手指/端面/外观', 'state_space': True, 'desc': '[基础·分段小模型] 感知层·B5 外观质量检测 (AOI): 金手指划痕/端面脏污/外观缺陷判定 → 上报监控 (良率支撑)。【2026-09-20 接线·v4.2 几何】原始图 → 状态空间区域检测/伺服引导: ①区域检测 GET /region?grab=1 = 原始图坐标系的**金手指区域**(只含焊盘排, 实测~1455x70; 不含下方实心金带与塑料亮边沿) + 对焦清晰度 focus ②触发检测 POST /capture_detect (异步, 判决只打工控机终端) ③规范化裁剪 GET /picture?kind=crop = **金手指纵向拉长到 960x960 方图**(与 imgsz=960 对齐, 喂 YOLO); GET /picture?kind=natural = 原比例 1455x70(目检); GET /crop_info = 指标(残余倾角/金覆盖/高亮占比) ④对准+对焦伺服 L2.aoi_gold_align → tools/aoi_gold_servo.py (区域偏差→L2小步进; 沿光轴退火找 focus 峰值; 默认 dry-run) 【2026-10-08 取像参数与「根数不稳」真根因 · 已并进 yolo_3d/quality_check.py::AOIQualityChecker】① 这台金手指相机(SN D265250070, OPT-LCRT1500)出厂**自动曝光/自动增益是开着的** ⇒ 对 ExposureTime/Gain 的写入一律 rv=100100010 **静默失败**, 文件里的 10000us 从未生效; ② 相机于是拉 ~94ms 超长曝光硬扛 ⇒ 恒定过曝(条带 20~32% 像素≥250) ⇒ 金手指之间的暗缝被糊白**桥接**成一条宽亮段 ⇒ 判据图上根数 19/21/22 反复; 画面发糊同源(**不是对焦** —— 该机手动定焦, 软件里没有对焦节点); ③ 处方(顺序不可换, 逐条 rv=0 实测): ExposureAuto→Off → GainAuto→Off → ExposureTime → Gain → Gamma; **禁用「停采集→写→恢复采集」**(实测 StartGrabbing 卡死, 整路相机死掉); ④ 定值: 曝光 20000us × 增益 8.0(扫档: 片p50=206 / 缝p10=49, 对比度157 vs 其它档 33~34; 曝光仅自动档 1/5 ⇒ 更锐); 范围 曝光1~1e7us · 增益1.33~16.38(写1.0会被拒) · Gamma 0~3.999; ⑤ 现场光源偏暗是客观事实(10000us 下整幅均值仅16, 最亮区94, 要~9倍补偿) ⇒ 先查灯, 程序侧用「高增益+短曝光」换锐度; ⑥ 同一次挖出的判据渲染 bug: 局部变量 `gate` 覆盖了同名参数 dict ⇒ 暗帧必抛 AttributeError, 判据图整个报错(已改名 edge_gate); ⑦ 用法: AOIQualityChecker().assess_frame(帧) → ok / too_dark / overexposed / gaps_washed + 还差几倍(need_x); 取像参数不健康时 check() **不报 PASS**(参数错的帧上谈缺陷判定没有意义)。自检: gui-venv311/bin/python src/lerobot/policies/yolo_3d/quality_check.py 【产线/调试分工 (2026-10-08)】产线程序跑在工控机 192.168.23.23(10082 金手指/10083 表面), 改产线必须经 tools/aoi_remote_deploy.py(哈希核对+失败回滚); 调试程序跑在本节点: 本仓库 tools/aoi/ 里的同名副本 + quality_check.py::AOIQualityChecker(取像参数/画面健康度/缺陷判据三类逻辑都在这个类里); 两边对齐用 tools/aoi/production_sync.py status|verify|diff|pull。', 'aoi_interfaces': {'region': 'http://192.168.23.23:10082/region?grab=1', 'capture': 'http://192.168.23.23:10082/capture_detect', 'picture_origin': 'http://192.168.23.23:10082/picture', 'picture_crop_stretched_960': 'http://192.168.23.23:10082/picture?kind=crop', 'picture_crop_natural': 'http://192.168.23.23:10082/picture?kind=natural', 'crop_quality': 'http://192.168.23.23:10082/crop_info', 'servo_skill': 'L2.aoi_gold_align'}, 'crop_geometry_v4_2': {'golden_fingers_native': '1455x70 (焊盘排, 21:1)', 'canonical_for_yolo': '960x960 (纵向拉伸填满, 与 imgsz=960 对齐)', 'excluded': '下方实心金带(y1180-1265) 与 塑料本体亮边沿(y>=1258)', 'quality_metric': '残余倾角 -0.94~0.61 px/1000 (在原比例版上算)'}, 'camera_params': {'sn': 'D265250070', 'model': 'OPT-LCRT1500 / CC1-GG50', 'exposure_us': 20000.0, 'gain_db': 8.0, 'gamma': 1.0, 'exposure_range': [1.0, 10000000.0], 'gain_range': [1.33, 16.38], 'must_disable_auto_first': ['ExposureAuto', 'GainAuto'], 'init_order': ['ExposureAuto=Off', 'GainAuto=Off', 'ExposureTime', 'Gain', 'Gamma'], 'source': 'src/lerobot/policies/yolo_3d/quality_check.py :: AOIQualityChecker.CAMERA', 'sweep_evidence': {'20000x8': [206, 49, 157], '30000x8': [149, 115, 34], '60000x4': [150, 115, 34], '120000x2': [146, 113, 33]}}, 'quality_verdicts': ['ok', 'too_dark', 'overexposed', 'gaps_washed'], 'architecture': '产线程序运行在工控机 192.168.23.23 (10082 金手指 / 10083 表面); 调试程序运行在状态空间工程的这个 AOI 质量检查节点 (src/lerobot/policies/yolo_3d/quality_check.py::AOIQualityChecker + tools/aoi/ 副本)', 'production': {'host': '192.168.23.23', 'finger': {'port': 10082, 'remote_file': 'D:\\xspace\\ultralytics_AOI\\cam_finger_10082_work_v20.py', 'repo_copy': 'tools/aoi/cam_finger_10082_work_v24.py', 'endpoints': {'region': '/region?grab=1', 'capture_detect': '/capture_detect', 'picture': '/picture?kind=crop|natural|origin', 'crop_info': '/crop_info', 'param': '/param', 'last_result': '/last_result', 'storage': '/storage'}}, 'surface': {'port': 10083, 'remote_file': 'D:\\xspace\\ultralytics_AOI\\cam_surface_10083_work_v20.py', 'repo_copy': 'tools/aoi/cam_surface_10083_work_v20.py'}, 'sync_tool': 'tools/aoi/production_sync.py', 'deploy_tool': 'tools/aoi_remote_deploy.py', 'runtime_tool': 'tools/aoi_remote_run.py', 'manifest': 'tools/aoi/PRODUCTION_MANIFEST.json'}, 'debug': {'class': 'src/lerobot/policies/yolo_3d/quality_check.py :: AOIQualityChecker', 'params_source': 'AOIQualityChecker.CAMERA (曝光/增益/Gamma + 下发顺序)', 'frame_health': 'AOIQualityChecker.assess_frame() → ok/too_dark/overexposed/gaps_washed + need_x', 'defect_rules': 'AOIQualityChecker.check() → DET-AOI-01~04', 'self_test': 'gui-venv311/bin/python src/lerobot/policies/yolo_3d/quality_check.py', 'align': 'python3 tools/aoi/production_sync.py status|verify|diff|pull'}}

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
