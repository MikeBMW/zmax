#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_fw_chain.py — 插拔场景(TASK-01-FW/SCN-01-FW) · 流形引擎空间智能链 联合调试器

老倪 2026-10-15: 「配制成插拔场景, 自主进化… 你来对应实时监控的 topic, 保证流形引擎的空间智能、
预测的结构、输出的驱动扭矩张量, 能将这个意图解码成元任务, 进而进入 L3 长程任务规划、L2 前馈加速预测
的状态; 这些主要预测的 topic 都要在实时检测的分析界面看到/观察/验证; 信息连接是核心…
元任务要发出来 topic, 明确记录」

本工具做三件事 (**只读唯一依据 + 只追加记录, 不改任何既有产线链路**):
  ① 把**已在跑**的链上真值收齐成一条「空间智能链」记录 (每周期一行 jsonl):
     空间智能(度规/特征值) → 结构(势能/梯度/谷底) → 预测(驱动扭矩张量 M·(−∇Φ)) →
     意图→元任务(meta_tasks) → L3 长程规划 → L2 前馈 (INTACT 通道) → VLM/编码器感知来源
  ② 落「元任务发出」台账 `zmax_data/ss_live/meta_task_ledger.jsonl` (**明确记录**每次发出:
     时间/任务/场景/条数/首条ID/内容哈希/意图来源/发布出口), 与 zmax/ss_meta_task 同一份口径
  ③ 写运行产物 `zmax_data/task_runs/TASK-01-FW/chain_<ts>.jsonl` —— 给信号分析打标用
     (`tools/sig_scene_tags.py --build --from-runs` 按"真出现过的信号名"标到插拔场景=绿)

用法:
  ./gui-venv311/bin/python tools/ss_fw_chain.py --cycles 20 --hz 2        # 采 20 周期 (真值采样)
  ./gui-venv311/bin/python tools/ss_fw_chain.py --report                  # 只打当前一帧报告
  ./gui-venv311/bin/python tools/ss_fw_chain.py --selftest                # 判据自检
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
RUNS = os.path.join(ROOT, "zmax_data", "task_runs")
LEDGER = os.path.join(LIVE, "meta_task_ledger.jsonl")
OUT_LATEST = os.path.join(LIVE, "fw_chain_latest.json")
TASK = "TASK-01-FW"
SCENE = "SCN-01-FW"
STALE_S = 15.0                      # 采样链每周期落盘 ⇒ 15s 内算新鲜 (比拓扑 5s 宽, 比"一轮一份"紧)


def _load(name):
    p = os.path.join(LIVE, name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f), time.time() - os.path.getmtime(p)
    except Exception:                                                          # noqa: BLE001
        return {}, float("inf")


def _f(x, d=0.0):
    try:
        v = float(x)
        return v if math.isfinite(v) else d
    except Exception:                                                          # noqa: BLE001
        return d


def _norm(v):
    try:
        return math.sqrt(sum(_f(x) ** 2 for x in v))
    except Exception:                                                          # noqa: BLE001
        return 0.0


def chain_record():
    """收齐一帧「空间智能链」记录 (全部字段来自唯一依据文件, 缺就 null, 不补 0 凑数)。"""
    eng, age_eng = _load("engine_latest.json")
    tor, age_tor = _load("torque_live.json")
    hom, age_hom = _load("manifold_homeostasis.json")
    meta, age_meta = _load("meta_tasks.json")
    st, age_st = _load("engine_loop_status.json")

    mts = meta.get("items") or meta.get("meta_tasks") or []
    mt_ids = [str(m.get("mt_id")) for m in mts if isinstance(m, dict)]
    h = hashlib.sha1(json.dumps(mt_ids, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]

    tq = tor.get("torque") or []
    phi_c = tor.get("phi_contrib") or {}
    eig = [_f(tor.get("metric_eig_min")), _f(tor.get("metric_eig_max"))]
    eig_spread = (eig[1] / eig[0]) if eig[0] > 0 else None
    conf = eng.get("confidence")
    conf = float(conf) if isinstance(conf, (int, float)) else None
    gates = str(tor.get("gates") or "")

    # ── 两个如实定义的指标 (公式写在字段里, 供 UI 核对) ──
    # 理解力 (空间智能的"看懂"程度): 置信 × 度量各向异性合理度; 潜表示非退化 (范数>0) 才计分
    z = eng.get("z_latent") or []
    z_ok = 1.0 if _norm(z) > 1e-6 else 0.0
    struct_ok = 1.0 if (phi_c.get("phi_total") not in (None, 0)) else 0.0
    comprehension = None
    if conf is not None:
        comprehension = round(max(0.0, min(1.0, conf)) * z_ok * struct_ok, 4)
    # 掌控力 (能不能"拿住"全局): 各层闸门在位比例 × 势场朝谷底 (distance→0 越好) × 未被限幅折扣
    g_on = sum(1 for k in ("L2", "L3", "L4") if ("%s=1" % k) in gates)
    g_ratio = g_on / 3.0
    dist = _f(tor.get("dist_to_trough_m"))
    trough = 1.0 / (1.0 + 10.0 * abs(dist))
    clip = 0.6 if tor.get("clipped") else 1.0
    control = round(g_ratio * trough * clip, 4)

    rec = {
        "ts": time.time(), "ts_str": time.strftime("%F %T"),
        "task_id": eng.get("task_id") or st.get("task_id") or TASK,
        "task_name": eng.get("task_name") or "",
        "scene": SCENE,
        # ① 空间智能 (度规 = 空间的"尺子")
        "流形引擎.空间智能_流形类型": eng.get("manifold") or tor.get("manifold"),
        "流形引擎.空间智能_度规M": _f(tor.get("metric_M")),
        "流形引擎.空间智能_度规维数": _f(tor.get("metric_dim")),
        "流形引擎.空间智能_度规正定": bool(tor.get("metric_pd_ok")),
        "流形引擎.空间智能_特征值下限": eig[0], "流形引擎.空间智能_特征值上限": eig[1],
        "流形引擎.空间智能_各向异性": round(eig_spread, 3) if eig_spread else None,
        "流形引擎.空间智能_潜表示维数": len(z), "流形引擎.空间智能_潜表示范数": round(_norm(z), 4),
        "流形引擎.空间智能_编码器": eng.get("encoder") or "",
        "流形引擎.空间智能_编码来源": eng.get("z_source") or "",
        # ② 预测的结构 (势场/梯度/谷底)
        "流形引擎.结构_势能φ": _f(tor.get("phi")),
        "流形引擎.结构_势能_L2": _f(phi_c.get("L2")), "流形引擎.结构_势能_L3": _f(phi_c.get("L3")),
        "流形引擎.结构_势能_L4": _f(phi_c.get("L4_obstacle")) + _f(phi_c.get("L4_world")),
        "流形引擎.结构_势能梯度范数": _f(tor.get("grad_raw_norm")),
        "流形引擎.结构_谷底距离_m": dist,
        "流形引擎.结构_阶段": tor.get("stage") or "", "流形引擎.结构_技能": tor.get("skill") or "",
        # ③ 输出的驱动扭矩张量 T = M·(−∇Φ)
        "流形引擎.预测_扭矩张量模": _f(tor.get("torque_norm")),
        "流形引擎.预测_扭矩上限_Nm": _f(tor.get("t_max")),
        "流形引擎.预测_是否限幅": bool(tor.get("clipped")),
        "流形引擎.预测_扭矩增益": _f(tor.get("gain")),
        "流形引擎.理解力": comprehension, "流形引擎.掌控力": control,
        "流形引擎.内稳态_模式": hom.get("mode"), "流形引擎.内稳态_紧迫度": (hom.get("urgency") or {}),
        "流形引擎.内稳态_主导": hom.get("dominant"), "流形引擎.内稳态_动作增益": _f(hom.get("dominance_gain") or hom.get("gain") or eng.get("hom_gain")),
        # ④ 元任务 (意图解码 → 元任务)
        "元任务.元任务数": len(mts), "元任务.首条ID": (mt_ids[0] if mt_ids else ""),
        "元任务.内容哈希": h, "元任务.任务": meta.get("task_id") or "",
        # ⑤ L3 长程任务规划 (真值缺就 null, 不编)
        "L3规划.活跃": None, "L3规划.步数": None, "L3规划.当前阶段": None,
        # ⑥ L2 前馈加速预测 (INTACT/pipeline 通道)
        "L2前馈.管线挂载": bool(eng.get("pipe_on")), "L2前馈.管线调用数": eng.get("pipe_calls"),
        "L2前馈.闸门": gates,
        # ⑦ 帧龄 (诚实: 谁旧标谁)
        "帧龄_s.引擎": round(age_eng, 2), "帧龄_s.扭矩": round(age_tor, 2),
        "帧龄_s.内稳态": round(age_hom, 2), "帧龄_s.元任务": round(age_meta, 2),
    }
    # L3 真值 (有就读, 无就 null)
    l3, age_l3 = _load("l3_live_status.json")
    if l3:
        rec["L3规划.活跃"] = (time.time() - age_l3) < 60.0
        rec["L3规划.步数"] = l3.get("idx")
        rec["L3规划.当前阶段"] = l3.get("stage")
        rec["帧龄_s.L3"] = round(age_l3, 2)
    return rec


def publish_meta_task_ledger():
    """元任务发出 → 台账 (明确记录)。返回本次台账记录。"""
    meta, age = _load("meta_tasks.json")
    mts = meta.get("items") or meta.get("meta_tasks") or []
    ids = [str(m.get("mt_id")) for m in mts if isinstance(m, dict)]
    by_layer = {}
    for m in mts:
        if isinstance(m, dict):
            by_layer[str(m.get("layer"))] = by_layer.get(str(m.get("layer")), 0) + 1
    rec = {
        "ts": time.time(), "ts_str": time.strftime("%F %T"),
        "topic": "zmax/ss_meta_task", "publisher": "tools/dds/ss_daemon.py (5s 节拍, 与 ss_cfg_names 同出口)",
        "task_id": meta.get("task_id") or TASK, "scene": SCENE,
        "n": len(ids), "by_layer": by_layer, "first_mt": (ids[0] if ids else ""),
        "ids_sha1_16": hashlib.sha1(json.dumps(ids, ensure_ascii=False).encode("utf-8")).hexdigest()[:16],
        "src_age_s": round(age, 2),
        "src": "zmax_data/ss_live/meta_tasks.json ← tools/ss_meta_task.py (复用 export_meta_doc.build_meta_tasks)",
    }
    os.makedirs(LIVE, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=20)
    ap.add_argument("--hz", type=float, default=2.0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        r = chain_record()
        ok = (r["流形引擎.空间智能_度规正定"] is not False
              and (r["元任务.元任务数"] or 0) > 0
              and r["流形引擎.结构_势能φ"] > 0
              and r["流形引擎.预测_扭矩张量模"] > 0
              and r["流形引擎.理解力"] is not None)
        print("自检: 链记录字段齐全且非退化 =", ok)
        print(json.dumps({k: v for k, v in r.items() if k.startswith(("流形引擎.理解", "流形引擎.掌控", "元任务.", "L3规划."))},
                         ensure_ascii=False, indent=2)[:600])
        return 0 if ok else 1

    if a.report:
        print(json.dumps(chain_record(), ensure_ascii=False, indent=2))
        return 0

    run_dir = os.path.join(RUNS, TASK)
    os.makedirs(run_dir, exist_ok=True)
    rp = os.path.join(run_dir, "chain_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
    n_ok, led = 0, None
    dt = 1.0 / max(0.1, a.hz)
    for i in range(max(1, a.cycles)):
        rec = chain_record()
        with open(rp, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        with open(OUT_LATEST, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        if i % max(1, int(a.hz)) == 0:                     # 每秒发一条元任务台账 (与话题 5s 节拍同源)
            led = publish_meta_task_ledger()
        n_ok += 1
        if i < a.cycles - 1:
            time.sleep(dt)
    print("✅ 插拔场景空间智能链: %d 周期 → %s" % (n_ok, rp))
    print("✅ 元任务台账 (明确记录): %s  最近一条: %s"
          % (LEDGER, json.dumps(led or {}, ensure_ascii=False)[:200]))
    print(json.dumps(chain_record(), ensure_ascii=False, indent=2)[:1200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
