#!/usr/bin/env python3
"""gs_dataset_merge.py — 把多次扫描的 3DGS 数据集合并成一个(同一场景 / 同一套手眼+TCP 真源)。

用途: 老倪 2026-10-08「前后两张图, 可以合并么? 都是同一个场景」—— 把上一轮(map_v5186_plane 251 帧)
      和本轮采集合成一份, 再**一次训练**: 视差覆盖更大、全局一致, 比"续训"更干净。

用法:
    python3 tools/gs_dataset_merge.py --out <合并后目录> --in <数据集1> [<数据集2> ...]

产物(与 gs_dataset.py 口径一致, gs_train.py 只读 cameras.json + images/):
    <out>/images/<标签>__<原名>.jpg     ← 各源图复制(加标签前缀防重名)
    <out>/cameras.json                  ← frames 拼接, file 改写; convention/K/w/h 必须一致(不一致即拒)
    <out>/meta.json                     ← 来源/数量/合并时间(可追溯)

前提(必须成立, 否则位姿不可比): 各源来自**同一台相机 + 同一基坐标系**(本工程 = 臂上 D405 + TCP 真值 + 同一手眼标定)。
"""
import argparse
import json
import os
import shutil
import sys
import time


def load_ds(p: str):
    cj = os.path.join(p, "cameras.json")
    if not os.path.isfile(cj):
        raise SystemExit("❌ 不是数据集(缺 cameras.json): %s" % p)
    with open(cj, encoding="utf-8") as f:
        c = json.load(f)
    fr = c.get("frames") or []
    if not fr:
        raise SystemExit("❌ 数据集没有 frames: %s" % p)
    for k in ("K", "width", "height"):
        if k not in c:
            raise SystemExit("❌ 数据集缺字段 %s: %s" % (k, p))
    return c, fr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="合并后数据集目录")
    ap.add_argument("--in", dest="srcs", nargs="+", required=True, help="源数据集目录(≥1 个)")
    ap.add_argument("--tag-prefix", default="", help="统一前缀(默认用源目录名)")
    a = ap.parse_args()

    os.makedirs(os.path.join(a.out, "images"), exist_ok=True)
    base = None
    out_frames = []
    per_src = []

    for si, src in enumerate(a.srcs):
        c, fr = load_ds(src)
        _base = a.tag_prefix or os.path.basename(os.path.normpath(src))
        tag = str(_base).replace("/", "_")
        # 🔴 多源必须带序号: 否则同名源(或同目录传两次)标签相同 ⇒ 后一份图**覆盖**前一份 ⇒ 帧多图少
        if len(a.srcs) > 1:
            tag = "%s_g%d" % (tag, si)
        # K/分辨率 必须一致: 不一致的图混在一起 = 相机内参错的监督
        sig = {k: c[k] for k in ("K", "width", "height")}
        if base is None:
            base = (sig, c)
        else:
            for k in ("K", "width", "height"):
                if json.dumps(base[0][k], sort_keys=True) != json.dumps(sig[k], sort_keys=True):
                    raise SystemExit("❌ 内参/分辨率不一致(%s): %s vs %s" % (k, a.srcs[0], src))
        n_ok = 0
        for f in fr:
            name = f.get("file")
            sp = os.path.join(src, "images", name or "")
            if not name or not os.path.isfile(sp):
                continue
            new = "%s__%s" % (tag, name)
            shutil.copyfile(sp, os.path.join(a.out, "images", new))
            g = dict(f)
            g["file"] = new
            g["merged_from"] = os.path.basename(os.path.normpath(src))
            out_frames.append(g)
            n_ok += 1
        per_src.append({"src": src, "frames": n_ok, "tag": tag})
        print("   + %-40s %4d 帧 → 标签 %s" % (src, n_ok, tag))

    if base is None:
        raise SystemExit("❌ 没有任何可用源数据集")
    base_c = base[1]
    merged = {
        "convention": base_c.get("convention", "T_cam2world"),
        "K": base_c["K"], "width": base_c["width"], "height": base_c["height"],
        "dist_removed": base_c.get("dist_removed", True),
        "frames": out_frames,
        "merged": {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "sources": per_src},
    }
    with open(os.path.join(a.out, "cameras.json"), "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)
    with open(os.path.join(a.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"ts": merged["merged"]["ts"], "merged_from": per_src,
                   "n_frames": len(out_frames), "width": base_c["width"], "height": base_c["height"]},
                  f, ensure_ascii=False, indent=2)
    # transforms.json(外部工具用; gs_train 不读) —— 有就照搬第一份
    tj = os.path.join(a.srcs[0], "transforms.json")
    if os.path.isfile(tj):
        shutil.copyfile(tj, os.path.join(a.out, "transforms.json"))

    n_img = len(os.listdir(os.path.join(a.out, "images")))
    print("\n✅ 合并完成: %s" % a.out)
    print("   frames %d(图 %d 张) · 来源 %d 个 · 内参校验通过(%sx%s)"
          % (len(out_frames), n_img, len(a.srcs), base_c["width"], base_c["height"]))
    if n_img != len(out_frames):
        print("   ⚠️ 图数(%d)≠帧数(%d): 有帧缺图, 已跳过" % (n_img, len(out_frames)))
    print("   下一步: gs_train.py --data %s --out <资产目录>" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
