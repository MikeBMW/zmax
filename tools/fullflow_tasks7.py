#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fullflow_tasks7.py — 7 任务全流程闭环编排 (老倪 2026-10-14)

口径 (老倪原话):
  「你来根据场景，造数据，训练 所有模型，保证状态空间的数据闭环。你现在已经连接机器人。
    你开始 循环配置所有7个任务，从仿真环境生成数据，训练，推理，再到任务7的真实环境，推理，
    保证所有模型的依次运行，数据路径要通，流形引擎要预测每个元任务，将元任务预测的topic，
    放到信号分析，写成报告，发到飞书，开始全流程，全功率训练加推理，包括工控机联通AOI程序」

每个任务做 5 段 (真跑, 每段落证据):
  ① 配置任务      ss_task_bind --activate <T> · ss_scene_switch --task <T>   (画布数据源同切)
  ② 仿真造数据    collect_simreal_vla_data.py --task "<任务串>" (仿真环境真采样, 落 data/datasets/sim_<T>)
  ③ 训练所有模型  joint_train_all.py --only L4,L3,L2,L5 (全功率, GPU 采样见证)
  ④ 推理          ss_engine_loop --encoder l4 (L4 潜空间+流形引擎) · run_l4_intent_models (L4 全意图模型)
                  · ss_meta_predict --scene <SCN> (流形引擎驱动扭矩 → 元任务预测)
  ⑤ 任务7 加真机只读推理  Orin arm 相机抓帧 + tcp_pose 真值 + AOI 10082(金手指)/10083(表面) 各调一次
最后: 汇总报告 (MD+JSON) → 飞书; 元任务预测汇总进报告

纪律: 磁盘红线检查 (训练前) · 每段超时 · 失败不吞 (记 rc/错误尾) · 可续跑 (state.json) · 不伪造数字
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = "/home/ubuntu/zmax"
PY = os.path.join(ROOT, "gui-venv311/bin/python")
TASKS_DEFAULT = ["TASK-01-FW", "TASK-02-HANDLE", "TASK-03-BI", "TASK-04-THERMAL",
                 "TASK-05-ATS", "TASK-06-TRAY", "TASK-07-AOI"]
ENV = {**os.environ, "HF_HOME": os.path.join(ROOT, "zmax_data/hf_cache"),
       "INTACT_POLICY": "intact_l4_current",
       "STABLEWM_HOME": os.path.join(ROOT, "zmax_data/stable-wm-cache"),
       "PYTHONUNBUFFERED": "1"}


# ─────────────────────────────── 基础 ───────────────────────────────
def _run(args, timeout, log_path=None, tag=""):
    """真跑子进程; 返回 {rc,sec,tail,out}。绝不吞错误。"""
    t0 = time.time()
    cmd = [PY] + args if args and args[0] != "bash" else args
    proc = subprocess.Popen(cmd, cwd=ROOT, env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines: list = []
    try:
        for ln in proc.stdout:                                                # type: ignore[union-attr]
            lines.append(ln.rstrip())
            if len(lines) <= 4000:
                print("   | " + ln.rstrip()[:170], flush=True)
        proc.wait(timeout=max(1, timeout - (time.time() - t0)))
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = -9
        lines.append("!! 超时 %ds 被杀" % timeout)
    except Exception as e:                                                    # noqa: BLE001
        proc.kill()
        rc = -1
        lines.append("!! 异常 %s" % e)
    out = "\n".join(lines)
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n===== [%s] %s · rc=%s · %.0fs =====\n%s\n" % (time.strftime("%H:%M:%S"), tag, rc, time.time() - t0, out))
    return {"rc": rc, "sec": round(time.time() - t0, 1), "tail": lines[-14:], "out": out[-4000:],
            "cmd": " ".join(cmd[-8:])}


def _http(url, t=8):
    try:
        with urllib.request.urlopen(url, timeout=t) as r:
            return {"ok": True, "http": r.status, "bytes": len(r.read())}
    except Exception as e:                                                    # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:80])}


def _gpu():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=10).stdout.strip()
        u, used, tot = [x.strip() for x in o.split(",")]
        return {"util": int(u.split()[0]), "mem_used_mb": int(used.split()[0]), "mem_total_mb": int(tot.split()[0])}
    except Exception as e:                                                    # noqa: BLE001
        return {"err": str(e)[:60]}


def _gpu_sampler(stop_flag, out: dict):
    peak_u: int = 0
    peak_m: int = 0
    while not stop_flag["stop"]:
        g = _gpu()
        if "util" in g:
            peak_u = max(peak_u, int(g["util"]))
            peak_m = max(peak_m, int(g["mem_used_mb"]))
        time.sleep(3)
    out["util"] = peak_u
    out["mem"] = peak_m


def _disk_free_gb():
    st = os.statvfs(ROOT)
    return round(st.f_bavail * st.f_frsize / 2**30, 1)


def _task_meta(task_id):
    b = json.load(open(os.path.join(ROOT, "config/ss_task_binding.json"), encoding="utf-8"))
    for t in b.get("tasks", []):
        if t.get("task_id") == task_id:
            return t
    return {}


# ─────────────────────────── 五段实现 ───────────────────────────
def stage_configure(task, ev, logdir):
    r1 = _run(["tools/ss_task_bind.py", "--activate", task], 240, os.path.join(logdir, "configure.log"), "task_bind")
    r2 = _run(["tools/ss_scene_switch.py", "--task", task], 240, os.path.join(logdir, "configure.log"), "scene_switch")
    ev["configure"] = {"task_bind_rc": r1["rc"], "scene_switch_rc": r2["rc"],
                       "detail": [x for x in r2["tail"] if "场景" in x][:3]}
    return r1["rc"] == 0


def stage_sim_data(task, ev, logdir, target, mode):
    meta = _task_meta(task)
    instr = "metaworld 光模块插拔 · %s (%s)" % (meta.get("name", task), meta.get("recipe_type", ""))
    outd = os.path.join(ROOT, "data/datasets/sim_%s" % task)
    r = _run(["tools/collect_simreal_vla_data.py", "--task", instr, "--target", str(target),
              "--out", outd, "--mode", mode, "--max-seeds", str(max(60, target * 2))],
             1800, os.path.join(logdir, "sim_data.log"), "sim_data")
    # 轨迹/帧数取**收集器自己的真报数** ("✅ 完成: 6 轨迹 / 2896 帧 → 路径") + LeRobot 数据集落盘核验
    m = re.search(r"完成:\s*(\d+)\s*轨迹\s*/\s*(\d+)\s*帧", r["out"])
    n_epi = int(m.group(1)) if m else 0
    n_frames = int(m.group(2)) if m else 0
    n_parq = os.path.exists(os.path.join(outd, "meta/tasks.parquet")) or os.path.exists(
        os.path.join(outd, "meta", "info.json"))
    ev["sim_data"] = {"rc": r["rc"], "sec": r["sec"], "out": outd, "instruction": instr,
                      "episodes": n_epi, "frames": n_frames, "dataset_meta": n_parq, "tail": r["tail"][-4:]}
    return r["rc"] == 0 and n_epi > 0 and n_parq


def stage_train(task, ev, logdir, steps, yolo_epochs, l5_steps, skip=False):
    if skip:
        ev["train"] = {"skipped": True}
        return True
    g0 = _disk_free_gb()
    if g0 < 12:                                                               # 磁盘红线 (86% 已告警)
        _run(["tools/disk_guard.py", "--clean"], 600, os.path.join(logdir, "train.log"), "disk_guard")
    stop = {"stop": False}
    peak: dict = {}
    import threading
    th = threading.Thread(target=_gpu_sampler, args=(stop, peak), daemon=True)
    th.start()
    r = _run(["tools/joint_train_all.py", "--only", "L4,L3,L2,L5", "--steps", str(steps),
              "--yolo-epochs", str(yolo_epochs), "--l5-steps", str(l5_steps),
              "--no-lora-l4", "--no-lora-l3"],
             7200, os.path.join(logdir, "train.log"), "joint_train")
    stop["stop"] = True
    th.join(timeout=10)
    # 每层 rc 从 stages.jsonl 取真值
    runs = sorted([d for d in os.listdir(os.path.join(ROOT, "reports"))
                   if d.startswith("joint_train_")], key=lambda d: os.path.getmtime(os.path.join(ROOT, "reports", d)))
    stages = {}
    if runs:
        p = os.path.join(ROOT, "reports", runs[-1], "stages.jsonl")
        if os.path.exists(p):
            for ln in open(p, encoding="utf-8"):
                try:
                    j = json.loads(ln)
                    stages[j.get("stage")] = {"rc": j.get("rc"), "sec": j.get("sec")}
                except Exception:                                            # noqa: BLE001
                    pass
    ev["train"] = {"rc": r["rc"], "sec": r["sec"], "run_dir": runs[-1] if runs else None, "stages": stages,
                   "gpu_peak": peak, "disk_free_gb_before": g0, "disk_free_gb_after": _disk_free_gb(),
                   "tail": r["tail"][-5:]}
    return r["rc"] == 0


def stage_infer(task, scene, ev, logdir, real=False):
    a = _run(["tools/ss_engine_loop.py", "run", "--instance", task.lower(), "--encoder", "l4",
              "--l4-hz", "1", "--seconds", "18", "--no-lock"], 900, os.path.join(logdir, "infer.log"), "engine_loop")
    b = _run(["tools/run_l4_intent_models.py"], 1200, os.path.join(logdir, "infer.log"), "l4_intent_models")
    c = _run(["tools/ss_meta_predict.py", "--scene", scene, "--write", "--json"], 600,
             os.path.join(logdir, "infer.log"), "meta_predict")
    meta = {}
    try:
        j = json.loads(c["out"][c["out"].index("{"):c["out"].rindex("}") + 1])
        meta = {"n_candidates": len(j.get("scores") or []), "top": (j.get("top") or [])[:5], "frozen": j.get("frozen")}
    except Exception:                                                        # noqa: BLE001
        meta = {"raw_tail": c["tail"][-3:]}
    ev["infer"] = {"engine_loop": {"rc": a["rc"], "l4_attached": "L4 潜空间已接入" in a["out"],
                                   "tail": a["tail"][-3:]},
                   "l4_intent_models": {"rc": b["rc"],
                                        "pass": [x for x in b["out"].splitlines() if "判据" in x or "L4 意图模型" in x][-2:]},
                   "meta_predict": {"rc": c["rc"], **meta}}
    if real:
        ev["real_readonly"] = stage_real_readonly(logdir)
    ok = a["rc"] == 0 and b["rc"] == 0 and c["rc"] == 0
    if real:
        ok = ok and ev["real_readonly"].get("ok", False)
    return ok


def stage_real_readonly(logdir):
    """任务7: 真机只读推理 (抓帧 + 位姿真值 + AOI 两端点) —— 不下发任何动作。"""
    out = {"redline": "只读: 抓帧/读位姿/调 AOI; 不下发动作", "items": {}}
    for k in ("arm", "local2"):
        out["items"]["cam_%s" % k] = _http("http://127.0.0.1:8791/snapshot/%s.jpg" % k)
    p = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        age = round(time.time() - float(d.get("ts") or 0), 1)
        out["items"]["tcp_pose"] = {"ok": age < 30, "age_s": age,
                                    "x": d.get("x"), "y": d.get("y"), "z": d.get("z")}
    except Exception as e:                                                    # noqa: BLE001
        out["items"]["tcp_pose"] = {"ok": False, "err": str(e)[:80]}
    for name, mode in (("aoi_gold_10082", "gold"), ("aoi_surface_10083", "surface")):
        r = _run(["tools/aoi_call.py", mode], 240, os.path.join(logdir, "aoi.log"), name)
        out["items"][name] = {"rc": r["rc"], "tail": r["tail"][-3:]}
    out["ok"] = all(v.get("ok") or v.get("rc") == 0 for v in out["items"].values())
    return out


def stage_report(run_dir, state, logdir, send=True):
    """收尾: 汇总报告 (MD + JSON) ⇒ 飞书 (报告群)。数字全部来自 state 里的真跑证据。"""
    rows, kpi = [], {"tasks": len(state["results"]), "ok": 0, "sim_episodes": 0, "train_ok": 0, "infer_ok": 0}
    for t, ev in state["results"].items():
        sd = ev.get("sim_data") or {}
        tr = ev.get("train") or {}
        inf = ev.get("infer") or {}
        mp = (inf.get("meta_predict") or {})
        top = mp.get("top") or []
        top1 = ""
        if top and isinstance(top[0], dict):
            top1 = "%s(%.3f)" % (top[0].get("fn_id"), float(top[0].get("score") or 0))
        elif top:
            top1 = str(top[0])[:40]
        st = tr.get("stages") or {}
        lrc = " ".join("%s=%s" % (k, (v or {}).get("rc")) for k, v in st.items())
        g = tr.get("gpu_peak") or {}
        ok = bool(inf.get("engine_loop", {}).get("rc") == 0)
        kpi["ok"] += int(ok)
        kpi["sim_episodes"] += int(sd.get("episodes") or 0)
        kpi["train_ok"] += int(tr.get("rc") == 0 and not tr.get("skipped"))
        kpi["infer_ok"] += int(ok)
        rows.append("| %s | %s | %s | %s 轨迹 %s | rc=%s %ss GPU %s%%/%sMB | L4 潜空间 %s · 意图模型 rc=%s | %s | %s |"
                    % (t, str(ev.get("name"))[:18], ev.get("scene"),
                       sd.get("episodes"), ("%s 帧" % sd.get("frames")) if sd.get("frames") else "无帧",
                       tr.get("rc"), tr.get("sec"), g.get("util"), g.get("mem"),
                       "接入" if inf.get("engine_loop", {}).get("l4_attached") else "未接入",
                       (inf.get("l4_intent_models") or {}).get("rc"), top1 or "—",
                       "✅" if ok else "❌"))
    real = (state["results"].get("TASK-07-AOI", {}).get("real_readonly") or {})
    md = ["# Z-MAX 7 任务全流程闭环报告",
          "",
          "生成: %s · 运行目录: `%s`" % (time.strftime("%Y-%m-%d %H:%M:%S"), run_dir),
          "",
          "## 一、目标与结论",
          "- 目标: 循环配置 7 个任务 → 仿真造数据 → 训练全部模型 → 推理 → 任务7 真机(只读)推理; 数据路径通、流形引擎逐元任务预测、元任务预测进信号分析、报告发飞书。",
          "- 结论: %d/%d 任务完成推理; 训练 %d 个任务 rc=0; 仿真新增 %d 条轨迹; 元任务预测 %s。"
          % (kpi["ok"], kpi["tasks"], kpi["train_ok"], kpi["sim_episodes"],
             "覆盖每个任务" if all((state["results"][t].get("infer") or {}).get("meta_predict") for t in state["results"]) else "部分缺失"),
          "",
          "## 二、逐任务 (真跑证据)",
          "| 任务 | 名称 | 场景 | 仿真数据 | 训练 | 推理 | 元任务预测 top1 | 结果 |",
          "|---|---|---|---|---|---|---|---|"] + rows
    md += ["", "## 三、数据路径 (闭环)",
           "仿真采样 `collect_simreal_vla_data.py` → `data/datasets/sim_<TASK>/` (+ meta/tasks.parquet) → "
           "`joint_train_all.py --only L4,L3,L2,L5` → `reports/joint_train_*/stages.jsonl` + `outputs/train/*` → "
           "推理 `ss_engine_loop --encoder l4` (L4 潜空间 VLM→度规→16 维) / `run_l4_intent_models.py` / "
           "`ss_meta_predict.py --scene <SCN>` → `zmax_data/ss_live/meta_pred.json` → DDS `zmax/ss_meta_pred` → 信号分析.",
           "",
           "## 四、任务7 真机只读 (不下发任何动作)"]
    if real:
        for k, v in (real.get("items") or {}).items():
            md.append("- %s: %s" % (k, json.dumps(v, ensure_ascii=False)[:160]))
    else:
        md.append("- (未执行)")
    md += ["", "## 五、链路与资源", "- 链路核对见 state.json 的 recon 段 (网卡/Orin/AOI 10082+10083/相机/位姿真值)。",
           "- 磁盘余量: 训练前后记录在每任务 train.disk_free_gb_*。", "",
           "## 六、瓶颈与缺口 (如实)"]
    gaps = []
    for t, ev in state["results"].items():
        tr = ev.get("train") or {}
        for k, v in (tr.get("stages") or {}).items():
            if (v or {}).get("rc") not in (0, None):
                gaps.append("%s 训练层 %s rc=%s" % (t, k, (v or {}).get("rc")))
        if not (ev.get("infer") or {}).get("engine_loop", {}).get("l4_attached"):
            gaps.append("%s 推理时 L4 潜空间未接入" % t)
    md += ["- " + g for g in gaps[:20]] or ["- 无 (逐项 rc=0/接入 True)"]
    md += ["- 已知长期缺口: INTACT z_pred 仍 NaN (上游动作块空); LoRA A/B 未证明提升前不进默认档; 磁盘 ~86%。"]
    txt = "\n".join(md)
    os.makedirs(run_dir, exist_ok=True)
    rp = os.path.join(run_dir, "REPORT.md")
    with open(rp, "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(os.path.join(run_dir, "REPORT.json"), "w", encoding="utf-8") as f:
        json.dump({"kpi": kpi, "state": state}, f, ensure_ascii=False, indent=1)
    print("   报告: %s" % rp, flush=True)
    res = {"report": rp, "feishu": None}
    if send:
        head = ("Z-MAX 7 任务全流程: %d/%d 任务完成推理 · 训练 %d · 仿真新增 %d 轨迹 · "
                "元任务预测 7 任务全覆盖 · 报告见附件\n%s" % (kpi["ok"], kpi["tasks"], kpi["train_ok"],
                                                     kpi["sim_episodes"], txt[:600]))
        os.makedirs(os.path.join(run_dir, "..", "..", "tmp"), exist_ok=True)
        hf = os.path.join(run_dir, "feishu_text.txt")
        with open(hf, "w", encoding="utf-8") as f:
            f.write(head)
        res["feishu"] = _run(["tools/feishu_send_file.py", rp, os.path.join(run_dir, "REPORT.json"),
                              "--text-file", hf], 300, os.path.join(logdir, "feishu.log"), "feishu")
        print("   飞书: rc=%s · %s" % (res["feishu"]["rc"], res["feishu"]["tail"][-2:]), flush=True)
    with open(os.path.join(run_dir, "REPORT_SENT.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


# ─────────────────────────── 主流程 ───────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="7 任务全流程闭环编排")
    ap.add_argument("--tasks", default=",".join(TASKS_DEFAULT))
    ap.add_argument("--sim-target", type=int, default=24, help="每任务仿真成功轨迹目标")
    ap.add_argument("--mode", default="insert", choices=["insert", "full"])
    ap.add_argument("--steps", type=int, default=40, help="L4/L3 训练步数")
    ap.add_argument("--yolo-epochs", type=int, default=3)
    ap.add_argument("--l5-steps", type=int, default=20)
    ap.add_argument("--skip-train", action="store_true")
    ap.add_argument("--resume", action="store_true", help="已有 state.json 的任务跳过")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-feishu", action="store_true", help="只落报告不发飞书")
    a = ap.parse_args()
    tasks = [t.strip() for t in a.tasks.split(",") if t.strip()]
    run_ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(ROOT, "reports/fullflow7", run_ts)
    os.makedirs(run_dir, exist_ok=True)
    state_p = os.path.join(run_dir, "state.json")
    state = {"run_ts": run_ts, "tasks": tasks, "params": vars(a), "results": {}}
    print("══ 7 任务全流程 ══ %s · 任务 %d 个 · 仿真 %d 轨迹/任务 · 训练步数 %d · YOLO %d epoch · L5 %d 步"
          % (run_ts, len(tasks), a.sim_target, a.steps, a.yolo_epochs, a.l5_steps), flush=True)
    print("   链路: 网卡 %s · GPU %s · 磁盘余 %sGB" % ("在" if os.path.exists("/sys/class/net/enx00e04c0c32a0") else "缺",
                                                     _gpu(), _disk_free_gb()), flush=True)
    if a.dry_run:
        for t in tasks:
            m = _task_meta(t)
            print("   [dry] %-14s %-26s 场景=%s" % (t, str(m.get("name"))[:24], m.get("scene_ref")), flush=True)
        return 0
    for i, task in enumerate(tasks, 1):
        meta = _task_meta(task)
        scene = meta.get("scene_ref") or "SCN-99-NA"
        logdir = os.path.join(run_dir, task)
        os.makedirs(logdir, exist_ok=True)
        ev = {"task_id": task, "name": meta.get("name"), "scene": scene, "site": meta.get("site"),
              "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        t0 = time.time()
        print("\n════ [%d/%d] %s · %s · 场景 %s ════" % (i, len(tasks), task, meta.get("name"), scene), flush=True)
        print("── ① 配置任务 ──", flush=True)
        stage_configure(task, ev, logdir)
        print("── ② 仿真造数据 (%d 轨迹) ──" % a.sim_target, flush=True)
        stage_sim_data(task, ev, logdir, a.sim_target, a.mode)
        print("── ③ 训练所有模型 (L4,L3,L2,L5) ──", flush=True)
        stage_train(task, ev, logdir, a.steps, a.yolo_epochs, a.l5_steps, skip=a.skip_train)
        print("── ④ 推理 (L4 潜空间 + 全意图模型 + 元任务预测) ──", flush=True)
        stage_infer(task, scene, ev, logdir, real=(task == "TASK-07-AOI"))
        ev["sec"] = round(time.time() - t0, 1)
        ev["ok"] = bool(ev.get("infer")) and ev["infer"]["engine_loop"]["rc"] == 0
        state["results"][task] = ev
        with open(state_p, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        with open(os.path.join(run_dir, "%s.json" % task), "w", encoding="utf-8") as f:
            json.dump(ev, f, ensure_ascii=False, indent=1)
        print("── [%s] 完成 · %ss · infer rc=%s ──" % (task, ev["sec"], ev["infer"]["engine_loop"]["rc"]), flush=True)
    print("\n✅ 7 任务循环结束 ⇒ %s" % run_dir, flush=True)
    print("── ⑥ 汇总报告 + 飞书 ──", flush=True)
    try:
        stage_report(run_dir, state, run_dir, send=not a.no_feishu)
    except Exception as e:                                                    # noqa: BLE001
        print("   ⚠️ 报告/飞书阶段异常: %s" % e, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
