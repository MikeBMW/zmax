#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚡ 判据: 力场上显示的 L2~L5 力 = trace 话题 zmax/ss_force_l2..l5 (逐位对账)

老倪 2026-10-19: 「L2~L5 力的输出, 在力场上显示的力, 都做到 trace 的 topic;
                  L4 的 Tx 是流形引擎, L3 的 Tx 是 DiT, L2 的 Tx 是前馈加速器」

判据 (全绿才算通过):
  ① 四条话题都真的在发 (每条 ≥1 帧)
  ② 每帧 layer / tx 与口径表一致 (tx = 力的产生端)
  ③ x/y/z/mag/raw_mag/w/k 与 tools/layer_forces.py 的**同一份**加权结果逐位相等 (tol 1e-9)
  ④ src 非空 (能追到真源文件.字段)
  ⑤ 帧龄/新鲜度如实: fresh 与 age_s 必须能对上 layer_forces 的 fresh/age_s

用法:
  python3 tools/verify_layer_force_topics.py            # 自动起一个 4s 的 daemon 发布端做取证
  python3 tools/verify_layer_force_topics.py --live     # 不发, 只收常驻 zmax-dds-ss 的帧
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dds"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("CYCLONEDDS_URI", "file://%s/dds/cyclonedds_unicast.xml" % ROOT)

import layer_forces as LF                                                   # noqa: E402
import gravity_law as GL                                                    # noqa: E402
from zmax_node import Node                                                  # noqa: E402

LAYERS = (("L2", "ss_force_l2", "前馈加速器"),
          ("L3", "ss_force_l3", "DiT 动作头"),
          ("L4", "ss_force_l4", "流形引擎"),
          ("L5", "ss_force_l5", "DeepSeek VL 场景理解"))
TOL = 1e-9


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="只收常驻守护的帧, 不自己起发布端")
    ap.add_argument("--seconds", type=float, default=4.0)
    a = ap.parse_args()

    exp = LF.layer_forces()
    gf = GL.field({L: (exp.get(L) or {}).get("vec") for L, _t, _x in LAYERS})
    comps = {c.get("L"): c for c in (gf.get("comps") or [])}
    print("📌 期望口径 = 力场格子 (layer_forces 加权张量 → gravity_law |F|=G·M/r²)")
    node = Node("force_verify", domain=0)
    for _l, t, _x in LAYERS:
        node.sub(t)
    print("📡 已订阅 %s" % ", ".join("zmax/" + t for _l, t, _x in LAYERS))

    proc = None
    if not a.live:
        # 等发现/配对, 再起发布端 (BEST_EFFORT 不重发历史 ⇒ 先有读者再发)
        time.sleep(1.0)
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "tools", "dds", "ss_daemon.py"),
             "--seconds", str(a.seconds)],
            cwd=ROOT, env=dict(os.environ, ZMAX_REPO=ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    got = {}
    t0 = time.time()
    while time.time() - t0 < a.seconds + 1.0:
        for _l, t, _x in LAYERS:
            for m in (node.take(t, timeout=0.2) or []):
                # 同层多条只留最后一条 (最新一拍)
                got[t] = m
        if len(got) == len(LAYERS):
            break
    if proc is not None:
        try:
            proc.wait(timeout=6)
        except Exception:                                                    # noqa: BLE001
            proc.kill()

    ok, fail = [], []

    def chk(cond, msg):
        (ok if cond else fail).append(msg)

    for L, t, tx in LAYERS:
        m = got.get(t)
        if m is None:
            fail.append("① %s: 一帧都没收到 (发布端没发 / 没配对)" % t)
            continue
        ok.append("① %s 收到帧 seq=%s" % (t, getattr(m, "seq", None)))
        chk(str(getattr(m, "layer", "")) == L, "② %s layer=%r (期望 %r)" % (t, getattr(m, "layer", ""), L))
        chk(str(getattr(m, "tx", "")) == tx, "② %s tx=%r (期望 %r)" % (t, getattr(m, "tx", ""), tx))
        e = exp.get(L) or {}
        c = comps.get(L) or {}
        ev = c.get("vec")
        if not ev:
            fail.append("③ %s: 力场当前没有该层力 (comps 缺; 此刻应有, 说明取数条件变了)" % t)
            continue
        for nm, j in (("x", 0), ("y", 1), ("z", 2)):
            chk(abs(float(getattr(m, nm)) - float(ev[j])) <= TOL,
                "③ %s.%s=%.12g vs 力场格子 %.12g" % (t, nm, float(getattr(m, nm)), float(ev[j])))
        chk(abs(float(m.mag) - float(c.get("mag") or 0.0)) <= TOL,
            "③ %s.mag=%.12g vs 力场 |F| %.12g (G·M/r²)" % (t, float(m.mag), float(c.get("mag") or 0.0)))
        chk(abs(float(m.raw_mag) - float(e.get("mag") or 0.0)) <= TOL,
            "③ %s.raw_mag=%.12g vs 引力律前加权幅值 %.12g" % (t, float(m.raw_mag), float(e.get("mag") or 0.0)))
        chk(abs(float(m.w) - float(e.get("w") or 0.0)) <= TOL, "③ %s.w=%s vs %s" % (t, m.w, e.get("w")))
        chk(abs(float(m.k) - float(e.get("k") or 0.0)) <= TOL, "③ %s.k=%s vs %s" % (t, m.k, e.get("k")))
        chk(bool(str(getattr(m, "src", "")).strip()), "④ %s.src 非空: %s" % (t, str(m.src)[:60]))
        chk("引力律" in str(getattr(m, "note", "")),
            "④ %s.note 标明引力律口径: %s" % (t, str(m.note)[-60:]))
        chk(int(getattr(m, "fresh", -1)) == (1 if e.get("fresh") else 0),
            "⑤ %s.fresh=%s vs %s" % (t, m.fresh, 1 if e.get("fresh") else 0))
        ea = e.get("age_s")
        want = float(ea) if ea is not None else -1.0
        chk(abs(float(m.age_s) - want) <= max(1.5, abs(want) * 0.05) if want >= 0 else float(m.age_s) < 0,
            "⑤ %s.age_s=%s vs %s (±5%%/1.5s)" % (t, m.age_s, ea))

    for x in ok:
        print("  ✅ " + x)
    for x in fail:
        print("  ❌ " + x)
    print("\n%s  %d 通过 / %d 失败" % ("🟢 PASS" if not fail else "🔴 FAIL", len(ok), len(fail)))
    if not fail:
        print("   口径: tx = " + " · ".join("%s:%s" % (L, tx) for L, _t, tx in LAYERS))
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
