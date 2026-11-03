#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_cond_proj_2stage.py — 两段式训练条件投影 (复用 LoRA 那套: 冻结主干, 只训小投影)

为什么两段式 (本机 8GB 显存的唯一可行路径):
  推理路径 predict_action / predict_action_chunk 是 **numpy 往返 + @torch.no_grad()**
  (modeling_smolvla_lew.py:536 torch.from_numpy) ⇒ 计算图断, 反传 500M 主干也必 OOM。
  但 action_head.forward (action_head.py:375) 是 **纯 torch 的 flow-matching 训练分支**,
  接收 conditioning_tokens / actions / p_cond, 直接出 loss。于是:
      第一段  no_grad 编码: images+lang → multimodal_embeds (常量, 不建图)
      第二段  可微训练:     emb + actions + p_cond → loss → 只反传到 p_cond_proj
  显存只吃 DiT + 3×960 投影, 8GB 够用。

判据 (留出集, 按帧 8:2 切):
  ① 基线 p_cond=0 的动作 RMSE (推理值 vs 真值)
  ② 训练后 p_cond=真值 的 RMSE —— 必须下降
  ③ 对照: 训好的权重 + p_cond=0 —— 必须回到基线 (证明增益来自条件)

用法:
  --smoke  8 帧跑通两段链路
  正式:   --limit 4000 --epochs 3
"""
import argparse
import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

DS_DEFAULT = os.path.join(ROOT, "data/datasets/sim_TASK-01-FW")
CK_DEFAULT = "outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model"
TASK = "insert the optical module into the slot"


def load_ds(ds, limit=None):
    import pyarrow.parquet as pq
    fs = sorted(glob.glob(os.path.join(ds, "data/**/*.parquet"), recursive=True))
    cols = {k: [] for k in ("observation.state", "action", "episode_index", "frame_index")}
    for f in fs:
        t = pq.read_table(f)
        for k in cols:
            if k in t.column_names:
                cols[k].append(np.asarray(t[k].to_pylist()))
    for k in cols:
        cols[k] = np.concatenate(cols[k])
    st, ac = cols["observation.state"], cols["action"]
    n = len(st) if limit is None else min(int(limit), len(st))
    vid = sorted(glob.glob(os.path.join(ds, "videos/observation.image/**/*.mp4"), recursive=True))
    return {"state": st[:n].astype(np.float32), "action": ac[:n].astype(np.float32),
            "ep": cols["episode_index"][:n], "video": vid[0] if vid else None}


class Frames:
    def __init__(self, path):
        import cv2
        self.f = []
        cap = cv2.VideoCapture(path)
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            self.f.append(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
        cap.release()

    def __len__(self):
        return len(self.f)

    def get(self, i):
        return self.f[int(i) % len(self.f)]


def build_pcond(states, eps=None, log=print):
    """L4 条件 = **旋转意图**: 目标四元数 × 当前四元数的逆 → 3 维旋转向量 (S³ 上的误差方向)。

    来源: 数据集 state[7:11] 是真四元数 (范数恒为 1.000, 实测), 目标取每 episode 末帧姿态。
    这条量回答"还要往哪转", 与 state 里的当前姿态不是同一个量 (是误差/意图), 有独立信息。
    """
    st = np.asarray(states, dtype=np.float64)
    q = st[:, 7:11].copy()
    q /= (np.linalg.norm(q, axis=1, keepdims=True) + 1e-12)
    n = len(q)
    goal = np.zeros_like(q)
    if eps is None:
        goal[:] = q[-1]                                   # 无 episode 标签: 用末帧
    else:
        for e in np.unique(eps):
            m = np.asarray(eps) == e
            goal[m] = q[np.where(m)[0][-1]]
    out = np.zeros((n, 3), dtype=np.float32)
    for i in range(n):
        # 相对旋转 r = conj(q_cur) * q_goal  (wxyz)
        w1, v1 = q[i, 0], q[i, 1:4]
        w2, v2 = goal[i, 0], goal[i, 1:4]
        w = w1 * w2 + float(v1 @ v2)
        v = w1 * v2 - w2 * v1 - np.cross(v1, v2)
        if w < 0:                                          # 取短弧
            w, v = -w, -v
        nv = np.linalg.norm(v)
        if nv < 1e-12:
            continue
        ang = 2.0 * np.arctan2(nv, max(w, 0.0))
        out[i] = (v / nv) * ang
    log("  p_cond: 非零 %d/%d | |rotvec| 中位 %.4f rad" % (int((np.abs(out).sum(1) > 1e-9).sum()), n,
                                                          float(np.median(np.linalg.norm(out, axis=1)))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", default=DS_DEFAULT)
    ap.add_argument("--ckpt", default=CK_DEFAULT)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", default="models/p_cond_proj_2stage.pt")
    a = ap.parse_args()

    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("设备:", dev)

    d = load_ds(a.ds, a.limit or (8 if a.smoke else None))
    print("数据: %d 帧 | state %s | action %s" % (len(d["state"]), d["state"].shape, d["action"].shape))

    from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
    from lerobot.policies.factory import make_pre_post_processors
    ck = a.ckpt if os.path.isabs(a.ckpt) else os.path.join(ROOT, a.ckpt)
    pol = SmolVLALewPolicy.from_pretrained(ck).to(dev).eval()
    pol.config.device = dev
    pre, post = make_pre_post_processors(pol.config, ck)
    head = pol.model.action_model
    head.ensure_p_cond(dim=3)
    proj = head.p_cond_proj
    print("p_cond_proj:", tuple(proj.weight.shape), "| 初始 max|w| = %.3e" % float(proj.weight.abs().max()))

    for p_ in pol.parameters():
        p_.requires_grad_(False)
    proj.weight.requires_grad_(True)

    vf = Frames(d["video"])
    pcond = build_pcond(d["state"], d["ep"])
    torch.set_grad_enabled(True)

    def encode(sel):
        """第一段: no_grad 编码 → conditioning tokens (常量)。"""
        imgs = np.stack([vf.get(i) for i in sel])
        it = torch.from_numpy(imgs).permute(0, 3, 1, 2).float().to(dev) / 255.0
        batch = {"observation.image": it,
                 "observation.state": torch.from_numpy(d["state"][sel]).to(dev),
                 "action": torch.from_numpy(d["action"][sel]).to(dev)}
        batch = pre(batch)
        batch["task"] = [TASK] * len(sel)
        examples = pol._prepare_model_inputs(batch)
        with torch.no_grad():
            emb = pol.model._get_multimodal_embeds([ex["image"] for ex in examples],
                                             [ex["lang"] for ex in examples])
        st = torch.from_numpy(np.stack([ex["state"] for ex in examples])).to(dev).float()
        act = torch.from_numpy(np.stack([ex["action"] for ex in examples])).to(dev).float()
        return emb.detach().float(), st.float(), act.float()   # SigLIP 出 bf16, 统一 fp32 才能接 action_head

    CACHE = {}

    def precompute(sel):
        """一次性把每帧编码成 conditioning tokens 缓存 (编码段只跑一遍)。"""
        E, S, A = [], [], []
        B0 = 8          # 16 帧编码会 OOM (SigLIP 激活), 8 帧实测可行
        for b0 in range(0, len(sel), B0):
            e, s_, a_ = encode(sel[b0:b0 + B0])
            E.append(e.cpu()); S.append(s_.cpu()); A.append(a_.cpu())
            if (b0 // B0) % 10 == 0:
                print("  编码 %d/%d" % (b0 + len(sel[b0:b0 + B0]), len(sel)))
        CACHE["E"] = torch.cat(E); CACHE["S"] = torch.cat(S); CACHE["A"] = torch.cat(A)
        print("预编码完成 %s | %.0f MB" % (tuple(CACHE["E"].shape), CACHE["E"].numel() * 4 / 1e6))

    def train_step(sel):
        E, S, A = CACHE["E"], CACHE["S"], CACHE["A"]
        ti = torch.from_numpy(np.asarray(sel))
        emb = E[ti].to(dev); st = S[ti].to(dev); act = A[ti].to(dev)
        pc = torch.from_numpy(pcond[sel]).to(dev)
        return head(conditioning_tokens=emb, actions=act, state=st, p_cond=pc)

    def infer_rmse(sel, zero_cond=False):
        """第三段评估: 走推理路径 (numpy) 拿动作, 与真值比。"""
        tot, cnt = 0.0, 0
        for b0 in range(0, len(sel), a.batch):
            b = sel[b0:b0 + a.batch]
            imgs = np.stack([vf.get(i) for i in b])
            it = torch.from_numpy(imgs).permute(0, 3, 1, 2).float().to(dev) / 255.0
            batch = {"observation.image": it,
                     "observation.state": torch.from_numpy(d["state"][b]).to(dev)}
            batch = pre(batch)
            batch["task"] = [TASK] * len(b)
            pc = torch.zeros((len(b), 3), device=dev) if zero_cond else torch.from_numpy(pcond[b]).to(dev)
            with torch.no_grad():
                y = pol.predict_action_chunk(batch, p_cond=pc)
            y = y.reshape(len(b), -1)[:, :4].cpu().numpy()
            tot += float((((y - d["action"][b]) ** 2)).sum())
            cnt += len(b) * 4
        return (tot / max(cnt, 1)) ** 0.5

    idx = np.arange(len(d["state"]))
    if a.smoke:
        loss = train_step(idx)
        print("smoke: loss = %.6f | grad = %s" % (float(loss), proj.weight.grad is None and "None" or "有"))
        loss.backward()
        print("反向 OK | |grad| = %.6e" % float(proj.weight.grad.abs().sum()))
        return 0

    cut = int(len(idx) * 0.8)
    tr, va = idx[:cut], idx[cut:]
    print("train %d / val %d" % (len(tr), len(va)))

    precompute(idx)                       # 编码只跑一遍, 之后训练只过 DiT
    va_eval = va[:160]                    # 评估走推理路径更慢, 取子集

    opt = torch.optim.Adam([proj.weight], lr=a.lr)
    base = infer_rmse(va_eval, zero_cond=True)
    print("基线 (p_cond=0) val RMSE = %.6f" % base)

    for ep in range(a.epochs):
        np.random.shuffle(tr)
        run, nb = 0.0, 0
        for b0 in range(0, len(tr), a.batch):
            b = tr[b0:b0 + a.batch]
            if len(b) < 2:
                continue
            loss = train_step(b)
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_([proj.weight], 1.0)
            opt.step()
            run += float(loss); nb += 1
        v1 = infer_rmse(va_eval, zero_cond=False)
        v0 = infer_rmse(va_eval, zero_cond=True)
        print("epoch %d | train loss %.6f | val RMSE(cond) %.6f | val RMSE(zero) %.6f | vs 基线 %+.2f%%"
              % (ep + 1, run / max(1, nb), v1, v0, (v1 - base) / base * 100))

    torch.save({"p_cond_proj": proj.weight.detach().cpu(), "dim": 3}, os.path.join(ROOT, a.out))
    print("✅ 已保存", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
