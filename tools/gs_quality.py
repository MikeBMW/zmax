#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_quality.py — 3DGS 建图**质量门**(数据集健康 + 训练产物判定), 不假装成功。

为什么需要它(实测教训 2026-10-01):
  · 采集端把同一张图按 8Hz 连取十几次, 每次记一个不同 TCP 位姿 ⇒ 数据集里
    "同一张图配多个位姿" = 矛盾监督 ⇒ 训练视角都拟合不上, 但**日志里 loss 看着在降**,
    报告里 PSNR 也有 12.87 —— 不做判定就会把废资产当成果交付。
  · 判定必须与**平凡基线**比: "整幅填常数" 的 PSNR 也有 ~12dB, 低于它等于没建出东西。

用法:
  gs_quality.py --dataset <数据集目录>                     # 只看数据
  gs_quality.py --dataset <数据集> --model <产物目录>       # 再看训练产物(有 train_report.json 与 renders/)
  gs_quality.py --model <产物目录> --json <输出>            # 只看模型
输出: 人读摘要 + JSON(默认 <model 或 dataset>/quality_report.json)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

PASS, WARN, FAIL, INFO = "pass", "warn", "fail", "info"


def _gray(p, size=None):
    from PIL import Image
    im = Image.open(p).convert("L")
    if size:
        im = im.resize(size)
    return np.asarray(im).astype(np.float32)


def dataset_checks(d):
    out = {"dataset": os.path.abspath(d), "checks": {}, "notes": []}
    cj = json.load(open(os.path.join(d, "cameras.json"), encoding="utf-8"))
    fr = cj["frames"]
    n = len(fr)
    out["n_frames"] = n
    if n == 0:
        out["verdict"] = FAIL
        out["notes"].append("数据集没有帧")
        return out
    # ① 唯一图(按内容)
    import hashlib
    hs = []
    small = []
    for f in fr:
        p = os.path.join(d, "images", f["file"])
        try:
            hs.append(hashlib.md5(open(p, "rb").read()).hexdigest())
            small.append(_gray(p, (80, 60)))
        except Exception:
            hs.append("missing")
            small.append(np.zeros((60, 80), np.float32))
    uniq = len(set(hs))
    out["unique_images"] = uniq
    out["dup_ratio"] = round(1.0 - uniq / max(1, n), 4)
    # ② 不同视点(位置 5mm + 姿态 0.01)
    P = np.array([f["pos"] for f in fr], float)
    R = np.array([np.array(f["T_cam2world"], float)[:3, :3] for f in fr])
    q = np.round(np.hstack([P / 0.005, R.reshape(n, -1) / 0.01])).astype(np.int64)
    views = len({tuple(v) for v in q})
    out["distinct_views"] = views
    # ③ 同一位姿、不同时刻的画面差异(静态场景硬约束, 抓"同图配不同位姿")
    bins = {}
    for i in range(n):
        bins.setdefault(tuple(q[i]), []).append(i)
    difs = []
    for v in bins.values():
        if len(v) >= 2:
            for a, b in zip(v[:-1], v[1:]):
                difs.append(float(np.abs(small[a] - small[b]).mean()))
    out["same_pose_pairs"] = len(difs)
    out["same_pose_img_diff_med"] = round(float(np.median(difs)), 2) if difs else None
    # ④ 视差跨度 / 相邻基线
    spread = (P.max(0) - P.min(0)) * 1000
    out["spread_mm"] = [round(float(v), 1) for v in spread]
    if n >= 2:
        step = np.linalg.norm(np.diff(P, axis=0), axis=1) * 1000
        out["consecutive_baseline_mm_med"] = round(float(np.median(step)), 1)
    # ⑤ 画质异常(黑帧/模糊)
    m = np.array([s.mean() for s in small])
    c = np.array([s.std() for s in small])
    out["brightness_med"] = round(float(np.median(m)), 1)
    out["contrast_med"] = round(float(np.median(c)), 1)
    out["dark_frames"] = int((m < 30).sum())
    out["flat_frames"] = int((c < 12).sum())
    # ---- 判定 ----
    ck = out["checks"]
    ck["unique_images"] = (PASS if uniq / max(1, n) > 0.9 else FAIL,
                           "唯一图 %d/%d (重复率 %.1f%%); 重复>10%% ⇒ 同图配不同位姿=矛盾监督" % (uniq, n, out["dup_ratio"] * 100))
    ck["distinct_views"] = (PASS if views >= 50 else WARN, "真正不同视点 %d 个(3DGS 建议 ≥100)" % views)
    if len(difs) >= 5:
        _d = out["same_pose_img_diff_med"] or 999.0
        ck["static_scene"] = (PASS if _d < 8 else FAIL,
                              "同一位姿不同时刻画面差异中位 %.1f/255(应 <8, %d 对)" % (_d, len(difs)))
    elif len(difs) > 0:
        ck["static_scene"] = (WARN, "同一位姿配对只有 %d 对 ⇒ 样本不足, 不判定(需 ≥5)" % len(difs))
    ck["parallax"] = (PASS if max(spread) >= 150 else WARN,
                      "相机位姿跨度 %s mm (视差太小只能出浅浮雕)" % out["spread_mm"])
    ck["image_health"] = (PASS if out["dark_frames"] == 0 and out["flat_frames"] == 0 else WARN,
                          "黑帧 %d · 无纹理帧 %d" % (out["dark_frames"], out["flat_frames"]))
    out["verdict"] = FAIL if any(v[0] == FAIL for v in ck.values()) else (
        WARN if any(v[0] == WARN for v in ck.values()) else PASS)
    return out


def session_checks(s, hash_file="/home/ubuntu/zmax/zmax_data/gs_assets/scan_hashes.txt"):
    """采集会话(raw)体检 —— 这里能抓到"同一画面被存成多份、每份配不同位姿"这个致命坑:
    数据集里看不出(采样后重复对变少), 但 raw 层样本多、一眼可见。"""
    out = {"session": os.path.abspath(s), "checks": {}, "notes": []}
    fp = os.path.join(s, "frames.jsonl")
    if not os.path.exists(fp):
        out["verdict"] = WARN
        out["notes"].append("没有 frames.jsonl(不是采集会话?)")
        return out
    h = {}
    if os.path.exists(hash_file):
        for ln in open(hash_file, encoding="utf-8"):
            p = ln.split()
            if len(p) >= 2:
                h[os.path.basename(p[-1])] = p[0]
    rows = []
    for ln in open(fp, encoding="utf-8"):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        p = r.get("pose_after") or r.get("pose_before") or {}
        if not r.get("file") or "x" not in p:
            continue
        md5 = r.get("md5") or h.get(os.path.basename(r["file"]), "?" + r["file"])
        rows.append({"file": r["file"], "md5": md5, "dup": bool(r.get("dup")),
                     "pos": np.array([float(p["x"]), float(p["y"]), float(p["z"])])})
    if not rows:
        out["verdict"] = WARN
        out["notes"].append("没有带位姿的帧记录")
        return out
    files = {r["file"] for r in rows}
    contents = {r["md5"] for r in rows}
    out.update(fetches=len(rows), unique_files=len(files), unique_contents=len(contents),
               content_dup_ratio=round(1.0 - len(contents) / max(1, len(rows)), 4),
               same_content_diff_files=int(len(files) - len(contents)) if len(files) > len(contents) else 0)
    # 同一内容被存成多个文件 ⇒ 把它们的位姿摊开看差异
    by = {}
    for r in rows:
        by.setdefault(r["md5"], []).append(r)
    bad, checked = 0, 0
    worst = 0.0
    for k, v in by.items():
        fl = {x["file"] for x in v}
        if len(fl) <= 1:
            continue
        checked += 1
        P = np.array([x["pos"] for x in v])
        d = float(np.linalg.norm(P - P[0], axis=1).max())
        worst = max(worst, d)
        if d > 0.005:
            bad += 1
    out["content_groups_with_bad_poses"] = bad
    out["worst_pose_spread_in_group_mm"] = round(worst * 1000, 1)
    ck = out["checks"]
    if checked:
        ck["content_pose_consistency"] = (
            (PASS if bad == 0 else FAIL),
            "同一画面(共 %d 组)里位姿一致: 不一致 %d 组, 最大位姿差 %.1fmm ⇒ 0 才正常"
            "(原来每取必存 + 每次记位姿 ⇒ 同图配多位姿=矛盾监督)" % (checked, bad, worst * 1000))
    else:
        ck["content_pose_consistency"] = (INFO, "没有「同一画面被存成多个文件」的情况"
                                                "(采集器已按内容去重: 内容不变不落盘)")
    ck["fetch_rate"] = (WARN if out["content_dup_ratio"] > 0.5 else PASS,
                        "取图 %d 次 / 唯一画面 %d 张 (重复 %.1f%%) ⇒ 相机有效帧率远低于取图率时, "
                        "重复取图只是浪费, 数据本身不脏" % (len(rows), len(contents), out["content_dup_ratio"] * 100))
    out["verdict"] = FAIL if any(v[0] == FAIL for v in ck.values()) else (
        WARN if any(v[0] == WARN for v in ck.values()) else PASS)
    return out


def model_checks(mdir, dset=None):
    out = {"model": os.path.abspath(mdir), "checks": {}, "notes": []}
    rep_p = os.path.join(mdir, "train_report.json")
    if not os.path.exists(rep_p):
        out["verdict"] = FAIL
        out["notes"].append("没有 train_report.json")
        return out
    rep = json.load(open(rep_p, encoding="utf-8"))
    out["n_gaussians"] = rep.get("n_gaussians")
    out["psnr_holdout_db"] = rep.get("psnr_holdout_db")
    out["psnr_train_db"] = rep.get("psnr_train_db")
    # 平凡基线: "整幅填常数(该图均值)" 的 PSNR —— 拿留出渲染存档里的 GT 现算
    rd = os.path.join(mdir, "renders")
    base, uniq_colors, n_r = [], [], 0
    if os.path.isdir(rd):
        gts = sorted(f for f in os.listdir(rd) if f.endswith("_gt.png"))
        from PIL import Image
        for g in gts:
            a = np.asarray(Image.open(os.path.join(rd, g)).convert("RGB")).astype(np.float32) / 255.0
            mu = a.reshape(-1, 3).mean(0)
            base.append(-10 * math.log10(max(float(((a - mu) ** 2).mean()), 1e-12)))
            n_r += 1
        for r in sorted(f for f in os.listdir(rd) if f.endswith(".png") and not f.endswith("_gt.png"))[:3]:
            img = np.asarray(Image.open(os.path.join(rd, r)).convert("RGB"))
            uniq_colors.append(len(np.unique(img.reshape(-1, 3), axis=0)))
    out["trivial_baseline_db"] = round(float(np.mean(base)), 2) if base else None
    out["render_unique_colors"] = uniq_colors
    out["renders_checked"] = n_r
    out["recipe"] = rep.get("recipe", {})
    # ---- 判定 ----
    ck = out["checks"]
    if out["trivial_baseline_db"] is not None and out["psnr_holdout_db"] is not None:
        d = out["psnr_holdout_db"] - out["trivial_baseline_db"]
        out["gain_over_trivial_db"] = round(d, 2)
        ck["beats_trivial"] = (PASS if d >= 3.0 else FAIL,
                               "留出 PSNR %.2f dB · 平凡基线(填常数) %.2f dB ⇒ 增益 %.2f dB (要 ≥3)"
                               % (out["psnr_holdout_db"], out["trivial_baseline_db"], d))
    if uniq_colors:
        worst = min(uniq_colors)
        ck["render_has_structure"] = (PASS if worst > 1000 else FAIL,
                                      "渲染图唯一色 %s (纯色=1 ⇒ 没渲染出场景)" % uniq_colors)
    if out["psnr_train_db"] is not None and out["trivial_baseline_db"] is not None:
        d2 = out["psnr_train_db"] - out["trivial_baseline_db"]
        ck["fits_training_views"] = (PASS if d2 >= 5 else FAIL,
                                     "训练视角 PSNR %.2f dB ⇒ 比基线高 %.2f dB (要 ≥5; 低了说明连拟合都没做到)"
                                     % (out["psnr_train_db"], d2))
    out["verdict"] = FAIL if any(v[0] == FAIL for v in ck.values()) else (
        WARN if any(v[0] == WARN for v in ck.values()) else PASS)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--session", default="", help="采集会话(raw)目录: 查同画面多位姿/重复取图")
    ap.add_argument("--json", default="", help="JSON 输出路径(默认写到 model/dataset 目录)")
    args = ap.parse_args()
    if not args.dataset and not args.model and not args.session:
        print("需要 --dataset / --model / --session 至少一个")
        return 2
    rep = {"ts": __import__("time").strftime("%F %T")}
    if args.session:
        rep["session"] = session_checks(args.session)
    if args.dataset:
        rep["data"] = dataset_checks(args.dataset)
    if args.model:
        rep["model"] = model_checks(args.model, args.dataset)
    verds = [v["verdict"] for k, v in rep.items() if isinstance(v, dict) and "verdict" in v]
    rep["verdict"] = FAIL if FAIL in verds else (WARN if WARN in verds else PASS)
    for part in ("session", "data", "model"):
        if part in rep:
            p = rep[part]
            print("── %s: %s (%s)" % (part, p.get("verdict", "?").upper(),
                                      p.get("dataset") or p.get("model")))
            for k, (v, why) in p.get("checks", {}).items():
                print("   [%s] %-22s %s" % (v.upper(), k, why))
            for nt in p.get("notes", []):
                print("   · %s" % nt)
    print("══ 总判定: **%s**" % rep["verdict"].upper())
    op = args.json
    if not op:
        base = args.model or args.dataset
        op = os.path.join(base, "quality_report.json") if base else ""
    if op:
        json.dump(rep, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("   → %s" % op)
    return 0 if rep["verdict"] != FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
