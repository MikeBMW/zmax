#!/usr/bin/env python3
"""atomic_skills.py — Z-MAX 原子技能库 (真实源码, 2026-09-08 老倪: 集中到 src/lerobot)

🧩 原子技能层: 决策层 (动作调制器状态机经安全边界) 选定当前技能 → 复制技能模板
实例化 → 快速执行 → 输出执行指令给 🤖执行器。

本文件 = 原子技能模板的**权威定义源** (SK01-08 = 插装任务 8 阶段模板)。
画布 SK01-08 节点 (sssk1-8) 右键源码指向本文件的技能类; node_logic 播放展示
读本文件模板 + 引擎轨迹当前帧 (stage=当前技能 / target=决策赋值 / u_exec_vec=实际下发)。

✅ 数值同源契约 (2026-10-16 起**本文件即唯一真源**): 引擎不再自带一份阶段偏置 ——
  src/lerobot/engine/sim.py 的 STAGE_APPROACH_H/STAGE_ALIGN_H/STAGE_DESCEND_H/STAGE_LIFT
  直接取自本文件各类的 params (hover_h/descend_h/lift_h), `_stage_target()` 走
  `SK0x.next_target(ctx=几何)`; 真机 `tools/l2_daemon.py::build_move()` 走
  `next_target(points=点位库, spec=阶段)`。两处消费同一份规则, 不再各算一遍。
  改偏置 ⇒ 改这里一处 (判据 tools/verify_skill_target_port.py 会核逐位一致)。

夹爪语义契约: 引擎/3D: 0=张开 1=夹紧; metaworld obs 反 (1=张开 0=闭合), 记录层 1−obs。
任务链: SK01-08 = 插装 8 段 (mode=insert); mode=full 追加 拔出/AOI转移/AOI检测/回程/放下
(13 段) — 新技能模板按同构扩展 (见 SKILL_ORDER 注释)。
"""


class AtomicSkill:
    """原子技能模板基类 — 一个技能 = 一段可实例化执行的固定轨迹模板。

    决策层"实时赋值" (阶段目标/速度) 后复制实例化; 字段:
      code    技能编号 (SK01-08)
      stage   对应状态机阶段名 (cognition.ActionModulator.STAGES)
      goal    目标语义 (锚=光模块头/夹爪, 与 _stage_target 同语义)
      params  关键模板参数 (数值同源引擎常量, 见顶部契约)
      evidence 本技能完成的推进证据 (状态机 advance 判据)
      ctrl    控制语义 (夹爪/限速)
      source  数值来源引擎常量 (溯源)
    """

    code = "SK--"
    stage = ""
    name = ""
    desc = ""
    goal = ""
    params = {}
    evidence = ""
    ctrl = {}
    source = ""

    # ── ⚖ 本技能的物理约束 (惯性/质量变化率/速度/加速度/位移) ──────────────────────
    #   老倪 (2026-10-15): 「每个技能都清楚的知道自己动作的惯性」「速度 v、加速度 a、位移 s
    #   需要可以标定, 比如上限下限」。**技能类不自带物理数字** —— 数值真源只有一处:
    #   config/calib/zmax_skill_physics.json (按 stage 取, 每项带 min/max), 读法就是下面三个方法。
    #   为什么不把 m/F/v 直接写进类里: 会立刻出现第二份数字 (引擎常量 / 标定真源 / 技能类 三处打架)。
    #   实测踩过: 段名不统一 (PHYS 里「放入」 vs 引擎「放下」) ⇒ 静默套用了别的段的物理量。
    @classmethod
    def _phys_mod(cls):
        """取物理闸模块 (兼容三种导入方式: 包内相对 / 绝对包名 / 直接文件加载)。"""
        try:
            from .. import physics_constraints as _pc        # noqa: WPS433 (包内相对)
            return _pc
        except Exception:                                                       # noqa: BLE001
            pass
        try:
            from lerobot.policies.left_right.state_space import physics_constraints as _pc   # noqa: WPS433
            return _pc
        except Exception:                                                       # noqa: BLE001
            import importlib.util
            import os
            _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "physics_constraints.py")
            _s = importlib.util.spec_from_file_location("zmax_physics_constraints", _p)
            _m = importlib.util.module_from_spec(_s)
            _s.loader.exec_module(_m)
            return _m

    @classmethod
    def phys(cls):
        """本技能的物理上限: m/F/v/v_min/a_max/jerk_max/s/s_step/dmdt + 真源与上下限。

        例: SK01Approach.phys()["a_max"] → 4.17 m/s² (由 F=5N / m=1.2kg 推出, 或用标定值 a)。
        """
        return cls._phys_mod().limits_for(cls.stage)

    @classmethod
    def phys_bounds(cls):
        """本技能每个物理量的**物理上下限** [min, max] + 单位 (给标定界面/接口用)。"""
        return cls._phys_mod().bounds_for(cls.stage)

    @classmethod
    def phys_check(cls):
        """自检: 本技能的物理量是否齐、是否都在物理上下限内 (标定越界立刻看得出来)。"""
        q, b, bad = cls.phys(), cls.phys_bounds() or {}, []
        # 真源里的名字 → 闸门输出里的名字 (a 生效值是 a_max: 标定 a 或 F/m 推出; s 生效值是 s_max)
        _alias = {"a": "a_max", "s": "s_max"}
        for k, spec in b.items():
            v = q.get(_alias.get(k, k))
            lo, hi = spec.get("min"), spec.get("max")
            if v is None or lo is None or hi is None:
                bad.append("%s 缺项" % k)
            elif not (float(lo) - 1e-12 <= float(v) <= float(hi) + 1e-12):
                bad.append("%s=%s ∉ [%s, %s]" % (k, v, lo, hi))
        if q.get("unknown_stage"):
            bad.append("段名 '%s' 在真源/内置表里都没有 ⇒ 已标 unknown_stage, 别静默当别的段用" % cls.stage)
        return {"ok": not bad, "code": cls.code, "stage": cls.stage, "problems": bad,
                "phys": {k: q.get(k) for k in ("m", "F", "v", "v_min", "a_max", "jerk_max", "s_step", "s_max")},
                "真源": q.get("calib_src_kind")}

    # ── ⚖ 本技能的物理模型 (方程形式写在这里, 数值不抄 —— 打开技能就能看到方程) ──────────
    #   老倪 (2026-10-15): 「我打开 SK01Approach 的时候, 怎么没有看到任何物理方程呢?」
    #   ⇒ 方程形式逐条写进技能类 (下面 EQ), 数值仍只从真源取 (config/calib/zmax_skill_physics.json);
    #     打开技能看到形式, 调用 phys_model()/show_phys() 看到"带本段真实数字的方程"。
    #   形式与闸门 physics_constraints.InertiaLimiter.limit() 的 ①..⑤ 一一对应, 改一处必须改另一处
    #   (判据 tools/verify_skill_physics_calib.py ⑩ 会卡住: 类里方程条数/数字必须与真源一致)。
    EQ = {
        "①位移←速度": ("s(t) = ∫ v dt", "‖v‖·dt ≤ s_step  (单拍位移封顶; 段累计 ≤ s_max)"),
        "②速度←加速度": ("v(t) = ∫ a dt", "‖Δv‖ ≤ a_max·dt,  a_max = F_max/m"),
        "③加加速度(平顺)": ("a(t) = ∫ j dt", "‖Δa‖ ≤ jerk_max·dt  (伺服带宽有限, 不许阶跃)"),
        "④动量/质量率": ("p = m·v", "‖m·Δv + v·Δm‖ ≤ F_max·dt  (抓取建立/释放时质量在变)"),
        "⑤惯量(牛顿二定律)": ("F = m·a", "a = F/m  ⇒ 同样推力, 质量越大加速度越小"),
    }

    @classmethod
    def phys_model(cls):
        """本技能的**物理模型**: 五条方程 + 本段真实数值 (全部取自真源, 类里不硬编码数字)。"""
        q = cls.phys()
        dt = float(q.get("dt") or 0.1)
        m, F = float(q["m"]), float(q["F"])
        a, j, ss, sm = float(q["a_max"]), float(q["jerk_max"]), float(q["s_step"]), float(q["s_max"])
        v, vmin = float(q["v"]), float(q.get("v_min") or 0.0)
        dm = float(q.get("dmdt_max") or q.get("dmdt") or 0.0)   # 闸门里叫 dmdt, 报告里叫 dmdt_max
        eq = dict(cls.EQ)
        return {
            "技能": "%s %s [%s]" % (cls.code, cls.name, cls.stage),
            "方程": {
                "①位移←速度": "%s   ∧   ‖v‖·dt ≤ %.4f m  (段累计 ≤ %.3f m)   [v ≤ %.3f m/s]"
                              % (eq["①位移←速度"][0], ss, sm, v),
                "②速度←加速度": "%s   ∧   ‖Δv‖ ≤ a_max·dt = %.3f×%.2f = %.4f m/s"
                                % (eq["②速度←加速度"][0], a, dt, a * dt),
                "③加加速度(平顺)": "%s   ∧   ‖Δa‖ ≤ jerk_max·dt = %.1f×%.2f = %.4f m/s²"
                                   % (eq["③加加速度(平顺)"][0], j, dt, j * dt),
                "④动量/质量率": "%s   ∧   ‖m·Δv + v·Δm‖ ≤ F_max·dt = %.1f×%.2f = %.4f N·s (dm/dt=%.2f kg/s)"
                                % (eq["④动量/质量率"][0], F, dt, F * dt, dm),
                "⑤惯量(牛顿二定律)": "%s   ⇒   a_max = %.1f N / %.2f kg = %.3f m/s²"
                                     % (eq["⑤惯量(牛顿二定律)"][0], F, m, F / max(1e-9, m)),
            },
            "数值": {"m_kg": m, "F_max_N": F, "v_cap_mps": v, "v_min_mps": vmin, "a_max_mps2": a,
                     "jerk_max_mps3": j, "s_step_m": ss, "s_max_m": sm, "dmdt_max_kg_s": dm, "dt": dt},
            "上下限": cls.phys_bounds(),
            "真源": q.get("calib_src_kind"),
            "自检": cls.phys_check(),
        }

    # ── ⚖ 物理模型的**调用点** (真执行语句, 不是注释) ─────────────────────────────
    #   老倪 (2026-10-15): 「原子技能, 哪里是调用物理模型的? 这里没看到模型调用的语句,
    #   怎么保证每次都有物理约束」⇒ 每个技能类体内都有一条真调用 (`clamp`), 落到本方法,
    #   本方法再落到闸门 physics_constraints.InertiaLimiter.limit (五式 ①..⑤ 的唯一收口)。
    #   派发链每拍走这里: tools/ss_skill_dispatch.py::SkillDispatch._phys() → 技能对象.clamp()。
    #   判据 tools/verify_skill_physics_calls.py 会数「调用次数 == 派发拍数」(没有一拍绕过闸)。
    _LIMITER = None

    @classmethod
    def limiter(cls):
        """本技能用的物理闸实例 (模块级**单例**: 段累计行程/上拍速度/削因计数必须跨拍连续)。"""
        if AtomicSkill._LIMITER is None:
            AtomicSkill._LIMITER = cls._phys_mod().InertiaLimiter()
        return AtomicSkill._LIMITER

    def apply_physics(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """⚖ **真调用物理模型**: 候选动作 u → 物理可行动作 (五式收口于闸门 limit())。

        返回闸门原始结果: {u, v_req, err, err_norm, big, why, phys, ...}
        `why` 写明是哪条约束削的 (可行/速度/加速度/加加速度/动量·质量率/位移),
        `err` 就是"物理不可行"的偏差量 —— 信号分析里看得见, 也是判据的取证口。
        """
        return self.limiter().limit(self.stage, u, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt, dt=dt)

    # ══════════════════════════════════════════════════════════════════════════
    # 🔵 3D 约束通道 (圆柱) —— **每个技能自带自己那根管子** (2026-11-01 老倪)
    #   老倪: 「把这个原子技能的通道 · 圆柱体 · 运动学约束的功能, 迁移到状态空间工程,
    #          要在每个技能里, 我要用代码调试, 进入断点」
    #   之前: 通道在 cognition.skill_step() 收口处统一套一次 (一个点, 九个技能共用) ⇒
    #        调试只能断在 cognition 里, 看不出"哪个技能过的是哪根管子", 也没有技能自己的半径。
    #   现在: 数据真源**不变** (zmax_data/ss_live/skill_corridors.json ← tools/ss_corridor_build.py),
    #        但读取/投影的调用点下沉到**每个技能的 clamp() 末尾**:
    #            `return self.corridor_finish(_out)`
    #        断点打这一行就停在**这个技能自己的**通道里; 半径按段取
    #        (接近 25 / 对位 8 / 下降 6 / 抓取 3 / 抬起 25 / 转移 25 / 插入 3 / 完成 6 mm)。
    #   管道几何 = 圆柱: 轴 = 该段真实轨迹折线, 半径 = 工艺间隙 —— 与 AR 页的圆环管壁同一份数据,
    #   所以页面上看到的管子就是代码里正在约束的那一根。
    CORRIDOR_STAGE = None          # 通道真源里的段名; None ⇒ 用 cls.stage (段名不统一时子类覆盖)
    CORRIDOR_R_MM = None           # 半径覆盖 mm; None ⇒ 用真源 r_mm (标定后由 json 说话)
    # 零位移技能 (夹爪开合那类): plan 里该段 a==b, 没有运动就没有"运动通道" —— 如实标, 不造管子
    CORRIDOR_ZERO_MOTION = False

    @classmethod
    def _corridor_mod(cls):
        """取通道算法模块 corridor.py (与 cognition 同一份, 固定模块名复用缓存)。"""
        import sys as _sys
        m = _sys.modules.get("zmax_skill_corridor")
        if m is not None:
            return m
        import importlib.util as _ilu
        import os as _os
        p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "corridor.py")
        spec = _ilu.spec_from_file_location("zmax_skill_corridor", p)
        if spec is None or spec.loader is None:
            raise ImportError("无法加载通道模块: %s" % p)
        m = _ilu.module_from_spec(spec)
        _sys.modules["zmax_skill_corridor"] = m
        spec.loader.exec_module(m)
        return m

    @classmethod
    def corridor(cls):
        """本技能的圆柱通道 (读真源, 不现算): {stage,r_mm,L_mm,n_poly,axis,a,b,v_along_cap,s_tick_mm}。

        没有真源 ⇒ None (**不编一根假管子**); cls.CORRIDOR_R_MM 可覆盖半径 (标定/实验用)。
        """
        st = cls.CORRIDOR_STAGE or cls.stage
        corr = (cls._corridor_mod().load_corridors() or {}).get(st)
        if not corr:
            return None
        if cls.CORRIDOR_R_MM is not None:
            corr = dict(corr)
            corr["r_mm"] = float(cls.CORRIDOR_R_MM)
        return corr

    def __repr__(self):
        """调试用可读表示 —— 没有它, 调试器里 `p self` 只会打 `<...SK03Descend object at 0x7f...>`,
        除了类名和内存地址什么也看不到 (老倪 2026-11-01 现场问「你这是输出的什么」)。
        只读不写, 自己绝不许抛异常 (调试器会在任意时刻调它)。
        """
        try:
            _r = None
            try:
                _c = type(self).corridor() or {}
                _r = _c.get("r_mm")
            except Exception:                                              # noqa: BLE001
                _r = None
            _pos = getattr(self, "pos_mm", None)
            _ps = ("(%.0f,%.0f,%.0f)mm" % tuple(float(x) for x in list(_pos)[:3])) if _pos is not None else "—"
            return "<%s %s %s r=%smm pos=%s travel=%.0fmm>" % (
                type(self).__name__, self.code, self.stage,
                ("%.1f" % _r) if isinstance(_r, (int, float)) else "—",
                _ps, float(getattr(self, "travel_m", 0.0) or 0.0) * 1000.0)
        except Exception:                                                  # noqa: BLE001
            return "<%s>" % type(self).__name__

    @staticmethod
    def debugger_attached():
        """有调试器挂着吗 (VSCode/debugpy/pdb)。

        实测: `python -m pdb` 下 `sys.gettrace()` 是 **None**, 但调用帧的 `f_trace` 是
        `Bdb.trace_dispatch` ⇒ 必须**沿调用栈查 f_trace**, 只查 gettrace() 会漏判 (踩过)。
        """
        import sys
        try:
            if sys.gettrace() is not None:
                return True
            fr, n = sys._getframe(1), 0
            while fr is not None and n < 40:
                if getattr(fr, "f_trace", None) is not None:
                    return True
                fr, n = fr.f_back, n + 1
            m = sys.modules.get("debugpy")
            if m is not None:
                try:
                    return bool(m.is_client_connected())
                except Exception:                                          # noqa: BLE001
                    return True
        except Exception:                                                  # noqa: BLE001
            return False
        return False

    def corridor_dbg(self):
        """🛑 断点本身 (不是注释): 本技能过通道前停一下。

        触发条件 (任意一条):
          ① `ZMAX_CORRIDOR_BREAK=1` / 技能号(`SK03`) / 段名(`下降`) ⇒ **每次都停**
          ② 有调试器挂着 (VSCode F5 / `python -m pdb` / debugpy) ⇒ 每个技能本进程**停一次**
             (`ZMAX_CORRIDOR_BREAK_FIRST=0` 可关掉这个自动停)
        生产运行 (无调试器、无 env) 一律不停 —— 不会把引擎挂住。
        """
        import os
        import sys
        env = os.environ.get("ZMAX_CORRIDOR_BREAK")
        if env == "0":
            return
        if env in ("1", self.code, self.stage):
            breakpoint()
            return
        if env:
            return                                   # 指定了别的技能/段 ⇒ 本技能不停
        if os.environ.get("ZMAX_CORRIDOR_BREAK_FIRST", "1") == "0":
            return
        # ② 自动: 调试器挂着就停 (每技能本进程一次)。判据三选一 + 必须有终端,
        #    否则 CI/pytest 里 breakpoint() 会去读 stdin 把进程挂住。
        if not sys.stdin.isatty():
            return
        attached = AtomicSkill.debugger_attached()
        if attached:
            key = (type(self).__name__, os.getpid())
            if key not in AtomicSkill._DBG_STOPPED:
                AtomicSkill._DBG_STOPPED.add(key)
                breakpoint()

    _DBG_STOPPED = set()

    def corridor_reset(self):
        """段切换时清掉活通道的锚点 (轴必须固定在**本段起点**, 不能每拍跟着当前位姿重锚)。"""
        self._cor_a = None

    _MEM_DB = None
    _MEM_TAB = {"接近": ("槽", "槽"), "下降": ("槽", "槽"), "抓取": ("槽", "槽"), "抬起": ("槽", "槽"),
                "转移": ("槽", "孔"), "对位": ("孔", "孔"), "插入": ("孔", "孔"), "完成": ("孔", "孔")}

    @classmethod
    def mem_limits(cls):
        """🧠 本段在 L2 记忆库里的通道限额 (只读库; 库不可用/关闸 → None)。

        取法: 与方案册同口径 —— 先按技能语义挑形状 (抓取系 槽→槽 / 转移 槽→孔 / 对位·插入·完成 孔→孔),
        再取该形状里**实跑次数最多**的那条 (kind=real 优先), 不用 geom 冒充实测。
        返回 {key, r_mm, L_mm, v_along_cap, s_tick_m, tact_s, kind} 或 None。
        """
        import os as _os, json as _js
        if _os.environ.get("ZMAX_MEM_EN", "1") in ("0", "false", "False", "off"):
            return None
        if AtomicSkill._MEM_DB is None:
            _db = {}
            try:
                _here = _os.path.dirname(_os.path.abspath(__file__))
                # 仓库根 = 往上找到带 .git 的那层 (写死 dirname 层数必错: 本文件在 src/lerobot/... 深 6 层)
                _d = _here
                while _d != _os.path.dirname(_d) and not _os.path.isdir(_os.path.join(_d, ".git")):
                    _d = _os.path.dirname(_d)
                _p = _os.environ.get("ZMAX_L2_STORE") or _os.path.join(_d, "data/memory/l2_store/corridors.json")
                _d = _js.load(open(_p, encoding="utf-8")).get("corridors") or {}
                for _k, _v in _d.items():
                    _db.setdefault(str(_v.get("stage") or ""), []).append(_v)
            except Exception:                                    # noqa: BLE001
                _db = {}
            AtomicSkill._MEM_DB = _db
        _lst = AtomicSkill._MEM_DB.get(str(cls.stage)) or []
        if not _lst:
            return None
        _ps, _pe = cls._MEM_TAB.get(str(cls.stage), ("槽", "槽"))

        def _ok(v):
            _f, _t = str(v.get("from") or ""), str(v.get("to") or "")
            return _f.startswith(_ps) and (_t.startswith(_pe) or _t == "-")

        _pool = [v for v in _lst if v.get("kind") == "real" and _ok(v)] or \
                [v for v in _lst if _ok(v)] or _lst
        _best = max(_pool, key=lambda v: (v.get("kind") == "real", v.get("n_poly") or 0))
        return {"key": _best.get("key"), "kind": _best.get("kind"),
                "r_mm": _best.get("r_mm"), "L_mm": _best.get("L_mm"),
                "v_along_cap": _best.get("v_along_cap"),
                "s_tick_m": (float(_best.get("s_tick_mm") or 0.0) / 1000.0) or None,
                "tact_s": _best.get("tact_s"),
                "champ_n_ok": None,
                "src": "data/memory/l2_store/corridors.json"}

    def corridor_finish(self, out, pos_mm=None, dt=None, target_mm=None):
        """🔵 收口最后一关 (每个 clamp 末尾调): 把本技能动作投影进**本技能的圆柱通道**。

        · 轴向: 轴向越界归零; v_along ≤ min(v_cap, L/tact) —— 节拍参与约束
        · 横向: 偏出 r ⇒ 切掉向外分量 + 补回中速度 (不是等比缩小, 缩减不回中)
        · 单拍: ‖v‖·dt ≤ s_tick

        几何来源两个, 同一个投影算法:
          ① 真源包络 (zmax_data/ss_live/skill_corridors.json): 轴 = 每条历史机动的真实折线 (基座/AR 系)
          ② 本帧活通道 `corridor.build(stage, 当前位置, 本段目标)`: 轴 = 理想轨迹 cur→target
             —— 调用方给的坐标是什么系, 它就是什么系 (仿真/真机都不串系), 只在 ① 系不对时启用
        返回 out (补 "corridor"); 通道缺失/关掉/ZMAX_CORRIDOR=0 ⇒ 原样返回 (不编)。
        调试: ZMAX_CORRIDOR_BREAK=1|SK03|下降 ⇒ 停在本函数的断点 (pdb/debugpy 都行)。
        """
        import os
        if os.environ.get("ZMAX_CORRIDOR", "1") == "0":
            return out
        try:
            corr = self.corridor()
            # 🧠 记忆赋能 (2026-11-02 老倪): 工艺点级通道给的节拍预算/单拍限额**只收紧不放松**
            #   真源 data/memory/l2_store/corridors.json (corridor 的代表条目, 与方案册同口径)。
            #   ZMAX_MEM_EN=0 ⇒ 不叠加, 输出与不打补丁前逐位相同 (A/B 用)。
            _mem = self.mem_limits()
            if corr and _mem:
                corr = dict(corr)
                _cands = [x for x in (corr.get("v_along_cap"), _mem.get("v_along_cap")) if x]
                if _cands:
                    corr["v_along_cap"] = min(float(x) for x in _cands)
                _cands2 = [x for x in (corr.get("s_tick_mm"), _mem.get("s_tick_mm")) if x]
                if _cands2:
                    corr["s_tick_mm"] = min(float(x) for x in _cands2)
                corr["mem"] = _mem
            if not corr:
                out = dict(out)
                if self.CORRIDOR_ZERO_MOTION:
                    out["corridor"] = {"skill": self.code, "stage": self.CORRIDOR_STAGE or self.stage,
                                       "n/a": "零位移段 (夹爪开合), 没有运动通道"}
                else:
                    out["corridor"] = {"skill": self.code, "stage": self.CORRIDOR_STAGE or self.stage,
                                       "error": "无通道真源 (zmax_data/ss_live/skill_corridors.json 缺该段)"}
                return out
            _m = self._corridor_mod()
            if pos_mm is None:
                pos_mm = getattr(self, "pos_mm", None) or _m._live_pos_mm()
            if pos_mm is None:
                out = dict(out)
                out["corridor"] = {"skill": self.code, "stage": corr.get("stage"), "r_mm": corr.get("r_mm"),
                                   "no_pos": 1,
                                   "error": "无 3D 坐标 (trace_live 缺/过期, 或它是仿真坐标系) ⇒ 本拍不过通道"}
                return out
            _dt = dt if dt is not None else getattr(self, "DT_S", None)
            # ── 几何来源 (同一个投影算法, 只是管子怎么来不同) ────────────────────────
            #   ① 有本段目标 ⇒ 活通道: 轴 = 当前末端 → 本段目标 (与调用方同坐标系, 仿真/真机都不串系)
            #   ② 没有目标 ⇒ 真源包络: 轴 = 该技能每条历史机动的真实折线 (基座/AR 系)
            _tgt = target_mm if target_mm is not None else getattr(self, "target_mm", None)
            _t3 = [float(x) for x in list(_tgt)[:3]] if _tgt is not None else None
            geo, _mode = corr, "stored"
            if _t3 is not None:
                # 🔴 轴必须锚在**本段起点**: 拿"当前位姿→目标"每拍重算的话, 横向偏差恒为 0,
                #    管子等于没约束 (实测: 这样算出来 dev 全程 0.0mm)。起点在段首拍锁定, 段内不动。
                if getattr(self, "_cor_a", None) is None:
                    self._cor_a = [float(x) for x in pos_mm[:3]]
                try:
                    _live = _m.build(corr.get("stage"), self._cor_a, _t3,
                                     v_cap=float(corr.get("v_cap") or 0.35),
                                     a_max=float(corr.get("a_max") or 4.166667),
                                     dt=float(_dt or 0.1), tact_s=corr.get("tact_s"),
                                     r_mm=float(corr.get("r_mm") or 10.0),
                                     s_step_m=float(corr.get("s_tick_mm") or 35.0) / 1000.0)
                    if float(_live.get("L_mm") or 0.0) > 0.5:
                        geo, _mode = _live, "live"
                except Exception:                                          # noqa: BLE001
                    geo, _mode = corr, "stored"
            u_out, info = _m.project_stage(corr.get("stage"), out.get("u"), pos_mm, geo, dt=_dt)
            info["mode"] = _mode
            if _mode == "live":
                info["target_mm"] = [round(x, 3) for x in list(_t3 or [])]
            else:
                # 🚧 用真源包络时必查坐标系: 它建于机器人基座/AR 坐标 (plan mm, x≈650),
                #    仿真的末端是 (34,611,127) —— 拿错系会 dev 半米到一米, 那不是"偏出管子"。
                #    判据 dev > max(100mm, 8·r): 单次机动只有几十 mm, 8 倍半径以外只能是串系 ⇒ 不套。
                _lim = max(100.0, 8.0 * float(corr.get("r_mm") or 0.0))
                if float(info.get("dev_mm") or 0.0) > _lim:
                    out = dict(out)
                    out["corridor"] = {"skill": self.code, "stage": corr.get("stage"),
                                       "r_mm": corr.get("r_mm"), "dev_mm": info.get("dev_mm"),
                                       "frame_mismatch": 1, "lim_mm": round(_lim, 1),
                                       "pos_mm": [round(float(x), 1) for x in pos_mm[:3]],
                                       "error": "坐标不在通道坐标系 (偏离 %.0fmm > %.0fmm) ⇒ 本拍不过通道"
                                                % (float(info.get("dev_mm") or 0.0), _lim)}
                    return out
            info["skill"] = self.code
            info["pos_mm"] = [round(float(x), 3) for x in pos_mm[:3]]
            out = dict(out)
            out["u"] = [float(x) for x in u_out]
            out["corridor"] = info
            if not info.get("in_channel"):
                _w = out.get("why") or ""
                out["why"] = "通道·越界" if _w in ("", "可行") else (_w + "+通道·越界")
            return out
        except Exception as e:                                              # noqa: BLE001
            out = dict(out)
            out["corridor"] = {"skill": self.code, "error": "%s: %s" % (type(e).__name__, e)}
            return out

    # ══════════════════════════════════════════════════════════════════════════
    # 🎯 执行口: **本段目标位姿** (单一真源, 2026-10-16)
    #   老倪: 「这些原子任务都有输出么? 最终的 MoveIt 是怎么选择实际的原子任务动作的」
    #   ⇒ 技能类必须能**输出目标**, 而不是只把别人给的动作削一遍。规则写在类属性 TARGET 里
    #     (ref = 参考点语义, off_key = 取 params 里哪个偏置), 由本方法解析成绝对位姿。
    #   两个消费者, 同一份规则 —— 引擎与真机不再各算一遍:
    #     仿真 src/lerobot/engine/sim.py::_stage_target()  → next_target(ctx=几何)
    #     真机 tools/l2_daemon.py::build_move()            → next_target(points=点位库, spec=阶段)
    #   缺上下文/未知段 ⇒ 返回 None (调用方显示"未生成"), **绝不编一个 0 目标**。
    TARGET = None

    @classmethod
    def target_rule(cls):
        """本段目标规则 {ref, off_key, tol_key?}; 没声明 = 本技能不产出目标。"""
        return dict(cls.TARGET) if isinstance(cls.TARGET, dict) else None

    @classmethod
    def _off_vec(cls):
        """从 params 取偏置向量 (off_key 指定键; 缺 → [0,0,0], 不猜)。"""
        r = cls.target_rule() or {}
        k = r.get("off_key")
        z = float(cls.params.get(k, 0.0)) if k else 0.0
        return [0.0, 0.0, z]

    @classmethod
    def next_target(cls, ctx=None, points=None, spec=None, with_phys=False, cur=None):
        """🎯 本段目标位姿 — 唯一定义处。

        ctx:    仿真几何 {"peg":[3], "head_off":[3], "table_z":f, "hole_mouth":[3], "hole":[3]}
        points: 真机点位库 {name: {"pos":[3], "quat":[4]}}
        spec:   真机调用参数 (点名称覆盖用, 与 l2_daemon 同口径)

        返回 {stage, skill, ref, off, xyz, quat, tol_m, v_cap, a_max, jerk_max, s_step, src}
        解析不了 → None。
        """
        import numpy as np                                  # 局部导入: 本模块也被无 numpy 的 venv 按需加载
        r = cls.target_rule()
        if not r:
            return None
        ref = str(r.get("ref") or "")
        off = np.asarray(cls._off_vec(), dtype=float)
        xyz = None
        quat = None
        src = ""
        # ① 点位库上下文优先 (真机): 有 points + 可解析点名 ⇒ 点位 + 本段偏置。
        #    这就是"原子技能给真机/MoveIt 的目标": 同一段在仿真里按几何(peg/hole)算, 在真机上按
        #    点位库(taught_points: slot1/insert_pose/…)算 —— 偏置/语义只有一份, 参考点按环境换。
        _name = ((spec or {}).get("point") or r.get("point") or cls.params.get("point"))
        if points and _name and str(_name) in points and (points.get(str(_name)) or {}).get("pos"):
            _p = points[str(_name)]
            _pos = np.asarray(_p["pos"], dtype=float)
            if ref == "peg_xy_table":       # 抬起: 只抬 z (xy 留在点位上), 与几何口径同构
                xyz = np.array([_pos[0], _pos[1], _pos[2] + off[2]])
            else:
                xyz = _pos + off
            quat = list(_p["quat"]) if _p.get("quat") else None
            src = "taught_points[%s]" % _name
        elif ref == "rel":                                    # 真机 line_rel: 当前位姿 + 轴偏移
            if cur is None:
                return None
            _ax = str((spec or {}).get("axis") or r.get("axis") or "z_pos")
            # 行程来源优先级: 调用参数 > 技能 TARGET 声明 > 技能 params (pull_out_m 等) > 0
            _d = float((spec or {}).get("d_m") or r.get("d_m") or cls.params.get("d_m")
                       or cls.params.get("pull_out_m") or 0.0)
            _v = np.asarray(cur, dtype=float).ravel()[:3].copy()
            _i = {"x": 0, "y": 1, "z": 2}.get(_ax[0].lower(), 2)
            _sgn = -1.0 if _ax.lower().endswith("neg") else 1.0
            _v[_i] += _sgn * abs(_d)
            xyz = _v
            src = "cur+%s%.3fm" % (_ax, abs(_d))
        elif ref == "point":                                  # 声明只认点位, 但点位不在库 ⇒ 不编
            return None
        else:                                                 # 仿真: 几何上下文
            c = ctx or {}
            if ref == "peg":
                if c.get("peg") is None:
                    return None
                xyz = np.asarray(c["peg"], dtype=float) + off
            elif ref == "peg_xy_table":                       # [peg.x, peg.y, table_z + off_z]
                if c.get("peg") is None or c.get("table_z") is None:
                    return None
                xyz = np.array([float(c["peg"][0]), float(c["peg"][1]), float(c["table_z"]) + off[2]])
            elif ref in ("hole_mouth", "hole"):               # 末端 = 孔口/孔底 − 真实夹持偏移 + 偏置
                base = c.get(ref)
                hoff = c.get("head_off")
                if base is None or hoff is None:
                    return None
                xyz = np.asarray(base, dtype=float) - np.asarray(hoff, dtype=float) + off
            else:
                return None
            src = "ctx[%s]" % ref
        ph = (cls.phys() or {}) if with_phys else {}      # 包络按需 (默认只给目标, 不读标定真源)
        return {"stage": cls.stage, "skill": cls.code, "ref": ref, "off": [float(x) for x in off],
                "xyz": [float(x) for x in np.asarray(xyz, dtype=float).ravel()[:3]],
                "quat": quat,
                "tol_m": float(cls.params.get("tol_m", 0.002)),
                "v_cap": float(ph.get("v") or cls.ctrl.get("v_cap") or 0.0),
                "v_min": float(ph.get("v_min") or cls.ctrl.get("v_min") or 0.0),
                "a_max": float(ph.get("a_max") or 0.0),
                "jerk_max": float(ph.get("jerk_max") or 0.0),
                "s_step": float(ph.get("s_step") or 0.0),
                "phys_src": (ph.get("src") if with_phys else None),
                "src": src}

    @classmethod
    def command(cls, ctx=None, x=None, k=6.0, v_cap=None, points=None, spec=None):
        """🎯 目标驱动期望速度 (原子技能自己产出动作): u = k·(target − x), 限 v_cap, 到 tol 内→0。

        返回 {"u":[3], "target":[3], "err_m":f, "reached":bool, "rule":...}; 无目标 → None。
        这就是"原子任务输出动作"的执行口 —— 引擎 decide() 在 ZMAX_SKILL_FF=1 时用它当 u_ff。
        """
        import numpy as np                                  # 局部导入 (同 next_target)
        t = cls.next_target(ctx=ctx, points=points, spec=spec)
        if not t or x is None:
            return None
        x = np.asarray(x, dtype=float).ravel()[:3]
        e = np.asarray(t["xyz"], dtype=float) - x
        d = float(np.linalg.norm(e))
        cap = float(v_cap if v_cap is not None else (t.get("v_cap") or 0.0))
        if d <= float(t.get("tol_m") or 0.0):
            u = np.zeros(3)
        else:
            u = float(k) * e
            n = float(np.linalg.norm(u))
            if cap > 0 and n > cap:
                u = u * (cap / n)
        return {"u": [float(v) for v in u], "target": t["xyz"], "err_m": round(d, 6),
                "reached": bool(d <= float(t.get("tol_m") or 0.0)), "rule": t["ref"],
                "v_cap": cap, "src": t["src"]}

    @classmethod
    def show_phys(cls):
        """把本技能的物理模型打印出来 (人看/交付: 打开哪个技能, 就看到它自己的方程和数字)。"""
        d = cls.phys_model()
        out = ["⚖ %s — 物理模型 (数值真源: %s)" % (d["技能"], d["真源"])]
        for k, val in d["方程"].items():
            out.append("   %-18s %s" % (k, val))
        n = d["数值"]
        out.append("   本段数值: m=%.2fkg F≤%.1fN v≤%.3fm/s(v_min %.3f) a≤%.2fm/s² jerk≤%.1fm/s³ "
                   "单拍位移≤%.4fm 段行程≤%.3fm dm/dt≤%.2fkg/s"
                   % (n["m_kg"], n["F_max_N"], n["v_cap_mps"], n["v_min_mps"], n["a_max_mps2"],
                      n["jerk_max_mps3"], n["s_step_m"], n["s_max_m"], n["dmdt_max_kg_s"]))
        out.append("   自检: %s %s" % ("✅ 物理量齐 + 全在上下限内" if d["自检"]["ok"] else "❌",
                                      d["自检"]["problems"] or ""))
        txt = "\n".join(out)
        print(txt)
        return txt


class SK01Approach(AtomicSkill):
    """① 接近 — 从初始位移动到光模块抓握点正上方 (悬停, 不触碰)"""
    code = "SK01"
    # 🎯 目标: 光模块抓握点正上方悬停 (peg + 0,0,params.hover_h)
    TARGET = {"ref": "peg",         "off_key": "hover_h"}
    stage = "接近"
    name = "① 接近"
    desc = "夹爪移动到光模块抓握点正上方悬停 (水平粗对准)"
    goal = "光模块头 → peg + (0, 0, 0.09) 上方 (水平 xy 追 peg, z 悬停)"
    params = {"hover_h": 0.09}            # STAGE_APPROACH_H (sim_real)
    evidence = "手-光模块水平距离 < 0.06 (align_xy_coarse) → 对位"
    ctrl = {"gripper": "张开", "v_cap": 0.35, "v_min": 0.12}
    source = "state_space_sim_real.STAGE_APPROACH_H / cognition.STAGE_V_CAP"

    phys_note = "本段=接近: v_cap=0.350 m/s · a_max=4.167 m/s² · 单拍位移 s_step=0.0350 m (全部取真源 config/calib/zmax_skill_physics.json 的 value; 类里不另存一份数字)。"
    # ══════════════════════════════════════════════════════════════════════════
    # 本技能的约束 — 数字全写在这里 (真源 config/calib/zmax_skill_physics.json · 段=接近)
    #   加速度上限取真源 a (标定值优先, 无标定才用牛顿二定律 F/m): 4.166667 m/s²
    # ══════════════════════════════════════════════════════════════════════════
    DT_S      = 0.1            # 每拍 0.1 s
    M_KG      = 1.2            # 运动质量 kg (未夹持)
    F_MAX_N   = 5.0            # 允许力 N (④ 动力量)
    A_MAX     = 4.166667       # ② 加速度上限 m/s² (真源 a 标定值; = F/m = 5.0/1.20)
    V_CAP     = 0.35           # ① 速度上限 m/s
    V_MIN     = 0.12           # 最小速度 (低于它算到位, 不追)
    JERK_MAX  = 15.0           # ③ 加加速度上限 m/s³
    S_STEP    = 0.035          # ⑤ 单拍位移上限 m (= V_CAP × dt)
    S_MAX     = 0.6            # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1            # ④ 质量变化率上限 kg/s

    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """运动学 ①②③⑤ + 动力学 ④ —— 逐条算, 算出来的就是下发动作。

        u 请求动作 [vx,vy,vz,夹爪] · v_prev/a_prev 上一拍速度/加速度 (缺省当 0)
        返回 u(下发) v_req(请求) err(被削的量) why(哪条削的) phys(本段数字)
        """
        import numpy as np                                  # 局部导入 (本模块按需加载, 不强制 numpy)
        dt = self.DT_S if dt is None else float(dt)
        m, F_max = self.M_KG, self.F_MAX_N
        u_req = np.asarray(u, dtype=float).ravel().copy()
        v = u_req[:3].copy()                                # 只约束平移 3 维, 夹爪原样下发
        v0 = np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy()
        a0 = np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy()
        why = []

        # ① 速度: ‖v‖ ≤ V_CAP (超了等比缩小, 方向不变)
        n_v = float(np.linalg.norm(v))
        if n_v > self.V_CAP > 0:
            v = v * (self.V_CAP / n_v)
            why.append("速度")

        # ② 加速度: 每拍速度变化 ‖v−v0‖ ≤ A_MAX·dt (A_MAX 就是真源标定的那个加速度)
        a_max = self.A_MAX
        a_lim = a_max * dt
        dv = v - v0
        n_dv = float(np.linalg.norm(dv))
        if n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")

        # ③ 加加速度: 每拍加速度变化 ‖Δa‖ ≤ JERK_MAX·dt (不许阶跃, 伺服带宽有限)
        a_new = (v - v0) / dt
        da = a_new - a0
        j_lim = self.JERK_MAX * dt
        n_da = float(np.linalg.norm(da))
        if n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * dt
            why.append("加加速度")
        kin_why = "+".join(why) or "可行"

        # ④ 动力学: 动量/质量率 ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取/释放时质量在变)
        _dmdt = self.DMDT_MAX if dmdt is None else float(dmdt)
        dv = v - v0
        f_lim = F_max * dt
        f_need = m * dv + v * (_dmdt * dt)
        n_f = float(np.linalg.norm(f_need))
        dyn_why = []
        if n_f > f_lim > 0:
            v = v0 + dv * (f_lim / max(n_f, 1e-9))
            dyn_why.append("动量/质量率")
            why.append("动量/质量率")

        # ⑤ 位移: 单拍 ‖v‖·dt ≤ S_STEP; 本段累计 > S_MAX 只报不杀
        d_step = float(np.linalg.norm(v)) * dt
        if self.S_STEP > 0 and d_step > self.S_STEP * (1.0 + 1e-12):
            v = v * (self.S_STEP / max(d_step, 1e-12))
            why.append("位移")
        self.travel_m = float(getattr(self, "travel_m", 0.0)) + float(np.linalg.norm(v)) * dt
        over = int(self.S_MAX > 0 and self.travel_m > self.S_MAX * (1.0 + 1e-9))

        # 收口: 下发动作 / 被削掉的偏差 / 本段数字
        u_out = u_req.copy()
        u_out[:3] = v
        err = u_req[:3] - v
        e_norm = float(np.linalg.norm(err))
        # 🔴 2026-10-31 老倪「技能 return 的断点全都进不去」:
        #   原来 return/_out 里直接写列表推导 [float(x) for x in ...] —— 推导式是**独立 code object**,
        #   它自己的首行号就是这一行 ⇒ 调试器(和 pdb)会停在 <listcomp> 帧, 看起来"断点没进到 clamp"。
        #   现在把三个列表先算出来 (纯本函数语句), 断点下在 _out = { 这行就**稳停在 clamp() 帧**。
        _u_list = [float(x) for x in u_out]
        _v_list = [float(x) for x in u_req[:3]]
        _e_list = [float(x) for x in err]
        _out = {"u": _u_list, "v_req": _v_list,
                "err": _e_list, "err_norm": round(e_norm, 8),
                "big": int(e_norm > 0.05),
                "why": "+".join(why) or "可行",
                "kin_why": kin_why,
                "dyn_why": "+".join(dyn_why) or "可行",
                "phys": {"m": round(m, 4), "F_max": F_max, "v_cap": self.V_CAP, "v_min": self.V_MIN,
                         "a_max": round(a_max, 4), "jerk_max": round(self.JERK_MAX, 3),
                         "dmdt_max": _dmdt, "s_step": self.S_STEP, "s_max": self.S_MAX, "dt": dt,
                         "src": self.source,
                         "calib": "本类常量 (真源 config/calib/zmax_skill_physics.json)"},
                "s_travel": round(self.travel_m, 6), "over_travel": over,
                "f_need_N": round(n_f, 6), "kin_called": 1, "dyn_called": 1}
        self.corridor_dbg()                        # 🛑 本技能的断点 (F9 打这一行/VSCode 直接停)
        return self.corridor_finish(_out)

class SK02Align(AtomicSkill):
    """② 对位 — 光模块上方精对位 (更低悬停, 准备垂直下刀)"""
    code = "SK02"
    # 🎯 目标: 精对位高度 (peg + 0,0,params.hover_h)
    TARGET = {"ref": "peg",         "off_key": "hover_h"}
    stage = "对位"
    name = "② 对位"
    desc = "降到光模块上方精对位高度, 消除水平残差"
    goal = "光模块头 → peg + (0, 0, 0.05) 上方"
    params = {"hover_h": 0.05}            # STAGE_ALIGN_H
    evidence = "手-光模块水平距离 < 0.02 (align_xy_fine) → 下降"
    ctrl = {"gripper": "张开", "v_cap": 0.12, "v_min": 0.04}
    source = "state_space_sim_real.STAGE_ALIGN_H"

    phys_note = "本段=对位: v_cap=0.120 m/s · a_max=4.167 m/s² · 单拍位移 s_step=0.0120 m (全部取真源 config/calib/zmax_skill_physics.json 的 value; 类里不另存一份数字)。"
    # ══════════════════════════════════════════════════════════════════════════
    # 本技能的约束 — 数字全写在这里 (真源 config/calib/zmax_skill_physics.json · 段=对位)
    #   加速度上限取真源 a (标定值优先, 无标定才用牛顿二定律 F/m): 4.166667 m/s²
    # ══════════════════════════════════════════════════════════════════════════
    DT_S      = 0.1            # 每拍 0.1 s
    M_KG      = 1.2            # 运动质量 kg (未夹持)
    F_MAX_N   = 5.0            # 允许力 N (④ 动力量)
    A_MAX     = 4.166667       # ② 加速度上限 m/s² (真源 a 标定值; = F/m = 5.0/1.20)
    V_CAP     = 0.12           # ① 速度上限 m/s
    V_MIN     = 0.04           # 最小速度 (低于它算到位, 不追)
    JERK_MAX  = 5.142857       # ③ 加加速度上限 m/s³
    S_STEP    = 0.012          # ⑤ 单拍位移上限 m (= V_CAP × dt)
    S_MAX     = 0.06           # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1            # ④ 质量变化率上限 kg/s

    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """运动学 ①②③⑤ + 动力学 ④ —— 逐条算, 算出来的就是下发动作。

        u 请求动作 [vx,vy,vz,夹爪] · v_prev/a_prev 上一拍速度/加速度 (缺省当 0)
        返回 u(下发) v_req(请求) err(被削的量) why(哪条削的) phys(本段数字)
        """
        import numpy as np                                  # 局部导入 (本模块按需加载, 不强制 numpy)
        dt = self.DT_S if dt is None else float(dt)
        m, F_max = self.M_KG, self.F_MAX_N
        u_req = np.asarray(u, dtype=float).ravel().copy()
        v = u_req[:3].copy()                                # 只约束平移 3 维, 夹爪原样下发
        v0 = np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy()
        a0 = np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy()
        why = []

        # ① 速度: ‖v‖ ≤ V_CAP (超了等比缩小, 方向不变)
        n_v = float(np.linalg.norm(v))
        if n_v > self.V_CAP > 0:
            v = v * (self.V_CAP / n_v)
            why.append("速度")

        # ② 加速度: 每拍速度变化 ‖v−v0‖ ≤ A_MAX·dt (A_MAX 就是真源标定的那个加速度)
        a_max = self.A_MAX
        a_lim = a_max * dt
        dv = v - v0
        n_dv = float(np.linalg.norm(dv))
        if n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")

        # ③ 加加速度: 每拍加速度变化 ‖Δa‖ ≤ JERK_MAX·dt (不许阶跃, 伺服带宽有限)
        a_new = (v - v0) / dt
        da = a_new - a0
        j_lim = self.JERK_MAX * dt
        n_da = float(np.linalg.norm(da))
        if n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * dt
            why.append("加加速度")
        kin_why = "+".join(why) or "可行"

        # ④ 动力学: 动量/质量率 ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取/释放时质量在变)
        _dmdt = self.DMDT_MAX if dmdt is None else float(dmdt)
        dv = v - v0
        f_lim = F_max * dt
        f_need = m * dv + v * (_dmdt * dt)
        n_f = float(np.linalg.norm(f_need))
        dyn_why = []
        if n_f > f_lim > 0:
            v = v0 + dv * (f_lim / max(n_f, 1e-9))
            dyn_why.append("动量/质量率")
            why.append("动量/质量率")

        # ⑤ 位移: 单拍 ‖v‖·dt ≤ S_STEP; 本段累计 > S_MAX 只报不杀
        d_step = float(np.linalg.norm(v)) * dt
        if self.S_STEP > 0 and d_step > self.S_STEP * (1.0 + 1e-12):
            v = v * (self.S_STEP / max(d_step, 1e-12))
            why.append("位移")
        self.travel_m = float(getattr(self, "travel_m", 0.0)) + float(np.linalg.norm(v)) * dt
        over = int(self.S_MAX > 0 and self.travel_m > self.S_MAX * (1.0 + 1e-9))

        # 收口: 下发动作 / 被削掉的偏差 / 本段数字
        u_out = u_req.copy()
        u_out[:3] = v
        err = u_req[:3] - v
        e_norm = float(np.linalg.norm(err))
        # 🔴 2026-10-31 老倪「技能 return 的断点全都进不去」:
        #   原来 return/_out 里直接写列表推导 [float(x) for x in ...] —— 推导式是**独立 code object**,
        #   它自己的首行号就是这一行 ⇒ 调试器(和 pdb)会停在 <listcomp> 帧, 看起来"断点没进到 clamp"。
        #   现在把三个列表先算出来 (纯本函数语句), 断点下在 _out = { 这行就**稳停在 clamp() 帧**。
        _u_list = [float(x) for x in u_out]
        _v_list = [float(x) for x in u_req[:3]]
        _e_list = [float(x) for x in err]
        _out = {"u": _u_list, "v_req": _v_list,
                "err": _e_list, "err_norm": round(e_norm, 8),
                "big": int(e_norm > 0.05),
                "why": "+".join(why) or "可行",
                "kin_why": kin_why,
                "dyn_why": "+".join(dyn_why) or "可行",
                "phys": {"m": round(m, 4), "F_max": F_max, "v_cap": self.V_CAP, "v_min": self.V_MIN,
                         "a_max": round(a_max, 4), "jerk_max": round(self.JERK_MAX, 3),
                         "dmdt_max": _dmdt, "s_step": self.S_STEP, "s_max": self.S_MAX, "dt": dt,
                         "src": self.source,
                         "calib": "本类常量 (真源 config/calib/zmax_skill_physics.json)"},
                "s_travel": round(self.travel_m, 6), "over_travel": over,
                "f_need_N": round(n_f, 6), "kin_called": 1, "dyn_called": 1}
        self.corridor_dbg()                        # 🛑 本技能的断点 (F9 打这一行/VSCode 直接停)
        return self.corridor_finish(_out)

class SK03Descend(AtomicSkill):
    """③ 下降 — 张爪垂直下刀包住光模块身 (触到即停)"""
    code = "SK03"
    # 🎯 目标: 贴到抓握点 (peg + 0,0,params.descend_h)
    TARGET = {"ref": "peg",         "off_key": "descend_h"}
    stage = "下降"
    name = "③ 下降"
    desc = "张开的夹爪垂直下降到抓握点 (包住光模块两侧)"
    goal = "夹爪 → peg 抓握点 + (0, 0, 0.004) (贴到抓握点)"
    params = {"descend_h": 0.004,          # STAGE_DESCEND_H
              "z_stall_frames": 8}         # 下降停滞判据 (被销/台顶住)
    evidence = "接触概率 >0.6 (力觉) 或 到达抓握位姿 (几何+z停滞≥8帧) → 抓取"
    ctrl = {"gripper": "张开 (到位前不闭 — 状态锁存非比例)", "v_cap": 0.09}
    source = "state_space_sim_real.STAGE_DESCEND_H / _z_stall"

    phys_note = "本段=下降: v_cap=0.090 m/s · a_max=4.167 m/s² · 单拍位移 s_step=0.0090 m (全部取真源 config/calib/zmax_skill_physics.json 的 value; 类里不另存一份数字)。"
    # ══════════════════════════════════════════════════════════════════════════
    # 本技能的约束 — 数字全写在这里 (真源 config/calib/zmax_skill_physics.json · 段=下降)
    #   加速度上限取真源 a (标定值优先, 无标定才用牛顿二定律 F/m): 4.166667 m/s²
    # ══════════════════════════════════════════════════════════════════════════
    DT_S      = 0.1            # 每拍 0.1 s
    M_KG      = 1.2            # 运动质量 kg (未夹持)
    F_MAX_N   = 5.0            # 允许力 N (④ 动力量)
    A_MAX     = 4.166667       # ② 加速度上限 m/s² (真源 a 标定值; = F/m = 5.0/1.20)
    V_CAP     = 0.09           # ① 速度上限 m/s
    V_MIN     = 0.0            # 最小速度 (低于它算到位, 不追)
    JERK_MAX  = 3.857143       # ③ 加加速度上限 m/s³
    S_STEP    = 0.009          # ⑤ 单拍位移上限 m (= V_CAP × dt)
    S_MAX     = 0.05           # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1            # ④ 质量变化率上限 kg/s

    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """运动学 ①②③⑤ + 动力学 ④ —— 逐条算, 算出来的就是下发动作。

        u 请求动作 [vx,vy,vz,夹爪] · v_prev/a_prev 上一拍速度/加速度 (缺省当 0)
        返回 u(下发) v_req(请求) err(被削的量) why(哪条削的) phys(本段数字)
        """
        import numpy as np                                  # 局部导入 (本模块按需加载, 不强制 numpy)
        dt = self.DT_S if dt is None else float(dt)
        m, F_max = self.M_KG, self.F_MAX_N
        u_req = np.asarray(u, dtype=float).ravel().copy()
        v = u_req[:3].copy()                                # 只约束平移 3 维, 夹爪原样下发
        v0 = np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy()
        a0 = np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy()
        why = []

        # ① 速度: ‖v‖ ≤ V_CAP (超了等比缩小, 方向不变)
        n_v = float(np.linalg.norm(v))
        if n_v > self.V_CAP > 0:
            v = v * (self.V_CAP / n_v)
            why.append("速度")

        # ② 加速度: 每拍速度变化 ‖v−v0‖ ≤ A_MAX·dt (A_MAX 就是真源标定的那个加速度)
        a_max = self.A_MAX
        a_lim = a_max * dt
        dv = v - v0
        n_dv = float(np.linalg.norm(dv))
        if n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")

        # ③ 加加速度: 每拍加速度变化 ‖Δa‖ ≤ JERK_MAX·dt (不许阶跃, 伺服带宽有限)
        a_new = (v - v0) / dt
        da = a_new - a0
        j_lim = self.JERK_MAX * dt
        n_da = float(np.linalg.norm(da))
        if n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * dt
            why.append("加加速度")
        kin_why = "+".join(why) or "可行"

        # ④ 动力学: 动量/质量率 ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取/释放时质量在变)
        _dmdt = self.DMDT_MAX if dmdt is None else float(dmdt)
        dv = v - v0
        f_lim = F_max * dt
        f_need = m * dv + v * (_dmdt * dt)
        n_f = float(np.linalg.norm(f_need))
        dyn_why = []
        if n_f > f_lim > 0:
            v = v0 + dv * (f_lim / max(n_f, 1e-9))
            dyn_why.append("动量/质量率")
            why.append("动量/质量率")

        # ⑤ 位移: 单拍 ‖v‖·dt ≤ S_STEP; 本段累计 > S_MAX 只报不杀
        d_step = float(np.linalg.norm(v)) * dt
        if self.S_STEP > 0 and d_step > self.S_STEP * (1.0 + 1e-12):
            v = v * (self.S_STEP / max(d_step, 1e-12))
            why.append("位移")
        self.travel_m = float(getattr(self, "travel_m", 0.0)) + float(np.linalg.norm(v)) * dt
        over = int(self.S_MAX > 0 and self.travel_m > self.S_MAX * (1.0 + 1e-9))

        # 收口: 下发动作 / 被削掉的偏差 / 本段数字
        u_out = u_req.copy()
        u_out[:3] = v
        err = u_req[:3] - v
        e_norm = float(np.linalg.norm(err))
        # 🔴 2026-10-31 老倪「技能 return 的断点全都进不去」:
        #   原来 return/_out 里直接写列表推导 [float(x) for x in ...] —— 推导式是**独立 code object**,
        #   它自己的首行号就是这一行 ⇒ 调试器(和 pdb)会停在 <listcomp> 帧, 看起来"断点没进到 clamp"。
        #   现在把三个列表先算出来 (纯本函数语句), 断点下在 _out = { 这行就**稳停在 clamp() 帧**。
        _u_list = [float(x) for x in u_out]
        _v_list = [float(x) for x in u_req[:3]]
        _e_list = [float(x) for x in err]
        _out = {"u": _u_list, "v_req": _v_list,
                "err": _e_list, "err_norm": round(e_norm, 8),
                "big": int(e_norm > 0.05),
                "why": "+".join(why) or "可行",
                "kin_why": kin_why,
                "dyn_why": "+".join(dyn_why) or "可行",
                "phys": {"m": round(m, 4), "F_max": F_max, "v_cap": self.V_CAP, "v_min": self.V_MIN,
                         "a_max": round(a_max, 4), "jerk_max": round(self.JERK_MAX, 3),
                         "dmdt_max": _dmdt, "s_step": self.S_STEP, "s_max": self.S_MAX, "dt": dt,
                         "src": self.source,
                         "calib": "本类常量 (真源 config/calib/zmax_skill_physics.json)"},
                "s_travel": round(self.travel_m, 6), "over_travel": over,
                "f_need_N": round(n_f, 6), "kin_called": 1, "dyn_called": 1}
        self.corridor_dbg()                        # 🛑 本技能的断点 (F9 打这一行/VSCode 直接停)
        return self.corridor_finish(_out)

class SK04Grasp(AtomicSkill):
    """④ 抓取 — 闭合夹爪深夹 (夹持锁存, 抬起前随动验证)"""
    code = "SK04"
    # 🎯 目标: 原地 (peg), 只闭爪不改位置
    TARGET = {"ref": "peg",         "off_key": None}
    stage = "抓取"
    name = "④ 抓取"
    desc = "夹爪闭合深夹光模块 → 锁存夹持偏移 (真机同构: 编码器锚定)"
    goal = "原地闭爪 (深夹: 夹紧度 1−obs 升到 ≥0.50, obs<0.50)"
    params = {"grasp_th": 0.50,            # 夹紧度阈值 (obs<0.50)
              "grasp_sat": 0.70}           # metaworld 夹住销饱和 (~0.70 obs)
    evidence = "夹紧度 >0.50 (深夹到位) → 抬起; 15 帧稳定+<8mm → 真值锚定"
    ctrl = {"gripper": "闭合锁存 (抓取及之后恒闭合)", "v_cap": 0.04}
    source = "cognition.ActionModulator(grasp_th=0.50) / GRASP_SAT"

    phys_note = "本段=抓取: v_cap=0.040 m/s · a_max=9.375 m/s² · 单拍位移 s_step=0.0040 m (全部取真源 config/calib/zmax_skill_physics.json 的 value; 类里不另存一份数字)。"
    # ══════════════════════════════════════════════════════════════════════════
    # 本技能的约束 — 数字全写在这里 (真源 config/calib/zmax_skill_physics.json · 段=抓取)
    #   加速度上限取真源 a (标定值优先, 无标定才用牛顿二定律 F/m): 9.375000 m/s²
    # ══════════════════════════════════════════════════════════════════════════
    DT_S      = 0.1            # 每拍 0.1 s
    M_KG      = 1.28           # 运动质量 kg (夹持建立中)
    F_MAX_N   = 12.0           # 允许力 N (④ 动力量)
    A_MAX     = 9.375          # ② 加速度上限 m/s² (真源 a 标定值; = F/m = 12.0/1.28)
    V_CAP     = 0.04           # ① 速度上限 m/s
    V_MIN     = 0.0            # 最小速度 (低于它算到位, 不追)
    JERK_MAX  = 2.25           # ③ 加加速度上限 m/s³
    S_STEP    = 0.004          # ⑤ 单拍位移上限 m (= V_CAP × dt)
    S_MAX     = 0.006          # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.5            # ④ 质量变化率上限 kg/s

    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """运动学 ①②③⑤ + 动力学 ④ —— 逐条算, 算出来的就是下发动作。

        u 请求动作 [vx,vy,vz,夹爪] · v_prev/a_prev 上一拍速度/加速度 (缺省当 0)
        返回 u(下发) v_req(请求) err(被削的量) why(哪条削的) phys(本段数字)
        """
        import numpy as np                                  # 局部导入 (本模块按需加载, 不强制 numpy)
        dt = self.DT_S if dt is None else float(dt)
        m, F_max = self.M_KG, self.F_MAX_N
        u_req = np.asarray(u, dtype=float).ravel().copy()
        v = u_req[:3].copy()                                # 只约束平移 3 维, 夹爪原样下发
        v0 = np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy()
        a0 = np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy()
        why = []

        # ① 速度: ‖v‖ ≤ V_CAP (超了等比缩小, 方向不变)
        n_v = float(np.linalg.norm(v))
        if n_v > self.V_CAP > 0:
            v = v * (self.V_CAP / n_v)
            why.append("速度")

        # ② 加速度: 每拍速度变化 ‖v−v0‖ ≤ A_MAX·dt (A_MAX 就是真源标定的那个加速度)
        a_max = self.A_MAX
        a_lim = a_max * dt
        dv = v - v0
        n_dv = float(np.linalg.norm(dv))
        if n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")

        # ③ 加加速度: 每拍加速度变化 ‖Δa‖ ≤ JERK_MAX·dt (不许阶跃, 伺服带宽有限)
        a_new = (v - v0) / dt
        da = a_new - a0
        j_lim = self.JERK_MAX * dt
        n_da = float(np.linalg.norm(da))
        if n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * dt
            why.append("加加速度")
        kin_why = "+".join(why) or "可行"

        # ④ 动力学: 动量/质量率 ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取/释放时质量在变)
        _dmdt = self.DMDT_MAX if dmdt is None else float(dmdt)
        dv = v - v0
        f_lim = F_max * dt
        f_need = m * dv + v * (_dmdt * dt)
        n_f = float(np.linalg.norm(f_need))
        dyn_why = []
        if n_f > f_lim > 0:
            v = v0 + dv * (f_lim / max(n_f, 1e-9))
            dyn_why.append("动量/质量率")
            why.append("动量/质量率")

        # ⑤ 位移: 单拍 ‖v‖·dt ≤ S_STEP; 本段累计 > S_MAX 只报不杀
        d_step = float(np.linalg.norm(v)) * dt
        if self.S_STEP > 0 and d_step > self.S_STEP * (1.0 + 1e-12):
            v = v * (self.S_STEP / max(d_step, 1e-12))
            why.append("位移")
        self.travel_m = float(getattr(self, "travel_m", 0.0)) + float(np.linalg.norm(v)) * dt
        over = int(self.S_MAX > 0 and self.travel_m > self.S_MAX * (1.0 + 1e-9))

        # 收口: 下发动作 / 被削掉的偏差 / 本段数字
        u_out = u_req.copy()
        u_out[:3] = v
        err = u_req[:3] - v
        e_norm = float(np.linalg.norm(err))
        # 🔴 2026-10-31 老倪「技能 return 的断点全都进不去」:
        #   原来 return/_out 里直接写列表推导 [float(x) for x in ...] —— 推导式是**独立 code object**,
        #   它自己的首行号就是这一行 ⇒ 调试器(和 pdb)会停在 <listcomp> 帧, 看起来"断点没进到 clamp"。
        #   现在把三个列表先算出来 (纯本函数语句), 断点下在 _out = { 这行就**稳停在 clamp() 帧**。
        _u_list = [float(x) for x in u_out]
        _v_list = [float(x) for x in u_req[:3]]
        _e_list = [float(x) for x in err]
        _out = {"u": _u_list, "v_req": _v_list,
                "err": _e_list, "err_norm": round(e_norm, 8),
                "big": int(e_norm > 0.05),
                "why": "+".join(why) or "可行",
                "kin_why": kin_why,
                "dyn_why": "+".join(dyn_why) or "可行",
                "phys": {"m": round(m, 4), "F_max": F_max, "v_cap": self.V_CAP, "v_min": self.V_MIN,
                         "a_max": round(a_max, 4), "jerk_max": round(self.JERK_MAX, 3),
                         "dmdt_max": _dmdt, "s_step": self.S_STEP, "s_max": self.S_MAX, "dt": dt,
                         "src": self.source,
                         "calib": "本类常量 (真源 config/calib/zmax_skill_physics.json)"},
                "s_travel": round(self.travel_m, 6), "over_travel": over,
                "f_need_N": round(n_f, 6), "kin_called": 1, "dyn_called": 1}
        self.corridor_dbg()                        # 🛑 本技能的断点 (F9 打这一行/VSCode 直接停)
        return self.corridor_finish(_out)

class SK05Lift(AtomicSkill):
    """⑤ 抬起 — 垂直提起光模块离台 (随动验证夹持是否真建立)"""
    code = "SK05"
    # 🎯 目标: [peg.x, peg.y, table_z + params.lift_h] (提到台面之上 lift_h)
    TARGET = {"ref": "peg_xy_table", "off_key": "lift_h"}
    stage = "抬起"
    name = "⑤ 抬起"
    desc = "垂直抬升光模块离台面到转移高度 (夹持质量由随动判定)"
    goal = "光模块 body z → peg_z0 + 0.16 (STAGE_LIFT, 高于孔口 0.13)"
    params = {"lift_h": 0.16}              # STAGE_LIFT (真实化; 销升 16cm)
    evidence = "提起高度 >0.08 (lift_h 判据) → 转移; 滑脱(off 漂移>8mm) → 回接近重抓"
    ctrl = {"gripper": "闭合保持", "v_cap": 0.30, "v_min": 0.10}
    source = "state_space_sim_real.STAGE_LIFT / GRASP_SLIP_MM"

    phys_note = "本段=抬起: v_cap=0.300 m/s · a_max=3.704 m/s² · 单拍位移 s_step=0.0300 m (全部取真源 config/calib/zmax_skill_physics.json 的 value; 类里不另存一份数字)。"
    # ══════════════════════════════════════════════════════════════════════════
    # 本技能的约束 — 数字全写在这里 (真源 config/calib/zmax_skill_physics.json · 段=抬起)
    #   加速度上限取真源 a (标定值优先, 无标定才用牛顿二定律 F/m): 3.703704 m/s²
    # ══════════════════════════════════════════════════════════════════════════
    DT_S      = 0.1            # 每拍 0.1 s
    M_KG      = 1.35           # 运动质量 kg (已夹持)
    F_MAX_N   = 5.0            # 允许力 N (④ 动力量)
    A_MAX     = 3.703704       # ② 加速度上限 m/s² (真源 a 标定值; = F/m = 5.0/1.35)
    V_CAP     = 0.3            # ① 速度上限 m/s
    V_MIN     = 0.1            # 最小速度 (低于它算到位, 不追)
    JERK_MAX  = 12.857143      # ③ 加加速度上限 m/s³
    S_STEP    = 0.03           # ⑤ 单拍位移上限 m (= V_CAP × dt)
    S_MAX     = 0.16           # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1            # ④ 质量变化率上限 kg/s

    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """运动学 ①②③⑤ + 动力学 ④ —— 逐条算, 算出来的就是下发动作。

        u 请求动作 [vx,vy,vz,夹爪] · v_prev/a_prev 上一拍速度/加速度 (缺省当 0)
        返回 u(下发) v_req(请求) err(被削的量) why(哪条削的) phys(本段数字)
        """
        import numpy as np                                  # 局部导入 (本模块按需加载, 不强制 numpy)
        dt = self.DT_S if dt is None else float(dt)
        m, F_max = self.M_KG, self.F_MAX_N
        u_req = np.asarray(u, dtype=float).ravel().copy()
        v = u_req[:3].copy()                                # 只约束平移 3 维, 夹爪原样下发
        v0 = np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy()
        a0 = np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy()
        why = []

        # ① 速度: ‖v‖ ≤ V_CAP (超了等比缩小, 方向不变)
        n_v = float(np.linalg.norm(v))
        if n_v > self.V_CAP > 0:
            v = v * (self.V_CAP / n_v)
            why.append("速度")

        # ② 加速度: 每拍速度变化 ‖v−v0‖ ≤ A_MAX·dt (A_MAX 就是真源标定的那个加速度)
        a_max = self.A_MAX
        a_lim = a_max * dt
        dv = v - v0
        n_dv = float(np.linalg.norm(dv))
        if n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")

        # ③ 加加速度: 每拍加速度变化 ‖Δa‖ ≤ JERK_MAX·dt (不许阶跃, 伺服带宽有限)
        a_new = (v - v0) / dt
        da = a_new - a0
        j_lim = self.JERK_MAX * dt
        n_da = float(np.linalg.norm(da))
        if n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * dt
            why.append("加加速度")
        kin_why = "+".join(why) or "可行"

        # ④ 动力学: 动量/质量率 ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取/释放时质量在变)
        _dmdt = self.DMDT_MAX if dmdt is None else float(dmdt)
        dv = v - v0
        f_lim = F_max * dt
        f_need = m * dv + v * (_dmdt * dt)
        n_f = float(np.linalg.norm(f_need))
        dyn_why = []
        if n_f > f_lim > 0:
            v = v0 + dv * (f_lim / max(n_f, 1e-9))
            dyn_why.append("动量/质量率")
            why.append("动量/质量率")

        # ⑤ 位移: 单拍 ‖v‖·dt ≤ S_STEP; 本段累计 > S_MAX 只报不杀
        d_step = float(np.linalg.norm(v)) * dt
        if self.S_STEP > 0 and d_step > self.S_STEP * (1.0 + 1e-12):
            v = v * (self.S_STEP / max(d_step, 1e-12))
            why.append("位移")
        self.travel_m = float(getattr(self, "travel_m", 0.0)) + float(np.linalg.norm(v)) * dt
        over = int(self.S_MAX > 0 and self.travel_m > self.S_MAX * (1.0 + 1e-9))

        # 收口: 下发动作 / 被削掉的偏差 / 本段数字
        u_out = u_req.copy()
        u_out[:3] = v
        err = u_req[:3] - v
        e_norm = float(np.linalg.norm(err))
        # 🔴 2026-10-31 老倪「技能 return 的断点全都进不去」:
        #   原来 return/_out 里直接写列表推导 [float(x) for x in ...] —— 推导式是**独立 code object**,
        #   它自己的首行号就是这一行 ⇒ 调试器(和 pdb)会停在 <listcomp> 帧, 看起来"断点没进到 clamp"。
        #   现在把三个列表先算出来 (纯本函数语句), 断点下在 _out = { 这行就**稳停在 clamp() 帧**。
        _u_list = [float(x) for x in u_out]
        _v_list = [float(x) for x in u_req[:3]]
        _e_list = [float(x) for x in err]
        _out = {"u": _u_list, "v_req": _v_list,
                "err": _e_list, "err_norm": round(e_norm, 8),
                "big": int(e_norm > 0.05),
                "why": "+".join(why) or "可行",
                "kin_why": kin_why,
                "dyn_why": "+".join(dyn_why) or "可行",
                "phys": {"m": round(m, 4), "F_max": F_max, "v_cap": self.V_CAP, "v_min": self.V_MIN,
                         "a_max": round(a_max, 4), "jerk_max": round(self.JERK_MAX, 3),
                         "dmdt_max": _dmdt, "s_step": self.S_STEP, "s_max": self.S_MAX, "dt": dt,
                         "src": self.source,
                         "calib": "本类常量 (真源 config/calib/zmax_skill_physics.json)"},
                "s_travel": round(self.travel_m, 6), "over_travel": over,
                "f_need_N": round(n_f, 6), "kin_called": 1, "dyn_called": 1}
        self.corridor_dbg()                        # 🛑 本技能的断点 (F9 打这一行/VSCode 直接停)
        return self.corridor_finish(_out)

class SK06Transfer(AtomicSkill):
    """⑥ 转移 — 持光模块平移至孔口上方 (悬高 2cm, 对准插孔)"""
    code = "SK06"
    # 🎯 目标: 孔口前方上方 (hole_mouth − 真实夹持偏移 + 0,0,params.hover)
    TARGET = {"ref": "hole_mouth",  "off_key": "hover"}
    stage = "转移"
    name = "⑥ 转移"
    desc = "夹持光模块水平转移到带孔盒孔口正上方 (工艺定位)"
    goal = "光模块头 → 孔口 + (0, 0, 0.02) (INSERT_HOVER 悬高)"
    params = {"hover": 0.02,               # INSERT_HOVER (孔口上方悬高)
              "align_th": 0.025}           # 头-孔口水平对准阈值
    evidence = "头-孔口水平 <0.025 且 peg 头悬孔口 2cm±1.2cm → 插入"
    ctrl = {"gripper": "闭合保持", "v_cap": 0.35, "v_min": 0.12}
    source = "cognition.INSERT_HOVER / sim_real align_th"

    phys_note = "本段=转移: v_cap=0.350 m/s · a_max=3.704 m/s² · 单拍位移 s_step=0.0350 m (全部取真源 config/calib/zmax_skill_physics.json 的 value; 类里不另存一份数字)。"
    # ══════════════════════════════════════════════════════════════════════════
    # 本技能的约束 — 数字全写在这里 (真源 config/calib/zmax_skill_physics.json · 段=转移)
    #   加速度上限取真源 a (标定值优先, 无标定才用牛顿二定律 F/m): 3.703704 m/s²
    # ══════════════════════════════════════════════════════════════════════════
    DT_S      = 0.1            # 每拍 0.1 s
    M_KG      = 1.35           # 运动质量 kg (已夹持)
    F_MAX_N   = 5.0            # 允许力 N (④ 动力量)
    A_MAX     = 3.703704       # ② 加速度上限 m/s² (真源 a 标定值; = F/m = 5.0/1.35)
    V_CAP     = 0.35           # ① 速度上限 m/s
    V_MIN     = 0.12           # 最小速度 (低于它算到位, 不追)
    JERK_MAX  = 15.0           # ③ 加加速度上限 m/s³
    S_STEP    = 0.035          # ⑤ 单拍位移上限 m (= V_CAP × dt)
    S_MAX     = 0.6            # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1            # ④ 质量变化率上限 kg/s

    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """运动学 ①②③⑤ + 动力学 ④ —— 逐条算, 算出来的就是下发动作。

        u 请求动作 [vx,vy,vz,夹爪] · v_prev/a_prev 上一拍速度/加速度 (缺省当 0)
        返回 u(下发) v_req(请求) err(被削的量) why(哪条削的) phys(本段数字)
        """
        import numpy as np                                  # 局部导入 (本模块按需加载, 不强制 numpy)
        dt = self.DT_S if dt is None else float(dt)
        m, F_max = self.M_KG, self.F_MAX_N
        u_req = np.asarray(u, dtype=float).ravel().copy()
        v = u_req[:3].copy()                                # 只约束平移 3 维, 夹爪原样下发
        v0 = np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy()
        a0 = np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy()
        why = []

        # ① 速度: ‖v‖ ≤ V_CAP (超了等比缩小, 方向不变)
        n_v = float(np.linalg.norm(v))
        if n_v > self.V_CAP > 0:
            v = v * (self.V_CAP / n_v)
            why.append("速度")

        # ② 加速度: 每拍速度变化 ‖v−v0‖ ≤ A_MAX·dt (A_MAX 就是真源标定的那个加速度)
        a_max = self.A_MAX
        a_lim = a_max * dt
        dv = v - v0
        n_dv = float(np.linalg.norm(dv))
        if n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")

        # ③ 加加速度: 每拍加速度变化 ‖Δa‖ ≤ JERK_MAX·dt (不许阶跃, 伺服带宽有限)
        a_new = (v - v0) / dt
        da = a_new - a0
        j_lim = self.JERK_MAX * dt
        n_da = float(np.linalg.norm(da))
        if n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * dt
            why.append("加加速度")
        kin_why = "+".join(why) or "可行"

        # ④ 动力学: 动量/质量率 ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取/释放时质量在变)
        _dmdt = self.DMDT_MAX if dmdt is None else float(dmdt)
        dv = v - v0
        f_lim = F_max * dt
        f_need = m * dv + v * (_dmdt * dt)
        n_f = float(np.linalg.norm(f_need))
        dyn_why = []
        if n_f > f_lim > 0:
            v = v0 + dv * (f_lim / max(n_f, 1e-9))
            dyn_why.append("动量/质量率")
            why.append("动量/质量率")

        # ⑤ 位移: 单拍 ‖v‖·dt ≤ S_STEP; 本段累计 > S_MAX 只报不杀
        d_step = float(np.linalg.norm(v)) * dt
        if self.S_STEP > 0 and d_step > self.S_STEP * (1.0 + 1e-12):
            v = v * (self.S_STEP / max(d_step, 1e-12))
            why.append("位移")
        self.travel_m = float(getattr(self, "travel_m", 0.0)) + float(np.linalg.norm(v)) * dt
        over = int(self.S_MAX > 0 and self.travel_m > self.S_MAX * (1.0 + 1e-9))

        # 收口: 下发动作 / 被削掉的偏差 / 本段数字
        u_out = u_req.copy()
        u_out[:3] = v
        err = u_req[:3] - v
        e_norm = float(np.linalg.norm(err))
        # 🔴 2026-10-31 老倪「技能 return 的断点全都进不去」:
        #   原来 return/_out 里直接写列表推导 [float(x) for x in ...] —— 推导式是**独立 code object**,
        #   它自己的首行号就是这一行 ⇒ 调试器(和 pdb)会停在 <listcomp> 帧, 看起来"断点没进到 clamp"。
        #   现在把三个列表先算出来 (纯本函数语句), 断点下在 _out = { 这行就**稳停在 clamp() 帧**。
        _u_list = [float(x) for x in u_out]
        _v_list = [float(x) for x in u_req[:3]]
        _e_list = [float(x) for x in err]
        _out = {"u": _u_list, "v_req": _v_list,
                "err": _e_list, "err_norm": round(e_norm, 8),
                "big": int(e_norm > 0.05),
                "why": "+".join(why) or "可行",
                "kin_why": kin_why,
                "dyn_why": "+".join(dyn_why) or "可行",
                "phys": {"m": round(m, 4), "F_max": F_max, "v_cap": self.V_CAP, "v_min": self.V_MIN,
                         "a_max": round(a_max, 4), "jerk_max": round(self.JERK_MAX, 3),
                         "dmdt_max": _dmdt, "s_step": self.S_STEP, "s_max": self.S_MAX, "dt": dt,
                         "src": self.source,
                         "calib": "本类常量 (真源 config/calib/zmax_skill_physics.json)"},
                "s_travel": round(self.travel_m, 6), "over_travel": over,
                "f_need_N": round(n_f, 6), "kin_called": 1, "dyn_called": 1}
        self.corridor_dbg()                        # 🛑 本技能的断点 (F9 打这一行/VSCode 直接停)
        return self.corridor_finish(_out)

class SK07Insert(AtomicSkill):
    """⑦ 插入 — 毫米级解析伺服精插 (两段式: 垂直对心→水平推入孔底)"""
    code = "SK07"
    # 🎯 目标: 插到孔底 (hole − 真实夹持偏移)
    TARGET = {"ref": "hole",        "off_key": None}
    stage = "插入"
    name = "⑦ 插入"
    desc = "光模块头对心孔口 → 沿孔轴推入孔底 (接触段, 禁肌肉记忆快通道)"
    goal = "光模块头 → 孔底 goal (插深 < 6mm 判完成)"
    params = {"insert_depth": 0.006,       # 完成判据 (离孔底 6mm)
              "z_align_tol": 0.0012,       # 段① z 对心容差 (1.2mm, 防顶孔沿)
              "stall_backoff": "遇阻回撤 12帧≈15mm → 分级重试(转移/接近)"}
    evidence = "插深 <0.006 → 完成 (full 模式 → 拔出)"
    ctrl = {"gripper": "闭合保持 (力控推入)", "v_cap": 0.085, "v_min": 0.02}
    source = "sim_real insert_depth=0.006 / cognition.STAGE_V_MIN 插入"

    phys_note = "本段=插入: v_cap=0.085 m/s · a_max=1.481 m/s² · 单拍位移 s_step=0.0085 m (全部取真源 config/calib/zmax_skill_physics.json 的 value; 类里不另存一份数字)。"
    # ══════════════════════════════════════════════════════════════════════════
    # 本技能的约束 — 数字全写在这里 (真源 config/calib/zmax_skill_physics.json · 段=插入)
    #   加速度上限取真源 a (标定值优先, 无标定才用牛顿二定律 F/m): 1.481481 m/s²
    # ══════════════════════════════════════════════════════════════════════════
    DT_S      = 0.1            # 每拍 0.1 s
    M_KG      = 1.35           # 运动质量 kg (已夹持)
    F_MAX_N   = 2.0            # 允许力 N (④ 动力量)
    A_MAX     = 1.481481       # ② 加速度上限 m/s² (真源 a 标定值; = F/m = 2.0/1.35)
    V_CAP     = 0.085          # ① 速度上限 m/s
    V_MIN     = 0.0            # 最小速度 (低于它算到位, 不追)
    JERK_MAX  = 3.642857       # ③ 加加速度上限 m/s³
    S_STEP    = 0.0085         # ⑤ 单拍位移上限 m (= V_CAP × dt)
    S_MAX     = 0.02           # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1            # ④ 质量变化率上限 kg/s

    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """运动学 ①②③⑤ + 动力学 ④ —— 逐条算, 算出来的就是下发动作。

        u 请求动作 [vx,vy,vz,夹爪] · v_prev/a_prev 上一拍速度/加速度 (缺省当 0)
        返回 u(下发) v_req(请求) err(被削的量) why(哪条削的) phys(本段数字)
        """
        import numpy as np                                  # 局部导入 (本模块按需加载, 不强制 numpy)
        dt = self.DT_S if dt is None else float(dt)
        m, F_max = self.M_KG, self.F_MAX_N
        u_req = np.asarray(u, dtype=float).ravel().copy()
        v = u_req[:3].copy()                                # 只约束平移 3 维, 夹爪原样下发
        v0 = np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy()
        a0 = np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy()
        why = []

        # ① 速度: ‖v‖ ≤ V_CAP (超了等比缩小, 方向不变)
        n_v = float(np.linalg.norm(v))
        if n_v > self.V_CAP > 0:
            v = v * (self.V_CAP / n_v)
            why.append("速度")

        # ② 加速度: 每拍速度变化 ‖v−v0‖ ≤ A_MAX·dt (A_MAX 就是真源标定的那个加速度)
        a_max = self.A_MAX
        a_lim = a_max * dt
        dv = v - v0
        n_dv = float(np.linalg.norm(dv))
        if n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")

        # ③ 加加速度: 每拍加速度变化 ‖Δa‖ ≤ JERK_MAX·dt (不许阶跃, 伺服带宽有限)
        a_new = (v - v0) / dt
        da = a_new - a0
        j_lim = self.JERK_MAX * dt
        n_da = float(np.linalg.norm(da))
        if n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * dt
            why.append("加加速度")
        kin_why = "+".join(why) or "可行"

        # ④ 动力学: 动量/质量率 ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取/释放时质量在变)
        _dmdt = self.DMDT_MAX if dmdt is None else float(dmdt)
        dv = v - v0
        f_lim = F_max * dt
        f_need = m * dv + v * (_dmdt * dt)
        n_f = float(np.linalg.norm(f_need))
        dyn_why = []
        if n_f > f_lim > 0:
            v = v0 + dv * (f_lim / max(n_f, 1e-9))
            dyn_why.append("动量/质量率")
            why.append("动量/质量率")

        # ⑤ 位移: 单拍 ‖v‖·dt ≤ S_STEP; 本段累计 > S_MAX 只报不杀
        d_step = float(np.linalg.norm(v)) * dt
        if self.S_STEP > 0 and d_step > self.S_STEP * (1.0 + 1e-12):
            v = v * (self.S_STEP / max(d_step, 1e-12))
            why.append("位移")
        self.travel_m = float(getattr(self, "travel_m", 0.0)) + float(np.linalg.norm(v)) * dt
        over = int(self.S_MAX > 0 and self.travel_m > self.S_MAX * (1.0 + 1e-9))

        # 收口: 下发动作 / 被削掉的偏差 / 本段数字
        u_out = u_req.copy()
        u_out[:3] = v
        err = u_req[:3] - v
        e_norm = float(np.linalg.norm(err))
        # 🔴 2026-10-31 老倪「技能 return 的断点全都进不去」:
        #   原来 return/_out 里直接写列表推导 [float(x) for x in ...] —— 推导式是**独立 code object**,
        #   它自己的首行号就是这一行 ⇒ 调试器(和 pdb)会停在 <listcomp> 帧, 看起来"断点没进到 clamp"。
        #   现在把三个列表先算出来 (纯本函数语句), 断点下在 _out = { 这行就**稳停在 clamp() 帧**。
        _u_list = [float(x) for x in u_out]
        _v_list = [float(x) for x in u_req[:3]]
        _e_list = [float(x) for x in err]
        _out = {"u": _u_list, "v_req": _v_list,
                "err": _e_list, "err_norm": round(e_norm, 8),
                "big": int(e_norm > 0.05),
                "why": "+".join(why) or "可行",
                "kin_why": kin_why,
                "dyn_why": "+".join(dyn_why) or "可行",
                "phys": {"m": round(m, 4), "F_max": F_max, "v_cap": self.V_CAP, "v_min": self.V_MIN,
                         "a_max": round(a_max, 4), "jerk_max": round(self.JERK_MAX, 3),
                         "dmdt_max": _dmdt, "s_step": self.S_STEP, "s_max": self.S_MAX, "dt": dt,
                         "src": self.source,
                         "calib": "本类常量 (真源 config/calib/zmax_skill_physics.json)"},
                "s_travel": round(self.travel_m, 6), "over_travel": over,
                "f_need_N": round(n_f, 6), "kin_called": 1, "dyn_called": 1}
        self.corridor_dbg()                        # 🛑 本技能的断点 (F9 打这一行/VSCode 直接停)
        return self.corridor_finish(_out)

class SK07Place(AtomicSkill):
    """⑦ 放入 (摆盘链 mode=tray) — 把光模块下放进 tray 槽位并释放 (替代插拔链的 SK07Insert)

    摆盘 = 取放, 不是插入: 无孔口/无接触推入, 终点 = 件底贴槽底面 (内底顶面 + 件半高)。
    与 SK07Insert 同编号同"决策层选定第 7 段"语义 —— **由任务配置选哪一支** (配置改变功能)。
    """
    code = "SK07"
    # 🎯 目标: 点位库的摆放点 (真机点位上下文; 仿真无点位库时返回 None)
    TARGET = {"ref": "point", "off_key": None}
    stage = "放入"          # 摆盘链里对应状态机的「放下」段 (ActionModulator.PLACE_IDX)
    # 🔵 通道: 放入 = 松爪+离开, plan 里没有独立位移段 ⇒ 零位移, 无运动通道 (如实标, 不造管子)
    CORRIDOR_ZERO_MOTION = True
    name = "⑦ 放入"
    desc = "件吊到目标槽位上方 → 垂直下放到槽底 → 开爪释放 (低速触底, 不压伤)"
    goal = "光模块中心 → tray 槽位中心 (z = 内底顶面 + 件半高 0.016m)"
    params = {"place_z": 0.016,             # 槽底落座高度 (真源: 内底 0.010 + 半高 0.006)
              "angle_tol_deg": 1.0,         # 姿态容差 (TASK-06-TRAY 判据 ≤1°)
              "xy_tol_m": 0.001,            # 单边 ≤1mm (TASK-06-TRAY 判据)
              "release_h": 0.004}           # 距槽底 4mm 内即开爪释放
    evidence = "件落进槽位 (|Δxy| ≤ 1mm, |Δyaw| ≤ 1°) + 已开爪 → 完成"
    ctrl = {"gripper": "闭合保持 → 触底开爪释放", "v_cap": 0.06, "v_min": 0.015}
    source = "cognition.ActionModulator TRAY_MODE/PLACE_IDX + sim_scene_def tray 槽位真源"

    phys_note = "本段=放入: v_cap=0.060 m/s · a_max=1.481 m/s² · 单拍位移 s_step=0.0060 m (全部取真源 config/calib/zmax_skill_physics.json 的 value; 类里不另存一份数字)。"
    # ══════════════════════════════════════════════════════════════════════════
    # 本技能的约束 — 数字全写在这里 (真源 config/calib/zmax_skill_physics.json · 段=放入)
    #   加速度上限取真源 a (标定值优先, 无标定才用牛顿二定律 F/m): 1.481481 m/s²
    # ══════════════════════════════════════════════════════════════════════════
    DT_S      = 0.1            # 每拍 0.1 s
    M_KG      = 1.35           # 运动质量 kg (已夹持)
    F_MAX_N   = 2.0            # 允许力 N (④ 动力量)
    A_MAX     = 1.481481       # ② 加速度上限 m/s² (真源 a 标定值; = F/m = 2.0/1.35)
    V_CAP     = 0.06           # ① 速度上限 m/s
    V_MIN     = 0.0            # 最小速度 (低于它算到位, 不追)
    JERK_MAX  = 2.571429       # ③ 加加速度上限 m/s³
    S_STEP    = 0.006          # ⑤ 单拍位移上限 m (= V_CAP × dt)
    S_MAX     = 0.6            # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.5            # ④ 质量变化率上限 kg/s

    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """运动学 ①②③⑤ + 动力学 ④ —— 逐条算, 算出来的就是下发动作。

        u 请求动作 [vx,vy,vz,夹爪] · v_prev/a_prev 上一拍速度/加速度 (缺省当 0)
        返回 u(下发) v_req(请求) err(被削的量) why(哪条削的) phys(本段数字)
        """
        import numpy as np                                  # 局部导入 (本模块按需加载, 不强制 numpy)
        dt = self.DT_S if dt is None else float(dt)
        m, F_max = self.M_KG, self.F_MAX_N
        u_req = np.asarray(u, dtype=float).ravel().copy()
        v = u_req[:3].copy()                                # 只约束平移 3 维, 夹爪原样下发
        v0 = np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy()
        a0 = np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy()
        why = []

        # ① 速度: ‖v‖ ≤ V_CAP (超了等比缩小, 方向不变)
        n_v = float(np.linalg.norm(v))
        if n_v > self.V_CAP > 0:
            v = v * (self.V_CAP / n_v)
            why.append("速度")

        # ② 加速度: 每拍速度变化 ‖v−v0‖ ≤ A_MAX·dt (A_MAX 就是真源标定的那个加速度)
        a_max = self.A_MAX
        a_lim = a_max * dt
        dv = v - v0
        n_dv = float(np.linalg.norm(dv))
        if n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")

        # ③ 加加速度: 每拍加速度变化 ‖Δa‖ ≤ JERK_MAX·dt (不许阶跃, 伺服带宽有限)
        a_new = (v - v0) / dt
        da = a_new - a0
        j_lim = self.JERK_MAX * dt
        n_da = float(np.linalg.norm(da))
        if n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * dt
            why.append("加加速度")
        kin_why = "+".join(why) or "可行"

        # ④ 动力学: 动量/质量率 ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取/释放时质量在变)
        _dmdt = self.DMDT_MAX if dmdt is None else float(dmdt)
        dv = v - v0
        f_lim = F_max * dt
        f_need = m * dv + v * (_dmdt * dt)
        n_f = float(np.linalg.norm(f_need))
        dyn_why = []
        if n_f > f_lim > 0:
            v = v0 + dv * (f_lim / max(n_f, 1e-9))
            dyn_why.append("动量/质量率")
            why.append("动量/质量率")

        # ⑤ 位移: 单拍 ‖v‖·dt ≤ S_STEP; 本段累计 > S_MAX 只报不杀
        d_step = float(np.linalg.norm(v)) * dt
        if self.S_STEP > 0 and d_step > self.S_STEP * (1.0 + 1e-12):
            v = v * (self.S_STEP / max(d_step, 1e-12))
            why.append("位移")
        self.travel_m = float(getattr(self, "travel_m", 0.0)) + float(np.linalg.norm(v)) * dt
        over = int(self.S_MAX > 0 and self.travel_m > self.S_MAX * (1.0 + 1e-9))

        # 收口: 下发动作 / 被削掉的偏差 / 本段数字
        u_out = u_req.copy()
        u_out[:3] = v
        err = u_req[:3] - v
        e_norm = float(np.linalg.norm(err))
        # 🔴 2026-10-31 老倪「技能 return 的断点全都进不去」:
        #   原来 return/_out 里直接写列表推导 [float(x) for x in ...] —— 推导式是**独立 code object**,
        #   它自己的首行号就是这一行 ⇒ 调试器(和 pdb)会停在 <listcomp> 帧, 看起来"断点没进到 clamp"。
        #   现在把三个列表先算出来 (纯本函数语句), 断点下在 _out = { 这行就**稳停在 clamp() 帧**。
        _u_list = [float(x) for x in u_out]
        _v_list = [float(x) for x in u_req[:3]]
        _e_list = [float(x) for x in err]
        _out = {"u": _u_list, "v_req": _v_list,
                "err": _e_list, "err_norm": round(e_norm, 8),
                "big": int(e_norm > 0.05),
                "why": "+".join(why) or "可行",
                "kin_why": kin_why,
                "dyn_why": "+".join(dyn_why) or "可行",
                "phys": {"m": round(m, 4), "F_max": F_max, "v_cap": self.V_CAP, "v_min": self.V_MIN,
                         "a_max": round(a_max, 4), "jerk_max": round(self.JERK_MAX, 3),
                         "dmdt_max": _dmdt, "s_step": self.S_STEP, "s_max": self.S_MAX, "dt": dt,
                         "src": self.source,
                         "calib": "本类常量 (真源 config/calib/zmax_skill_physics.json)"},
                "s_travel": round(self.travel_m, 6), "over_travel": over,
                "f_need_N": round(n_f, 6), "kin_called": 1, "dyn_called": 1}
        self.corridor_dbg()                        # 🛑 本技能的断点 (F9 打这一行/VSCode 直接停)
        return self.corridor_finish(_out)

class SK08Complete(AtomicSkill):
    """⑧ 完成 — 插入到位, 本轮任务结束 (mode=full 续拔出/AOI 链)"""
    code = "SK08"
    # 🎯 目标: 保持在插入终点 (hole − 真实夹持偏移)
    TARGET = {"ref": "hole",        "off_key": None}
    stage = "完成"
    name = "⑧ 完成"
    desc = "插入深度达标 → 任务完成 (mode=insert 终点; full 模式插入后进入拔出链)"
    goal = "保持 (已插到底)"
    params = {"done": "depth < insert_depth 连续确认", "mode_full_next": "拔出"}
    evidence = "阶段 == 完成 (done)"
    ctrl = {"gripper": "闭合保持", "v_cap": 0.02}
    source = "cognition.ActionModulator STAGES[完成]"

    phys_note = "本段=完成: v_cap=0.020 m/s · a_max=1.481 m/s² · 单拍位移 s_step=0.0020 m (全部取真源 config/calib/zmax_skill_physics.json 的 value; 类里不另存一份数字)。"
    # ══════════════════════════════════════════════════════════════════════════
    # 本技能的约束 — 数字全写在这里 (真源 config/calib/zmax_skill_physics.json · 段=完成)
    #   加速度上限取真源 a (标定值优先, 无标定才用牛顿二定律 F/m): 1.481481 m/s²
    # ══════════════════════════════════════════════════════════════════════════
    DT_S      = 0.1            # 每拍 0.1 s
    M_KG      = 1.35           # 运动质量 kg (已夹持)
    F_MAX_N   = 2.0            # 允许力 N (④ 动力量)
    A_MAX     = 1.481481       # ② 加速度上限 m/s² (真源 a 标定值; = F/m = 2.0/1.35)
    V_CAP     = 0.02           # ① 速度上限 m/s
    V_MIN     = 0.0            # 最小速度 (低于它算到位, 不追)
    JERK_MAX  = 2.25           # ③ 加加速度上限 m/s³
    S_STEP    = 0.002          # ⑤ 单拍位移上限 m (= V_CAP × dt)
    S_MAX     = 0.002          # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1            # ④ 质量变化率上限 kg/s

    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """运动学 ①②③⑤ + 动力学 ④ —— 逐条算, 算出来的就是下发动作。

        u 请求动作 [vx,vy,vz,夹爪] · v_prev/a_prev 上一拍速度/加速度 (缺省当 0)
        返回 u(下发) v_req(请求) err(被削的量) why(哪条削的) phys(本段数字)
        """
        import numpy as np                                  # 局部导入 (本模块按需加载, 不强制 numpy)
        dt = self.DT_S if dt is None else float(dt)
        m, F_max = self.M_KG, self.F_MAX_N
        u_req = np.asarray(u, dtype=float).ravel().copy()
        v = u_req[:3].copy()                                # 只约束平移 3 维, 夹爪原样下发
        v0 = np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy()
        a0 = np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy()
        why = []

        # ① 速度: ‖v‖ ≤ V_CAP (超了等比缩小, 方向不变)
        n_v = float(np.linalg.norm(v))
        if n_v > self.V_CAP > 0:
            v = v * (self.V_CAP / n_v)
            why.append("速度")

        # ② 加速度: 每拍速度变化 ‖v−v0‖ ≤ A_MAX·dt (A_MAX 就是真源标定的那个加速度)
        a_max = self.A_MAX
        a_lim = a_max * dt
        dv = v - v0
        n_dv = float(np.linalg.norm(dv))
        if n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")

        # ③ 加加速度: 每拍加速度变化 ‖Δa‖ ≤ JERK_MAX·dt (不许阶跃, 伺服带宽有限)
        a_new = (v - v0) / dt
        da = a_new - a0
        j_lim = self.JERK_MAX * dt
        n_da = float(np.linalg.norm(da))
        if n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * dt
            why.append("加加速度")
        kin_why = "+".join(why) or "可行"

        # ④ 动力学: 动量/质量率 ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取/释放时质量在变)
        _dmdt = self.DMDT_MAX if dmdt is None else float(dmdt)
        dv = v - v0
        f_lim = F_max * dt
        f_need = m * dv + v * (_dmdt * dt)
        n_f = float(np.linalg.norm(f_need))
        dyn_why = []
        if n_f > f_lim > 0:
            v = v0 + dv * (f_lim / max(n_f, 1e-9))
            dyn_why.append("动量/质量率")
            why.append("动量/质量率")

        # ⑤ 位移: 单拍 ‖v‖·dt ≤ S_STEP; 本段累计 > S_MAX 只报不杀
        d_step = float(np.linalg.norm(v)) * dt
        if self.S_STEP > 0 and d_step > self.S_STEP * (1.0 + 1e-12):
            v = v * (self.S_STEP / max(d_step, 1e-12))
            why.append("位移")
        self.travel_m = float(getattr(self, "travel_m", 0.0)) + float(np.linalg.norm(v)) * dt
        over = int(self.S_MAX > 0 and self.travel_m > self.S_MAX * (1.0 + 1e-9))

        # 收口: 下发动作 / 被削掉的偏差 / 本段数字
        u_out = u_req.copy()
        u_out[:3] = v
        err = u_req[:3] - v
        e_norm = float(np.linalg.norm(err))
        # 🔴 2026-10-31 老倪「技能 return 的断点全都进不去」:
        #   原来 return/_out 里直接写列表推导 [float(x) for x in ...] —— 推导式是**独立 code object**,
        #   它自己的首行号就是这一行 ⇒ 调试器(和 pdb)会停在 <listcomp> 帧, 看起来"断点没进到 clamp"。
        #   现在把三个列表先算出来 (纯本函数语句), 断点下在 _out = { 这行就**稳停在 clamp() 帧**。
        _u_list = [float(x) for x in u_out]
        _v_list = [float(x) for x in u_req[:3]]
        _e_list = [float(x) for x in err]
        _out = {"u": _u_list, "v_req": _v_list,
                "err": _e_list, "err_norm": round(e_norm, 8),
                "big": int(e_norm > 0.05),
                "why": "+".join(why) or "可行",
                "kin_why": kin_why,
                "dyn_why": "+".join(dyn_why) or "可行",
                "phys": {"m": round(m, 4), "F_max": F_max, "v_cap": self.V_CAP, "v_min": self.V_MIN,
                         "a_max": round(a_max, 4), "jerk_max": round(self.JERK_MAX, 3),
                         "dmdt_max": _dmdt, "s_step": self.S_STEP, "s_max": self.S_MAX, "dt": dt,
                         "src": self.source,
                         "calib": "本类常量 (真源 config/calib/zmax_skill_physics.json)"},
                "s_travel": round(self.travel_m, 6), "over_travel": over,
                "f_need_N": round(n_f, 6), "kin_called": 1, "dyn_called": 1}
        self.corridor_dbg()                        # 🛑 本技能的断点 (F9 打这一行/VSCode 直接停)
        return self.corridor_finish(_out)


# ══════════════════════════════════════════════════════════════════════════════
# full 模式 4 段技能 (SK09-12) — 2026-11-01
#   insert/tray 之外的完整工艺链: 完成 → 拔出 → AOI转移 → AOI检测 → 回程 → 放下
#   这 4 段过去只有物理量配置 (config/calib/zmax_skill_physics.json) 和段名,
#   没有技能类 ⇒ skill_for() 返回 None ⇒ 一律走通用闸, 技能 return/断点永不进。
#   现在补类: 数字全部由 config/calib/zmax_skill_physics.json 生成, clamp 与 SK01-08 同一套算式。
# ══════════════════════════════════════════════════════════════════════════════
class _StageClamp(AtomicSkill):
    """共用 clamp (①②③④⑤ 逐条算) — 与 SK01-08 的 clamp 逐字同一套算式, 只有数字按本段取。"""

    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """运动学 ①②③⑤ + 动力学 ④ —— 逐条算, 算出来的就是下发动作。

        u 请求动作 [vx,vy,vz,夹爪] · v_prev/a_prev 上一拍速度/加速度 (缺省当 0)
        返回 u(下发) v_req(请求) err(被削的量) why(哪条削的) phys(本段数字)
        """
        import numpy as np                                  # 局部导入 (本模块按需加载, 不强制 numpy)
        dt = self.DT_S if dt is None else float(dt)
        m, F_max = self.M_KG, self.F_MAX_N
        u_req = np.asarray(u, dtype=float).ravel().copy()
        v = u_req[:3].copy()                                # 只约束平移 3 维, 夹爪原样下发
        v0 = np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy()
        a0 = np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy()
        why = []

        # ① 速度: ‖v‖ ≤ V_CAP (超了等比缩小, 方向不变)
        n_v = float(np.linalg.norm(v))
        if n_v > self.V_CAP > 0:
            v = v * (self.V_CAP / n_v)
            why.append("速度")

        # ② 加速度: 每拍速度变化 ‖v−v0‖ ≤ A_MAX·dt (A_MAX 就是真源标定的那个加速度)
        a_max = self.A_MAX
        a_lim = a_max * dt
        dv = v - v0
        n_dv = float(np.linalg.norm(dv))
        if n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")

        # ③ 加加速度: 每拍加速度变化 ‖Δa‖ ≤ JERK_MAX·dt (不许阶跃, 伺服带宽有限)
        a_new = (v - v0) / dt
        da = a_new - a0
        j_lim = self.JERK_MAX * dt
        n_da = float(np.linalg.norm(da))
        if n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * dt
            why.append("加加速度")
        kin_why = "+".join(why) or "可行"

        # ④ 动力学: 动量/质量率 ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取/释放时质量在变)
        _dmdt = self.DMDT_MAX if dmdt is None else float(dmdt)
        dv = v - v0
        f_lim = F_max * dt
        f_need = m * dv + v * (_dmdt * dt)
        n_f = float(np.linalg.norm(f_need))
        dyn_why = []
        if n_f > f_lim > 0:
            v = v0 + dv * (f_lim / max(n_f, 1e-9))
            dyn_why.append("动量/质量率")
            why.append("动量/质量率")

        # ⑤ 位移: 单拍 ‖v‖·dt ≤ S_STEP; 本段累计 > S_MAX 只报不杀
        d_step = float(np.linalg.norm(v)) * dt
        if self.S_STEP > 0 and d_step > self.S_STEP * (1.0 + 1e-12):
            v = v * (self.S_STEP / max(d_step, 1e-12))
            why.append("位移")
        self.travel_m = float(getattr(self, "travel_m", 0.0)) + float(np.linalg.norm(v)) * dt
        over = int(self.S_MAX > 0 and self.travel_m > self.S_MAX * (1.0 + 1e-9))

        # 收口: 下发动作 / 被削掉的偏差 / 本段数字
        u_out = u_req.copy()
        u_out[:3] = v
        err = u_req[:3] - v
        e_norm = float(np.linalg.norm(err))
        # 🔴 2026-10-31 老倪「技能 return 的断点全都进不去」:
        #   原来 return/_out 里直接写列表推导 [float(x) for x in ...] —— 推导式是**独立 code object**,
        #   它自己的首行号就是这一行 ⇒ 调试器(和 pdb)会停在 <listcomp> 帧, 看起来"断点没进到 clamp"。
        #   现在把三个列表先算出来 (纯本函数语句), 断点下在 _out = { 这行就**稳停在 clamp() 帧**。
        _u_list = [float(x) for x in u_out]
        _v_list = [float(x) for x in u_req[:3]]
        _e_list = [float(x) for x in err]
        _out = {"u": _u_list, "v_req": _v_list,
                "err": _e_list, "err_norm": round(e_norm, 8),
                "big": int(e_norm > 0.05),
                "why": "+".join(why) or "可行",
                "kin_why": kin_why,
                "dyn_why": "+".join(dyn_why) or "可行",
                "phys": {"m": round(m, 4), "F_max": F_max, "v_cap": self.V_CAP, "v_min": self.V_MIN,
                         "a_max": round(a_max, 4), "jerk_max": round(self.JERK_MAX, 3),
                         "dmdt_max": _dmdt, "s_step": self.S_STEP, "s_max": self.S_MAX, "dt": dt,
                         "src": self.source,
                         "calib": "本类常量 (真源 config/calib/zmax_skill_physics.json)"},
                "s_travel": round(self.travel_m, 6), "over_travel": over,
                "f_need_N": round(n_f, 6), "kin_called": 1, "dyn_called": 1}
        self.corridor_dbg()                        # 🛑 本技能的断点 (F9 打这一行/VSCode 直接停)
        return self.corridor_finish(_out)


class SK09Pull(_StageClamp):
    """夹持件沿孔轴向上退出 45mm (独立限速 60mm/s, 不与插入共用速度)"""
    code = "SK09"
    TARGET = {"ref": "rel", "axis": "z_pos", "d_m": 0.045}   # 退出 45mm (真源 s=0.045)
    stage = "拔出"
    name = "⑨ 拔出"
    desc = "夹持件沿孔轴向上退出 45mm (独立限速 60mm/s, 不与插入共用速度)"
    goal = "已插入件 → 退出孔口 (退出行程 ≥ pull_out_m 判完成)"
    params = {"pull_out_m": 0.045, "release_after": "退出后保持夹持, 由 SK08 放下"}
    evidence = "退出位移 ≥ pull_out_m 且孔口无拖拽 (力/位移双判)"
    ctrl = {"gripper": "闭合保持 (退出全程不松)", "v_cap": 0.06, "v_min": 0.02}
    source = "config/calib/zmax_skill_physics.json · 段=拔出 (v/a/jerk/s/s_step/m/F/dmdt 逐项取 value)"
    phys_note = "本段=拔出: 速度上限取真源 v(0.06 m/s, 独立 60mm/s 物理限), 加速度=a 标定值, 行程 s=pull_out_m(0.045 m) ⇒ 单拍位移 ≤ s_step。"

    DT_S      = 0.1          # 每拍 s
    M_KG      = 1.35         # 运动质量 kg
    F_MAX_N   = 5.0          # 允许力 N
    A_MAX     = 3.703704     # ② 加速度上限 m/s²
    V_CAP     = 0.06         # ① 速度上限 m/s
    V_MIN     = 0.02         # 最小速度 (低于它算到位)
    JERK_MAX  = 2.571429     # ③ 加加速度上限 m/s³
    S_STEP    = 0.006        # ⑤ 单拍位移上限 m
    S_MAX     = 0.045        # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1          # ④ 质量变化率上限 kg/s

class SK10AoiTransfer(_StageClamp):
    """把件从取料侧搬到 AOI 检测位 (快速大行程段, 600mm 级)"""
    code = "SK10"
    TARGET = {"ref": "point"}
    stage = "AOI转移"
    name = "⑩ AOI转移"
    desc = "把件从取料侧搬到 AOI 检测位 (快速大行程段, 600mm 级)"
    goal = "件 → AOI 检测位点位 (xy 容差 1mm)"
    params = {"point": "aoi_pose", "xy_tol_m": 0.001}
    evidence = "到位残差 ≤ 1mm 且姿态偏差 ≤ 1°"
    ctrl = {"gripper": "闭合保持", "v_cap": 0.3, "v_min": 0.1}
    source = "config/calib/zmax_skill_physics.json · 段=AOI转移 (v/a/jerk/s/s_step/m/F/dmdt 逐项取 value)"
    phys_note = "本段=AOI转移: 快速搬运段 ⇒ v=0.30 m/s、jerk 放宽到 12.86 m/s³ (真源 a/jerk 分别取值), 单拍位移 s_step=0.030 m。"

    DT_S      = 0.1          # 每拍 s
    M_KG      = 1.35         # 运动质量 kg
    F_MAX_N   = 5.0          # 允许力 N
    A_MAX     = 3.703704     # ② 加速度上限 m/s²
    V_CAP     = 0.3          # ① 速度上限 m/s
    V_MIN     = 0.1          # 最小速度 (低于它算到位)
    JERK_MAX  = 12.857143    # ③ 加加速度上限 m/s³
    S_STEP    = 0.03         # ⑤ 单拍位移上限 m
    S_MAX     = 0.6          # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1          # ④ 质量变化率上限 kg/s

class SK11AoiInspect(_StageClamp):
    """在 AOI 检测位做毫米级微进给并保持静止, 由 8793/10082/10083 服务出判据"""
    code = "SK11"
    TARGET = {"ref": "point"}
    stage = "AOI检测"
    name = "⑪ AOI检测"
    desc = "在 AOI 检测位做毫米级微进给并保持静止, 由 8793/10082/10083 服务出判据"
    goal = "件 → 检测工位 (静止保持, 检测期间零位移)"
    params = {"point": "aoi_pose", "dwell_s": 1.5, "detect_api": "/aoi/gold|/aoi/surface"}
    evidence = "静止保持 + 检测服务返回 verdict (ok/ng) 才算本段完成"
    ctrl = {"gripper": "闭合保持", "v_cap": 0.05, "v_min": 0.0}
    source = "config/calib/zmax_skill_physics.json · 段=AOI检测 (v/a/jerk/s/s_step/m/F/dmdt 逐项取 value)"
    phys_note = "本段=AOI检测: 微进给段 ⇒ v=0.05 m/s、单拍 0.005 m、行程 0.03 m; 静止保持期间速度必须压到 v_min 以下 (真源 v_min=0.0)。"

    DT_S      = 0.1          # 每拍 s
    M_KG      = 1.35         # 运动质量 kg
    F_MAX_N   = 5.0          # 允许力 N
    A_MAX     = 3.703704     # ② 加速度上限 m/s²
    V_CAP     = 0.05         # ① 速度上限 m/s
    V_MIN     = 0.0          # 最小速度 (低于它算到位)
    JERK_MAX  = 2.25         # ③ 加加速度上限 m/s³
    S_STEP    = 0.005        # ⑤ 单拍位移上限 m
    S_MAX     = 0.03         # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1          # ④ 质量变化率上限 kg/s

class SK12Return(_StageClamp):
    """检测完把件送回取放位/原点 (与 AOI转移同速, 大行程)"""
    code = "SK12"
    TARGET = {"ref": "point"}
    stage = "回程"
    name = "⑫ 回程"
    desc = "检测完把件送回取放位/原点 (与 AOI转移同速, 大行程)"
    goal = "件 → 回程目标点 (xy 容差 1mm)"
    params = {"point": "home_pose", "xy_tol_m": 0.001}
    evidence = "到位残差 ≤ 1mm"
    ctrl = {"gripper": "闭合保持", "v_cap": 0.3, "v_min": 0.1}
    source = "config/calib/zmax_skill_physics.json · 段=回程 (v/a/jerk/s/s_step/m/F/dmdt 逐项取 value)"
    phys_note = "本段=回程: 与 AOI转移 同参数 (v=0.30 m/s, jerk=12.86 m/s³), 单拍 0.030 m。"

    DT_S      = 0.1          # 每拍 s
    M_KG      = 1.35         # 运动质量 kg
    F_MAX_N   = 5.0          # 允许力 N
    A_MAX     = 3.703704     # ② 加速度上限 m/s²
    V_CAP     = 0.3          # ① 速度上限 m/s
    V_MIN     = 0.1          # 最小速度 (低于它算到位)
    JERK_MAX  = 12.857143    # ③ 加加速度上限 m/s³
    S_STEP    = 0.03         # ⑤ 单拍位移上限 m
    S_MAX     = 0.6          # ⑤ 本段行程上限 m
    DMDT_MAX  = 0.1          # ④ 质量变化率上限 kg/s


# ── 技能注册表 (插装 8 段; 顺序 = 状态机推进序) ──
SKILLS = [SK01Approach, SK02Align, SK03Descend, SK04Grasp,
          SK05Lift, SK06Transfer, SK07Insert, SK08Complete]

# 🧩 摆盘链 (mode="tray", 2026-10-10): 第 7 段 = 「放入」而不是「插入」。
#    两条链共用 SK01-06/SK08, 只有第 7 段分叉 ⇒ **同一工程按任务配置选哪条链** (配置改变功能)。
#    SKILL_BY_CODE 保持插拔链语义 (SK07=插入), 摆盘查询请用 skills_for_mode("tray")。
SKILLS_TRAY = [SK01Approach, SK02Align, SK03Descend, SK04Grasp,
               SK05Lift, SK06Transfer, SK07Place, SK08Complete]

# stage → 技能 (状态机当前阶段 → 当前技能模板)
SKILL_BY_STAGE = {cls.stage: cls for cls in SKILLS}
SKILL_BY_STAGE.update({cls.stage: cls for cls in SKILLS_TRAY})   # 追加「放入」(键不冲突)
# code → 技能
# 🧩 full 链 (2026-11-01): 完成 → 拔出 → AOI转移 → AOI检测 → 回程 → 放下
SKILLS_FULL = [SK01Approach, SK02Align, SK03Descend, SK04Grasp, SK05Lift, SK06Transfer,
               SK08Complete, SK09Pull, SK10AoiTransfer, SK11AoiInspect, SK12Return, SK07Place]
SKILL_BY_STAGE.update({cls.stage: cls for cls in SKILLS_FULL})
SKILLS_FULL_CODES = SKILLS_FULL
SKILL_BY_CODE = {cls.code: cls for cls in SKILLS}
SKILL_BY_CODE_TRAY = {cls.code: cls for cls in SKILLS_TRAY}


def skills_for_mode(mode="insert"):
    """按任务模式取技能链: tray(摆盘) → SK07 是「放入」; 其它 → SK07 是「插入」"""
    _m = str(mode).lower()
    if _m == "tray":
        return list(SKILLS_TRAY)
    if _m == "full":
        return list(SKILLS_FULL)
    return list(SKILLS)


def list_skills(mode="insert"):
    """技能清单 (GUI/文档/测试复用)"""
    return [{"code": cls.code, "name": cls.name, "stage": cls.stage,
             "desc": cls.desc, "goal": cls.goal, "params": dict(cls.params),
             "evidence": cls.evidence, "ctrl": dict(cls.ctrl),
             "source": cls.source,
             # ⚖ 物理模型 (老倪 2026-10-15: 每个技能要能看到自己的物理方程): 方程五式 + 本段绑定说明
             "phys_note": getattr(cls, "phys_note", ""),
             "phys_equations": dict(getattr(cls, "EQ", {})),
             "phys": {**{k: cls.phys().get(k) for k in
                         ("m", "F", "v", "v_min", "a_max", "jerk_max", "s_step", "s_max")},
                      "dmdt_max": (cls.phys().get("dmdt_max") or cls.phys().get("dmdt"))},
             "phys_bounds": cls.phys_bounds()}
            for cls in skills_for_mode(mode)]


if __name__ == "__main__":
    print("=== Z-MAX 原子技能库 (SK01-08, 真实源) ===")
    for s in list_skills():
        print(f"  {s['code']} {s['name']} [{s['stage']}] {s['desc']}")
        print(f"      目标: {s['goal']}")
        print(f"      推进: {s['evidence']}")
        print(f"      参数: {s['params']}  ctrl: {s['ctrl']}")
        if s.get("phys"):
            ph = s["phys"]
            print("      ⚖ 物理: m=%.2fkg F≤%.1fN v≤%.3fm/s a≤%.2fm/s² jerk≤%.1fm/s³ 单拍位移≤%.4fm "
                  "段行程≤%.3fm dm/dt≤%.2fkg/s"
                  % (ph["m"], ph["F"], ph["v"], ph["a_max"], ph["jerk_max"], ph["s_step"],
                     ph["s_max"], ph["dmdt_max"]))
            print("         方程: " + " | ".join("%s %s" % (k, v[0]) for k, v in (s.get("phys_equations") or {}).items()))
            print("         本段: %s" % s.get("phys_note", ""))




# ── stage → 技能类 索引 (派发链按阶段找技能对象, 不自己编号) ─────────────────────────
def _index_by_stage():
    out = {}
    for _v in list(globals().values()):
        if isinstance(_v, type) and issubclass(_v, AtomicSkill) and getattr(_v, "code", "SK--") != "SK--":
            out.setdefault(str(_v.stage), _v)          # 同段多个类时取先定义的 (真源只能有一个)
    return out


SKILL_BY_STAGE = _index_by_stage()

# 🔴 2026-10-31 老倪「所有技能的 return 都没进入」:
#   摆盘链 转移→放入 的落点是 STAGES[11] =「放下」(PLACE_IDX=11), 而技能类声明的段名是「放入」,
#   ⇒ skill_for("放下") 返回 None ⇒ 落件段走通用闸, SK07Place 的 return 一拍都不执行 (断点永不进)。
#   显式别名: 放下 ⇔ 放入 是同一段工艺的两个叫法, 用同一个类 (同一份算式/同一条断点)。
SKILL_BY_STAGE.setdefault("放下", SKILL_BY_STAGE.get("放入"))


def bind_limiter(lim):
    """把**外部闸实例**绑成技能调用口用的那一个 (派发链 ↔ 信号分析必须共用同一实例)。

    为什么必须共用: 段累计行程 `travel` / 上拍速度 `last_v` / 削因计数都是**跨拍状态**,
    两处各持一个实例 ⇒ 行程与削因各记一半 (信号分析里 s_mm 直接变 0, 判据也数不准调用次数)。
    """
    AtomicSkill._LIMITER = lim
    return lim


def rule_for_skill(sk):
    """registry 技能 (data/skills/l2_atomic/registry.json) → 目标规则。**97 条全覆盖**。

      · ros=line_abs / 多阶段技能的阶段 to ⇒ {"ref":"point"}  (点位库 + 偏置 0)
      · ros=line_rel                      ⇒ {"ref":"rel", "axis": …}  (当前位姿 + 轴偏移)
      · 服务型 (ros=service/url 调用, 如 AOI 接口) ⇒ None (它不产生位姿目标, 别硬塞)
    返回 None = 该技能没有位姿目标 (调用方如实退回原逻辑)。
    """
    if not isinstance(sk, dict):
        return None
    _ros = str(sk.get("ros") or "").strip().lower()
    if _ros == "line_abs":
        return {"ref": "point"}
    if _ros == "line_rel":
        return {"ref": "rel", "axis": str(sk.get("axis") or "z_pos")}
    return None


def target_of_skill(sk, points=None, spec=None, cur=None):
    """按 registry 技能定义解析目标位姿 (不依赖具体 SK 类): {xyz,quat,ref,src} 或 None。"""
    r = rule_for_skill(sk)
    if not r:
        return None
    # 一次性子类承载规则 (不改任何具体技能类的 TARGET, 也不动全局状态)
    _tmp = type("SKTmp", (AtomicSkill,),
                {"TARGET": r, "stage": str(sk.get("id") or ""), "params": {}})
    return _tmp.next_target(points=points, spec=spec, cur=cur)


def skill_for(stage):
    """按段名取技能类 (没有对应技能类的段返回 None ⇒ 派发链退回同段真源闸, 如实登记)。"""
    return SKILL_BY_STAGE.get(str(stage))