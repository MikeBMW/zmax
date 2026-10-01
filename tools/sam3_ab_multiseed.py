#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SAM3 微调适配器 **同口径 A/B 判据** (多 seed × 多折) —— 转绿 / 不转绿的取证脚本

回答一个问题: **微调到底有没有提升?** (老倪门槛: 有提升非仅不回退; 未证明提升不得进默认档)

设计 (每条都对应用户给的判据要求):
  ① **多 seed × 多折**: K 折把全部标注帧轮着当留出集 (每帧恰好被留出一次), 每折换 S 个训练种子重训;
     报 **均值 ± 标准差** + 最低折, 不拿单次数字当结论。
  ② **同源留出集**: 留出帧**不参与**该折训练 (K 折交叉验证), 评估口径 = 训练同源 (同一 processor/分辨率/
     同一教师伪标签缓存)。
  ③ **平凡基线**: 每折都跑 **未微调基座** (vit_lora_blocks=0 ⇒ 零 LoRA) 的**同口径**数字作对照。
  ④ **框 IoU 与掩膜 IoU 分开报**, 并写死口径:
     · 掩膜 IoU 的对照方 = **教师伪标签** (= 冻结基座在同一精确框提示下的输出) ⇒ **基座在该指标上是上界**,
       蒸馏只能逼近; 这条**不是**"真值", 报告里一律写作"教师伪标签"。
     · 框 IoU 的对照方 = **真标注 GT 框** ⇒ 基座**不是**上界, 是唯一可能真提升的那条路。
  ⑤ **Δ vs 噪声带**: 主判据 = 框 IoU(真标注) 的配对 95% 置信区间; 若下界 ≤ 0 (Δ 落在噪声带内) ⇒
     结论必须是「**未证明提升**」, 不许把"没变差"包装成"提升"。

判据 (写死, 先定后跑):
  转 in_service ⇔ 主指标(框 IoU@真标注) 配对 Δ 的 95%CI 下界 > 0 **且** 掩膜 IoU(教师伪标签) Δ 的 CI 下界 ≥ 0
                 (即: 真标注那一路确有提升, 且没有在教师一致性上明显变差)
  否则          ⇒ 保持 candidate, 结论写「未证明提升 (Δ ≤ 噪声带)」

用法:
  ./gui-venv311/bin/python tools/sam3_ab_multiseed.py --folds 3 --seeds 0,1,2 \
      --out reports/sam3_ab_<ts> [--shipped-adapter outputs/sam3_finetune/annot_v1/lora_adapter]
  ./gui-venv311/bin/python tools/sam3_ab_multiseed.py --folds 3 --seeds 0 --smoke   # 冒烟(不许当结论)

显存红线: 本机同刻只允许一个占卡模型; 跑前确认 nvidia-smi 无别的 >1500MiB 计算进程。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from lerobot.policies.sam3_seg import finetune as FT          # noqa: E402
from lerobot.policies.sam3_seg.lora_inject import load_lora_adapter   # noqa: E402


def _adapter_prefix_filter():
    """只对**视觉塔**限"最后 N 个 block"; 文本塔全层 (与训练侧 build_trainable_model 同口径)。
    把同一谓词套到文本塔会因索引 0..23 < 24 而静默跳过全部文本层 ⇒ 键对不上。"""
    return {"vision_encoder.backbone.layers.":
            (lambda i, N=FT.VIT_LORA_BLOCKS: i >= 32 - N)}


# ── 折目录 (符号链接, 不复制数据; 教师伪标签按折的 split 名软链过去) ─────────────
def make_fold_dirs(pool, fold_stems, root: Path, master_cache: Path, master_ds: Path) -> tuple[Path, Path]:
    ds, cache = root / "dataset", root / "cache"
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (ds / sub).mkdir(parents=True, exist_ok=True)
    (cache / FT.MASK_SUBDIR / "train").mkdir(parents=True, exist_ok=True)
    (cache / FT.MASK_SUBDIR / "val").mkdir(parents=True, exist_ok=True)
    if not (ds / "data.yaml").exists():
        shutil.copy2(master_ds / "data.yaml", ds / "data.yaml")
    for s in pool:
        split = "val" if s.stem in fold_stems else "train"
        img = Path(s.img_path)
        lab = master_ds / "labels" / s.split / f"{s.stem}.txt"
        for src, dst in ((img, ds / "images" / split / img.name),
                         (lab, ds / "labels" / split / f"{s.stem}.txt")):
            if dst.exists() or dst.is_symlink():
                continue
            if src.exists():
                dst.symlink_to(src.resolve())
        for i in range(len(s.boxes_xyxy)):
            p = FT.teacher_mask_path(master_cache, s, i)          # master: <split>/<stem>__b<i>.png
            # ⚠️ 教师伪标签与"帧属于哪个 split"无关, 而**训练侧看折的 split、评估侧看原 split**
            # ⇒ 两个 split 目录都软链一份 (否则评估侧按原 split 找不到, 报 FileNotFoundError)。
            for split2 in ("train", "val"):
                for ext in (".png", ".json"):
                    src = p.with_suffix(ext)
                    dst = cache / FT.MASK_SUBDIR / split2 / (p.stem + ext)
                    if (dst.exists() or dst.is_symlink()) or not src.exists():
                        continue
                    dst.symlink_to(src.resolve())
    return ds, cache


# ── 同口径逐 query 评估 (基座 / 适配器 共用这一个函数) ────────────────────────
@FT.torch.no_grad()
def eval_perquery(model, samples, cache, args, jitter: float, seed: int) -> dict:
    """返回 {(stem, gt_idx): {"mask":IoU(对教师伪标签), "box":IoU(对GT框), "q":query}}。

    配对口径: 以 **(帧, GT 框)** 为单位 (而不是 query 下标) —— 基座与适配器的 Hungarian 匹配结果
    可能落在不同 query 上, 按 GT 框对齐才能逐单位配对比较。
    """
    torch = FT.torch
    model.eval()
    rng = np.random.default_rng(seed)
    rows: dict = {}
    for s in samples:
        boxes = FT.jitter_boxes(s.boxes_xyxy, jitter, rng)          # 同一 seed ⇒ 基座与适配器看到**同一批**抖动框
        inp = {k: (v.to("cuda") if k != "original_sizes" else v) for k, v in cache[s.stem].items()}
        inp["pixel_values"] = inp["pixel_values"].to(torch.bfloat16)
        bb = torch.tensor([[[(b[0] + b[2]) / 2 / s.W, (b[1] + b[3]) / 2 / s.H,
                             (b[2] - b[0]) / s.W, (b[3] - b[1]) / s.H] for b in boxes]],
                          dtype=torch.bfloat16, device="cuda")
        inp["input_boxes"] = bb
        inp["input_boxes_labels"] = torch.ones(bb.shape[:2], dtype=torch.long, device="cuda")
        out = model(**inp)
        hw_ = int(out.pred_masks.shape[-1])
        pm = out.pred_masks[0].float().sigmoid()
        pb = out.pred_boxes[0].float()
        gt = torch.tensor([[b[0] / s.W, b[1] / s.H, b[2] / s.W, b[3] / s.H] for b in s.boxes_xyxy],
                          dtype=torch.float32, device="cuda")
        qi, gi = FT.match_queries(pb, gt)
        for q, g in zip(qi.tolist(), gi.tolist()):
            m = pm[q] > 0.5
            t = torch.as_tensor(FT.load_teacher_mask(FT.teacher_mask_path(args.cache_dir, s, g), hw_)[0],
                                device="cuda")
            u = (m | t).sum().clamp(min=1)
            rows[(s.stem, g)] = {"mask": float((m & t).sum()) / float(u),
                                 "box": float(FT._box_iou(pb[q], gt[g])), "q": int(q)}
    return rows


def _run_args(**kw):
    """run_train 需要的参数命名空间 (默认与 annot_v1 交付口径一致)。"""
    base = dict(seed=0, dataset=FT.DATASET_DIR, model_dir=FT.SAM3_DIR, size=FT.SIZE,
                lora_vit_blocks=FT.VIT_LORA_BLOCKS, r=FT.R, alpha=FT.ALPHA,
                cache_dir="", out="", epochs=12, max_steps=0, lr_lora=2e-4, lr_head=1e-4,
                gate_steps=2, log_every=50, w_mask=2.0, w_box=1.0, w_cls=0.5, w_pres=1.0,
                aug="light", box_jitter=0.08)
    base.update(kw)
    return argparse.Namespace(**base)


def stats(vals):
    a = np.asarray(vals, dtype=float)
    if a.size == 0:
        return {"n": 0, "mean": 0.0, "std": 0.0}
    return {"n": int(a.size), "mean": float(a.mean()),
            "std": float(a.std(ddof=1)) if a.size > 1 else 0.0,
            "min": float(a.min()), "max": float(a.max())}


def paired_delta(ad: dict, bs: dict, keys) -> list:
    out = []
    for k in keys:
        if k in ad and k in bs:
            out.append(ad[k] - bs[k])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="SAM3 适配器 多 seed × 多折 同口径 A/B")
    ap.add_argument("--folds", type=int, default=3, help="K 折 (每帧恰好留出一次)")
    ap.add_argument("--seeds", default="0,1,2", help="训练随机种子列表")
    ap.add_argument("--jitters", default="0,0.08", help="提示框抖动档 (0=精确框)")
    ap.add_argument("--eval-seeds", default="11,12,13", help="评估抖动种子 (基座/适配器共用同一批)")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--dataset", default=FT.DATASET_DIR)
    ap.add_argument("--master-cache", default=str(REPO / "data" / "sam3_finetune_cache"))
    ap.add_argument("--out", default="")
    ap.add_argument("--shipped-adapter", default="", help="额外汇总: 交付产物 annot_v1 在它自己的留出 val 上")
    ap.add_argument("--smoke", action="store_true", help="冒烟(极少步数), 结果不许当结论")
    a = ap.parse_args()
    if a.smoke:
        a.folds, a.seeds, a.epochs, a.max_steps = 3, "0", 1, 6
        a.jitters, a.eval_seeds = "0", "11"
    if not a.out:
        a.out = str(REPO / "reports" / ("sam3_ab_" + time.strftime("%Y%m%d_%H%M%S")))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    folds_ts = out / "folds"
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
    jitters = [float(x) for x in a.jitters.split(",") if x.strip()]
    evseeds = [int(x) for x in a.eval_seeds.split(",") if x.strip()]

    import torch
    free = torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_reserved(0)
    used = torch.cuda.memory_allocated(0)
    print("[gpu] 本进程可见已用 %.2fGB / 共 %.2fGB (跑前请确认无别的计算进程)" %
          (used / 1e9, torch.cuda.get_device_properties(0).total_memory / 1e9))

    master_ds = Path(a.dataset)
    master_cache = Path(a.master_cache)
    names = FT.read_class_names(master_ds)
    pool = sorted(FT.scan_split(master_ds, "train") + FT.scan_split(master_ds, "val"), key=lambda s: s.stem)
    print("[data] 全部标注帧 %d · 框 %d · 类 %s" %
          (len(pool), sum(len(s.boxes_xyxy) for s in pool), names))

    # 折划分 (固定 rng; 每帧恰好落在一折的留出集里)
    perm = np.random.default_rng(20261001).permutation(len(pool))
    fold_idx = np.array_split(perm, a.folds)
    folds = [[pool[i] for i in ix] for ix in fold_idx]
    print("[fold] %d 折 · 每折留出帧数 %s" % (a.folds, [len(f) for f in folds]))
    fold_dirs = [make_fold_dirs(pool, {s.stem for s in f}, folds_ts / f"f{fi}", master_cache, master_ds)
                 for fi, f in enumerate(folds)]

    # ── 公共预编码 (输入只与帧有关, 与折无关) ────────────────────────────────
    # ① 平凡基线 = **纯净 HF 基座** (完全不注入 LoRA) —— 不是"注入了零初始化 LoRA 的模型"
    from transformers import Sam3Model, Sam3Processor
    proc0 = Sam3Processor.from_pretrained(FT.SAM3_DIR, local_files_only=True)
    try:
        proc0.image_processor.size = {"height": FT.SIZE, "width": FT.SIZE}
    except Exception:                                            # noqa: BLE001
        pass
    model0 = Sam3Model.from_pretrained(FT.SAM3_DIR, local_files_only=True,
                                       dtype=torch.bfloat16).to("cuda").eval()
    proc = proc0
    cache_raw = FT.preencode(proc, pool, FT.SIZE, names, log=print)

    # 等价性自证: 训练口径的 step-0 模型 (**已注入 LoRA, B 零初始化**) 与纯净基座
    #    必须逐位一致 ⇒ 「训练 step0 基线 == 基座」这句话有据可依。
    mz, _, _ = FT.build_trainable_model(FT.SAM3_DIR, size=FT.SIZE, log=print)
    with torch.no_grad():
        s0 = pool[0]
        inp = {k: (v.to("cuda") if k != "original_sizes" else v) for k, v in cache_raw[s0.stem].items()}
        inp["pixel_values"] = inp["pixel_values"].to(torch.bfloat16)
        bb = torch.tensor([[[(b[0] + b[2]) / 2 / s0.W, (b[1] + b[3]) / 2 / s0.H,
                             (b[2] - b[0]) / s0.W, (b[3] - b[1]) / s0.H] for b in s0.boxes_xyxy]],
                          dtype=torch.bfloat16, device="cuda")
        inp["input_boxes"] = bb
        inp["input_boxes_labels"] = torch.ones(bb.shape[:2], dtype=torch.long, device="cuda")
        o1, o0 = mz(**inp), model0(**inp)
        d_m = float((o1.pred_masks.float() - o0.pred_masks.float()).abs().max())
        d_b = float((o1.pred_boxes.float() - o0.pred_boxes.float()).abs().max())
    print("[equiv] 零初始化 LoRA 注入后 vs 纯净基座: pred_masks 最大逐位差 %.3e · pred_boxes %.3e "
          "⇒ %s" % (d_m, d_b, "逐位一致 ✅" if (d_m == 0 and d_b == 0) else "有差异 ❌"))
    del mz
    torch.cuda.empty_cache()

    rows_path = out / "rows.jsonl"
    recs = []
    t_all = time.time()
    equiv = {"max_abs_diff_pred_masks": d_m, "max_abs_diff_pred_boxes": d_b,
             "bitwise_equal": bool(d_m == 0 and d_b == 0)}

    # ── ① 平凡基线: 未微调基座 (零 LoRA), 每折留出集 × 每抖动档 × 每评估种子 ──
    base_rows = {}                                   # (fold, jitter, evseed) -> rows
    for fi, fold in enumerate(folds):
        for j in jitters:
            for es in evseeds:
                args = _run_args(cache_dir=str(fold_dirs[fi][1]))
                r = eval_perquery(model0, fold, cache_raw, args, j, es)
                base_rows[(fi, j, es)] = r
        print("[base] 折%d 留出 %d 帧 · 基线评估完成 (%d 档×%d 种子 · %d 个 GT 框)"
              % (fi, len(fold), len(jitters), len(evseeds), len(base_rows[(fi, jitters[0], evseeds[0])])))
    del model0
    torch.cuda.empty_cache()
    print("[base] 基座模型已释放 (显存 %.2fGB)" % (torch.cuda.memory_allocated() / 1e9))

    # ── ② 逐折 × 逐种子: 训练适配器 → 同口径评估 ──
    def seed_eval(model, fi, fold, cache_dir, tag, extra=None):
        for j in jitters:
            for es in evseeds:
                args = _run_args(cache_dir=cache_dir)
                r = eval_perquery(model, fold, cache_raw, args, j, es)
                bs = base_rows[(fi, j, es)]
                keys = sorted(set(r) & set(bs))
                dm = paired_delta({k: r[k]["mask"] for k in r}, {k: bs[k]["mask"] for k in bs}, keys)
                db = paired_delta({k: r[k]["box"] for k in r}, {k: bs[k]["box"] for k in bs}, keys)
                rec = {"tag": tag, "fold": fi, "seed": tag.split("seed")[-1], "jitter": j, "eval_seed": es,
                       "n_units": len(keys), **(extra or {}),
                       "base_mask": float(np.mean([bs[k]["mask"] for k in keys])) if keys else 0.0,
                       "ad_mask": float(np.mean([r[k]["mask"] for k in keys])) if keys else 0.0,
                       "base_box": float(np.mean([bs[k]["box"] for k in keys])) if keys else 0.0,
                       "ad_box": float(np.mean([r[k]["box"] for k in keys])) if keys else 0.0,
                       "d_mask": float(np.mean(dm)) if dm else 0.0, "d_mask_sd": float(np.std(dm, ddof=1)) if len(dm) > 1 else 0.0,
                       "d_box": float(np.mean(db)) if db else 0.0, "d_box_sd": float(np.std(db, ddof=1)) if len(db) > 1 else 0.0,
                       "win_box": float(np.mean([x > 0 for x in db])) if db else 0.0}
                recs.append(rec)
                with open(rows_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print("[%s] 折%d 抖动%.2f es%d · n=%d · 框IoU %s→%s (Δ%+.4f) · 掩膜IoU %s→%s (Δ%+.4f)"
                      % (tag, fi, j, es, rec["n_units"], ("%.4f" % rec["base_box"]), ("%.4f" % rec["ad_box"]),
                         rec["d_box"], ("%.4f" % rec["base_mask"]), ("%.4f" % rec["ad_mask"]), rec["d_mask"]))
        return

    row_cache = {}
    for fi, fold in enumerate(folds):
        fold_stems = {s.stem for s in fold}
        ds_dir, cache_dir = make_fold_dirs(pool, fold_stems, folds_ts / f"f{fi}", master_cache, master_ds)
        print("[fold%d] 训练集 %d 帧 / 留出 %d 帧" % (fi, len(pool) - len(fold), len(fold)))
        for sd in seeds:
            run_out = out / f"f{fi}_seed{sd}"
            run_out.mkdir(parents=True, exist_ok=True)
            args = _run_args(seed=sd, dataset=str(ds_dir), cache_dir=str(cache_dir), out=str(run_out),
                             epochs=a.epochs, max_steps=a.max_steps)
            t0 = time.time()
            print("\n=== 训练 折%d seed%d → %s ===" % (fi, sd, run_out))
            res = FT.run_train(args, log=print)
            (run_out / "run_report.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
            print("[train] 折%d seed%d 完成 %.1fs · peak %.2fGB · 步 %d" %
                  (fi, sd, time.time() - t0, res["peak_gb"], res["steps"]))
            # 评估用**从盘上重新加载的产物** (与部署同一条加载路径 ⇒ 顺带证明落盘适配器真能装回模型)
            del res
            torch.cuda.empty_cache()
            mad, _, _ = FT.build_trainable_model(FT.SAM3_DIR, size=FT.SIZE, log=print)
            info = load_lora_adapter(mad, str(run_out / "lora_adapter"), targets=dict(FT.LORA_TARGETS),
                                     r=FT.R, alpha=FT.ALPHA, prefix_filter=_adapter_prefix_filter(), log=print)
            seed_eval(mad, fi, fold, str(cache_dir), tag=f"fold{fi}_seed{sd}",
                      extra={"adapter_sha256_12": info["sha256"][:12], "adapter_tensors": info["n_tensors"],
                             "adapter_nonzero_B": info["nonzero_lora_B"]})
            del mad, info
            torch.cuda.empty_cache()

    # ── ③ 统计 (均值±标准差 / K 折最低折 / 配对 95%CI) ──
    summary = {"config": {"folds": a.folds, "seeds": seeds, "jitters": jitters, "eval_seeds": evseeds,
                          "epochs": a.epochs, "max_steps": a.max_steps, "dataset": str(master_ds),
                          "n_frames": len(pool), "n_boxes": sum(len(s.boxes_xyxy) for s in pool),
                          "classes": names, "smoke": bool(a.smoke)},
               "gpu": {"peak_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2)},
               "base_model_equivalence": equiv,
               "per_run": recs, "metrics": {}}
    for j in jitters:
        sub = [r for r in recs if r["jitter"] == j]
        d_box = [r["d_box"] for r in sub]
        d_mask = [r["d_mask"] for r in sub]
        fold_means_box = [float(np.mean([r["d_box"] for r in sub if r["fold"] == fi])) for fi in range(a.folds)]
        fold_means_mask = [float(np.mean([r["d_mask"] for r in sub if r["fold"] == fi])) for fi in range(a.folds)]
        seed_means_box = [float(np.mean([r["d_box"] for r in sub if r["seed"] == str(sd)])) for sd in seeds]
        n = sum(r["n_units"] for r in sub)                 # 单位样本数 (跨 run 求和; 非独立样本已注明)
        m = float(np.mean(d_box)) if d_box else 0.0
        sd_ = float(np.std(d_box, ddof=1)) if len(d_box) > 1 else 0.0
        se = sd_ / np.sqrt(len(d_box)) if d_box else 0.0
        ci = (m - 1.96 * se, m + 1.96 * se)
        mm = float(np.mean(d_mask)) if d_mask else 0.0
        sdm = float(np.std(d_mask, ddof=1)) if len(d_mask) > 1 else 0.0
        sem = sdm / np.sqrt(len(d_mask)) if d_mask else 0.0
        summary["metrics"]["jitter%.2f" % j] = {
            "runs": len(sub), "n_units_total": n,
            "d_box_mean": m, "d_box_sd": sd_, "d_box_ci95": [ci[0], ci[1]],
            "d_box_by_fold": stats(fold_means_box), "d_box_min_fold": min(fold_means_box) if fold_means_box else 0.0,
            "d_box_by_seed": stats(seed_means_box),
            "d_mask_mean": mm, "d_mask_sd": sdm, "d_mask_ci95": [mm - 1.96 * sem, mm + 1.96 * sem],
            "d_mask_min_fold": min(fold_means_mask) if fold_means_mask else 0.0,
            "base_box_mean": float(np.mean([r["base_box"] for r in sub])) if sub else 0.0,
            "ad_box_mean": float(np.mean([r["ad_box"] for r in sub])) if sub else 0.0,
            "base_mask_mean": float(np.mean([r["base_mask"] for r in sub])) if sub else 0.0,
            "ad_mask_mean": float(np.mean([r["ad_mask"] for r in sub])) if sub else 0.0,
            "win_rate_box": float(np.mean([r["win_box"] for r in sub])) if sub else 0.0}

    # ── ④ 判据 (先定后跑; 主指标 = 框 IoU@真标注) ──
    main = summary["metrics"].get("jitter%.2f" % jitters[0], {})
    ci_lo = main.get("d_box_ci95", [0, 0])[0]
    ci_hi_mask = main.get("d_mask_ci95", [0, 0])
    improved = (ci_lo > 0) and (ci_hi_mask[0] >= 0)
    d_box_m = main.get("d_box_mean") or 0.0
    d_box_sd = main.get("d_box_sd") or 0.0
    mag_in_noise = abs(d_box_m) < d_box_sd        # 老倪口径: Δ 小于 ±标准差 = 噪声带内
    reasons = []
    if ci_lo <= 0:
        reasons.append("主指标 Δ 的 95%%CI 下界 %.4f ≤ 0 (统计上未超出噪声)" % ci_lo)
    if ci_hi_mask[0] < 0:
        reasons.append("掩膜 IoU(对教师伪标签) 显著下降 CI95 [%+.4f, %+.4f] ⇒ 掩膜口径退化 "
                       "(服务对外交付的正是掩膜/多边形)" % (ci_hi_mask[0], ci_hi_mask[1]))
    if mag_in_noise:
        reasons.append("Δ 幅度 |%+.4f| < run 间标准差 %.4f ⇒ 提升量小于噪声带" % (d_box_m, d_box_sd))
    if (main.get("d_box_min_fold") or 0) < 0:
        reasons.append("有折为负 (最低折 %+.4f)" % main["d_box_min_fold"])
    if improved:
        reasons = ["主指标 Δ 显著为正 (%+.4f, CI95 下界 %+.4f > 0) 且掩膜口径未退化" % (d_box_m, ci_lo)]
    summary["verdict"] = {
        "primary_metric": "box_iou_vs_gt(真标注) @ jitter%.2f" % jitters[0],
        "primary_delta_mean": d_box_m, "primary_ci95": main.get("d_box_ci95"),
        "noise_band_sd": d_box_sd, "magnitude_within_noise_band": bool(mag_in_noise),
        "mask_metric": "mask_iou_vs_teacher(教师伪标签 ⇒ 基座=上界) @ jitter%.2f" % jitters[0],
        "mask_delta_mean": main.get("d_mask_mean"), "mask_ci95": main.get("d_mask_ci95"),
        "rule": "转绿 ⇔ 主指标 Δ 的 95%CI 下界 > 0 且 掩膜 Δ 的 CI 下界 ≥ 0",
        "improved": bool(improved), "reasons": reasons,
        "verdict": ("有提升 (Δ 显著大于噪声带) ⇒ 可转 in_service" if improved
                    else "未证明提升 ⇒ 保持 candidate; 原因: " + "; ".join(reasons))}

    # ── ⑤ 交付产物 annot_v1 在它自己的留出 val 上的单独一行 (样本极少, 只作参考) ──
    if a.shipped_adapter and not a.smoke:
        print("\n=== 交付产物自证: %s ===" % a.shipped_adapter)
        tr, va = FT.scan_split(master_ds, "train"), FT.scan_split(master_ds, "val")
        cache_all = FT.preencode(proc, tr + va, FT.SIZE, names, log=print)
        args = _run_args(cache_dir=str(master_cache))
        mbase, _, _ = FT.build_trainable_model(FT.SAM3_DIR, size=FT.SIZE, vit_lora_blocks=0, log=print)
        shipped = {}
        for j in jitters:
            for es in evseeds:
                b = eval_perquery(mbase, va, cache_all, args, j, es)
                shipped["base@j%.2f_es%d" % (j, es)] = b
        del mbase
        torch.cuda.empty_cache()
        mad, _, _ = FT.build_trainable_model(FT.SAM3_DIR, size=FT.SIZE, log=print)
        info = load_lora_adapter(mad, a.shipped_adapter, targets=dict(FT.LORA_TARGETS), r=FT.R, alpha=FT.ALPHA,
                                 prefix_filter=_adapter_prefix_filter(), log=print)
        for j in jitters:
            for es in evseeds:
                b = eval_perquery(mad, va, cache_all, args, j, es)
                bs = shipped["base@j%.2f_es%d" % (j, es)]
                keys = sorted(set(b) & set(bs))
                kk = "annot_v1@j%.2f_es%d" % (j, es)
                shipped[kk] = {"n_units": len(keys),
                               "base_mask": float(np.mean([bs[k]["mask"] for k in keys])),
                               "ad_mask": float(np.mean([b[k]["mask"] for k in keys])),
                               "base_box": float(np.mean([bs[k]["box"] for k in keys])),
                               "ad_box": float(np.mean([b[k]["box"] for k in keys]))}
                shipped[kk]["d_box"] = shipped[kk]["ad_box"] - shipped[kk]["base_box"]
                shipped[kk]["d_mask"] = shipped[kk]["ad_mask"] - shipped[kk]["base_mask"]
                print("[shipped] %s n=%d 框 %.4f→%.4f (Δ%+.4f) 掩膜 %.4f→%.4f (Δ%+.4f)"
                      % (kk, len(keys), shipped[kk]["base_box"], shipped[kk]["ad_box"], shipped[kk]["d_box"],
                         shipped[kk]["base_mask"], shipped[kk]["ad_mask"], shipped[kk]["d_mask"]))
        summary["shipped"] = {"adapter": a.shipped_adapter, "adapter_info": info,
                              "n_val_frames": len(va), "n_val_boxes": sum(len(s.boxes_xyxy) for s in va),
                              "rows": {k: v for k, v in shipped.items() if not k.startswith("base@")}}
        del mad
        torch.cuda.empty_cache()

    (out / "ab_summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n" + "=" * 78)
    v = summary["verdict"]
    print("主指标 %s: Δ 均值 %+.4f (sd %.4f) · 95%%CI [%+.4f, %+.4f]"
          % (v["primary_metric"], v["primary_delta_mean"] or 0, v["noise_band_sd"] or 0,
             (v["primary_ci95"] or [0, 0])[0], (v["primary_ci95"] or [0, 0])[1]))
    print("掩膜口径 %s: Δ 均值 %+.4f" % (v["mask_metric"], v["mask_delta_mean"] or 0))
    print("判定: %s" % v["verdict"])
    print("总耗时 %.1f min · 报告 %s" % ((time.time() - t_all) / 60, out / "ab_summary.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
