#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📊 模型资产 + 算力状态 只读采集器 (给『模型引擎』页供数)

为什么存在: 『模型引擎』页需要"实时"地看到四层模型(L5认知/L4世界模型/L3动作/L2检测)的
权重现状 + 与本机 GPU 的真实同步 + 当前有没有训练在跑。之前这些口径散落在各脚本里、
靠人肉 ls,既容易过期也容易写死。本工具**只读**地把它们统一采一遍,输出固定字段,
页/编排器直接吃 JSON。

设计红线 (与老倪工程约束一致):
  * 只读: 不写任何已有文件、不启动/停止训练、不杀进程、不发真机指令、不联网。
    唯一会落盘的是 --json-out <path> (调用者显式指定才写)。
  * 全部实时采集, 不写死任何数值: GPU 走 nvidia-smi; 训练进程走 ps; 模型/报告走文件系统 stat。
  * 采集失败必须显式报错 (error 字段), 不允许留空静默 —— 页上"空"和"坏了"是两回事。

用法:
  python3 tools/model_inventory.py                 # 人读表格
  python3 tools/model_inventory.py --json          # 结构化 (stdout)
  python3 tools/model_inventory.py --json-out f.json
  python3 tools/model_inventory.py --reports-n 20  # 报告取最近 N 条 (默认 15)

字段 (固定): {generated_at, gpu:{util,mem_used,mem_total,temp,power,procs[]},
              training:[{layer,pid,elapsed_s,progress}],
              models:[{layer,name,path,size,mtime,report,last_train}],
              reports:[...]}
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(ROOT, "reports")
ACTIVE_JSON = os.path.join(ROOT, "models", "active_models.json")

# 四层: 数值来源 = active_models.json 的在役指针 (真源); 找不到就回退到目录扫描
LAYERS = ["L5", "L4", "L3", "L2"]
LAYER_DESC = {
    "L5": "VLM 认知 (SmolVLM2 LoRA/merged)",
    "L4": "INTACT 世界模型 (意图-动作)",
    "L3": "SmolVLA+LEW 动作策略",
    "L2": "YOLO 光模块检测",
}


# ---------------------------------------------------------------- 小工具
def _run(cmd: list, timeout: int = 30) -> tuple:
    """跑子进程, 返回 (rc, stdout, stderr)。绝不抛异常 —— 采集器要能容错。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        return 127, "", f"FileNotFoundError: {e}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except Exception as e:  # noqa: BLE001 - 采集器不允许因单个异常整体崩
        return 1, "", f"{type(e).__name__}: {e}"


def _now_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


def _num(s):
    """把 nvidia-smi 的值 (可能带单位/可能是 [N/A]) 转成数字; 转不了返回 None。"""
    if s is None:
        return None
    s = str(s).strip()
    m = re.search(r"-?[0-9]+(?:\.[0-9]+)?", s)
    return float(m.group(0)) if m else None


def _stat(path: str) -> dict:
    """返回存在的文件的 size(bytes)/mtime(iso); 不存在则 exists=False (不报错, 是"缺"不是"坏")。"""
    try:
        st = os.stat(path)          # 跟随软链取真实目标的大小/时间 (在役 L2 是软链)
        return {
            "exists": True,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "mtime_epoch": st.st_mtime,
        }
    except OSError:
        return {"exists": False, "size": None, "mtime": None, "mtime_epoch": None}


def _dir_size(path: str) -> int:
    """目录内文件字节和 (浅层即可, 这些模型目录都是扁平的)。"""
    total = 0
    try:
        for name in os.listdir(path):
            fp = os.path.join(path, name)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    except OSError:
        pass
    return total


# ---------------------------------------------------------------- 1) GPU
def collect_gpu() -> dict:
    """实时采 GPU: 调 nvidia-smi。字段全部来自真实输出; 失败置 error 而不留空。"""
    gpu = {"ts": _now_iso()}
    rc, out, err = _run([
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,"
        "power.draw,power.limit",
        "--format=csv,noheader,nounits",
    ])
    if rc != 0 or not out.strip():
        gpu["error"] = (err or out or "nvidia-smi returned empty").strip()
        gpu["procs"] = []
        return gpu
    gpu["raw_csv"] = out.strip()
    line = out.strip().splitlines()[0]
    cols = [c.strip() for c in line.split(",")]
    # 列序与上面 query 一一对应: idx,name,util,mem_used,mem_total,temp,power,power_limit
    gpu["index"] = int(_num(cols[0]) or 0)
    gpu["name"] = cols[1]
    gpu["util"] = _num(cols[2])          # %
    gpu["mem_used"] = _num(cols[3])      # MiB
    gpu["mem_total"] = _num(cols[4])     # MiB
    gpu["temp"] = _num(cols[5])          # C
    gpu["power"] = _num(cols[6])         # W
    gpu["power_limit"] = _num(cols[7])   # W (笔记本常为 N/A -> None)
    if gpu.get("mem_total"):
        gpu["mem_pct"] = round(100.0 * (gpu["mem_used"] or 0) / gpu["mem_total"], 1)
    # 进程列表
    rc2, out2, _ = _run([
        "nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
        "--format=csv,noheader,nounits",
    ])
    procs = []
    if rc2 == 0 and out2.strip():
        for ln in out2.strip().splitlines():
            parts = [p.strip() for p in ln.split(",")]
            if len(parts) < 3:
                continue
            procs.append({"pid": int(_num(parts[0]) or -1),
                          "name": parts[1],
                          "mem": _num(parts[2])})
    gpu["procs"] = procs
    return gpu


# ---------------------------------------------------------------- 2) 训练进程
# 只认真正的"训练入口"; 推理/服务进程 (ss_local_infer_server/ss_bypass_run/auto_loop) 不算训练
TRAIN_SIGNS = [
    (re.compile(r"l5_vlm_lora_train", re.I), "L5"),
    (re.compile(r"yolo_annot_train", re.I), "L2"),
    (re.compile(r"lerobot[._]scripts[._]lerobot_train|lerobot_train", re.I), "L3"),
    (re.compile(r"joint_train_all", re.I), None),          # 编排器: 层别再从参数里抠
    (re.compile(r"train\.py.*intact|intact.*train\.py", re.I), "L4"),
    (re.compile(r"INTACT-JEPA/.*train\.py", re.I), "L4"),
]


def _classify_training(args: str):
    """返回层别标记或 None。编排器 joint_train_all 从 --only 抠出子层。"""
    for pat, layer in TRAIN_SIGNS:
        if not pat.search(args):
            continue
        if layer is not None:
            return layer
        m = re.search(r"--only\s+([A-Za-z0-9/]+)", args)
        return f"JOINT({m.group(1)})" if m else "JOINT(L4/L3/L2)"
    return None


# 进度行解析: 按"最可能→最不可能"试; 命中即停。返回 {step,total,loss,epoch,raw}
PROG_PATTERNS = [
    # L5 自训: "step 80/120 loss 0.2001 lr 2.89e-05 52s ETA 26s 显存 3.12GB"
    re.compile(r"step\s+(\d+)\s*/\s*(\d+)\s+loss\s+([0-9.]+)"),
    # lerobot tqdm: "Training: 100%|█| 40/40 [00:55<00:00, 1.38s/step]"
    re.compile(r"Training:.*?\|\s*(\d+)\s*/\s*(\d+)\s*\[([^\]]+)\]"),
    # 通用 tqdm (含 loss=)
    re.compile(r"(\d+)\s*/\s*(\d+)\s*\[[0-9:<]+\][^\n]*loss[=:]\s*([0-9.]+)"),
    # ultralytics YOLO epoch 行: "1/50  ... box_loss ..."
    re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s+\S+.*?(box_loss|cls_loss)"),
    # 通用 Epoch
    re.compile(r"[Ee]poch\s+(\d+)\s*/\s*(\d+)"),
    # 通用 step
    re.compile(r"\bstep\s+(\d+)\s*/\s*(\d+)"),
]


def _parse_progress(log_path: str, tail_lines: int = 120) -> dict:
    """扫日志尾部, 抽出步数/epoch/loss 进度行。找不到就如实说 (found=False)。"""
    if not log_path or not os.path.isfile(log_path):
        return {"found": False, "reason": "log 不存在"}
    try:
        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()[-tail_lines:]
    except OSError as e:
        return {"found": False, "reason": f"读日志失败: {e}"}
    for ln in reversed(lines):               # 从最后一行往前找, 取最新进度
        s = ln.strip()
        if not s:
            continue
        for pat in PROG_PATTERNS:
            m = pat.search(s)
            if not m:
                continue
            g = m.groups()
            out = {"found": True, "raw": s[:200]}
            nums = [x for x in g if x and str(x).isdigit()]
            if len(nums) >= 2:
                out["step"] = int(nums[0])
                out["total"] = int(nums[1])
            lrm = re.search(r"loss[=:\s]+([0-9.]+)", s)
            if lrm:
                out["loss"] = float(lrm.group(1))
            ep = re.search(r"[Ee]poch\s+(\d+)\s*/\s*(\d+)", s)
            if ep:
                out["epoch"] = int(ep.group(1))
                out["epoch_total"] = int(ep.group(2))
            return out
    return {"found": False, "reason": f"尾部 {tail_lines} 行无进度标记"}


def _recent_logs(dirs: list) -> list:
    """列 dirs 下所有 *.log, 按 mtime 降序。用于把在跑进程对到它的 stdout 日志。"""
    logs = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        # 深一层就够 (reports/joint_train_<ts>/*.log)
        for fp in glob.glob(os.path.join(d, "*.log")) + glob.glob(os.path.join(d, "*", "*.log")):
            st = _stat(fp)
            if st["exists"]:
                logs.append({"path": fp, "mtime_epoch": st["mtime_epoch"]})
    logs.sort(key=lambda x: x["mtime_epoch"] or 0, reverse=True)
    return logs


def collect_training() -> list:
    """扫 ps 找真实训练进程, 标注层别/pid/时长/命令行, 并行尾日志进度。"""
    rc, out, _ = _run(["ps", "-eo", "pid=,etimes=,args="])
    if rc != 0 or not out:
        return []
    logs = _recent_logs([REPORTS_DIR, os.path.join(ROOT, "outputs")])
    procs = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split(None, 2)
        if len(parts) < 3:
            continue
        pid, etimes, args = parts[0], parts[1], parts[2]
        if "model_inventory.py" in args:      # 不把自己算进去
            continue
        layer = _classify_training(args)
        if not layer:
            continue
        try:
            elapsed = int(etimes)
        except ValueError:
            elapsed = None
        start_epoch = (datetime.now().timestamp() - elapsed) if elapsed is not None else None
        # 对日志: 取"进程启动之后还在写"的最新 .log (层别关键字优先, 否则整体最新)
        log_path = None
        layer_kw = {"L2": ("L2", "yolo"), "L3": ("L3", "lerobot", "smolvla"),
                    "L4": ("L4", "intact"), "L5": ("L5", "vlm")}.get(layer, ())
        for lg in logs:
            if start_epoch and lg["mtime_epoch"] and lg["mtime_epoch"] < start_epoch - 10:
                continue
            if layer_kw and any(k.lower() in os.path.basename(lg["path"]).lower() for k in layer_kw):
                log_path = lg["path"]
                break
        if log_path is None and logs:
            log_path = logs[0]["path"]
        procs.append({
            "layer": layer,
            "pid": int(pid),
            "elapsed_s": elapsed,
            "cmd": args[:240],
            "log": log_path,
            "progress": _parse_progress(log_path) if log_path else {"found": False, "reason": "无匹配日志"},
        })
    return procs


# ---------------------------------------------------------------- 3) 四层模型
def _load_active() -> dict:
    if os.path.isfile(ACTIVE_JSON):
        try:
            with open(ACTIVE_JSON, "r", errors="replace") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _newest(paths: list) -> str:
    """返回 mtime 最新的一个路径 (排除不存在)。"""
    best, best_t = None, -1
    for p in paths:
        st = _stat(p)
        if st["exists"] and (st["mtime_epoch"] or 0) > best_t:
            best, best_t = p, st["mtime_epoch"]
    return best


def _layer_candidates(layer: str, active: dict) -> list:
    """按层收集候选权重 (真源优先: active_models.json 的指针排第一)。"""
    cands = []  # (name, path, is_active)
    if layer == "L2":
        act = (active.get("L2") or {}).get("path")
        if act:
            cands.append(("L2 在役 (指针)", os.path.join(ROOT, act), True))
        newest = _newest(glob.glob(os.path.join(
            ROOT, "external/lerobot-smolvla-lew/runs/detect/outputs/yolo_annot*/**/weights/best.pt"),
            recursive=True))
        if newest:
            cands.append(("L2 最新训练产物", newest, False))
    elif layer == "L3":
        act = (active.get("L3") or {}).get("path")
        if act:
            cands.append(("L3 在役 (运行时 ckpt)", os.path.join(ROOT, act), True))
        newest = _newest(glob.glob(os.path.join(
            ROOT, "outputs/train/*/checkpoints/last/pretrained_model/model_merged.safetensors")))
        if newest:
            cands.append(("L3 最新 LoRA-merged 产物", newest, False))
    elif layer == "L4":
        act = (active.get("L4") or {}).get("path")
        if act:
            # intact_l4_current 是"目录 + 恰好一个 weights.pt 软链"格式 → 指向软链真实目标
            wt = os.path.join(act, "weights.pt")
            cands.append(("L4 在役 (稳定指针)", wt if os.path.exists(wt) else act, True))
        newest = _newest(glob.glob(os.path.join(
            ROOT, "zmax_data/stable-wm-cache/checkpoints/intact_goal_optical_insert_*",
            "weights_epoch_*merged.pt")) + glob.glob(os.path.join(
            ROOT, "zmax_data/stable-wm-cache/checkpoints/intact_goal_optical_insert_*",
            "weights_epoch_*.pt")))
        if newest:
            cands.append(("L4 最新续训/LoRA 产物", newest, False))
    elif layer == "L5":
        newest_merged = _newest(glob.glob(os.path.join(
            ROOT, "zmax_data/models/l5_vlm_merged_*/model.safetensors")))
        if newest_merged:
            cands.append(("L5 最新 merged (可部署)", newest_merged, True))
        newest_lora = _newest(glob.glob(os.path.join(
            ROOT, "zmax_data/models/l5_vlm_lora_*/adapter_model.safetensors")))
        if newest_lora:
            cands.append(("L5 最新 LoRA adapter", newest_lora, False))
    return cands


def _match_report(model_path: str, layer: str, reports: list) -> dict:
    """给一个权重找**真正对应**的训练报告 (产物路径包含关系 或 时间戳嵌入权重路径)。

    刻意**不**按"同层最近"退化 —— 否则会把"同层另一个模型"的训练报告错挂到这个权重上
    (实测: 在役 L4 权重是 v6r11, 却会匹配到刚训的 v6lora_40 报告, 误导)。找不到就返回 None,
    "该权重的训练报告不在白名单内"本身是有价值的事实。
    """
    mp = os.path.realpath(model_path) if os.path.exists(model_path) else model_path
    best, best_score, best_kind = None, -1, None
    for r in reports:
        art = (r.get("artifact") or "") or ""
        score, kind = 0, None
        if art:
            a = os.path.realpath(art) if os.path.exists(art) else art
            a = a.rstrip("/")
            b = os.path.basename(a)
            if a and (a in mp or mp in a):
                score, kind = 100, "artifact"          # 产物路径是权重路径/被其包含 (同一次训练)
            elif b and b != "checkpoints" and b in mp.split(os.sep):
                score, kind = 80, "artifact_seg"       # 产物目录名是权重路径的一段
        if score == 0:
            # 完整时间戳 "YYYYMMDD_HHMMSS" 出现在权重路径 ⇒ 同一次训练 (只用完整戳, 不用裸日期,
            # 否则"同一天不同 run"会互相误配 —— 实测 L5 merged 曾被当日失败的 overnight run 抢挂)
            toks = re.findall(r"\d{8}_\d{6}", f"{r.get('ts') or ''} {r.get('source') or ''}")
            if any(t in mp for t in toks):
                score, kind = 80, "ts_token"
        if score > best_score:
            best, best_score, best_kind = r, score, kind
    # 只有强关联 (产物路径/完整时间戳) 才算"有对应训练报告"
    if best is not None and best_score >= 80:
        best = dict(best)
        best["match_kind"] = best_kind
        return best
    return None


def collect_models(reports: list) -> list:
    """逐层采集权重: 路径/大小/mtime/真实目标/对应报告/最近一次训练/推理可用判定。"""
    active = _load_active()
    models = []
    for layer in LAYERS:
        for name, path, is_active in _layer_candidates(layer, active):
            st = _stat(path)
            real = os.path.realpath(path) if os.path.exists(path) else path
            is_link = os.path.islink(path)
            rep = _match_report(path, layer, reports)
            size = st["size"]
            if size is None and os.path.isdir(path):
                size = _dir_size(path)          # 目录型 (L4 指针/L3 ckpt 目录)
            # 推理可用判定 (静态): 文件存在且 >0 字节。不做真推理。
            ready = bool(st["exists"] and (size or 0) > 0)
            entry = {
                "layer": layer,
                "name": f"{layer} · {name}",
                "path": path,
                "realpath": real if real != path else None,
                "symlink": is_link,
                "active": is_active,
                "size": size,
                "size_h": _human(size),
                "mtime": st["mtime"],
                "report": rep["report"] if rep else None,
                "last_train": ({"ts": rep.get("ts"), "steps": rep.get("steps"),
                                "secs": rep.get("secs"), "layer": rep.get("layer"),
                                "match_kind": rep.get("match_kind"),
                                "source": rep.get("source")} if rep else None),
                # 判定依据写清楚, 页上可解释
                "ready": ready,
                "ready_reason": ("存在且 size>0" if ready else
                                 ("路径不存在" if not st["exists"] else "size<=0")),
            }
            models.append(entry)
    return models


def _human(n) -> str:
    if n is None:
        return "?"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024.0
    return f"{n:.1f}PB"


# ---------------------------------------------------------------- 4) 报告解析
def _parse_joint_summary(fp: str) -> list:
    """reports/joint_train_<ts>/summary.json: 每 row 一个 stage(L2/L3/L4/L5)。"""
    rows = []
    try:
        with open(fp, "r", errors="replace") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return rows
    steps = d.get("steps")
    for row in d.get("rows", []):
        ev = (row.get("evidence") or [{}])[0]
        layer = (row.get("stage") or "").split()[0] or None
        ts = row.get("ts") or d.get("generated_at")
        rows.append({
            "source": os.path.basename(os.path.dirname(fp)),   # joint_train_<ts>
            "report": fp,
            "kind": "joint",
            "layer": layer,
            "desc": row.get("layer"),
            "steps": steps,
            "secs": row.get("secs"),
            "rc": row.get("rc"),
            "artifact": ev.get("path"),
            "ts": ts,
            "log": row.get("log"),
        })
    return rows


def _parse_l5_train(fp: str) -> dict:
    """reports/l5_vlm_train_*.json: {ts,steps,samples,adapter,ckpt,load_4bit,peak_gb}。"""
    try:
        with open(fp, "r", errors="replace") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "source": os.path.basename(fp),
        "report": fp,
        "kind": "l5_vlm_train",
        "layer": "L5",
        "desc": "SmolVLM2 LoRA 适配",
        "steps": d.get("steps"),
        "samples": d.get("samples"),
        "secs": None,                      # 该格式不含耗时; 峰值显存代偿
        "peak_gb": d.get("peak_gb"),
        "rc": 0,
        "artifact": d.get("adapter"),
        "ts": d.get("ts"),
        "log": None,
    }


def collect_reports(limit: int = 15) -> list:
    """白名单格式: joint_train_*/summary.json + l5_vlm_train_*.json。自己探字段, 不写死 schema。"""
    records = []
    for fp in sorted(glob.glob(os.path.join(REPORTS_DIR, "joint_train_*", "summary.json"))):
        records.extend(_parse_joint_summary(fp))
    for fp in sorted(glob.glob(os.path.join(REPORTS_DIR, "l5_vlm_train_*.json"))):
        rec = _parse_l5_train(fp)
        if rec:
            records.append(rec)
    # 时间倒序 (ts 可能是 "2026-10-10 06:26:37" / "20261009_231339" / "l5s5")
    records.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return records[:limit]


# ---------------------------------------------------------------- 输出
def build(reports_n: int = 15) -> dict:
    reports = collect_reports(limit=max(reports_n, 60))   # 模型匹配要全量, 输出再截断
    models = collect_models(reports)
    return {
        "generated_at": _now_iso(),
        "gpu": collect_gpu(),
        "training": collect_training(),
        "models": models,
        "reports": reports[:reports_n],
    }


def render(d: dict) -> str:
    L = []
    g = d["gpu"]
    L.append(f"== 模型资产 + 算力状态 ==")
    L.append(f"采集时间: {d['generated_at']}")
    if g.get("error"):
        L.append(f"[GPU] 采集失败: {g['error']}")
    else:
        L.append(f"[GPU] {g.get('name')} · util {g.get('util')}% · "
                 f"mem {g.get('mem_used')}/{g.get('mem_total')} MiB ({g.get('mem_pct')}%) · "
                 f"{g.get('temp')}C · {g.get('power')}W")
        for p in g.get("procs", []):
            L.append(f"      pid {p['pid']:<7} {p['mem']} MiB  {p['name']}")
    tr = d["training"]
    L.append(f"[训练] 在跑训练进程: {len(tr)}")
    for t in tr:
        pg = t.get("progress") or {}
        ptxt = (pg.get("raw") if pg.get("found") else f"(无进度: {pg.get('reason')})")
        L.append(f"      {t['layer']} pid={t['pid']} 已跑 {t['elapsed_s']}s")
        L.append(f"      log={t.get('log')}")
        L.append(f"      progress: {ptxt}")
    L.append(f"[模型] 共 {len(d['models'])} 条:")
    for m in d["models"]:
        tag = "在役" if m["active"] else "候选"
        ready = "就绪" if m["ready"] else f"不可用({m['ready_reason']})"
        L.append(f"      [{m['layer']}|{tag}] {m['name']}")
        L.append(f"            path={m['path']}")
        if m.get("realpath"):
            L.append(f"            → real {m['realpath']}")
        lt = m.get("last_train") or {}
        L.append(f"            size={m['size_h']} mtime={m['mtime']} 推理={ready}")
        rep_txt = m.get("report") or "无(白名单内无匹配)"
        lt_txt = (f"{lt.get('ts')} steps={lt.get('steps')} secs={lt.get('secs')} "
                  f"[{lt.get('match_kind')}]") if lt else "无"
        L.append(f"            report={rep_txt}")
        L.append(f"            last_train={lt_txt}")
    L.append(f"[报告] 最近 {len(d['reports'])} 次训练:")
    for r in d["reports"]:
        L.append(f"      {r.get('ts')} {r.get('layer')} steps={r.get('steps')} "
                 f"secs={r.get('secs')} rc={r.get('rc')} → {r.get('artifact')}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="只读模型资产+算力状态采集器")
    ap.add_argument("--json", action="store_true", help="输出 JSON 到 stdout")
    ap.add_argument("--json-out", metavar="PATH", help="把 JSON 写到指定文件")
    ap.add_argument("--reports-n", type=int, default=15, help="报告取最近 N 条 (默认 15)")
    args = ap.parse_args()

    d = build(reports_n=args.reports_n)

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    elif not args.json_out:
        print(render(d))
    else:
        print(f"已写 {args.json_out}")


if __name__ == "__main__":
    main()
