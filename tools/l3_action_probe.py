#!/usr/bin/env python3
"""l3_action_probe.py —— L3 (SmolVLA-LEW) 接口探针 / 同源对账 (老倪 2026-11-15「先把接口搞通」)

两条模式, 都必须与训练器/部署走同一条代码路径 (不同源 = 口径必错):
  --config <yaml>   用训练配置现建 policy(和 lerobot_train 同一条 make_policy 路), 维度由数据集自动对齐
  --ckpt   <dir>    加载已训 ckpt (只在不改配置时用)

打印:
  ① 接口契约: action_dim / chunk / n_action_steps / resize / norm ACTION / input_features
  ② 真机数据集同一帧的 action 真值
  ③ 模型原始输出(归一化空间) → postprocessor 反归一化后 → 4 维 mm
  ④ 同口径对账: 量级 / 夹爪 0~70
  ⑤ 线上 action.json 现值

断点: 采样循环在 src/lerobot/policies/smolvla_lew/action_head.py 的 predict_action(),
      本脚本 predict_action_chunk 一定会走进去:
  ./gui-venv311/bin/python -m pdb -c "b /home/ubuntu/zmax/src/lerobot/policies/smolvla_lew/action_head.py:437" -c c tools/l3_action_probe.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HOME", "/home/ubuntu/.cache/huggingface")

import numpy as np
import torch

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

CFG = os.path.join(ROOT, "configs/policies/smolvla/config_smolvla_live1115.yaml")
OLD_CKPT = os.path.join(ROOT, "outputs/train/smolvla_lew_d1/checkpoints/040000/pretrained_model")


def build_from_config(cfg_path: str):
    """与 lerobot_train 完全同一条路: parse → make_dataset → make_policy → make_pre_post_processors."""
    from draccus import parse as dparse
    from lerobot.configs.train import TrainPipelineConfig

    import lerobot.policies.smolvla_lew.configuration_smolvla_lew  # noqa: F401  (注册 "smolvla_lew")
    from lerobot.datasets.factory import make_dataset
    from lerobot.policies import make_policy, make_pre_post_processors

    _argv = sys.argv                      # draccus 会吃 sys.argv, 先摘掉本脚本自己的参数
    sys.argv = [_argv[0]]
    try:
        cfg = dparse(TrainPipelineConfig, config_path=cfg_path)
    finally:
        sys.argv = _argv
    dataset = make_dataset(cfg)
    policy = make_policy(cfg=cfg.policy, ds_meta=dataset.meta, rename_map=cfg.rename_map)
    pre, post = make_pre_post_processors(
        cfg.policy,
        pretrained_path=None,
        dataset_stats=dataset.meta.stats,
        preprocessor_overrides={"device_processor": {"device": "cpu"}},
    )
    return cfg, dataset, policy, pre, post


def build_from_ckpt(ckpt: str):
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy

    policy = SmolVLALewPolicy.from_pretrained(ckpt)
    pre, post = make_pre_post_processors(policy.config, pretrained_path=ckpt)
    return None, None, policy, pre, post


def to_tensor(v, device="cpu"):
    if isinstance(v, torch.Tensor):
        return v.unsqueeze(0).to(device) if v.ndim and v.dtype.is_floating_point or v.ndim >= 3 else v
    return torch.as_tensor(np.asarray(v)).unsqueeze(0).to(device)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=CFG)
    ap.add_argument("--ckpt", default=None)
    ap.add_argument("--idx", type=int, default=100)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--timesteps", type=int, default=1,
                    help="采样步数覆盖(默认 1 = 只验接口通路, 数值不代表策略水平; 要真数值用 4 上 GPU)")
    args = ap.parse_args()

    print("=" * 78)
    if args.ckpt:
        print("① 模式: 加载 ckpt", args.ckpt)
        cfg, dataset, pol, pre, post = build_from_ckpt(args.ckpt)
    else:
        print("① 模式: 用训练配置现建 (与 lerobot_train 同源)", args.config)
        cfg, dataset, pol, pre, post = build_from_config(args.config)
        pol = pol.to(args.device).eval()

    c = pol.config
    print("   action_dim       =", c.action_dim)
    print("   chunk / exec     =", c.chunk_size, "/", c.n_action_steps)
    print("   resize_images_to =", c.resize_images_to, " siglip =", c.siglip_image_size)
    print("   norm ACTION      =", (c.normalization_mapping or {}).get("ACTION"))
    print("   input_features   =", list((c.input_features or {}).keys()))
    print("   output_features  =", list((c.output_features or {}).keys()))

    if dataset is None:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        ds_root = os.path.join(ROOT, "zmax_data/datasets/lerobot/zmax_live_215ep1_128")
        dataset = LeRobotDataset(repo_id="zmax/live_215ep1_128", root=ds_root)

    print("=" * 78)
    print("② 真机数据集同一帧 #%d" % args.idx)
    item = dataset[args.idx]
    print("   帧键:", [k for k in item if k not in ("task",)])
    truth = np.asarray(item["action"], dtype=np.float32).reshape(-1)[:4]
    print("   真机 action [x,y,z(mm),grip] =", np.round(truth, 2))

    # 按 policy 需要的键取 (observation.image ← observation.images.top)
    in_keys = list((c.input_features or {}).keys())
    batch = {}
    for k in in_keys:
        if k in item:
            batch[k] = item[k]
            continue
        cand = [ik for ik in item if ik.startswith("observation.image")]
        if k.startswith("observation.image") and cand:
            batch[k] = item[cand[0]]
            print("   键映射: %s ← %s" % (k, cand[0]))
        else:
            print("   ⚠️ policy 需要 %s, 帧里没有" % k)
    batch["task"] = item.get("task", "insert optical module")

    print("=" * 78)
    print("③ pre → predict_action_chunk(采样循环) → post 反归一化")
    if args.timesteps and args.timesteps > 0:
        pol.config.num_inference_timesteps = int(args.timesteps)
        print("   采样步数覆盖为 %d (接口验证口径)" % args.timesteps)
    b = {k: (v if k == "task" else to_tensor(v).to(args.device)) for k, v in batch.items()}
    b = pre(b)
    with torch.no_grad():
        out = pol.predict_action_chunk(b)
    raw = out.detach().cpu().float()
    print("   原始输出(归一化空间) shape=%s 前4=%s" % (tuple(raw.shape), np.round(raw.reshape(-1)[:4].numpy(), 4)))

    pred4 = denorm(post, out)[:4]
    print("   反归一化后 [x,y,z(mm),grip] =", np.round(pred4, 2))

    print("=" * 78)
    print("④ 同口径对账")
    d = pred4 - truth
    st = json.load(open(os.path.join(ROOT, "zmax_data/datasets/lerobot/zmax_live_215ep1_128/meta/stats.json")))["action"]
    mn = np.array(st["min"], dtype=np.float32)[:4]
    mx = np.array(st["max"], dtype=np.float32)[:4]
    print("   真机 :", np.round(truth, 2))
    print("   模型 :", np.round(pred4, 2))
    print("   训练集范围 [min,max]:", np.round(mn, 2), "~", np.round(mx, 2))
    print("   差值 :", np.round(d, 2), "|Δ|max =", round(float(np.abs(d).max()), 2))

    # ① 接口判据(与策略好不好无关): 4 维 · 落在训练集范围 · 是 mm 而不是 -1~1
    in_range = bool(np.all(pred4 >= mn - 0.05) and np.all(pred4 <= mx + 0.05))
    is_mm = bool(np.abs(pred4[:3]).max() > 50)
    print("   【接口】4 维 + 落在 [min,max] + mm 量级:", "PASS" if (in_range and is_mm) else "FAIL")
    if not is_mm:
        print("      ⇒ 反归一化没生效(输出仍在 -1~1 归一化空间)")
    # ② 水平判据(只有真 ckpt 才有意义)
    if args.ckpt:
        ok = bool(np.abs(d[:3]).max() < 60)
        print("   【水平】与真机同帧偏差 < 60mm:", "PASS" if ok else "FAIL (训练不足/需继续训)")
    else:
        print("   【水平】未加载 ckpt = 随机权重, 偏差不作判据(接口通了即可)")

    ap_path = os.path.join(ROOT, "zmax_data/ss_live/action.json")
    if os.path.exists(ap_path):
        a = json.load(open(ap_path))
        print("⑤ 线上 action.json:", {k: a.get(k) for k in ("src", "i", "x", "y", "z", "grip_mm")})
    return 0


def denorm(post, out: torch.Tensor) -> np.ndarray:
    """用 policy 自己的 postprocessor 反归一化 (ckpt/训练集 stats 同源, MIN_MAX)。"""
    try:
        r = post({"action": out})
        if isinstance(r, dict) and "action" in r:
            return np.asarray(r["action"].detach().cpu().float()).reshape(-1)
    except Exception as e:                                            # noqa: BLE001
        print("   ⚠️ post(dict) 失败: %s" % e)
    try:
        r = post(out)
        return np.asarray(r.detach().cpu().float()).reshape(-1)
    except Exception as e:                                            # noqa: BLE001
        print("   ⚠️ post(tensor) 失败: %s" % e)
    print("   ⚠️ 回退手算 MIN_MAX (仅示意, 不作为交付判据)")
    st = json.load(open(os.path.join(ROOT, "zmax_data/datasets/lerobot/zmax_live_215ep1_128/meta/stats.json")))
    mn = np.array(st["action"]["min"], dtype=np.float32)[:4]
    mx = np.array(st["action"]["max"], dtype=np.float32)[:4]
    return np.asarray(out.detach().cpu().float()).reshape(-1)[:4] * (mx - mn) + mn


if __name__ == "__main__":
    sys.exit(main())
