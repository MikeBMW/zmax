#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_chunk_topic.py — 新增话题 zmax/ss_action_chunk (🧩 动作块) + 守护发布。

老倪 2026-10-15: 「Flow Matching Action Head 的输出, 是个 chunk action, 预测 [a_t,…,a_{t+H-1}] …
应该有输出 topic, 在信号分析里显示」

载荷 = 唯一依据 zmax_data/ss_live/chunk_latest.json (由常驻回路每周期经 tools/ss_chunk_pipeline.py 落盘):
  chunk[H,4] 引擎规划的动作块 / ff[H,4] 前馈序列 / u[H,4] 加权+逐拍调制+逐拍安全后的执行序列 /
  lam[H] 块权重 / 平滑性 (转角·步间差·二阶差分) / 阶段 / 块耗时。
三段都发 ⇒ 话题上能直接看出"块 → 前馈序列 → 加权 → 调制/安全 → 技能"这条链的每一环。
"""
from __future__ import annotations

import io
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── ① 类型 ───────────────────────────────────────────────────────────────────
TP = os.path.join(REPO, "dds", "ss_types.py")
s = io.open(TP, encoding="utf-8").read()
assert "class SSActionChunk" not in s
ANCHOR = """# ──────────────── 🧮 流形引擎 · 常驻周期循环 (老倪 2026-10-14) ────────────────"""
NEW = '''# ─────────────────────── 🧩 动作块 (老倪 2026-10-15) ───────────────────────
@dataclass
class SSActionChunk(IdlStruct, typename="zmax::SSActionChunk"):
    """🧩 **动作块 (chunk action)** —— 老倪 2026-10-15: 「Flow Matching Action Head 的输出是个 chunk action,
    预测 [a_t,…,a_{t+H-1}], 一次推理管多步 … 应该有输出 topic, 在信号分析里显示」

    链路口径 (每一环都在载荷里, 不是图上的箭头):
      chunk[H,4]  引擎**一次求解**的测地线规划 → 逐点解码的动作块 (a_t … a_{t+H-1})
      ff[H,4]     前馈加速器 (训练左脑 MLP 真权重) 的 H 步序列 (逐拍 或 hold, ff_mode 写明)
      u[H,4]      加权后的序列 (u = (1-λ)·ff + λ·chunk) → 逐拍过动作调制器 → 逐拍过安全执行边界
      lam[H]      块权重 (近步小、远步大, 单调; 可查)
    唯一依据: tools/ss_chunk_pipeline.py 落的 zmax_data/ss_live/chunk_latest.json (常驻回路每周期写);
          守护读它发布 (过期/缺块只发告警, 不拿旧块当现在)。
    H 上限 16 (载荷按 16 预留, 实际块长看 h 字段)。
    """
    ts: float64 = 0.0                  # 发布时刻 (epoch 秒)
    cycle: int64 = 0                   # 产出块的回路周期号 (单调, 可判"是不是真在跑")
    h: int32 = 0                       # 块长 H (实际)
    stage: str = ""                    # 当前八阶段 (接近/对位/下降/…)
    stage_idx: int32 = -1
    chunk_src: str = ""                # 块来源 (测地线规划 … / ridge 解码 …)
    ff_mode: str = ""                  # 前馈序列来源 (rollout / hold)
    chunk: sequence[float64] = field(default_factory=list)   # H*4 平铺 (a_t … a_{t+H-1})
    ff: sequence[float64] = field(default_factory=list)      # H*4 平铺 (前馈序列)
    u: sequence[float64] = field(default_factory=list)       # H*4 平铺 (调制+安全后, 待技能选取)
    lam: sequence[float64] = field(default_factory=list)     # H (块权重)
    turn_max_deg: float64 = -1.0       # 块内最大折角 (度)
    turn_mean_deg: float64 = -1.0      # 块内平均折角 (度)
    step_delta: float64 = -1.0         # 块内平均步间差 ‖Δa‖
    jerk: float64 = -1.0               # 块内平均二阶差分 ‖Δ²a‖
    u_norm0: float64 = -1.0            # 第一拍 (当前阶段要执行的那一拍) 速度模长
    skill_list: str = ""               # 派发到各技能 (\"下降:步0, 抓取:步1, …\")
    dispatch_age_s: float64 = -1.0     # 技能派发帧龄 (由技能循环服务刷新的 skill_dispatch.json)
    ms: float64 = -1.0                 # 本块耗时
    src: str = ""
    note: str = ""


''' + ANCHOR
s = s.replace(ANCHOR, NEW, 1)
io.open(TP, "w", encoding="utf-8").write(s)
print("① ss_types.py: 加 SSActionChunk")

# ── ② 守护: 发布 ────────────────────────────────────────────────────────────
DP = os.path.join(REPO, "tools", "dds", "ss_daemon.py")
d = io.open(DP, encoding="utf-8").read()
assert "def pub_action_chunk" not in d
HOOK = '''    def pub_meta_pred(self):'''
d = d.replace(HOOK, '''    def pub_action_chunk(self):
        """🧩 **动作块** → zmax/ss_action_chunk (老倪 2026-10-15)。

        唯一依据 = 常驻回路经 tools/ss_chunk_pipeline.py 落的 zmax_data/ss_live/chunk_latest.json。
        纪律: 帧龄 > CHUNK_STALE_S 就明说陈旧; 块不 ok (引擎无目标点等) 就发空块 + note 写原因, 不编块。
        """
        from ss_types import SSActionChunk                                    # noqa: PLC0415
        _root = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
        p = os.path.join(_root, "zmax_data", "ss_live", "chunk_latest.json")
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:                                               # noqa: BLE001
            self.publish("ss_action_chunk", SSActionChunk(ts=time.time(),
                                                          note="读不到块唯一依据 %s (%s)" % (os.path.basename(p),
                                                                                          type(e).__name__)))
            return False
        age = time.time() - float(d.get("ts") or 0.0)
        note = ""
        if not d.get("ok"):
            note = "块未产出: %s" % str(d.get("reason") or "")[:80]
        elif age > CHUNK_STALE_S:
            note = "⚠️ 块陈旧 %.1fs (> %.0fs): 这不是现在的块" % (age, CHUNK_STALE_S)
        ch, ff, uu = (d.get("chunk") or []), (d.get("ff") or []), (d.get("u") or [])
        sk = d.get("skills") or {}
        # 技能派发帧龄 (由技能循环服务刷新的 skill_dispatch.json)
        _dage = -1.0
        try:
            with open(os.path.join(_root, "zmax_data", "ss_live", "skill_dispatch.json"), encoding="utf-8") as f:
                _dage = time.time() - float((json.load(f) or {}).get("ts") or 0.0)
        except Exception:                                                    # noqa: BLE001
            pass
        self.publish("ss_action_chunk", SSActionChunk(
            ts=time.time(), cycle=int(d.get("cycle") or 0), h=int(d.get("h") or 0),
            stage=str(d.get("stage") or ""), stage_idx=int(d.get("stage_idx") or -1),
            chunk_src=str(d.get("chunk_src") or "")[:120], ff_mode=str(d.get("ff_mode") or "")[:80],
            chunk=[float(x) for row in ch for x in (row or [])],
            ff=[float(x) for row in ff for x in (row or [])],
            u=[float(x) for row in uu for x in (row or [])],
            lam=[float(x) for x in (d.get("lam") or [])],
            turn_max_deg=float(d.get("turn_max_deg") or -1.0),
            turn_mean_deg=float(d.get("turn_mean_deg") or -1.0),
            step_delta=float(d.get("step_delta") or -1.0), jerk=float(d.get("jerk") or -1.0),
            u_norm0=float(d.get("u_norm0") or -1.0),
            skill_list=", ".join("%s:步%d" % (k, int(v.get("step") or 0)) for k, v in list(sk.items())[:8]),
            dispatch_age_s=round(_dage, 2),
            ms=float(d.get("ms") or -1.0), src=str(d.get("chunk_src") or "")[:120], note=note))
        return True

    def pub_meta_pred(self):''', 1)
# 常量
d = d.replace('''META_PRED_STALE_S = ''', '''CHUNK_STALE_S = float(os.environ.get("ZMAX_CHUNK_STALE_S", "30"))
META_PRED_STALE_S = ''', 1)
# MODE_TOPICS: 三档都发 (A 核心集 / B 全开 / C 只走 shm —— 由 allowed() 收口, 这里登记进清单)
for _old, _new in [('"ss_meta_pred", "ss_stage"],', '"ss_meta_pred", "ss_stage", "ss_action_chunk"],'),
                   ('"ss_meta_pred", "ss_stage"],', '"ss_meta_pred", "ss_stage", "ss_action_chunk"],')]:
    d = d.replace(_old, _new)
io.open(DP, "w", encoding="utf-8").write(d)
print("② ss_daemon.py: 加 pub_action_chunk + CHUNK_STALE_S + 清单登记")
