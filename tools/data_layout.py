#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data/ 目录分区迁移 —— 老倪 (2026-10-09):
「将总工程文件 zmax_space.proj 放在 /home/ubuntu/zmax/data/database；所有工程文件和数据库文件都放在这里；
  你可以设计一下路径结构；继续整合所有数据文件，现在的数据太杂乱了。」

设计: data/ 顶层的 ~60 个条目收成 6 个桶 + README
  data/database/  🗄 工程文件 + 数据库 (唯一; .proj / .db / archive/; 改数事件=库 param_events 表)
  data/skills/    💪 技能库 (L2 原子技能注册表 / 示教点 / 肌肉记忆 / 变更日志)   [原地, 名字已达标]
  data/scene/     🎬 场景 · 叠加 · 感知 (overlay_spec / cam_calib / traj_display / scene_state.json)
  data/memory/    🧠 记忆层 (memory_layers / shared / macro / assembly / muscle / intact / insert_position)
  data/calib/     📐 标定 (handeye / selfcal / aoi_caliber_bench)
  data/datasets/  📊 数据集 (yolo_* / ss_* / metaworld_* / smolvla_* / l4_mani / points / mcap / orin_* / *.npz / *.mp4)

纪律:
  1. --dry 先看清单 (file:line + 每条改写), 不落盘。
  2. --apply 前先 tar 备份 (zmax_data/backups/data_layout_pre_<ts>.tar.gz)。
  3. 只改**可执行代码区** (tools/ src/ config/ flows/ 顶层), 逐条排除:
     docs/ reports/ zmax_data/ external/ .git/ 以及任何 _archive/ (历史快照=证据, 不许篡改)。
  4. 🔴 排除 `lerobot-smolvla-lew/data/` 命中的行 —— 那是**别的仓库**的 data 目录, 改了必错。
  5. 三种写法一起改: `data/<name>` · `"data", "<name>"` · `'data', '<name>'`。
  6. 移动用 mv (同盘 rename, 数据不动); 软链保持指向原目标 (不改 payload)。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# ── 迁移映射 (顶层名 → 桶) ────────────────────────────────────────────────
MAPPING = {}


def _add(bucket, names):
    for n in names:
        MAPPING[n] = bucket


_add("datasets", [
    "yolo_peg", "yolo_peg_v2", "yolo_peg_dr", "yolo_peg_drmix", "yolo_peg_depth", "yolo_peg_holdout",
    "yolo_annot", "yolo_annot_sim", "yolo_annot_usbcam", "yolo_annot_l5slots", "yolo_annot_l5vlm",
    "yolo_aoi_annot",
    "ss_mw_lerobot", "ss_mw_lerobot_v2", "ss_mw_lerobot_v3", "ss_mw_lerobot_v3w", "ss_mw_lerobot_v4w",
    "ss_mw_raw", "ss_mw_ss", "ss_simreal_raw", "ss_insert", "ss_insert_lerobot",
    "ss3d_l3_full_insert_pull_aoi_104.mp4",
    "metaworld_peg", "metaworld_peg_v7",
    "smolvla_peg_full", "smolvla_peg_img", "smolvla_peg_v8", "smolvla_peg_v8_d1",
    "l4_mani", "points", "mcap", "orin_6d", "orin_live",
    "real_yolo_perception_100.mp4", "real_yolo_perception_104.mp4",
    "intent_pairs_v1.npz", "manifold_geo_v1.npz", "stop_signal_v1.npz", "target_decoder_data.npz",
    "su2_mapping.json", "sam3_finetune_cache", "l5_vlm_sft",
])
_add("memory", [
    "memory_layers.json", "memory_layers.json.bak-20260915",
    "shared_memory.json", "shared_memory.json.bak_0922",
    "macro_memory.json", "assembly_memory.json", "muscle_memory.json",
    "intact_robot_state.json", "insert_position.json",
])
_add("scene", ["scene_state.json"])
_add("calib", ["handeye", "selfcal", "aoi_caliber_bench"])

BUCKETS = ["database", "skills", "scene", "memory", "calib", "datasets"]

SCAN_DIRS = ["tools", "src", "config"]
SCAN_GLOBS = (".py", ".sh", ".json", ".yaml", ".yml", ".txt", ".md")
SKIP_DIR_PARTS = ("/_archive/", "/docs/", "/reports/", "/zmax_data/", "/external/", "/.git/",
                  "/backups/", "/node_modules/")
FOREIGN = "lerobot-smolvla-lew/data/"          # 🔴 别的仓库的 data 目录, 一律不碰
CANVAS_FILES = ("flows/state_space_obs.json", "src/lerobot/engineering/flows/state_space_obs.json")


def _iter_files():
    self_path = os.path.abspath(__file__)
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        for cur, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", ".git", "_archive", "node_modules")]
            rel_cur = "/" + os.path.relpath(cur, ROOT).replace(os.sep, "/") + "/"
            if any(p in rel_cur for p in SKIP_DIR_PARTS):
                continue
            for f in files:
                if f.endswith(SCAN_GLOBS):
                    p = os.path.join(cur, f)
                    if os.path.abspath(p) == self_path:      # 迁移器自身不改写自己
                        continue
                    yield p
    # flows/ 顶层 (画布 + 顶层 json), 不含 _archive
    fd = os.path.join(ROOT, "flows")
    if os.path.isdir(fd):
        for f in os.listdir(fd):
            p = os.path.join(fd, f)
            if os.path.isfile(p) and f.endswith((".json", ".py", ".sh")):
                yield p


def _patterns():
    """(编译好的正则, 替换串, 说明) —— 长名优先, 防止 data/scene 吃掉 data/scene_state.json"""
    pats = []
    for name in sorted(MAPPING, key=len, reverse=True):
        b = MAPPING[name]
        esc = re.escape(name)
        # ① 斜杠写法: data/<name>  后面不能再跟名字字符
        pats.append((re.compile(r"(?<![A-Za-z0-9_./-])data/" + esc + r"(?![A-Za-z0-9_.\-])"),
                     "data/%s/%s" % (b, name), "slash"))
        # ② os.path.join(..., "data", "<name>") 逗号写法 (单/双引号)
        for q in ('"', "'"):
            pats.append((re.compile(re.escape(q + "data" + q) + r"\s*,\s*" + re.escape(q + name + q)),
                         q + "data" + q + ", " + q + b + q + ", " + q + name + q, "join"))
    return pats


def scan():
    pats = _patterns()
    hits = []
    for p in _iter_files():
        try:
            txt = open(p, encoding="utf-8").read()
        except Exception:                                                        # noqa: BLE001
            continue
        if "data/" not in txt and '"data"' not in txt and "'data'" not in txt:
            continue
        lines = txt.split("\n")
        for i, ln in enumerate(lines, 1):
            if FOREIGN in ln:
                continue
            for rx, rep, kind in pats:
                if rx.search(ln):
                    hits.append({"file": os.path.relpath(p, ROOT), "line": i, "kind": kind,
                                 "before": ln.strip()[:160],
                                 "after": rx.sub(rep, ln).strip()[:160]})
                    break
    return hits


def apply_rewrite(hits):
    by_file = {}
    for h in hits:
        by_file.setdefault(h["file"], []).append(h)
    pats = _patterns()
    changed = []
    for rel, hs in by_file.items():
        p = os.path.join(ROOT, rel)
        txt = open(p, encoding="utf-8").read()
        lines = txt.split("\n")
        n = 0
        for i, ln in enumerate(lines):
            if FOREIGN in ln:
                continue
            orig = ln
            for rx, rep, _k in pats:
                ln = rx.sub(rep, ln)
            if ln != orig:
                lines[i] = ln
                n += 1
        if n:
            open(p, "w", encoding="utf-8").write("\n".join(lines))
            changed.append({"file": rel, "lines": n})
    return changed


def plan_moves():
    moves = []
    for name, bucket in MAPPING.items():
        src = os.path.join(DATA, name)
        if not os.path.exists(src) and not os.path.islink(src):
            continue
        moves.append((name, bucket, src, os.path.join(DATA, bucket, name)))
    return moves


def do_moves(moves):
    done = []
    for name, bucket, src, dst in moves:
        bd = os.path.dirname(dst)
        os.makedirs(bd, exist_ok=True)
        if os.path.lexists(dst):
            print("  ⚠️ 目标已存在, 跳过: %s" % dst)
            continue
        if os.path.islink(src):
            tgt = os.readlink(src)
            os.remove(src)
            os.symlink(tgt, dst)                 # 软链原样搬到桶里 (payload 不动)
        else:
            shutil.move(src, dst)                # 同盘 rename, 数据不动
        done.append({"name": name, "bucket": bucket, "from": os.path.relpath(src, ROOT),
                     "to": os.path.relpath(dst, ROOT), "is_link": os.path.islink(dst)})
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-move", action="store_true")
    a = ap.parse_args()
    if not (a.dry or a.apply):
        ap.error("要 --dry 或 --apply")

    hits = scan()
    moves = plan_moves()
    print("=" * 78)
    print("改写命中: %d 行 / %d 个文件" % (len(hits), len(set(h["file"] for h in hits))))
    byd = {}
    for h in hits:
        byd[h["file"].split("/")[0] + "/" + (h["file"].split("/")[1] if "/" in h["file"] else "")] = \
            byd.get(h["file"].split("/")[0] + "/" + (h["file"].split("/")[1] if "/" in h["file"] else ""), 0) + 1
    for k, v in sorted(byd.items(), key=lambda x: -x[1]):
        print("   %-28s %d" % (k, v))
    print("-" * 78)
    print("搬迁: %d 项" % len(moves))
    for name, bucket, src, dst in sorted(moves, key=lambda x: x[1]):
        kind = "LINK" if os.path.islink(src) else ("DIR " if os.path.isdir(src) else "FILE")
        sz = subprocess.run(["du", "-sh", src], capture_output=True, text=True).stdout.split("\t")[0]
        print("   %-5s %-40s → %s/  (%s)" % (kind, name, bucket, sz))
    if a.dry:
        print("=" * 78)
        for h in hits[:80]:
            print("%s:%s [%s]\n   - %s\n   + %s" % (h["file"], h["line"], h["kind"], h["before"], h["after"]))
        if len(hits) > 80:
            print("... 另有 %d 行 (见 --apply 的 manifest)" % (len(hits) - 80))
        return 0

    # ── apply ──
    ts = time.strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(ROOT, "zmax_data", "backups")
    os.makedirs(bdir, exist_ok=True)
    tb = os.path.join(bdir, "data_layout_pre_%s.tar.gz" % ts)
    files = sorted(set(h["file"] for h in hits))
    subprocess.run(["tar", "-czf", tb] + files, cwd=ROOT, check=False)
    print("备份: %s (%d 文件, %.1f MB)" % (tb, len(files), os.path.getsize(tb) / 1e6))

    changed = apply_rewrite(hits)
    print("改写完成: %d 个文件" % len(changed))
    done = [] if a.no_move else do_moves(moves)
    print("搬迁完成: %d 项" % len(done))

    man = os.path.join(bdir, "DATA_LAYOUT_MANIFEST_%s.jsonl" % ts)
    with open(man, "w", encoding="utf-8") as f:
        for d in done:
            f.write(json.dumps({"kind": "move", **d}, ensure_ascii=False) + "\n")
        for c in changed:
            f.write(json.dumps({"kind": "rewrite", **c}, ensure_ascii=False) + "\n")
    print("清单: %s" % man)
    return 0


if __name__ == "__main__":
    sys.exit(main())
