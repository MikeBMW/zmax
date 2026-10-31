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
            _d = float((spec or {}).get("d_m") or 0.0)
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

    # ⚖ 物理模型调用 (真语句, 不是注释): 本段每拍动作 → 五式闸
    #   老倪 2026-10-15:「原子技能, 哪里是调用物理模型的?」⇒ 类体里就能看到这一条;
    #   实现落在基类 AtomicSkill.apply_physics → physics_constraints.InertiaLimiter.limit。
    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """⚖ 本段动作过物理模型 (①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移)。

        🔴 2026-10-31 老倪「这个 clamp 也没有断点啊」⇒ 拆成两步写, 为的是断点:
           在 `return r` 那行打红点, 调试器里直接看得到 r 的全部字段
           (u / v_req / err / why / kin_why / dyn_why / phys), 而不是只剩一个 return 表达式。
           行为逐位不变 (同一调用、同一返回)。
        """
        r = self.apply_physics(u, dt=dt, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt)
        return r

    # ⚖ 物理模型 (五式, 与闸门 physics_constraints ①..⑤ 一一对应; 数值取真源, 类里不抄数字)
    #   ① 位移←速度:  s = ∫v dt   ,  ‖v‖·dt ≤ s_step          (单拍位移封顶, 段累计 ≤ s_max)
    #   ② 速度←加速度: v = ∫a dt   ,  ‖Δv‖ ≤ a_max·dt, a_max = F_max/m   (牛顿二定律)
    #   ③ 加加速度:    a = ∫j dt   ,  ‖Δa‖ ≤ jerk_max·dt       (伺服带宽有限, 不许阶跃)
    #   ④ 动量/质量率: p = m·v     ,  ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取建立/释放时质量在变)
    #   ⑤ 惯量:        F = m·a     ⇒  a = F/m
    #   带本段真实数字的方程: SK01Approach.show_phys()
    phys_note = '未夹持 m=1.20kg · F=5N 通用力 · dm/dt=0.1 ⇒ ①(±0.35m/s)+②(4.17m/s²)绑; ④ 非绑定'


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

    # ⚖ 物理模型调用 (真语句, 不是注释): 本段每拍动作 → 五式闸
    #   老倪 2026-10-15:「原子技能, 哪里是调用物理模型的?」⇒ 类体里就能看到这一条;
    #   实现落在基类 AtomicSkill.apply_physics → physics_constraints.InertiaLimiter.limit。
    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """⚖ 本段动作过物理模型 (①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移)。

        🔴 2026-10-31 老倪「这个 clamp 也没有断点啊」⇒ 拆成两步写, 为的是断点:
           在 `return r` 那行打红点, 调试器里直接看得到 r 的全部字段
           (u / v_req / err / why / kin_why / dyn_why / phys), 而不是只剩一个 return 表达式。
           行为逐位不变 (同一调用、同一返回)。
        """
        r = self.apply_physics(u, dt=dt, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt)
        return r

    # ⚖ 物理模型 (五式, 与闸门 physics_constraints ①..⑤ 一一对应; 数值取真源, 类里不抄数字)
    #   ① 位移←速度:  s = ∫v dt   ,  ‖v‖·dt ≤ s_step          (单拍位移封顶, 段累计 ≤ s_max)
    #   ② 速度←加速度: v = ∫a dt   ,  ‖Δv‖ ≤ a_max·dt, a_max = F_max/m   (牛顿二定律)
    #   ③ 加加速度:    a = ∫j dt   ,  ‖Δa‖ ≤ jerk_max·dt       (伺服带宽有限, 不许阶跃)
    #   ④ 动量/质量率: p = m·v     ,  ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取建立/释放时质量在变)
    #   ⑤ 惯量:        F = m·a     ⇒  a = F/m
    #   带本段真实数字的方程: SK02Align.show_phys()
    phys_note = '未夹持 m=1.20kg · F=5N · v 收到 0.12m/s ⇒ ①+③(jerk 5.1)绑; ④ 非绑定'


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

    # ⚖ 物理模型调用 (真语句, 不是注释): 本段每拍动作 → 五式闸
    #   老倪 2026-10-15:「原子技能, 哪里是调用物理模型的?」⇒ 类体里就能看到这一条;
    #   实现落在基类 AtomicSkill.apply_physics → physics_constraints.InertiaLimiter.limit。
    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """⚖ 本段动作过物理模型 (①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移)。

        🔴 2026-10-31 老倪「这个 clamp 也没有断点啊」⇒ 拆成两步写, 为的是断点:
           在 `return r` 那行打红点, 调试器里直接看得到 r 的全部字段
           (u / v_req / err / why / kin_why / dyn_why / phys), 而不是只剩一个 return 表达式。
           行为逐位不变 (同一调用、同一返回)。
        """
        r = self.apply_physics(u, dt=dt, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt)
        return r

    # ⚖ 物理模型 (五式, 与闸门 physics_constraints ①..⑤ 一一对应; 数值取真源, 类里不抄数字)
    #   ① 位移←速度:  s = ∫v dt   ,  ‖v‖·dt ≤ s_step          (单拍位移封顶, 段累计 ≤ s_max)
    #   ② 速度←加速度: v = ∫a dt   ,  ‖Δv‖ ≤ a_max·dt, a_max = F_max/m   (牛顿二定律)
    #   ③ 加加速度:    a = ∫j dt   ,  ‖Δa‖ ≤ jerk_max·dt       (伺服带宽有限, 不许阶跃)
    #   ④ 动量/质量率: p = m·v     ,  ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取建立/释放时质量在变)
    #   ⑤ 惯量:        F = m·a     ⇒  a = F/m
    #   带本段真实数字的方程: SK03Descend.show_phys()
    phys_note = '未夹持 m=1.20kg · 触到即停 ⇒ ①(0.09m/s)+③绑; 段行程 s_max=0.05 收紧(=对位悬停高度)'


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

    # ⚖ 物理模型调用 (真语句, 不是注释): 本段每拍动作 → 五式闸
    #   老倪 2026-10-15:「原子技能, 哪里是调用物理模型的?」⇒ 类体里就能看到这一条;
    #   实现落在基类 AtomicSkill.apply_physics → physics_constraints.InertiaLimiter.limit。
    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """⚖ 本段动作过物理模型 (①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移)。

        🔴 2026-10-31 老倪「这个 clamp 也没有断点啊」⇒ 拆成两步写, 为的是断点:
           在 `return r` 那行打红点, 调试器里直接看得到 r 的全部字段
           (u / v_req / err / why / kin_why / dyn_why / phys), 而不是只剩一个 return 表达式。
           行为逐位不变 (同一调用、同一返回)。
        """
        r = self.apply_physics(u, dt=dt, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt)
        return r

    # ⚖ 物理模型 (五式, 与闸门 physics_constraints ①..⑤ 一一对应; 数值取真源, 类里不抄数字)
    #   ① 位移←速度:  s = ∫v dt   ,  ‖v‖·dt ≤ s_step          (单拍位移封顶, 段累计 ≤ s_max)
    #   ② 速度←加速度: v = ∫a dt   ,  ‖Δv‖ ≤ a_max·dt, a_max = F_max/m   (牛顿二定律)
    #   ③ 加加速度:    a = ∫j dt   ,  ‖Δa‖ ≤ jerk_max·dt       (伺服带宽有限, 不许阶跃)
    #   ④ 动量/质量率: p = m·v     ,  ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取建立/释放时质量在变)
    #   ⑤ 惯量:        F = m·a     ⇒  a = F/m
    #   带本段真实数字的方程: SK04Grasp.show_phys()
    phys_note = '夹持建立 m 1.20→1.28 · F=12N(夹爪最大夹持力) · **dm/dt=0.5kg/s ⇒ ④ 真绑定** (动量变化要付得起)'


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

    # ⚖ 物理模型调用 (真语句, 不是注释): 本段每拍动作 → 五式闸
    #   老倪 2026-10-15:「原子技能, 哪里是调用物理模型的?」⇒ 类体里就能看到这一条;
    #   实现落在基类 AtomicSkill.apply_physics → physics_constraints.InertiaLimiter.limit。
    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """⚖ 本段动作过物理模型 (①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移)。

        🔴 2026-10-31 老倪「这个 clamp 也没有断点啊」⇒ 拆成两步写, 为的是断点:
           在 `return r` 那行打红点, 调试器里直接看得到 r 的全部字段
           (u / v_req / err / why / kin_why / dyn_why / phys), 而不是只剩一个 return 表达式。
           行为逐位不变 (同一调用、同一返回)。
        """
        r = self.apply_physics(u, dt=dt, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt)
        return r

    # ⚖ 物理模型 (五式, 与闸门 physics_constraints ①..⑤ 一一对应; 数值取真源, 类里不抄数字)
    #   ① 位移←速度:  s = ∫v dt   ,  ‖v‖·dt ≤ s_step          (单拍位移封顶, 段累计 ≤ s_max)
    #   ② 速度←加速度: v = ∫a dt   ,  ‖Δv‖ ≤ a_max·dt, a_max = F_max/m   (牛顿二定律)
    #   ③ 加加速度:    a = ∫j dt   ,  ‖Δa‖ ≤ jerk_max·dt       (伺服带宽有限, 不许阶跃)
    #   ④ 动量/质量率: p = m·v     ,  ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取建立/释放时质量在变)
    #   ⑤ 惯量:        F = m·a     ⇒  a = F/m
    #   带本段真实数字的方程: SK05Lift.show_phys()
    phys_note = '已夹持 m=1.35kg(夹爪1.2+件0.15) · F=5N · 段行程 s_max=0.16(STAGE_LIFT) ⇒ ①+②绑'


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

    # ⚖ 物理模型调用 (真语句, 不是注释): 本段每拍动作 → 五式闸
    #   老倪 2026-10-15:「原子技能, 哪里是调用物理模型的?」⇒ 类体里就能看到这一条;
    #   实现落在基类 AtomicSkill.apply_physics → physics_constraints.InertiaLimiter.limit。
    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """⚖ 本段动作过物理模型 (①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移)。

        🔴 2026-10-31 老倪「这个 clamp 也没有断点啊」⇒ 拆成两步写, 为的是断点:
           在 `return r` 那行打红点, 调试器里直接看得到 r 的全部字段
           (u / v_req / err / why / kin_why / dyn_why / phys), 而不是只剩一个 return 表达式。
           行为逐位不变 (同一调用、同一返回)。
        """
        r = self.apply_physics(u, dt=dt, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt)
        return r

    # ⚖ 物理模型 (五式, 与闸门 physics_constraints ①..⑤ 一一对应; 数值取真源, 类里不抄数字)
    #   ① 位移←速度:  s = ∫v dt   ,  ‖v‖·dt ≤ s_step          (单拍位移封顶, 段累计 ≤ s_max)
    #   ② 速度←加速度: v = ∫a dt   ,  ‖Δv‖ ≤ a_max·dt, a_max = F_max/m   (牛顿二定律)
    #   ③ 加加速度:    a = ∫j dt   ,  ‖Δa‖ ≤ jerk_max·dt       (伺服带宽有限, 不许阶跃)
    #   ④ 动量/质量率: p = m·v     ,  ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取建立/释放时质量在变)
    #   ⑤ 惯量:        F = m·a     ⇒  a = F/m
    #   带本段真实数字的方程: SK06Transfer.show_phys()
    phys_note = '已夹持 m=1.35kg · F=5N · 空中快移 v=0.35 ⇒ ①+jerk(15.0)绑; 段行程用 POS_LIMIT 包络 0.6(工位跳度待现场标)'


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

    # ⚖ 物理模型调用 (真语句, 不是注释): 本段每拍动作 → 五式闸
    #   老倪 2026-10-15:「原子技能, 哪里是调用物理模型的?」⇒ 类体里就能看到这一条;
    #   实现落在基类 AtomicSkill.apply_physics → physics_constraints.InertiaLimiter.limit。
    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """⚖ 本段动作过物理模型 (①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移)。

        🔴 2026-10-31 老倪「这个 clamp 也没有断点啊」⇒ 拆成两步写, 为的是断点:
           在 `return r` 那行打红点, 调试器里直接看得到 r 的全部字段
           (u / v_req / err / why / kin_why / dyn_why / phys), 而不是只剩一个 return 表达式。
           行为逐位不变 (同一调用、同一返回)。
        """
        r = self.apply_physics(u, dt=dt, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt)
        return r

    # ⚖ 物理模型 (五式, 与闸门 physics_constraints ①..⑤ 一一对应; 数值取真源, 类里不抄数字)
    #   ① 位移←速度:  s = ∫v dt   ,  ‖v‖·dt ≤ s_step          (单拍位移封顶, 段累计 ≤ s_max)
    #   ② 速度←加速度: v = ∫a dt   ,  ‖Δv‖ ≤ a_max·dt, a_max = F_max/m   (牛顿二定律)
    #   ③ 加加速度:    a = ∫j dt   ,  ‖Δa‖ ≤ jerk_max·dt       (伺服带宽有限, 不许阶跃)
    #   ④ 动量/质量率: p = m·v     ,  ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取建立/释放时质量在变)
    #   ⑤ 惯量:        F = m·a     ⇒  a = F/m
    #   带本段真实数字的方程: SK07Insert.show_phys()
    phys_note = '已夹持 m=1.35kg · **F=2N 金手指保护 ⇒ a_max 只有 1.48m/s²(②最紧)** · 段行程 0.02≈孔深 ⇒ ②+⑤ 绑'


class SK07Place(AtomicSkill):
    """⑦ 放入 (摆盘链 mode=tray) — 把光模块下放进 tray 槽位并释放 (替代插拔链的 SK07Insert)

    摆盘 = 取放, 不是插入: 无孔口/无接触推入, 终点 = 件底贴槽底面 (内底顶面 + 件半高)。
    与 SK07Insert 同编号同"决策层选定第 7 段"语义 —— **由任务配置选哪一支** (配置改变功能)。
    """
    code = "SK07"
    # 🎯 目标: 点位库的摆放点 (真机点位上下文; 仿真无点位库时返回 None)
    TARGET = {"ref": "point", "off_key": None}
    stage = "放入"          # 摆盘链里对应状态机的「放下」段 (ActionModulator.PLACE_IDX)
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

    # ⚖ 物理模型调用 (真语句, 不是注释): 本段每拍动作 → 五式闸
    #   老倪 2026-10-15:「原子技能, 哪里是调用物理模型的?」⇒ 类体里就能看到这一条;
    #   实现落在基类 AtomicSkill.apply_physics → physics_constraints.InertiaLimiter.limit。
    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """⚖ 本段动作过物理模型 (①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移)。

        🔴 2026-10-31 老倪「这个 clamp 也没有断点啊」⇒ 拆成两步写, 为的是断点:
           在 `return r` 那行打红点, 调试器里直接看得到 r 的全部字段
           (u / v_req / err / why / kin_why / dyn_why / phys), 而不是只剩一个 return 表达式。
           行为逐位不变 (同一调用、同一返回)。
        """
        r = self.apply_physics(u, dt=dt, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt)
        return r

    # ⚖ 物理模型 (五式, 与闸门 physics_constraints ①..⑤ 一一对应; 数值取真源, 类里不抄数字)
    #   ① 位移←速度:  s = ∫v dt   ,  ‖v‖·dt ≤ s_step          (单拍位移封顶, 段累计 ≤ s_max)
    #   ② 速度←加速度: v = ∫a dt   ,  ‖Δv‖ ≤ a_max·dt, a_max = F_max/m   (牛顿二定律)
    #   ③ 加加速度:    a = ∫j dt   ,  ‖Δa‖ ≤ jerk_max·dt       (伺服带宽有限, 不许阶跃)
    #   ④ 动量/质量率: p = m·v     ,  ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取建立/释放时质量在变)
    #   ⑤ 惯量:        F = m·a     ⇒  a = F/m
    #   带本段真实数字的方程: SK07Place.show_phys()
    phys_note = '已夹持 m=1.35kg · F=2N 不压伤 · **开爪释放 dm/dt=0.5 ⇒ ④ 绑定** · 段行程 0.06(放下行)'


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

    # ⚖ 物理模型调用 (真语句, 不是注释): 本段每拍动作 → 五式闸
    #   老倪 2026-10-15:「原子技能, 哪里是调用物理模型的?」⇒ 类体里就能看到这一条;
    #   实现落在基类 AtomicSkill.apply_physics → physics_constraints.InertiaLimiter.limit。
    def clamp(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None):
        """⚖ 本段动作过物理模型 (①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移)。

        🔴 2026-10-31 老倪「这个 clamp 也没有断点啊」⇒ 拆成两步写, 为的是断点:
           在 `return r` 那行打红点, 调试器里直接看得到 r 的全部字段
           (u / v_req / err / why / kin_why / dyn_why / phys), 而不是只剩一个 return 表达式。
           行为逐位不变 (同一调用、同一返回)。
        """
        r = self.apply_physics(u, dt=dt, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt)
        return r

    # ⚖ 物理模型 (五式, 与闸门 physics_constraints ①..⑤ 一一对应; 数值取真源, 类里不抄数字)
    #   ① 位移←速度:  s = ∫v dt   ,  ‖v‖·dt ≤ s_step          (单拍位移封顶, 段累计 ≤ s_max)
    #   ② 速度←加速度: v = ∫a dt   ,  ‖Δv‖ ≤ a_max·dt, a_max = F_max/m   (牛顿二定律)
    #   ③ 加加速度:    a = ∫j dt   ,  ‖Δa‖ ≤ jerk_max·dt       (伺服带宽有限, 不许阶跃)
    #   ④ 动量/质量率: p = m·v     ,  ‖m·Δv + v·Δm‖ ≤ F_max·dt (抓取建立/释放时质量在变)
    #   ⑤ 惯量:        F = m·a     ⇒  a = F/m
    #   带本段真实数字的方程: SK08Complete.show_phys()
    phys_note = '已夹持 m=1.35kg · F=2N 保持 · v=0.02 ⇒ ①最紧; 段行程 0.002(终点判据)'


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
SKILL_BY_CODE = {cls.code: cls for cls in SKILLS}
SKILL_BY_CODE_TRAY = {cls.code: cls for cls in SKILLS_TRAY}


def skills_for_mode(mode="insert"):
    """按任务模式取技能链: tray(摆盘) → SK07 是「放入」; 其它 → SK07 是「插入」"""
    return list(SKILLS_TRAY if str(mode).lower() == "tray" else SKILLS)


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