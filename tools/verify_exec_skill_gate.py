#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_exec_skill_gate.py — 真机下发收口「原子技能约束复核」判据 (离线, 不下发动作)

判据:
  ① 超限 ⇒ 降速 (抬起 请求 500mm/s ⇒ 削到技能允许值)
  ② 限内 ⇒ 原样放行 (不无端降速)
  ③ 允许值 = 该技能类常量独立算出的最小值 (不是硬编码, 不是拍脑袋)
  ④ 无阶段可判 ⇒ 明示跳过 (不静默假装管过)
  ⑤ 关闸 (ZMAX_EXEC_SKILL_GATE=0) ⇒ 与老口径逐位一致 (零回归)
  ⑥ 被削 ⇒ 取证落盘 (exec_skill_gate.jsonl 可回读)
"""
import importlib.util
import json
import os
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

ROWS = []


def ck(tag, name, ok, detail=""):
    ROWS.append((tag, ok, name, detail))
    print(("  ✅ " if ok else "  ❌ ") + "%s %s — %s" % (tag, name, detail))


def load_daemon():
    p = os.path.join(ROOT, "tools", "l2_daemon.py")
    spec = importlib.util.spec_from_file_location("zmax_l2_daemon_probe", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["zmax_l2_daemon_probe"] = m
    spec.loader.exec_module(m)
    return m


def main() -> int:
    L = load_daemon()
    SK = L._atomic_skills()
    cls = SK.skill_for("抬起")
    dt = float(getattr(cls, "DT_S", 0.1) or 0.1)
    # 段速硬闸 = min(顶速, 单拍位移/拍) —— 与 clamp 的 ①速度/①位移 同一口径;
    # a/jerk 是腿内斜坡, 只记 ramp_s, 不降速
    v_ref = min(x for x in (float(cls.V_CAP), float(cls.S_STEP) / dt) if x > 0)

    # ① 超限降速
    call = {"ros": "line_rel", "axis": "z_pos"}
    sp, info = L._skill_gate(call, speed=500.0)
    ck("①", "超限 ⇒ 降速 (请求 500mm/s)", bool(info.get("cut")) and abs(sp - v_ref * 1000) < 0.01,
       "→ %.2f mm/s · 瓶颈 %s" % (sp, info.get("bottleneck")))

    # ② 限内放行
    sp2, info2 = L._skill_gate(call, speed=round(v_ref * 1000 * 0.5, 3))
    ck("②", "限内 ⇒ 原样放行", (not info2.get("cut")) and abs(sp2 - round(v_ref * 1000 * 0.5, 3)) < 1e-6,
       "→ %.2f mm/s (未削)" % sp2)

    # ③ 真源一致
    ck("③", "允许值 = min(顶速, 单拍位移/拍) (真源常量)", abs(info["v_allow_mm_s"] - v_ref * 1000) < 0.01,
       "skill=%s v_allow=%.2f · 独立算=%.2f mm/s · 斜坡需 %.3fs (不降速)"
       % (info.get("skill"), info["v_allow_mm_s"], v_ref * 1000, info.get("ramp_s")))

    # ④ 无阶段跳过
    sp3, info3 = L._skill_gate({"ros": "no_such_ros"}, speed=500.0)
    ck("④", "无阶段 ⇒ 明示跳过", (not info3.get("applied")) and sp3 == 500.0
       and "跳过" in str(info3.get("why")), "why=%s" % info3.get("why"))

    # ⑤ 关闸零回归
    _bak = L._SKILL_GATE_ON
    L._SKILL_GATE_ON = False
    sp4, info4 = L._skill_gate(call, speed=500.0)
    L._SKILL_GATE_ON = _bak
    ck("⑤", "关闸 ⇒ 与老口径逐位一致 (500 不动)", sp4 == 500.0 and not info4.get("applied"),
       "why=%s" % info4.get("why"))

    # ⑥ 取证落盘
    logp = L._SKG_LOG
    n0 = sum(1 for _ in open(logp, encoding="utf-8")) if os.path.exists(logp) else 0
    L._skill_gate(call, speed=999.0)
    n1 = sum(1 for _ in open(logp, encoding="utf-8")) if os.path.exists(logp) else 0
    rec = {}
    if n1 > n0:
        rec = json.loads(open(logp, encoding="utf-8").read().strip().split("\n")[-1])
    ck("⑥", "被削 ⇒ 取证落盘可回读", n1 == n0 + 1 and rec.get("stage") == "抬起",
       "%s 新增1行 · 末行 stage=%s v=%.1f→%.1f" % (os.path.basename(logp), rec.get("stage"),
                                                   rec.get("from", 0), rec.get("v_allow_mm_s", 0)))

    # ⑦ 不传 arg 时按 call 自带速度复核 (chan_send 的多数调用点不传 speed ⇒ 必须能自取)
    sp5, info5 = L._skill_gate({"ros": "line_rel", "axis": "z_pos", "speed": 800.0})
    ck("⑦", "不传 arg ⇒ 按 call.speed 复核 (800→300)", bool(info5.get("cut"))
       and abs(sp5 - 300.0) < 0.01 and info5.get("src") == "call/env",
       "→ %.1f mm/s · src=%s" % (sp5, info5.get("src")))

    # ⑧ 收口处真挂了闸 (静态: chan_send 内有调用, 且在下发腿之前)
    src = open(os.path.join(ROOT, "tools", "l2_daemon.py"), encoding="utf-8").read()
    _i_ch = src.index("def chan_send(")
    _i_gate = src.find("_speed_gated, _skg = _skill_gate(", _i_ch)
    _i_leg = src.find("_bridge_send(call, target, quat, speed)", _i_ch)
    ck("⑧", "chan_send 收口真挂闸 (且在腿之前)", 0 < _i_gate < _i_leg,
       "闸位置 %s < 腿位置 %s" % (_i_gate, _i_leg))

    npass = sum(1 for r in ROWS if r[1])
    print("\n判据: PASS %d / FAIL %d   (审计计数 %s)" % (npass, len(ROWS) - npass, L._SKG))
    out = {"ok": npass == len(ROWS), "pass": npass, "total": len(ROWS), "v_ref_mm_s": v_ref * 1000,
           "rows": [{"tag": t, "ok": o, "name": n, "detail": d} for t, o, n, d in ROWS]}
    os.makedirs(os.path.join(ROOT, "zmax_data", "eval"), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, "zmax_data", "eval", "verify_exec_skill_gate.json"), "w"),
              ensure_ascii=False, indent=1)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
