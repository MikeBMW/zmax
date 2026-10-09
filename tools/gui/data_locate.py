#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data/ 分区定位器 (2026-10-09 老倪: 「继续整合所有数据文件, 现在的数据太杂乱了」)

data/ 顶层只留 6 个桶:
    database/  <产品>/ = 该产品的工程文件 + 数据库 (.proj / .db / archive + param_events 表)
    skills/    技能库 (L2 原子技能注册表 / 示教点 / 肌肉记忆)
    scene/     场景 · 叠加 · 感知 (overlay_spec / cam_calib / traj_display / scene_state.json)
    memory/    记忆层 (memory_layers / shared / macro / assembly / muscle / intact)
    calib/     标定 (handeye / selfcal / aoi_caliber_bench)
    datasets/  数据集 (yolo_* / ss_* / metaworld_* / smolvla_* / orin_* / *.npz / *.mp4)

凡**按名字动态拼路径**的地方 (枚举/候选表) 一律走这里, 别写死 "data", name ——
分区以后写死的会静默找不到 (目录不存在 = isdir False, 不报错)。
"""
import os

BUCKETS = ("datasets", "memory", "calib", "scene", "skills", "database")


def data_dir(root, name):
    """data/<name> 的真实位置: 新分区优先, 找不到回退旧顶层 (兼容老盘/老工程)。"""
    for b in BUCKETS:
        p = os.path.join(root, "data", b, name)
        if os.path.exists(p):
            return p
    return os.path.join(root, "data", name)


def datasets_root(root):
    """数据集枚举根: data/datasets (分区后); 没有就回退 data/ (老盘)。"""
    p = os.path.join(root, "data", "datasets")
    return p if os.path.isdir(p) else os.path.join(root, "data")


def iter_datasets(root):
    """列出数据集目录名 (按 datasets_root 枚举)。"""
    r = datasets_root(root)
    if not os.path.isdir(r):
        return []
    return [n for n in sorted(os.listdir(r)) if os.path.isdir(os.path.join(r, n))]
