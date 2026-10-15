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
from lerobot.policies.left_right.state_space.physics_constraints import InertiaLimiter   # noqa: E402
LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
SHM = os.environ.get("ZMAX_SHM_DIR", "/dev/shm/zmax_ss_engine")
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
DT = 0.1                      # 块内每拍时长 (与回路 10Hz 同口径)


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
            out[st] = {"stage": st, "action": _p["u"], "step": step, "ts": now,
                       "age_s": round(now - float(c["ts"]), 4), "n": self.skill_n.get(st, 0),
                       "block_ts": c.get("block_ts"),
                       # ⚖ 物理闸口径: 请求值/可执行值/偏差/大偏差/哪条约束削的 + 该技能物理上限
                       "req": [round(float(x), 6) for x in _p["v_req"]],
                       "err": [round(float(x), 6) for x in _p["err"]], "err_norm": _p["err_norm"],
                       "big": _p["big"], "why": _p["why"], "phys": _p["phys"]}
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
