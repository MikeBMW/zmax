#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 模型引擎 · 管理/训练动作入口 (2026-11-25 老倪「所有模型, 都要显示, 管理, 可训练」)

设计口径
  · 清单只读: `tools/model_inventory.py --json` 的 `all_models` (319 条, 磁盘真源)。
  · 本文件只做**动作**: 设为在役 / 发起训练 / 停止训练 —— 每个动作都回执 JSON, 供 GUI 显示。
  · 换模型 = 改指针(models/active_models.json) 或改软链, **绝不覆盖权重文件**;
    写前先备份、写后回读校验 (verify), 失败自动回滚。
  · 训练一律后台 nohup + 独立日志; 同层已有训练在跑则拒绝 (除非 --force), 避免 8G 显存双开 OOM。

用法
  python tools/model_engine_ctl.py --set-active L3 outputs/train/x/checkpoints/004000/pretrained_model
  python tools/model_engine_ctl.py --train L4 [--steps 200] [--dry-run] [--force]
  python tools/model_engine_ctl.py --stop 12345
  python tools/model_engine_ctl.py --status
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTIVE = os.path.join(ROOT, "models", "active_models.json")
LOG_DIR = os.path.join(ROOT, "logs")
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable

# 各层训练入口 —— 与 models/active_models.json 的 role 字段同源 (改这里要同步那边)
TRAIN_ENTRY = {
    "L2": ["tools/yolo_annot_train.py", "--epochs", "30"],
    "L3": ["tools/joint_train_all.py", "--only", "L3"],
    "L4": ["tools/joint_train_all.py", "--only", "L4"],
    "L5": ["tools/l5_vlm_lora_train.py"],
}
LAYERS = ("L2", "L3", "L4", "L5")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _out(d: dict, rc: int = 0) -> int:
    print(json.dumps(d, ensure_ascii=False, indent=1))
    return rc


def load_active() -> dict:
    try:
        with open(ACTIVE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:                                                  # noqa: BLE001
        return {"_error": repr(e)}


def _backup_active() -> str:
    bk = "%s.bak.%s" % (ACTIVE, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(bk), exist_ok=True)
    shutil.copy2(ACTIVE, bk)
    return bk


# ───────────────────────────── 1) 设为在役 ─────────────────────────────
def set_active(layer: str, path: str) -> dict:
    """把某一层的在役指针切到 path。L2 是软链 (models/yolo_peg_live.pt) ⇒ 原子重建软链;

    其它层写 active_models.json。两者都: 备份 → 写 → 回读校验 → 失败回滚。
    """
    layer = layer.upper()
    if layer not in LAYERS:
        return {"ok": False, "error": "未知层 %s (只认 %s)" % (layer, "/".join(LAYERS))}
    fp = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if not os.path.exists(fp):
        return {"ok": False, "error": "目标不存在: %s" % fp}

    # L2 · YOLO: 在役是软链 models/yolo_peg_live.pt —— 重建软链 (原子 rename)
    if layer == "L2" and (fp.endswith(".pt") or fp.endswith(".pth")):
        link = os.path.join(ROOT, "models", "yolo_peg_live.pt")
        old = os.readlink(link) if os.path.islink(link) else None
        tmp = link + ".new"
        try:
            if os.path.lexists(tmp):
                os.remove(tmp)
            os.symlink(os.path.relpath(fp, os.path.dirname(link)), tmp)
            os.replace(tmp, link)                     # 原子
            got = os.path.realpath(link)
            ok = got == os.path.realpath(fp)
            if not ok:                                # 回滚
                if old is not None:
                    os.symlink(old, tmp) if not os.path.lexists(tmp) else None
                    os.replace(tmp, link)
                return {"ok": False, "error": "软链回读不一致", "want": fp, "got": got}
            return {"ok": True, "layer": "L2", "mode": "symlink",
                    "old": old, "new": os.readlink(link), "verified": True, "ts": _now()}
        except OSError as e:
            return {"ok": False, "error": "重建软链失败: %r" % (e,), "old": old}

    # L3/L4/L5 (以及 L2 的 SAM3 适配器不在此列): 写 active_models.json
    d = load_active()
    if d.get("_error"):
        return {"ok": False, "error": "active_models.json 读不出: %s" % d["_error"]}
    if layer == "L2":
        return {"ok": False, "error": "L2 只支持切换 YOLO(.pt 软链); SAM3 走 8796 服务的适配器切换"}
    bk = _backup_active()
    old = (d.get(layer) or {}).get("path")
    rel = os.path.relpath(fp, ROOT) if fp.startswith(ROOT) else fp
    node = d.get(layer) or {}
    node["path"] = rel
    node.setdefault("kind", {"L3": "smolvla", "L4": "intact", "L5": "vlm"}.get(layer, ""))
    node["name"] = node.get("name") or "%s · %s" % (layer, os.path.basename(fp))
    node["switched_at"] = _now()
    node["switched_from"] = old
    d[layer] = node
    d["updated"] = _now()
    try:
        with open(ACTIVE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except OSError as e:
        shutil.copy2(bk, ACTIVE)
        return {"ok": False, "error": "写回失败已回滚: %r" % (e,)}
    back = (load_active().get(layer) or {}).get("path")
    if back != rel:
        shutil.copy2(bk, ACTIVE)                       # 回读不一致 → 回滚
        return {"ok": False, "error": "回读不一致已回滚", "want": rel, "got": back}
    return {"ok": True, "layer": layer, "mode": "pointer", "old": old, "new": rel,
            "verified": True, "backup": os.path.relpath(bk, ROOT), "ts": _now()}


# ───────────────────────────── 2) 训练 ─────────────────────────────
def _running(layer: str | None = None) -> list:
    """本机正在跑的模型训练进程 (只看 tools/ 下的训练入口, 不看无关 python)。"""
    rows = []
    keys = ("yolo_annot_train", "joint_train_all", "l5_vlm_lora_train", "sam3_finetune",
            "train_awe", "train_cog", "train_cond")
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            continue
        if not any(k in cmd for k in keys):
            continue
        ly = "?"
        for k, v in (("--only L2", "L2"), ("--only L3", "L3"), ("--only L4", "L4"),
                     ("yolo_annot_train", "L2"), ("sam3_finetune", "L2"), ("l5_vlm_lora_train", "L5")):
            if k in cmd:
                ly = v
                break
        if layer and ly != layer:
            continue
        try:
            et = int(float(open("/proc/%s/stat" % pid).read().split()[21]) / os.sysconf("SC_CLK_TCK"))
        except Exception:                                                       # noqa: BLE001
            et = None
        rows.append({"pid": int(pid), "layer": ly, "cmd": cmd[:220], "elapsed_s": et})
    return rows


def train(layer: str, extra: list | None = None, dry_run: bool = False, force: bool = False) -> dict:
    layer = layer.upper()
    if layer not in TRAIN_ENTRY:
        return {"ok": False, "error": "未知层 %s" % layer}
    if _running(layer) and not force:
        return {"ok": False, "error": "该层已有训练在跑 (8G 显存双开会 OOM); 确要并行加 --force",
                "running": _running(layer)}
    cmd = list(TRAIN_ENTRY[layer]) + list(extra or [])
    full = " ".join([PY] + cmd)
    if dry_run:
        return {"ok": True, "dry_run": True, "layer": layer, "cmd": full,
                "note": "未启动; 去掉 --dry-run 即后台开跑"}
    os.makedirs(LOG_DIR, exist_ok=True)
    log = os.path.join(LOG_DIR, "model_train_%s_%s.log" % (layer, datetime.now().strftime("%Y%m%d_%H%M%S")))
    try:
        f = open(log, "ab")
        p = subprocess.Popen([PY] + cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:                                                      # noqa: BLE001
        return {"ok": False, "error": "启动失败: %r" % (e,), "cmd": full}
    time.sleep(1.0)
    alive = _pid_alive(p.pid)
    return {"ok": alive, "layer": layer, "pid": p.pid, "log": os.path.relpath(log, ROOT),
            "cmd": full, "alive_after_1s": alive,
            "error": None if alive else "进程启动后 1s 内退出, 看日志", "ts": _now()}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop(pid: int) -> dict:
    if not _pid_alive(pid):
        return {"ok": False, "error": "pid %s 不存在" % pid}
    try:
        os.kill(pid, 15)
        for _ in range(20):
            if not _pid_alive(pid):
                return {"ok": True, "pid": pid, "signal": "TERM", "ts": _now()}
            time.sleep(0.5)
        os.kill(pid, 9)
        return {"ok": True, "pid": pid, "signal": "KILL(超时升级)", "ts": _now()}
    except OSError as e:
        return {"ok": False, "error": repr(e)}


def status() -> dict:
    d = load_active()
    act = {ly: (d.get(ly) or {}).get("path") for ly in LAYERS if d.get(ly)}
    return {"ok": True, "ts": _now(), "active": act, "running": _running(),
            "train_entry": {k: " ".join(v) for k, v in TRAIN_ENTRY.items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description="模型引擎 管理/训练动作 (设为在役 · 训练 · 停止)")
    ap.add_argument("--set-active", nargs=2, metavar=("LAYER", "PATH"))
    ap.add_argument("--train", metavar="LAYER")
    ap.add_argument("--extra", nargs=argparse.REMAINDER, default=[],
                    help="追加给训练脚本的参数 (放最后, 如 --extra --steps 200)")
    ap.add_argument("--stop", type=int, metavar="PID")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.set_active:
        return _out(set_active(*a.set_active), 0)
    if a.train:
        return _out(train(a.train, a.extra, a.dry_run, a.force), 0)
    if a.stop:
        return _out(stop(a.stop), 0)
    if a.status:
        return _out(status(), 0)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
