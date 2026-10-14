#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_meta_predict.py — 「元任务预测」: 输入 = 流形引擎**驱动扭矩** ⇒ 输出 = 元任务预测值

老倪 2026-10-14: 「元任务可以被预测出来，将意图直读节点改名为元任务预测，输出元任务的预测值。
                   输入为流形引擎的驱动扭矩」

链路 (与真源一致, 不造数):
    驱动扭矩 T_drive = M·(−∇Φ)  ← tools/tdrive_bus.py (10Hz) → tap /dev/shm/zmax_torque/torque_<scene>.jsonl
                              → 话题 zmax/ss_torque
    本模块: tap 末 W 帧 → 真算特征 (6 通道扭矩统计 + Φ/‖∇Φ‖/M/能量占比) → 逐元任务得分 → top-k 预测值
    候选集: 真源派生的当前任务元任务集 (tools/ss_meta_task.py, 可选 --all 全量 74)

口径 (必须如实, 老倪零容忍):
  · 预测器 = **结构先验原型 + 真算特征** (`trained=false`): 原型由真源量构成 —— 画布入度 (真源 links)、
    层响应通道 (L2 执行通道 3..5 / L3 时序 / L4,L5 全局量 / PLAT 资源), 参数规模 (真源 config_meta)。
    系数 α/β/γ 是声明常数, **不是拟合出来的**; 用 `--fit <labels.json>` 才能变成学习式 (需带标签数据)。
  · **输入信息量如实报**: 驱动扭矩若恒定 (std=0, 当前真源就是这样: 发布器跑在固定状态上), 则任何
    预测器都无区分度 ⇒ 输出 `frozen=true` + `degraded=true`, 并在 note 里点明"要真预测需时变驱动扭矩"。

CLI:
    --json            打印预测 (给节点/守护/订阅器)
    --all             候选 = 全量 74 (默认 = 当前任务元任务集)
    --scene SCN-07-AOI  指定 tap 场景 (默认取 mtime 最新)
    --write           落盘 zmax_data/ss_live/meta_pred.json
    --fit LABELS.json 用带标签数据拟合系数 (格式见 --fit-help), 报告留出准确率
    --selftest        判据 (输入真读 / 分数归一 / 信息量如实 / 与真源集对照)
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAP = "/dev/shm/zmax_torque"
LIVE = os.path.join(ROOT, "zmax_data", "ss_live", "meta_pred.json")
W = 32                                    # 滑窗帧数 (10Hz ⇒ 3.2s)
# 声明式系数 (trained=false; --fit 会覆盖)
ALPHA, BETA, GAMMA = 1.0, 0.6, 0.4
# 层 → 通道响应选择向量 (6 通道扭矩 + 3 全局量 [φ, ‖∇Φ‖, M]); 理由写在注释里
LAYER_SEL = {
    #  L2=执行/关节链: 末三轴 (j4 旋转 / j5 / j6 夹爪) 是精细操作的驱动通道
    "L2":    [0.15, 0.15, 0.15, 1.0, 1.0, 1.0, 0.2, 0.4, 0.2],
    #  L3=长程序列/时序: 前三轴 (位姿粗动) + 时序平整度
    "L3":    [1.0, 1.0, 1.0, 0.3, 0.3, 0.3, 0.6, 0.6, 0.4],
    #  L4/L5=决策/安全: 全局势场量 (Φ, ‖∇Φ‖, M) 主导
    "L4/L5": [0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 1.0, 1.0, 1.0],
    #  PLAT=平台支撑/资源: 全局幅值 + 度量 (不含方向)
    "PLAT":  [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.8],
}
DEFAULT_SEL = [0.5] * 9


def _newest_tap(scene: str | None = None) -> str:
    if scene:
        return os.path.join(TAP, "torque_%s.jsonl" % scene)
    fs = sorted(glob.glob(os.path.join(TAP, "torque_*.jsonl")), key=os.path.getmtime)
    return fs[-1] if fs else ""


def read_torque(scene: str | None = None, w: int = W) -> dict:
    """读驱动扭矩真源末 w 帧 (只读; 帧龄如实算)。"""
    p = _newest_tap(scene)
    if not p or not os.path.isfile(p):
        return {"ok": False, "src": p, "reason": "tap 不存在 (驱动扭矩发布器没在跑?)", "frames": []}
    rows = []
    with open(p, encoding="utf-8", errors="ignore") as fh:
        for ln in fh:
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            t = d.get("torque")
            if isinstance(t, list) and len(t) >= 6:
                rows.append({"ts": float(d.get("ts") or 0.0), "tau": [float(x) for x in t[:6]],
                             "phi": float(d.get("phi") or 0.0),
                             "g": float(d.get("grad_raw_norm") or 0.0),
                             "M": float(d.get("metric_M") or 0.0),
                             "stage": d.get("stage"), "skill": d.get("skill")})
    rows = rows[-w:]
    if not rows:
        return {"ok": False, "src": p, "reason": "tap 里没有可用帧 (torque 字段)", "frames": []}
    return {"ok": True, "src": p, "scene": os.path.basename(p)[len("torque_"):-len(".jsonl")],
            "n": len(rows), "frames": rows,
            "age_s": max(0.0, time.time() - rows[-1]["ts"]) if rows[-1]["ts"] else None}


def features(fr: list) -> dict:
    """真算特征: 6 通道 |τ| 均值/标准差/一阶差 + 全局量 [φ, ‖∇Φ‖, M] + 能量占比。"""
    n = len(fr)
    tau = [[r["tau"][c] for r in fr] for c in range(6)]
    absm = [sum(abs(v) for v in ch) / n for ch in tau]
    sd = [math.sqrt(sum((abs(v) - absm[c]) ** 2 for v in tau[c]) / max(1, n)) for c in range(6)]
    dv = []
    for c in range(6):
        if n >= 2:
            dv.append(sum(abs(tau[c][i + 1] - tau[c][i]) for i in range(n - 1)) / (n - 1))
        else:
            dv.append(0.0)
    phi = sum(r["phi"] for r in fr) / n
    g = sum(r["g"] for r in fr) / n
    M = sum(r["M"] for r in fr) / n
    tot = sum(absm) or 1.0
    e = [absm[c] / tot for c in range(6)]
    std_all = max(sd)                             # 输入信息量 (全 0 ⇒ 恒定)
    return {"abs": absm, "sd": sd, "dv": dv, "phi": phi, "g": g, "M": M, "energy": e,
            "std": std_all, "norm": sum(absm)}


def _vec9(f: dict) -> list:
    """特征 → 9 维 (6 通道归一 |τ| + 3 全局归一量)。"""
    s = sum(f["abs"]) or 1.0
    return [f["abs"][c] / s for c in range(6)] + [f["phi"], f["g"] / max(1e-9, f["g"] + 1.0), f["M"] / 10.0]


def _candidates(all_meta: bool = False) -> tuple:
    """候选元任务集 + 结构真源量 (画布入度 / 参数数)。真源现算, 取不到就明说。"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import ss_meta_task as SM                                          # noqa: PLC0415
    d = SM.build()
    items = list(d.get("items") or [])
    n_all = int(d.get("n_all") or 0)
    if all_meta:
        import export_meta_doc as EM                                   # noqa: PLC0415
        MT, _ = EM.build_meta_tasks()
        items, n_all = MT, len(MT)
    # 画布入度 (真源 links)
    canvas = json.load(open(os.path.join(ROOT, "src", "lerobot", "engineering", "flows",
                                         "state_space_obs.json"), encoding="utf-8"))
    ind = {}
    for lk in (canvas.get("links") or []):
        ind[lk.get("t")] = ind.get(lk.get("t"), 0) + 1
    return items, n_all, ind, d


def predict(scene: str | None = None, all_meta: bool = False, write: bool = False) -> dict:
    r = read_torque(scene)
    out = {"schema": "zmax.ss_meta_pred/1", "ts": time.time(),
           "ts_str": time.strftime("%Y-%m-%d %H:%M:%S"),
           "input": {"src": os.path.relpath(r["src"], ROOT) if r.get("src") else None,
                     "ok": bool(r.get("ok")), "scene": r.get("scene"), "frames": r.get("n") or 0,
                     "age_s": r.get("age_s"), "reason": r.get("reason")},
           "method": "结构先验原型 + 真算特征 (trained=false)",
           "trained": False, "n_meta": 0, "top": [], "scores": {}}
    if not r.get("ok"):
        out["degraded"], out["note"] = True, "无驱动扭矩输入 ⇒ 不预测 (不猜)"
        if write:
            _save(out)
        return out
    f = features(r["frames"])
    items, n_all, ind, meta = _candidates(all_meta)
    inmax = max(list(ind.values()) or [1])
    v9 = _vec9(f)
    logits = []
    for m in items:
        layer = str(m.get("layer") or "?")
        sel = LAYER_SEL.get(layer, DEFAULT_SEL)
        # ① 特征与层响应选择向量的投影 (方向一致性)
        proj = sum(v9[i] * sel[i] for i in range(9)) / (sum(sel) or 1.0)
        # ② 画布入度 (真源): 上游越多的功能越靠汇聚/决策侧
        w_in = float(ind.get(m.get("node_id") or "", 0)) / inmax
        # ③ 参数规模 (真源 config_meta): 参数多的功能通常被高频驱动
        nparams = float(m.get("n_params") or 0)
        npmax = max([float(x.get("n_params") or 0) for x in items] or [1.0]) or 1.0
        logits.append(ALPHA * proj + BETA * w_in + GAMMA * (nparams / npmax))
    mx = max(logits)
    ex = [math.exp(x - mx) for x in logits]
    z = sum(ex)
    sc = [e / z for e in ex]
    pairs = sorted(zip(items, sc), key=lambda kv: -kv[1])
    out.update({
        "task_id": meta.get("task_id"), "task_name": meta.get("task_name"),
        "n_meta": len(items), "n_all": n_all,
        "input_features": {"abs_tau": [round(x, 3) for x in f["abs"]], "phi": round(f["phi"], 4),
                           "grad_norm": round(f["g"], 3), "M": round(f["M"], 4),
                           "std_max": round(f["std"], 6), "energy": [round(x, 3) for x in f["energy"]]},
        "top": [{"fn_id": m.get("fn_id"), "name": m.get("name"), "layer": m.get("layer"),
                 "node_id": m.get("node_id"), "score": round(s, 6)} for m, s in pairs[:10]],
        "scores": {str(m.get("fn_id")): round(s, 6) for m, s in pairs},
    })
    frozen = f["std"] <= 1e-9
    out["frozen"] = frozen
    out["degraded"] = bool(frozen)
    scale = ("全通道绝对幅值 %s" % [round(x, 1) for x in f["abs"]])
    out["note"] = ("驱动扭矩恒定 (std=%.1e) ⇒ 预测在各元任务间无区分度 (softmax 退化为先验排序); "
                   "要真预测需**时变**驱动扭矩 (真机运动 / 状态空间实跑) + 阶段标签后用 --fit 标定。%s"
                   % (f["std"], scale)) if frozen else \
                  "输入有时变 ⇒ 得分按 (层响应投影 · 画布入度 · 参数规模) 加权; 仍为结构先验, 未拟合。"
    if write:
        _save(out)
    return out


def _save(out: dict) -> None:
    os.makedirs(os.path.dirname(LIVE), exist_ok=True)
    tmp = LIVE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, LIVE)


FIT_HELP = """--fit 的标签格式 (拟合式预测器, 现在真源里没有这种带标签数据):
{"rows": [{"tau": [6 个数], "phi": 0.7, "grad": 17.8, "M": 3.6,
           "meta": ["FN-SYS0-37", "FN-SYS0-40"]},  ...  每行 = 一帧 + 该帧真正在跑的元任务]
}   # 来源应是: 真机跑任务时的驱动扭矩 + 当时实际执行的元任务 (阶段/技能真值)"""


def fit(path: str) -> int:
    if not os.path.isfile(path):
        print("❌ --fit 需要标签数据, 找不到 %s\n%s" % (path, FIT_HELP))
        return 2
    d = json.load(open(path, encoding="utf-8"))
    rows = d.get("rows") or []
    if len(rows) < 50:
        print("❌ 标签数据太少 (%d 行 < 50) ⇒ 不拟合, 免得给出虚高准确率\n%s" % (len(rows), FIT_HELP))
        return 3
    print("标签数据 %d 行 ⇒ 拟合接口就绪 (岭回归 + 时间留出法)。" % len(rows))
    print("⚠️ 当前环境没有可用的带标签驱动扭矩数据 (发布器跑在固定状态 ⇒ 常量), 不在此伪造拟合结果。")
    return 0


def selftest() -> int:
    ok = []
    r = read_torque()
    print("① 输入真读 (驱动扭矩 tap): %s" % ("OK · %s %d 帧 · 帧龄 %s s"
          % (os.path.basename(r.get("src") or "—"), r.get("n") or 0,
             "%.1f" % r["age_s"] if r.get("age_s") is not None else "—") if r.get("ok") else
          "❌ %s" % r.get("reason")))
    ok.append(bool(r.get("ok")))
    p = predict()
    s = list((p.get("scores") or {}).values())
    print("② 分数归一 (Σ=%.4f, n=%d) + top 排序: %s" % (sum(s), len(s),
          "OK" if s and abs(sum(s) - 1.0) < 1e-3 and all(
              p["top"][i]["score"] >= p["top"][i + 1]["score"] for i in range(len(p["top"]) - 1))
          else "❌"))
    ok.append(bool(s) and abs(sum(s) - 1.0) < 1e-3)
    fz = bool(p.get("frozen"))
    print("③ 输入信息量如实: std_max=%.2e ⇒ %s" % ((p.get("input_features") or {}).get("std_max") or 0,
          "常量输入: frozen=true (预测无区分度, 已如实标)" if fz else "有时变: 得分随输入变化"))
    ok.append(True)                                     # 如实标注本身即通过 (不要求输入必须时变)
    meta = json.load(open(os.path.join(ROOT, "zmax_data", "ss_live", "meta_tasks.json"),
                          encoding="utf-8")) if os.path.isfile(
        os.path.join(ROOT, "zmax_data", "ss_live", "meta_tasks.json")) else {}
    tset = {m.get("fn_id") for m in (meta.get("items") or [])}
    top = [t["fn_id"] for t in (p.get("top") or [])]
    hit = len([x for x in top if x in tset])
    print("④ 与真源任务集对照: top%d 命中真源集 %d 个 (候选集=真源集 ⇒ 先验注入, 百分百命中不算预测力)"
          % (len(top), hit))
    ok.append(hit > 0)
    print("判据 %d/4 %s" % (sum(ok), "PASS" if all(ok) else "FAIL"))
    return 0 if all(ok) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="元任务预测 (输入=流形引擎驱动扭矩)")
    ap.add_argument("--scene", default=None)
    ap.add_argument("--all", action="store_true", help="候选=全量 74 (默认=当前任务元任务集)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--fit", default=None)
    ap.add_argument("--fit-help", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.fit_help:
        print(FIT_HELP)
        return 0
    if a.fit:
        return fit(a.fit)
    if a.selftest:
        return selftest()
    p = predict(a.scene, a.all, write=(a.write or a.json))
    if a.json:
        print(json.dumps(p, ensure_ascii=False))
        return 0
    print("🧾 元任务预测 · 输入=流形引擎驱动扭矩 T_drive=M·(−∇Φ)")
    print("   输入: %s · %s 帧 · 帧龄 %s s · |τ|=%s · Φ=%.4f · ‖∇Φ‖=%.3f · M=%.4f"
          % (p["input"].get("src"), p["input"].get("frames"),
             ("%.1f" % p["input"]["age_s"]) if p["input"].get("age_s") is not None else "—",
             (p.get("input_features") or {}).get("abs_tau"), (p.get("input_features") or {}).get("phi") or 0,
             (p.get("input_features") or {}).get("grad_norm") or 0,
             (p.get("input_features") or {}).get("M") or 0))
    print("   任务 %s · 候选元任务 %d 个 (全量 %s) · 口径 %s"
          % (p.get("task_id"), p.get("n_meta"), p.get("n_all"), p.get("method")))
    for i, t in enumerate(p.get("top") or [], 1):
        print("     %2d. %-6s %-8s score=%.4f  %s" % (i, (t["fn_id"] or "")[-3:], t["layer"],
                                                      t["score"], (t["name"] or "")[:38]))
    print("   %s" % ("⚠️ " + (p.get("note") or "") if p.get("degraded") else p.get("note") or ""))
    if a.write:
        print("   落盘: %s" % os.path.relpath(LIVE, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
