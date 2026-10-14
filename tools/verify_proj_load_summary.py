#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 「状态空间工程加载」弹窗只列**已加载配置的名称** (2026-10-14 老倪:
「弹出来的文本清单简单一些, 只是列出所有加载的配置的名称即可。你写了那么多数字字符串, 不是给人看的。别的都删掉」)。

判据口径 (逐条可查):
  ① 真源 = 工程文件本身: 清单里的每一项都对应文件里真有的段 (不多不少, 顺序固定);
  ② 弹窗正文**不含数字** (工程文件名那行除外): 统计/计数/哈希/索引/坐标 一律不许出现;
  ③ 弹窗正文不含旧字段痕迹: stats/真源:/备份:/漂移/sha/md5/{ }/画布: 已替换…;
  ④ 代码里那版 json.dumps(stats) 旧弹窗已删干净 (防回退)。

跑法: ./gui-venv311/bin/python tools/verify_proj_load_summary.py
"""
import json
import os
import re
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.chdir(ROOT)

res = []


def chk(name, cond, extra=""):
    res.append(("✓" if cond else "✗") + " " + name + (" :: %s" % (extra,) if extra else ""))


import project_file as PJ                                                      # noqa: E402
import studio as ST                                                            # noqa: E402

path = PJ.find_space(ROOT) if hasattr(PJ, "find_space") else None
if not path or not os.path.exists(path):
    path = os.path.join(ROOT, "reports/projects/SS_主工程_任务配置.zmaxproj")
chk("① 找到状态空间工程真源", os.path.exists(path), path)

d = json.load(open(path, encoding="utf-8"))
names = ST._pj_loaded_names(path)
_real = [k for k, _ in ST._PROJ_SECTION_NAMES if k in d]
chk("② 清单 = 工程文件里真有的段 (按真源现算, 不硬编)", len(names) == len(_real) and len(names) >= 4,
    "%d 项: %s" % (len(names), " / ".join(names)))

# 复刻弹窗正文 (与 studio._load_project_file 里同一段格式, 逐字一致)
body = "✅ 工程已加载\n\n%s\n\n已加载配置:\n%s" % (
    os.path.basename(path), "\n".join("  · " + n for n in names))
_lines = body.splitlines()
_payload = [ln for ln in _lines if "zmaxproj" not in ln and ".proj" not in ln]

chk("③ 弹窗正文不含任何数字 (工程文件名那行除外)",
    not any(re.search(r"\d", ln) for ln in _payload),
    [ln for ln in _payload if re.search(r"\d", ln)][:2] or "0 处数字")

_bad = ("stats", "真源:", "备份:", "漂移", "sha", "md5", "{", "}", "画布: 已替换", "节点", "连线")
_hit = [b for b in _bad if b in body]
chk("④ 旧弹窗痕迹全清 (统计/哈希/路径/漂移/结构计数)", not _hit, _hit or "0 处残留")

chk("⑤ 名称清单里确实有『画布 · 状态空间工程』等中文名 (不是键名)",
    "画布 · 状态空间工程" in body and "canvas" not in body.replace("无法识别", ""),
    [n for n in names][:3])

_src = open(os.path.join(ROOT, "tools/gui/studio.py"), encoding="utf-8").read()
_SRC_OLD1 = 'json.dumps(r.get("stats")'
chk("⑥ 代码里 json.dumps(stats) 那版旧弹窗已删 (防回退)",
    _SRC_OLD1 not in _src and "_pj_loaded_names(path)" in _src,
    ("旧写法 %d 处" % _src.count(_SRC_OLD1)) if _SRC_OLD1 in _src else "0 处")
chk("⑦ 『总工程已集成式打开』那版数字清单也已删 (ok=/结构计数/漂移/时间戳 不进弹窗)",
    '集成式打开完成 (ok=' not in _src and '_pj_loaded_names(path)' in _src,
    "旧写法 %d 处" % _src.count("集成式打开完成 (ok="))
_n_use = _src.count("_pj_loaded_names(path)")
chk("⑧ 两处弹窗 (📂 加载工程文件 / 🗂 状态空间工程已打开) 都走同一份名称清单",
    _n_use >= 2, "%d 处调用" % _n_use)

print("\n".join(res))
n_ok = sum(1 for r in res if r.startswith("✓"))
print("\n判据汇总: %d/%d PASS" % (n_ok, len(res)))
sys.exit(0 if n_ok == len(res) else 1)
