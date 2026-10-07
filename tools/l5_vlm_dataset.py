#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 L5 · VLM 蒸馏数据通道 (2026-10-07) —— 给本地 Qwen2.5-VL 造 SFT 样本

老倪口径: 「L5 定方向造数据」。L5 现有两条路:
  · 教师 = 现有强 VLM 通道 (SceneVLM: DeepSeek-flash vision, ~/.hermes/.env 已配 key)
  · 学生 = 本地 Qwen2.5-VL-3B-Instruct (8GB 4060 可跑, 蒸馏后离线可用)
本脚本只做**数据**这件事: 真帧 → 真教师 → 合法 JSON 样本, 落盘可复现。

纪律 (与仓库其它工具同口径):
  · 只收**教师真返回且 JSON 合法**的样本; 不合法/看不清的**丢弃并计数**, 绝不补写。
  · 像素内容去重 (同一画面不重复进样本); 断点续跑 (已采过的帧 hash 直接跳过)。
  · train/val 按**帧**划分 (同帧不跨集, 避免同源泄漏 = 假提升)。
  · 全程打印进度/合法率/耗时 (可观测), 结束落 manifest (含教师 src 与参数)。

用法:
  gui-venv311/bin/python tools/l5_vlm_dataset.py build --limit 60 --workers 4
  gui-venv311/bin/python tools/l5_vlm_dataset.py stat
"""
import argparse
import concurrent.futures as cf
import glob
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT_DIR = os.path.join(ROOT, "data/l5_vlm_sft")
ALL_JSONL = os.path.join(OUT_DIR, "all.jsonl")
MANIFEST = os.path.join(OUT_DIR, "manifest.json")
# 默认帧池: 真机标注帧(已去重) + 实时抽帧 (都是**真机画面**, 不是渲染图)
POOL_DEFAULT = os.path.join(ROOT, "data/yolo_annot/dataset/images")
POOL_EXTRA = os.path.join(ROOT, "zmax_data/ss_live")

# 训练用的任务契约 —— 与 scene_vlm.SceneVLM.describe 的提示词**同源**
TASK_SYS = ("你是 Z-MAX 光模块插拔工位的现场视觉助手, 面向「把真实场景标定做对」这件事。")
TASK_USER = ("看这张工位相机图, 只回答 JSON:\n"
             '{"目标可见": true/false, "目标是什么": "…", "目标位置": "画面左上/中上/…", '
             '"在夹爪上吗": true/false/"看不清", "朝向": "…", '
             '"画面质量": {"模糊": bool, "过暗或过曝": bool, "太远或太小": bool, "被遮挡": bool}, '
             '"光照": "…", "背景线索": "你能看到的工装/托盘/标定板等", '
             '"标定建议": "下一步该让操作员做什么(一句话, 具体动哪个动作)"}\n'
             "看不清的字段写 \"看不清\", 不要编。只输出 JSON, 第一个字符必须是 {")
REQUIRED_FIELDS = ["目标可见", "目标是什么", "目标位置", "在夹爪上吗", "画面质量", "标定建议"]

# ── 任务 B: 裁剪目标区域 → 状态判读 (2026-10-08 加) ──
#   动机(实测): 整帧问 deepseek-flash, 与人工真值框一致率只有 0.479 —— 小目标(≈1.3% 像素)在整帧里
#   教师看不见; 而真实链路里**目标框本来就由 L2 给出** ⇒ 让教师看"检测框裁出来的区域"判状态,
#   既是它擅长的活, 也与工程实际口径一致(位置由 L2 管, 状态由 L5 判)。
STATE_SYS = ("你是 Z-MAX 光模块插拔工位的现场视觉助手, 正在看 L2 检测框裁出来的**目标区域特写**。")
STATE_USER = ("这是检测框裁出来的目标区域(光模块/工装件特写)。只回答 JSON:\n"
              '{"目标可见": true/false, "目标是什么": "…", '
              '"在夹爪上吗": true/false/"看不清", "朝向": "…/看不清", '
              '"画面质量": {"模糊": bool, "过暗或过曝": bool, "被遮挡": bool}, '
              '"下一步动作": "给操作员的一句具体指令"}\n'
              "看不清的字段写 \"看不清\", 不要编。只输出 JSON, 第一个字符必须是 {")
STATE_REQUIRED = ["目标可见", "目标是什么", "在夹爪上吗", "画面质量", "下一步动作"]
CROP_DIR = os.path.join(OUT_DIR, "crops")


def crop_by_box(img_path: str, margin: float = 0.35):
    """按人工真值框裁出目标区域 (带边距); 返回 (裁剪图路径, 框像素尺寸) 或 (None, None)"""
    d, f = os.path.split(img_path)
    lab = None
    for split in ("train", "val", "test"):
        if os.path.basename(d) == split:
            q = os.path.normpath(os.path.join(os.path.dirname(d), "..", "labels", split,
                                              os.path.splitext(f)[0] + ".txt"))
            lab = q if os.path.exists(q) else None
            break
    if not lab:
        return None, None
    lines = [l.split() for l in open(lab, encoding="utf-8") if l.strip()]
    if not lines:
        return None, None
    try:
        import numpy as np
        from PIL import Image
        im = Image.open(img_path).convert("RGB")
        W, H = im.size
        xs = []
        for p in lines:
            cx, cy, w, h = (float(v) for v in p[1:5])
            x1, y1 = (cx - w / 2 + w * -margin / 2) * W, (cy - h / 2 - h * margin / 2) * H
            x2, y2 = (cx + w / 2 + w * margin / 2) * W, (cy + h / 2 + h * margin / 2) * H
            xs.append((max(0, x1), max(0, y1), min(W, x2), min(H, y2)))
        bx1 = min(v[0] for v in xs); by1 = min(v[1] for v in xs)
        bx2 = max(v[2] for v in xs); by2 = max(v[3] for v in xs)
        os.makedirs(CROP_DIR, exist_ok=True)
        out = os.path.join(CROP_DIR, os.path.splitext(f)[0] + ".png")
        im.crop((int(bx1), int(by1), int(bx2), int(by2))).save(out)
        return out, (int(bx2 - bx1), int(by2 - by1))
    except Exception:                                                          # noqa: BLE001
        return None, None


def _phash(p: str) -> str:
    """像素级内容指纹 (同画面不同文件名也算重复 → 去重)"""
    try:
        import numpy as np
        from PIL import Image
        im = Image.open(p).convert("L").resize((32, 32))
        a = np.asarray(im, dtype="float32")
        return hashlib.sha1(a.tobytes()).hexdigest()[:16]
    except Exception:                                                          # noqa: BLE001
        return ""


def truth_boxes(img_path: str) -> int:
    """该帧的**人工标注真值**框数 (YOLO txt: 每行一个框)。
    路径规则: …/images/<split>/x.jpg → …/labels/<split>/x.txt (找不到就返回 -1 = 无真值)"""
    d, f = os.path.split(img_path)
    for split in ("train", "val", "test"):
        if os.path.basename(d) == split:
            lab = os.path.join(os.path.dirname(d), "..", "labels", split, os.path.splitext(f)[0] + ".txt")
            lab = os.path.normpath(lab)
            if os.path.exists(lab):
                n = 0
                for line in open(lab, encoding="utf-8"):
                    if line.strip() and len(line.split()) >= 5:
                        n += 1
                return n
            return -1
    return -1


def _valid(j, required=None) -> tuple[bool, str]:
    if not isinstance(j, dict):
        return False, "不是 JSON 对象"
    miss = [k for k in (required or REQUIRED_FIELDS) if k not in j]
    if miss:
        return False, "缺字段: " + ",".join(miss[:3])
    return True, ""


def pool_files(pools) -> list[str]:
    """收集帧 (⚠️ 递归: 真机标注帧在 images/train、images/val 子目录里, 只 glob 顶层会漏掉 55 张)"""
    fs = []
    for d in pools:
        for ext in ("png", "jpg", "jpeg"):
            fs += glob.glob(os.path.join(d, "**", "*." + ext), recursive=True)
    return sorted(set(fs))


def load_done() -> dict:
    """已采样本: phash → 记录 (断点续跑)"""
    done = {}
    if os.path.exists(ALL_JSONL):
        for l in open(ALL_JSONL, encoding="utf-8"):
            if l.strip():
                try:
                    r = json.loads(l)
                except Exception:                                              # noqa: BLE001
                    continue
                if r.get("phash"):
                    done[r["phash"]] = r
    return done


def _log_call_crop(crop, r, src_img, bwh):
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "teacher_calls.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "task": "state", "crop": crop, "src_img": src_img,
                                "box_wh": bwh, "ok": bool(r.get("ok")), "src": r.get("src"),
                                "latency_ms": r.get("latency_ms"), "why": r.get("why"),
                                "json": r.get("json")}, ensure_ascii=False) + "\n")
    except Exception:                                                          # noqa: BLE001
        pass


def teach_one(path: str, timeout: float, teacher: str = "", task: str = "describe") -> dict:
    """一帧 → 教师判读 (真调用; 失败如实返回 why, 不编样本)"""
    from lerobot.policies.left_right.state_space.scene_vlm import SceneVLM
    t0 = time.time()
    src_img = path
    try:
        vlm = SceneVLM.get()
        if not vlm.url:
            return {"phash": _phash(path), "image": path, "ok": False,
                    "why": "无教师通道 (未配 DEEPSEEK_API_KEY, 本地 worker 不当教师)"}
        if task == "state":
            crop, bwh = crop_by_box(path)
            if not crop:
                return {"phash": _phash(path), "image": path, "ok": False,
                        "why": "无真值框, 状态任务不适用"}
            r = vlm.ask(crop, STATE_USER, system=STATE_SYS, max_tokens=300)
            r["json"] = None
            if r.get("ok"):
                from lerobot.policies.left_right.state_space.scene_vlm import _json_from
                r["json"] = _json_from(r.get("text"))
                r["ok"] = bool(r["json"])
            _log_call_crop(crop, r, path, bwh)
            path = crop
        else:
            r = vlm.describe(path)
    except Exception as e:                                                     # noqa: BLE001
        return {"phash": _phash(path), "image": path, "ok": False,
                "why": f"{type(e).__name__}: {e}"[:160]}
    j = r.get("json")
    ok, why = _valid(j, STATE_REQUIRED if task == "state" else None)
    if not ok and not r.get("ok"):
        why = str(r.get("why") or why)[:120]      # 调用本身失败时, 报真因(别用"不是 JSON 对象"掩盖)
    return {"phash": _phash(path), "image": os.path.abspath(path), "n_box": truth_boxes(path),
            "task": task, "src_img": os.path.abspath(src_img),
            "ok": bool(ok and j),
            "why": why or r.get("why") or "", "json": j if ok else None,
            "answer": json.dumps(j, ensure_ascii=False) if ok else None,
            "src": r.get("src"), "teacher": teacher or r.get("src"),
            "latency_ms": r.get("latency_ms") or int((time.time() - t0) * 1000),
            "ts": time.time()}


def cmd_build(a) -> int:
    if getattr(a, "key_env", ""):
        _k = os.environ.get(a.key_env, "")
        if _k:
            os.environ["SS_VLM_KEY"] = _k
            print(f"🔑 已注入 SS_VLM_KEY (来自 env {a.key_env}, 长度 {len(_k)})")
        else:
            print(f"⚠️ env {a.key_env} 为空 ⇒ 显式通道会退化成 rule 回退")
    pools = a.pool.split(",") if a.pool else [POOL_DEFAULT, POOL_EXTRA]
    files = pool_files(pools)
    done = load_done()
    todo_all = []
    seen_hash = set() if a.force else set(done)
    dup = 0
    for p in files:
        h = _phash(p)
        if not h:
            continue
        if h in seen_hash:
            dup += 1
            continue
        seen_hash.add(h)
        todo_all.append(p)
    if a.force:
        for k, r in done.items():
            _ = k
    print(f"📦 帧池 {len(files)} 张 (去重丢弃 {dup}) · 已有样本 {len(done)} 条 · 待采 {len(todo_all)} 张")
    if a.limit and len(todo_all) > a.limit:
        todo_all = todo_all[:a.limit]
        print(f"   本批限量 {len(todo_all)} 张 (--limit {a.limit})")
    if not todo_all:
        print("✅ 没有新帧要采 (断点续跑: 直接 stat)")
        return cmd_stat(a)

    os.makedirs(OUT_DIR, exist_ok=True)
    ok_n = bad_n = 0
    t0 = time.time()
    f = open(ALL_JSONL, "a", encoding="utf-8")
    try:
        with cf.ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
            futs = {ex.submit(teach_one, p, a.timeout, a.teacher, a.task): p for p in todo_all}
            for i, fu in enumerate(cf.as_completed(futs), 1):
                r = fu.result()
                if r.get("ok"):
                    ok_n += 1
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    f.flush()
                    flag = "✅"
                else:
                    bad_n += 1
                    flag = "✗"
                if i % 5 == 0 or i == len(todo_all):
                    el = time.time() - t0
                    eta = (el / i) * (len(todo_all) - i)
                    print(f"   [{i}/{len(todo_all)}] {flag} ok={ok_n} 丢弃={bad_n} "
                          f"用时 {el:.0f}s ETA {eta:.0f}s · {r.get('why', '')[:60]}")
    finally:
        f.close()
    el = time.time() - t0
    man = {"ts": time.time(), "pools": pools, "workers": a.workers, "limit": a.limit,
           "frames_total": len(files), "dup_dropped": dup, "asked": len(todo_all),
           "ok": ok_n, "dropped": bad_n, "secs": round(el, 1),
           "src": "SceneVLM.describe (教师通道)"}
    with open(MANIFEST, "w", encoding="utf-8") as mf:
        json.dump(man, mf, ensure_ascii=False, indent=1)
    print(f"⏹ 本批结束: 合法 {ok_n} / 丢弃 {bad_n} · 用时 {el:.0f}s · manifest {os.path.relpath(MANIFEST, ROOT)}")
    return cmd_stat(a)


def cmd_stat(a) -> int:
    done = load_done()
    recs = [r for r in done.values() if r.get("ok")]
    if not recs:
        print("⚠️ 还没有合法样本 (先 build)")
        return 1
    # ⚠️ 教师 × 标注真值 交叉核对 (2026-10-08 实测): 有真值框的帧上教师仍可能报"看不清"
    #   ⇒ 那种样本会把模型教会"看不见目标", 属**坏样本**, 必须丢; 一致率如实报数。
    # 按教师分组的一致率 (教师 A/B 仲裁: 谁与人工真值更一致就用谁当教师)
    by_teacher = {}
    for r in recs:
        # ⚠️ state 任务的样本图是**裁剪图**, 真值框在原始帧上 ⇒ 真值一律按 src_img 查
        k = truth_boxes(r.get("src_img") or r["image"])
        r["n_box"] = k
        if k < 0:
            continue
        t = r.get("teacher") or r.get("src") or "?"
        d = by_teacher.setdefault(t, {"n": 0, "agree": 0})
        d["n"] += 1
        if (k > 0) == ((r.get("json") or {}).get("目标可见") is True):
            d["agree"] += 1
    print("🧪 教师与人工真值一致率 (仲裁用):")
    best_t, best_rate = None, -1.0
    for t, d in sorted(by_teacher.items(), key=lambda kv: -kv[1]["agree"] / max(1, kv[1]["n"])):
        rt = d["agree"] / max(1, d["n"])
        print(f"   {t:28} {d['agree']}/{d['n']} = {rt:.3f}")
        if rt > best_rate:
            best_t, best_rate = t, rt
    if getattr(a, "teacher_filter", ""):
        cand = [r for r in recs if (r.get("teacher") or r.get("src")) == getattr(a, "teacher_filter", "")]
        print(f"   选用教师: {a.teacher_filter} ({len(cand)} 条)")
    else:
        cand = [r for r in recs if (r.get("teacher") or r.get("src")) == best_t] if best_t else recs
        if best_t:
            print(f"   选用教师: {best_t} (最高一致率 {best_rate:.3f})")
    # 同一帧多教师时只留选用教师那条 (避免同帧多答案混进训练)
    dedup = {}
    for r in cand:
        dedup[r["phash"]] = r
    keep, drop_conflict, no_truth = [], [], 0
    for k, r in sorted(dedup.items()):
        if not r.get("ok"):
            continue
        # ⚠️ 旧样本写入时还没 n_box 字段 ⇒ 现场从图片路径重算 (不依赖历史记录)
        nb = truth_boxes(r.get("src_img") or r["image"])
        vis = (r.get("json") or {}).get("目标可见")
        if nb == -1:
            no_truth += 1
            keep.append(r)                       # 无标注真值 (实时帧): 只能信教师, 单列计数
        elif nb > 0 and vis is True:
            keep.append(r)                       # 有框 + 教师确实看到 → 正样本 ✓
        elif nb == 0 and vis is False:
            keep.append(r)                       # 无框 + 教师说看不到 → 真负样本 ✓
        else:
            drop_conflict.append({"image": os.path.basename(r["image"]), "n_box": nb, "教师可见": vis})
    # 按帧划分 train/val (同帧不跨集) —— 只在 keep 里划
    keys = sorted(r["phash"] for r in keep)
    n_val = max(1, int(len(keys) * 0.25))
    val_keys = set(keys[-n_val:])
    tr = [r for r in keep if r["phash"] not in val_keys]
    va = [r for r in keep if r["phash"] in val_keys]
    if drop_conflict:
        print(f"⚠️ 丢弃与标注真值冲突的样本 {len(drop_conflict)} 条 (有框却说看不清→会教模型变瞎):")
        for d in drop_conflict[:5]:
            print(f"     - {d['image']} 真值框 {d['n_box']} 教师可见={d['教师可见']}")
    for name, rows in (("train", tr), ("val", va)):
        p = os.path.join(OUT_DIR, f"{name}.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                _st = (r.get("task") or "describe") == "state"
                f.write(json.dumps({"image": r["image"],
                                    "system": STATE_SYS if _st else TASK_SYS,
                                    "user": STATE_USER if _st else TASK_USER,
                                    "task": "state" if _st else "describe",
                                    "answer": r["answer"], "phash": r["phash"],
                                    "teacher_src": r.get("src")}, ensure_ascii=False) + "\n")
        print(f"📄 {os.path.relpath(p, ROOT)}: {len(rows)} 条")
    srcs = {}
    for r in recs:
        srcs[r.get("src")] = srcs.get(r.get("src"), 0) + 1
    lat = [r.get("latency_ms") for r in recs if r.get("latency_ms")]
    for r in recs:
        if r.get("n_box") in (None, -1):
            r["n_box"] = truth_boxes(r.get("src_img") or r["image"])
    with_truth = [r for r in recs if r.get("n_box", -1) >= 0]
    agree = sum(1 for r in with_truth
                if ((r["n_box"] > 0) == ((r.get("json") or {}).get("目标可见") is True)))
    rate = round(agree / max(1, len(with_truth)), 3)
    print(f"📊 合法样本 {len(recs)} · 教师来源 {srcs} · 延迟中位 {sorted(lat)[len(lat)//2] if lat else '-'}ms")
    print(f"🎯 教师 vs 人工标注真值一致率 {agree}/{len(with_truth)} = {rate} "
          f"(无真值帧 {no_truth} 条另计) · 冲突丢弃 {len(drop_conflict)} 条")
    print("   划分: train {} / val {} (按帧, 同帧不跨集)".format(len(tr), len(va)))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="L5 · VLM 蒸馏数据通道")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="采一批真帧 → 真教师 → 合法 JSON 样本")
    b.add_argument("--pool", default="", help="逗号分隔的帧目录 (默认: 真机标注帧 + 实时抽帧)")
    b.add_argument("--limit", type=int, default=60)
    b.add_argument("--workers", type=int, default=4)
    b.add_argument("--timeout", type=float, default=60.0)
    b.add_argument("--force", action="store_true",
                   help="忽略 phash 去重, 对同一批帧重问 (用于**教师 A/B 对照**; 结果按 teacher 分组)")
    b.add_argument("--teacher", default="", help="教师标签 (写进样本 teacher 字段, 便于分组统计)")
    b.add_argument("--task", default="state", choices=["state", "describe"],
                   help="state=按真值框裁剪后判状态(默认, 实测教师更可靠); describe=整帧场景描述")
    b.add_argument("--key-env", default="", help="从该环境变量名取 VLM key 并注入 SS_VLM_KEY "
                   "(进程内读取, 密钥不进命令行也不打印 —— 安全层会屏蔽 shell 里的密钥展开)")
    st = sub.add_parser("stat", help="统计 + 重划 train/val (按教师分组算一致率)")
    st.add_argument("--teacher-filter", default="", help="只用该教师标签的样本建集 (默认自动选一致率最高的)")
    a = ap.parse_args()
    if a.cmd == "build":
        return cmd_build(a)
    return cmd_stat(a)


if __name__ == "__main__":
    sys.exit(main())
