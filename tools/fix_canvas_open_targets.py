#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🛠 画布「右键打开源代码」全量对齐 (老倪 2026-11-15)

判据: 右键必须落到**算法本体的入口函数**, 不是转发壳、不是 library.py 包装 (除非算法真就写在那)。
候选按可信度排序, 命中即停:
  ① 画布节点原 params.source (工程师手工标的算法位置, 支持 "path · sym" / "path::sym")
  ② library._EXTERNAL_LOC
  ③ 注册表函数的真文件 (优先非 library.py)
  ④ 注册表 file/line 元数据
符号解析: 给定符号 → 找 def/class; 没给 → 按入口名 run/main/step/plant/limit/compute/predict/plan/collect
顺序找; 再不行取首函数。所有落点都要求文件真存在 + 解开软链 + ≥20 行。

用法: python3 tools/fix_canvas_open_targets.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
CANVAS = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
MIN_LINES = 20

ENTRY = ("run", "main", "step", "plant", "limit", "compute", "predict", "plan",
         "collect", "sync_to_macro", "dispatch", "__call__", "apply", "act")

# 组/行节点 (画布上只是分组, 没有独立函数) → 语义上归属的模块
GROUP = {
    "row_mem_l2": ("src/lerobot/memory/mem_nodes.py", "node_ss_mem_l2"),
    "row_mem_l3": ("src/lerobot/memory/mem_nodes.py", "node_ss_mem_l3"),
    "row_mem_l4": ("src/lerobot/memory/mem_nodes.py", "node_ss_mem_l4"),
    "ssbg_skill": ("src/lerobot/policies/left_right/state_space/skills/atomic_skills.py", None),
    "ssbg8": ("src/lerobot/verification/verification_layer.py", None),
    "ssbg9": ("tools/gui/ss_bypass_view.py", None),
    "ssbg_vlm": ("src/lerobot/policies/smolvla_lew/vlm_encoder.py", None),
    "ssbg_data": ("src/lerobot/middleware/nodes/impl/data.py", "node_metaworld_data"),
    "ssbg7": ("src/lerobot/manifold/manifold_engine.py", None),
    "ssbg0": ("src/lerobot/perception/yolo.py", None),
    "ssff_hist": ("src/lerobot/middleware/nodes/impl/ss_ff_hist.py", "node_ss_ff_hist"),
    "ss3d_view": ("src/lerobot/middleware/nodes/impl/ss_3d_view.py", "node_ss_3d_view"),
    "ssbg5": ("src/lerobot/policies/left_right/state_space/planner.py", "class TaskPlanner"),
    # 这几个算法就写在 library.py 里 (内联实现, 不是包装), 必须按真函数名定位
    "sscap": ("src/lerobot/engineering/nodes/library.py", "node_ss_cap"),
    "ss_l5": ("src/lerobot/engineering/nodes/library.py", "node_l5_loop"),
    "n_realscene": ("src/lerobot/engineering/nodes/library.py", "node_realscene_live"),
    "n_l2_muscle": ("src/lerobot/engineering/nodes/library.py", "node_n_l2_muscle"),
    "ssmode": ("src/lerobot/engineering/nodes/library.py", "node_mode_switch"),
    "ssvideo": ("src/lerobot/engineering/nodes/library.py", "node_ss_scope"),
    "ssvideo2": ("src/lerobot/engineering/nodes/library.py", "node_ss_video"),
    "n_intent_bundle": ("src/lerobot/memory/mem_nodes.py", "node_ss_intent_bundle"),
    "n_skill_dict": ("src/lerobot/memory/mem_nodes.py", "node_ss_skill_dict"),
    "n_mem_links": ("src/lerobot/memory/mem_nodes.py", "node_ss_mem_links"),
}


def norm(p):
    if not p:
        return None
    p = p.strip().strip("`").strip()
    for pre in ("/home/ubuntu/zmax/", "src/lerobot/", "lerobot/"):
        if p.startswith(pre):
            p = p[len(pre):]
            break
    for base in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "src/lerobot")):
        q = os.path.join(base, p)
        if os.path.isfile(os.path.realpath(q)):
            return os.path.realpath(q)
    return None


def split_src(s):
    """"path.py · sym" / "path.py::sym" / "path.py node_x" / "path.py --flag" → (path, sym)"""
    if not s:
        return None, None
    s = str(s).strip()
    for sep in (" · ", "::", "·"):
        if sep in s:
            a, b = s.split(sep, 1)
            return a.strip(), b.strip() or None
    parts = s.split()
    if len(parts) >= 2:
        tail = parts[1]
        if tail.startswith("-"):
            return parts[0], None
        return parts[0], " ".join(parts[1:])
    return s, None


def lines_of(p):
    try:
        return sum(1 for _ in open(p, encoding="utf-8", errors="ignore"))
    except Exception:                                                      # noqa: BLE001
        return 0


def defs(p):
    out = []
    try:
        for i, ln in enumerate(open(p, encoding="utf-8", errors="ignore"), 1):
            t = ln.lstrip()
            if t.startswith(("def ", "class ", "async def ")):
                head = t.split("(")[0].strip()
                kind = "class" if head.startswith("class ") else "def"
                nm = re.sub(r"^(class|async def|def)\s+", "", head).strip()
                out.append((i, kind, nm))
    except Exception:                                                      # noqa: BLE001
        pass
    return out


def resolve_symbol(p, sym):
    """给定了符号就必须**精确**命中; 允许前缀匹配但必须唯一; 全不中就返回 None
    (宁可换下一个候选文件, 也不许糊到文件第一个 def —— 那正是"打开到不相干代码"的来源)。"""
    ds = defs(p)
    if not ds:
        return None
    if sym:
        want = re.sub(r"^(def|class|async def)\s+", "", sym.split("(")[0]).strip()
        if "." in want and not want.startswith(("class ", "def ")):
            want = want.split(".")[-1]
        for i, k, nm in ds:
            if nm == want:
                return i, "%s %s" % (k, nm)
        fuzzy = [(i, k, nm) for i, k, nm in ds if want and (nm.startswith(want) or want.startswith(nm))]
        if len(fuzzy) == 1:
            i, k, nm = fuzzy[0]
            return i, "%s %s" % (k, nm)
        return None
    low = {nm: (i, k) for i, k, nm in ds}
    for e in ENTRY:
        if e in low:
            i, k = low[e]
            return i, "%s %s" % (k, e)
    for i, k, nm in ds:
        if not nm.startswith("_"):
            return i, "%s %s" % (k, nm)
    return None


def pick(nid, pr, reg, ext):
    tries = []
    src, sym = split_src(pr.get("source"))
    # 路径里没带符号时, 用上一轮写进去的 source_symbol (否则会被"首函数"糊掉)
    if not sym and pr.get("source_symbol"):
        sym = str(pr["source_symbol"])
    if nid in GROUP:                      # 分组节点: 语义归属模块优先级最高
        g, gs = GROUP[nid]
        tries.append((g, gs or sym, "group"))
    if src:
        tries.append((src, sym, "canvas.source"))
    if nid in ext:
        p, ln, s2 = ext[nid]
        tries.append((p, s2, "_EXTERNAL_LOC"))
    spec = None
    try:
        spec = reg.get(nid)
    except Exception:                                                      # noqa: BLE001
        spec = None
    if isinstance(spec, dict):
        f = spec.get("file")
        fn = getattr(spec.get("fn"), "__name__", None)
        if f and os.path.basename(f) != "library.py":
            tries.append((f, fn or sym, "registry.file"))
        if f:
            tries.append((f, fn or sym, "registry.wrapper"))
    for p, s, how in tries:
        rp = norm(p)
        if not rp:
            continue
        n = lines_of(rp)
        if n < MIN_LINES and not how.endswith("wrapper"):
            continue
        r = resolve_symbol(rp, s)
        if r:
            return rp, r[1], r[0], how
        if how == "group":            # 分组节点落在小脚本上, 无 def 也算对
            return rp, None, 1, how
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    from lerobot.engineering import registry as R
    from lerobot.engineering.nodes import library as L
    ext = getattr(L, "_EXTERNAL_LOC", {}) or {}

    d = json.load(open(CANVAS, encoding="utf-8"))
    chg, nomap = [], []
    for nd in d.get("nodes") or []:
        nid = nd.get("id") or ""
        pr = nd.setdefault("params", {})
        r = pick(nid, pr, R, ext)
        if not r:
            nomap.append((nid, (nd.get("name") or "")[:26], pr.get("source")))
            continue
        rp, sym, ln, how = r
        new = (os.path.relpath(rp, ROOT), sym, int(ln))
        if (pr.get("source"), pr.get("source_symbol"), pr.get("source_line")) != new:
            chg.append({"id": nid, "how": how, "old": (pr.get("source"), pr.get("source_symbol"), pr.get("source_line")), "new": new})
        pr["source"], pr["source_symbol"], pr["source_line"] = new

    print("画布节点 %d · 需改 %d · 无实现 %d" % (len(d.get("nodes") or []), len(chg), len(nomap)))
    for c in chg:
        print("  %-13s %-18s %s → %s :%s %s"
              % (c["id"], c["how"], (c["old"][0] or "-").split("lerobot/")[-1][:40],
                 c["new"][0].split("lerobot/")[-1], c["new"][2], c["new"][1] or ""))
    for i, nm, s in nomap:
        print("  ✗ 无实现 %-13s %-26s source=%s" % (i, nm, s))
    if a.apply:
        shutil.copy2(CANVAS, CANVAS + ".bak_openfix5")
        json.dump(d, open(CANVAS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已回写 · 改 %d 节点" % len(chg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
