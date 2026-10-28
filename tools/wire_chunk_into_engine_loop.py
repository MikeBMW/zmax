#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wire_chunk_into_engine_loop.py — 把 🧩 块流水线接进常驻回路 (每周期真算块)。

老倪 2026-10-15: 「Flow Matching Action Head 的输出, 是个 chunk action … 应该有输出 topic, 在信号分析里显示。
这个 chunk action 序列里的 action 动作, 应该给前馈加速器输出的 action 加权; 前馈加速器发出的 action 也应该
是一个序列, 由动作调制器调制后继续执行; ... 最后从安全执行器输出后, 给到每个技能 ... 通过一个循环服务快速流转」

接法 (纯**增量**, 不改引擎原有动作): 常驻回路每周期在 `eng.step()` 之后多算一条块流水线
  tools/ss_chunk_pipeline.py → 块/前馈序列/加权/逐拍调制/逐拍安全/技能派发
  ① 落盘 zmax_data/ss_live/chunk_latest.json + skill_dispatch.json (话题/技能服务都读它)
  ② 把块的关键量并进 engine_trace.json / engine_latest.json 的 trace 键 (信号分析直接画)
  ③ **不动** rec["action"] (引擎解出的动作照旧) —— 块是"规划+派发分支", 由技能循环服务消费;
     真机执行仍须走授权通道 (动作授权只从 8793 来), 本模块不碰真机指令。
关: ZMAX_CHUNK_H=1 (或 =0) ⇒ 本模块完全不参与 (逐位回退)。
"""
from __future__ import annotations

import io
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(REPO, "tools", "ss_engine_loop.py")
s = io.open(P, encoding="utf-8").read()
n = 0


def rep(old, new):
    global s, n
    assert old in s, "锚点没找到: %r" % old[:90]
    s = s.replace(old, new, 1)
    n += 1


# ① __init__: 建块流水线 (默认 H=8; ZMAX_CHUNK_H=1/0 关)
rep('''    def __init__(self, hz: float, state_file: str | None, traj_path: str, inertia: bool,''',
    '''    def _chunk_stage(self) -> tuple[int, str]:
        """当前八阶段 (唯一依据 zmax_data/ss_live/trace_live.json = ss_stage 话题的同一份; 读不到就 0 + 如实标注)。"""
        try:
            d = _j(os.path.join(LIVE_DIR, "trace_live.json"), None) or {}
            _n = str(d.get("阶段") or d.get("stage") or "")
            if _n:
                for i, s_ in enumerate(["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]):
                    if s_ in _n:
                        return i, s_
            _i = d.get("idx8")
            if isinstance(_i, (int, float)):
                return max(0, min(7, int(_i))), str(_n)
        except Exception:                                                    # noqa: BLE001
            pass
        return 0, ""

    def _meta_pred(self):
        """🧾 元任务预测 (唯一依据 meta_pred.json —— 与话题 zmax/ss_meta_pred 同源; 读不到返回 None)。"""
        try:
            d = _j(os.path.join(LIVE_DIR, "meta_pred.json"), None) or {}
            _t = d.get("top") or []
            _v = [float(x.get("score") or 0.0) for x in _t if isinstance(x, dict)]
            return {"top1": (_v[0] if _v else 0.0),
                    "spread": ((_v[0] - _v[1]) if len(_v) > 1 else 0.0),
                    "n_meta": int(d.get("n_meta") or 0), "frozen": int(d.get("frozen") or 0)}
        except Exception:                                                    # noqa: BLE001
            return None

    def __init__(self, hz: float, state_file: str | None, traj_path: str, inertia: bool,''')

# ② cycle(): eng.step 之后算块
rep('''        rec = self.eng.step(np.asarray(state, float), dt=self.dt)
        ms = (time.perf_counter() - t0) * 1000.0
        self.n += 1''',
    '''        rec = self.eng.step(np.asarray(state, float), dt=self.dt)
        ms = (time.perf_counter() - t0) * 1000.0
        self.n += 1
        # 🧩 动作块流水线 (老倪 2026-10-15; ZMAX_CHUNK_H<=1 不进): 引擎出块 → 前馈序列 → 加权 → 逐拍调制
        #    → 逐拍安全 → 技能派发。**不改** rec["action"] (引擎动作照旧), 块走独立分支 + 落盘给技能服务。
        chunk_rec: dict = {}
        if self.chunk is not None and not replay:
            try:
                _si, _sn = self._chunk_stage()
                chunk_rec = self.chunk.step(self.eng, np.asarray(state, float), state=np.asarray(state, float),
                                            stage_idx=_si, meta=self._meta_pred(),
                                            residual=float(rec.get("residual") or 0.0))
                chunk_rec["stage_name"] = _sn
            except Exception as e:                                           # noqa: BLE001
                chunk_rec = {"ok": False, "reason": "%s: %s" % (type(e).__name__, str(e)[:120])}''')

# ③ 并进 trace 记录
rep('''            "pipe": pipe_rec if isinstance(pipe_rec, dict) else {},''',
    '''            "chunk": chunk_rec if isinstance(chunk_rec, dict) else {},
            "chunk_keys": (self.chunk.trace_keys(chunk_rec)
                           if (self.chunk is not None and isinstance(chunk_rec, dict)) else {}),
            "pipe": pipe_rec if isinstance(pipe_rec, dict) else {},''')
io.open(P, "w", encoding="utf-8").write(s)
print("ss_engine_loop.py 已改 %d 处" % n)
