#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_recon_state.py — 高保真重建(3DGS)状态真源, 挂在 📡 融合定位建图 节点上 (out3)。

为什么要有它(2026-11-19):
  画布节点 sssensor(📡 融合定位建图) 的真实源只有两半 ——
    ① 状态融合 src/lerobot/policies/left_right/state_space/perception.py::fuse_sensors
    ② ORB 建图 src/lerobot/manifold/localization_mapping.py (mapping_live.json, 最后更新 10-13 就停了)
  而我们真正在用的 3DGS 高保真重建(采集→建集→550C训练→splat→8816推流)全在 tools/ 里各跑各的,
  状态空间里既看不到"地图质量", 也查不到资产路径与帧龄。本脚本把这条链路收成**单一真源**:
      zmax_data/mapping/gs_recon_live.json   (节点 out3 读取口, 带 stage/帧龄/可复算数字)

口径(全部可复核, 不估):
  stage       采集中 <60s 有 frames.jsonl 追加 · 训练中 550C 训练日志 <300s 在长 · 否则 已就绪
  psnr        取当前资产 train_report.json 的 psnr_holdout_db (留出视角, 与训练同口径)
  coverage_mm 训练集 data 目录的 coverage/bbox (会话 meta 或 ds meta.json)
  asset       当前 8816 在跑的资产名 + splat 字节 + 写入时间

用法:
  gs_recon_state.py once            # 采一次写盘(幂等)
  gs_recon_state.py watch --hz 0.033  # 常驻 30s 一轮 (systemd 用)
  gs_recon_state.py status          # 人读摘要
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(ROOT, "zmax_data", "gs_scan")
ASSETS = os.path.join(ROOT, "zmax_data", "gs_assets")
OUT = os.path.join(ROOT, "zmax_data", "mapping", "gs_recon_live.json")
HIST = os.path.join(ROOT, "zmax_data", "mapping", "gs_recon_history.jsonl")
INTEL = "intel@192.168.23.70"
STREAM_HEALTH = "http://192.168.23.70:8816/health"
TRAIN_LOG = "/home/intel/gsPITCH.log"


def _mtime(p: str) -> float:
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _newest(pattern: str) -> str:
    cand = [p for p in glob.glob(pattern) if os.path.exists(p)]
    return max(cand, key=_mtime) if cand else ""


def _read_json(p: str) -> dict:
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _ssh(cmd: str, timeout: float = 9.0) -> str:
    try:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=4", "-o", "BatchMode=yes",
                            "-o", "StrictHostKeyChecking=no", INTEL, cmd],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _http_json(url: str, timeout: float = 3.0) -> dict:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return {}


def scan_state(now: float) -> dict:
    """采集会话: 最近 60s 内有帧追加 ⇒ 采集中。"""
    best, best_m, best_n = "", 0.0, 0
    for d in glob.glob(os.path.join(SCAN, "*")):
        f = os.path.join(d, "frames.jsonl")
        m = _mtime(f)
        if m > best_m:
            best, best_m = os.path.basename(d), m
            try:
                with open(f, "rb") as fh:
                    fh.seek(0, os.SEEK_END)
                    fh.seek(max(0, fh.tell() - 65536))
                    best_n = sum(1 for _ in fh)
            except OSError:
                best_n = 0
    age = (now - best_m) if best_m else -1.0
    return {"session": best, "age_s": round(age, 1) if age >= 0 else -1.0,
            "tail_lines": best_n, "active": bool(best_m and age < 60.0)}


def asset_state() -> dict:
    """当前资产: 取 assets 下最新 train_report.json (psnr/高斯/覆盖)。"""
    latest_p, latest_m = "", 0.0
    for p in glob.glob(os.path.join(ASSETS, "*", "train_report.json")):
        m = _mtime(p)
        if m > latest_m:
            latest_p, latest_m = p, m
    if not latest_p:
        return {}
    rep = _read_json(latest_p)
    name = os.path.basename(os.path.dirname(latest_p))
    splat = os.path.join(os.path.dirname(latest_p), "gs.splat")
    spl = os.path.getsize(splat) if os.path.exists(splat) else 0
    # 覆盖范围: 优先 data 目录里的 meta/coverage
    cov = None
    data = rep.get("data") or ""
    if data and not os.path.exists(data):          # 数据集在 550C 上 ⇒ 远端读 coverage.json
        rtxt = _ssh("cat %s/coverage.json 2>/dev/null" % data, timeout=6.0)
        if rtxt:
            try:
                j = json.loads(rtxt)
                cov = (j.get("coverage_mm") or j.get("extent_mm")
                       or j.get("bbox_mm") or j.get("bbox"))
            except Exception:
                cov = None
    for cand in (os.path.join(data, "meta.json"), os.path.join(data, "coverage.json")):
        if os.path.exists(cand):
            j = _read_json(cand)
            cov = (cov or j.get("coverage_mm") or j.get("extent_mm")
                   or j.get("bbox_mm") or j.get("bbox"))
            if cov:
                break
    return {"map_id": name, "psnr_holdout_db": rep.get("psnr_holdout_db"),
            "psnr_train_db": rep.get("psnr_train_db"), "n_gauss": rep.get("n_gaussians"),
            "steps": rep.get("steps"), "frames": (rep.get("frames") or rep.get("n_views")),
            "coverage_mm": cov, "splat_bytes": spl, "trained_at": round(latest_m),
            "age_s": round(time.time() - latest_m, 1) if latest_m else -1.0,
            "asset_dir": os.path.dirname(latest_p)}


def train_state(now: float) -> dict:
    """550C 训练: 读**最新**的 gs*.log 尾 + mtime(训练日志名不固定), 不敢断言就明写 unknown。"""
    txt = _ssh("L=$(ls -t /home/intel/gs*.log 2>/dev/null | head -1); "
               "echo LOGBASENAME=$L; tail -c 400 \"$L\" 2>/dev/null; echo ---; date +%s -r \"$L\" 2>/dev/null")
    if not txt or "---" not in txt:
        return {"state": "unknown", "reason": "550C 不可达或日志缺失"}
    lb = ""
    for ln in txt.splitlines():
        if ln.startswith("LOGBASENAME="):
            lb = ln.split("=", 1)[1].strip()
    txt2 = "\n".join(ln for ln in txt.splitlines() if not ln.startswith("LOGBASENAME="))
    tail, _, mt = txt2.partition("---")
    try:
        m = float(mt.strip().splitlines()[-1])
    except Exception:
        m = 0.0
    age = (now - m) if m else -1.0
    step = ""
    for ln in reversed(tail.splitlines()):
        ln = ln.strip()
        if ln.startswith("[") and "/" in ln:
            step = ln[:80]
            break
    return {"state": "running" if (m and age < 300) else "idle",
            "log": lb or TRAIN_LOG, "log_age_s": round(age, 1) if age >= 0 else -1.0,
            "last_step_line": step}


def stream_state() -> dict:
    h = _http_json(STREAM_HEALTH)
    if not h:
        return {"state": "down"}
    return {"state": "live", "gaussians": h.get("gaussians"), "w": h.get("w"), "h": h.get("h"),
            "fps": h.get("fps"), "src": h.get("src"), "pose_age_s": h.get("pose_age_s"),
            "view": h.get("view")}


def build() -> dict:
    now = time.time()
    sc = scan_state(now)
    ast = asset_state()
    tr = train_state(now)
    st = stream_state()
    if tr.get("state") == "unknown":
        # SSH 抖动不能把"训练中"翻成"已就绪"(会误导人) ⇒ 沿用上一轮结论并标注 stale
        prev = _read_json(OUT).get("train") or {}
        if prev.get("state") in ("running", "idle"):
            tr = dict(prev)
            tr["stale"] = True
    stage = "已就绪"
    if sc.get("active"):
        stage = "采集中"
    elif tr.get("state") == "running":
        stage = "训练中"
    rec = {
        "schema": "zmax.gs_recon.v1",
        "node": "sssensor",
        "port": "out3",
        "name": "📡 融合定位建图 · 高保真重建 (3DGS)",
        "stage": stage,
        "ts": round(now, 3),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "capture": sc,
        "train": tr,
        "asset": ast,
        "stream": st,
        # 状态空间三个量(给 ssobs 消费)
        "state_space": {
            "map_coverage_mm": (ast.get("coverage_mm") if ast else None),
            "map_psnr_db": (ast.get("psnr_holdout_db") if ast else None),
            "map_asset_age_s": (ast.get("age_s") if ast else None),
        },
        "pipeline": [
            {"step": "采集", "cmd": "tools/gs_capture.py --out zmax_data/gs_scan/<session> --hz 10",
             "state": "running" if sc.get("active") else "idle"},
            {"step": "建集", "cmd": "tools/map_build_3dgs_ds.py --session <session> --out <ds> --crop 960x720",
             "state": "unknown"},
            {"step": "训练", "cmd": "550C gs_train.py --data <ds> --out <out> --steps N --refine-stop M",
             "state": tr.get("state")},
            {"step": "发布", "cmd": "tools/gs_ply2splat.py --ply gs.ply --out gs.splat",
             "state": "ok" if ast else "idle"},
            {"step": "推流", "cmd": "550C gs_render_stream_intel.py (8816)",
             "state": st.get("state")},
        ],
    }
    return rec


def write(rec: dict) -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    with open(HIST, "a", encoding="utf-8") as f:
        f.write(json.dumps({k: rec[k] for k in ("ts", "stage", "state_space", "capture", "train")},
                           ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="once", choices=["once", "watch", "status"])
    ap.add_argument("--hz", type=float, default=1.0 / 30.0)
    a = ap.parse_args()
    if a.cmd == "once":
        rec = build()
        write(rec)
        print(json.dumps({"stage": rec["stage"], "asset": rec["asset"].get("map_id"),
                          "psnr": rec["asset"].get("psnr_holdout_db"),
                          "n_gauss": rec["asset"].get("n_gauss"),
                          "out": os.path.relpath(OUT, ROOT)}, ensure_ascii=False))
        return 0
    if a.cmd == "status":
        rec = _read_json(OUT)
        if not rec:
            print("无真源文件, 先跑 once")
            return 1
        print("stage %s · %s" % (rec["stage"], rec["updated"]))
        print("asset %s · psnr %s · 高斯 %s · 资产帧龄 %ss" % (
            rec["asset"].get("map_id"), rec["asset"].get("psnr_holdout_db"),
            rec["asset"].get("n_gauss"), rec["asset"].get("age_s")))
        print("capture %s (age %ss) · train %s · stream %s" % (
            rec["capture"].get("session"), rec["capture"].get("age_s"),
            rec["train"].get("state"), rec["stream"].get("state")))
        return 0
    period = max(2.0, 1.0 / a.hz)
    print("[gs_recon_state] watch %.1fs 一轮 → %s" % (period, os.path.relpath(OUT, ROOT)), flush=True)
    while True:
        try:
            rec = build()
            write(rec)
            print("[gs_recon_state] %s %s · %s · psnr %s" % (
                rec["updated"][11:], rec["stage"], rec["asset"].get("map_id"),
                rec["asset"].get("psnr_holdout_db")), flush=True)
        except Exception as e:
            print("[gs_recon_state] err %s: %s" % (type(e).__name__, e), flush=True)
        time.sleep(period)


if __name__ == "__main__":
    sys.exit(main())
