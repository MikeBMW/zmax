#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evolve_ar_world.py — AR 场景「自造数据 → 训练 → 同源评测 → 择优晋级」自主进化编排器 (550A)

老倪 2026-11-04: 「状态空间所有模型要打通; 结合 AR 场景, 自动生成数据, 自己进化」

一轮 = 
  ① 造数据  tools/ar_mujoco_clutter.py  → 本代独立数据集 (MuJoCo AR 工位渲染, 标签=金色像素主连通域)
  ② 训练    tools/ar_yolo_train_eval.py → L2 检测器 (在役权重为起点, 4060 CUDA)
  ③ 评测    同一权重跑**固定留出集**: hc=带干扰件(有提升空间) / legacy=干净(不许回退)
  ④ 晋级    只有 hc.map50 > 历史最好 + margin, 且 legacy 不回退, 才换 zmax_data/ar_evolve/best.pt
            并把 models/yolo_ar_evolve.pt 指过去; **在役 yolo_peg_live.pt 一律不碰**
  ⑤ 全层    可选: fullflow_tasks7 (L4/L3/L5 真训练+推理) + pipeline_closure_run (六节点闭环)
  ⑥ 报告    reports/evolution_ar/<ts>/evolution.json|REPORT.md + 飞书 (intel 侧网关)

纪律
  · 每代数字都来自真跑; 缺一项就写 null 并标「未测」, 不假 0。
  · 晋级是**加法**: 旧 best 留档, 台账 ledger.json 追加一行 (可回滚)。
  · 训练前只让出**自身常驻回路**的显存 (sam3 懒服务), 不碰执行腿/授权链。

用法
  python tools/evolve_ar_world.py --rounds 2 --n 200 --clutter 4 --epochs 15
  python tools/evolve_ar_world.py --status
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
PY = os.path.join(ROOT, "gui-venv311/bin/python")
AR = os.path.join(ROOT, "zmax_data/ar_evolve")
LEDGER = os.path.join(AR, "ledger.json")
HOLDOUT_HC = os.path.join(AR, "holdout_clutter/data.yaml")
HOLDOUT_LEGACY = os.path.join(ROOT, "zmax_data/ar_mujoco/holdout/data.yaml")
LIVE_AR = os.path.join(ROOT, "models/yolo_ar_peg.pt")   # 在役 (只读, 绝不覆盖)
EVOLVE_PTR = os.path.join(ROOT, "models/yolo_ar_evolve.pt")
CUR = os.path.join(AR, "best.pt")                       # 当前进化最优
ENV_GL = {"MUJOCO_GL": "glfw", "DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/gdm/Xauthority"}


def log(msg: str) -> None:
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def sh(cmd, timeout=7200, env=None):
    t0 = time.time()
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=e)
    return {"rc": p.returncode, "sec": round(time.time() - t0, 1),
            "out": (p.stdout or "")[-2500:], "err": (p.stderr or "")[-2500:]}


def load_ledger():
    try:
        return json.load(open(LEDGER, encoding="utf-8"))
    except Exception:                                                       # noqa: BLE001
        return {"generations": [], "best": None}


def save_ledger(d):
    os.makedirs(AR, exist_ok=True)
    tmp = LEDGER + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, LEDGER)


def gpu():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                            "--format=csv,noheader"], capture_output=True, text=True, timeout=10).stdout
        u, used, tot = [x.strip() for x in o.strip().split(",")]
        return {"util": int(u.split()[0]), "used_mb": int(used.split()[0]), "total_mb": int(tot.split()[0])}
    except Exception as e:                                                  # noqa: BLE001
        return {"err": str(e)[:60]}


SHED_UNITS = ["zmax-ss-canvas-loop.service"]      # 画布常驻回路 (实测占 2.2GB, 训完起回)


def free_gpu(stop_lazy=True):
    """让出显存: 停画布常驻回路 + 懒加载的 sam3 (都是可秒起回的只读回路), 记录以便回起。

    8GB 卡上引擎(1.8G)+画布(2.2G)+INTACT(1.3G)常驻 ⇒ 训练必然 OOM。
    只动这两个**自身只读回路**, 不碰执行腿/授权链/位姿中继。
    """
    stopped = []
    if not stop_lazy:
        return stopped
    for u in SHED_UNITS:
        try:
            st = subprocess.run(["systemctl", "is-active", u], capture_output=True, text=True).stdout.strip()
            if st == "active":
                # 服务态里没有交互 tty ⇒ 必须 sudo -n (本机 sudo 免密); 失败要吵出来, 不能当已停
                p = subprocess.run(["sudo", "-n", "systemctl", "stop", u], capture_output=True, text=True, timeout=60)
                if p.returncode == 0:
                    stopped.append({"unit": u})
                else:
                    log("free_gpu 警告: 停 %s 失败 rc=%s %s" % (u, p.returncode, (p.stderr or "")[:120]))
        except Exception as e:                                              # noqa: BLE001
            log("free_gpu 警告(%s): %s" % (u, e))
    try:
        out = subprocess.run(["pgrep", "-f", "sam3_seg.py --serve"], capture_output=True, text=True).stdout
        for pid in [int(x) for x in out.split() if x.strip().isdigit()]:
            cmd = open("/proc/%d/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
            subprocess.run(["kill", "-TERM", str(pid)], timeout=10)
            stopped.append({"pid": pid, "cmd": cmd})
    except Exception as e:                                                  # noqa: BLE001
        log("free_gpu 警告: %s" % e)
    if stopped:
        time.sleep(3)
        log("让出显存: %s" % json.dumps(stopped, ensure_ascii=False)[:200])
    return stopped


def restore_gpu(stopped):
    """训练结束把让出的回路起回 (只起自己刚停的, 不碰别的)。"""
    for s in stopped or []:
        try:
            if s.get("unit"):
                subprocess.run(["sudo", "-n", "systemctl", "start", s["unit"]], timeout=90)
            elif s.get("pid"):
                subprocess.Popen(s["cmd"], shell=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        except Exception as e:                                              # noqa: BLE001
            log("restore_gpu 警告: %s" % e)
    if stopped:
        log("已起回: %s" % json.dumps([s.get("unit") or s.get("pid") for s in stopped], ensure_ascii=False))


def gpu_sample(stop, out, peak):
    while not stop.get("stop"):
        g = gpu()
        if "util" in g:
            peak["util"] = max(peak.get("util", 0), g["util"])
            peak["mem_mb"] = max(peak.get("mem_mb", 0), g["used_mb"])
        time.sleep(3)


def run_generation(g: int, a, ledger) -> dict:
    ts = time.strftime("%Y%m%d_%H%M%S")
    gdir = os.path.join(AR, "gen_%02d_%s" % (g, ts))
    os.makedirs(gdir, exist_ok=True)
    seed_data = 70000 + g * 137
    base = CUR if os.path.exists(CUR) else LIVE_AR
    rec = {"gen": g, "ts": ts, "dir": gdir, "seed_data": seed_data, "clutter": a.clutter,
           "base": base, "n": a.n, "epochs": a.epochs, "stages": {}}

    # ① 造数据
    log("① 造数据 clutter=%d n=%d seed=%d" % (a.clutter, a.n, seed_data))
    ds = os.path.join(gdir, "ds")
    r = sh([PY, "tools/ar_mujoco_clutter.py", "--gen", "--n", str(a.n), "--clutter", str(a.clutter),
            "--seed", str(seed_data), "--out", ds], timeout=3600, env=ENV_GL)
    meta = {}
    try:
        meta = json.load(open(os.path.join(ds, "meta.json"), encoding="utf-8"))
    except Exception:                                                       # noqa: BLE001
        pass
    rec["stages"]["data"] = {"rc": r["rc"], "sec": r["sec"], "stats": meta.get("stats"),
                             "box_w_px": meta.get("box_w_px"), "err": None if r["rc"] == 0 else r["err"][-400:]}
    if r["rc"] != 0 or not meta.get("stats", {}).get("kept"):
        rec["ok"] = False
        rec["error"] = "造数据失败"
        return rec

    # train.yaml: train=本代, val=固定带干扰件留出集的 **images 目录** (ultralytics 只认目录/相对路径,
    # 写 yaml 路径会报 "Error loading data ... data.yaml" ⇒ 最终数字统一由 ③ 的独立 val 给)
    tdy = os.path.join(gdir, "train.yaml")
    open(tdy, "w", encoding="utf-8").write(
        "path: %s\ntrain: images\nval: %s/images\nnames:\n  0: gold_module\n"
        % (ds, os.path.dirname(HOLDOUT_HC)))

    # ② 训练 + ③ 评测 (同一进程, 同一权重)
    log("②③ 训练 %d epoch + 固定留出集评测 (base=%s)" % (a.epochs, os.path.basename(base)))
    stopped = free_gpu(a.free_gpu)
    rec["gpu_before"] = gpu()
    jout = os.path.join(gdir, "train_eval.json")
    t0 = time.time()
    r = sh([PY, "tools/ar_yolo_train_eval.py", "--base", base, "--data", tdy,
            "--epochs", str(a.epochs), "--batch", str(a.batch), "--project", gdir, "--name", "train",
            "--out", jout, "--eval", "hc=" + HOLDOUT_HC, "--eval", "legacy=" + HOLDOUT_LEGACY,
            "--seed", str(g)], timeout=7200)
    rec["stages"]["train_eval"] = {"rc": r["rc"], "sec": r["sec"], "err": None if r["rc"] == 0 else r["err"][-600:]}
    try:
        te = json.load(open(jout, encoding="utf-8"))
    except Exception as e:                                                  # noqa: BLE001
        te = {"ok": False, "error": "读不到 %s: %s" % (jout, e)}
    rec["train_eval"] = {k: te.get(k) for k in ("ok", "weights", "train_sec", "train_last_row", "eval", "error")}
    restore_gpu(stopped)
    rec["gpu_after"] = gpu()
    rec["free_gpu_stopped"] = stopped
    if not te.get("ok"):
        rec["ok"] = False
        rec["error"] = te.get("error") or "训练/评测失败"
        return rec

    hc = te["eval"]["hc"]
    lg = te["eval"]["legacy"]
    rec["score"] = {"hc_map50": hc["map50"], "hc_precision": hc["precision"], "hc_recall": hc["recall"],
                    "legacy_map50": lg["map50"]}

    # ④ 晋级门禁 (两把尺都要过)
    prev = ledger.get("best") or {}
    prev_hc = prev.get("hc_map50")
    prev_lg = prev.get("legacy_map50")
    improved = prev_hc is None or hc["map50"] >= float(prev_hc) + a.margin
    no_regress = prev_lg is None or lg["map50"] >= float(prev_lg) - a.no_regress_tol
    rec["gate"] = {"prev_hc": prev_hc, "prev_legacy": prev_lg, "margin": a.margin,
                   "improved": improved, "no_regress": no_regress,
                   "verdict": "promote" if (improved and no_regress) else "keep"}
    if improved and no_regress and te.get("weights"):
        keep = os.path.join(AR, "weights", "gen_%02d_%s.pt" % (g, ts))
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        shutil.copyfile(te["weights"], keep)
        if os.path.exists(CUR):
            shutil.copyfile(CUR, os.path.join(AR, "weights", "superseded_" + ts + ".pt"))
        shutil.copyfile(keep, CUR)
        try:
            if os.path.islink(EVOLVE_PTR) or os.path.exists(EVOLVE_PTR):
                os.unlink(EVOLVE_PTR)
            os.symlink(os.path.relpath(CUR, os.path.dirname(EVOLVE_PTR)), EVOLVE_PTR)
        except Exception as e:                                              # noqa: BLE001
            rec["gate"]["symlink_err"] = str(e)[:200]
        ledger["best"] = {"gen": g, "ts": ts, "weights": keep, "hc_map50": hc["map50"],
                          "hc_precision": hc["precision"], "hc_recall": hc["recall"],
                          "legacy_map50": lg["map50"], "base": base}
        rec["promoted"] = keep
        log("✅ 晋级: hc_map50 %.4f (prev %s) · legacy %.4f" % (hc["map50"], prev_hc, lg["map50"]))
    else:
        rec["promoted"] = None
        log("⏸ 不晋级: hc %.4f vs prev %s (improved=%s no_regress=%s)"
            % (hc["map50"], prev_hc, improved, no_regress))
    rec["ok"] = True
    return rec


def fullflow(a, gdir) -> dict:
    log("⑤ 全层: fullflow_tasks7 (L4/L3/L2/L5 真训练+推理, AR 任务)")
    r = sh([PY, "tools/fullflow_tasks7.py", "--tasks", a.fullflow_task, "--sim-target", str(a.sim_target),
            "--steps", str(a.steps), "--yolo-epochs", str(a.yolo_epochs), "--l5-steps", str(a.l5_steps),
            "--no-feishu"], timeout=5400)
    return {"rc": r["rc"], "sec": r["sec"], "tail": r["out"][-1200:]}


def pipeline(a, gdir) -> dict:
    log("⑤ 全层: pipeline_closure_run (六节点闭环真跑)")
    r = sh([PY, "tools/pipeline_closure_run.py", "--seed", "104", "--vote"], timeout=1800)
    return {"rc": r["rc"], "sec": r["sec"], "tail": r["out"][-1200:]}


def report(a, rounds, extra) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    od = os.path.join(ROOT, "reports", "evolution_ar", ts)
    os.makedirs(od, exist_ok=True)
    led = load_ledger()
    doc = {"ts": ts, "rounds": rounds, "params": vars(a), "extra": extra,
           "best": led.get("best"), "generations": led.get("generations", [])[-12:]}
    json.dump(doc, open(os.path.join(od, "evolution.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    lines = ["# AR 场景自主进化 · %s" % ts, "",
             "口径: 造数据=MuJoCo AR 工位渲染(标签=金色像素主连通域, 像素级真值); "
             "评测=固定留出集 hc(6 干扰件)/legacy(干净); 晋级须 hc 提升 ≥ %.3f 且 legacy 不回退 > %.3f"
             % (a.margin, a.no_regress_tol), ""]
    b = led.get("best") or {}
    lines += ["## 当前最优", "",
              "- gen %s · hc mAP50 **%s** · hc P %s / R %s · legacy mAP50 %s"
              % (b.get("gen", "—"), b.get("hc_map50", "未测"), b.get("hc_precision", "未测"),
                 b.get("hc_recall", "未测"), b.get("legacy_map50", "未测")),
              "- 权重: `%s` · 指针 `%s`" % (b.get("weights", "—"), EVOLVE_PTR), "",
              "## 逐代台账", "",
              "| gen | 数据 kept | 训练耗时 | hc mAP50 | hc P | legacy mAP50 | 结论 |",
              "|---|---|---|---|---|---|---|"]
    for r in (led.get("generations") or [])[-12:]:
        s = r.get("score") or {}
        lines.append("| %s | %s | %ss | %s | %s | %s | %s |" % (
            r.get("gen"), (r.get("stages", {}).get("data") or {}).get("stats", {}).get("kept", "—"),
            (r.get("stages", {}).get("train_eval") or {}).get("sec", "—"),
            s.get("hc_map50", "未测"), s.get("hc_precision", "未测"), s.get("legacy_map50", "未测"),
            "晋级" if r.get("promoted") else ("失败" if r.get("ok") is False else "保持")))
    for k, v in (extra or {}).items():
        lines += ["", "## %s" % k, "```", json.dumps(v, ensure_ascii=False)[:1500], "```"]
    md = os.path.join(od, "REPORT.md")
    open(md, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return md


def send_feishu(md, a) -> dict:
    if a.no_feishu:
        return {"skipped": True}
    r = sh(["/usr/bin/python3", "tools/feishu_send_file.py", "--text", "AR 自主进化报告", md], timeout=120)
    md_id = ""
    for line in (r["out"] + r["err"]).splitlines():
        if "message_id" in line:
            md_id = line.strip()
    return {"rc": r["rc"], "msg": md_id or (r["out"] + r["err"])[-300:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1, help="0=无限自主进化 (常驻服务)")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--clutter", type=int, default=4)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--margin", type=float, default=0.004)
    ap.add_argument("--no-regress-tol", type=float, default=0.005)
    ap.add_argument("--cooldown", type=int, default=30)
    ap.add_argument("--free-gpu", type=int, default=1)
    ap.add_argument("--fullflow", type=int, default=1)
    ap.add_argument("--pipeline", type=int, default=0,
                    help="1=跑 pipeline_closure_run 六节点闭环 (吃 2GB 显存且耗时长, 默认关)")
    ap.add_argument("--fullflow-every", type=int, default=1)
    ap.add_argument("--fullflow-task", default="TASK-07-AOI")
    ap.add_argument("--sim-target", type=int, default=10)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--yolo-epochs", type=int, default=3)
    ap.add_argument("--l5-steps", type=int, default=20)
    ap.add_argument("--no-feishu", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    led = load_ledger()
    if a.status:
        print(json.dumps({"best": led.get("best"), "n_gen": len(led.get("generations") or []),
                          "last": (led.get("generations") or [{}])[-1]}, ensure_ascii=False, indent=1)[:3000])
        return 0

    os.makedirs(AR, exist_ok=True)
    log("进化开始: rounds=%d n=%d clutter=%d epochs=%d base=%s"
        % (a.rounds, a.n, a.clutter, a.epochs, os.path.basename(CUR if os.path.exists(CUR) else LIVE_AR)))
    extra = {}
    # 代次接着台账走 (服务重启后不从 1 重来): 保证每代的**数据 seed 都不同**, 否则反复训同一批
    i = len(led.get("generations") or [])
    done = 0
    last_md = ""
    while True:                       # a.rounds<=0 ⇒ 无限自主进化 (常驻服务用)
        i += 1
        done += 1
        rec = run_generation(i, a, led)
        led.setdefault("generations", []).append(rec)
        save_ledger(led)
        if a.fullflow and (i % max(1, a.fullflow_every) == 0):
            extra["fullflow_gen%d" % i] = fullflow(a, rec["dir"])
            led["generations"][-1]["fullflow"] = {"rc": extra["fullflow_gen%d" % i]["rc"],
                                                  "sec": extra["fullflow_gen%d" % i]["sec"]}
            save_ledger(led)
        if i == 1 and a.pipeline:
            extra["pipeline"] = pipeline(a, rec["dir"])
            led["generations"][-1]["pipeline"] = {"rc": extra["pipeline"]["rc"],
                                                  "sec": extra["pipeline"]["sec"]}
            save_ledger(led)
        infinite = a.rounds <= 0
        if infinite or done >= a.rounds:
            last_md = report(a, i, {k: v for k, v in extra.items() if k.endswith("gen%d" % i)})
            # 飞书节流: 晋级/失败必发; 无限模式其余每 6 代发一次 (否则 42 条/天刷屏)
            must = (not infinite) or bool(rec.get("promoted")) or (rec.get("ok") is False)
            fe = send_feishu(last_md, a) if (must or i % 6 == 0) else {"throttled": True}
            log("报告: %s · 飞书: %s" % (last_md, json.dumps(fe, ensure_ascii=False)[:160]))
            if not infinite:
                print(json.dumps({"report": last_md, "feishu": fe,
                                  "best": load_ledger().get("best")}, ensure_ascii=False))
                return 0
        log("冷却 %ds" % a.cooldown)
        time.sleep(a.cooldown)


if __name__ == "__main__":
    sys.exit(main())
