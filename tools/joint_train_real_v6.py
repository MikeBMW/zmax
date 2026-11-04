#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 多层同时训练架构 V6 — 真像素 + 力觉支路 + 全 chunk 多步监督 (单一 autograd 图)

老倪: "不要分开训练低层和高层。把所有数据(力觉/视觉/动作)全喂给网络, 让整个系统像一个大齿轮一起转。"

相对 V5 的三处**实测缺陷**修复:
  ① 视觉真帧: V5 第 244 行 `px = torch.rand(...)` 喂的是噪声; 本文件默认读 h5 真 pixels
     (--pixels rand 可复现 V5 口径做同代码 A/B)
  ② 力觉进图: obs[13:18] 是引擎 cur18 的力/触觉预留位; 本文件 ForceEncoder 把它编码后
     注入 L4 潜空间, 并加力预测头 L_force (预测下一步力/接触)。
     ★ 实测: 当前数据集该 5 位全 0 (max|·|=0.0) ⇒ 力信号为空时**自动跳过**该项并显式报出,
       不伪造梯度 —— 力要真进图必须先把真力写进这 5 位。
  ③ 全 chunk + 多步: 动作 loss 覆盖 t..t+6 全部 7 步 (V5 只取 u[:,0]);
     世界模型加 k 步 rollout 一致 (t→t+1→t+2)。

一条图: 单一 Adam(model.parameters()) + 单次 backward, 梯度同时回传
       L2 / 力编码器 / 记忆 / L4 encoder+predictor / L3 动作头。

用法:
  PY=/home/ubuntu/zmax/external/INTACT-JEPA/.venv/bin/python
  $PY tools/joint_train_real_v6.py --steps 200 --batch 6
  $PY tools/joint_train_real_v6.py --steps 200 --pixels rand --out reports/joint_real_v6_rand.json   # V5 口径对照
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = "/home/ubuntu/zmax"
INTACT = "/home/ubuntu/zmax/external/INTACT-JEPA"
CACHE = "/home/ubuntu/zmax/zmax_data/stable-wm-cache"
CKPT_DIR = f"{CACHE}/checkpoints/intact_l4_current"
sys.path.insert(0, f"{ROOT}/src")
sys.path.insert(0, INTACT)
os.chdir(ROOT)

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

K_ACT = 0.5        # 引擎标定: act = u / K_ACT
FORCE_SLICE = slice(13, 18)   # 引擎 cur18 里力/触觉预留位 (13-15 wrench 3 维 + 16-17 触觉 2 维)
CHUNK = 7


def grad_norm(mod):
    tot, n = 0.0, 0
    for _, p in mod.named_parameters():
        if p.requires_grad and p.grad is not None:
            tot += float(p.grad.detach().norm() ** 2)
            n += 1
    return (tot ** 0.5), n


def load_memory_features(dim=192):
    """五层记忆 → 定长向量 (真数据, 来自 data/*memory*.json)。"""
    feats, names = [], []
    try:
        mm = json.load(open(f"{ROOT}/data/muscle_memory.json"))
        champs = [k for k, v in mm.items() if isinstance(v, dict) and v.get("champ_u")]
        n_ok = sum(int(v.get("n_ok") or 0) for v in mm.values() if isinstance(v, dict))
        feats += [len(mm) / 1000.0, len(champs) / 100.0, n_ok / 100.0]
        names += ["muscle_n", "muscle_champ", "muscle_ok"]
    except Exception:                                                      # noqa: BLE001
        feats += [0.0, 0.0, 0.0]
        names += ["muscle_x3"]
    try:
        sm = json.load(open(f"{ROOT}/data/shared_memory.json"))
        feats += [len(sm.get("l2") or []) / 100.0, len(sm.get("l3") or []) / 100.0,
                  len(sm.get("l4") or []) / 100.0, len(sm.get("links") or []) / 100.0]
        names += ["l2_n", "l3_n", "l4_n", "links_n"]
    except Exception:                                                      # noqa: BLE001
        feats += [0.0] * 4
        names += ["shared_x4"]
    try:
        asm = json.load(open(f"{ROOT}/data/assembly_memory.json"))
        runs = asm.get("runs") or []
        done = sum(1 for r in runs if r.get("done"))
        feats += [len(runs) / 100.0, done / 100.0,
                  (done / len(runs) if runs else 0.0)]
        names += ["runs_n", "runs_done", "runs_rate"]
    except Exception:                                                      # noqa: BLE001
        feats += [0.0] * 3
        names += ["assembly_x3"]
    try:
        mac = json.load(open(f"{ROOT}/data/macro_memory.json"))
        feats += [len(mac.get("knowledge") or []) / 100.0,
                  len(mac.get("diagnosis") or []) / 100.0,
                  len(mac.get("capability") or {}) / 100.0]
        names += ["macro_k", "macro_diag", "macro_cap"]
    except Exception:                                                      # noqa: BLE001
        feats += [0.0] * 3
        names += ["macro_x3"]
    v = torch.tensor(feats, dtype=torch.float32)
    if v.numel() < dim:
        v = F.pad(v, (0, dim - v.numel()))
    return v[:dim], names


class MemoryEncoder(nn.Module):
    def __init__(self, in_dim=192, out_dim=192):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(in_dim, 64), nn.GELU(),
                                 nn.Linear(64, out_dim), nn.Tanh())

    def forward(self, mem):
        return self.net(mem)


class ForceEncoder(nn.Module):
    """力/触觉 5 维 → 潜向量 (V6 新增: 力进主干)。"""

    def __init__(self, in_dim=5, out_dim=192):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(in_dim, 32), nn.GELU(),
                                 nn.Linear(32, 64), nn.GELU(),
                                 nn.Linear(64, out_dim), nn.Tanh())

    def forward(self, f):
        return self.net(f)


class L2Project(nn.Module):
    def __init__(self, out_dim=192):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(3, 16, 7, stride=4, padding=3), nn.GELU(),
            nn.Conv2d(16, 32, 5, stride=4, padding=2), nn.GELU(),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Linear(32, out_dim))

    def forward(self, img):
        return self.net(img)


class OfficialLikeActionHead(nn.Module):
    """与 lerobot StateSpaceActionHead 同构 (Linear→SiLU→…→Linear) — 保证可部署。"""

    def __init__(self, input_dim=192, action_dim=4, chunk_size=CHUNK, hidden_dim=256, num_layers=2):
        super().__init__()
        layers = [nn.Linear(input_dim, hidden_dim), nn.SiLU()]
        for _ in range(num_layers - 1):
            layers += [nn.Linear(hidden_dim, hidden_dim), nn.SiLU()]
        layers.append(nn.Linear(hidden_dim, action_dim * chunk_size))
        self.mlp = nn.Sequential(*layers)
        self.action_dim = action_dim
        self.chunk_size = chunk_size

    def forward(self, z):
        b = z.shape[0]
        return self.mlp(z).view(b, self.chunk_size, self.action_dim)


class JointV6(nn.Module):
    def __init__(self, jepa, z_dim=192, mem_dim=192):
        super().__init__()
        self.jepa = jepa
        self.l2 = L2Project(z_dim)
        self.force = ForceEncoder(5, z_dim)                # ★ 力觉支路
        self.mem = MemoryEncoder(mem_dim, z_dim)
        self.l3 = OfficialLikeActionHead(z_dim)
        self.wm_proj = nn.Linear(z_dim, z_dim)
        self.l2_cons = nn.Linear(z_dim, z_dim)
        self.up_cons = nn.Linear(z_dim, z_dim)
        self.force_head = nn.Linear(z_dim, 5)              # ★ 力预测头
        self.goal_enc = nn.Sequential(
            nn.Linear(39, 128), nn.GELU(), nn.Linear(128, z_dim))

    def _latent(self, px, act_sem, mem, force):
        l2_tok = self.l2(px)
        f_tok = self.force(force)
        mem_cond = self.mem(mem)
        info = {"pixels": px.unsqueeze(1), "action": act_sem.unsqueeze(1)}
        enc = self.jepa.encode(info)
        z_t = enc["emb"] if isinstance(enc, dict) else enc
        if z_t.dim() == 4:
            z_t = z_t[:, :, 0, :]
        if z_t.dim() == 3:
            z_t = z_t[:, 0, :]
        z_t = z_t[:, :192] + l2_tok + mem_cond + f_tok   # ★ 四源注入 (视觉/记忆/力/JEPA)
        return z_t, l2_tok, f_tok

    def forward(self, px, act_sem, act_sem_next, obs, nobs, obs2, act_chunk, mem, force, force_next,
                use_force=True):
        z_t, l2_tok, f_tok = self._latent(px, act_sem, mem, force)

        # ---- L4: 一步世界模型 ----
        a_emb = self.jepa.action_encoder(act_sem.unsqueeze(1))
        z_pred = self.jepa.predict(z_t.unsqueeze(1), a_emb)[:, 0, :]
        z_goal = self.goal_enc(nobs)
        L_wm = F.mse_loss(self.wm_proj(z_pred), z_goal.detach())

        # ---- L4: 二步 rollout 一致 (t→t+1→t+2) ----
        a_emb2 = self.jepa.action_encoder(act_sem_next.unsqueeze(1))
        z_pred2 = self.jepa.predict(z_pred.unsqueeze(1), a_emb2)[:, 0, :]
        L_wm2 = F.mse_loss(self.wm_proj(z_pred2), self.goal_enc(obs2).detach())

        # ---- L3: 全 chunk 7 步监督 ----
        u = self.l3(z_pred)                                # (b, 7, 4)
        L_act = F.mse_loss(u, act_chunk)

        # ---- 双向耦合 ----
        L_l2 = F.mse_loss(self.l2_cons(l2_tok), z_pred.detach())
        L_up = F.mse_loss(self.up_cons(z_pred), l2_tok.detach())

        # ---- 力预测 (无信号时跳过, 不伪造) ----
        if use_force:
            L_force = F.mse_loss(self.force_head(z_pred), force_next)
        else:
            L_force = torch.zeros((), device=z_pred.device)

        return L_wm, L_wm2, L_act, L_l2, L_up, L_force, u, act_chunk, z_t, z_pred


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5", default=f"{CACHE}/datasets/optical_insert_v6_disturb.h5")
    ap.add_argument("--seed", type=int, default=0, help="同时控制采样与新增模块初始化 (多 seed 复核用)")
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--pixels", choices=["real", "rand"], default="real")
    ap.add_argument("--mask-obs", action="store_true",
                    help="消融: 把 obs 的位置/目标维(0:13)清零, 只留图像+记忆+力 → 用来判视觉是否真带信息")
    ap.add_argument("--grad-clip", type=float, default=1.0, help="梯度裁剪 (0=关); seed3 曾 L_act 0.0089→0.133 崩溃")
    ap.add_argument("--force-mode", choices=["real", "zero", "shuffle"], default="real",
                    help="力消融: real=真力 / zero=力通道全0且不算力loss / shuffle=打乱时间对齐(同分布无信息)")
    ap.add_argument("--mask-obs-all", action="store_true",
                    help="严格消融: 清零 obs[0:36] (含上一帧18维, 否则位姿从 prev 泄漏) — 视觉唯一位姿来源")
    ap.add_argument("--auto-lambda", action="store_true", default=True)
    ap.add_argument("--save", default="")
    ap.add_argument("--out", default=f"{ROOT}/reports/joint_real_v6.json")
    a = ap.parse_args()
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print("=" * 108)
    print("🔗 V6 一条图 — 真像素 + 力觉支路 + 全chunk/多步 | 单 Adam + 单 backward")
    print("=" * 108)
    import h5py
    f = h5py.File(a.h5, "r")
    if "ep_offset" in f and "ep_len" in f:
        ep_off = np.asarray(f["ep_offset"][:], np.int64)
        ep_len = np.asarray(f["ep_len"][:], np.int64)
    elif "ep_idx" in f:                      # 引擎录制器只写 ep_idx → 现算段边界
        eidx = np.asarray(f["ep_idx"][:], np.int64)
        uniq, starts, counts = np.unique(eidx, return_index=True, return_counts=True)
        order = np.argsort(starts)
        ep_off, ep_len = starts[order].astype(np.int64), counts[order].astype(np.int64)
    else:
        raise SystemExit("❌ 数据集既无 ep_offset/ep_len 也无 ep_idx")
    has_px = "pixels" in f
    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    print(f"数据: {os.path.basename(a.h5)} · {len(ep_off)} episodes · pixels={'有' if has_px else '无'}")

    mem_vec, mem_names = load_memory_features()
    print(f"记忆入图: {len(mem_names)} 项 · 非零 {int((mem_vec != 0).sum())}/{mem_vec.numel()}")

    # 力通道是否有真信号 (实测判据, 不是假设)
    fds = None
    if "force" in f:
        fds = np.asarray(f["force"][:], np.float32).reshape(-1)
        f_absmax = float(np.abs(fds).max()) if fds.size else 0.0
        f_src = "h5['force'] (引擎 force_norm)"
    else:
        probe = np.concatenate([np.asarray(f["observation"][int(o) + np.arange(min(int(l), 200)), 13:18])
                                for o, l in zip(ep_off[:20], ep_len[:20])])
        f_absmax = float(np.abs(probe).max()) if probe.size else 0.0
        f_src = "obs[13:18] 预留位"
    use_force = (f_absmax > 1e-6) and (a.force_mode != "zero")
    print(f"力通道 [{f_src}]: max|·|={f_absmax:.3e} → "
          f"{'✅ 有信号, 力进图' if use_force else '⚠️ 全 0 (数据里没力) ⇒ 力预测项跳过, 只保留力编码支路(零输入)'}")

    from hydra.utils import instantiate
    cfg = json.load(open(f"{CKPT_DIR}/config.json"))
    t0 = time.time()
    jepa = instantiate(cfg).to(dev)
    sd = torch.load(f"{CKPT_DIR}/weights.pt", map_location="cpu", weights_only=False)
    jepa.load_state_dict(sd, strict=False)
    print(f"真 JEPA: {time.time() - t0:.1f}s | {sum(p.numel() for p in jepa.parameters()):,} 参数")

    model = JointV6(jepa).to(dev)   # 新增模块已由 torch.manual_seed(a.seed) 决定
    print(f"L2 {sum(p.numel() for p in model.l2.parameters()):,} · "
          f"力 {sum(p.numel() for p in model.force.parameters()):,} · "
          f"记忆 {sum(p.numel() for p in model.mem.parameters()):,} · "
          f"L3 {sum(p.numel() for p in model.l3.parameters()):,}")
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)
    scale = {"wm": 1.0, "wm2": 1.0, "act": 1.0, "l2": 1.0, "up": 1.0, "force": 1.0}
    px_stats = {"mean": 0.0, "std": 0.0}

    def sample(batch):
        obs, nobs, obs2, chunks, force, force_n, pxs = [], [], [], [], [], [], []
        tries = 0
        while len(obs) < batch and tries < batch * 40:
            tries += 1
            e = int(rng.integers(0, len(ep_off)))
            off, ln = int(ep_off[e]), int(ep_len[e])
            if ln < CHUNK + 4:
                continue
            t = int(rng.integers(0, ln - CHUNK - 2))
            o = np.asarray(f["observation"][off + t], np.float32)[:39]
            n = np.asarray(f["observation"][off + t + 1], np.float32)[:39]
            o2 = np.asarray(f["observation"][off + t + 2], np.float32)[:39]
            ch = np.asarray(f["action"][off + t:off + t + CHUNK], np.float32)
            if ch.shape[0] != CHUNK:
                continue
            if a.pixels == "real" and has_px:
                im = np.asarray(f["pixels"][off + t], np.uint8).astype(np.float32) / 255.0
                pxs.append(torch.from_numpy(im).permute(2, 0, 1))
            obs.append(o); nobs.append(n); obs2.append(o2); chunks.append(ch)
            if fds is not None:
                fv, fnv = float(fds[off + t]), float(fds[off + t + 1])
                force.append(np.array([fv, float(fv > 0), o[3], 0.0, 0.0], np.float32))
                force_n.append(np.array([fnv, float(fnv > 0), n[3], 0.0, 0.0], np.float32))
            else:
                force.append(o[13:18]); force_n.append(n[13:18])
        if not obs:
            raise RuntimeError("采样失败: 数据段太短")
        B = len(obs)
        o = torch.from_numpy(np.stack(obs)).float().to(dev)
        n = torch.from_numpy(np.stack(nobs)).float().to(dev)
        o2 = torch.from_numpy(np.stack(obs2)).float().to(dev)
        if a.mask_obs or a.mask_obs_all:     # 消融: 位置/目标维清零 (力通道单独走 fz, 不受影响)
            k = 36 if a.mask_obs_all else 13
            o[:, :k] = 0.0; n[:, :k] = 0.0; o2[:, :k] = 0.0
        ch = torch.from_numpy(np.stack(chunks)).float().to(dev)          # (b,7,4)
        fz = torch.from_numpy(np.stack(force)).float().to(dev)
        fn = torch.from_numpy(np.stack(force_n)).float().to(dev)
        if a.force_mode == "zero":            # 消融: 力通道彻底去掉
            fz = torch.zeros_like(fz); fn = torch.zeros_like(fn)
        elif a.force_mode == "shuffle":       # 消融: 同分布但时间对齐被打乱
            pi = torch.randperm(fz.shape[0], device=fz.device)
            fz, fn = fz[pi], fn[pi]
        if pxs:
            px = torch.stack(pxs).to(dev)
            px_stats["mean"] = float(px.mean()); px_stats["std"] = float(px.std())
        else:
            px = torch.rand(B, 3, 224, 224, device=dev)
            px_stats["mean"] = float(px.mean()); px_stats["std"] = float(px.std())
        sem = torch.clamp(ch[:, 0, :3] / K_ACT, -1, 1)
        act8 = F.pad(sem, (0, 5))                                        # 3 → 8 维真语义
        sem_n = torch.clamp(ch[:, 1, :3] / K_ACT, -1, 1)
        act8n = F.pad(sem_n, (0, 5))                                     # t+1 步语义 (二步 rollout)
        return px, act8, act8n, o, n, o2, ch, fz, fn

    hist = []
    t0 = time.time()
    for i in range(1, a.steps + 1):
        px, act8, act8n, obs, nobs, obs2, ch, fz, fn = sample(a.batch)
        try:
            Ls = model(px, act8, act8n, obs, nobs, obs2, ch,
                       mem_vec.unsqueeze(0).repeat(len(obs), 1).to(dev),
                       fz, fn, use_force=use_force)
        except Exception as e:                                            # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"❌ 前向失败: {type(e).__name__}: {str(e)[:200]}")
            return 1
        L_wm, L_wm2, L_act, L_l2, L_up, L_force, u, target, z_t, z_pred = Ls
        terms = {"wm": L_wm, "wm2": L_wm2, "act": L_act, "l2": L_l2, "up": L_up}
        if use_force:
            terms["force"] = L_force
        if a.auto_lambda:
            with torch.no_grad():
                for k, v in terms.items():
                    scale[k] = 0.9 * scale[k] + 0.1 * max(float(v), 1e-6)
            L = torch.stack([t / scale[k] for k, t in terms.items()]).sum()
        else:
            L = L_wm + L_wm2 + L_act + 0.5 * L_l2 + 0.5 * L_up + (L_force if use_force else 0)
        opt.zero_grad(set_to_none=True)
        L.backward()
        if a.grad_clip and a.grad_clip > 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), a.grad_clip)
        gm, nm = grad_norm(model.mem)
        gf, nf = grad_norm(model.force)
        gl2, nl2 = grad_norm(model.l2)
        gp, npred = grad_norm(model.jepa.predictor)
        ge, nenc = grad_norm(model.jepa.encoder)
        g3, n3 = grad_norm(model.l3)
        gh, nh = grad_norm(model.force_head)
        gconv, nconv = grad_norm(model.l2.net[0])                        # 真像素是否真到 L2 第一层
        opt.step()
        if i % max(1, a.steps // 5) == 0 or i == 1:
            mae = float((u - target).abs().mean())
            mae0 = float((u[:, 0, :] - target[:, 0, :]).abs().mean())
            print(f"  step {i:4d} | L_wm {float(L_wm):.4f} L_wm2 {float(L_wm2):.4f} "
                  f"L_act {float(L_act):.5f} L_l2 {float(L_l2):.4f} L_up {float(L_up):.4f} "
                  f"L_force {float(L_force):.3e} | MAE7 {mae:.4f} MAE1 {mae0:.4f} | "
                  f"∇mem {gm:.1e}({nm}) ∇force {gf:.1e}({nf}) ∇L2 {gl2:.1e}({nl2}) "
                  f"∇conv0 {gconv:.1e}({nconv}) ∇pred {gp:.1e}({npred}) ∇enc {ge:.1e}({nenc}) ∇L3 {g3:.1e}({n3}) ∇fhead {gh:.1e}({nh})")
            hist.append({"step": i, "L_wm": float(L_wm), "L_wm2": float(L_wm2),
                         "L_act": float(L_act), "L_l2": float(L_l2), "L_up": float(L_up),
                         "L_force": float(L_force), "mae7": mae, "mae1": mae0,
                         "g_mem": gm, "g_force": gf, "g_l2": gl2, "g_conv0": gconv,
                         "g_pred": gp, "g_enc": ge, "g_l3": g3, "g_fhead": gh})

    dt = time.time() - t0
    last = hist[-1]
    pixels_real = (a.pixels == "real" and has_px)
    verdict = {
        "真像素进图(数据集有pixels且conv0有梯度)": bool(pixels_real and last["g_conv0"] > 0),
        "梯度回传L2感知": last["g_l2"] > 0,
        "梯度回传力编码器": last["g_force"] > 0,
        "梯度回传力预测头": last["g_fhead"] > 0,
        "力通道有真信号": use_force,
        "梯度回传L4predictor": last["g_pred"] > 0,
        "梯度回传L4encoder": last["g_enc"] > 0,
        "梯度回传L3动作头": last["g_l3"] > 0,
        "梯度回传记忆编码器": last["g_mem"] > 0,
        "动作MAE(全chunk)下降": last["mae7"] < hist[0]["mae7"],
    }
    print("=" * 108)
    for k, v in verdict.items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(f"  像素: mode={a.pixels} mean={px_stats['mean']:.3f} std={px_stats['std']:.3f}")
    print(f"  耗时 {dt:.1f}s | MAE7 {hist[0]['mae7']:.4f} → {last['mae7']:.4f} | "
          f"MAE1 {hist[0]['mae1']:.4f} → {last['mae1']:.4f}")
    print("=" * 108)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": a.steps, "batch": a.batch,
               "pixels": a.pixels, "px_stats": px_stats, "force_signal": use_force,
               "hist": hist, "verdict": verdict, "secs": round(dt, 2)},
              open(a.out, "w"), ensure_ascii=False, indent=1)
    if a.save:
        os.makedirs(a.save, exist_ok=True)
        torch.save({"joint": {k: v for k, v in model.state_dict().items()
                              if k.startswith(("l2.", "force.", "mem.", "l3.", "wm_proj.",
                                               "l2_cons.", "up_cons.", "force_head.", "goal_enc."))},
                    "verdict": verdict}, os.path.join(a.save, "joint_v6.pt"))
        torch.save(model.jepa.state_dict(), os.path.join(a.save, "weights.pt"))
        print(f"产物 → {a.save} (joint_v6.pt + weights.pt[扁平])")
    print(f"取证: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
