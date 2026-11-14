#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scheduler_fsm.py — 工厂调度状态机 (Dispatch FSM), 放在「🧭 动作调制器 sssched」里。

为什么状态机住在这里 (老倪 2026-11-14「状态机放在动作调制节点比较合理, 对应小脑基底节的状态,
工厂调度」): 调制器本来就同时握着**三样只有一处能有的东西** —— ①当前阶段(状态) ②各层提案(L2/L3/L4)
③物理约束闸。状态机挪到别处, 就会出现"状态在这一处、闸在那一处"的双真源; 基底节的功能正是
"按状态选通路 + 一票否决", 与这里的角色一一对应。程序入口(ss_canvas_loop)只是**节拍器**:
每拍把观测灌给本状态机 → 拿到 (状态, 该状态的策略) → 交给调制器融合/限速/过闸。

三件事由本文件唯一收口:
  1. STATES      状态集合 (与 ActionModulator.STAGES 同名同序, 兼容老调用)
  2. POLICY      每个状态的调度策略: 层配比 w_L3/w_L4/w_L2 · 速度上限/下限 · 力否决阈值 · 技能
  3. GUARDS      状态转移表: (事件, 守卫) → 目标状态; 守卫一律用**可证据化的观测量**
                 (水平距离/接触概率/夹持力/抬升高度/插入深度/落位), 不用"感觉"

失败分支(与现场一致):
  · 夹持丢失 (抬起~回程, 连续 5 帧夹持力<0.05 且件已落回抓握高度) → 回退「接近」重抓
  · 残差连续否决 → 状态*不变*但由调制器返回零动作 (状态机不自己动, 避免"状态乱跳掩盖故障")
  · 力超阈值 → 该状态下 L3 提案被 veto (策略里的 f_veto), 状态不变
"""
from __future__ import annotations

import os
import time

# ── 1. 状态集合 (与 ActionModulator.STAGES 同名同序) ──────────────────────────
STATES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入",
          "拔出", "AOI转移", "AOI检测", "回程", "放下", "完成"]
IDX = {s: i for i, s in enumerate(STATES)}
GRASP_IDX = 3
PLACE_IDX = 11                  # 摆盘链的「放入」复用「放下」
DONE_IDX = len(STATES) - 1
RETREAT_LO, RETREAT_HI = GRASP_IDX + 1, len(STATES) - 3

# ── 2. 每状态调度策略 (层权重和为 1.0; 缺层时由仲裁器按在场层归一化) ────────────
def _p(w3, w4, w2, v_cap, v_min, f_veto):
    return {"w_L3": w3, "w_L4": w4, "w_L2": w2,
            "v_cap": v_cap, "v_min": v_min, "f_veto_n": f_veto}

POLICY = {
    # 自由段: 大模型指方向为主, 流形引擎给曲率, 基础技能兜底 → 快移
    "接近":    _p(0.50, 0.32, 0.18, 0.35, 0.12, 30.0),
    "抬起":    _p(0.50, 0.32, 0.18, 0.30, 0.10, 30.0),
    "转移":    _p(0.55, 0.30, 0.15, 0.35, 0.12, 30.0),
    "回程":    _p(0.55, 0.30, 0.15, 0.30, 0.12, 30.0),
    "AOI转移": _p(0.55, 0.30, 0.15, 0.30, 0.12, 30.0),
    # 精段: 几何精度靠流形引擎, 大模型退居提示 → 慢而准
    "对位":    _p(0.25, 0.55, 0.20, 0.12, 0.04, 25.0),
    "下降":    _p(0.20, 0.58, 0.22, 0.09, 0.04, 25.0),
    "AOI检测": _p(0.15, 0.60, 0.25, 0.05, 0.02, 20.0),
    # 接触段: 力控为主, 大模型只留最小权重(不许它"冲")
    "抓取":    _p(0.10, 0.60, 0.30, 0.04, 0.02, 40.0),
    "插入":    _p(0.10, 0.60, 0.30, 0.085, 0.03, 40.0),
    "拔出":    _p(0.10, 0.60, 0.30, 0.06, 0.02, 40.0),
    "放下":    _p(0.10, 0.60, 0.30, 0.06, 0.02, 25.0),
    # 收尾
    "完成":    _p(0.00, 0.60, 0.40, 0.02, 0.00, 20.0),
}

assert abs(sum(POLICY["接近"][k] for k in ("w_L3", "w_L4", "w_L2")) - 1.0) < 1e-9


def policy_for(state: str) -> dict:
    return dict(POLICY.get(state, POLICY["完成"]))


# ── 3. 转移表 ────────────────────────────────────────────────────────────────
def _registry() -> dict:
    """进程级注册表 —— 存在 builtins 上。

    为什么不用本模块的全局变量: 端侧/引擎按**文件路径**加载 (importlib.spec_from_file_location)
    cognition 时, 同一个 scheduler_fsm.py 会被加载成**两个模块对象**, 各自的全局变量互不相通 ⇒
    入口拿到 A 实例、引擎推进的是 B 实例 (实测: 引擎已经把状态推到「抬起」, 入口还停在「接近」,
    所以终端一行 🔀 都不打)。挂在 builtins 上才能保证"一个进程只有一个状态机"。
    """
    import builtins
    r = getattr(builtins, "_ZMAX_FSM_REG", None)
    if r is None:
        r = {}
        builtins._ZMAX_FSM_REG = r
    return r


def get_fsm(mode: str = "insert", **kw) -> "DispatchFSM":
    """进程内单例 —— 为什么必须单例 (2026-11-14 实测):

    `safety_limit_impl` 每拍都是 `cog.ActionModulator()` **新建**一个调制器 (实测第 252 行),
    如果状态机跟着调制器 new, 那 stage_idx 每拍回到 0、history 每拍清空 ⇒ 状态机永远不会推进
    (SS_FSM.json 只出现过 接近→对位 就再不动, 就是这个原因)。
    状态是**进程级事实**, 必须与"谁构造调制器"解耦 ⇒ 这里用模块级单例, 调制器只是借用。
    """
    reg = _registry()
    key = str(mode)
    f = reg.get(key)
    if f is None:
        f = DispatchFSM(mode=mode, **kw) if kw else DispatchFSM(mode=mode)
        reg[key] = f
    return f


class DispatchFSM:
    """工厂调度状态机: 只吃**证据**, 不吃"应该到哪了"。每拍 step(obs) 推进一格。"""

    def __init__(self, mode: str = "insert", confirm_n: int = 2,
                 align_xy_coarse: float = 0.05, align_xy_fine: float = 0.004,
                 contact_th: float = 0.6, grasp_th: float = 0.5,
                 lift_h: float = 0.02, align_th: float = 0.02,
                 insert_depth: float = 0.012, insert_hover: float = 0.02,
                 insert_z_tol: float = 0.012, pull_out_m: float = 0.010,
                 pull_clear_h: float = 0.02):
        self.mode = mode
        self.state_idx = 0
        self.confirm_n = int(confirm_n)
        self.align_xy_coarse = align_xy_coarse
        self.align_xy_fine = align_xy_fine
        self.contact_th = contact_th
        self.grasp_th = grasp_th
        self.lift_h = lift_h
        self.align_th = align_th
        self.insert_depth = insert_depth
        self.insert_hover = insert_hover
        self.insert_z_tol = insert_z_tol
        self.pull_out_m = pull_out_m
        self.pull_clear_h = pull_clear_h
        self._pend = {}
        self._grasp_lost = 0
        self.t_enter = time.time()
        self.history = [(STATES[0], "init")]
        self.n_trans = 0
        self.n_cycle = 0                  # 周期计数(每拍 +1) —— 断点锚的伴生观测量
        self.last_reason = ""
        self._dump()                      # 初始状态也落盘: 页面第一眼就能看到"调度器在哪个状态"

    # -- 只读视图 --
    @property
    def state(self) -> str:
        return STATES[self.state_idx]

    def policy(self) -> dict:
        return policy_for(self.state)

    def snapshot(self) -> dict:
        d = policy_for(self.state)
        d.update({"state": self.state, "idx": self.state_idx, "mode": self.mode,
                  "since_s": round(time.time() - self.t_enter, 2),
                  "n_trans": self.n_trans, "n_cycle": self.n_cycle,
                  "last_reason": self.last_reason,
                  "history": self.history[-6:]})
        return d

    # -- 推进 --
    def _go(self, idx: int, reason: str):
        if idx == self.state_idx:
            return False
        self.state_idx = int(idx)
        self.t_enter = time.time()
        self.n_trans += 1
        self.last_reason = reason
        self.history.append((STATES[self.state_idx], reason))
        self._pend.clear()
        self._dump()
        return True

    # ── 取证: 每次状态切换落一个小 JSON, 让页面/终端都能看到"调度器现在在哪个状态" ──
    FSM_JSON = os.environ.get("ZMAX_FSM_JSON") or os.path.expanduser("~/zmax/zmax_data/ss_live/ss_fsm.json")

    def _dump(self):
        try:
            import json as _j
            p = self.FSM_JSON
            os.makedirs(os.path.dirname(p), exist_ok=True)
            _j.dump(self.snapshot(), open(p + ".tmp", "w"), ensure_ascii=False, indent=1)
            os.replace(p + ".tmp", p)
        except Exception:                                                    # noqa: BLE001
            pass

    def step(self, obs: dict) -> str:
        """obs 键(全部可选, 缺失=没证据, 不猜): d_xy/contact_p/gripper/lifted/dist_h/
        peg_z/hole_z/depth/placed/grasp_force/at_grasp_pose。返回当前状态名。"""
        self.n_cycle = self.n_cycle + 1   # ⛳ 周期断点锚: 每一个调度周期都会执行到这一行, 断点打这里(F9)
        # 自停锚(不靠手打断点): 环境变量 ZMAX_STOP_AT_SCHED=1 或存在 /tmp/zmax_stop_at_sched 就当场停住
        #   有调试器 → debugpy.breakpoint() (VSCode 里能看到完整栈/变量)
        #   没调试器 → pdb.set_trace() (终端里停)
        if os.environ.get("ZMAX_STOP_AT_SCHED") == "1" or os.path.exists("/tmp/zmax_stop_at_sched"):
            _held = False
            try:
                import debugpy
                # 只有真有客户端连着(你的 F5 调试会话)才走 debugpy, 否则 breakpoint() 是静默 no-op
                if getattr(debugpy, "is_client_connected", lambda: False)():
                    debugpy.breakpoint()
                    _held = True
            except Exception:                                            # noqa: BLE001
                _held = False
            if not _held:
                import pdb
                pdb.set_trace()
        st = self.state
        g = obs.get

        # ① 夹持丢失回退 (抬起~回程; 「放下」除外 — 放件时开爪属正常工艺)
        if RETREAT_LO <= self.state_idx <= RETREAT_HI and g("grasp_force") is not None:
            self._grasp_lost = self._grasp_lost + 1 if float(g("grasp_force")) < 0.05 else 0
            _fell = (g("peg_z") is not None and g("peg_z_grasp") is not None
                     and float(g("peg_z")) < float(g("peg_z_grasp")) + 0.02)
            if self._grasp_lost >= 5 and _fell:
                self._grasp_lost = 0
                self._go(0, "⚠️ 夹持丢失且件落回台面(连续5帧夹持力<0.05) → 回退重抓")
                return self.state

        dxy = g("d_xy") if g("d_xy") is not None else g("dist_h")
        target, reason = None, ""

        if st == "接近" and dxy is not None and dxy < self.align_xy_coarse:
            target, reason = 1, f"粗到位 水平距离 {dxy:.4f} < {self.align_xy_coarse}"
        elif st == "对位" and dxy is not None and dxy < self.align_xy_fine:
            target, reason = 2, f"精对位 {dxy:.4f} < {self.align_xy_fine}"
        elif st == "下降" and ((g("contact_p") is not None and g("contact_p") > self.contact_th)
                              or g("at_grasp_pose")):
            target = 3
            reason = (f"触到工件 接触概率 {float(g('contact_p')):.2f} > {self.contact_th}"
                      if (g("contact_p") is not None and g("contact_p") > self.contact_th)
                      else "到达抓握位姿(几何证据)")
        elif st == "抓取" and g("gripper") is not None and float(g("gripper")) > self.grasp_th:
            target, reason = 4, f"夹持建立 gripper={float(g('gripper')):.2f}"
        elif st == "抬起" and g("lifted") is not None and float(g("lifted")) > self.lift_h:
            target, reason = 5, f"已提起 {float(g('lifted')):.4f}m > {self.lift_h}m"
        elif st == "转移" and self.mode == "tray" and g("dist_h") is not None \
                and float(g("dist_h")) < self.align_th:
            target, reason = PLACE_IDX, f"对准槽位 dist_h={float(g('dist_h')):.4f} → 放入"
        elif st == "转移" and g("dist_h") is not None and float(g("dist_h")) < self.align_th and (
                g("hole_z") is None or (g("peg_z") is not None and
                                        abs(float(g("peg_z")) - float(g("hole_z")) - self.insert_hover)
                                        <= self.insert_z_tol)):
            target, reason = 6, f"对准孔口 dist_h={float(g('dist_h')):.4f}"
        elif st == "插入" and g("depth") is not None and float(g("depth")) < self.insert_depth:
            target = IDX["拔出"] if self.mode == "full" else DONE_IDX
            reason = f"插入深度达标 depth={float(g('depth')):.4f}" + ("" if self.mode != "full" else " → 拔出")
        elif st == "拔出" and None not in (g("depth"), g("peg_z"), g("hole_z")):
            if float(g("depth")) > self.pull_out_m and (float(g("peg_z")) - float(g("hole_z"))) > self.pull_clear_h:
                target, reason = IDX["AOI转移"], f"拔出完成 depth={float(g('depth')):.4f}"
        elif st == "放下" and g("placed"):
            target, reason = DONE_IDX, "放回初始位完成(件触台 → 开爪)"

        if target is None:
            self._pend.clear()          # 证据不成立 → 待确认清零 (必须连续 confirm_n 拍)
            return self.state

        self._pend[target] = self._pend.get(target, 0) + 1
        if self._pend[target] >= self.confirm_n:
            self._go(target, reason)
        return self.state
