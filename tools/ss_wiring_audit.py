#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_wiring_audit.py — 状态空间「所有模型是否真在链上」的一次性取证 (只读)

判据分两类, 不许混:
  · 在链 (wired)  = 有实时输出文件在刷新 **且** 引擎/管线的逐层调用台账里有它 (layer_calls.jsonl)
  · 离线/未接 (off)= 文件陈旧、调用计数为 0、或回退到内建 PCA ⇒ 如实标「未打通」

输出: reports/ss_wiring/<ts>.json|md  (给验收/大屏引用)
用法: python tools/ss_wiring_audit.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import time

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
SS = os.path.join(ROOT, "zmax_data/ss_live")
LAYERS = os.path.join(SS, "layer_calls.jsonl")

# 模型/节点 → 证据文件 (None 表示证据来自 layer_calls 的层名)
WIRED = {
    "L5 规划器 (planner.rules / taskplanner)": ("L5", None),
    "记忆层 (memory.json 五层记忆)": ("MEM", None),
    "L2 检测器 (yolo_peg_live / yolo_ar_peg)": ("L2", os.path.join(ROOT, "zmax_data/ss_bypass/yolo_detections.json")),
    "L4 世界模型 (INTACT-JEPA, vote)": ("L4", None),
    "L3 执行分发 (dispatch.k_act)": ("L3", None),
}


def age(p: str):
    try:
        return round(time.time() - os.path.getmtime(p), 1)
    except OSError:
        return None


def last_layer_call():
    try:
        with open(LAYERS, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 20000))
            tail = f.read().decode("utf-8", "replace").strip().splitlines()
        return json.loads(tail[-1]) if tail else None
    except Exception:                                                        # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    ts = time.strftime("%Y%m%d_%H%M%S")
    eng = {}
    try:
        eng = json.load(open(os.path.join(SS, "engine_latest.json"), encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        pass
    lc = last_layer_call()
    layers = (lc or {}).get("layers") or {}
    rows = []
    for name, (key, extra) in WIRED.items():
        L = layers.get(key) or {}
        ok = bool(L.get("ok"))
        row = {"model": name, "layer": key, "ok": ok,
               "src": L.get("src"), "ms": L.get("ms"), "n": L.get("n"), "conf": L.get("conf"),
               "layer_calls_ts": (lc or {}).get("ts_str"), "pipe_calls": (lc or {}).get("pipe_calls")}
        if extra:
            row["evidence_file"] = os.path.relpath(extra, ROOT)
            row["age_s"] = age(extra)
        if not ok:
            row["verdict"] = "未打通 (本次逐层台账里没有 ok=True)"
        elif extra and (row.get("age_s") is None or row["age_s"] > 120):
            row["verdict"] = "文件陈旧 (age=%ss)" % row.get("age_s")
            row["ok"] = False
        else:
            row["verdict"] = "在链 (真调用 %sms, 输出 n=%s)" % (L.get("ms"), L.get("n"))
        rows.append(row)

    # 引擎级: L4 潜表示是否为真 VLM 编码 (不是 PCA 回退)
    zsrc = str(eng.get("z_source") or "")
    latent_real = ("PCA" not in zsrc) and bool(eng.get("z_latent"))
    rows.append({"model": "L4 潜表示 (引擎 z_source → 16 维流形)", "layer": "z",
                 "ok": latent_real, "src": zsrc[:160],
                 "verdict": "真 VLM 编码" if latent_real else "回退内建 PCA (未打通)",
                 "engine_cycle": eng.get("cycle")})

    # 引擎级: SE(3) 7 维位姿预测 (6 维 ξ → 群指数 → 7 数)
    sp = eng.get("se3_pose") or {}
    if sp:
        ok_sp = bool(sp.get("ok")) and len(sp.get("pose7_pred") or []) == 7
        verdict = ("在链 · 7 数 ‖q‖=%.6f · 1步残差 %s" % (
            float(sp.get("quat_norm") or 0),
            json.dumps(sp.get("residual_1step") or sp.get("residual") or "未产生", ensure_ascii=False))
            if ok_sp else ("守卫生效 (未编数据): %s" % str(sp.get("why") or "未出数")[:80]))
    else:
        ok_sp, verdict = False, "未接 (SE3_POSE_HEAD=0)"
    rows.append({"model": "SE(3) 7 维位姿预测 (6维ξ→指数映射)", "layer": "se3_pose",
                 "ok": ok_sp, "src": sp.get("mode", ""), "n": len(sp.get("pose7_pred") or []),
                 "verdict": verdict, "na": (not bool(sp))})

    # 引擎级: 动作块 / 扭矩
    ch = eng.get("chunk") or {}
    rows.append({"model": "L3 动作块 (chunk → 执行口)", "layer": "chunk", "ok": bool(ch),
                 "n": len(ch) if isinstance(ch, (list, dict)) else 0,
                 "verdict": "有块" if ch else "无块"})
    gt = os.path.join(SS, "gravity_trace.json")
    # 发布器有**任务闸** (TASK_OK): 只对插拔 FW 任务发, 换场景时刻意不发 (场景色标不能乱标)。
    # 所以必须区分「闸住了(设计如此)」与「坏了」, 不能一律算未打通。
    task_ok, active = "TASK-01-FW", "?"
    try:
        for ln in open(os.path.join(ROOT, "tools/gravity_trace_pub.py"), encoding="utf-8"):
            if ln.startswith("TASK_OK"):
                task_ok = ln.split("=")[1].split("#")[0].strip().strip('"\'')
                break
    except OSError:
        pass
    try:
        active = json.load(open(os.path.join(ROOT, "config/ss_task_binding.json"),
                                encoding="utf-8")).get("active_task") or "?"
    except Exception:                                                        # noqa: BLE001
        pass
    fresh = age(gt) is not None and age(gt) < 120
    gated = not str(active).startswith(task_ok)
    rows.append({"model": "万有引力表力信号 (gravity_trace)", "layer": "gravity",
                 "ok": fresh or gated, "age_s": age(gt), "gated": gated, "task_gate": task_ok,
                 "active_task": active, "na": gated and not fresh,
                 "verdict": ("在刷" if fresh else
                             ("任务闸: 只发 %s*, 当前 %s ⇒ 刻意不发 (设计如此, 非故障)" % (task_ok, active)
                              if gated else "陈旧/未刷"))})

    wired = sum(1 for r in rows if r.get("ok") and not r.get("na"))
    na = sum(1 for r in rows if r.get("na"))
    doc = {"ts": ts, "wired": wired, "na_gated": na, "total": len(rows) - na, "engine_cycle": eng.get("cycle"),
           "layer_calls": {"ts": (lc or {}).get("ts_str"), "pipe_calls": (lc or {}).get("pipe_calls"),
                           "ms": (lc or {}).get("ms")},
           "rows": rows}
    od = os.path.join(ROOT, "reports", "ss_wiring")
    os.makedirs(od, exist_ok=True)
    jp = a.json or os.path.join(od, ts + ".json")
    json.dump(doc, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = ["# 状态空间模型打通审计 · %s" % ts, "",
          "在链 **%d/%d** (另有 %d 项受任务闸, 不计入) · 引擎周期 %s · 逐层台账 %s (calls %s, %.1fms)"
          % (wired, len(rows) - na, na, eng.get("cycle"), (lc or {}).get("ts_str"),
             (lc or {}).get("pipe_calls"), float((lc or {}).get("ms") or 0)), "",
          "| 模型 | 在链 | 证据 | 判定 |", "|---|---|---|---|"]
    for r in rows:
        md.append("| %s | %s | %s | %s |" % (
            r["model"], "—" if r.get("na") else ("✅" if r.get("ok") else "❌"),
            ("%s → %sms n=%s" % (r.get("src"), r.get("ms"), r.get("n"))) if r.get("layer") in layers
            else str(r.get("src") or r.get("age_s") or "")[:60], r.get("verdict")))
    mp = os.path.join(od, ts + ".md")
    open(mp, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))
    print("\nJSON: %s\nMD: %s" % (jp, mp))
    return 0 if wired == len(rows) - na else 1


if __name__ == "__main__":
    raise SystemExit(main())
