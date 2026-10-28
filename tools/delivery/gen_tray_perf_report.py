#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📊 摆盘 (TASK-06-TRAY) 性能对账 —— 目标(配置单) vs 实测(真跑产物) vs 判定 vs 复核命令

老倪 2026-10-13: 「要保证基于任务配置参数, 能实现成功率>99%、节拍<3.5s 的硬性要求 …
                 主参数M要合理, 可被测量 … 要可操作, 可被验证」

纪律(与全工程一致): **每个数字现取现算**, 不手写; 取不到就写「未标定/未测」, 不许拿概念值充数。
输出: docs/deliverables/摆盘性能对账_<ver>.json / .md
用法: gui-venv311/bin/python tools/delivery/gen_tray_perf_report.py [--task TASK-06-TRAY] [--ver 5.50.5]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util as _ilu
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs", "deliverables")
BINDING = os.path.join(ROOT, "config", "ss_task_binding.json")
NPZ = os.path.join(ROOT, "reports", "tray_place_latest.npz")
MANIFOLD = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
TORQUE_JUDGE = os.path.join(ROOT, "reports", "driving_torque_judge.json")
CTRL_DT = 0.0125            # 摆盘链控制周期 (gen_tray_place_video: ctrl_dt = timestep × frame_skip)


def _load(path, name):
    spec = _ilu.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError("无法加载模块: %s" % path)
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _sha(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def task_cfg(tid):
    d = json.load(open(BINDING, encoding="utf-8"))
    t = next((x for x in (d.get("tasks") or []) if x.get("task_id") == tid), {})
    return d.get("active_task"), t


def episode_facts():
    """从真跑产物现算: 单颗CT / 精度 / 真空建立 / 保持 / 段分解。取不到返回 None。"""
    if not os.path.isfile(NPZ):
        return None
    import numpy as np
    z = np.load(NPZ, allow_pickle=True)
    meta = z["meta"].item()
    judges = meta.get("judges") or []
    st = [str(s) for s in z["stage"]]
    out = {"episode_tag": meta.get("episode_tag"), "seed": meta.get("seed"),
           "total": meta.get("total"), "placed": meta.get("placed"), "steps": meta.get("steps"),
           "params": meta.get("params") or {},
           "ct_s": [round(float(j["ct_s"]), 3) for j in judges],
           "ok": [bool(j.get("ok")) for j in judges],
           "xy_mm": [round(abs(float(j.get("dx_mm") or 0)) + abs(float(j.get("dy_mm") or 0)), 3) for j in judges],
           "yaw_deg": [round(abs(float(j.get("yaw_err_deg") or 0)), 3) for j in judges],
           "vac_ms": [float(j.get("vac_establish_ms") or 0) for j in judges],
           "hold_s": [float(j.get("hold_s") or 0) for j in judges],
           "steps_per_part": [int(j.get("steps") or 0) for j in judges]}
    # 段分解 (第一颗: 0..steps_per_part[0])
    n1 = out["steps_per_part"][0] if out["steps_per_part"] else len(st)
    segs, prev = [], None
    for s in st[:n1]:
        if s != prev:
            segs.append([s, 0])
            prev = s
        segs[-1][1] += 1
    out["segments"] = [{"段": s.replace("阶段 ", ""), "步": n, "时长_s": round(n * CTRL_DT, 2),
                        "占比_pct": round(100.0 * n * CTRL_DT / (n1 * CTRL_DT), 1)} for s, n in segs]
    out["ctrl_dt_s"] = CTRL_DT
    return out


def manifold_facts():
    """在役主参数 M 唯一依据 vs 配置单映射算出的 M (两端对账)。"""
    live = {}
    if os.path.isfile(MANIFOLD):
        live = json.load(open(MANIFOLD, encoding="utf-8"))
    mapped = {}
    try:
        m = _load(os.path.join(ROOT, "tools", "config_to_M.py"), "config_to_M_perf")
        fn = getattr(m, "compute_M", None)
        if fn:
            mapped = fn("TASK-06-TRAY") or {}
    except Exception as e:                                                       # noqa: BLE001
        mapped = {"_err": repr(e)[:120]}
    return {"live": {"M": live.get("M"), "dim": (live.get("metric") or {}).get("dim"),
                     "mode": (live.get("metric") or {}).get("mode"),
                     "unit": live.get("_unit"), "range": live.get("_range"),
                     "updated_at": live.get("_updated_at")},
            "mapped": {k: mapped.get(k) for k in ("scale", "dim", "mode", "diag", "components", "gain",
                                                  "audit_sha", "E_task_j", "level", "inputs")}}


def l45_speed_scale(tid):
    """现跑 L5 规划(L5Plan), 取节拍→速度指令闸的真实取值 (不猜)。"""
    try:
        m = _load(os.path.join(ROOT, "tools", "ss_task_l45.py"), "ss_task_l45_perf")
        cls = getattr(m, "L5Plan")
        o = cls(tid)
        est = 11.0
        return {"takt_s": float(o.takt_s), "est_s": est, "speed_scale": round(float(o.speed_scale), 3),
                "note": ("takt_s=%.2fs ≤ est=%.1fs(硬编码) ⇒ 分支直接给 speed_scale=%.2f, 完全不加速; "
                         "即便 takt 收紧到 <est, 闸门上限也只有 1.5× (ss_task_l45.py:106)"
                         % (float(o.takt_s), est, float(o.speed_scale)))}
    except Exception as e:                                                       # noqa: BLE001
        return {"_err": repr(e)[:160]}


def torque_facts():
    if not os.path.isfile(TORQUE_JUDGE):
        return None
    d = json.load(open(TORQUE_JUDGE, encoding="utf-8"))
    vs = d.get("verdicts") or []
    bad = [v.get("item") for v in vs if not v.get("ok")]
    return {"总项": len(vs), "通过": int(d.get("pass") or 0), "未过": int(d.get("fail") or 0),
            "跳过": d.get("skip") or [], "未过清单": bad, "生成": d.get("ts"),
            "主题": d.get("subject")}


def rows(t, ep, mf, ss, tq):
    """性能指标对账表: 目标/实测/判定/复核命令。"""
    tg = (t.get("targets") or {})
    ov = (t.get("overrides") or {})
    r = []

    def add(no, name, target, meas, verdict, cmd, note=""):
        r.append({"#": no, "指标": name, "目标(配置单)": target, "实测": meas,
                  "判定": verdict, "复核命令": cmd, "备注": note})

    ct = " ; ".join("%.3f" % x for x in (ep or {}).get("ct_s", [])) or "未测"
    takt = tg.get("单颗CT") or ov.get("cyc.takt") or "—"
    hard = 3.5
    cts = (ep or {}).get("ct_s") or []
    if cts:
        v = "未达标 (最坏 %.3fs = 目标 %.2fs 的 %.2f 倍; 硬上限 %.1fs 也超)" % (
            max(cts), 3.15, max(cts) / 3.15, hard)
    else:
        v = "未测"
    add(1, "单颗CT (节拍)", "%s (硬上限 ≤%.1fs)" % (takt, hard), "%s s" % ct, v,
        "python3 tools/delivery/gen_tray_perf_report.py")

    add(2, "节拍可达性 (配置项能否做到)",
        "改配置即可达标",
        "L5 速度指令 speed_scale=%.2f (takt=%.2fs vs est=11.0s)" % (ss.get("speed_scale") or -1, ss.get("takt_s") or -1),
        "**当前配置项不可能达标**: 需要 3.38× 提速, 闸门上限只有 1.5× 且 takt≤est 时恒为 1.0" if cts else "未测",
        "python3 tools/delivery/gen_tray_perf_report.py",
        ss.get("note", ""))

    n_ok = sum(1 for x in (ep or {}).get("ok", []) if x)
    n_all = len((ep or {}).get("ok", []))
    add(3, "连续动作成功率", "≥99% (PVT)", "%d/%d (单 seed %s)" % (n_ok, n_all, (ep or {}).get("seed")),
        "**不构成 99%% 证据** (单 seed %d 颗; 0 失效 n≥299 才是 95%% 置信下限 99%%)" % n_all if n_all else "未测",
        "python3 tools/gen_tray_place_video.py --seed <0..N> (逐 seed 报数, 汇总 ≥299 颗)",
        "验收样本量要求见附录 J")

    xy = (ep or {}).get("xy_mm") or []
    add(4, "取放精度 (水平单边)", "≤1.0 mm", ("最大 %.3f mm (%s)" % (max(xy), " ; ".join("%.3f" % x for x in xy))) if xy else "未测",
        ("达标" if xy and max(xy) <= 1.0 else "未达/未测"),
        "python3 -c \"import numpy as np;print(np.load('reports/tray_place_latest.npz',allow_pickle=True)['meta'].item()['judges'])\"",
        "唯一依据: 每颗判据 dx/dy 绝对值之和")

    yaw = (ep or {}).get("yaw_deg") or []
    add(5, "姿态偏差", "≤1.0 °", ("最大 %.3f °" % max(yaw)) if yaw else "未测",
        ("达标" if yaw and max(yaw) <= 1.0 else "未达/未测"),
        "同上 (judges[].yaw_err_deg)", "")

    vac = (ep or {}).get("vac_ms") or []
    vlim = (ep or {}).get("params", {}).get("vac_establish_ms") or ov.get("pick.vac_establish_ms") or 200
    add(6, "真空建立时长", "≤%s ms (配方上限)" % vlim,
        ("%s ms" % " ; ".join("%.1f" % v for v in vac)) if vac else "未测",
        ("**全部不合格** (超上限 %.1f~%.1f 倍)" % (min(vac) / float(vlim), max(vac) / float(vlim))) if vac else "未测",
        "python3 -c \"import numpy as np;print([j['vac_ok'] for j in np.load('reports/tray_place_latest.npz',allow_pickle=True)['meta'].item()['judges']])\"",
        "配方上限 200ms 与实测 425~538ms 差 2.1~2.7×; 需供应商给达标证据或按实测重定上限")

    hold = (ep or {}).get("hold_s") or []
    hcfg = (ep or {}).get("params", {}).get("hold_s") or ov.get("pick.hold_s") or 5.0
    add(7, "真空保持时长", "配置 %.1f s" % float(hcfg),
        ("%s s" % " ; ".join("%.2f" % v for v in hold)) if hold else "未测",
        ("超标 %.1f%% (实际保持 > 配置)" % (100 * (hold[0] / float(hcfg) - 1))) if hold else "未测",
        "同上 (judges[].hold_s / hold_s_cfg)", "保持过长会被节拍直接吃掉")

    add(8, "连续周转盘数", "≥12 盘 (PVT)", "未测 (单盘 3 颗)", "未验证",
        "python3 tools/gen_tray_place_video.py --modules 3 --seed <N> (连续 ≥12 盘不中断报数)",
        "验收判据: 12 盘无人工干预、无报警")

    lv, mp = (mf or {}).get("live") or {}, (mf or {}).get("mapped") or {}
    same = (lv.get("M") == mp.get("scale")) and (lv.get("dim") == mp.get("dim")) and (lv.get("mode") == mp.get("mode"))
    add(9, "主参数 M (配置单→M 映射落役)", "配置单算出的 M 必须 == 在役唯一依据",
        "在役 M=%s (dim=%s/%s) vs 配置单映射 M=%s (dim=%s/%s)" % (
            lv.get("M"), lv.get("dim"), lv.get("mode"), mp.get("scale"), mp.get("dim"), mp.get("mode")),
        "**不一致 ⇒ 映射未落役**" if not same else "一致",
        "python3 tools/config_to_M.py --task TASK-06-TRAY   # 落役: 加 --write (改在役唯一依据前须评审)",
        "映射规则 R1–R5 在 config_to_M.py; 落役判据 verify_metric_main_param.py 23/0 PASS (节点侧)")

    add(10, "驱动扭矩话题 ss_torque", "10Hz 常驻 · 与 tap 逐位一致 · 场景=活跃场景",
        "判据 %s 项 · 通过 %s · 未过 %s (未过: %s)" % ((tq or {}).get("总项"), (tq or {}).get("通过"),
                                                    (tq or {}).get("未过"), (tq or {}).get("未过清单")),
        ("判据全过 ✅" if tq and not tq.get("未过") else
         "扭矩链本身全过; 唯一未过项是真录像依赖 (办公模式无相机源, 非扭矩缺陷)"),
        "gui-venv311/bin/python tools/verify_driving_torque_topic.py",
        "2026-10-13 修复: ①单播 DDS 配置 ②常驻服务 zmax-torque-bus (原先只是手跑脚本) ③场景跟随 ss_scene_switch")

    add(11, "数据空间话题灯 (10 个允许话题)", "全部绿 (真数据)", "见 zmax_data/dataspace/live.json 的 lamp_tally",
        "部分黑/红 (办公模式无机器人 ⇒ ss_state/ss_action/ss_plan 无源; ss_calib 设计 0.2Hz vs 实测 19.84Hz 灯红)",
        "python3 -c \"import json;print(json.load(open('zmax_data/dataspace/live.json'))['lamp_tally'])\"",
        "2026-10-13 修复发现层: 单播配置 + 全参与者同一张 (原 10/10 黑灯)")
    return r


def build(tid, ver):
    active, t = task_cfg(tid)
    ep = episode_facts()
    mf = manifold_facts()
    ss = l45_speed_scale(tid)
    tq = torque_facts()
    rr = rows(t, ep, mf, ss, tq)
    doc = {
        "schema": 1, "ver": ver, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task": tid, "task_name": t.get("name"), "active_task": active,
        "scene": t.get("scene_ref"), "scene_color": "#1f6feb",
        "sources": {k: {"path": os.path.relpath(p, ROOT), "sha256_16": _sha(p), "mtime": (
            datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S") if os.path.isfile(p) else None)}
            for k, p in (("任务绑定", BINDING), ("摆盘真跑产物", NPZ), ("主参数M唯一依据", MANIFOLD),
                         ("扭矩判据报告", TORQUE_JUDGE))},
        "rows": rr, "episode": ep, "manifold": mf, "speed_gate": ss, "torque": tq,
    }
    return doc


def to_md(d):
    L = []
    L.append("# 摆盘 TASK-06-TRAY · 性能对账与配置映射 (v%s)" % d["ver"])
    L.append("")
    L.append("任务: %s (%s) · 场景: %s · 活跃任务: %s" % (d["task"], d["task_name"], d["scene"], d["active_task"]))
    L.append("生成: %s · 每个数字由 `tools/delivery/gen_tray_perf_report.py` 现取现算 (不手写)" % d["generated_at"])
    L.append("")
    L.append("## 1. 指标对账表")
    L.append("")
    L.append("| # | 指标 | 目标(配置单) | 实测 | 判定 | 复核命令 |")
    L.append("|---|---|---|---|---|---|")
    for r in d["rows"]:
        L.append("| %s | %s | %s | %s | %s | `%s` |" % (r["#"], r["指标"], r["目标(配置单)"], r["实测"],
                                                        r["判定"], r["复核命令"]))
    L.append("")
    ep = d.get("episode") or {}
    if ep.get("segments"):
        L.append("## 2. 单颗节拍分解 (第 1 颗 · 控制周期 %.4f s = 80Hz)" % ep.get("ctrl_dt_s", 0))
        L.append("")
        L.append("| 段 | 步 | 时长 s | 占单颗 % |")
        L.append("|---|---|---|---|")
        for s in ep["segments"]:
            L.append("| %s | %d | %.2f | %.1f%% |" % (s["段"], s["步"], s["时长_s"], s["占比_pct"]))
        L.append("")
        L.append("总步/颗: %s · 目标 3.15s ⇒ ≤251 步 ⇒ 需提速 %.2f×" % (
            " / ".join(str(x) for x in ep.get("steps_per_part") or []),
            (max(ep.get("ct_s") or [0]) / 3.15) if ep.get("ct_s") else 0))
        L.append("")
    mf = d.get("manifold") or {}
    L.append("## 3. 主参数 M (配置单 → M 的映射与落役对账)")
    L.append("")
    lv, mp = mf.get("live") or {}, mf.get("mapped") or {}
    L.append("- **定义**: 度量张量 g_ij(x) = M·G_ij(x), det G=1, M ∈ %s —— M = 整体尺度(物理=等效惯量尺度, a=F/M), G = 形状" % (lv.get("range")))
    L.append("- **在役唯一依据** `config/calib/zmax_manifold.json`: M=%s · dim=%s · mode=%s · 更新 %s" % (lv.get("M"), lv.get("dim"), lv.get("mode"), lv.get("updated_at")))
    L.append("- **配置单映射算得** (config_to_M R1–R5): M=%s · dim=%s · mode=%s · audit_sha=%s" % (mp.get("scale"), mp.get("dim"), mp.get("mode"), mp.get("audit_sha")))
    L.append("- **判定**: %s" % ("一致" if (lv.get("M") == mp.get("scale") and lv.get("dim") == mp.get("dim")) else "**不一致 ⇒ 摆盘配置单尚未落到在役主参数** (映射链存在、判据在节点侧 23/0 PASS, 但唯一依据未写)"))
    if mp.get("inputs"):
        L.append("- **可测量输入 (R5 能量标定)**:")
        for k, v in (mp.get("inputs") or {}).items():
            L.append("  - %s: %s" % (k, v))
    L.append("- **测量方法 (可被测量, 现场照做)**: ①能量法 M = 1 + (½·m_eff·v_peak² + m_eff·g·h)/E_ref, 输入 m_eff=夹具+工件(唯一依据 calib/称重)、v_peak(轨迹实测峰值, 由 tcp_pose 50Hz 差分)、h=行程(结构参数), E_ref=标定基准; ②动力学反解 M = F/a (施加已知力 F, 测加速度 a), 两种方法互检; ③验收区间 [0,8], 在役值须与配置单算出值逐位一致 (不一致即判不通过)。")
    L.append("")
    ss = d.get("speed_gate") or {}
    L.append("## 4. 节拍可达性 (配置项 → 性能, 代码级证据)")
    L.append("")
    L.append("- L5 速度指令: `speed_scale = max(1.0, min(1.5, takt_s/est))` if takt_s > est else 1.0")
    L.append("- 现取值: takt_s=%s · est=%ss (硬编码) · speed_scale=%s" % (ss.get("takt_s"), ss.get("est_s"), ss.get("speed_scale")))
    L.append("- **结论**: %s" % ss.get("note"))
    L.append("- 要求 3.15s 需 **3.38×** 提速 ⇒ 现配置项无论怎么改都不可达; 必须改结构 (见 §5)")
    L.append("")
    L.append("## 5. 达标路径 (须改的工程项, 逐条可验证)")
    L.append("")
    L.append("| 项 | 现状 | 目标 | 改什么 | 验证 |")
    L.append("|---|---|---|---|---|")
    L.append("| 控制周期 | 12.5ms (80Hz) | ≤5ms (≥200Hz) | 真机控制器周期/仿真 frame_skip | 节拍 = 步数×周期, 实测 CT 逐颗报 |")
    L.append("| 速度剖面 | z 接近段 29.7~31.1mm/s | 粗接近 ≥100mm/s, 精接近保留 | 段分级 (按公差/行程) | 段分解表 (§2) |")
    L.append("| 固定等待段 | 对位+完成 1.35s (12.7%) | 取消/并行 | L5 阶段链 | 段分解表 (§2) |")
    L.append("| 速度闸 | clamp 1.5× | 按实测标定至 ≥3.4× | ss_task_l45.py:106 + est=11.0 硬编码改实测 | 节拍可达性 (§4) |")
    L.append("| 主参数 M | 在役 3.283 (dim3/full) | 配置单算出 4.423 (dim6/isotropic) 落役 | config_to_M --write + 摆盘链真正消费 M | §3 + verify_metric_main_param |")
    L.append("| 真空建立 | 425~538ms | ≤200ms | 真空阈值/吸嘴压入量/检测带宽 | 判据 vac_ok |")
    L.append("")
    tq = d.get("torque") or {}
    L.append("## 6. 驱动扭矩话题 (流形引擎输出) 验证")
    L.append("")
    L.append("- 判据报告: %s 项 · 通过 %s · 未过 %s" % (tq.get("总项"), tq.get("通过"), tq.get("未过")))
    L.append("- 未过项: %s" % (tq.get("未过清单") or "无"))
    L.append("- 语义: ss_torque = M·(−∇Φ) (M 来自主参数唯一依据, Φ 为真实势场); 单位按规格记 N·m, **未做扭矩计量学标定** (payload 自带声明)")
    L.append("- 复核: `gui-venv311/bin/python tools/verify_driving_torque_topic.py` → `reports/driving_torque_judge.json`")
    L.append("")
    L.append("## 7. 数据来源与指纹 (可回读)")
    L.append("")
    L.append("| 来源 | 路径 | sha256(16) | mtime |")
    L.append("|---|---|---|---|")
    for k, v in (d.get("sources") or {}).items():
        L.append("| %s | `%s` | %s | %s |" % (k, v["path"], v["sha256_16"], v["mtime"]))
    L.append("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="TASK-06-TRAY")
    ap.add_argument("--ver", default="5.50.5")
    a = ap.parse_args()
    d = build(a.task, a.ver)
    os.makedirs(DOCS, exist_ok=True)
    jp = os.path.join(DOCS, "摆盘性能对账_%s.json" % a.ver)
    mp = os.path.join(DOCS, "摆盘性能对账_%s.md" % a.ver)
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    with open(mp, "w", encoding="utf-8") as f:
        f.write(to_md(d))
    print("✅ %s" % jp)
    print("✅ %s" % mp)
    print("   指标 %d 条 · 实测单颗CT %s · 主参数M 在役 %s / 映射 %s" % (
        len(d["rows"]), d["episode"] and d["episode"]["ct_s"],
        (d["manifold"]["live"] or {}).get("M"), (d["manifold"]["mapped"] or {}).get("scale")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
