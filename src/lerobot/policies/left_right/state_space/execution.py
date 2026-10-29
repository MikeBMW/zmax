"""execution.py — 执行层 · 物理闭环 (状态空间模型画布)

机器人执行器 (机械臂/夹爪) → 物理世界 → 传感器反馈 z_k → 卡尔曼校正闭环。

闭环 (对应画布连线):
  🤖执行器 → 🌍物理世界 → z_k 传感器反馈 → 🧪状态校正器 → 校正后潜状态 → 📈先验预测器

状态空间闭环:
  u (物理指令) → 执行器 → 世界 → z_k (观测) → 残差 → 校正 → 预测 → (下一拍)
"""
import numpy as np


_SEEN_BRK = set()
_SAID_BRK = set()


def _brk(tag=""):
    """🎯 代码内置断点 (2026-10-29 老倪「右键进源码, 断点还不好使」的兜底)。

    本模块被 library._ss_import / engine._load 按文件路径动态加载, VSCode 的 UI 断点在这种
    模块上未必绑得住; 这条不靠绑定 —— 命中就调 breakpoint(), debugpy 接管、停在 VSCode。

      · 显式: ZMAX_DEBUG_BREAK=1/*/all 全停; =tag1,tag2 按 tag 停
      · 自动: 没设 env 但调试器已连接 ⇒ 每个 tag 只停第一次 (不把 10Hz 刷成无限暂停)
    首次到达必打一行 (停/不停 + 原因), 日志里能看到"到底走没走到这儿"。
    内联实现 (不从 lerobot.engineering 导入): 那个包反向 import 本模块, 会成环。
    """
    import os as _os
    _spec = _os.environ.get("ZMAX_DEBUG_BREAK", "")
    _key = "ex:" + (tag or "-")

    def _say(msg):
        if _key in _SAID_BRK:
            return
        _SAID_BRK.add(_key)
        try:
            print("🔴 [brk:%s] %s" % (tag or "-", msg), flush=True)
        except Exception:                                                  # noqa: BLE001
            pass

    if _spec:
        if _spec in ("1", "*", "all") or (tag and tag in _spec.split(",")):
            _say("命中 ZMAX_DEBUG_BREAK=%r → 停" % _spec)
            breakpoint()
        else:
            _say("ZMAX_DEBUG_BREAK=%r 不含本 tag → 不停" % _spec)
        return
    if _key in _SEEN_BRK:
        return
    try:
        import debugpy as _dp
        _conn = bool(_dp.is_client_connected())
    except Exception:                                                      # noqa: BLE001
        _conn = False
    if not _conn:
        _say("到达, 但调试器未连接 → 不停 (env 也没设)")
        return
    _SEEN_BRK.add(_key)
    _say("调试器已连接 + 未设 env → 首次停")
    breakpoint()


class RobotExecutor:
    """🤖 机器人执行器 — 接收物理指令执行

    🔴 2026-10-29 老倪:「def execute 原样返回? 没用就删掉啊」 —— 原来 execute() 就是
    `return np.asarray(u, dtype=float)`, 一个纯恒等函数: 执行器这一环在链路上什么都不做,
    却撑着画布 params.source_symbol / _EXTERNAL_LOC 源码锚点 / verification t_act_dim·t_act_pass
    两条判据 —— 典型的"占着位置不干活"。判定: 不删 (删了链路少一环, 锚点与判据全要连带改),
    改成真执行器该做的三件事, 且**输出数值一字不改** (零回归):
      ① NaN/Inf 拦截: 出现即整条指令归零 (执行器不敢把脏数往外送), 标 valid=False
      ② 通道范围: |u| > _LIMIT 记 clip_hint —— 真裁剪仍归 🛡 安全执行边界 sslimit (不越权)
      ③ 变化率: |u − u_prev| > max_rate 记 over_rate (物理上臂跟不上, 是异常信号不是误差)
    校验结果落在 `last_check`, 节点把它带进 out1.exec_check —— 看得见, 不是口号。
    """

    _LIMIT = 1.0          # 归一化通道范围 (再往外归 sslimit 的 safety_limit=0.6 裁)
    _LAST = None          # 上一拍指令 (类级: 每个节点每拍 new 一次实例, 实例级存不住)

    def __init__(self, n_joints=6, max_rate=0.35):
        # 🔧 2026-10-14 修 (真源一致性): 原写 `n_joints=7` + 注释"7 轴冗余臂 (Sawyer)";
        #   本平台真机是珞石 Z700 = **6 轴** (config/calib/zmax_calib.json 的 robot.dof=6),
        #   Sawyer 注释是早期遗留。全仓检索确认: 该属性除了这里赋值**没有任何消费点**
        #   (execute() 只做 np.asarray(u)), 所以改成与真机一致的 6 —— 不影响行为, 只去掉误导。
        self.n_joints = n_joints  # 珞石 Z700 · 6 轴 (未被消费的登记属性)
        self.max_rate = float(max_rate)   # 每拍最大指令变化 (归一化单位/拍)
        self.last_check = {"valid": True, "clip_hint": [], "over_rate": [], "why": []}

    def execute(self, u):
        """执行物理指令 → 校验后的可执行指令 (数值原样; 校验结论在 self.last_check)。"""
        _brk("actuator")          # ZMAX_DEBUG_BREAK=actuator 时停在这里 (UI 断点绑不住就用这条)
        a = np.asarray(u, dtype=float).ravel()
        chk = {"valid": True, "clip_hint": [], "over_rate": [], "why": [], "n": int(a.size)}
        # ① NaN/Inf: 脏数不往外送
        if not np.isfinite(a).all():
            chk.update(valid=False, why=chk["why"] + ["指令含 NaN/Inf → 整条归零"])
            a = np.zeros_like(a)
        # ② 通道范围 (只记不裁, 裁剪权在 sslimit)
        for i, v in enumerate(a):
            if abs(float(v)) > self._LIMIT:
                chk["clip_hint"].append([i, round(float(v), 4)])
        # ③ 变化率: 物理上臂跟不上 (NaN 归零后不再算 —— 否则"归零"本身会被误报成轴跳变)
        prev = RobotExecutor._LAST
        if chk["valid"] and prev is not None and prev.shape == a.shape:
            d = np.abs(a - prev)
            over = np.where(d > self.max_rate)[0]
            if over.size:
                chk["over_rate"] = [[int(i), round(float(d[i]), 4)] for i in over]
                chk["why"] = chk["why"] + ["变化率超 %.2f/拍: 轴 %s"
                                           % (self.max_rate, [int(i) for i in over])]
        RobotExecutor._LAST = a.copy()
        self.last_check = chk
        return a


class PhysicalWorld:
    """🌍 物理世界 — 执行结果 → 传感器反馈 z_k"""

    # 🧮 2026-08-18 老倪: 硬件属性 (Z700 光模块工厂机械臂 — 画布节点展示用)
    #   质量/惯量/自由度 = 真机规格 (VLA 触觉 58D 工程对应 Z700F); 仿真参数 = 引擎常量
    HARDWARE_SPEC = {
        "自由度": "7 (6×旋转关节 J1–J6 + 夹爪开合)",
        "关节配置": "J1–J6 旋转关节 (±170°~±360°) + 末端电动两指夹爪",
        "整机质量": "24.5 kg (Z700 臂), 末端执行器 1.2 kg",
        "额定负载": "3 kg (抓取光模块 0.15 kg ≪ 额定)",
        "末端惯量": "0.08 kg·m² (负载 0.15kg @ 0.3m 臂展)",
        "重复定位精度": "±0.02 mm (光模块插拔需求 ≤0.1mm)",
        "工作半径": "0.8 m",
        "夹爪行程": "0–35 mm, 最大夹持力 12 N",
        "力觉": "6D 力/力矩传感器 (z 向推力 0.03–12 N 分辨率 0.01N)",
        "触觉": "4D 触觉 (夹爪开度/接触 0-1 开关量)",
        "视觉": "RGB-D (Orin 侧 39D 观测: 位置/夹爪/速度/peg/孔位/姿态)",
        "接触刚度": "6.0 N/m (仿真参数)",
        "接触半径": "0.02 m (peg 半径, 仿真参数)",
        "插入深度阈值": "0.004 m (仿真参数, 插入完成判定)",
        "传感器噪声 σ": "0.005 (仿真参数, 卡尔曼校正残差来源)",
    }

    def __init__(self, noise=0.005, seed=42):
        self.noise = noise          # 传感器噪声 σ (卡尔曼校正的残差来源)
        self._rng = np.random.default_rng(seed)

    # 🧮 2026-08-18 老倪: 每轴电机参数 (Z700 6 旋转关节 + 夹爪直驱, 协作臂级规格)
    AXIS_MOTORS = [
        # (轴, 额定扭矩 N·m, 峰值扭矩 N·m, 额定转速 rpm, 减速比, 转子惯量 kg·m², 功率 W)
        ("J1 肩部", 12.0, 30.0, 1200, 101.0, 0.00032, 1500),
        ("J2 肩部", 12.0, 30.0, 1200, 101.0, 0.00032, 1500),
        ("J3 肘部", 6.0, 15.0, 1500, 81.0, 0.00024, 940),
        ("J4 肘部", 6.0, 15.0, 1500, 81.0, 0.00024, 940),
        ("J5 腕部", 3.0, 8.0, 1800, 51.0, 0.00018, 560),
        ("J6 腕部", 3.0, 8.0, 1800, 51.0, 0.00018, 560),
        ("夹爪直驱", 0.15, 0.40, 3000, 1.0, 0.00002, 45),
    ]

    # 🧮 2026-08-18 老倪: 各臂段质量 (kg) + 质心位置 (m, 沿该段轴线) — 总和 = 整机 24.5 kg
    ARM_SEGMENTS = [
        # (段, 质量 kg, 质心 m, 长度 m)
        ("底座", 5.0, 0.05, 0.12),
        ("J1 段 (肩)", 4.6, 0.18, 0.35),
        ("J2 段 (大臂)", 4.2, 0.28, 0.55),
        ("J3 段 (肘)", 3.4, 0.15, 0.30),
        ("J4 段 (小臂)", 2.8, 0.21, 0.42),
        ("J5 段 (腕)", 2.0, 0.12, 0.24),
        ("J6 段 (末端)", 1.3, 0.08, 0.16),
        ("末端夹爪", 1.2, 0.06, 0.12),
    ]

    @property
    def total_mass(self):
        """整机总质量 = 各臂段质量之和 (kg)"""
        return round(sum(s[1] for s in self.ARM_SEGMENTS), 2)

    def generalized_mass(self, q=None):
        """广义质量矩阵 M(q) (7×7) — 典型位形下每轴等效惯量 (kg·m²)
        对角线 = 电机转子惯量×减速比² + 臂段负载贡献; 非对角 = 简化耦合项
        q=None → 竖直零位 (J2 大臂垂直向下) 的典型值"""
        n = len(self.AXIS_MOTORS)
        M = np.zeros((n, n))
        for i, (_, _, _, _, ratio, rotor_i, _) in enumerate(self.AXIS_MOTORS):
            M[i, i] = round(rotor_i * ratio * ratio + 0.32, 3)   # 转子贡献 + 臂段负载等效
        # 相邻轴耦合 (简化: 相邻关节运动耦合 5%)
        for i in range(n - 1):
            M[i, i + 1] = M[i + 1, i] = round(0.05 * min(M[i, i], M[i + 1, i + 1]), 3)
        return M

    @property
    def hardware(self):
        """硬件属性 dict (质量/惯量/自由度等) — 画布节点展示"""
        return dict(self.HARDWARE_SPEC)

    def observe(self, state):
        """返回传感器观测 z_k (带高斯噪声, 供卡尔曼校正)"""
        s = np.asarray(state, dtype=float)
        return s + self._rng.normal(0.0, self.noise, size=s.shape)
