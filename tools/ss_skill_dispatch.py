#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_skill_dispatch.py — 🧩 技能派发**常驻循环服务**: 块 → 每个技能取"最新那一拍" → 实时执行。

老倪 2026-10-15: 「最后从安全执行器输出后, 给到每个技能, 由肌肉记忆的每个技能 接近 对位 下降等,
选取最新的动作执行, 实时执行。最后的技能, 应该通过一个循环服务, 快速流转到具体的技能。」

做法 (60Hz 默认, 纯读块 + 写共享内存, 不下发任何真机指令):
  ① 读块唯一依据 zmax_data/ss_live/chunk_latest.json (常驻回路每周期写; 含 u[H,4] = 加权+调制+安全后的序列)
  ② 每个技能 (八阶段: 接近/对位/下降/抓取/抬起/转移/插入/完成) 认领块里属于自己的那一拍
     (块内第 i 拍 → 阶段 stage_idx+i); 没轮到的技能保持**上一次最新**的那一拍 (肌肉记忆: 用最近拿到的)
  ③ 队内推进: 按经过时间把每技能的"当前拍"往前推 (块 dt=0.1s), 推到底就停在最后一拍 (等下一块)
     ⇒ 技能拿到的是**最新可用**动作, 而不是一块里永远第一步
  ④ 落两条唯一依据:
     /dev/shm/zmax_ss_engine/skill_<idx>_<name>.json   每个技能的当前动作 (技能侧直接读, 微秒级)
     zmax_data/ss_live/skill_latest.json               平铺数值 (信号分析直接画: 每技能速度 + 派发帧龄/次数)
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "src") not in __import__("sys").path:
    __import__("sys").path.insert(0, os.path.join(ROOT, "src"))
from lerobot.policies.left_right.state_space.physics_constraints import (InertiaLimiter,   # noqa: E402
                                                                       limits_for)
# ⚖ 技能号 ↔ 阶段: 唯一依据 = 技能库的类 (code/stage 类属性), 不在这里手写编号
from lerobot.policies.left_right.state_space.skills.atomic_skills import (  # noqa: E402
    SKILLS, SKILLS_TRAY, bind_limiter, skill_for)
CODE_BY_STAGE = {}
for _c in list(SKILLS) + list(SKILLS_TRAY):
    CODE_BY_STAGE.setdefault(_c.stage, _c.code)          # SK07 插拔链=插入 / 摆盘链=放入 (同号两支)
LIVE = os.environ.get("ZMAX_LIVE_DIR") or os.path.join(ROOT, "zmax_data", "ss_live")
SHM = os.environ.get("ZMAX_SHM_DIR", "/dev/shm/zmax_ss_engine")
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
DT = 0.1                      # 块内每拍时长 (与回路 10Hz 同口径)
POSE_STALE_S = float(os.environ.get("ZMAX_SKILL_POSE_STALE_S", "5.0"))   # 位姿停更阈值 (= 发布守护同口径)


_SCENE_PREV = {"t": None}
_LAST_POSE = {"v": None, "wall": 0.0}
POSE_HOLD_S = 3.0        # 场景快照短暂停更 (3D 暂停/掉一拍) 时沿用上一次真值, 超过就老实回 -1


def _read_scene_pose():
    """回落位姿: 3D 场景真值 (trace_live.json 末端_x/y/z, m → mm)。

    为什么需要 (老倪 2026-10-17: 「3D 场景光模块都抓起来了、插拔也成功了, 为什么抓取的 x 位置、
    接近的 x 位置一直不变?」): tap 位姿 state_*.jsonl 已停更 (实测最后一份 10-16 09:11, 30+ 小时),
    _read_pose 按"不许拿旧位姿当现在"的口径一律填 -1.0 ⇒ 8 个技能的 x/y/z 全是常量 -1。
    而 3D 面板同一时刻用的是 trace_live.json 的真值末端 (活, 10Hz) —— 用同一份数据回落,
    界面上"场景里看到的位姿"与"信号分析里的技能位姿"就是同一个数。

    红线: 只在**文件新鲜 + 场景时钟在推进**时才回落; 冻结快照一律不用 (照样返回 None → -1.0)。
    """
    import json as _json
    p = os.path.join(LIVE, "trace_live.json")
    try:
        st = os.stat(p)
        age = time.time() - st.st_mtime
        if age > 2.0:
            return None
        with open(p, encoding="utf-8") as fh:
            d = _json.load(fh)
    except Exception:                                                             # noqa: BLE001
        return None
    ex, ey, ez = d.get("末端_x"), d.get("末端_y"), d.get("末端_z")
    if ex is None and isinstance(d.get("末端"), (list, tuple)) and len(d["末端"]) >= 3:
        ex, ey, ez = d["末端"][0], d["末端"][1], d["末端"][2]
    if not all(isinstance(v, (int, float)) for v in (ex, ey, ez)):
        return None
    tsec = d.get("时间_s")
    if _SCENE_PREV["t"] is not None and tsec == _SCENE_PREV["t"] and age > 0.5:
        return None                        # 场景时钟不走了 ⇒ 冻结快照, 不能当现位姿
    _SCENE_PREV["t"] = tsec
    # ⚠️ 3D 场景出口只有位置 (ss_dreamview 3757 行: 姿态不在这条出口) ⇒ a/b/c 不下发假值, 记 -1,
    #   由质量告警标「姿态不可观测 (源停更)」; 真姿态要等 tap/Orin tcp_pose 恢复。
    out = {"x": round(float(ex) * 1000.0, 3), "y": round(float(ey) * 1000.0, 3),
           "z": round(float(ez) * 1000.0, 3), "angle": -1.0,
           "a": -1.0, "b": -1.0, "c": -1.0,
           "pose_age_s": round(age, 3), "src": "trace_live(3D 场景真值·m→mm)"}
    _LAST_POSE.update(v=dict(out), wall=time.time())
    return out


def _held_pose():
    """上一次有效位姿 (≤POSE_HOLD_S) —— 快照停一两拍时不至于把 x 抖成 -1。"""
    v = _LAST_POSE.get("v")
    if v and (time.time() - float(_LAST_POSE.get("wall") or 0)) <= POSE_HOLD_S:
        out = dict(v)
        out["pose_age_s"] = round(time.time() - float(_LAST_POSE["wall"]) + float(v.get("pose_age_s") or 0), 3)
        out["src"] = v.get("src", "") + "·保持"
        return out
    return None


def _read_pose():
    """真机 tap 位姿 (x/y/z mm + 姿态角 deg) —— 尾读最新 state_*.jsonl 的**最后一行** (不整文件读入)。

    口径与发布守护 tools/dds/ss_daemon.py::read_state 同源 (同一个 tap 文件、同一个新鲜度阈值):
      帧龄 > POSE_STALE_S ⇒ 位姿停更 ⇒ 一律 -1 (老倪: 不许拿旧位姿当现在)。
    """
    import glob as _g
    c = _g.glob(os.path.join(LIVE, "state_*.jsonl"))
    if not c:
        _sc0 = _read_scene_pose() or _held_pose()
        if _sc0 is not None:
            return _sc0
        return {"x": -1.0, "y": -1.0, "z": -1.0, "angle": -1.0, "pose_age_s": -1.0}
    p = max(c, key=os.path.getmtime)
    age = time.time() - os.path.getmtime(p)
    try:
        with open(p, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 262144))
            tail = fh.read().decode("utf-8", "ignore").strip().splitlines()
        d = json.loads(tail[-1]) if tail else {}
    except Exception:                                                             # noqa: BLE001
        return {"x": -1.0, "y": -1.0, "z": -1.0, "angle": -1.0, "pose_age_s": age}
    if age > POSE_STALE_S:
        _sc = _read_scene_pose() or _held_pose()
        if _sc is not None:
            return _sc                     # tap 停更 ⇒ 用 3D 场景同一拍真值 (标注 src)
        return {"x": -1.0, "y": -1.0, "z": -1.0, "angle": -1.0, "pose_age_s": age, "stale": 1}
    tcp = [float(v) for v in (d.get("tcp") or [])]
    q = [float(v) for v in (d.get("tcp_quat") or [])]
    _rpy = d.get("tcp_rpy") or d.get("rpy") or []
    ang = -1.0
    if len(q) >= 4:
        import math as _m
        w = max(-1.0, min(1.0, abs(q[3])))
        ang = round(2.0 * _m.degrees(_m.acos(w)), 3)
    import math as _m2
    _a = _b = _c = -1.0
    if len(_rpy) >= 3:                       # tap 直接给欧拉角 (deg)
        _a, _b, _c = (float(_rpy[0]), float(_rpy[1]), float(_rpy[2]))
    elif len(q) >= 4:                        # 四元数 → ZYX 欧拉角 (deg)
        _w, _x, _y, _z = (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
        _a = _m2.degrees(_m2.atan2(2 * (_w * _x + _y * _z), 1 - 2 * (_x * _x + _y * _y)))
        _b = _m2.degrees(_m2.asin(max(-1.0, min(1.0, 2 * (_w * _y - _z * _x)))))
        _c = _m2.degrees(_m2.atan2(2 * (_w * _z + _x * _y), 1 - 2 * (_y * _y + _z * _z)))
    return {"x": (tcp[0] if len(tcp) > 0 else -1.0), "y": (tcp[1] if len(tcp) > 1 else -1.0),
            "z": (tcp[2] if len(tcp) > 2 else -1.0), "angle": ang,
            "a": _a, "b": _b, "c": _c, "pose_age_s": round(age, 3)}


def _atomic_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 🐛 2026-10-16 实测 (快照判据红过一条): tmp 名固定成 `path + ".tmp"` 在**多写者**下必炸 ——
    #   引擎 ticker 与本派发器同时写 skill_phys.json 时, 一方 os.replace 已把 tmp 搬走,
    #   另一方 rename 就报 FileNotFoundError: '...skill_phys.json.tmp' (tmp 不存在), 看着像"文件丢了"。
    #   修法: tmp 名带 pid + 随机后缀 (仍同目录 ⇒ 同文件系统, os.replace 依旧原子), 失败路径清残件。
    tmp = "%s.tmp.%d.%s" % (path, os.getpid(), uuid.uuid4().hex[:8])
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:                                                # noqa: BLE001
                pass


def _norm(a):
    try:
        return round(float(sum(float(x) * float(x) for x in a[:3]) ** 0.5), 6)
    except Exception:                                                      # noqa: BLE001
        return -1.0


class Dispatcher:
    def __init__(self, hz: float = 60.0):
        self.hz = float(hz)
        self.n = 0
        self.reset_n = 0
        self.skill_n = {s: 0 for s in STAGES}
        self.cur = {}           # 技能 → {"action": [...], "step": i, "ts": 拿到时刻, "stage": 块阶段}
        # ⚖ 2026-10-15 老倪「每个技能都清楚地知道自己动作的惯性」: 每个技能各自记上一拍的**实际下发**速度/加速度,
        #   物理闸要拿它算 Δv/Δa (惯性是"下一拍相对上一拍"的关系, 不是绝对量)。
        self.lim = InertiaLimiter(dt=DT)
        # ⚖ 老倪 2026-10-15「原子技能, 哪里是调用物理模型的?怎么保证每次都有物理约束」:
        #   闸实例**绑给技能调用口** (bind_limiter) ⇒ 技能类里的 clamp() 与派发链/信号分析共用同一实例,
        #   段累计行程与削因计数才不会两处各记一半; 计数见下 (判据用它证「拍数 == 过闸次数」)。
        bind_limiter(self.lim)
        # 🧭 2026-10-31 老倪「不应该有个调度节点负责调用某一个技能么」→ 单射调度:
        #   每拍**只有一个在职技能** (= 块当前阶段), 只有它过物理闸; 其余 7 个保持上一次认领的那一拍
        #   (肌肉记忆留参考), 在职=0 且**不调 clamp**。改后判据: 在职数=1 · 闸拍数 480/s→60/s ·
        #   在职技能的动作/偏差与改前逐位一致 (不调 = 不改数, 只去掉旧值空转).
        self.active = None          # 当前在职技能 (段名)
        self.n_switch = 0           # 换技能次数 (判据: 8 段轮一遍才切换)
        self._last_p = {}           # 段 → 上一次在职时过闸的结果 (不在职时原样沿用, 不重算)
        self._sk_cache = {}
        self.n_gate_skill = 0        # 走"技能对象自己的调用口"的拍数 (本段有技能类)
        self.n_gate_stage = 0        # 走"同段唯一依据闸"的拍数 (本段没有技能类: 拔出/AOI转移/AOI检测/回程)
        self.last_v = {s_: np.zeros(3) for s_ in STAGES}
        self.last_a = {s_: np.zeros(3) for s_ in STAGES}
        # ⚖ 加速度唯一依据: 块边界算一次并**保留到下一块** (老倪 2026-10-15「信号分析里要看到 a 加速度」)。
        #   为什么不能直接用 last_a: 它是 (本tick − 上一tick)/dt, 而块内同一步动作不变 ⇒ 只在换块那一拍
        #   出现一个 16ms 尖峰 (60Hz 里 1 拍), 信号分析按 ~50Hz 采样几乎永远采不到 ⇒ 现场看 a 恒为 0 (假信号)。
        #   改为: 换新块时算 ‖v_本块 − v_上一块‖ / Δt_块间 (mm/s²), 保留到下一块 ⇒ 稳定可读。
        self.a_blk = {}            # stage → 块间加速度 mm/s²
        self.v_blk = {}            # stage → 上一次换块时的速度 mm/s
        self.t_blk = {}            # stage → 上一次换块的时刻
        self.err_last = {"ts": 0.0, "err": {}, "big": {}, "big_stage": "", "err_norm": {}, "why": {}}
        self._chunk_ts = None
        os.makedirs(SHM, exist_ok=True)

    def _chunk(self):
        try:
            with open(os.path.join(LIVE, "chunk_latest.json"), encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:                                                  # noqa: BLE001
            return None

    def _skill(self, st):
        """按段名取技能**对象** (缓存) —— 段名→技能类的映射来自 atomic_skills 类属性, 不自己编号。"""
        if st not in self._sk_cache:
            _c = skill_for(st)
            self._sk_cache[st] = _c() if _c is not None else None
        return self._sk_cache[st]

    def _phys(self, st, action):
        """⚖ 进技能的 action 先过物理闸 (惯性/加速度/加加速度/动量率/位移) —— 过不去就削出偏差 error。

        两路**都过闸**, 没有第三条路:
          · 本段有技能类 ⇒ 走**技能对象自己的调用口** `skill.clamp()` (真调用写在 atomic_skills 类体里, 打开就能看到);
          · 本段没有技能类 (拔出/AOI转移/AOI检测/回程) ⇒ 走同段唯一依据闸 `self.lim.limit()` (如实登记, 不假装有技能)。
        """
        _sk = self._skill(st)
        if _sk is not None:
            r = _sk.clamp(action, dt=DT, v_prev=self.last_v.get(st), a_prev=self.last_a.get(st))
            self.n_gate_skill += 1
        else:
            r = self.lim.limit(st, action, v_prev=self.last_v.get(st), a_prev=self.last_a.get(st))
            self.n_gate_stage += 1
        v = np.asarray(r["u"], float)[:3]
        self.last_a[st] = (v - self.last_v.get(st, np.zeros(3))) / DT
        self.last_v[st] = v
        return r

    def cycle(self) -> dict:
        d = self._chunk()
        now = time.time()
        if d and float(d.get("ts") or 0) != self._chunk_ts and d.get("ok"):
            # 新块到了: 每个技能认领属于自己的一拍 (最后一步再前进)
            self._chunk_ts = float(d.get("ts") or 0)
            u = d.get("u") or []
            si = int(d.get("stage_idx") or 0)
            # 🧭 调度: 本块的当前阶段 = 唯一在职技能 (换段才切换, 其余技能不参与本拍)
            _act = STAGES[min(len(STAGES) - 1, max(0, si))]
            if _act != self.active:
                _prev = self.active
                self.active = _act
                self.n_switch += 1
                # 换技能: 清掉该技能上一拍的惯性/段行程 (不能拿别的段的 v/a 当自己的)
                try:
                    self.lim.reset_stage(_act)
                except Exception:                                          # noqa: BLE001
                    pass
                self.last_v[_act] = np.zeros(3)
                self.last_a[_act] = np.zeros(3)
                self._last_p.pop(_act, None)
                if _prev:
                    self.last_v[_prev] = np.zeros(3)
                    self.last_a[_prev] = np.zeros(3)
            got = []
            for i, a in enumerate(u):
                st = STAGES[min(len(STAGES) - 1, si + i)]
                self.cur[st] = {"action": [float(x) for x in a], "step": i,
                                "ts": now, "stage": str(d.get("stage") or ""), "block_ts": self._chunk_ts}
                self.skill_n[st] = self.skill_n.get(st, 0) + 1
                got.append(st)
                # ⚖ 块间加速度: 本块该技能速度 − 上一块该技能速度, 除以两块时间差 (保留到下一块)
                _v_now = float(np.linalg.norm(np.asarray(a, float)[:3])) * 1000.0
                _t_prev, _v_prev = self.t_blk.get(st), self.v_blk.get(st)
                if _t_prev is not None and _v_prev is not None:
                    self.a_blk[st] = abs(_v_now - float(_v_prev)) / max(1e-3, now - float(_t_prev))
                self.v_blk[st] = _v_now
                self.t_blk[st] = now
            self.reset_n += 1
            self.last_got = got
        # 队内推进: 按经过时间把每技能的当前拍往前推
        out = {}
        for st, c in list(self.cur.items()):
            adv = int((now - float(c["ts"])) / DT)
            step = min(c["step"] + max(0, adv), max(0, len(c["action"]) - 1) if False else c["step"])
            # 块内推进由"块序号"决定: 当前拍 = 认领时那一拍 + 经过拍数 (上限 7)
            step = min(c["step"] + max(0, adv), 7)
            _req = c["action"]
            _on = (st == self.active)
            if _on:
                _p = self._phys(st, _req)          # ← 只有在职技能过物理闸 (60Hz)
                self._last_p[st] = _p
            else:
                # 不在职: 原样沿用上一次在职时的闸后结果 —— 不重算、不改数、不计数
                _p = self._last_p.get(st)
                if _p is None:
                    _p = {"u": list(_req), "v_req": list(_req), "err": [0.0, 0.0, 0.0],
                          "err_norm": 0.0, "big": 0, "why": "未派发",
                          "kin_why": "未派发", "dyn_why": "未派发",
                          "phys": dict(limits_for(st) or {})}
            # ⚖ 老倪 2026-10-15: 信号分析要看到 x y z v a 等物理值 ⇒ 逐拍把这些量算出来落盘
            _a_n = float(self.a_blk.get(st, 0.0))                     # mm/s² (块间速度变化率, 保留到下一块)
            _s_mm = float(self.lim.travel.get(st, 0.0)) * 1000.0       # 本段累计行程 mm
            out[st] = {"stage": st, "action": _p["u"], "step": step, "ts": now,
                       "在职": 1 if _on else 0,
                       "age_s": round(now - float(c["ts"]), 4), "n": self.skill_n.get(st, 0),
                       "block_ts": c.get("block_ts"),
                       # ⚖ 物理闸口径: 请求值/可执行值/偏差/大偏差/哪条约束削的 + 该技能物理上限
                       "req": [round(float(x), 6) for x in _p["v_req"]],
                       "err": [round(float(x), 6) for x in _p["err"]], "err_norm": _p["err_norm"],
                       "big": (_p["big"] if _on else 0), "why": _p["why"], "phys": _p["phys"],
                       # 🧭/⚖ 2026-10-31 老倪「接近、对位要符合运动学约束; 物理约束改成动力学约束;
                       #   都要真正调用」—— 每拍分开记两条闸各自削了什么 (同一份 _p, 不另算)。
                       "kin_why": _p.get("kin_why", ""), "dyn_why": _p.get("dyn_why", ""),
                       "a_mms2": _a_n, "s_mm": _s_mm,
                       "skill": CODE_BY_STAGE.get(st, "")}
            _atomic_json(os.path.join(SHM, "skill_%d_%s.json" % (STAGES.index(st), st)), out[st])
        flat = {"ts": now, "n": self.n, "reset_n": self.reset_n,
                "派发帧龄_s": 0.0, "块帧龄_s": round(now - (self._chunk_ts or now), 3),
                # 🧭 单射调度 (2026-10-31): 在职技能唯一 / 切换计数 / 闸只对在职技能计时
                "在职技能": self.active or "", "在职数": (1 if self.active else 0),
                "切换次数": self.n_switch,
                # ⚖ 过闸计数 (可观察): 技能调用口拍数 + 无技能段拍数 + 闸门累计拍数与削因
                "过闸_技能拍": self.n_gate_skill, "过闸_段闸拍": self.n_gate_stage,
                "闸_拍数": int(getattr(self.lim, "n", 0)),
                "闸_削因": dict(getattr(self.lim, "n_cut", {}) or {}),
                "闸_不可行拍": int(sum((getattr(self.lim, "n_cut", {}) or {}).values())),
                # 🧭 运动学约束 / ⚖ 动力学约束 分闸计数 (老倪 2026-10-31「都要真正调用」):
                #   拍数必须都 == 闸_拍数 (没有一拍绕过任何一条闸); 削因各记各的。
                "运动学闸_拍": int(getattr(self.lim, "n_kin", 0)),
                "动力学闸_拍": int(getattr(self.lim, "n_dyn", 0)),
                "运动学削因": dict((getattr(self.lim, "kin", None) and self.lim.kin.n_cut) or {}),
                "动力学削因": dict((getattr(self.lim, "dyn", None) and self.lim.dyn.n_cut) or {}),
                "动力学_力超限拍": int(getattr(getattr(self.lim, "dyn", None), "n_force", 0)),
                "两条闸对账": ("一致" if int(getattr(self.lim, "n_kin", 0)) == int(getattr(self.lim, "n", -1))
                              == int(getattr(self.lim, "n_dyn", -2)) else "❌ 拍数不一致")}
        for st in STAGES:
            v = out.get(st)
            flat["%s_mps" % st] = (_norm(v["action"]) if v else -1.0)
            flat["%s_拍" % st] = (v["step"] if v else -1)
            flat["%s_请求_mps" % st] = (_norm(v["req"]) if v and v.get("req") else -1.0)   # 前馈/块给的请求值
            flat["%s_偏差_mps" % st] = (float(v.get("err_norm") or 0.0) if v else -1.0)     # ⚖ 物理不可行偏差
            flat["%s_可行" % st] = (0 if (v or {}).get("why") not in (None, "可行") else 1)  # 1=原样可行 0=被削
            # 🧭/⚖ 分闸判据: 1 = 该闸这一拍削了本段动作 (信号分析可直接画)
            flat["%s_运动学_削" % st] = (0 if (v or {}).get("kin_why") not in (None, "", "可行") else 1)
            flat["%s_动力学_削" % st] = (0 if (v or {}).get("dyn_why") not in (None, "", "可行") else 1)
        _atomic_json(os.path.join(LIVE, "skill_latest.json"), flat)
        # ⚖ 原子技能物理量唯一依据 (老倪 2026-10-15「所有原子技能都要有 topic 输出, 信号分析里看到 x y z v a」):
        #   每个技能一份 —— 数值/偏差/物理上限全部来自上面刚过的物理闸 (_p), 不另算一份;
        #   位置/姿态由 DDS 发布端从真机 tap 补 (这里不管位姿, 只管动作侧物理量)。
        _pose = _read_pose()          # 位姿: 该技能在职时当前末端位姿就是它这一拍的位置
        _ph = {"ts": now, "dt": DT, "pose": _pose, "src": "InertiaLimiter(按拍过闸) + config/calib/zmax_skill_physics.json",
               "skills": {}}
        for _st in STAGES:
            _v = out.get(_st)
            _code = CODE_BY_STAGE.get(_st, "")
            if not _code:
                continue
            # ⚖ 包络一律取 **limits_for 唯一依据** (在职/不在职都一样): 闸门导出到每拍结果里的 phys 是
            #   给报告看的**四舍五入摘要** (m 4位 / a_max 4位 / jerk_max 3位), 拿它当"物理模型"发布
            #   就等于把 4.166667 变成 4.1667 —— 信号分析里对不上唯一依据, 判据也过不了 1e-6。
            _q = dict(limits_for(_st) or {}) or dict((_v or {}).get("phys") or {})
            # ⚠️ 两个来源的键名不同 (闸门 phys: v_cap/F_max; limits_for: v/F/jerk/s) —— 统一成正名,
            #    否则会把包络写成一串 -1 而在信号分析里显示"没有物理模型"(同一类坑: dmdt vs dmdt_max)。
            def _pk(*names):
                for _n in names:
                    _x = _q.get(_n)
                    if isinstance(_x, (int, float)):
                        return float(_x)
                return -1.0
            _pv = isinstance(_pose.get("x"), (int, float)) and float(_pose.get("x")) != -1.0
            _ph["skills"][_code] = {
                "stage": _st, "在职": (1 if (_v and _v.get("在职")) else 0),
                "step": (_v["step"] if _v else -1),
                # 位置 = **当前 TCP 真值**, 与"这个技能此刻是否在派发(在职)"无关:
                # 老倪 2026-10-17「抓取的 x 位置一直不变」—— 原来 在职=0 就填 -1, 8 条里 5 条恒为 -1,
                # 看着像信号坏了。在职只决定 v/a/s/err 这些**本技能的过程量**有没有值。
                "x": (_pose["x"] if _pv else -1.0), "y": (_pose["y"] if _pv else -1.0),
                "z": (_pose["z"] if _pv else -1.0),
                "angle": (_pose["angle"] if (_pv and _pose.get("angle", -1.0) != -1.0) else -1.0),
                "pose_age_s": _pose["pose_age_s"],
                "a": (_pose.get("a", -1.0) if _pv else -1.0),
                "b": (_pose.get("b", -1.0) if _pv else -1.0),
                "c": (_pose.get("c", -1.0) if _pv else -1.0),
                "pose_src": _pose.get("src") or "tap(state_*.jsonl)",   # 位姿出处: 可审计, 不混用
                "v_mms": (float(np.linalg.norm(np.asarray(_v["action"], float)[:3])) * 1000.0
                          if _v else -1.0),                                    # 速度 mm/s (不四舍五入: 界面负责显示)
                "a_mms2": (_v["a_mms2"] if _v else -1.0),                      # 加速度 mm/s²
                "s_mm": (_v["s_mm"] if _v else -1.0),                          # 段累计行程 mm
                "err_mms": (float(_v["err_norm"]) * 1000.0 if _v else -1.0),   # 削出的偏差 mm/s
                "big": (_v["big"] if _v else 0),
                "why": ((_v or {}).get("why") or ""),
                # 🧭/⚖ 分闸留痕: 这个技能的拍被运动学闸削了哪条 / 被动力学闸削了哪条
                "kin_why": ((_v or {}).get("kin_why") or ""),
                "dyn_why": ((_v or {}).get("dyn_why") or ""),
                "v_cap": _pk("v_cap", "v"), "a_max": _pk("a_max", "a_cal"),
                "jerk_max": _pk("jerk_max", "jerk"),
                "s_step": _pk("s_step"), "s_max": _pk("s_max", "s"),
                "m_kg": _pk("m"), "f_max": _pk("F_max", "F"),
                "calib": str(_q.get("calib") or ""),
            }
        _ph["skills"]["_元"] = {"派发帧龄_s": 0.0, "块帧龄_s": flat["块帧龄_s"], "n": self.n}
        _atomic_json(os.path.join(LIVE, "skill_phys.json"), _ph)
        # ⚖ 偏差唯一依据: 小偏差 → 🧪 状态校正器 (修正误差); 大偏差 → 📡 融合定位 → 🧮 流形引擎 (顶层补偿)
        #   每个技能各一份 (带物理上限与削因), 下游按 big 分流 —— 这是"误差反馈"的唯一出口, 不另开通道。
        _e = {"ts": now, "src": "physics_constraints.InertiaLimiter", "big_err": self.lim.big_err,
              "err": {st: v.get("err") for st, v in out.items()},
              "req": {st: v.get("req") for st, v in out.items()},
              "u": {st: v.get("action") for st, v in out.items()},
              "err_norm": {st: v.get("err_norm") for st, v in out.items()},
              "big": {st: (v.get("big") if v.get("在职") else 0) for st, v in out.items()},
              "why": {st: v.get("why") for st, v in out.items()},
              "phys": {st: v.get("phys") for st, v in out.items()},
              "big_stage": next((st for st, v in out.items() if v.get("big")), ""),
              "stats": self.lim.stats()}
        self.err_last = _e
        _atomic_json(os.path.join(LIVE, "skill_error.json"), _e)
        # 末端技能 (最靠后那一段) 当前状态一并写, 便于上层"看得到技能现状"
        flat["末端技能"] = list(out)[-1] if out else ""
        flat["末端偏差"] = (out[list(out)[-1]]["err_norm"] if out else -1.0)
        self.n += 1
        if self.n % max(1, int(self.hz * 10)) == 1:
            print("[%s] 派发 #%d · 块 %d 个 · 在职 %s (共 %d 段) · 块帧龄 %.2fs"
                  % (time.strftime("%H:%M:%S"), self.n, self.reset_n, self.active or "-", len(out),
                     flat["块帧龄_s"]), flush=True)
        return flat

    def run(self, seconds: float = 0.0):
        t0 = time.time()
        period = 1.0 / max(1e-3, self.hz)
        while True:
            t1 = time.perf_counter()
            try:
                self.cycle()
            except Exception as e:                                          # noqa: BLE001
                print("⚠️ 派发失败: %s: %s" % (type(e).__name__, str(e)[:120]), flush=True)
            if seconds and (time.time() - t0) >= seconds:
                return
            time.sleep(max(0.0, period - (time.perf_counter() - t1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=60.0)
    ap.add_argument("--seconds", type=float, default=0.0)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    dp = Dispatcher(hz=a.hz)
    if a.once:
        print(json.dumps(dp.cycle(), ensure_ascii=False, indent=1))
        return 0
    print("🧩 技能派发循环服务: %.0fHz · 唯一依据 %s · 出口 %s" % (a.hz, LIVE, SHM), flush=True)
    dp.run(a.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
