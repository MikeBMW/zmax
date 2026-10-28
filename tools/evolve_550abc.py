#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evolve_550abc.py — 新场景 (TASK-08-AL1 · 光纤端面检测上料缓存) 的全系统自主进化,
三个产品档位 550A / 550B / 550C 各跑一遍「配置 → 自生成数据 → 训练全模型 → 推理 → 报告」。

它不发明流程: 每一段都是 Z-MAX 已有工具的**真调用**:
  档位      tools/zmax_compute_mode.py --apply 550X --no-vscode --no-train
  五段闭环  tools/fullflow_tasks7.py --tasks TASK-08-AL1 ...   (①配置 ②造数据 ③训练 ④推理 ⑥报告)
  汇总      reports/evolution/<ts>/{evolution.json,REPORT.md}

判定 (每档都记真数, 不猜):
  · 造数据: 收集器自报 "完成: N 轨迹 / M 帧" + LeRobot meta 落盘
  · 训练:   rc=0 且 stages.jsonl 里 L4/L3/L2/L5 全有记录; GPU 峰值利用率/显存
  · 推理:   engine_loop rc=0 且打印 "L4 潜空间已接入"; L4 意图模型 rc=0; 元任务预测候选数

用法:
  python tools/evolve_550abc.py --run            # 跑三档 (默认 A→B→C)
  python tools/evolve_550abc.py --run --profiles 550A
  python tools/evolve_550abc.py --status         # 看最近一次进化结果
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "gui-venv311/bin/python")
TASK = "TASK-08-AL1"
SCENE = "SCN-08-AL1"          # 由 --task 推导 (见 scene_of / main)


def scene_of(task):
    """任务 → 场景 (真源 tasks.json 的 scene_ref; 读不到再退回绑定真源)"""
    for p, key in ((os.path.join(ROOT, "data/database/zmax/sources/config/tasks/tasks.json"), "tasks"),
                   (os.path.join(ROOT, "data/database/zmax/sources/config/ss_task_binding.json"), "tasks")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:                                        # noqa: BLE001
            continue
        for x in (d.get(key) or []):
            if x.get("task_id") == task:
                v = x.get("scene_ref") or x.get("scene") or x.get("scene_id")
                if v:
                    return v if str(v).startswith("SCN") else str(v).split()[0]
    return "?"
EVO = os.path.join(ROOT, "reports", "evolution")
FF = os.path.join(ROOT, "reports", "fullflow7")
MODEL = "zmax_compute_mode.py"
LOOPS = ("ss_engine_loop.py", "l3_live.py", "ss_torque")


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def sh(args, timeout=5400, log_path=None):
    t0 = time.time()
    with open(log_path or os.devnull, "ab") as lf:
        p = subprocess.run([PY] + args, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)
    return {"rc": p.returncode, "sec": round(time.time() - t0, 1)}


def tail(path, n=6):
    try:
        return [x.rstrip("\n") for x in open(path, encoding="utf-8", errors="replace").readlines()[-n:]]
    except Exception:                                                            # noqa: BLE001
        return []


def profile_show():
    r = subprocess.run([PY, "tools/" + MODEL, "--show"], cwd=ROOT, capture_output=True, text=True)
    return (r.stdout or "").strip().splitlines()[:1]


def stop_loops():
    """训练前停掉常驻推理/引擎循环 (同一张卡不许两个模型进程抢显存), 返回可重启的命令行。"""
    killed = []
    out = subprocess.run(["pgrep", "-af", "|".join(LOOPS)], capture_output=True, text=True).stdout
    for ln in out.splitlines():
        if "pgrep" in ln or "evolve_550abc" in ln:
            continue
        pid, cmd = ln.split(None, 1)
        try:
            os.kill(int(pid), signal.SIGTERM)
            killed.append(cmd)
        except Exception:                                                        # noqa: BLE001
            pass
    if killed:
        time.sleep(2)
        log("⏸ 停掉 %d 个常驻循环 (避免显存互抢)" % len(killed))
    return killed


def start_loops(cmds):
    for c in cmds:
        try:
            subprocess.Popen(["setsid", "bash", "-lc", "cd %s && exec %s" % (ROOT, c)],
                             stdout=open("/tmp/evo_loop_restart.log", "ab"), stderr=subprocess.STDOUT)
        except Exception as e:                                                   # noqa: BLE001
            log("⚠️ 循环重启失败: %s" % e)
    if cmds:
        log("▶ 已按原命令行重启 %d 个循环" % len(cmds))


def new_ff_dir(before):
    if not os.path.isdir(FF):
        return None
    after = {d for d in os.listdir(FF) if os.path.isdir(os.path.join(FF, d))}
    fresh = sorted(after - before)
    return os.path.join(FF, fresh[-1]) if fresh else None


def parse_run(run_dir):
    """从 fullflow 的 state.json 取真数 (不含任何估算)。"""
    p = os.path.join(run_dir, "state.json")
    if not os.path.exists(p):
        return {}
    s = json.load(open(p, encoding="utf-8"))
    ev = (s.get("results") or {}).get(TASK) or {}
    d = ev.get("sim_data") or {}
    t = ev.get("train") or {}
    f = ev.get("infer") or {}
    return {
        "run_dir": run_dir,
        "sec": ev.get("sec"),
        "episodes": d.get("episodes"), "frames": d.get("frames"),
        "sim_rc": d.get("rc"), "dataset_meta": d.get("dataset_meta"),
        "train_rc": t.get("rc"), "train_skipped": t.get("skipped", False),
        "train_stages": t.get("stages"), "gpu_peak": t.get("gpu_peak"),
        "train_run_dir": t.get("run_dir"),
        "infer_engine_rc": (f.get("engine_loop") or {}).get("rc"),
        "l4_attached": (f.get("engine_loop") or {}).get("l4_attached"),
        "l4_intent_rc": (f.get("l4_intent_models") or {}).get("rc"),
        "l4_intent_pass": (f.get("l4_intent_models") or {}).get("pass"),
        "meta_candidates": (f.get("meta_predict") or {}).get("n_candidates"),
        "meta_top": (f.get("meta_predict") or {}).get("top"),
        "ok": ev.get("ok"),
    }


def ckpt_fingerprint():
    """模型产物指纹: outputs/train 下最新 mtime + 文件数 (证明模型真被重训/改写)。"""
    best = {"mtime": 0, "n": 0, "newest": None}
    for base in ("outputs/train", "outputs"):
        p = os.path.join(ROOT, base)
        if not os.path.isdir(p):
            continue
        for dp, _, fns in os.walk(p):
            for fn in fns:
                if not fn.endswith((".pt", ".pth", ".safetensors", ".ckpt", ".bin", ".onnx")):
                    continue
                fp = os.path.join(dp, fn)
                m = os.path.getmtime(fp)
                best["n"] += 1
                if m > best["mtime"]:
                    best.update(mtime=m, newest=os.path.relpath(fp, ROOT))
    best["mtime_s"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(best["mtime"])) if best["mtime"] else None
    return best


def run_profile(pf, sim_target, steps, yolo_epochs, l5_steps, skip_train, run_dir):
    before = {d for d in os.listdir(FF)} if os.path.isdir(FF) else set()
    r_apply = sh([MODEL.split("/")[-1] if False else "tools/" + MODEL, "--apply", pf,
                  "--no-vscode", "--no-train"], 900, os.path.join(run_dir, "apply_%s.log" % pf))
    applied = profile_show()
    log("   档位已切 %s: rc=%d · %s" % (pf, r_apply["rc"], applied[0] if applied else "?"))
    args = ["tools/fullflow_tasks7.py", "--tasks", TASK, "--sim-target", str(sim_target),
            "--mode", "insert", "--steps", str(steps), "--yolo-epochs", str(yolo_epochs),
            "--l5-steps", str(l5_steps), "--no-feishu"]
    if skip_train:
        args.append("--skip-train")
    fp0 = ckpt_fingerprint()
    r = sh(args, 5400, os.path.join(run_dir, "fullflow_%s.log" % pf))
    fp1 = ckpt_fingerprint()
    ff = new_ff_dir(before)
    res = {"profile": pf, "apply_rc": r_apply["rc"], "apply_state": applied, "ff_rc": r["rc"],
           "ff_sec": r["sec"], "ff_dir": ff, "ckpt_before": fp0, "ckpt_after": fp1,
           "log": os.path.join(run_dir, "fullflow_%s.log" % pf)}
    res.update(parse_run(ff) if ff else {})
    res["log_tail"] = tail(res["log"], 8)
    log("   %s 完成: fullflow rc=%d · %ss · 轨迹 %s / 帧 %s · 训练 rc=%s · 推理 rc=%s"
        % (pf, r["rc"], r["sec"], res.get("episodes"), res.get("frames"),
           res.get("train_rc"), res.get("infer_engine_rc")))
    return res


def _train_dataset():
    """最近一次 L3 训练实际用的数据集根 (从 train_config.json 读) —— 用来核「造的 data 有没有进训练」"""
    import glob
    ps = sorted(glob.glob(os.path.join(ROOT, "outputs/train/*/checkpoints/*/pretrained_model/train_config.json")),
                key=os.path.getmtime)
    if not ps:
        return None, None
    try:
        c = json.load(open(ps[-1], encoding="utf-8"))
        return (c.get("dataset") or {}).get("root"), os.path.getmtime(ps[-1])
    except Exception:                                            # noqa: BLE001
        return None, None


def write_report(evo_dir, results, meta):
    j = {"ts": meta["ts"], "task": TASK, "scene": SCENE, "profiles": results, "meta": meta}
    with open(os.path.join(evo_dir, "evolution.json"), "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=1)

    L = []
    L.append("# 自主进化报告 · %s (%s)\n" % (TASK, SCENE))
    L.append("- 时间: %s" % meta["ts"])
    L.append("- 场景: %s" % SCENE)
    L.append("- 任务: %s" % TASK)
    L.append("- 链路: ① 配置任务=ss_task_bind+ss_scene_switch ② 自生成数据=collect_simreal_vla_data ③ 训练=joint_train_all(L4,L3,L2,L5) ④ 推理=ss_engine_loop+run_l4_intent_models+ss_meta_predict ⑤ 报告=本文件")
    L.append("- 仿真环境: metaworld 插拔 (平台唯一仿真环境); 场景几何/参数真源 = /autoLight#c1 (米, base 世界系)\n")
    L.append("## 结果\n")
    def cell(x):
        return re.sub(r"\s+", " ", str(x if x is not None else "—")).replace("|", "／")
    L.append("| 档位 | 档位状态 | 自生成数据 | 训练 | 推理 | 元任务候选 | 耗时 |")
    L.append("|---|---|---|---|---|---|---|")
    for r in results:
        st = (r.get("apply_state") or ["?"])[0]
        st = re.sub(r"\s+", " ", st)[:46]
        data = "%s 轨迹 / %s 帧" % (r.get("episodes"), r.get("frames")) if r.get("episodes") is not None else "—"
        tr = "跳过(部署档)" if r.get("train_skipped") else ("rc=%s" % r.get("train_rc"))
        if r.get("train_stages"):
            tr += " (" + ",".join(sorted(r["train_stages"].keys())) + ")"
        inf = "rc=%s%s" % (r.get("infer_engine_rc"), " · L4接入" if r.get("l4_attached") else "")
        L.append("| %s | %s | %s | %s | %s | %s | %ss |" % (
            r["profile"], cell(st), cell(data), cell(tr), cell(inf),
            cell(r.get("meta_candidates")), r.get("ff_sec")))
    L.append("\n## 每档细节\n")
    for r in results:
        L.append("### %s\n" % r["profile"])
        L.append("- fullflow: rc=%s 目录=`%s`" % (r.get("ff_rc"), os.path.relpath(r.get("ff_dir") or "-", ROOT)))
        L.append("- 造数据: rc=%s · %s 轨迹 / %s 帧 · LeRobot meta=%s" % (r.get("sim_rc"), r.get("episodes"),
                                                                 r.get("frames"), r.get("dataset_meta")))
        if r.get("train_skipped"):
            L.append("- 训练: 跳过 (550C 部署档不训练, 用上一档产出的权重做部署推理)")
        else:
            L.append("- 训练: rc=%s stages=%s gpu=%s" % (r.get("train_rc"),
                     json.dumps(r.get("train_stages"), ensure_ascii=False),
                     json.dumps(r.get("gpu_peak"), ensure_ascii=False)))
        L.append("- 模型产物指纹: 前 %s 个/%s → 后 %s 个/%s (最新 %s)" % (
            (r.get("ckpt_before") or {}).get("n"), (r.get("ckpt_before") or {}).get("mtime_s"),
            (r.get("ckpt_after") or {}).get("n"), (r.get("ckpt_after") or {}).get("mtime_s"),
            (r.get("ckpt_after") or {}).get("newest")))
        L.append("- 推理: engine rc=%s · L4 潜空间接入=%s · L4 意图模型 rc=%s" % (
            r.get("infer_engine_rc"), r.get("l4_attached"), r.get("l4_intent_rc")))
        if r.get("l4_intent_pass"):
            L.append("  - 判据: %s" % " / ".join(str(x).strip() for x in r["l4_intent_pass"]))
        L.append("- 元任务预测: 候选 %s · top %s" % (r.get("meta_candidates"), json.dumps(r.get("meta_top"), ensure_ascii=False)[:300]))
        L.append("- 日志: `%s`" % os.path.relpath(r["log"], ROOT))
        L.append("")
    L.append("## 系统同步 (四件真源 + 数据源)\n")
    try:
        t = json.load(open(os.path.join(ROOT, "config/tasks/tasks.json"), encoding="utf-8")).get("tasks") or []
        b = json.load(open(os.path.join(ROOT, "config/ss_task_binding.json"), encoding="utf-8"))
        row = next((x for x in t if x.get("task_id") == TASK), {}) or {}
        sc = json.load(open(os.path.join(ROOT, "flows/scenes_5jobs.json"), encoding="utf-8")).get("scenes") or []
        has_scene = any(x.get("scene_id") == SCENE for x in sc)
        L.append("- 场景真源 flows/scenes_5jobs.json: %s (共 %d 场景)" % ("含 %s" % SCENE if has_scene else "缺", len(sc)))
        L.append("- 任务真源 config/tasks/tasks.json: %s · 场景=%s · 段=%d · 覆盖=%d" % (
            row.get("task_id"), row.get("scene_ref"), len(row.get("applies_segments") or []), len(row.get("overrides") or {})))
        L.append("- 绑定 config/ss_task_binding.json: active_task=%s (共 %d 任务)" % (b.get("active_task"), len(b.get("tasks") or [])))
        d = os.path.join(ROOT, "data/scene/scenes", SCENE)
        L.append("- 场景库 data/scene/scenes/%s: %s" % (SCENE, sorted(os.listdir(d)) if os.path.isdir(d) else "缺"))
    except Exception as e:                                                       # noqa: BLE001
        L.append("- 系统同步核验异常: %r" % (e,))
    L.append("")
    L.append("## 数据 → 训练 同源核验 (这一环最容易假闭环)")

    sd = os.path.join(ROOT, "data/datasets/sim_%s" % TASK)
    tr, _tmt = _train_dataset()
    sd_mt = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(sd))) if os.path.isdir(sd) else "缺"
    L.append("- 本任务造数据目录: `data/datasets/sim_%s` (最后改动 %s)" % (TASK, sd_mt))
    L.append("- 训练实际数据集: `%s`" % (tr or "读不到 train_config.json"))
    same = bool(tr) and os.path.abspath(str(tr).replace("\\", "/")) == os.path.abspath(sd)
    if same:
        L.append("- 判定: ✅ 同源 —— 本次造的 data 就是训练用的那个集")
    else:
        L.append("- 判定: ⚠️ **不同源** —— 造数据与训练各自读不同的集, 训练不会因为本次造数据而改变")
        L.append("  - 根因1: `stage_sim_data` 输出固定目录且收集器幂等(已满足 target 就报完成不重采) ⇒ 看着 rc=0 但没新样本")
        L.append("  - 根因2: `stage_train` 调 `joint_train_all.py` **不传数据集**, 训练用它配置里写死的 `dataset.root`")
        L.append("  - 修复: stage_train 增加 `--dataset data/datasets/sim_%s` 并让 joint_train_all 透传到 L3 训练配置" % TASK)
    L.append("")
    L.append("## 口径说明\n")
    L.append("- 数据是**平台仿真**造出来的 (metaworld 插拔环境按任务指令采样), 不是设备实拍; 设备级(专机)仿真不在现有 sim 内。")
    L.append("- 训练为有界步数 (steps=%s / yolo %s epoch / L5 %s 步), 用于全链贯通与档位对比, 不等于收敛训练量。" %
             (meta["steps"], meta["yolo_epochs"], meta["l5_steps"]))
    L.append("- 三档差异来自 `config/platform/zmax_product.json` + `zmax_compute_mode.py --apply` 的真切换 (推理后端/线程/训练开关)。")
    with open(os.path.join(evo_dir, "REPORT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return os.path.join(evo_dir, "REPORT.md")


def main():
    global TASK, SCENE
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--profiles", default="550A,550B,550C")
    ap.add_argument("--sim-target", type=int, default=10)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--yolo-epochs", type=int, default=3)
    ap.add_argument("--l5-steps", type=int, default=20)
    ap.add_argument("--task", default=TASK, help="要进化的任务 (默认 %s; AR 300UPH 用 TASK-07-AOI)" % TASK)
    a = ap.parse_args()
    TASK = a.task
    SCENE = scene_of(TASK)

    if a.status:
        if not os.path.isdir(EVO):
            print("还没有进化记录"); return 0
        last = sorted(os.listdir(EVO))[-1]
        p = os.path.join(EVO, last, "REPORT.md")
        print(open(p, encoding="utf-8").read() if os.path.exists(p) else "缺 REPORT.md")
        return 0

    if not a.run:
        print(__doc__); return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    evo_dir = os.path.join(EVO, ts)
    os.makedirs(evo_dir, exist_ok=True)
    base = profile_show()
    log("══ 自主进化开始 · 基线档位 = %s ══" % (base[0] if base else "?"))
    loops = stop_loops()
    results = []
    try:
        for pf in [x.strip() for x in a.profiles.split(",") if x.strip()]:
            log("▶ %s" % pf)
            results.append(run_profile(pf, a.sim_target, a.steps, a.yolo_epochs, a.l5_steps,
                                       skip_train=(pf == "550C"), run_dir=evo_dir))
            with open(os.path.join(evo_dir, "progress.json"), "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=1)
    finally:
        # 还原基线档位 (不擅自把系统留在 550A/550B)
        cur = profile_show()
        cur_pf = (cur[0].split()[0] if cur else "")
        if base and cur_pf and cur_pf not in (base[0].split()[0] if base else ""):
            log("↩ 还原基线档位 %s" % base[0].split()[0])
            sh(["tools/" + MODEL, "--apply", base[0].split()[0], "--no-vscode", "--no-train"], 900,
               os.path.join(evo_dir, "restore_profile.log"))
        start_loops(loops)
        meta = {"ts": ts, "profiles": a.profiles, "sim_target": a.sim_target, "steps": a.steps,
                "yolo_epochs": a.yolo_epochs, "l5_steps": a.l5_steps, "baseline": base}
        p = write_report(evo_dir, results, meta)
        log("✅ 进化报告 → %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
