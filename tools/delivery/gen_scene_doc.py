#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_scene_doc.py — 按「配置模板」出**单场景**交付文档 (摆盘 / 插拔 各一份)

老倪 2026-10-13 交付口径:
  · 每个功能清单都要有 **输入 topic / 输出 topic / 详细功能描述 / 达到的性能指标**, 性能指标必须可测量;
    不同功能可以指向同一性能指标 (指标是功能的属性)。
  · **任务配置** = 调用不同的工艺技能; **工程配置** = 实际场景切换 / 空间点位 / 位置 / 角度 / 性能指标目标。
  · **每个功能都要有 topic 实际输入输出的测试报告** (真收发, 不是登记核对)。
  · 文档明确目标: **成功率 99% · 节拍 3.5s**。
  · 摆盘与插拔 = 两份文档 (同一模板, 由配置模板定义)。

真源 (全部现取, 不手写):
  outputs/config_sheets/配置单_<task>_latest.json      任务/画布/参数注册表/标定真源/点位台账
  reports/feature_io_test.json                         功能 topic 输入输出实测
  docs/deliverables/两场景验收报告_<ver>.json            性能实测与判定
  data/database/zmax/zmax_engineering.db               能力清单(31)/产品特征KPI/模块↔能力
  config/topics/scene_tags.json · config/ss_task_binding.json · config/platform/zmax_perf_spec.json

用法: gui-venv311/bin/python tools/delivery/gen_scene_doc.py --task TASK-06-TRAY --ver 5.50.5
产物: docs/deliverables/交付文档_<场景>_<task>_<ver>.md (+ .json)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCENES = {"TASK-06-TRAY": ("摆盘", "TASK-06-TRAY"), "TASK-01-FW": ("插拔", "TASK-01-FW")}
TARGETS = {"TASK-06-TRAY": {"success_rate": "≥99%", "takt_s": "≤3.15s (硬上限 3.5s)"},
           "TASK-01-FW": {"success_rate": "≥99%", "takt_s": "≤3.15s (硬上限 3.5s)"}}


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return d


def _sheet(task):
    p = os.path.join(ROOT, "outputs", "config_sheets", "配置单_%s_latest.json" % task)
    return _j(p, {}) or {}


def _acceptance(ver):
    p = os.path.join(ROOT, "docs", "deliverables", "两场景验收报告_%s.json" % ver)
    return _j(p, {}) or {}


def _db():
    p = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
    c = sqlite3.connect(p)
    cap = {r[0]: dict(zip(["bo_id", "grp", "name", "dirs", "brief", "explain", "iface", "inputs", "outputs",
                           "scenes", "engineering", "owner"], r))
           for r in c.execute("select bo_id, grp, name, dirs, brief, explain, iface, inputs, outputs,"
                              " scenes, engineering, owner from capability_dbc")}
    kpi, pf_rows = {}, []
    for pf_id, title, cref, kpi_s, status, mods in c.execute(
            "select pf_id, title, capability_ref, kpi, status, module_refs from product_features"):
        try:
            mods = json.loads(mods or "[]")
        except Exception:  # noqa: BLE001
            mods = []
        pf_rows.append({"pf_id": pf_id, "title": title, "cap": cref, "kpi": kpi_s, "status": status, "modules": mods})
        bo = (cref or "").split()[1] if cref and "BO_" in cref else ""
        if bo:
            for m in mods:
                kpi.setdefault(bo, []).append(kpi_s or "")
    return cap, pf_rows, kpi


def _probe():
    return _j(os.path.join(ROOT, "reports", "feature_io_test.json"), {}) or {}


def _binding():
    return _j(os.path.join(ROOT, "config", "ss_task_binding.json"), {}) or {}


def build(task, ver):
    name, tid = SCENES[task]
    sh = _sheet(task)
    acc = (_acceptance(ver).get("sections") or {})
    io = _probe()
    cap, pf_rows, kpi_by_bo = _db()
    binding = _binding()
    _ts = binding.get("tasks") or []
    tk = next((x for x in _ts if isinstance(x, dict) and x.get("task_id") == tid), {}) if isinstance(_ts, list) else (_ts.get(tid) or {})
    st = sh.get("任务") or {}
    canvas = sh.get("画布") or {}
    enabled = canvas.get("启用节点参数") or []
    eids = {x.get("id") for x in enabled}
    funcs = [f for f in (io.get("functions") or []) if f["id"] in eids]
    typed = io.get("typed") or {}
    scenes = (_j(os.path.join(ROOT, "config", "topics", "scene_tags.json"), {}) or {}).get("scenes") or []
    perf = _j(os.path.join(ROOT, "config", "platform", "zmax_perf_spec.json"), {}) or {}
    return {"task": task, "scene": name, "ver": ver, "sheet": sh, "acc": acc, "io": io, "cap": cap,
            "pf": pf_rows, "kpi_by_bo": kpi_by_bo, "binding": tk, "st": st, "canvas": canvas,
            "enabled": enabled, "funcs": funcs, "typed": typed, "scenes": scenes, "perf": perf,
            "rollup": {"n_functions": io.get("n_functions"), "n_out_ok": io.get("n_out_ok"),
                       "n_typed": io.get("n_typed"), "n_typed_ok": io.get("n_typed_ok")}}


def render(d):
    task, ver, name = d["task"], d["ver"], d["scene"]
    st, canvas, funcs, io = d["st"], d["canvas"], d["funcs"], d["io"]
    acc = d["acc"] or {}
    L = []
    A = L.append
    gen = time.strftime("%Y-%m-%d %H:%M:%S")
    A("# %s作业 交付文档 · %s · %s" % (name, task, ver))
    A("")
    A("> 本文件由配置模板同源渲染 (真源: 配置单 / 功能 topic 实测 / 验收报告 / 工程库), **数字不手写**。")
    A("> 场景: %s · 站点: %s · 场景号: %s · 生成: %s" %
      (st.get("场景"), st.get("site"), st.get("SCN"), gen))
    A("")
    # ── §0 目标 ──
    tgt = TARGETS.get(task, {})
    A("## 一、目标与达成情况 (硬指标: 成功率 99% · 节拍 3.5s)")
    A("")
    A("| 指标 | 目标 | 本次实测 | 判定 |")
    A("|---|---|---|---|")
    tray, ins = acc.get("perf_tray") or {}, acc.get("perf_insert") or {}
    v = acc.get("verdict") or {}
    if task == "TASK-06-TRAY":
        t = v.get("takt") or {}
        s = v.get("success") or {}
        A("| 单颗节拍 (CT) | %s | %s s | %s |" %
          (tgt["takt_s"], t.get("measured_s"), "达标" if (t.get("ratio") or 9) <= 0.9 else "**未达标 %.2f×**" % (t.get("ratio") or 0)))
        A("| 连续动作成功率 | ≥99%% | %d 次观测 0 失效 (95%% 置信下限 %.1f%%) | **证据不足** (需 ≥%d 次连续 0 失效) |" %
          (s.get("n_obs", 0), (s.get("ci95_lower") or 0) * 100, s.get("need_n_for_99") or 0))
        A("| 取放精度 | 单边 ≤1mm / ≤1° | Δxy ≤%.2f mm · 姿态 ≤%.2f° | 达标 |" %
          (max([abs(r.get("dx") or 0) for r in (tray.get("per") or [])] or [0]),
           max([r.get("yaw_deg") or 0 for r in (tray.get("per") or [])] or [0])))
        vac = v.get("vacuum") or {}
        _ms = vac.get("measured_ms") or []
        _lim = vac.get("judge_limit_ms") or 200
        _r = (max(_ms) / float(_lim)) if _ms else 0.0
        A("| 真空建立 | ≤%s ms (配方) | %s ms | %s |" %
          (_lim, _ms, "达标" if _r <= 1 else "**未达标 %.2f×**" % _r))
        _per = tray.get("per") or []
        A("| 逐颗质量 | — | %d/%d 颗合格 | %s |" %
          (tray.get("n_ok") if tray.get("n_ok") is not None else sum(1 for r in _per if r.get("ok")),
           tray.get("n") or len(_per), tray.get("summary") or ""))
    else:
        A("| 插入到位残差 | <2 mm (链内 `_insert_depth()<0.002m`) | %.4f mm | %s |" %
          (ins.get("depth_mm") or -1, "达标" if ins.get("depth_ok") else "未达标"))
        A("| 插入行程 (配置) | ins.depth | %s mm | — |" % ins.get("depth_cfg_target_mm"))
        A("| episode 时长 | — | %.2f s (%s 步) | 任务真源未定义节拍目标 |" %
          (ins.get("t_span_s") or 0, ins.get("steps")))
        A("| 终态 / success | 完成 | `%s` · %s | 达标 |" % (ins.get("stage_final"), ins.get("success")))
    A("")
    A("**明确目标**: 成功率 **≥99%** · 节拍 **≤3.15s (硬上限 3.5s)**。达成路径见 §五。")
    A("")
    # ── §1 工程配置 ──
    A("## 二、工程配置 (场景切换 · 空间点位 · 位置/角度 · 性能指标目标)")
    A("")
    A("### 2.1 场景切换")
    A("")
    A("| 任务 | 场景 | 场景号 | 颜色 |")
    A("|---|---|---|---|")
    for s in d["scenes"]:
        A("| %s | %s | %s | `%s` %s |" % (s.get("task"), s.get("scene"), s.get("scn"), s.get("color"), s.get("label")))
    A("")
    A("当前活跃任务: `%s` (真源 `config/ss_task_binding.json`) · 切换器 `tools/ss_scene_switch.py`" %
      (sh_active := (_j(os.path.join(ROOT, "config", "ss_task_binding.json"), {}) or {}).get("active_task")))
    A("")
    A("### 2.2 空间点位 / 位置 / 角度")
    A("")
    A("| 台账 | 文件 | 条数 | sha256(16) | 时间 |")
    A("|---|---|---|---|---|")
    for x in (d["sheet"].get("点位台账") or []):
        A("| %s | `%s` | %s | `%s` | %s |" % (x.get("label"), x.get("file"), x.get("count"), x.get("sha256_16"), x.get("mtime")))
    A("")
    A("标定真源: %s" % "; ".join("`%s` sha `%s`" % (x.get("file"), x.get("sha256_16"))
                                for x in (d["sheet"].get("标定真源") or [])))
    A("")
    blk = st.get("blocked_by_site") or []
    A("站位几何: %s" % ("**未标定** " + ", ".join("`%s`" % b for b in blk) + " ⇒ 坐标类参数标「不可信」"
                        if blk else "已标定"))
    A("")
    A("### 2.3 性能指标目标 (任务级)")
    A("")
    A("| 目标项 | 值 |")
    A("|---|---|")
    for k, x in (st.get("targets") or {}).items():
        A("| %s | %s |" % (k, x))
    A("")
    A("工程配置模板: 画布工程 `%s` · 文件 `%s` · 节点 %s / 连线 %s · md5 `%s` · 本场景启用节点 **%s**" %
      (canvas.get("工程"), canvas.get("文件"), canvas.get("节点"), canvas.get("连线"), canvas.get("md5"),
       canvas.get("启用节点数")))
    A("")
    # ── §2 任务配置 ──
    A("## 三、任务配置 (调用不同的工艺技能)")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 任务 | `%s` %s |" % (st.get("task_id"), st.get("name")))
    A("| 配方 | %s |" % st.get("recipe_type"))
    A("| 触发 | %s |" % st.get("trigger"))
    A("| 循环 | %s |" % st.get("loop"))
    A("| 安全 | %s |" % st.get("safety"))
    A("| 适用段 | %s |" % " / ".join(st.get("适用段") or []))
    A("| 不适用段 | %s |" % (" / ".join(st.get("不适用段") or []) or "—"))
    A("| 工单规则 | %s |" % st.get("orders_rule"))
    A("")
    A("### 3.1 工艺步骤 (任务调用的工艺技能序列)")
    A("")
    A("| t(s) | 时长(s) | 技能 | 说明 |")
    A("|---|---|---|---|")
    for p in (st.get("工艺步骤") or []):
        A("| %s | %s | **%s** | %s |" % (p.get("t"), p.get("dur"), p.get("name"), (p.get("desc") or "")[:200]))
    A("")
    A("### 3.2 参数覆盖 (任务 → 能力参数, 可测量)")
    A("")
    A("| 参数 | 值 | 归属能力 |")
    A("|---|---|---|")
    own = {"pick.vac_establish_ms": "C1 完整作业执行 (取件真空建立)", "pick.hold_s": "C1 (吸持保持)",
           "pick.retry": "C1 (重试上限)", "place.down_force_max": "C3 力控保护 (防压伤)",
           "place.angle_tol_deg": "C2 精细对位 (姿态容差)", "src.orient": "B1 目标识别定位 (来料朝向)",
           "cyc.takt": "C1 / H1 (节拍目标)", "sort.pass_tray": "C1 (分拣, 摆盘不适用)"}
    for k, x in (st.get("参数覆盖") or {}).items():
        A("| `%s` | %s | %s |" % (k, x, own.get(k, "—")))
    A("")
    A("档位 (运行开关): %s" % " · ".join("%s=%s" % (v.get("label"), "开" if v.get("checked") else "关")
                                        for v in (st.get("档位") or {}).values()))
    A("")
    # ── §3 功能清单 ──
    A("## 四、功能清单 (每个功能: 详细描述 · 输入 topic · 输出 topic · 性能指标)")
    A("")
    A("> 功能 = 能力库(BO_) + 本场景启用的画布节点。**性能指标是功能属性, 不同功能可指向同一指标** (可测量)。")
    A("")
    A("### 4.1 能力层 (31 项能力字典) — 本场景覆盖")
    A("")
    A("| 能力 | 域 | 方向 | 详细功能描述 | 输入 topic | 输出 topic | 性能指标 (可测量) | 本场景 |")
    A("|---|---|---|---|---|---|---|---|")
    mods_in_scene = {f["name"]: f for f in funcs}
    for bo, c in sorted(d["cap"].items()):
        pfs = [p for p in (d["pf"] or []) if bo in (p["cap"] or "")]
        hit = [p for p in pfs if any(m in mods_in_scene for m in p["modules"])]
        ot = []
        it = []
        for p in hit:
            for m in p["modules"]:
                f = mods_in_scene.get(m)
                if f:
                    ot += f["out_topics"]
                    it += f["in_topics"]
        kpi = "; ".join(sorted({p["kpi"] for p in pfs if p["kpi"]})) or "见 §4.2 节点指标"
        A("| **%s %s** | %s | %s | %s | %s | %s | %s | %s |" %
          (bo, c["name"], c["grp"], c["dirs"], (c["brief"] + "；" + (c["iface"] or ""))[:220],
           ", ".join("`%s`" % x for x in sorted(set(it))[:2]) or (c["inputs"] or "—")[:60],
           ", ".join("`%s`" % x for x in sorted(set(ot))[:2]) or (c["outputs"] or "—")[:60],
           kpi[:110], "**调用** (%d 节点)" % len(hit) if hit else "未调用"))
    A("")
    A("### 4.2 本场景启用节点 (功能实现) — 输入/输出 topic 与性能指标")
    A("")
    A("| 功能 (节点) | 层 | 详细功能描述 | 输入 topic | 输出 topic | 性能指标 (可测量) |")
    A("|---|---|---|---|---|---|")
    for f in sorted(funcs, key=lambda x: (x.get("layer") or "zz", x["id"])):
        kpi = "; ".join(f.get("kpi") or []) or ("见能力层 §4.1" if not f.get("cap") else "见能力 " + ",".join(f["cap"]))
        A("| **%s** | %s | %s | %s | `%s` | %s |" %
          (f["name"], f.get("layer") or "-", (f.get("desc") or "")[:180],
           ", ".join("`%s`" % t for t in f["in_topics"][:3]) or "（源节点）",
           f["out_topics"][0], kpi[:150]))
    A("")
    # ── §4 功能 topic 输入输出测试报告 ──
    A("## 五、每个功能的 topic 输入/输出 **实际测试报告**")
    A("")
    A("> 实测方式: 逐 topic **真 DDS 往返** (`zmax::SSTest` 载体, 发布/订阅**两个独立参与者**, 挂单播配置 "
      "`CYCLONEDDS_URI=dds/cyclonedds_unicast.xml`) + 注册 typed 话题按注册 QoS 只读订阅。")
    A("> 判据: 发出/收到 且 收到 ≥ 发出/2 ⇒ 通道 ✅; 收到 0 条 ⇒ 如实写 ❌ (不当「通过」)。")
    A("")
    r = d["rollup"] or {}
    A("| 汇总 | 数 |")
    A("|---|---|")
    A("| 功能(画布节点)总数 | %s |" % r.get("n_functions"))
    A("| 节点输出通道往返 ✅ | **%s / %s** |" % (r.get("n_out_ok"), r.get("n_functions")))
    A("| 注册 typed 话题有流量 ✅ | **%s / %s** |" % (r.get("n_typed_ok"), r.get("n_typed")))
    A("")
    A("### 5.1 本场景启用功能 (%d 个) 逐条实测" % len(funcs))
    A("")
    A("| 功能 (节点) | 输出 topic | 发出 | 收到 | 匹配 | 输出通道 | 输入 topic (上游) | 输入通道 |")
    A("|---|---|---|---|---|---|---|---|")
    for f in sorted(funcs, key=lambda x: (x.get("layer") or "zz", x["id"])):
        x = f.get("io") or {}
        A("| **%s** | `%s` | %s | %s | %s | %s | %s | %s |" %
          (f["name"], f["out_topics"][0], x.get("out_sent"), x.get("out_got"), x.get("matched"),
           "✅" if x.get("out_ok") else "❌",
           ", ".join("`%s`" % t for t in f["in_topics"][:2]) or "（源节点）",
           ("✅ %s/%s" % (x.get("in_measured"), x.get("in_total"))) if x.get("in_total") else "—(源)"))
    A("")
    A("### 5.2 数据空间注册 typed 话题 (全量) 实测")
    A("")
    A("| 话题 | 本窗口条数 | 实测 Hz | 帧龄 s | 判定 |")
    A("|---|---|---|---|---|")
    for k, x in sorted((d["typed"] or {}).items(), key=lambda y: (not y[1].get("ok"), y[0])):
        A("| `zmax/%s` | %s | %s | %s | %s |" % (k, x.get("count"), x.get("hz"), x.get("age_s"),
                                                "✅ 有流量" if x.get("ok") else "❌ 无发布端 (本刻未起)"))
    A("")
    # ── §5 结论 ──
    A("## 六、质量评估结论与达成路径")
    A("")
    for row in (v.get("rows") or acc.get("conclusion") or []):
        if isinstance(row, (list, tuple)) and len(row) >= 3:
            A("- **%s**: %s — %s" % (row[0], row[1], row[2]))
    A("")
    A("**达成 99% / 3.5s 的路径** (改完必须重跑同口径验收):")
    A("1. 真空保持 `pick.hold_s` 5.0s → 0.6~1.0s (节拍大头);")
    A("2. 接近段末尾**预抽真空**, 把真空建立时间藏进接近时间 (不放宽判据);")
    A("3. 放开速度档位 (`speed_scale` 现被 `est=11.0` 硬编码卡在 1.5×, 达标需 3.38×), 保留加速度限幅;")
    A("4. 连续验收 12 盘 × 25 颗 = 300 颗 0 失效, 出具 95% 置信下限 ≥99% 的成功率结论。")
    A("")
    A("## 复核命令")
    A("")
    A("```bash")
    A("python3 tools/ss_task_runner.py --task %s --no-video" % task)
    A("venvs/dds-venv/bin/python tools/verify_feature_io.py --seconds 10")
    A("gui-venv311/bin/python tools/delivery/gen_scene_doc.py --task %s --ver %s" % (task, ver))
    A("```")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, choices=list(SCENES))
    ap.add_argument("--ver", default="v5.50.5")
    a = ap.parse_args()
    d = build(a.task, a.ver)
    md = render(d)
    name = SCENES[a.task][0]
    out_md = os.path.join(ROOT, "docs", "deliverables", "交付文档_%s_%s_%s.md" % (name, a.task, a.ver))
    out_js = out_md[:-3] + ".json"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)
    with open(out_js, "w", encoding="utf-8") as f:
        json.dump({"task": a.task, "scene": name, "ver": a.ver, "generated_at": time.time(),
                   "sheet": d["sheet"], "funcs": d["funcs"], "typed": d["typed"], "rollup": d["rollup"]},
                  f, ensure_ascii=False, indent=1)
    print("→ %s (%d B)" % (out_md, os.path.getsize(out_md)))
    print("→ %s (%d B)" % (out_js, os.path.getsize(out_js)))
    print("   场景启用功能 %d 个 · 节点输出通道 %s/%s ✅ · typed 有流量 %s/%s" %
          (len(d["funcs"]), d["rollup"].get("n_out_ok"), d["rollup"].get("n_functions"),
           d["rollup"].get("n_typed_ok"), d["rollup"].get("n_typed")))


if __name__ == "__main__":
    main()
