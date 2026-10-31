#!/usr/bin/env python3
"""550C 影子世界进化 —— 在 3DGS 虚拟世界上做自主进化 (对标 FSD 的影子模式)。

老倪 2026-10-30: 「在 550C 中, 建立虚拟世界用 3DGS 表达, 自主进化开发影子模式,
对标特斯拉的 FSD —— 驾驶员在开车, FSD 在虚拟世界里自主进化」

═══════════════════════════════════════════════════════════════════════════
与 FSD 的对应关系
  真机在跑 (驾驶员开车)      →  zmax-550c-shadow 服务: 只读位姿/相机/AOI, 零指令
                                + 8806 autocap 把真实帧采成数据集
  车队数据回流               →  ~/zmax_shadow/ 经验记忆 + AOI 真实判定当标签
  虚拟世界 (sim)             →  8814 用真实帧训 3DGS (Arc GPU), 得到该工位的数字孪生
  FSD 在虚拟世界里自主进化   →  **本脚本**: 用真实帧的 holdout PSNR 当判据,
                                进化 3DGS 训练超参, 让虚拟世界保真度单调上升

为什么判据必须是 holdout PSNR
  3DGS 的"训练视角 PSNR"是背答案 (它就是在拟合那些图)。只有 **留出整段轨迹** 的
  PSNR 才代表"这个虚拟世界在没见过的视角上是不是真的对"。所以固定
  --holdout-mode block, 且每代都从 stdout 解析"留出视角 PSNR"这一行, 解析不到判废。

铁律
  ① 零真机指令: 本脚本只调 8814/gs_train.py 训练, 不碰任何运动/抓取接口。
  ② 不编数字: 每代分数只来自 gs_train.py 的实测输出; 解析失败/训练失败 ⇒ 判废, 不进台账。
  ③ 不覆盖历史: 台账只追加。
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import os
import os.path as osp
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
OUT = osp.join(HOME, "shadow_world")
LEDGER = osp.join(OUT, "evolve_ledger.json")
EXP = osp.join(OUT, "experience.jsonl")

GSX = osp.join(HOME, "gsxpu-venv", "bin", "python")
TRAIN = "/home/intel/zmax_map/tools/gs_train.py"
# 真实采集帧的数据集 (8806 autocap 的产出; 也可用 SS_DATASET 指其它会话)
DATASET = os.environ.get("SS_DATASET", "")

# 可进化参数: (名, 中心值, 对数空间?, 下界, 上界)
GENOME = [
    ("prune_opa",    0.005,   True,  5e-4,  5e-2),    # 低于此不透明度剪掉
    ("grow_grad2d",  0.0002,  True,  3e-5,  3e-3),    # 梯度阈值: 越大长得越少
    ("grow_scale3d", 0.01,    True,  0.004, 0.06),    # 3D 尺度超过则分裂
    ("grow_scale2d", 0.05,    True,  0.02,  0.25),    # 屏幕尺度超过则分裂
    ("sh_degree",    2.0,     False, 0.0,   3.0),     # 球谐阶数
    ("init_points",  100000., False, 50000., 200000.),# 初始高斯点数
]

STEPS = int(os.environ.get("SW_STEPS", "800"))        # 每代训练步数 (影子评估用短跑)
GENS = int(os.environ.get("SW_GENS", "6"))
MARGIN = float(os.environ.get("SW_MARGIN", "0.15"))   # dB, 优于 best 这么多才采纳
SEED = int(os.environ.get("SW_SEED", "0"))


def log(*a) -> None:
    print("[shadow-world] " + " ".join(str(x) for x in a), flush=True)


def _append(path: str, rec: dict) -> None:
    os.makedirs(osp.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_ledger() -> dict:
    if osp.exists(LEDGER):
        try:
            with open(LEDGER, encoding="utf-8") as f:
                d = json.load(f)
            d.setdefault("entries", [])
            return d
        except (OSError, ValueError):
            pass
    return {"entries": [], "best": None, "best_psnr": None}


def save_ledger(d: dict) -> None:
    os.makedirs(OUT, exist_ok=True)
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LEDGER)


def pick_dataset() -> str | None:
    """找一份真实采集的数据集 (含 cameras.json + images/)。"""
    if DATASET and osp.isdir(DATASET):
        return DATASET
    base = "/home/intel/gs_train_service_intel/jobs"
    if not osp.isdir(base):
        return None
    cands = []
    for j in os.listdir(base):
        ds = osp.join(base, j, "ds")
        cj = osp.join(ds, "cameras.json")
        im = osp.join(ds, "images")
        if osp.isfile(cj) and osp.isdir(im):
            n = len(os.listdir(im))
            if n >= 80:                    # 少于 80 张做不出可用世界
                cands.append((n, os.path.getmtime(cj), ds))
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][2]


def run_train(params: dict, tag: str) -> dict:
    """跑一代 3DGS 训练, 从 stdout 解析留出视角 PSNR。返回 {ok, psnr, why}。"""
    out = osp.join(OUT, "runs", tag)
    os.makedirs(out, exist_ok=True)
    cmd = [GSX, TRAIN, "--data", DS, "--out", out, "--steps", str(STEPS),
           "--holdout-mode", "block",
           "--prune-opa", "%.6g" % params["prune_opa"],
           "--grow-grad2d", "%.6g" % params["grow_grad2d"],
           "--grow-scale3d", "%.6g" % params["grow_scale3d"],
           "--grow-scale2d", "%.6g" % params["grow_scale2d"],
           "--sh-degree", str(int(round(params["sh_degree"]))),
           "--init-points", str(int(round(params["init_points"]))),
           "--seed", str(SEED)]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)  # noqa: S603
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": "训练超时(3600s)", "secs": round(time.time() - t0, 1)}
    except OSError as e:
        return {"ok": False, "why": f"起不来 {type(e).__name__}: {e}"}
    txt = (r.stdout or "") + "\n" + (r.stderr or "")
    m = re.findall(r"留出视角\s*PSNR\s*=\s*([0-9.]+)\s*dB", txt)
    if not m:
        tail = txt.strip().splitlines()[-3:]
        return {"ok": False, "why": "没解析到留出视角 PSNR: " + " | ".join(tail)[:200],
                "secs": round(time.time() - t0, 1), "rc": r.returncode}
    psnr_h = float(m[-1])
    tr = re.findall(r"训练视角\s*([0-9.]+)\s*dB", txt)
    return {"ok": True, "psnr": psnr_h,
            "psnr_train": float(tr[-1]) if tr else None,
            "secs": round(time.time() - t0, 1), "rc": r.returncode}


def mutate(base: dict, rng) -> dict:
    """从 best 出发按对数/线性抖动变异, 全部夹在物理界限内。"""
    g = {}
    for name, _c, is_log, lo, hi in GENOME:
        v = float(base[name])
        if name == "sh_degree":
            g[name] = float(max(lo, min(hi, round(v + rng.choice([-1, 0, 0, 1])))))
        elif is_log:
            g[name] = float(min(hi, max(lo, v * (2.0 ** rng.uniform(-1.0, 1.0)))))
        else:
            g[name] = float(min(hi, max(lo, v * rng.uniform(0.6, 1.6))))
    return g


def main() -> int:
    global DS
    os.makedirs(osp.join(OUT, "runs"), exist_ok=True)
    ds = pick_dataset()
    if not ds:
        print("__RESULT__" + json.dumps(
            {"ok": False, "why": "没有可用的真实采集数据集(需 >=80 张真图 + cameras.json); "
                                 "8806 autocap 还在攒帧"}, ensure_ascii=False))
        return 0
    DS = ds
    n_img = len(os.listdir(osp.join(ds, "images")))
    log(f"数据集 = {ds} ({n_img} 张真实帧) · 每代 {STEPS} 步 · {GENS} 代")

    import random
    rng = random.Random(SEED + int(time.time()) // 3600)

    led = load_ledger()
    best = led.get("best") or {n: c for n, c, _l, _a, _b in GENOME}
    best_p = led.get("best_psnr")
    log(f"台账 {len(led['entries'])} 条 · best_psnr={best_p}")

    acc = rej = 0
    for _ in range(GENS):
        cand = mutate(best, rng)
        gen = len(led["entries"]) + 1
        tag = time.strftime("%Y%m%d_%H%M%S") + f"_g{gen}"
        t0 = time.time()
        r = run_train(cand, tag)
        secs = round(time.time() - t0, 1)
        if not r.get("ok"):
            log(f"gen{gen} 判废: {r.get('why')} ({secs}s)")
            rej += 1
            led["entries"].append({"gen": gen, "params": cand, "ok": False,
                                   "why": r.get("why"), "secs": secs})
            save_ledger(led)
            continue
        p = r["psnr"]
        improved = (best_p is None) or (p > best_p + MARGIN)
        if improved:
            best, best_p = cand, p
            acc += 1
        else:
            rej += 1
        led["entries"].append({"gen": gen, "params": cand, "ok": True, "psnr": p,
                               "psnr_train": r.get("psnr_train"), "secs": secs,
                               "accepted": bool(improved), "dataset": ds,
                               "n_images": n_img})
        led["best"], led["best_psnr"] = best, best_p
        save_ledger(led)
        _append(EXP, {"t": time.time(), "gen": gen, "psnr_holdout": p,
                      "psnr_train": r.get("psnr_train"), "params": cand,
                      "accepted": bool(improved), "secs": secs, "n_images": n_img})
        log(f"gen{gen} 留出PSNR={p:.2f}dB (训练视角 {r.get('psnr_train')}) "
            f"{secs}s {'采纳' if improved else '回滚'}  best={best_p:.2f}dB")

    out = {"ok": True, "gens": GENS, "accepted": acc, "rejected": rej,
           "best_psnr": best_p, "best_params": best, "dataset": ds,
           "n_images": n_img, "steps": STEPS, "host": os.uname().nodename,
           "data": f"真实相机帧 {n_img} 张 (8806 autocap 采) + 3DGS 在 Arc GPU 上训",
           "fitness_semantics": "3DGS 留出整段轨迹的可视 PSNR (dB), 越高越好; "
                                "不是真机精度, 是虚拟世界的重建保真度"}
    print("__RESULT__" + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
