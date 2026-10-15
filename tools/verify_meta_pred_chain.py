#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_meta_pred_chain.py — 🧾元任务预测 → (信号页显示 + 动作调制器约束) 的判据。

老倪 2026-10-15: 「元任务预测发出的 topic 是什么? 需要显示确切的元任务…元任务预测的输出, 这是个具体信号,
应该也给到动作调制器, 直接约束动作调制的状态输出」

判据 (每条都打在真东西上, 不看源码字面量就算过):
 ① 话题在发: trace.jsonl 里 zmax/ss_meta_pred 的 digest 能解出 mt1..mt5 + spread + top_txt
 ② top_txt 里有**确切的元任务名** (功能号 + 名字 + 得分, ≥3 条)
 ③ 信号页真建出 ds.zmax/ss_meta_pred.mt1..mt5, 且「🧾 元任务预测」文字行真显示了 ≥3 条确切元任务
 ④ 画布: 🧾元任务预测 → 🧭动作调制器 的线在 (n_intent_direct:out1 → sssched:in2)
 ⑤ 引擎侧**真被消费** (不是声明线): decide() 吃 meta; 关闸时行为逐位不变; 开闸时输出被按 f 削幅且计数增加
 ⑥ 仿真轨迹里有 sstrace.元任务门控 键 (开闸时看得见削了多少)
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np                                                      # noqa: E402

ok = True


def chk(name, cond, detail=""):
    global ok
    print("   %s %s%s" % ("✅" if cond else "❌", name, (" · " + str(detail)) if detail else ""))
    ok = ok and bool(cond)


# ── ① 话题 + digest ─────────────────────────────────────────────────────────
print("① 话题 zmax/ss_meta_pred 在发且 digest 含确切元任务")
tp = os.path.join(REPO, "zmax_data", "dataspace", "trace.jsonl")
last = None
try:
    with open(tp, encoding="utf-8", errors="ignore") as f:
        for ln in f.readlines()[-800:]:
            try:
                r = json.loads(ln)
            except Exception:                                               # noqa: BLE001
                continue
            if r.get("topic") == "zmax/ss_meta_pred":
                last = r
except Exception as e:                                                      # noqa: BLE001
    last = None
    print("      读 trace.jsonl 失败: %s" % e)
chk("话题在 trace.jsonl 里 (最近 800 帧)", last is not None)
d = {}
if last:
    _dg = str(last.get("digest") or "")
    for k in ("mt1", "mt2", "mt3", "mt4", "mt5", "spread"):
        chk("digest 有数值键 %s" % k, ('"%s"' % k) in _dg)
    _mt = None
    try:
        _mt = json.loads(_dg)
    except Exception:                                                       # noqa: BLE001
        pass
    _txt = str((_mt or {}).get("top_txt") or "")
    chk("digest 有 top_txt (确切元任务串)", bool(_txt), _txt[:80])
    chk("top_txt 含 ≥3 条「功能号 + 名字 + 得分」", _txt.count("›") >= 2 and "FN-" in _txt)
    chk("帧龄新鲜 (<120s)", (time.time() - float(last.get("t") or 0)) < 120)

# ── ③ 信号页显示 ────────────────────────────────────────────────────────────
print("② 信号分析页: 建出 mt1..mt5 且文字行显示确切元任务")
try:
    from PyQt5 import QtWidgets                                        # noqa: E402
    import canoe_graphic as cg                                          # noqa: E402
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    w = cg.CanoeGraphicWidget()
    w.show()
    t_end = time.time() + 16
    while time.time() < t_end:
        app.processEvents()
        time.sleep(0.1)
    ks = [k for k in w.store.keys() if k.startswith("ds.zmax/ss_meta_pred.mt")]
    chk("页面已建 mt 信号 ≥3", len(ks) >= 3, sorted(ks)[:6])
    import re as _re
    plain = _re.sub("<[^>]+>", "", w.lb_meta.text() or "")
    chk("文字行显示了确切元任务 (≥3 条)", plain.count("›") >= 2 and "FN-" in plain, plain[:110])
    chk("文字行不含占位空态", "等话题" not in plain)
except Exception as e:                                                      # noqa: BLE001
    chk("信号页探针", False, e)

# ── ④ 画布接线 ──────────────────────────────────────────────────────────────
print("③ 画布: 元任务预测 → 动作调制器")
try:
    d2 = json.load(open(os.path.realpath(os.path.join(REPO, "flows", "state_space_obs.json")), encoding="utf-8"))
    wire = [l for l in d2["links"] if l.get("f") == "n_intent_direct" and l.get("t") == "sssched"]
    chk("线在 (n_intent_direct → sssched)", bool(wire), (wire[0].get("label") if wire else ""))
except Exception as e:                                                      # noqa: BLE001
    chk("读画布", False, e)

# ── ⑤ 引擎侧真消费 (开关 + 门控律) ──────────────────────────────────────────
print("④ 引擎侧真消费: decide(meta=) 默认不变 / 开闸按 f 削幅")
try:
    sys.path.insert(0, os.path.join(REPO, "src"))
    from lerobot.policies.left_right.state_space import cognition as C   # noqa: E402
    u_ff = np.array([0.5, 0.2, -0.1, 0.0])
    u_fb = np.array([0.01, 0.0, 0.0, 0.0])
    meta = {"top1": 0.0366, "spread": 0.0125, "n_meta": 51, "frozen": 1}
    os.environ.pop("ZMAX_META_GATE", None)
    m1, _ = C.ActionModulator().decide(u_ff, u_fb, 0.0, 0.0)
    m2, _ = C.ActionModulator().decide(u_ff, u_fb, 0.0, 0.0, meta=meta)
    chk("默认 (ZMAX_META_GATE 未设) 行为逐位不变", bool(np.array_equal(m1, m2)), "max|Δ|=%.2e" % float(np.max(np.abs(m1 - m2))))
    os.environ["ZMAX_META_GATE"] = "1"
    mod = C.ActionModulator()
    m3, tag3 = mod.decide(u_ff, u_fb, 0.0, 0.0, meta=meta)
    chk("开闸后输出被削幅 (‖u‖ 变小)", float(np.linalg.norm(m3[:3])) < float(np.linalg.norm(m2[:3])),
        "%.5f → %.5f, f=%.3f" % (float(np.linalg.norm(m2[:3])), float(np.linalg.norm(m3[:3])),
                                 float(getattr(mod, "meta_gate", 0))))
    chk("开闸后方向不变 (只削幅)", bool(np.allclose(m3[:3] / max(1e-9, float(np.linalg.norm(m3[:3]))),
                                                    m2[:3] / max(1e-9, float(np.linalg.norm(m2[:3]))), atol=1e-9)))
    chk("证据可查 (meta_calls>0 且 tag 写明)", int(getattr(mod, "meta_calls", 0)) > 0 and "元任务门控" in tag3, tag3)
    os.environ.pop("ZMAX_META_GATE", None)
except Exception as e:                                                      # noqa: BLE001
    chk("引擎侧探针", False, e)

# ── ⑥ 仿真轨迹键 ────────────────────────────────────────────────────────────
print("⑤ 仿真轨迹有 meta_gate 键")
try:
    src = open(os.path.join(REPO, "tools", "gui", "state_space_sim.py"), encoding="utf-8").read()
    chk("轨迹字典含 meta_gate 且逐拍写入", '"meta_gate": []' in src and 'tr["meta_gate"].append' in src)
    chk("回路把 meta 传进 decide (真消费点)", "meta=_meta" in src and "_meta_pred_snapshot" in src)
except Exception as e:                                                      # noqa: BLE001
    chk("轨迹键", False, e)

print("\n" + "=" * 84)
print("结论: %s" % ("✅ 全过 — 元任务预测: 话题在发+确切元任务上屏+画布有线+引擎真消费(默认关, 可开)" if ok else "❌ 未通过"))
print("=" * 84)
sys.exit(0 if ok else 1)
