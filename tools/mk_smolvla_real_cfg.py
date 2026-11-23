#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mk_smolvla_real_cfg.py —— 用**真机录制数据集**生成 SmolVLA+LEW 训练配置（管线验证用）

为什么单独一个脚本: 现有 `mk_smolvla_sim_cfg.py` 里写死仿真集口径
(observation.image 3x480x480 + state 39 维 + 单集 metaworld)。真机数据是
state 13 维 (j1..j6 rad + xyz mm + 四元数)，夹爪在 action 第 3 维 ⇒ 必须改四处:
  ① input_features.observation.state.shape = [13] · state_dim = 13
  ② gripper_dim = 3 (真机 action = [x,y,z,grip]，不是仿真 8 维的 6)
  ③ dataset.repo_id / root 指向真机集
  ④ num_video_frames / n_obs_steps 必须与起点 ckpt 的 pos_embedding 对齐 (7)

用法:
  ./gui-venv311/bin/python tools/mk_smolvla_real_cfg.py \
      --dataset zmax_data/datasets/lerobot/live_1123_004601_svla \
      --out configs/generated_train_configs/config_smolvla_real_smoke.yaml \
      --outdir outputs/train/smolvla_real_smoke --steps 60 --batch 2
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = os.path.join(ROOT, "configs/generated_train_configs/config_smolvla_lew_lora_200_200.yaml")


def pick_base_ckpt(n_obs=7):
    """取 n_obs_steps 与本次配置一致的最近 ckpt（否则 pos_embedding 形状不符）。"""
    best = None
    for c in glob.glob(os.path.join(ROOT, "outputs/train/smolvla_lew*/checkpoints/*/pretrained_model/train_config.json")):
        try:
            pol = json.load(open(c)).get("policy", {})
            if int(pol.get("n_obs_steps") or 0) == n_obs:
                d = os.path.dirname(os.path.dirname(c))
                if best is None or os.path.getmtime(c) > os.path.getmtime(best[0]):
                    best = (c, d)
        except Exception:                                                # noqa: BLE001
            continue
    return best[1] if best else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="数据集目录（相对 ROOT 或绝对）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--outdir", required=True, help="输出目录（相对 ROOT）")
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--num-workers", type=int, default=4)
    ap.add_argument("--n-obs", type=int, default=7)
    ap.add_argument("--pretrained", default="", help="留空=自动取同 n_obs 的最近 ckpt")
    ap.add_argument("--image-key", default="", help="留空=自动挑数据集里第一个图像键")
    a = ap.parse_args()

    ds = a.dataset if os.path.isabs(a.dataset) else os.path.join(ROOT, a.dataset)
    info = json.load(open(os.path.join(ds, "meta/info.json"), encoding="utf-8"))
    feats = info["features"]
    state_shape = feats["observation.state"]["shape"][0]
    act_shape = feats["action"]["shape"][0]
    img_keys = [k for k, v in feats.items() if v.get("dtype") == "image"]
    if not img_keys:
        print("❌ 数据集没有图像特征")
        return 2
    img_key = a.image_key or img_keys[0]
    ih, iw = feats[img_key]["shape"][0], feats[img_key]["shape"][1]

    pre = a.pretrained or pick_base_ckpt(a.n_obs)
    if not pre:
        print("❌ 找不到 n_obs=%d 的起点 ckpt（会与 pos_embedding 形状不符）" % a.n_obs)
        return 2
    if not pre.endswith("pretrained_model"):
        pre = os.path.join(pre, "pretrained_model")

    cfg = yaml.safe_load(open(BASE, encoding="utf-8"))
    rel_ds = os.path.relpath(ds, ROOT)
    cfg["dataset"]["repo_id"] = rel_ds
    cfg["dataset"]["root"] = rel_ds
    cfg["dataset"]["episodes"] = None
    # 图像键 → 策略要的单路键
    cfg["rename_map"] = {} if img_key == "observation.image" else {img_key: "observation.image"}
    pol = cfg["policy"]
    pol["input_features"] = {"observation.image": {"type": "VISUAL", "shape": [3, ih, iw]},
                             "observation.state": {"type": "STATE", "shape": [state_shape]}}
    pol["state_dim"] = state_shape
    pol["action_dim"] = act_shape
    pol["output_features"] = {"action": {"type": "ACTION", "shape": [act_shape]}}
    pol["gripper_dim"] = act_shape - 1     # 真机 action 末维 = 夹爪
    pol["pretrained_path"] = pre
    pol["n_obs_steps"] = a.n_obs
    pol["num_video_frames"] = a.n_obs
    pol["chunk_size"] = a.n_obs
    pol["n_action_steps"] = a.n_obs
    cfg["output_dir"] = a.outdir
    cfg["job_name"] = os.path.basename(a.outdir)
    cfg["steps"] = a.steps
    cfg["batch_size"] = a.batch
    cfg["num_workers"] = a.num_workers
    cfg["save_freq"] = max(a.steps, 1)
    cfg["log_freq"] = 5
    cfg["eval_freq"] = -1
    cfg["peft"] = None
    os.makedirs(os.path.dirname(os.path.join(ROOT, a.out)), exist_ok=True)
    with open(os.path.join(ROOT, a.out), "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

    print(json.dumps({"cfg": a.out, "dataset": rel_ds, "frames": info.get("total_frames"),
                      "fps": info.get("fps"), "state_dim": state_shape, "action_dim": act_shape,
                      "gripper_dim": pol["gripper_dim"], "image": [img_key, ih, iw],
                      "n_obs": a.n_obs, "pretrained": os.path.relpath(pre, ROOT),
                      "steps": a.steps, "batch": a.batch}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
