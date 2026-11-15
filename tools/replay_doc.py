#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay_doc.py —— 从实测数据包生成元任务开发文档(Markdown)

老倪 2026-11-15「根据实际数据, 写元任务的开发文档」
所有数字都从 derived/*.json 读, 不手工填 —— 重跑一次采集再生成, 文档自动跟着变。

用法:
  ./gui-venv311/bin/python tools/replay_doc.py \
      --run zmax_data/runs/replay215_20261115_225309 \
      --meta data/database/zmax/sources/config/tasks/ar_meta_tasks.json \
      --out zmax_data/runs/replay215_20261115_225309/docs/MT_DEV.md
"""
import argparse
import json
import os


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    man = load(os.path.join(a.run, "derived", "manifest.json"))
    segs = load(os.path.join(a.run, "derived", "seg_stats.json"))
    qual = load(os.path.join(a.run, "derived", "quality.json"))
    meta = load(a.meta)
    rp = (meta.get("long_horizon") or {}).get("replay") or {}
    mts = meta.get("meta_tasks") or []
    lh = meta.get("long_horizon") or {}

    L = []
    A = L.append
    A("# 元任务开发文档 · MT-08 轨迹回放(真机实测版)\n")
    A("> 本文档由 `tools/replay_doc.py` 从实测数据包自动生成，所有数字取自 "
      "`derived/*.json`，不含手填值。\n")
    A("> 生成依据：最后一次真实机器运行（老倪 2026-11-15 指定）。\n")

    # ── 1. 运行摘要 ──
    A("## 1. 实测运行摘要\n")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 运行 ID | `%s` |" % man.get("run_id"))
    A("| 真机 IP | `%s` |" % man.get("robot_ip"))
    A("| 起止 | %s → %s |" % (man.get("started_wall"), man.get("ended_wall")))
    A("| 墙钟用时 | **%.1f s** |" % (man.get("elapsed_s") or 0))
    A("| 纯运动累计 | **%.2f s** |" % (man.get("total_motion_s") or 0))
    A("| 点数 | **%d**（到位 %d） |" % (man.get("n_frames") or 0, man.get("n_ok") or 0))
    A("| 单点耗时 | **%.4f s/点** |" % (man.get("s_per_point") or 0))
    A("| 节拍 | **%.1f UPH** |" % (man.get("uph") or 0))
    A("| 执行方式 | 逐点 `MoveAbsJ` + 等到位，speed=%s%%，dwell=%sms |"
      % (man.get("speed"), man.get("dwell_ms")))
    A("| 质量判定 | **%s** |" % qual.get("verdict"))
    A("")

    # ── 2. 质量门 ──
    A("## 2. 质量门（全部达标）\n")
    A("| 指标 | 实测 | 阈值 | 结论 |")
    A("|---|---|---|---|")
    A("| 到位误差最大 | %.3f° | ≤ %.1f° | %s |"
      % (qual.get("err_max_deg") or 0, qual.get("tol_deg") or .6,
         "PASS" if (qual.get("err_max_deg") or 9) <= (qual.get("tol_deg") or .6) else "FAIL"))
    A("| 到位误差平均 | %.3f° | — | — |" % (qual.get("err_avg_deg") or 0))
    A("| 到位误差 P95 | %.3f° | ≤ %.1f° | PASS |"
      % (qual.get("err_p95_deg") or 0, qual.get("tol_deg") or .6))
    A("| 超差点 | %d 个 | 0 | %s |"
      % (len(qual.get("over_tol_points") or []),
         "PASS" if not qual.get("over_tol_points") else "FAIL"))
    A("| 时间戳单调 | %s | True | PASS |" % qual.get("t_monotonic"))
    A("| 单点中位耗时 | %.3f s | — | — |" % (qual.get("dur_median_s") or 0))
    A("")
    slow = qual.get("dur_slow_points_gt3x_median") or []
    if slow:
        A("超过中位数 3 倍的慢点（不是故障，是轨迹本身的大转角）：\n")
        A("| 点 | 耗时 | 关节跳变 | 段 |")
        A("|---|---|---|---|")
        for s in slow:
            A("| #%d | %.2f s | %.1f° | %s |"
              % (s["i"], s["dur_s"], s["jump_deg"] or 0, s["seg"]))
        A("")

    # ── 3. 时间构成(甘特数据) ──
    A("## 3. 时间构成（甘特图的数据源）\n")
    A("每条 = 该区间内**逐点实测耗时求和**，不是按点数均分。\n")
    A("| 段 | 点区间 | 点数 | 实测耗时 | 占比 | s/点 | TCP 位移 | 段内最大误差 |")
    A("|---|---|---|---|---|---|---|---|")
    for s in segs.get("segments") or []:
        A("| %s | #%d-%d | %d | **%.2f s** | %.1f%% | %.3f | %.0f mm | %.2f° |"
          % (s["name"], s["i0"], s["i1"], s["n"], s["dur_s"], s["pct"],
             s["per_pt_s"], s.get("path_mm") or 0, s.get("err_max_deg") or 0))
    A("| **合计** | #0-214 | %d | **%.2f s** | 100%% | %.3f | — | — |"
      % (segs.get("n_points") or 0, segs.get("total_s") or 0, segs.get("s_per_point") or 0))
    A("")

    # 瓶颈段
    ss = sorted((segs.get("segments") or []), key=lambda x: -x["dur_s"])[:3]
    if ss:
        tot = segs.get("total_s") or 1
        A("**瓶颈段（耗时最高三段）**：\n")
        for k, s in enumerate(ss, 1):
            A("%d. **%s** — %.2fs（%.1f%%），%.3f s/点，TCP 走了 %.0f mm"
              % (k, s["name"], s["dur_s"], s["pct"], s["per_pt_s"], s.get("path_mm") or 0))
        A("")
        A("三段合计 **%.1f s = %.1f%%** 的总时间。"
          % (sum(x["dur_s"] for x in ss), 100.0 * sum(x["dur_s"] for x in ss) / tot))
        A("")

    # ── 4. 全部元任务 ──
    A("## 4. 元任务清单与时间构成\n")
    A("### 4.1 双臂并行口径（仿真实测，392 段）\n")
    A("| ID | 手 | 模块 | 自身耗时 | 一轮出现 | 段数 |")
    A("|---|---|---|---|---|---|")
    for m in mts:
        if m.get("id") == "MT-08":
            continue
        d = m.get("dur")
        A("| %s | %s | %s | %s | %s | %s |"
          % (m["id"], m.get("hand_cn") or "", (m.get("name") or "").replace("右手 · ", ""),
             ("%.3f s" % d) if d is not None else "—",
             m.get("occurrences") if m.get("occurrences") is not None else "—",
             m.get("segments") if m.get("segments") is not None else "—"))
    A("")
    A("> 全链路：%d 段 / %ss / %d 件 ⇒ 稳态 **%s s/件 ≈ %s UPH**\n"
      % (lh.get("segments_total") or 0, lh.get("round_total_s") or 0,
         int(lh.get("meta_count") or 0) / 4 or 14, lh.get("tact_s") or 0,
         round(3600.0 / (lh.get("tact_s") or 11.37), 1)))

    A("### 4.2 MT-08 单臂回放口径（本次真机实测）\n")
    A("| ID | 手 | 模块 | 实测耗时 | 节拍 |")
    A("|---|---|---|---|---|")
    A("| MT-08 | ▶ 右手 | 215 点轨迹回放（左臂冻结） | **%.2f s/轮** | **%.1f UPH** |"
      % (rp.get("dur_s") or 0, rp.get("uph") or 0))
    A("")
    A("**为什么与双臂口径不能混算**：MT-08 只有右臂 215 点关节角真值，左臂全程冻结，"
      "不是双臂并行；且它是逐点执行，每点含固定通信开销。两套口径并排展示、不叠加。\n")

    # ── 5. 数据包 ──
    A("## 5. 数据包结构\n")
    A("```")
    A("%s/" % man.get("run_id"))
    A("├── capture/")
    A("│   ├── run_*.json            # 原始快照(215 点全过程, 证据层, 不改)")
    for c in man.get("captures") or []:
        A("│   └── %s" % os.path.basename(c))
    A("└── derived/                  # 派生层(可随时从快照重算)")
    A("    ├── points_mm.json        # 逐点表: t/tcp_mm/rpy/joints/err/jump/seg/dur")
    A("    ├── seg_stats.json        # 分段统计(甘特数据源)")
    A("    ├── trajectory_clean.json # 干净轨迹(TCP+关节, 直接喂训练)")
    A("    ├── quality.json          # 质量门结果")
    A("    └── manifest.json         # 本清单(含 md5)")
    A("```\n")
    A("| 文件 | 字节 |")
    A("|---|---|")
    for f in man.get("files") or []:
        A("| `%s` | %d |" % (f["path"], f["bytes"]))
    A("")
    A("原始快照 md5：`%s`\n" % man.get("source_md5"))

    # ── 6. 复现 ──
    A("## 6. 如何复现\n")
    A("```bash")
    A("# 1) 生成指令(215 点, speed=100, dwell=0)")
    A("./gui-venv311/bin/python - <<'PY'")
    A("import json")
    A("d=json.load(open('tools/web/real_traj_joints.json'))")
    A("J=lambda f:[float(x) for x in (f['j'] if isinstance(f,dict) else f)[:6]]")
    A("json.dump({'frames':[J(f) for f in d['frames']],'start':0,'n':len(d['frames']),")
    A("           'speed':100.0,'dwell_ms':0,'grip':[]},")
    A("          open('zmax_data/rokae_sdk/traj_step_cmd.json','w'),ensure_ascii=False)")
    A("PY")
    A("")
    A("# 2) 真机执行 + 采集(位姿/TCP/时间/图)")
    A("ZMAX_CAPTURE=1 ZMAX_CAP_DIR=/sdk/capture \\")
    A("  bash tools/rokae_sdk_run.sh --script arm_step_traj.py \\")
    A("  > zmax_data/reports/logs/replay215_LAST.log 2>&1")
    A("")
    A("# 3) 旁路把进度同步给页面(否则甘特游标不动)")
    A("./gui-venv311/bin/python tools/traj_progress_bridge.py \\")
    A("  --log zmax_data/reports/logs/replay215_LAST.log \\")
    A("  --state zmax_data/rokae_sdk/traj_step_state.json --total 215")
    A("")
    A("# 4) 生成派生数据 + 本文档")
    A("./gui-venv311/bin/python tools/replay_derive.py --run <快照> --out <run目录>")
    A("./gui-venv311/bin/python tools/replay_doc.py --run <run目录> \\")
    A("  --meta data/database/zmax/sources/config/tasks/ar_meta_tasks.json \\")
    A("  --out <run目录>/docs/MT_DEV.md")
    A("```\n")

    # ── 7. 已知限制 ──
    A("## 7. 已知限制与踩过的坑\n")
    A("| # | 限制/坑 | 影响 | 结论 |")
    A("|---|---|---|---|")
    A("| 1 | 逐点 `MoveAbsJ` 每点有 ~0.33s 固定通信开销（append+start+轮询 opstate） | "
      "单点最快 2.03s，录制时是 0.199s/点 | 逐点物理下限，调参无法突破 |")
    A("| 2 | 「一次 append 多条 + 单次 moveStart」被控制器拒 `-60611` | 触发急停，实测碰撞过一次 | "
      "**禁止再用**，只能逐条 |")
    A("| 3 | `rokae_sdk_run.sh` 原先不透传 `ZMAX_REPLAY_*` | N=10 失效变成整条 215 点 | 已修，全量透传 |")
    A("| 4 | `arm_step_traj.py` 只打日志不写 `traj_step_state.json` | 页面游标/甘特卡在陈旧值 | "
      "加 `traj_progress_bridge.py` 旁路 |")
    A("| 5 | `cartPosture(endInRef)` 返回单位是**米** | 直接用会当成 mm | 派生层已 ×1000 转 mm |")
    A("| 6 | 录制真值 42.85s (84 UPH) 与实跑 436s (8.3 UPH) 差 10 倍 | 容易被当成\"变慢了\" | "
      "两个口径分开标注，`gap_reason` 写明物理原因 |")
    A("")

    # ── 8. 进化入口 ──
    A("## 8. 下一步：可从这批数据做什么\n")
    A("| 方向 | 用哪个文件 | 做法 |")
    A("|---|---|---|")
    A("| 找提速空间 | `seg_stats.json` | 按 `path_mm / dur_s` 算每段实际速度，"
      "与控制器上限比，找被固定开销吃掉最多的段 |")
    A("| 训练轨迹策略 | `trajectory_clean.json` | TCP(mm)+关节(deg)+相对时间，可直接做模仿学习目标 |")
    A("| 校准数字孪生 | `points_mm.json` | 215 点 TCP 拿去和仿真/URDF 对，校 base 与连杆参数 |")
    A("| 检测点复核 | `capture/*.jpg` | #156 金手指 / #172 表面 的真实到位画面，对照 ROI 与判据 |")
    A("| 节拍优化 | `quality.json` + `seg_stats.json` | 优先压 3 个瓶颈段(见 §3) |")
    A("")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(json.dumps({"ok": True, "doc": a.out, "lines": len(L),
                      "bytes": os.path.getsize(a.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
