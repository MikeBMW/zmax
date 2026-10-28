#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fullflow_status.py — 「7 任务全流程闭环」只读状态采集 (供 👑 大屏 / 飞书卡片)。

一句话: 把 reports/fullflow7/<最新 run>/state.json 的真跑证据压成一段 JSON —— 谁跑过、几任务成、仿真多少轨迹、
训练每层 rc/GPU 峰值、元任务预测覆盖与**输入是否退化**、任务7 真机只读证据、报告路径与缺口。

红线: **只读** (只读 state.json / tap 尾帧 / 报告文件头), 不写业务文件、不触发任何跑批;
      取不到就如实写 null + note, 绝不编造。

用法:
  python3 tools/fullflow_status.py            # 人读摘要
  python3 tools/fullflow_status.py --json     # 单段 JSON (大屏/卡片吃)
  python3 tools/fullflow_status.py --run DIR  # 指定 run 目录
"""
from __future__ import annotations

import argparse
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FF7 = os.path.join(ROOT, "reports", "fullflow7")
TAPS = "/dev/shm/zmax_torque"


def _tap_torque(scene: str):
    """某场景驱动扭矩 tap 尾帧 ‖T‖ (只读尾 256KB, 倒序找完整行 —— 写入器还在追加)。"""
    p = os.path.join(TAPS, "torque_%s.jsonl" % scene)
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - 262144))
            for ln in reversed(f.read().decode("utf-8", "replace").splitlines()):
                try:
                    return float(json.loads(ln).get("torque_norm"))
                except Exception:                                             # noqa: BLE001
                    continue
    except Exception:                                                         # noqa: BLE001
        return None
    return None


def _latest_run(run: str | None = None) -> str | None:
    if run:
        return run if os.path.exists(os.path.join(run, "state.json")) else None
    best, best_t = None, -1.0
    for p in glob.glob(os.path.join(FF7, "*", "state.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:                                                     # noqa: BLE001
            continue
        if not (d.get("results") or {}):
            continue
        t = os.path.getmtime(p)
        if t > best_t:
            best, best_t = os.path.dirname(p), t
    return best


def collect(run: str | None = None) -> dict:
    out = {"ok": False, "run": None, "note": None}
    rd = _latest_run(run)
    if not rd:
        out["note"] = "无 fullflow7 run (未跑过 7 任务闭环)"
        return out
    try:
        st = json.load(open(os.path.join(rd, "state.json"), encoding="utf-8"))
    except Exception as e:                                                    # noqa: BLE001
        out["note"] = "state.json 读失败: %s" % str(e)[:80]
        return out
    res = st.get("results") or {}
    tasks = sorted(res)
    sim_ep = sim_fr = 0
    train_ok = 0
    layers: dict = {}
    gpu_u = gpu_m = 0
    disks: dict = {}
    infer_ok = 0
    meta_n = 0
    tops: list = []
    tnorm: dict = {}
    real = {}
    for t in tasks:
        ev = res[t] or {}
        sd = ev.get("sim_data") or {}
        sim_ep += int(sd.get("episodes") or 0)
        sim_fr += int(sd.get("frames") or 0)
        tr = ev.get("train") or {}
        sts = tr.get("stages") or {}
        layers[t] = {k: (v or {}).get("rc") for k, v in sts.items()}
        if sts and all((v or {}).get("rc") == 0 for v in sts.values()):
            train_ok += 1
        _gp = tr.get("gpu_peak") or {}          # 唯一依据键: train.gpu_peak={util,mem}
        gpu_u = max(gpu_u, int(_gp.get("util") or 0))
        gpu_m = max(gpu_m, int(_gp.get("mem") or 0))
        for k, src in (("disk_free_min_gb", tr.get("disk_free_gb_after")),
                       ("disk_free_first_gb", tr.get("disk_free_gb_before"))):
            if isinstance(src, (int, float)):
                disks[k] = min(disks.get(k, src), src) if k in disks else src
        inf = ev.get("infer") or {}
        if (inf.get("engine_loop") or {}).get("rc") == 0 and (inf.get("l4_intent_models") or {}).get("rc") == 0:
            infer_ok += 1
        mp = inf.get("meta_predict") or {}
        if mp.get("n_candidates"):
            meta_n += 1
            tp = (mp.get("top") or [{}])[0]
            if tp.get("fn_id"):
                tops.append(tp["fn_id"])
        scn = (inf.get("tdrive") or {}).get("scene")
        if scn and scn not in tnorm:
            tnorm[scn] = _tap_torque(scn)
        if t == "TASK-07-AOI" or ev.get("real_readonly"):
            real = (ev.get("real_readonly") or {}).get("items") or real
    tn = [v for v in tnorm.values() if v is not None]
    degenerate = bool(tn) and len(set(round(v, 4) for v in tn)) == 1
    rp = os.path.join(rd, "REPORT.md")
    out.update({
        "ok": True, "run": rd,
        "tasks": len(tasks), "tasks_infer_ok": infer_ok, "tasks_train_ok": train_ok,
        "sim_episodes": sim_ep, "sim_frames": sim_fr,
        "gpu_peak_util": gpu_u, "gpu_peak_mem_mb": gpu_m, "layers_rc": layers, "disk": disks,
        "meta_pred_tasks": meta_n, "meta_top1_distinct": sorted(set(tops)),
        "meta_torque_norm": sorted(set(round(v, 4) for v in tn)) if tn else [],
        "meta_input_degenerate": degenerate,
        "real_readonly": real,
        "report_md": rp if os.path.exists(rp) else None,
        "report_mtime": (os.path.getmtime(rp) if os.path.exists(rp) else None),
        "gaps": (["元任务预测输入退化: 各场景驱动扭矩相同 (‖T‖=%s) ⇒ 无区分度, 需并场景特征或训练预测头"
                  % (sorted(set(round(v, 4) for v in tn))[0] if tn else "?")] if degenerate else [])
                + ["INTACT z_pred 仍 NaN (上游动作块空)", "LoRA A/B 未证明提升前不进默认档"],
    })
    if not real:
        out["note"] = "任务7 真机只读证据缺 (该 run 未含 TASK-07-AOI 或未跑真机段)"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="7 任务全流程闭环 只读状态 (大屏/飞书卡片数据源)")
    ap.add_argument("--json", action="store_true", help="只打 JSON")
    ap.add_argument("--run", default=None, help="指定 run 目录 (默认取最新)")
    a = ap.parse_args()
    d = collect(a.run)
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0
    if not d["ok"]:
        print("❌ %s" % d["note"])
        return 1
    print("▶ 7 任务全流程闭环 · %s" % os.path.basename(d["run"]))
    print("  任务 %s · 推理ok %s · 训练全层rc=0 %s (GPU 峰值 %s%%/%sMB)"
          % (d["tasks"], d["tasks_infer_ok"], d["tasks_train_ok"], d["gpu_peak_util"], d["gpu_peak_mem_mb"]))
    print("  仿真 %s 轨迹 / %s 帧 · 磁盘余 %sGB (末次)" % (
        d["sim_episodes"], d["sim_frames"], (d.get("disk") or {}).get("disk_free_min_gb")))
    print("  元任务预测 覆盖 %s/%s 任务 · top1 %s · 驱动扭矩 ‖T‖ %s%s"
          % (d["meta_pred_tasks"], d["tasks"], "/".join(d["meta_top1_distinct"]),
             d["meta_torque_norm"], " ⚠️输入退化(无区分度)" if d["meta_input_degenerate"] else ""))
    rr = d.get("real_readonly") or {}
    if rr:
        print("  任务7 真机只读: " + " · ".join("%s=%s" % (k, (v or {}).get("rc", (v or {}).get("bytes")))
                                               for k, v in rr.items()))
    print("  报告 %s" % d["report_md"])
    for g in d["gaps"]:
        print("  ⚠️ " + g)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
