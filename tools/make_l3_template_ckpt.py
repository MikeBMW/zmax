"""造一个 7 维 L3 模板 ckpt —— 让断点立刻能调, 不必等训练。

口径与训练/部署完全一致 (7 维真机 action, 位姿逐点取 215 点真值表):
    action = [x, y, z(mm), a, b, c(deg), grip(0/70)]
    unnorm_out=True ⇒ head 的 predict_action 出口直接是这 7 个量的 10 步 chunk

差别只有一个: DiT/action head 是**随机初始化**的 (VLM 主干从本地 HF 缓存加载真权重),
所以数值不准 —— 用来验证形状/量纲/断点, 不用于判断策略水平。

用法: python tools/make_l3_template_ckpt.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

REPO = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(REPO, "src"))

# 7 维真实口径 (取自 zmax_live_215ep1_7d_128/meta/stats.json)
MN = [211.187, -511.462, 114.904, -177.840, -88.915, -178.982, 0.0]
MX = [817.839, 410.839, 998.601, 176.284, 86.012, 178.463, 70.0]
NAMES = ["x", "y", "z", "a", "b", "c", "grip"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "outputs/train/smolvla_live1115_7d_v1/checkpoints/last/pretrained_model"))
    ap.add_argument("--donor", default=os.path.join(
        REPO, "outputs/train/smolvla_live1115_v1/checkpoints/last/pretrained_model"),
        help="从这里借 preprocessor.json / postprocessor.json (state 13 维口径一致)")
    a = ap.parse_args()

    import torch
    from lerobot.policies.smolvla_lew.configuration_smolvla_lew import SmolVLALewConfig
    from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy

    from lerobot.configs.types import FeatureType, PolicyFeature

    cfg = SmolVLALewConfig(
        action_dim=len(NAMES), state_dim=13, chunk_size=10, n_action_steps=5,
        num_inference_timesteps=4, action_model_type="DiT-B",
        action_hidden_size=256, action_num_layers=2,
        siglip_image_size=128, num_vision_tokens=64, resize_images_to=(128, 128),
        smolvlm_name="HuggingFaceTB/SmolVLM2-500M-Video-Instruct", freeze_smolvlm=True,
        unnorm_out=True, action_min=MN, action_max=MX,
        grip_binary_thresh=35.0, grip_index=6,
        # validate_features() 要求至少一个视觉输入 ⇒ 与真实数据集同构 (必须是 PolicyFeature)
        input_features={
            "observation.images.top": PolicyFeature(type=FeatureType.VISUAL, shape=(3, 128, 128)),
            "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(13,)),
        },
        output_features={"action": PolicyFeature(type=FeatureType.ACTION, shape=(len(NAMES),))},
    )
    print("[tpl] 构造 7 维 policy (VLM 从本地缓存, head 随机初始化) …", flush=True)
    pol = SmolVLALewPolicy(cfg)
    pol.eval()

    os.makedirs(a.out, exist_ok=True)
    print("[tpl] save_pretrained → %s" % a.out, flush=True)
    pol.save_pretrained(a.out)

    # processor 文件: state 是 13 维 MEAN_STD, 与 4 维 donor 完全一致 ⇒ 直接借
    for f in ("preprocessor.json", "postprocessor.json", "train_config.json"):
        s = os.path.join(a.donor, f)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(a.out, f))
            print("  borrowed %s" % f, flush=True)

    # 复核: 写进去的 config 必须是 7 维口径
    c = json.load(open(os.path.join(a.out, "config.json")))
    ok = (int(c.get("action_dim", 0)) == 7 and int(c.get("state_dim", 0)) == 13
          and c.get("unnorm_out") is True and int(c.get("grip_index", -1)) == 6
          and len(c.get("action_min") or []) == 7 and len(c.get("action_max") or []) == 7
          and os.path.isfile(os.path.join(a.out, "model.safetensors")))
    print("\n[tpl] config: action_dim=%s state_dim=%s unnorm_out=%s grip_index=%s min/max=%d/%d"
          % (c.get("action_dim"), c.get("state_dim"), c.get("unnorm_out"), c.get("grip_index"),
             len(c.get("action_min") or []), len(c.get("action_max") or [])))
    print("[tpl] model.safetensors: %.0f MB"
          % (os.path.getsize(os.path.join(a.out, "model.safetensors")) / 1e6))
    print("[tpl] 判定:", "PASS —— 可以 reload 调试 (数值为随机权重)" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
