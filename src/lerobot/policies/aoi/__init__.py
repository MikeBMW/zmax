# -*- coding: utf-8 -*-
"""AOI 光学质量检测 —— 算法层 (老倪 2026-11-10 定的架构)。

老倪原话: 「def node_ss_aoi(ctx): 这个应该是 AOI 的算法，怎么能在中间件里呢?
AOI 算法，在 /home/ubuntu/zmax/src/lerobot/policies 算法路径，统一管理」

架构约定 (与 policies/yolo_3d、policies/sam3_seg 同级):
    middleware/nodes/impl/ss_aoi.py   节点**薄壳**: 取上下文 → 调这里 → 发话题/返回 dict
    policies/aoi/                     算法**真身**: 取图 / 判据 / 判决 / 话题值

依赖方向只能 policies ← middleware。
所以「缓存」和「话题发布」一律**由调用方注入**(cache / publish 参数)，
本包**不 import** lerobot.middleware —— 否则 algorithms 反过来依赖节点层，又是一团乱。

三路分工 (互不替代, 来源必须可区分):
    gold.py       金手指 10082 —— 搬运工控机 /last_result 真判决 (remote-10082)
    gold_yolo.py  金手指 10082 —— 本机 YOLO 推理 (local-yolo, 与搬运并列)
    surface.py    表面   10083 —— 本机 surface_judge 重算 (local-judge)
"""
from .gold import gold_bypass                     # noqa: F401
from .gold_yolo import gold_yolo_bypass, gold_yolo_model   # noqa: F401
from .surface import surface_bypass               # noqa: F401

__all__ = ["gold_bypass", "gold_yolo_bypass", "gold_yolo_model", "surface_bypass"]
