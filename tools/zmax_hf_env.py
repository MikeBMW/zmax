#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HF 缓存环境唯一依据 — 训练入口**只许从这里取**, 不许各写一份。

为什么独立成模块 (2026-10-14 实测事故):
  `run_full_drill.py` 与 `tools/gui/model_engine_window.py` 各自写了
  `HF_HOME = os.path.expanduser("~/zmax_data/hf_cache")` —— 展开成 /home/ubuntu/zmax_data/hf_cache,
  **少了 /zmax/ 一段, 该目录根本不存在**。joint_train_all 拿到坏 HF_HOME 后 HF_HUB_CACHE 不存在,
  于是它主动放弃 HF_ENV ⇒ transformers 不带 offline 去连 huggingface.co ⇒ **L3(SmolVLA) 直接 rc=1**
  ("We couldn't connect to 'https://huggingface.co' … couldn't find them in the cached files"),
  而 L2/L4 因为不碰 HF 缓存"看起来正常"，故障被掩盖成"L3 就是不行"。

唯一依据口径 (与 tools/joint_train_all.py HF_HOME、tools/zmax_bootstrap.py ZMAX_HF_HOME 一致):
  工程根下的 zmax_data/hf_cache   (hub/ 里是真模型, SmolVLM2 基座在
  models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/snapshots/<rev>/)
"""
import os

ROOT = os.environ.get("ZMAX_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HOME = os.path.join(os.environ.get("ZMAX_DATA", os.path.join(ROOT, "zmax_data")), "hf_cache")


def hf_home():
    """HF 家 = env ZMAX_HF_HOME / HF_HOME (仅当它真有 hub/ 子目录) / 工程根 zmax_data/hf_cache。"""
    for c in (os.environ.get("ZMAX_HF_HOME"), os.environ.get("HF_HOME"), DEFAULT_HOME):
        if c and os.path.isdir(os.path.join(c, "hub")):
            return c
    return DEFAULT_HOME


def hf_env(base=None, offline=True):
    """跑训练/加载模型时该用的完整环境 (继承当前 environ + HF 三项)。"""
    home = hf_home()
    e = dict(os.environ if base is None else base)
    e.update({"HF_HOME": home, "HF_HUB_CACHE": os.path.join(home, "hub")})
    if offline:
        e["HF_HUB_OFFLINE"] = "1"          # 有本地缓存就别去连网 (连不上就是 rc=1 假故障)
    return e


def describe():
    """自检/取证用: 一行说明 + hub 是否存在。"""
    h = hf_home()
    return {"HF_HOME": h, "HF_HUB_CACHE": os.path.join(h, "hub"),
            "hub_ok": os.path.isdir(os.path.join(h, "hub"))}


if __name__ == "__main__":
    import json
    print(json.dumps(describe(), ensure_ascii=False, indent=2))
