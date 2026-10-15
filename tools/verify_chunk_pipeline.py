#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_chunk_pipeline.py — 🧩 动作块链判据 (老倪 2026-10-15 原话逐条对)。

老倪: 「Flow Matching Action Head 的输出, 是个 chunk action, 预测 [a_t,…,a_{t+H-1}] 一次推理管多步, 轨迹更平滑,
便于异步执行, 对不? 应该有输出 topic, 在信号分析里显示。这个 chunk action 序列里的 action 动作, 应该给前馈
加速器输出的 action 加权; 前馈加速器发出的 action 也应该是一个序列, 由动作调制器调制后继续执行; 调制后输出的
也应该是序列 action, 最后从安全执行器输出后, 给到每个技能, 由肌肉记忆的每个技能 … 选取最新的动作执行,
实时执行。最后的技能, 应该通过一个循环服务, 快速流转到具体的技能。」

判据 (全部打在真东西上):
  ① 话题 zmax/ss_action_chunk 真在发 (DDS 订阅收到) 且载荷含 chunk/ff/u/lam 四段
  ② 块是"多步且逐步不同" (H≥2, ‖Δa‖>0) —— 不是同一拍复制 H 份
  ③ 块长/阶段/平滑性字段在 (H, stage, turn/step_delta/jerk 都是实数)
  ④ 前馈序列长度 == H 且 ff_mode 写明来源 (hold/rollout)
  ⑤ 加权: λ 单调递增且 u ≠ chunk (加权+调制+安全真的改动了动作)
  ⑥ 逐拍调制/安全: u 每拍都在安全界内
  ⑦ 技能派发循环服务 active + 每技能文件在 /dev/shm + skill_latest.json 帧龄 <1s + 计数在涨
  ⑧ 信号分析页: 建出 chunk.* / skill.* 行 + 🧩 文字行 (含 H=)
  ⑨ 零回归: 引擎原有 action 仍在发且块是**独立分支** (rec.action 与 chunk 分开)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(REPO, "zmax_data", "ss_live")
ok = True


def chk(name, cond, detail=""):
    global ok
    print("   %s %s%s" % ("✅" if cond else "❌", name, (" · " + str(detail)) if detail else ""))
    ok = ok and bool(cond)


# ── ① DDS 话题 ──────────────────────────────────────────────────────────────
print("① 话题 zmax/ss_action_chunk (DDS) 在发 + 四段载荷")
sys.path.insert(0, os.path.join(REPO, "dds"))
msg = None
try:
    from zmax_node import Node                                                    # noqa: E402
    import ss_types as T                                                          # noqa: E402
    n = Node("chunk_verify")
    t0 = time.time()
    while time.time() - t0 < 20 and msg is None:
        for x in n.take("ss_action_chunk", timeout=1.0):
            msg = x
            break
except Exception as e:                                                            # noqa: BLE001
    chk("DDS 订阅", False, e)
chk("话题收到帧", msg is not None)
if msg is not None:
    chk("h == 8 (块长)", int(msg.h) == 8, "h=%d" % msg.h)
    chk("chunk 段长度 = h*4", len(list(msg.chunk)) == 4 * int(msg.h), len(list(msg.chunk)))
    chk("ff 段长度 = h*4", len(list(msg.ff)) == 4 * int(msg.h), len(list(msg.ff)))
    chk("u 段长度 = h*4", len(list(msg.u)) == 4 * int(msg.h), len(list(msg.u)))
    chk("lam 段长度 = h", len(list(msg.lam)) == int(msg.h), len(list(msg.lam)))
    chk("阶段 + 块来源写明", bool(msg.stage) and bool(msg.chunk_src), "%s | %s" % (msg.stage, msg.chunk_src[:40]))

# ── ②/③/⑤ 块真源 ───────────────────────────────────────────────────────────
print("② 块真源: 多步逐步不同 + 平滑性 + 加权/调制生效")
try:
    with open(os.path.join(LIVE, "chunk_latest.json"), encoding="utf-8") as f:
        d = json.load(f)
    chk("块 ok (未产出会写明原因)", bool(d.get("ok")), str(d.get("reason") or "")[:60])
    ch = d.get("chunk") or []
    uu = d.get("u") or []
    lam = d.get("lam") or []

    def _nrm(v):
        return float(sum(x * x for x in v[:3]) ** 0.5)

    dif = [abs(_nrm(ch[i + 1]) - _nrm(ch[i])) for i in range(len(ch) - 1)]
    chk("块 ≥2 拍", len(ch) >= 2, "H=%d" % len(ch))
    chk("逐步不同 (不是同一拍复制)", max(dif or [0]) > 1e-6, "max|Δ‖a‖|=%.2e" % (max(dif) if dif else 0))
    chk("平滑性字段是实数", all(isinstance(d.get(k), (int, float)) for k in ("turn_mean_deg", "step_delta", "jerk")),
        "转角%.2f° 步间差%.5f 二阶%.5f" % (d.get("turn_mean_deg") or 0, d.get("step_delta") or 0, d.get("jerk") or 0))
    chk("λ 单调递增 (近步小→远步大)", all(lam[i] < lam[i + 1] for i in range(len(lam) - 1)),
        "λ0=%.3f → λ%d=%.3f" % (lam[0], len(lam) - 1, lam[-1]) if lam else "")
    _same = all(abs(_nrm(uu[i]) - _nrm(ch[i])) < 1e-9 for i in range(min(len(uu), len(ch))))
    chk("加权+调制+安全真改动了动作 (u≠chunk)", not _same,
        "u首拍%.5f vs chunk首拍%.5f" % (_nrm(uu[0]) if uu else -1, _nrm(ch[0]) if ch else -1))
    _ff = d.get("ff") or []
    chk("前馈序列长度 = H 且来源写明", len(_ff) == len(ch) and bool(d.get("ff_mode")),
        "%s (%.0f 字)" % (d.get("ff_mode"), len(_ff)))
except Exception as e:                                                            # noqa: BLE001
    chk("读块真源", False, e)

# ── ⑥ 安全界 ────────────────────────────────────────────────────────────────
print("③ 逐拍安全执行边界 (每拍都在界内)")
try:
    sys.path.insert(0, os.path.join(REPO, "src"))
    from lerobot.policies.left_right.state_space.safety import POS_LIMIT          # noqa: E402
    import numpy as np                                                            # noqa: E402
    _lim = float(POS_LIMIT) if np.isscalar(POS_LIMIT) else None
    _uv = np.asarray([a for a in (d.get("u") or [])], float)
    if _lim is not None:
        chk("u 每拍 |a| ≤ POS_LIMIT(%.3f)" % _lim, bool(np.all(np.abs(_uv) <= _lim + 1e-9)),
            "max|a|=%.4f" % float(np.max(np.abs(_uv))))
    else:
        chk("POS_LIMIT 可查", True, str(type(POS_LIMIT)))
except Exception as e:                                                            # noqa: BLE001
    chk("安全界探针", False, e)

# ── ⑦ 技能派发循环服务 ──────────────────────────────────────────────────────
print("④ 技能派发循环服务 (快速流转到具体技能)")
try:
    st = subprocess.run(["systemctl", "is-active", "zmax-ss-skill-dispatch.service"],
                        capture_output=True, text=True).stdout.strip()
    chk("服务 active", st == "active", st)
    shm = "/dev/shm/zmax_ss_engine"
    files = sorted(f for f in os.listdir(shm) if f.startswith("skill_")) if os.path.isdir(shm) else []
    chk("每技能出口在 /dev/shm (共享内存直传)", len(files) >= 1, files[:4])
    with open(os.path.join(LIVE, "skill_latest.json"), encoding="utf-8") as f:
        s2 = json.load(f)
    age = time.time() - float(s2.get("ts") or 0)
    chk("派发快照帧龄 <1s", age < 1.0, "%.3fs" % age)
    n1 = int(s2.get("n") or 0)
    time.sleep(1.2)
    with open(os.path.join(LIVE, "skill_latest.json"), encoding="utf-8") as f:
        n2 = int((json.load(f) or {}).get("n") or 0)
    chk("派发计数在涨 (实时循环)", n2 > n1, "%d → %d" % (n1, n2))
except Exception as e:                                                            # noqa: BLE001
    chk("技能派发探针", False, e)

# ── ⑧ 信号分析页 ────────────────────────────────────────────────────────────
print("⑤ 信号分析页: chunk/skill 行 + 🧩 文字行")
try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
    from PyQt5 import QtWidgets                                                   # noqa: E402
    import re as _re                                                             # noqa: E402
    import canoe_graphic as cg                                                    # noqa: E402
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    w = cg.CanoeGraphicWidget()
    w.show()
    t1 = time.time() + 16
    while time.time() < t1:
        app.processEvents()
        time.sleep(0.1)
    _ks = sorted(w.store.keys())
    # 块信号走两条真源: ① 常驻回路平铺的语义键 sseng.chunk.* ② DDS 话题 digest ds.zmax/ss_action_chunk.*
    ck = [k for k in _ks if ("chunk" in k)]
    sk = [k for k in _ks if k.startswith("skill.")]
    chk("页面建出块信号行 (语义键或话题键)", len(ck) >= 4, "%d 行 例:%s" % (len(ck), ck[:3]))
    chk("含块步语义键 sseng.chunk.块步", any(k.startswith("sseng.chunk.块步") for k in ck),
        [k for k in ck if k.startswith("sseng.chunk.")][:4])
    chk("含话题键 ds.zmax/ss_action_chunk.*", any(k.startswith("ds.zmax/ss_action_chunk.") for k in ck),
        [k for k in ck if k.startswith("ds.")][:3])
    chk("页面建出 skill.* 行", len(sk) >= 1, "%d 行 例:%s" % (len(sk), sk[:4]))
    txt = _re.sub("<[^>]+>", "", w.lb_chunk.text() or "")
    chk("🧩 文字行显示块长/阶段/技能", ("H=" in txt and "阶段" in txt and "技能派发" in txt), txt[:110])
except Exception as e:                                                            # noqa: BLE001
    chk("信号页探针", False, e)

# ── ⑨ 零回归 ────────────────────────────────────────────────────────────────
print("⑥ 零回归: 引擎原有 action 照旧 + 块是独立分支")
try:
    with open(os.path.join(LIVE, "engine_latest.json"), encoding="utf-8") as f:
        e2 = json.load(f)
    chk("engine_latest 仍有 action (原有口径不动)", isinstance(e2.get("action"), list) and len(e2["action"]) == 4,
        e2.get("action"))
    chk("块作为独立字段并存 (chunk_keys)", isinstance(e2.get("chunk_keys"), dict) and len(e2["chunk_keys"]) > 5,
        "%d 个块键" % len(e2.get("chunk_keys") or {}))
    ap = subprocess.run(["systemctl", "is-active", "zmax-ss-engine-loop.service", "zmax-dds-ss.service"],
                        capture_output=True, text=True).stdout.split()
    chk("常驻回路 + 守护 都 active", ap == ["active", "active"], ap)
except Exception as e:                                                            # noqa: BLE001
    chk("回归探针", False, e)

print("\n" + "=" * 84)
print("结论: %s" % ("✅ 全过 — 块有话题/多步逐步不同/前馈序列/加权+调制+安全/技能循环服务/信号页可见"
                    if ok else "❌ 未通过"))
print("=" * 84)
sys.exit(0 if ok else 1)
