#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_skill_dispatch.py — 🧩 技能派发**常驻循环服务**: 块 → 每个技能取"最新那一拍" → 实时执行。

老倪 2026-10-15: 「最后从安全执行器输出后, 给到每个技能, 由肌肉记忆的每个技能 接近 对位 下降等,
选取最新的动作执行, 实时执行。最后的技能, 应该通过一个循环服务, 快速流转到具体的技能。」

做法 (60Hz 默认, 纯读块 + 写共享内存, 不下发任何真机指令):
  ① 读块真源 zmax_data/ss_live/chunk_latest.json (常驻回路每周期写; 含 u[H,4] = 加权+调制+安全后的序列)
  ② 每个技能 (八阶段: 接近/对位/下降/抓取/抬起/转移/插入/完成) 认领块里属于自己的那一拍
     (块内第 i 拍 → 阶段 stage_idx+i); 没轮到的技能保持**上一次最新**的那一拍 (肌肉记忆: 用最近拿到的)
  ③ 队内推进: 按经过时间把每技能的"当前拍"往前推 (块 dt=0.1s), 推到底就停在最后一拍 (等下一块)
     ⇒ 技能拿到的是**最新可用**动作, 而不是一块里永远第一步
  ④ 落两条真源:
     /dev/shm/zmax_ss_engine/skill_<idx>_<name>.json   每个技能的当前动作 (技能侧直接读, 微秒级)
     zmax_data/ss_live/skill_latest.json               平铺数值 (信号分析直接画: 每技能速度 + 派发帧龄/次数)
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "src") not in __import__("sys").path:
    __import__("sys").path.insert(0, os.path.join(ROOT, "src"))
from lerobot.policies.left_right.state_space.physics_constraints import (InertiaLimiter,   # noqa: E402
                                                                       limits_for)
# ⚖ 技能号 ↔ 阶段: 真源 = 技能库的类 (code/stage 类属性), 不在这里手写编号
from lerobot.policies.left_right.state_space.skills.atomic_skills import SKILLS, SKILLS_TRAY  # noqa: E402
CODE_BY_STAGE = {}
for _c in list(SKILLS) + list(SKILLS_TRAY):
    CODE_BY_STAGE.setdefault(_c.stage, _c.code)          # SK07 插拔链=插入 / 摆盘链=放入 (同号两支)
LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
SHM = os.environ.get("ZMAX_SHM_DIR", "/dev/shm/zmax_ss_engine")
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
DT = 0.1                      # 块内每拍时长 (与回路 10Hz 同口径)
POSE_STALE_S = float(os.environ.get("ZMAX_SKILL_POSE_STALE_S", "5.0"))   # 位姿停更阈值 (= 发布守护同口径)


def _read_pose():
    """真机 tap 位姿 (x/y/z mm + 姿态角 deg) —— 尾读最新 state_*.jsonl 的**最后一行** (不整文件读入)。

    口径与发布守护 tools/dds/ss_daemon.py::read_state 同源 (同一个 tap 文件、同一个新鲜度阈值):
      帧龄 > POSE_STALE_S ⇒ 位姿停更 ⇒ 一律 -1 (老倪: 不许拿旧位姿当现在)。
    """
    import glob as _g
    c = _g.glob(os.path.join(LIVE, "state_*.jsonl"))
    if not c:
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
        return {"x": -1.0, "y": -1.0, "z": -1.0, "angle": -1.0, "pose_age_s": age, "stale": 1}
    tcp = [float(v) for v in (d.get("tcp") or [])]
    q = [float(v) for v in (d.get("tcp_quat") or [])]
    ang = -1.0
    if len(q) >= 4:
        import math as _m
        w = max(-1.0, min(1.0, abs(q[3])))
        ang = round(2.0 * _m.degrees(_m.acos(w)), 3)
    return {"x": (tcp[0] if len(tcp) > 0 else -1.0), "y": (tcp[1] if len(tcp) > 1 else -1.0),
            "z": (tcp[2] if len(tcp) > 2 else -1.0), "angle": ang, "pose_age_s": round(age, 3)}


def _atomic_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, path)


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
        self.last_v = {s_: np.zeros(3) for s_ in STAGES}
        self.last_a = {s_: np.zeros(3) for s_ in STAGES}
        # ⚖ 加速度真源: 块边界算一次并**保留到下一块** (老倪 2026-10-15「信号分析里要看到 a 加速度」)。
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

    def _phys(self, st, action):
        """⚖ 进技能的 action 先过物理闸 (惯性/加速度/加加速度/动量率) —— 过不去就削出偏差 error。"""
        r = self.lim.limit(st, action, v_prev=self.last_v.get(st), a_prev=self.last_a.get(st))
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
            _p = self._phys(st, _req)
            # ⚖ 老倪 2026-10-15: 信号分析要看到 x y z v a 等物理值 ⇒ 逐拍把这些量算出来落盘
            _a_n = float(self.a_blk.get(st, 0.0))                     # mm/s² (块间速度变化率, 保留到下一块)
            _s_mm = float(self.lim.travel.get(st, 0.0)) * 1000.0       # 本段累计行程 mm
            out[st] = {"stage": st, "action": _p["u"], "step": step, "ts": now,
                       "age_s": round(now - float(c["ts"]), 4), "n": self.skill_n.get(st, 0),
                       "block_ts": c.get("block_ts"),
                       # ⚖ 物理闸口径: 请求值/可执行值/偏差/大偏差/哪条约束削的 + 该技能物理上限
                       "req": [round(float(x), 6) for x in _p["v_req"]],
                       "err": [round(float(x), 6) for x in _p["err"]], "err_norm": _p["err_norm"],
                       "big": _p["big"], "why": _p["why"], "phys": _p["phys"],
                       "a_mms2": _a_n, "s_mm": _s_mm,
                       "skill": CODE_BY_STAGE.get(st, "")}
            _atomic_json(os.path.join(SHM, "skill_%d_%s.json" % (STAGES.index(st), st)), out[st])
        flat = {"ts": now, "n": self.n, "reset_n": self.reset_n,
                "派发帧龄_s": 0.0, "块帧龄_s": round(now - (self._chunk_ts or now), 3)}
        for st in STAGES:
            v = out.get(st)
            flat["%s_mps" % st] = (_norm(v["action"]) if v else -1.0)
            flat["%s_拍" % st] = (v["step"] if v else -1)
            flat["%s_请求_mps" % st] = (_norm(v["req"]) if v and v.get("req") else -1.0)   # 前馈/块给的请求值
            flat["%s_偏差_mps" % st] = (float(v.get("err_norm") or 0.0) if v else -1.0)     # ⚖ 物理不可行偏差
            flat["%s_可行" % st] = (0 if (v or {}).get("why") not in (None, "可行") else 1)  # 1=原样可行 0=被削
        _atomic_json(os.path.join(LIVE, "skill_latest.json"), flat)
        # ⚖ 原子技能物理量真源 (老倪 2026-10-15「所有原子技能都要有 topic 输出, 信号分析里看到 x y z v a」):
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
            # ⚖ 包络一律取 **limits_for 真源** (在职/不在职都一样): 闸门导出到每拍结果里的 phys 是
            #   给报告看的**四舍五入摘要** (m 4位 / a_max 4位 / jerk_max 3位), 拿它当"物理模型"发布
            #   就等于把 4.166667 变成 4.1667 —— 信号分析里对不上真源, 判据也过不了 1e-6。
            _q = dict(limits_for(_st) or {}) or dict((_v or {}).get("phys") or {})
            # ⚠️ 两个来源的键名不同 (闸门 phys: v_cap/F_max; limits_for: v/F/jerk/s) —— 统一成正名,
            #    否则会把包络写成一串 -1 而在信号分析里显示"没有物理模型"(同一类坑: dmdt vs dmdt_max)。
            def _pk(*names):
                for _n in names:
                    _x = _q.get(_n)
                    if isinstance(_x, (int, float)):
                        return float(_x)
                return -1.0
            _ph["skills"][_code] = {
                "stage": _st, "在职": 1 if _v else 0,
                "step": (_v["step"] if _v else -1),
                "x": (_pose["x"] if _v else -1.0), "y": (_pose["y"] if _v else -1.0),
                "z": (_pose["z"] if _v else -1.0), "angle": (_pose["angle"] if _v else -1.0),
                "pose_age_s": _pose["pose_age_s"],
                "v_mms": (float(np.linalg.norm(np.asarray(_v["action"], float)[:3])) * 1000.0
                          if _v else -1.0),                                    # 速度 mm/s (不四舍五入: 界面负责显示)
                "a_mms2": (_v["a_mms2"] if _v else -1.0),                      # 加速度 mm/s²
                "s_mm": (_v["s_mm"] if _v else -1.0),                          # 段累计行程 mm
                "err_mms": (float(_v["err_norm"]) * 1000.0 if _v else -1.0),   # 削出的偏差 mm/s
                "big": (_v["big"] if _v else 0),
                "why": ((_v or {}).get("why") or ""),
                "v_cap": _pk("v_cap", "v"), "a_max": _pk("a_max", "a_cal"),
                "jerk_max": _pk("jerk_max", "jerk"),
                "s_step": _pk("s_step"), "s_max": _pk("s_max", "s"),
                "m_kg": _pk("m"), "f_max": _pk("F_max", "F"),
                "calib": str(_q.get("calib") or ""),
            }
        _ph["skills"]["_元"] = {"派发帧龄_s": 0.0, "块帧龄_s": flat["块帧龄_s"], "n": self.n}
        _atomic_json(os.path.join(LIVE, "skill_phys.json"), _ph)
        # ⚖ 偏差真源: 小偏差 → 🧪 状态校正器 (修正误差); 大偏差 → 📡 融合定位 → 🧮 流形引擎 (顶层补偿)
        #   每个技能各一份 (带物理上限与削因), 下游按 big 分流 —— 这是"误差反馈"的唯一出口, 不另开通道。
        _e = {"ts": now, "src": "physics_constraints.InertiaLimiter", "big_err": self.lim.big_err,
              "err": {st: v.get("err") for st, v in out.items()},
              "req": {st: v.get("req") for st, v in out.items()},
              "u": {st: v.get("action") for st, v in out.items()},
              "err_norm": {st: v.get("err_norm") for st, v in out.items()},
              "big": {st: v.get("big") for st, v in out.items()},
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
            print("[%s] 派发 #%d · 块 %d 个 · 技能 %d 个在职 · 块帧龄 %.2fs"
                  % (time.strftime("%H:%M:%S"), self.n, self.reset_n, len(out), flat["块帧龄_s"]), flush=True)
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
    print("🧩 技能派发循环服务: %.0fHz · 真源 %s · 出口 %s" % (a.hz, LIVE, SHM), flush=True)
    dp.run(a.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
