#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚦 控制台右上角三色状态灯 —— 真源与判据 (老倪 2026-10-15)

老倪原话: 「那三个状态指示灯，保留，绿色表示功能正常(可以随时进行模型推理，且所有模型可以数据闭环全流程工作)，
黄色灯光默认保持现状，工作时要以1秒为周期闪烁，表示训练正在进行(且GPU负荷平均大于50%)，红色灯光默认也是保持现状，
工作时要以1秒为周期闪烁，表示正处于真机器联调且随时可以进行机械臂操作；你来同步功能，要保证功能的准确实时显示。」

三个灯 = 三个**可证伪**的判据 (每条给实测证据 + 源时间戳/帧龄; 取不到就标失效, 绝不冒充现状):

  绿 实心常亮        = 功能正常: 随时可推理 + 全部在役模型可解析 + 数据闭环全流程入口在位
      ① 推理服务 127.0.0.1:8790/health == 200                      (随时可以进行模型推理)
      ② models/active_models.json 的 L2/L3/L4 + extra_in_service 指针**逐个**解析到真实文件
      ③ 闭环四环入口在位: 采集(zmax_datasets.json 有条目) · 训练(tools/joint_train_all.py) ·
         推理(8790) · 部署(tools/model_autoload.py)
      任一不满足 ⇒ 绿灯**灭** + 写清缺哪条 (不冒充"功能正常")
  黄 1s 周期闪        = 训练进行中
      ① 训练进程在场 (口径同 tools/gpu_load_guard.py: lerobot_train|joint_train_all|yolo_annot_train|train_*.py)
      ② GPU 利用率**滑窗平均 > 50%** (最近 20s; 样本 <3 个时如实报"样本不足", 不拿单点冒充平均)
      否则黄灯**保持现状** (空心不闪)
  红 1s 周期闪        = 真机联调中 且 随时可操作机械臂
      ① 联调中 = 位姿真源 zmax_data/rokae_sdk/tcp_out/latest.json 帧龄 ≤ 2s 且非全 0
      ② 可操作 = 真动授权 zmax_data/ctl_auth.json armed 且未过期 (single source: tools/ctl_auth.py)
      否则红灯**保持现状** (空心不闪)

用法:
  ./gui-venv311/bin/python tools/status_lights.py            # 人读
  ./gui-venv311/bin/python tools/status_lights.py --json     # GUI/脚本消费
  ./gui-venv311/bin/python tools/status_lights.py --reset-gpu # 清 GPU 滑窗样本
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTIVE_MODELS = os.path.join(ROOT, "models", "active_models.json")
DATASETS = os.path.join(ROOT, "zmax_data", "stable-wm-cache", "datasets", "zmax_datasets.json")
TRAIN_ENTRY = os.path.join(ROOT, "tools", "joint_train_all.py")
DEPLOY_ENTRY = os.path.join(ROOT, "tools", "model_autoload.py")
POSE_SRC = os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
AUTH_SRC = os.path.expanduser(os.environ.get("ZMAX_CTL_AUTH", "~/zmax/zmax_data/ctl_auth.json"))
GPU_RING = os.path.join(ROOT, "zmax_data", "status_lights_gpu.jsonl")
INFER_HEALTH = "http://127.0.0.1:8790/health"

POSE_FRESH_S = 2.0      # 位姿帧龄阈值 (50Hz 真值源; 视频/运动类 1~2s 口径)
GPU_WIN_S = 20.0        # GPU 滑窗
GPU_MIN_N = 3           # 滑窗最少样本
GPU_TRAIN_MIN = 50.0    # 训练中 GPU 平均负荷红线 (%)
BLINK_PERIOD_S = 1.0    # 闪烁周期 (1s = 0.5s 亮 / 0.5s 灭)

TRAIN_RE = re.compile(r"lerobot[_-]train|joint_train_all|yolo_annot_train|train_[A-Za-z0-9_]*\.py|auto_loop")


def sh(c, t=3):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:                                                           # noqa: BLE001
        return ""


def _http_ok(url, timeout=1.0):
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return (200 <= r.status < 300), r.status, round((time.time() - t0) * 1000, 1)
    except Exception as e:                                                      # noqa: BLE001
        return False, "%s" % e.__class__.__name__, round((time.time() - t0) * 1000, 1)


def _resolve(p):
    """指针 → 真实文件; 返回 (ok, realpath 或原因)"""
    if not p:
        return False, "空指针"
    ap = p if os.path.isabs(p) else os.path.join(ROOT, p)
    if not os.path.exists(ap):
        return False, "不存在: %s" % p
    rp = os.path.realpath(ap)
    if not os.path.exists(rp):
        return False, "断链: %s → %s" % (p, rp)
    return True, rp


def check_green():
    items = []
    # ① 推理服务
    ok, code, ms = _http_ok(INFER_HEALTH)
    items.append({"name": "推理服务 8790/health", "ok": bool(ok),
                  "ev": ("HTTP %s · %sms" % (code, ms))})
    # ② 在役模型指针
    try:
        reg = json.load(open(ACTIVE_MODELS, encoding="utf-8"))
    except Exception as e:                                                      # noqa: BLE001
        reg = {}
        items.append({"name": "在役模型真源", "ok": False, "ev": "%s: %s" % (e.__class__.__name__, e)})
    if reg:
        ptrs = []
        for lv in ("L2", "L3", "L4"):
            if isinstance(reg.get(lv), dict) and reg[lv].get("path"):
                ptrs.append((lv, reg[lv]["path"]))
        for lv, lst in (reg.get("extra_in_service") or {}).items():
            for it in (lst or []):
                if isinstance(it, dict) and it.get("path"):
                    ptrs.append(("%s/%s" % (lv, it.get("kind") or "extra"), it["path"]))
        bad = []
        for lv, p in ptrs:
            ok2, ev2 = _resolve(p)
            if not ok2:
                bad.append("%s %s" % (lv, ev2))
        items.append({"name": "在役模型指针 (%d 条)" % len(ptrs), "ok": not bad,
                      "ev": ("全部可解析" if not bad else "; ".join(bad)[:300])})
    # ③ 数据闭环全流程入口
    n_ds = None
    try:
        ds = json.load(open(DATASETS, encoding="utf-8"))
        n_ds = len(ds if isinstance(ds, list) else (ds.get("datasets") or ds.get("items") or ds))
    except Exception as e:                                                      # noqa: BLE001
        items.append({"name": "闭环·采集台账", "ok": False, "ev": "%s: %s" % (e.__class__.__name__, e)})
    if n_ds is not None:
        items.append({"name": "闭环·采集台账", "ok": n_ds > 0, "ev": "%s 条 (%s)" % (n_ds, "%s" % time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(DATASETS))))})
    items.append({"name": "闭环·训练入口", "ok": os.path.exists(TRAIN_ENTRY),
                  "ev": "tools/joint_train_all.py %s" % ("在" if os.path.exists(TRAIN_ENTRY) else "缺")})
    items.append({"name": "闭环·部署入口", "ok": os.path.exists(DEPLOY_ENTRY),
                  "ev": "tools/model_autoload.py %s" % ("在" if os.path.exists(DEPLOY_ENTRY) else "缺")})
    on = all(i["ok"] for i in items)
    miss = [i["name"] for i in items if not i["ok"]]
    why = "功能正常: 可随时推理 + 在役模型齐 + 闭环全流程入口在位" if on else "不满足: " + " · ".join(miss)
    return {"on": on, "why": why, "items": items}


def gpu_now():
    o = sh("nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits", t=4)
    vals = []
    for ln in o.splitlines():
        ln = ln.strip()
        if ln.isdigit():
            vals.append(int(ln))
    return vals


def gpu_avg():
    """滑窗平均: 本文件维护 ~/zmax/zmax_data/status_lights_gpu.jsonl (最近 20s, 至少 3 个样本)"""
    now = time.time()
    vals = gpu_now()
    lines = []
    try:
        os.makedirs(os.path.dirname(GPU_RING), exist_ok=True)
        if vals:
            with open(GPU_RING, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": round(now, 2), "gpu": max(vals)}) + "\n")
        lines = [ln for ln in open(GPU_RING, encoding="utf-8").read().splitlines() if ln.strip()][-400:]
        with open(GPU_RING, "w", encoding="utf-8") as f:
            f.write("\n".join(lines[-120:]) + "\n")
    except Exception:                                                           # noqa: BLE001
        pass
    smp = []
    for ln in lines:
        try:
            d = json.loads(ln)
            if now - float(d.get("ts", 0)) <= GPU_WIN_S:
                smp.append(float(d["gpu"]))
        except Exception:                                                       # noqa: BLE001
            continue
    if not smp and vals:
        smp = [float(max(vals))]
    if len(smp) >= GPU_MIN_N:
        return round(sum(smp) / len(smp), 1), len(smp), "滑窗 %.0fs/%d 样本" % (GPU_WIN_S, len(smp))
    return None, len(smp), "样本不足 (%d < %d), 不拿单点冒充平均" % (len(smp), GPU_MIN_N)


def train_procs():
    out, me = [], os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            cl = open("/proc/%s/cmdline" % pid, "rb").read().decode("utf-8", "replace").replace("\x00", " ").strip()
        except Exception:                                                       # noqa: BLE001
            continue
        if cl and TRAIN_RE.search(cl) and "status_lights" not in cl:
            out.append({"pid": int(pid), "cmd": cl[:180]})
    return out


def check_yellow():
    procs = train_procs()
    avg, n, note = gpu_avg()
    ok_gpu = (avg is not None and avg > GPU_TRAIN_MIN)
    blink = bool(procs) and ok_gpu
    if blink:
        why = "训练进行中: %d 个训练进程 · GPU 平均 %.1f%% (>%g%%) · %s" % (len(procs), avg, GPU_TRAIN_MIN, note)
    elif pros := procs:
        why = "有训练进程但 GPU 平均 %s ⇒ 不闪 (训练进行中须 %s%% 以上)" % (
            ("%.1f%%" % avg) if avg is not None else note, GPU_TRAIN_MIN)
    else:
        why = "无训练进程 ⇒ 保持现状 (不闪)"
    return {"blink": blink, "why": why, "gpu_avg": avg, "gpu_n": n, "gpu_note": note, "train": procs}


def check_red():
    pose_age, pose_ok, pose_ev = None, False, "缺位姿真源"
    try:
        d = json.load(open(POSE_SRC, encoding="utf-8"))
        t_src = float(d.get("ts") or os.path.getmtime(POSE_SRC))
        pose_age = round(time.time() - t_src, 1)
        vals = [abs(float(d.get(k) or 0.0)) for k in ("x", "y", "z")]
        nonzero = any(v > 1e-6 for v in vals)
        pose_ok = (pose_age <= POSE_FRESH_S) and nonzero
        pose_ev = "位姿帧龄 %.1fs %s · %s" % (pose_age, "(≤2s)" if pose_age <= POSE_FRESH_S else "(陈旧!)",
                                            "值非全0" if nonzero else "全0 陈旧值")
    except Exception as e:                                                      # noqa: BLE001
        pose_ev = "位姿真源读不到: %s: %s" % (e.__class__.__name__, e)
    armed, until, auth_ev = False, None, "授权真源读不到"
    try:
        a = json.load(open(AUTH_SRC, encoding="utf-8"))
        until = float(a.get("until") or 0)
        armed = until > time.time()
        auth_ev = "真动授权 %s (until %s · 剩 %.0fs)" % (
            "已 armed" if armed else "未授权/已过期",
            time.strftime("%H:%M:%S", time.localtime(until)) if until else "—",
            max(0.0, until - time.time()))
    except Exception as e:                                                      # noqa: BLE001
        auth_ev = "授权真源读不到: %s: %s" % (e.__class__.__name__, e)
    blink = pose_ok and armed
    if blink:
        why = "真机联调中且可操作: %s · %s" % (pose_ev, auth_ev)
    else:
        miss = []
        if not pose_ok:
            miss.append("不在联调 (%s)" % pose_ev)
        if not armed:
            miss.append("不可操作 (%s)" % auth_ev)
        why = "保持现状 (不闪): " + " · ".join(miss)
    return {"blink": blink, "why": why, "pose_age_s": pose_age, "pose_ok": pose_ok,
            "pose_ev": pose_ev, "armed": armed, "auth_until": until, "auth_ev": auth_ev}


def collect():
    return {"ts": round(time.time(), 2), "t": time.strftime("%Y-%m-%d %H:%M:%S"),
            "blink_period_s": BLINK_PERIOD_S,
            "green": check_green(), "yellow": check_yellow(), "red": check_red()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--reset-gpu", action="store_true", help="清 GPU 滑窗样本")
    a = ap.parse_args()
    if a.reset_gpu:
        try:
            os.remove(GPU_RING)
            print("已清 GPU 滑窗: %s" % GPU_RING)
        except FileNotFoundError:
            print("(GPU 滑窗本来就没有)")
        return 0
    d = collect()
    if a.json:
        print(json.dumps(d, ensure_ascii=False))
        return 0
    print("🚦 状态灯 (口径: %s · 闪烁周期 %ss)" % (time.strftime("%H:%M:%S"), BLINK_PERIOD_S))
    print("  🟢 绿 %s  %s" % ("实心/常亮" if d["green"]["on"] else "灭(空心)", d["green"]["why"]))
    for it in d["green"]["items"]:
        print("       %s %-22s %s" % ("✓" if it["ok"] else "✗", it["name"], it["ev"]))
    print("  🟡 黄 %s  %s" % ("1s 周期闪烁" if d["yellow"]["blink"] else "保持现状(空心不闪)", d["yellow"]["why"]))
    print("  🔴 红 %s  %s" % ("1s 周期闪烁" if d["red"]["blink"] else "保持现状(空心不闪)", d["red"]["why"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
