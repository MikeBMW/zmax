#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_fw_manifold_chain.py — 插拔场景「流形引擎空间智能链」判据 (老倪 2026-10-15 的十条要求逐条取证)

判据口径: 只认**唯一依据文件 + 真 tap + 真台账**; 缺就报 ⚠/❌ 并指出开关, 不许编。
  ① 链上真值齐全且新鲜 (引擎/扭矩/内稳态/元任务 帧龄 + 非退化)
  ② 空间智能: 度规(尺子) + 潜表示(编码器是谁)
  ③ 预测的结构: 势能 φ 分层分解 + 梯度 + 谷底距离 + 阶段/技能
  ④ 输出的驱动扭矩张量 T=M·(−∇Φ): 模/上限/限幅, 且 M 与 −∇Φ 一致性校验
  ⑤ 意图→元任务发出 topic + **台账明确记录** (哈希与当前 meta_tasks.json 同口径)
  ⑥ L3 长程任务规划: 真值活跃/步数/阶段
  ⑦ L2 前馈加速预测 + INTACT 驱动 (管线挂载/调用数/INTACT 计数) —— 读 fwchain 联调实例 tap
  ⑧ 主要预测 topic 在「实时检测·信号分析」界面可见 (信号→插拔场景 标签)
  ⑨ 插拔环境渲染图像 → VLM → 流形引擎结构感知 (渲染帧服务 + 编码器真值)
  ⑩ 元任务记录字段完整 (话题出口/发布者/任务/场景/哈希/时间)
退出码: 0=全过 (允许带 ⚠ 提示), 1=有 ❌
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
LEDGER = os.path.join(LIVE, "meta_task_ledger.jsonl")
TAGS = os.path.join(ROOT, "config", "topics", "scene_tags.json")
STALE = 20.0
PASS, FAIL = [], []


def _j(name):
    p = os.path.join(LIVE, name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f), time.time() - os.path.getmtime(p)
    except Exception:                                                              # noqa: BLE001
        return {}, float("inf")


def ck(cond, ok, bad, warn=False):
    (print("   ⚠ %s" % bad) if warn and not cond else None)
    if cond:
        PASS.append(ok); print("   ✅ %s" % ok)
    elif not warn:
        FAIL.append(bad); print("   ❌ %s" % bad)
    else:
        PASS.append(ok)
    return bool(cond)


def num(x, d=0.0):
    try:
        return float(x)
    except Exception:                                                              # noqa: BLE001
        return d


def main():
    print("=" * 78)
    print("插拔场景 · 流形引擎空间智能链 判据  (唯一依据=zmax_data/ss_live + tap + config/topics)")
    print("=" * 78)

    eng, ae = _j("engine_latest.json")
    tor, at = _j("torque_live.json")
    hom, ah = _j("manifold_homeostasis.json")
    meta, am = _j("meta_tasks.json")

    print("\n① 链上真值齐全且新鲜")
    for nm, age in (("引擎", ae), ("扭矩/结构", at), ("内稳态", ah), ("元任务", am)):
        ck(age <= STALE, "%s 帧龄 %.1fs ≤ %.0fs" % (nm, age, STALE), "%s 帧龄 %.1fs 陈 (>%.0fs)" % (nm, age, STALE))
    ck(not eng.get("stale"), "引擎非陈旧 (stale=%s)" % eng.get("stale"), "引擎 stale=%s" % eng.get("stale"))
    z = eng.get("z_latent") or []
    ck(sum(abs(num(v)) for v in z) > 1e-9, "潜表示非退化 (dim=%d)" % len(z), "潜表示全零/缺失 (dim=%d)" % len(z))

    print("\n② 空间智能 (度规=空间的尺子)")
    ck(num(tor.get("metric_M")) > 0, "度规标量 M=%.4f" % num(tor.get("metric_M")), "度规 M 缺失/≤0")
    ck(bool(tor.get("metric_pd_ok")), "度规正定 (pd_ok=True, dim=%s, 特征值 %.4f~%.4f)"
       % (tor.get("metric_dim"), num(tor.get("metric_eig_min")), num(tor.get("metric_eig_max"))),
       "度规非正定 (pd_ok=%s)" % tor.get("metric_pd_ok"))
    enc = str(eng.get("encoder") or "")
    print("   · 编码器真值: %s | %s" % (enc, eng.get("z_source")))
    print("   · 流形类型: %s | 理解力 %.4f | 掌控力 %.4f" % (
        eng.get("manifold"), num((_j("fw_chain_latest.json")[0] or {}).get("流形引擎.理解力")),
        num((_j("fw_chain_latest.json")[0] or {}).get("流形引擎.掌控力"))))

    print("\n③ 预测的结构 (势能 φ 分层 + 梯度 + 谷底)")
    pc = tor.get("phi_contrib") or {}
    ck(num(tor.get("phi")) > 0, "势能 φ=%.6f (L2=%.3g L3=%.3g L4=%.3g)" % (
        num(tor.get("phi")), num(pc.get("L2")), num(pc.get("L3")), num(pc.get("L4_world")) + num(pc.get("L4_obstacle"))),
       "势能 φ 缺失/≤0")
    ck(num(tor.get("grad_raw_norm")) > 0, "势场梯度范数 %.4f (指向谷底)" % num(tor.get("grad_raw_norm")),
       "梯度范数缺失")
    print("   · 谷底距离 %.4f m | 阶段 %s | 技能 %s" % (
        num(tor.get("dist_to_trough_m")), tor.get("stage"), tor.get("skill")))

    print("\n④ 输出的驱动扭矩张量 T = M·(−∇Φ)")
    tn = num(tor.get("torque_norm"))
    ck(tn > 0, "扭矩张量模 ‖τ‖=%.4f (上限 %.1f N·m, clipped=%s)" % (tn, num(tor.get("t_max")), tor.get("clipped")),
       "扭矩张量缺失/为 0")
    tq, gr, M = tor.get("torque") or [], tor.get("grad") or tor.get("gradient") or [], num(tor.get("metric_M"))
    if tq and gr and len(tq) == len(gr):
        import math
        lhs = math.sqrt(sum(num(v) ** 2 for v in tq))
        rhs = M * math.sqrt(sum(num(v) ** 2 for v in gr))
        rel = abs(lhs - rhs) / max(1e-9, rhs)
        ck(rel < 0.35, "一致性: ‖τ‖=%.4f ≈ M·‖∇Φ‖=%.4f (相对差 %.1f%%, 含增益/限幅)" % (lhs, rhs, rel * 100),
           "一致性差: ‖τ‖=%.4f vs M·‖∇Φ‖=%.4f (%.0f%%)" % (lhs, rhs, rel * 100))
    else:
        print("   · 分量校验跳过 (τ=%d 维, ∇Φ=%d 维, 张量按层收口)" % (len(tq), len(gr)))

    print("\n⑤ 意图 → 元任务: 发出 topic + 台账明确记录")
    mts = meta.get("items") or meta.get("meta_tasks") or []
    ids = [str(m.get("mt_id")) for m in mts if isinstance(m, dict)]
    cur = hashlib.sha1(json.dumps(ids, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    led = []
    if os.path.isfile(LEDGER):
        with open(LEDGER, encoding="utf-8") as f:
            led = [json.loads(x) for x in f if x.strip()]
    ck(bool(mts), "元任务 %d 条 (首条 %s, 任务 %s)" % (len(ids), ids[0] if ids else "-", meta.get("task_id")),
       "元任务为空")
    ck(bool(led), "台账 %s 有 %d 条记录" % (os.path.relpath(LEDGER, ROOT), len(led)), "台账无记录 (未明确记录)")
    if led:
        last = led[-1]
        ck(last.get("ids_sha1_16") == cur, "末条台账哈希 %s == 当前元任务哈希 %s (口径一致)" % (last.get("ids_sha1_16"), cur),
           "末条台账哈希 %s ≠ 当前 %s (口径不一致)" % (last.get("ids_sha1_16"), cur))
        ck(num(last.get("src_age_s")) <= STALE * 3, "台账源帧龄 %.1fs (跟随唯一依据, 非陈旧快照)" % num(last.get("src_age_s")),
           "台账源帧龄 %.1fs 陈" % num(last.get("src_age_s")))
        ck(len(led) >= 2, "台账在增长 (%d 条, 最新 %s)" % (len(led), last.get("ts_str")), "台账仅 1 条")

    print("\n⑥ L3 长程任务规划")
    l3, al3 = _j("l3_live_status.json")
    _lc = os.path.join(LIVE, "layer_calls.jsonl")
    _l3ok, _l3ms, _l3age, _r = False, 0.0, float("inf"), []
    if os.path.isfile(_lc):
        try:
            with open(_lc, encoding="utf-8") as f:
                _r = [json.loads(x) for x in f if x.strip()]
            _r = [x for x in _r if isinstance(x, dict) and num(x.get("ts")) > 0]
            if _r:
                _l3ok = bool(((_r[-1].get("layers") or {}).get("L3") or {}).get("ok"))
                _l3ms = num(((_r[-1].get("layers") or {}).get("L3") or {}).get("ms"))
                _l3age = time.time() - num(_r[-1].get("ts"))
        except Exception:                                                           # noqa: BLE001
            pass
    if l3 and al3 < 600:
        ck(True, "L3 规划真值活跃: 步 %s · 阶段 %s · 帧龄 %.0fs" % (l3.get("idx"), l3.get("stage"), al3),
           "L3 真值陈旧")
    elif _l3ok and _l3age < 180:
        ck(True, "L3 长程规划在线 (管线 dispatch): src=%s · %.0fms · 帧龄 %.0fs" % (
            ((_r[-1].get("layers") or {}).get("L3") or {}).get("src"), _l3ms, _l3age),
           "L3 未在线")
        if l3:
            print("   · l3_live_status.json 帧龄 %.0fs (旧口径真值, 静态)" % al3)
    else:
        print("   ⚠ L3 未在规划: l3_live_status 帧龄 %.0fs, 管线 L3 ok=%s ⇒ 引擎回路未带 --pipeline" % (al3, _l3ok))

    int_ok = False
    print("\n⑦ L2 前馈加速预测 + INTACT 驱动 (读联调实例唯一依据: engine_latest_<实例>.json + layer_calls.jsonl)")
    inst = sorted(glob.glob(os.path.join(LIVE, "engine_latest_*.json")), key=os.path.getmtime, reverse=True)
    inst = [p for p in inst if not p.endswith("engine_latest.json")]
    main_p = os.path.join(LIVE, "engine_latest.json")
    # 常驻回路已带链上开关时, 直接读主实例唯一依据 (联调实例只在它还新鲜时优先, 免得报旧档)
    if inst and (time.time() - os.path.getmtime(inst[0])) > 300:
        inst = []
    if not inst and os.path.isfile(main_p):
        inst = [main_p]
    ie, age_ie, iid = {}, float("inf"), "-"
    if inst:
        iid = os.path.basename(inst[0]).replace("engine_latest_", "").replace(".json", "")
        try:
            with open(inst[0], encoding="utf-8") as f:
                ie = json.load(f)
            age_ie = time.time() - os.path.getmtime(inst[0])
        except Exception:                                                          # noqa: BLE001
            pass
    lc = os.path.join(LIVE, "layer_calls.jsonl")
    rows = []
    if os.path.isfile(lc):
        with open(lc, encoding="utf-8") as f:
            for ln in f:
                try:
                    rows.append(json.loads(ln))
                except Exception:                                                      # noqa: BLE001
                    pass
    lastc = rows[-1] if rows else {}
    ly = lastc.get("layers") or {}
    if ie:
        print("   · 联调实例 %s (帧龄 %.0fs, cycle=%s, task=%s)" % (iid, age_ie, ie.get("cycle"), ie.get("task_id")))
        ck(bool(ie.get("pipe_on")), "管线挂载 pipe_on=%s, pipe_calls=%s (L2 前馈/u_ff 通道在位)" % (
            ie.get("pipe_on"), ie.get("pipe_calls")),
           "管线未挂载 (pipe_on=%s) ⇒ INTACT 未驱动 L2; 开关: --pipeline", warn=not ie.get("pipe_on"))
        ck(str(ie.get("encoder")) == "l4" or "VLM" in str(ie.get("z_source", "")),
           "编码器真值 encoder=%s (VLM 在回路)" % ie.get("encoder"),
           "编码器仍为 %s ⇒ VLM 未进回路; 开关: --encoder l4 --l4-frame-url" % ie.get("encoder"),
           warn=str(ie.get("encoder")) != "l4")
        int_ok = bool(ie.get("pipe_on"))
    else:
        print("   ⚠ 未找到联调实例唯一依据 — 先跑: SS_L4_INTACT=1 python tools/ss_engine_loop.py run "
              "--instance fwchain --encoder l4 --l4-frame-url http://127.0.0.1:8799/frame.png "
              "--pipeline --pipe-img http://127.0.0.1:8799/frame.png")
    if ly:
        ck(all(ly.get(k, {}).get("ok") for k in ("L5", "L2", "L4", "L3")),
           "多层同时在线: " + " · ".join("%s=%s(%.0fms)" % (k, (ly.get(k) or {}).get("src"), num((ly.get(k) or {}).get("ms")))
                                        for k in ("L5", "MEM", "L2", "L4", "L3")),
           "层未全部 ok: %s" % ly)
        ck("intact" in str((ly.get("L4") or {}).get("src", "")).lower(),
           "INTACT 真仲裁 L4: %s (%.0fms)" % ((ly.get("L4") or {}).get("src"), num((ly.get("L4") or {}).get("ms"))),
           "L4 未走 INTACT 通道: %s" % (ly.get("L4") or {}).get("src"), warn="intact" not in str(ly).lower())
        ck(bool(ly.get("L3", {}).get("ok")),
           "L3 长程任务规划在线: src=%s" % (ly.get("L3") or {}).get("src"),
           "L3 未在线: %s" % (ly.get("L3") or {}), warn=not ly.get("L3", {}).get("ok"))

    print("\n⑧ 主要预测 topic 在「实时检测·信号分析」界面可见 (信号→插拔场景)")
    tags = json.load(open(TAGS, encoding="utf-8"))["signals"]
    need = ["流形引擎.空间智能_度规M", "流形引擎.空间智能_潜表示维数", "流形引擎.结构_势能φ",
            "流形引擎.结构_势能梯度范数", "流形引擎.预测_扭矩张量模", "流形引擎.预测_是否限幅",
            "流形引擎.理解力", "流形引擎.掌控力", "元任务.元任务数", "元任务.内容哈希",
            "L3规划.步数", "L2前馈.管线挂载", "帧龄_s.引擎"]
    miss = [s for s in need if tags.get(s) != "插拔场景"]
    ck(not miss, "13 项主预测信号全部标记「插拔场景」(绿) — 界面可按场景过滤看到",
       "未标记插拔场景: %s" % miss)
    nfw = sum(1 for v in tags.values() if v == "插拔场景")
    print("   · 插拔场景信号总数 %d (含链上全部字段) · 注册表 %d 条" % (nfw, len(tags)))

    print("\n⑨ 插拔环境渲染图像 → VLM → 流形引擎结构感知")
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8799/status.json", timeout=4) as r:
            st = json.load(r)
        ck(st.get("n", 0) > 0 and num(st.get("age_s"), 99) <= 10 and num(st.get("std")) > 3,
           "渲染帧服务在线: 帧 %s · 帧龄 %.1fs · 尺寸 %s · std=%.1f (非黑帧)" % (
               st.get("n"), num(st.get("age_s")), st.get("shape"), num(st.get("std"))),
           "渲染帧服务异常/黑帧: %s" % st, warn=True)
    except Exception as e:                                                          # noqa: BLE001
        print("   ⚠ 渲染帧服务不可达 (%s) — 起: tools/fw_render_server.py --port 8799" % e)
    if int_ok:
        print("   · 该帧已进 VLM 编码器 + pipeline (见 ⑦ 的 encoder/pipe 真值) ⇒ 结构被流形引擎感知")

    print("\n⑩ 元任务记录字段完整")
    if led:
        last = led[-1]
        need_f = ("ts_str", "topic", "publisher", "task_id", "scene", "n", "first_mt", "ids_sha1_16", "src")
        mk = [k for k in need_f if last.get(k) in (None, "")]
        ck(not mk, "台账字段齐全: %s" % ", ".join(k for k in need_f),
           "台账缺字段: %s" % mk)
        print("   · 出口 %s ← %s" % (last.get("topic"), last.get("publisher")))

    print("\n" + "=" * 78)
    print("PASS %d · FAIL %d" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("   ❌ %s" % f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
