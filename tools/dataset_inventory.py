#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataset_inventory.py — Z-MAX 只读「数据资产清单」工具
=====================================================

为什么有这个脚本
----------------
本机的数据散落在三大块:  (1) 从 Hub 下载的数据/权重、(2) 采集与训练/评测生成的产物、
(3) 3DGS 建图/重建资产。以往要看"到底有哪些、多大、多新"得人工层层 ls + du，
既慢又容易漏。这个脚本把**真实存在的**数据一次性扫成结构化 JSON + 人读表格,
供 GUI/看板只读消费, 不写任何业务文件、不动在役链路。

设计红线 (为什么这么写)
----------------------
* **只读**: 所有文件访问都是 os.scandir/stat/os.path.exists, 绝不 open(写)/绝不删除/绝不联网。
* **实测目录**: 扫描根全部是脚本运行前用 ls 真实确认过的路径(见 ROOTS_* 常量),
  不靠猜; 路径不存在就记进 errors 并跳过, 不静默当有。
* **数字来自真实扫盘**: 大小/文件数/最新 mtime 一律现场 stat 累计, 不写死。
* **性能**: 只扫定点目录(不递归全仓/不动 ~/zmax_data 根, 那里几十 GB+上万文件);
  递归限深、跳过 .git/node_modules/__pycache__/备份 zip 等无关重目录;
  大目录只 os.scandir 只统计文件名+size+mtime, 不读内容(实测单次 < 30s)。
* **大文件不进 JSON**: 视频/权重只给 路径 + 大小 + mtime, 绝不把二进制塞进结构体。

类别口径 (机器校验要求 category ∈ downloaded/generated/map)
--------------------------------------------------------
* downloaded : 外部下载物 —— HF hub 缓存、HF datasets 缓存、下载的模型权重快照。
* generated  : 本机采集/训练/评测产物 —— 数据集、训练 run、YOLO 训练输出、
               世界模型 checkpoint、LoRA 适配器、评测报告(reports/*.json 汇总)。
* map        : 建图/重建资产 —— 3DGS(gaussian splatting) 资产、原始扫场会话、
               建图状态、场景注册表(data/scene)。

用法
----
  python3 tools/dataset_inventory.py                  # 人读表(按类别分组, 末尾总计)
  python3 tools/dataset_inventory.py --json           # 结构化 JSON 到 stdout(GUI 读)
  python3 tools/dataset_inventory.py --json-out p.json # 同时落一份 JSON 文件
  python3 tools/dataset_inventory.py --root /path      # 指定仓库根(默认自动定位)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

# --------------------------------------------------------------------------- #
# 常量: 扫描根与跳过规则 (全部为运行前 ls 实测确认过的真实路径)
# --------------------------------------------------------------------------- #

# 仓库根: 本脚本位于 <repo>/tools/ 下, 默认取上两级, 可用 --root 覆盖。
_DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 递归时要跳过的目录名 (无关/巨大/易循环): 版本库、依赖、缓存、锁。
SKIP_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".locks", ".cache", "xet",   # xet 是 HF 传输分块缓存, 与"数据资产"无关
}

# 递归时要跳过的文件后缀 (备份包/压缩包/临时), 避免把几十 GB 归档算进来。
SKIP_FILE_SUFFIXES = (
    ".zip", ".tar", ".tar.gz", ".tgz", ".zst", ".lz4", ".bak",
    ".lock", ".tmp", ".swp",
)

# 递归默认最大深度 (相对每个记录根而言)。数据集的 images/ 等都在浅层,
# 深于 6 层基本是嵌套日志, 限深同时控时。
DEFAULT_MAX_DEPTH = 6

# 我们关心的扩展名 (用于在记录里给出 parquet/video/jsonl 等的计数)。
INTERESTING_EXTS = (
    ".parquet", ".jsonl", ".json", ".mp4", ".avi", ".mov", ".mkv",
    ".npz", ".npy", ".jpg", ".jpeg", ".png", ".txt", ".csv", ".h5", ".hdf5",
    ".ply", ".splat", ".pcd", ".pt", ".pth", ".safetensors", ".bin",
)

# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #

def human_size(n: int) -> str:
    """字节数 → 人类可读 (1024 进制)。为什么自己写: 不引入外部依赖, 口径统一。"""
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if f < 1024.0:
            return f"{f:.1f}{unit}" if unit != "B" else f"{int(f)}B"
        f /= 1024.0
    return f"{f:.1f}EB"


def fmt_mtime(ts: float) -> str:
    """时间戳 → 本地 'YYYY-MM-DD HH:MM:SS'。ts<=0 表示没有文件。"""
    if not ts or ts <= 0:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def scan_tree(path: str, max_depth: int = DEFAULT_MAX_DEPTH) -> dict:
    """
    只读递归统计一棵目录树: 总字节 / 文件数 / 最新 mtime / 关心扩展名计数。

    为什么用 os.scandir + 显式栈而不是 os.walk:
    - scandir 的 entry.stat() 在本机文件系统上命中 dentry 缓存, 比 walk 再 stat 快;
    - 显式栈能精确控深, 且能在发现符号链接目录时**不跟进去**(防环 + 防重复计数);
    - 全程只读 stat, 不 open 任何文件内容。
    """
    total_bytes = 0
    file_count = 0
    dir_count = 0
    latest = 0.0
    ext_counts: dict[str, int] = {}

    if not os.path.exists(path):
        return {"size_bytes": 0, "file_count": 0, "dir_count": 0,
                "latest_mtime": 0.0, "ext_counts": {}}

    # 若是单文件 (如 .npz), 直接统计后返回。
    if os.path.isfile(path) and not os.path.isdir(path):
        st = os.stat(path)
        ext = os.path.splitext(path)[1].lower()
        ext_counts[ext] = 1
        return {"size_bytes": st.st_size, "file_count": 1, "dir_count": 0,
                "latest_mtime": st.st_mtime, "ext_counts": ext_counts}

    stack = [(path, 0)]
    while stack:
        cur, depth = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        # 目录符号链接不跟进去: 防环 + 防跨根重复计数。
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in SKIP_DIR_NAMES:
                                continue
                            dir_count += 1
                            if depth + 1 < max_depth:
                                stack.append((entry.path, depth + 1))
                            continue
                        if entry.is_file(follow_symlinks=False):
                            if entry.name.endswith(SKIP_FILE_SUFFIXES):
                                continue
                            st = entry.stat(follow_symlinks=False)
                            total_bytes += st.st_size
                            file_count += 1
                            if st.st_mtime > latest:
                                latest = st.st_mtime
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in INTERESTING_EXTS:
                                ext_counts[ext] = ext_counts.get(ext, 0) + 1
                    except OSError:
                        # 单个 entry 权限/断裂链接等: 跳过, 不中断整棵扫描。
                        continue
        except OSError:
            continue

    return {"size_bytes": total_bytes, "file_count": file_count,
            "dir_count": dir_count, "latest_mtime": latest,
            "ext_counts": ext_counts}


def make_record(category: str, name: str, path: str, kind: str, source: str,
                *, reuse: dict | None = None, extra: dict | None = None,
                max_depth: int = DEFAULT_MAX_DEPTH, follow: bool = False) -> dict:
    """
    组装一条清单记录。follow=True 时按 realpath 扫描(用于 data/datasets 下的符号链接),
    但记录里同时保留 path(原样) 与 real_path(解析后), 便于追溯来源。
    """
    path = os.path.abspath(path)
    real = os.path.realpath(path) if follow else path
    is_link = os.path.islink(path)

    stats = reuse if reuse is not None else scan_tree(real, max_depth)

    rec = {
        "category": category,           # downloaded / generated / map
        "kind": kind,                   # 细粒度类型(给 GUI 过滤)
        "name": name,
        "path": path,                   # 绝对路径(原样, 可能是符号链接)
        "real_path": real,              # 解析后真实路径
        "is_symlink": is_link,
        "size_bytes": stats["size_bytes"],
        "size_human": human_size(stats["size_bytes"]),
        "file_count": stats["file_count"],
        "dir_count": stats["dir_count"],
        "latest_mtime": stats["latest_mtime"],
        "latest_mtime_str": fmt_mtime(stats["latest_mtime"]),
        "source": source,               # 来源线索: HF repo 名 / 生成脚本名 / 采集来源
    }
    if extra:
        rec.update(extra)
    # 只把"关心扩展名"里非零的计数带上, 让 JSON 紧凑。
    ec = {k: v for k, v in stats.get("ext_counts", {}).items() if v}
    if ec:
        rec["ext_counts"] = ec
    return rec


def list_children(root: str) -> list[str]:
    """只读列出一级子项(文件+目录)绝对路径; 不存在返回 []。"""
    if not os.path.isdir(root):
        return []
    out = []
    try:
        with os.scandir(root) as it:
            for e in it:
                out.append(e.path)
    except OSError:
        return []
    return sorted(out)


# --------------------------------------------------------------------------- #
# 来源线索 (为什么需要: 让人/机一眼看出"这是什么产出的")
# --------------------------------------------------------------------------- #

def hf_repo_name(dirname: str) -> str:
    """HF hub 目录名 'models--Qwen--Qwen2.5-VL-3B-Instruct' → 'Qwen/Qwen2.5-VL-3B-Instruct'。"""
    parts = dirname.split("--")
    if len(parts) >= 3:
        return "/".join(parts[1:])
    return dirname


def gs_source_clue(name: str, has_ply: bool, has_splat: bool) -> str:
    """给 3DGS 资产一个来源线索(基于目录命名 + 产物文件), 不臆测。"""
    low = name.lower()
    if "colmap" in low:
        base = "COLMAP/SfM 重建"
    elif "merge" in low or "merged" in low:
        base = "多会话合并(gs_dataset_merge)"
    elif "scene" in low:
        base = "场景重建(gs_map_run/gs_train)"
    elif "map_sess" in low or "scan" in low or "traj" in low:
        base = "扫场会话(gs_capture 采集)"
    elif "inc" in low:
        base = "增量续训(gs_train --init-ply)"
    elif "blk" in low:
        base = "分块重建测试(blk*)"
    else:
        base = "3DGS 重建产物"
    tags = []
    if has_ply:
        tags.append("gs.ply")
    if has_splat:
        tags.append("gs.splat")
    if tags:
        base += " [+" + "/".join(tags) + "]"
    return base


def train_source_clue(name: str) -> str:
    """训练 run 目录 → 来源线索。"""
    low = name.lower()
    if "smolvla" in low and "lora" in low:
        return "SmolVLA LoRA 微调(outputs/train)"
    if "smolvla" in low:
        return "SmolVLA 训练(outputs/train)"
    if "state_space" in low:
        return "状态空间模型训练(outputs/train)"
    return "训练 run(outputs/train)"


def dataset_source_clue(name: str, is_link: bool, real: str) -> str:
    """数据集来源线索。"""
    if is_link and "lerobot-smolvla-lew/data" in real:
        return "lerobot 数据(符号链接 → external/lerobot-smolvla-lew/data)"
    if name.startswith("yolo"):
        return "YOLO 标注数据集(本机采集)"
    if name.startswith("l5_vlm"):
        return "L5 VLM SFT 数据集(本机采集)"
    if name.startswith("sam3"):
        return "SAM3 微调缓存(本机采集)"
    return "数据集(本机采集/整理)"


# --------------------------------------------------------------------------- #
# 各类别扫描
# --------------------------------------------------------------------------- #

def scan_downloaded(root: str) -> tuple[list[dict], list[str]]:
    """扫'已下载数据': HF hub 缓存 / HF datasets 缓存 / 下载的权重快照。"""
    items: list[dict] = []
    errors: list[str] = []

    # 1) HF hub 缓存: 每个 repo 目录一条记录 (models--* / datasets--*)。
    for hub_dir in ("zmax_data/hf_cache/hub", "zmax_data/hf_home/hub"):
        hub = os.path.join(root, hub_dir)
        if not os.path.isdir(hub):
            errors.append(f"missing hf hub: {hub_dir}")
            continue
        for child in list_children(hub):
            if not os.path.isdir(child):
                continue
            dn = os.path.basename(child)
            if not (dn.startswith("models--") or dn.startswith("datasets--")):
                continue
            repo = hf_repo_name(dn)
            kind = "hf_hub_model" if dn.startswith("models--") else "hf_hub_dataset"
            items.append(make_record(
                "downloaded", repo, child,
                kind, f"HF Hub: {repo}",
                extra={"hub_root": hub_dir},
            ))

    # 2) HF datasets parquet 缓存 (datasets library 落盘)。
    ds_cache = os.path.join(root, "zmax_data/hf_cache/datasets")
    if os.path.isdir(ds_cache):
        items.append(make_record(
            "downloaded", "hf_cache/datasets", ds_cache,
            "hf_datasets_cache", "HF datasets 库 parquet 缓存",
            extra={"hub_root": "zmax_data/hf_cache/datasets"},
        ))
    else:
        errors.append("missing hf datasets cache: zmax_data/hf_cache/datasets")

    # 3) 下载的模型权重快照 (SAM3 官重 + weights 目录), 都是外部下载物。
    for rel, name in (("zmax_data/models/sam3_hf", "sam3_hf"),
                      ("zmax_data/models/weights", "weights")):
        p = os.path.join(root, rel)
        if os.path.isdir(p):
            items.append(make_record(
                "downloaded", name, p, "hf_model_snapshot",
                "下载的模型权重快照(HF/official)",
            ))
    return items, errors


def scan_datasets(root: str, max_depth: int) -> list[dict]:
    """扫 data/datasets/*: 本机数据集 (符号链接按 realpath 统计, 记录原路径与来源)。"""
    items: list[dict] = []
    base = os.path.join(root, "data/datasets")
    for child in list_children(base):
        name = os.path.basename(child)
        is_link = os.path.islink(child)
        real = os.path.realpath(child)
        # 符号链接可能指向不存在的目标 → 记 0 但仍列出(如实)。
        items.append(make_record(
            "generated", name, child, "dataset",
            dataset_source_clue(name, is_link, real),
            follow=is_link, max_depth=max_depth,
        ))
    return items


def scan_train_outputs(root: str, max_depth: int) -> list[dict]:
    """扫训练产物: outputs/train/*, YOLO 训练输出, 世界模型 ckpt, 模型工件。"""
    items: list[dict] = []

    # 1) SmolVLA/LoRA 与状态空间训练 run。
    train_dir = os.path.join(root, "outputs/train")
    for child in list_children(train_dir):
        if not os.path.isdir(child):
            continue
        name = os.path.basename(child)
        items.append(make_record(
            "generated", name, child, "train_run",
            train_source_clue(name), max_depth=max_depth,
        ))

    # 2) ultralytics/lerobot YOLO 训练输出 (按数据集分组)。
    yolo_dir = os.path.join(root, "external/lerobot-smolvla-lew/runs/detect/outputs")
    for child in list_children(yolo_dir):
        if not os.path.isdir(child):
            continue
        name = os.path.basename(child)
        items.append(make_record(
            "generated", f"yolo/{name}", child, "yolo_train_output",
            f"YOLO 训练输出(runs/detect/outputs/{name})", max_depth=max_depth,
        ))

    # 3) 世界模型 (stable-wm) checkpoint 集合: 逐个 ckpt 一条, 便于看最新。
    ckpt_dir = os.path.join(root, "zmax_data/stable-wm-cache/checkpoints")
    for child in list_children(ckpt_dir):
        # checkpoints 下同时有文件(.txt 结果)和目录(.ckpt); 只列目录型 ckpt。
        if not os.path.isdir(child):
            continue
        name = os.path.basename(child)
        items.append(make_record(
            "generated", name, child, "wm_checkpoint",
            "稳定世界模型 checkpoint(zmax_data/stable-wm-cache/checkpoints)",
            max_depth=max_depth,
        ))

    # 4) zmax_data/models/* 其余工件 (LoRA 适配器/合并模型等); 已归 downloaded 的跳过。
    models_dir = os.path.join(root, "zmax_data/models")
    for child in list_children(models_dir):
        name = os.path.basename(child)
        if name in ("sam3_hf", "weights"):
            continue  # 已作 downloaded 权重快照
        if os.path.isdir(child):
            items.append(make_record(
                "generated", name, child, "model_artifact",
                "模型工件(LoRA/合并模型等)", max_depth=max_depth,
            ))
    return items


def scan_reports(root: str) -> dict:
    """
    评测/报告: reports/*.json 数量多(数百), 不做逐条记录, 而是按"类型"汇总 +
    给最新几条。类型 = 文件名去掉末尾时间戳/序号后的前缀。
    """
    base = os.path.join(root, "reports")
    summary = {"dir": base, "total_files": 0, "total_bytes": 0,
               "types": {}, "latest": []}
    if not os.path.isdir(base):
        return summary
    rows = []
    for child in list_children(base):
        if not os.path.isfile(child) or not child.endswith(".json"):
            continue
        try:
            st = os.stat(child)
        except OSError:
            continue
        name = os.path.basename(child)
        # 归一化类型: 去掉 .json, 再去掉末尾的 _YYYYMMDD... 或 _数字串。
        stem = name[:-5]
        typ = re.sub(r"[_-]\d{4,}.*$", "", stem)
        typ = re.sub(r"[_-]\d+$", "", typ) or stem
        rows.append((child, name, typ, st.st_size, st.st_mtime, st.st_mtime))
    summary["total_files"] = len(rows)
    summary["total_bytes"] = sum(r[3] for r in rows)
    for _, _, typ, size, _, _ in rows:
        t = summary["types"].setdefault(typ, {"count": 0, "bytes": 0})
        t["count"] += 1
        t["bytes"] += size
    # 最新的 5 条(按 mtime 降序)。
    rows.sort(key=lambda r: r[4], reverse=True)
    summary["latest"] = [
        {"name": n, "type": typ, "size_bytes": s, "mtime": fmt_mtime(m),
         "path": p}
        for (p, n, typ, s, m, _) in rows[:5]
    ]
    return summary


def scan_map(root: str, max_depth: int) -> tuple[list[dict], list[str]]:
    """扫'建图/重建数据'(重点): 3DGS 资产、原始扫场会话、建图状态、场景注册表。"""
    items: list[dict] = []
    errors: list[str] = []

    # 1) 3DGS 资产根: 每个子目录一条, 并探测是否含 gs.ply/gs.splat 真产物。
    assets = os.path.join(root, "zmax_data/gs_assets")
    if os.path.isdir(assets):
        for child in list_children(assets):
            if not os.path.isdir(child):
                continue
            name = os.path.basename(child)
            has_ply = os.path.exists(os.path.join(child, "gs.ply"))
            has_splat = os.path.exists(os.path.join(child, "gs.splat"))
            has_cams = os.path.exists(os.path.join(child, "cameras.json"))
            items.append(make_record(
                "map", name, child, "3dgs_asset",
                gs_source_clue(name, has_ply, has_splat),
                max_depth=max_depth,
                extra={"has_gs_ply": has_ply, "has_gs_splat": has_splat,
                       "has_cameras_json": has_cams},
            ))
    else:
        errors.append("missing 3dgs assets: zmax_data/gs_assets")

    # 2) 原始扫场采集会话 (大量 jpg 帧 + frames.jsonl + session_meta.json)。
    scan = os.path.join(root, "zmax_data/gs_scan")
    if os.path.isdir(scan):
        for child in list_children(scan):
            if not os.path.isdir(child):
                continue
            name = os.path.basename(child)
            items.append(make_record(
                "map", name, child, "capture_session",
                "原始扫场会话(gs_capture.py: frames/*.jpg)", max_depth=max_depth,
            ))
    else:
        errors.append("missing gs_scan: zmax_data/gs_scan")

    # 3) 建图状态/日志目录。
    status_dir = os.path.join(root, "zmax_data/gs_map")
    if os.path.isdir(status_dir):
        items.append(make_record(
            "map", "gs_map", status_dir, "map_status",
            "建图状态(status.json/run.log)", max_depth=max_depth,
        ))

    # 4) 场景注册表 (data/scene): 3D 对象/叠加规格, 属场景重建相关。
    scene_dir = os.path.join(root, "data/scene")
    if os.path.isdir(scene_dir):
        items.append(make_record(
            "map", "data/scene", scene_dir, "scene_registry",
            "场景注册表(objects3d/overlay_spec/相机标定)", max_depth=max_depth,
        ))
    return items, errors


# --------------------------------------------------------------------------- #
# 汇总 / 输出
# --------------------------------------------------------------------------- #

def build_inventory(root: str, max_depth: int) -> dict:
    """跑全部扫描, 组装最终结构体。"""
    now = datetime.now(timezone(timedelta(hours=8)))  # 本机为 CST(UTC+8)
    generated_at = now.isoformat(timespec="seconds")

    items: list[dict] = []
    errors: list[str] = []

    dl, e = scan_downloaded(root)
    items += dl
    errors += e
    items += scan_datasets(root, max_depth)
    items += scan_train_outputs(root, max_depth)
    m, e = scan_map(root, max_depth)
    items += m
    errors += e

    reports = scan_reports(root)

    # 按类别汇总。
    cats = {"downloaded": {"count": 0, "size_bytes": 0, "file_count": 0},
            "generated": {"count": 0, "size_bytes": 0, "file_count": 0},
            "map": {"count": 0, "size_bytes": 0, "file_count": 0}}
    for it in items:
        c = cats.setdefault(it["category"],
                            {"count": 0, "size_bytes": 0, "file_count": 0})
        c["count"] += 1
        c["size_bytes"] += it["size_bytes"]
        c["file_count"] += it["file_count"]

    total_bytes = sum(it["size_bytes"] for it in items)
    total_files = sum(it["file_count"] for it in items)

    # 建图重点摘要。
    map_items = [it for it in items if it["category"] == "map"]
    map_with_ply = [it for it in map_items if it.get("has_gs_ply")]

    return {
        "tool": "dataset_inventory.py",
        "schema_version": 1,
        "generated_at": generated_at,          # 必需: 时间戳(与 GPU 状态无关)
        "root": root,
        "max_depth": max_depth,
        "modules": {
            "downloaded": "HF hub 缓存 + HF datasets 缓存 + 下载的模型权重快照",
            "generated": "本机数据集 + 训练 run + YOLO 输出 + 世界模型 ckpt + 模型工件",
            "map": "3DGS 资产 + 原始扫场会话 + 建图状态 + 场景注册表",
        },
        "totals": {
            "items": len(items),
            "size_bytes": total_bytes,
            "size_human": human_size(total_bytes),
            "file_count": total_files,
        },
        "categories": {
            k: {
                "count": v["count"],
                "size_bytes": v["size_bytes"],
                "size_human": human_size(v["size_bytes"]),
                "file_count": v["file_count"],
            } for k, v in cats.items()
        },
        "map_summary": {
            "total_items": len(map_items),
            "items_with_gs_ply": len(map_with_ply),
            "asset_dirs": [it["path"] for it in map_with_ply],
            "size_bytes": sum(it["size_bytes"] for it in map_items),
            "size_human": human_size(sum(it["size_bytes"] for it in map_items)),
        },
        "reports_summary": {
            "dir": reports["dir"],
            "total_files": reports["total_files"],
            "total_bytes": reports["total_bytes"],
            "total_human": human_size(reports["total_bytes"]),
            "types": dict(sorted(reports["types"].items(),
                                 key=lambda kv: -kv[1]["count"])),
            "latest": reports["latest"],
        },
        "items": items,
        "errors": errors,
    }


def print_human(inv: dict) -> None:
    """人读表: 按类别分组, 每类别内按大小降序, 末尾给总计。"""
    cats_cn = {"downloaded": "已下载数据 (downloaded)",
               "generated": "已生成数据·训练/评测产物 (generated)",
               "map": "建图/重建数据 (map)"}
    order = ["downloaded", "generated", "map"]

    print("=" * 100)
    print(f"Z-MAX 数据资产清单 | generated_at: {inv['generated_at']}")
    print(f"扫描根: {inv['root']}   限深: {inv['max_depth']}   条目: {inv['totals']['items']}")
    print("=" * 100)

    for cat in order:
        rows = [it for it in inv["items"] if it["category"] == cat]
        if not rows:
            continue
        rows.sort(key=lambda r: r["size_bytes"], reverse=True)
        subtotal_bytes = sum(r["size_bytes"] for r in rows)
        print(f"\n### {cats_cn[cat]}  ({len(rows)} 条, 合计 {human_size(subtotal_bytes)})")
        print(f"{'名称':<34}{'大小':>10}{'文件数':>8}  {'最新 mtime':<20} 来源线索")
        print("-" * 100)
        for r in rows:
            name = r["name"]
            if len(name) > 32:
                name = name[:30] + ".."
            link = " -> " if r.get("is_symlink") else ""
            print(f"{name:<34}{r['size_human']:>10}{r['file_count']:>8}  "
                  f"{r['latest_mtime_str']:<20} {r['source']}{link}")
        print("-" * 100)
        print(f"{'小计':<34}{human_size(subtotal_bytes):>10}"
              f"{sum(r['file_count'] for r in rows):>8}")

    # 报告汇总。
    rs = inv["reports_summary"]
    print(f"\n### 评测/报告 reports/*.json  ({rs['total_files']} 个, "
          f"合计 {rs['total_human']})")
    top = list(rs["types"].items())[:8]
    print("  按类型 Top: " + ", ".join(f"{k}={v['count']}" for k, v in top))
    if rs["latest"]:
        print("  最新 5 条:")
        for r in rs["latest"]:
            print(f"    {r['mtime']}  {r['size_bytes']:>8}B  {r['name']}")

    # 建图重点摘要。
    ms = inv["map_summary"]
    print(f"\n### 建图/重建重点: {ms['total_items']} 条, "
          f"其中 {ms['items_with_gs_ply']} 条含 gs.ply 真产物, "
          f"合计 {ms['size_human']}")
    for p in ms["asset_dirs"][:10]:
        print(f"    - {p}")

    print("\n" + "=" * 100)
    t = inv["totals"]
    print(f"总计: {t['items']} 条 | 总大小 {t['size_human']} ({t['size_bytes']} bytes) "
          f"| 总文件数 {t['file_count']}")
    for cat in order:
        c = inv["categories"][cat]
        print(f"  - {cats_cn[cat]:<40} {c['count']:>3} 条  {c['size_human']:>10}")
    if inv["errors"]:
        print("\n注意(扫描中发现的缺失/异常):")
        for e in inv["errors"]:
            print(f"  ! {e}")
    print("=" * 100)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Z-MAX 只读数据资产清单 (下载/生成/建图)")
    ap.add_argument("--root", default=_DEFAULT_ROOT,
                    help="仓库根目录 (默认按脚本位置自动定位)")
    ap.add_argument("--json", action="store_true",
                    help="输出结构化 JSON 到 stdout (供 GUI 读取)")
    ap.add_argument("--json-out", metavar="PATH",
                    help="额外把 JSON 落盘到指定路径")
    ap.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH,
                    help=f"递归限深 (默认 {DEFAULT_MAX_DEPTH})")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    inv = build_inventory(root, args.max_depth)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(inv, f, ensure_ascii=False, indent=2)
        if not args.json:
            print(f"[dataset_inventory] JSON 已写入: {args.json_out}")

    if args.json:
        print(json.dumps(inv, ensure_ascii=False, indent=2))
    else:
        print_human(inv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
