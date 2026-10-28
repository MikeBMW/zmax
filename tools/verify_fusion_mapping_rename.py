#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_fusion_mapping_rename.py — 判据: 画布节点「📡 融合定位」全面改名「📡 融合定位建图」

证明 6 件事 (逐项 ✅/❌ + 证据 文件:行号):
  ① 画布唯一依据里节点 name == 「📡 融合定位建图」 (id 不变 = sssensor)
  ② registry 用**新旧两个关键词**都命中同一个节点 id:
       ②a grep 到注册表行 (含新旧关键词)  ②b 在 import/load 路径里真的解析一次 match_node
  ③ 所有已同步文件里不再残留**画布显示口径**的旧名 (脚本 matcher / 兼容别名不算; 白名单显式列出)
  ④ 画布结构未变: 89 节点 / 184 连线 (且唯一依据节点数 = 89)
  ⑤ 唯一依据链四条命令全绿 (ss_task_bind --check / engineering_db build / engineering_db check / canvas_level_audit)
  ⑥ 节点描述含建图能力 (专用实现 src/lerobot/manifold/localization_mapping.py) 且无禁词红线

用法: gui-venv311/bin/python tools/verify_fusion_mapping_rename.py
判据: 全 ✅ → exit 0; 任一 ❌ → exit 3
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
NEW = "📡 融合定位建图"
OLD = "📡 融合定位"
NODE_ID = "sssensor"          # 画布节点 id (不变)
REG_KEY = "ss_sensor"         # registry key (不变)
FN = "node_ss_s1"             # 处理函数 (不变)
CANVAS = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "state_space_obs.json")
LIBRARY = os.path.join(ROOT, "src", "lerobot", "engineering", "nodes", "library.py")

# 旧显示名的严格匹配: 「融合定位」但**后面不接「建图」** = 真残留
OLDSTRICT = re.compile(r"融合定位(?!建图)")

# ── 本论已同步的文件 (必须出现新名; 严格旧名只允许出现在白名单行) ──
SYNCED = [
    "data/database/zmax/sources/canvas/state_space_obs.json",
    "data/database/zmax/zmax_space.proj",
    "config/platform/zmax_platform.json",
    "data/database/zmax/sources/config/platform/zmax_platform.json",   # hardlink 同 inode
    "data/database/zmax/config_meta.json",
    "src/lerobot/engineering/nodes/library.py",
    "src/lerobot/engineering/nodes/by_level.py",
    "src/lerobot/verification/node_func_tree.py",
    "tools/gui/simulink_module.py",
    "tools/gui/data_world.py",
    "tools/gui/state_space_sim.py",
    "tools/gui/state_space_sim_real.py",
    "tools/gui/auto_test_suite.py",
    "tools/gui/ss_dreamview.py",
]

# ── 兼容别名 (允许保留严格旧名, 因为它就是"旧名兼容"的落点) ──
COMPAT = [
    ("src/lerobot/engineering/nodes/library.py", '_reg("ss_sensor", ["传感器融合", "融合定位建图", "融合定位"]'),
    ("tools/gui/simulink_module.py", 'elif ("融合定位" in nm) or ("传感器融合" in nm)'),
    ("tools/gui/auto_test_suite.py", '("融合定位建图" in n) or ("融合定位" in n)'),
]

FORBIDDEN = ["conv", "attention", "transformer", "mlp", "loss", "训练", "梯度",
             "卷积", "注意力", "sigmoid", "softmax", "embedding", "token"]

FAILS: list[str] = []


def chk(ok: bool, label: str, ev: str = "") -> bool:
    print(("  ✅ " if ok else "  ❌ ") + label + (("%s" % ("  " + ev)) if ev else ""))
    if not ok:
        FAILS.append(label)
    return ok


def relpath(p: str) -> str:
    return os.path.relpath(p, ROOT)


def lines_of(relpath_: str):
    ap = os.path.join(ROOT, relpath_)
    if not os.path.exists(ap):
        return None
    return open(ap, encoding="utf-8").read().splitlines()


def hits(ls, pattern):
    if isinstance(pattern, str):
        return [i + 1 for i, ln in enumerate(ls) if pattern in ln]
    return [i + 1 for i, ln in enumerate(ls) if pattern.search(ln)]


print("═" * 78)
print("判据: 画布节点「%s」→「%s」全面改名" % (OLD, NEW))
print("═" * 78)

# ── ① 画布唯一依据 name ────────────────────────────────────────────────────────
print("\n① 画布唯一依据 name == 「%s」" % NEW)
canvas = json.load(open(CANVAS, encoding="utf-8"))
clines = open(CANVAS, encoding="utf-8").read().splitlines()
named_new = [n for n in canvas["nodes"] if n.get("name") == NEW]
named_old = [n for n in canvas["nodes"] if n.get("name") == OLD]
name_line = next((i + 1 for i, ln in enumerate(clines) if ('"name": "%s"' % NEW) in ln), None)
chk(bool(named_new) and not named_old,
    "唯一依据 `%s` 节点 name == 「%s」 (恰好 1 个)" % (relpath(CANVAS), NEW),
    "%s:%s" % (relpath(CANVAS), name_line))
chk(named_new and named_new[0].get("id") == NODE_ID,
    "节点 id 未变 = %s (函数/键不动)" % NODE_ID,
    "id=%s type=%s" % (named_new[0].get("id"), named_new[0].get("type")) if named_new else "")

# ── ② registry 新旧关键词命中同一节点 ───────────────────────────────────────
print("\n② registry 用新旧两个关键词都命中同一节点 id")
liblines = lines_of("src/lerobot/engineering/nodes/library.py") or []
reg_line = next((i + 1 for i, ln in enumerate(liblines) if '_reg("%s"' % REG_KEY in ln), None)
reg_txt = liblines[reg_line - 1] if reg_line else ""
chk(reg_line is not None and ('"融合定位建图"' in reg_txt) and ('"融合定位"' in reg_txt),
    "②a grep 到注册表行, 含新关键词 + 旧关键词(兼容别名)",
    "src/lerobot/engineering/nodes/library.py:%s" % reg_line)

resolved = {}
err = None
try:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from lerobot.engineering import registry                       # noqa: E402
    from lerobot.engineering.nodes import library                  # noqa: E402,F401  (触发 _reg)
    for probe in (NEW, OLD, "融合定位"):
        resolved[probe] = registry.match_node(probe)
    info = registry.get(REG_KEY) or {}
    fnname = info.get("fn").__name__ if info.get("fn") else None
except Exception as e:                                             # noqa: BLE001
    err = repr(e)
    fnname = None
if err:
    chk(False, "②b import/load 路径解析 (异常)", err)
else:
    chk(resolved.get(NEW) == REG_KEY and resolved.get(OLD) == REG_KEY and resolved.get("融合定位") == REG_KEY,
        "②b 真解析: match_node(新名)=match_node(旧名)=match_node(裸旧名)= %s" % REG_KEY,
        "新名→%s · 旧名→%s · 裸旧名→%s" % (resolved.get(NEW), resolved.get(OLD), resolved.get("融合定位")))
    chk(fnname == FN, "②b registry[%s].fn == %s (节点 id 与函数不变)" % (REG_KEY, FN), "fn=%s" % fnname)

# ── ③ 已同步文件不再残留画布显示口径旧名 ────────────────────────────────────
print("\n③ 已同步文件残留旧名检查 (脚本 matcher / 兼容别名不计)")
compat_by_file: dict[str, list[str]] = {}
for f, frag in COMPAT:
    compat_by_file.setdefault(f, []).append(frag)
for rel in SYNCED:
    ls = lines_of(rel)
    if ls is None:
        chk(False, "文件缺失: %s" % rel)
        continue
    new_at = hits(ls, "融合定位建图")
    strict = hits(ls, OLDSTRICT)
    allowed = []
    for ln in strict:
        if any(fr in ls[ln - 1] for fr in compat_by_file.get(rel, [])):
            allowed.append(ln)
    bad = [ln for ln in strict if ln not in allowed]
    ev = "新名 %s:%s" % (rel, new_at[0] if new_at else "?")
    if strict:
        ev += " · 旧名行 %s%s" % (
            [("%d%s" % (l, "(别名)" if l in allowed else "")) for l in strict], "")
    chk(bool(new_at) and not bad, "无旧显示名残留: %s" % rel, ev)

# ── ④ 画布结构未变 ─────────────────────────────────────────────────────────
print("\n④ 画布结构未变")
nn = len(canvas.get("nodes") or [])
nl = len(canvas.get("links") or [])
nfun = len([n for n in (canvas.get("nodes") or []) if n.get("type") != "row_bg"])
chk(nn == 89 and nl == 184, "画布 = 89 节点 / 184 连线",
    "实测 %d 节点 (非 row_bg %d) / %d 连线" % (nn, nfun, nl))

# ── ⑤ 唯一依据链四条命令全绿 ────────────────────────────────────────────────────
print("\n⑤ 唯一依据链四条命令全绿")
CHAIN = [
    (["tools/ss_task_bind.py", "--check"], "ss_task_bind --check", "✅ config/ss_task_binding.json"),
    (["tools/engineering_db.py", "build"], "engineering_db build", "canvas_links"),
    (["tools/engineering_db.py", "check"], "engineering_db check", "✅ 判据全绿"),
    (["tools/canvas_level_audit.py"], "canvas_level_audit", "LEVEL_AUDIT_DONE"),
]
for args, label, marker in CHAIN:
    r = subprocess.run([PY] + args, cwd=ROOT, capture_output=True, text=True, timeout=600)
    out = (r.stdout or "") + (r.stderr or "")
    ok = r.returncode == 0 and marker in out
    ev = "rc=%d · 命中 %r" % (r.returncode, marker) if ok else \
         "rc=%d · 未命中 %r · 尾部: %s" % (r.returncode, marker, out[-160:].replace("\n", " "))
    chk(ok, "⑤ %s" % label, ev)

# ── ⑥ 描述含建图能力 + 禁词红线 ─────────────────────────────────────────────
print("\n⑥ 节点描述: 含建图能力实现 + 无禁词")
desc = (named_new[0].get("params", {}) if named_new else {}).get("desc", "")
desc_line = next((i + 1 for i, ln in enumerate(clines) if "localization_mapping.py" in ln and "desc" in ln), None)
cap_ok = ("localization_mapping.py" in desc and "建图" in desc
          and any(k in desc for k in ("ORB", "关键帧", "回环")) and "auto_start" in desc)
chk(cap_ok, "描述提到专用建图实现 src/lerobot/manifold/localization_mapping.py (ORB/关键帧/地图点/回环/自动加载)",
    "%s:%s" % (relpath(CANVAS), desc_line))
bw = [w for w in FORBIDDEN if w in desc]
chk(not bw, "描述无禁词 (%s)" % "/".join(FORBIDDEN), "命中: %s" % (bw or "无"))

# ── 汇总 ──────────────────────────────────────────────────────────────────
print("\n" + "═" * 78)
if FAILS:
    print("❌ 判据未过 %d 项: %s" % (len(FAILS), FAILS))
    print("═" * 78)
    sys.exit(3)
print("✅ 判据全绿 (改名后处处挂得上 · 旧名仍兼容 · 画布结构未变)")
print("═" * 78)
sys.exit(0)
