#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型加载台账自检 (老倪 2026-10-31: 「终端里我要看到加载每个模型的说明，到底是不是加载了」)

把状态空间链路上**每一个真模型**都真加载一次, 终端逐行打印:
    [模型] L3  SmolVLA+LEW 策略 ← <权重路径> · 存在=是 · 大小=1.29GB · 加载 OK · 6.8s · 参数量 625M · 设备 cuda

覆盖: L2 YOLO 检测 · L3 SmolVLA+LEW 策略 · L3 右脑 WorldModel (npz) · L3 前馈 MLP (npz)
      L4 流形引擎 (mu/W) · L5 SmolVLM2 视觉编码塔
任何一项失败都会打印"未加载/失败"并给原因 —— 不静默。

用法:  ./gui-venv311/bin/python tools/model_ledger.py [--only L2,L3]
       HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 (本机 HF 不通时必须)
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def _first(pat: str) -> str:
    hits = sorted(glob.glob(os.path.join(ROOT, pat), recursive=True),
                  key=os.path.getmtime, reverse=True)
    return hits[0] if hits else ""


def t_yolo(done: dict) -> None:
    """权重本体验证 (真 YOLO 加载); aligner 还要帧源, 单独说清楚, 不混为一谈。"""
    from lerobot.engineering.model_log import note
    w = os.environ.get("SS_YOLO_W") or _first("models/yolo_peg_live.pt") \
        or _first("models/**/yolo*.pt")
    if not w:
        note("L2", "YOLO 目标检测", "", False, detail="找不到 yolo_peg_live.pt")
        return
    t0 = time.time()
    from ultralytics import YOLO
    m = YOLO(w)
    names = list((getattr(m, "names", {}) or {}).values())
    note("L2", "YOLO 目标检测", w, True, elapsed=time.time() - t0,
         detail="类别 %s" % (",".join(map(str, names))[:40] or "-"))
    done["yolo"] = True


def t_l3(done: dict) -> None:
    from lerobot.engineering.nodes import smolvla_lew_l3 as L3                # noqa: PLC0415
    pol, _pre, _post, _dev, meta = L3._load_policy(ROOT)
    done["l3"] = pol is not None
    if pol is None:
        print("   ↳ L3 未加载: %s" % meta.get("err"))


def t_world(done: dict) -> None:
    from lerobot.policies.left_right.state_space import dynamics as D         # noqa: PLC0415
    p = os.environ.get("SS_WM_NPZ") or getattr(D, "NPZ_DEFAULT", "")
    if p and not os.path.isabs(p):
        p = os.path.join(ROOT, p)
    if p and os.path.isfile(p):
        D.rb_ff_forward(p, probe={})              # 真加载 npz (打印台账)
        done["world"] = True
    else:
        from lerobot.engineering.model_log import note
        note("L3", "右脑 WorldModel", p or "(未配置)", False, detail="找不到 npz")


def t_ff(done: dict) -> None:
    from lerobot.policies.left_right.state_space import parallel as P         # noqa: PLC0415
    p = os.environ.get("SS_FF_NPZ") or getattr(P, "NPZ_DEFAULT", "")
    if p and not os.path.isabs(p):
        p = os.path.join(ROOT, p)
    if p and os.path.isfile(p):
        P.load_npz_weights(p)
        done["ff"] = True
    else:
        from lerobot.engineering.model_log import note
        note("L3", "前馈加速器 MLP", p or "(未配置)", False, detail="找不到 npz")


def t_manifold(done: dict) -> None:
    from lerobot.manifold.manifold_engine import ManifoldEngine                # noqa: PLC0415
    p = os.environ.get("SS_MANI_NPZ") or _first("models/manifold_engine.npz") \
        or _first("models/**/manifold*.npz") or _first("**/manifold*.npz")
    eng = ManifoldEngine()
    ok = eng.load(p) if p else False
    done["manifold"] = bool(ok)
    from lerobot.engineering.model_log import note
    note("L4", "流形引擎 (mu/W)", p or "(未配置)", bool(ok),
         detail=("潜伏维 %s · n_fit %s" % (getattr(eng, "latent_dim", "?"), getattr(eng, "n_fit", "?")))
         if ok else "没找到/格式不符")


def t_vlm(done: dict) -> None:
    from lerobot.manifold.encoder_vlm import VLMVisionEncoder                 # noqa: PLC0415
    e = VLMVisionEncoder()
    ok, msg = e.available()                    # 真加载视觉塔 (台账在 _load 里打)
    if not ok:
        from lerobot.engineering.model_log import note
        note("L5", "SmolVLM2 视觉编码", getattr(e, "mid", ""), False, detail=msg[:70])
    done["vlm"] = bool(ok)


TASKS = {"L2": ("YOLO 检测", t_yolo), "L3": ("SmolVLA+LEW", t_l3), "L3w": ("右脑 WorldModel", t_world),
         "L3f": ("前馈 MLP", t_ff), "L4": ("流形引擎", t_manifold), "L5": ("SmolVLM2 视觉", t_vlm)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    want = {x.strip() for x in a.only.split(",") if x.strip()}
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("ZMAX_SINGLE_THREAD", "1")

    print("模型加载台账 · 逐项真加载 (ROOT=%s)" % ROOT)
    done, bad = {}, []
    for tag, (label, fn) in TASKS.items():
        if want and tag not in want:
            continue
        t0 = time.time()
        print("\n▶ %s %s" % (tag, label))
        try:
            fn(done)
        except Exception as e:                                               # noqa: BLE001
            bad.append(tag)
            print("   ✖ %s 加载异常: %s: %s" % (label, type(e).__name__, str(e)[:110]))
        print("   用时 %.2fs" % (time.time() - t0))
    from lerobot.engineering.model_log import _SEEN as _SEEN_KEYS
    print("\n—— 台账小结 ——")
    print("已打印的模型条目: %d%s" % (len(_SEEN_KEYS), (" · 异常: " + ",".join(bad)) if bad else " · 无异常"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
