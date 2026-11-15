#!/usr/bin/env python3
"""把数据集 action 统计量注入 ckpt 的 config.json ⇒ action head 出口直出真机口径。

为什么需要:
  action head 的 predict_action 只有在 config.unnorm_out=True 且带 action_min/action_max 时,
  才会在 return 前做 MIN_MAX 逆变换 (t∈[-1,1] → x/y/z 绝对 mm + grip 0/70) 并 clamp 到工作空间。
  训练产出的 config.json 默认不带这三项 (draccus 从 yaml 生成, yaml 里没有), 所以要补一次。

用法:
  python tools/inject_unnorm_stats.py outputs/train/<exp>/checkpoints/last/pretrained_model
  python tools/inject_unnorm_stats.py --all outputs/train/<exp>          # 补该实验所有 ckpt
  可选第 2 位置参数指定 stats.json; 默认取 zmax_live_215ep1_128 的 stats。

注意: 用 unnorm_out=True 的 ckpt 做评估时, 下游**不能**再 post() 一次, 否则双重反归一化。
"""
from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF_STATS = os.path.join(REPO, "zmax_data", "datasets", "lerobot",
                         "zmax_live_215ep1_128", "meta", "stats.json")
THRESH = 35.0        # 真机夹爪只有 0=合 / 70=开


def inject(ckpt_dir: str, stats_path: str) -> bool:
    cfg_p = os.path.join(ckpt_dir, "config.json")
    if not os.path.exists(cfg_p):
        print("  ✗ 缺 config.json:", ckpt_dir)
        return False
    st = json.load(open(stats_path))["action"]
    mn = [round(float(v), 4) for v in st["min"]]
    mx = [round(float(v), 4) for v in st["max"]]
    d = json.load(open(cfg_p))
    d["unnorm_out"] = True
    d["action_min"], d["action_max"] = mn, mx
    d["grip_binary_thresh"] = THRESH
    json.dump(d, open(cfg_p, "w"), ensure_ascii=False, indent=2)
    print("  ✓ %s  action_dim=%s  min=%s max=%s" % (ckpt_dir, d.get("action_dim"), mn, mx))
    return True


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    all_ck = "--all" in sys.argv
    if not args:
        print(__doc__)
        return 2
    target = args[0]
    stats = args[1] if len(args) > 1 else DEF_STATS
    if not os.path.exists(stats):
        print("✗ stats 不存在:", stats)
        return 2
    dirs: list[str] = []
    if all_ck:
        ckroot = os.path.join(target, "checkpoints")
        for name in sorted(os.listdir(ckroot)) if os.path.isdir(ckroot) else []:
            p = os.path.join(ckroot, name, "pretrained_model")
            if os.path.isdir(p):
                dirs.append(p)
    elif os.path.isdir(os.path.join(target, "pretrained_model")):
        dirs.append(os.path.join(target, "pretrained_model"))
    else:
        dirs.append(target)
    ok = sum(inject(d, stats) for d in dirs)
    print("\n%d/%d 个 ckpt 已注入 unnorm 口径" % (ok, len(dirs)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
