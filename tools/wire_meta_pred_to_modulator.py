#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wire_meta_pred_to_modulator.py — 🧾元任务预测 → 🧭动作调制器: 真·状态输出约束入口 (默认关)。

老倪 2026-10-15: 「元任务预测的输出, 这是个具体信号, 应该也给到动作调制器, 直接约束动作调制的状态输出」

现状 (必须先说清): 画布上 `n_intent_direct:out1 → sssched:in2`「元任务预测值 → 动作调制」**早就存在**,
但引擎侧 `ActionModulator.decide(u_ff, u_fb, contact_p, residual)` **根本没有元任务预测这个入参** ——
这条线是**声明线, 未被消费**(本工程反复踩的"接线 ≠ 被消费")。所以本次做的是**把它真接进决策**:
 ① `decide(..., meta=None)`: 新增可选入参 (默认 None ⇒ 行为**逐位不变**, 老路径零回退);
 ② 真约束律: 元任务得分离散度越低 (spread→0) ⇒ 预测越没区分度 ⇒ 输出越该保守:
      f = clip(1.0 − κ · (1 − spread/spread_ref), f_min, 1.0)      (κ=1.0, spread_ref=0.05, f_min=0.5)
    u ← u × f (只削幅, 不改方向 —— 与阶段限速同一条纪律: 保方向、削速度);
 ③ **开关** `ZMAX_META_GATE=1` 才生效 (默认 0): 依据"未证明提升不得进默认档"。现在 meta_pred 是
    frozen=1 (驱动扭矩恒定 ⇒ 无区分度), 拿恒定值做门控毫无意义 ⇒ 默认关, 等真机时变扭矩/训练头后再定律;
 ④ 证据: `mod.meta_gate` (最近一次门控值) + `mod.meta_calls` (生效次数) + 仿真轨迹键 `sstrace.元任务门控`
    ⇒ 信号分析里能看见门控值, 开没开、削了多少一目了然。
"""
from __future__ import annotations

import io
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
n = 0


def patch(path, pairs):
    global n
    p = os.path.join(REPO, path)
    s = io.open(p, encoding="utf-8").read()
    for old, new in pairs:
        assert old in s, "%s 锚点没找到: %r" % (path, old[:70])
        s = s.replace(old, new, 1)
        n += 1
    io.open(p, "w", encoding="utf-8").write(s)
    print("已改 %s (%d 处)" % (path, len(pairs)))


# ── ① 决策器: 元任务预测入参 + 门控律 ────────────────────────────────────────
patch("src/lerobot/policies/left_right/state_space/cognition.py", [
    ('''    def decide(self, u_ff, u_fb, contact_p, residual):
        """决策: ①否决权 (残差异常) ②前馈+反馈**相加** ③按阶段显式限速

        u = u_ff + k_fb·u_fb, 然后按当前阶段的速度上限等比缩放 (只削幅, 不改方向)。
        为什么不再用凸组合: 见 STAGE_V_CAP 上方注释 (量级差 21 倍 → 凸组合等于砍速度)。
        """''',
     '''    def decide(self, u_ff, u_fb, contact_p, residual, meta=None):
        """决策: ①否决权 (残差异常) ②前馈+反馈**相加** ③按阶段显式限速 ④元任务预测**门控**(可选)

        u = u_ff + k_fb·u_fb, 然后按当前阶段的速度上限等比缩放 (只削幅, 不改方向)。
        为什么不再用凸组合: 见 STAGE_V_CAP 上方注释 (量级差 21 倍 → 凸组合等于砍速度)。

        🧾 meta (老倪 2026-10-15「元任务预测的输出…直接约束动作调制的状态输出」):
          meta = {"spread": top1-top2, "top1": ..., "n_meta": ...} 来自 zmax/ss_meta_pred (真源 meta_pred.json)。
          · 只在本函数吃到 meta 且 ```ZMAX_META_GATE=1``` 时生效 (默认 0 ⇒ 行为逐位不变);
          · 约束律: 得分离散度越低 ⇒ 预测越没区分度 ⇒ 越保守:
              f = clip(1.0 - KAPPA*(1 - spread/SPREAD_REF), META_GATE_MIN, 1.0)   (只削幅, 不改方向)
          · 依据"未证明提升不得进默认档": 现在 meta_pred 为 frozen=1 (恒定扭矩⇒无区分度) ⇒ 默认关,
            等真机时变扭矩 / 训练头后再按同口径对照定律。生效次数/最近值可查 (meta_calls / meta_gate)。
        """'''
     ),
    ('''        vmin = self.v_min.get(st)
        if vmin is not None and 1e-6 < n < vmin:
            u = u * (vmin / n)             # 最小趋近速度: 证据未达标时别在末端磨 (同样保方向)
        tag = " · 接触" if contact_p > self.contact_th else ""
        return u, f"阶段 {st}{tag}"''',
     '''        vmin = self.v_min.get(st)
        if vmin is not None and 1e-6 < n < vmin:
            u = u * (vmin / n)             # 最小趋近速度: 证据未达标时别在末端磨 (同样保方向)
        # ── ④ 🧾 元任务预测门控 (默认关; 只削幅) ─────────────────────────────
        _mtag = ""
        try:
            if (meta and os.environ.get("ZMAX_META_GATE") == "1"):
                _sp = float(meta.get("spread") or 0.0)
                _f = 1.0 - float(os.environ.get("ZMAX_META_KAPPA") or 1.0) * (1.0 - _sp / 0.05)
                _f = min(1.0, max(0.5, _f))
                u = u * _f
                self.meta_gate = _f
                self.meta_calls = int(getattr(self, "meta_calls", 0)) + 1
                _mtag = " · 元任务门控 ×%.2f" % _f
        except Exception:                                                       # noqa: BLE001
            pass
        tag = (" · 接触" if contact_p > self.contact_th else "") + _mtag
        return u, f"阶段 {st}{tag}"'''
     ),
])

# ── ② 仿真回路: 读真源 meta_pred.json 传进去 + 轨迹键 ───────────────────────
patch("tools/gui/state_space_sim.py", [
    ('''            u, stage = self.sched.decide(u_ff, u_fb, contact_p, r_scalar)''',
     '''            # 🧾 元任务预测 (真源 = daemon 发的 zmax/ss_meta_pred 的同一份文件) → 动作调制器状态约束
            #   默认不生效 (ZMAX_META_GATE=1 才吃); 拿不到文件就传 None, 不伪造。
            _meta = self._meta_pred_snapshot()
            u, stage = self.sched.decide(u_ff, u_fb, contact_p, r_scalar, meta=_meta)'''
     ),
    ('''    def _io_snapshot(self, force, obs, u_ff, act4, latent_pred, prior, z_k,''',
     '''    def _meta_pred_snapshot(self, ttl=1.0):
        """🧾 元任务预测快照 (top1/spread/…): 真源 zmax_data/ss_live/meta_pred.json, 1s 缓存。

        与话题 zmax/ss_meta_pred 同源 (守护就是读这份文件转发的)。读不到返回 None —— 不编数。
        """
        _now = time.time()
        if getattr(self, "_meta_cache", None) and (_now - self._meta_cache[0] < ttl):
            return self._meta_cache[1]
        try:
            _p = os.path.join(os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax"),
                              "zmax_data", "ss_live", "meta_pred.json")
            with open(_p, encoding="utf-8") as _f:
                _d = json.load(_f)
            _top = _d.get("top") or []
            _v = [float(x.get("score") or 0.0) for x in _top if isinstance(x, dict)]
            _m = {"top1": (_v[0] if _v else 0.0),
                  "spread": ((_v[0] - _v[1]) if len(_v) > 1 else 0.0),
                  "n_meta": int(_d.get("n_meta") or 0),
                  "top1_name": (str(_top[0].get("name") or "") if _top else ""),
                  "frozen": int(_d.get("frozen") or 0)}
        except Exception:                                                       # noqa: BLE001
            _m = None
        self._meta_cache = (_now, _m)
        return _m

    def _io_snapshot(self, force, obs, u_ff, act4, latent_pred, prior, z_k,'''
     ),
    ('''              "prior_vec": [],''',
     '''              "prior_vec": [],
              "meta_gate": [],                    # 🧾 元任务门控值 (ZMAX_META_GATE=1 时 <1)'''),
    ('''            tr["prior_vec"].append(np.asarray(prior, dtype=float).copy())''',
     '''            tr["prior_vec"].append(np.asarray(prior, dtype=float).copy())
            tr["meta_gate"].append(float(getattr(self.sched, "meta_gate", 1.0)))'''
     ),
])
print("共 %d 处" % n)
