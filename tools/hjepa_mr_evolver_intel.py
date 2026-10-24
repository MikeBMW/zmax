#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧬 hjepa_mr_evolver_intel.py — 550C 几何分支自主进化 (跑在 Intel Arc 上)

适应度 = 几何自洽性, **不靠真值标注**:
  ① SE(3) 时序一致性: 相邻帧 twist 二阶差分小 (运动连续)
  ② 球面法线平滑性: 相邻帧法线切向量变化小
  ③ 切空间 NLL 校准: 不确定性报得准 ⇒ NLL 低

三个分量各自归一化后接**固定权重**。踩过的坑: 让权重参与变异时,
分数 6.17→11.89 全靠 w_nll 0.30→0.98, 模型本身没变好 —— 平凡基线式假提升。

台账 ~/hjepa_mr/evolve_ledger.json, 每代从 best 续, 优于 best+margin 才采纳。

用法 (Intel 上):
    ZMAX_ROOT=~/hjepa_mr MR_GENS=6 ~/train_venv/bin/python evolve.py
"""
import json
import os
import os.path as osp
import sys
import time

import numpy as np

_R = os.environ.get("ZMAX_ROOT", "/home/intel/hjepa_mr")
for _p in (os.path.join(_R, "src"), _R, os.path.expanduser("~/hjepa_mr")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OUT = osp.expanduser("~/hjepa_mr")
os.makedirs(OUT, exist_ok=True)
LEDGER = osp.join(OUT, "evolve_ledger.json")


def log(*a):
    print(*a, flush=True)


def _import_branch():
    """扁平 / 包结构双兼容: Intel 上推过去是扁平 .py, 本机是 lerobot.manifold 包。"""
    try:
        from lerobot.manifold.hjepa_manifold import (  # type: ignore
            build_geometric_branch, ema_update, make_momentum_target,
            tangent_gaussian_nll)
    except Exception:
        from hjepa_manifold import (  # type: ignore
            build_geometric_branch, ema_update, make_momentum_target,
            tangent_gaussian_nll)
    return (build_geometric_branch, make_momentum_target, ema_update,
            tangent_gaussian_nll)


def build_traj(n=80, seed=0):
    """造一段装配式轨迹: 位置平滑推进 + 微小姿态摆动 + 末段归零。

    ⚠ 这是**合成数据**, 只用来验证进化链路能跑; 真实适应度要用真机位姿
    (见 hjepa_mr_train_550a.py 从 jobs/*/ds/cameras.json 读真轨迹)。
    """
    t = np.linspace(0, 1, n)
    pos = np.stack([0.05 * (1 - t), 0.01 * (1 - t) ** 2, 0.002 * np.sin(6 * t)], axis=1)
    rpy = np.stack([0.02 * np.sin(8 * t), 0.015 * np.cos(7 * t), 0.01 * np.sin(5 * t)], axis=1)
    rpy *= (1 - t)[:, None]
    obs = np.concatenate([pos, rpy, np.full((n, 1), 0.5)], axis=1)
    return obs, np.c_[pos, rpy, np.zeros(n)]


def evaluate(hp, obs):
    """给定超参建几何分支, 在轨迹上自监督训几步, 再算几何自洽适应度。"""
    try:
        import torch

        (build_geometric_branch, make_momentum_target, ema_update,
         tangent_gaussian_nll) = _import_branch()
        torch.manual_seed(int(hp["seed"]))
        br = build_geometric_branch(d_in=256, d_g=int(hp["d_g"]),
                                    n_layers=int(hp["n_layers"]),
                                    with_uncertainty=True)
        tg = make_momentum_target(br)
        rs = np.random.RandomState(int(hp["seed"]) + 7)
        proj = torch.from_numpy((rs.normal(size=(7, 256)) / np.sqrt(7)).astype(np.float32))
        obs_t = torch.from_numpy(obs.astype(np.float32))
        opt = torch.optim.Adam(br.parameters(), lr=float(hp["lr"]))
        for _ in range(int(hp["steps"])):
            h = obs_t @ proj
            o = br(h)
            xi = o["xi"]
            smooth = (xi[2:] - 2 * xi[1:-1] + xi[:-2]).pow(2).mean()
            v_small = o["v_n"].pow(2).mean()
            loss = smooth + float(hp["lam_v"]) * v_small
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(br.parameters(), 1.0)
            opt.step()
            ema_update(tg, br, float(hp["momentum"]))

        with torch.no_grad():
            o = br(obs_t @ proj)
            xi = o["xi"].numpy()
            vn = o["v_n"].numpy()
            ls = o["log_sigma"].numpy()

        f_se3 = float(-np.mean(np.linalg.norm(np.diff(xi, axis=0), axis=1)))
        f_sph = float(-np.mean(np.linalg.norm(np.diff(vn, axis=0), axis=1)))
        nlls = [float(tangent_gaussian_nll(xi[i], xi[i + 1], ls[i][:6]))
                for i in range(len(xi) - 1)]
        f_nll = float(-np.mean(nlls))

        # 各分量归一化到同量级再接固定权重
        # 踩过: 原样加权时 f_se3/f_sph 是 -1e-4, f_nll 是 -12 ⇒ 全被 nll 吃掉
        ref_se3, ref_sph, ref_nll = 1e-2, 1e-2, 12.0
        u_se3 = f_se3 / ref_se3
        u_sph = f_sph / ref_sph
        u_nll = (f_nll + ref_nll) / ref_nll
        fitness = hp["w_se3"] * u_se3 + hp["w_sph"] * u_sph + hp["w_nll"] * u_nll
        return {"ok": True, "fitness": float(fitness),
                "u_se3": float(u_se3), "u_sph": float(u_sph), "u_nll": float(u_nll),
                "f_se3": f_se3, "f_sph": f_sph, "f_nll": f_nll,
                "n_params": sum(p.numel() for p in br.parameters())}
    except Exception as e:                                             # noqa: BLE001
        import traceback
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:200]),
                "tb": traceback.format_exc()[-600:]}


def load_ledger():
    if osp.exists(LEDGER):
        try:
            return json.load(open(LEDGER))
        except Exception:                                              # noqa: BLE001
            pass
    return {"entries": [], "best": None, "best_fitness": None}


def save_ledger(led):
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(led, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LEDGER)


def main():
    gens = int(os.environ.get("MR_GENS", "6"))
    margin = float(os.environ.get("MR_MARGIN", "0.002"))
    n_frames = int(os.environ.get("MR_FRAMES", "80"))
    obs, _ = build_traj(n=n_frames)
    led = load_ledger()
    best = led.get("best")
    best_f = led.get("best_fitness")
    log("[550C] 轨迹 %d 帧 (合成) · 已跑 %d 代 · best_fitness=%s"
        % (len(obs), len(led["entries"]), best_f))

    rng = np.random.default_rng(int(os.environ.get("MR_SEED", "0")) + len(led["entries"]))
    accepted = rejected = 0
    for _ in range(gens):
        base = (dict(best["hp"]) if best else
                dict(d_g=128, n_layers=2, lr=3e-3, steps=30, momentum=0.99,
                     lam_v=0.5, w_se3=1.0, w_sph=1.0, w_nll=0.3, seed=0))
        hp = dict(base)
        hp["lr"] = float(np.clip(base["lr"] * rng.uniform(0.6, 1.6), 1e-4, 3e-2))
        hp["steps"] = int(np.clip(base["steps"] + rng.integers(-8, 13), 10, 80))
        hp["d_g"] = int(rng.choice([64, 96, 128, 160]))
        hp["n_layers"] = int(rng.choice([2, 3]))
        hp["lam_v"] = float(np.clip(base["lam_v"] * rng.uniform(0.5, 2.0), 0.05, 5.0))
        # 🔴 适应度权重固定不许变异 (实测让它们变异 ⇒ 假提升)
        hp["w_se3"], hp["w_sph"], hp["w_nll"] = 1.0, 1.0, 0.3
        hp["seed"] = int(rng.integers(0, 10000))

        t0 = time.time()
        r = evaluate(hp, obs)
        secs = time.time() - t0
        gen = len(led["entries"]) + 1

        if not r.get("ok"):
            log("[550C] gen%d 失败: %s" % (gen, r.get("why")))
            log((r.get("tb") or "")[-400:])
            rejected += 1
            led["entries"].append({"gen": gen, "hp": hp, "ok": False,
                                   "why": r.get("why"), "secs": round(secs, 2)})
            save_ledger(led)
            continue

        f = r["fitness"]
        acc = (best_f is None) or (f > best_f + margin)
        if acc:
            best, best_f = {"hp": hp}, f
            accepted += 1
        else:
            rejected += 1
        led["entries"].append({
            "gen": gen, "hp": hp, "ok": True, "fitness": round(f, 6),
            "u_se3": round(r["u_se3"], 6), "u_sph": round(r["u_sph"], 6),
            "u_nll": round(r["u_nll"], 6),
            "f_se3": round(r["f_se3"], 8), "f_sph": round(r["f_sph"], 8),
            "f_nll": round(r["f_nll"], 4),
            "n_params": r["n_params"], "secs": round(secs, 2), "accepted": bool(acc),
            "reason": ("提升 → 采纳" if acc else
                       "未提升 (%.6f ≤ best %.6f + %.4f)" % (f, best_f or 0, margin))})
        led["best"], led["best_fitness"] = best, best_f
        save_ledger(led)
        log("[550C] gen%d fitness=%.4f (u_se3=%.3f u_sph=%.3f u_nll=%.3f | "
            "raw se3=%.2e sph=%.2e nll=%.2f) params=%d %.1fs %s"
            % (gen, f, r["u_se3"], r["u_sph"], r["u_nll"], r["f_se3"], r["f_sph"],
               r["f_nll"], r["n_params"], secs, "采纳" if acc else "回滚"))

    out = {"ok": True, "when": time.time(), "gens": gens,
           "accepted": accepted, "rejected": rejected,
           "best_fitness": best_f, "best_hp": (best or {}).get("hp"),
           "n_entries": len(led["entries"]), "host": os.uname().nodename,
           "data": "合成轨迹 (正弦装配式)",
           "fitness_semantics": "几何自洽性 (SE3平滑+法线平滑+NLL校准), 非真值精度"}
    print("__RESULT__" + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
