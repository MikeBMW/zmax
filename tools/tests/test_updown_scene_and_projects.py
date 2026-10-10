#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上下料场景 / 项目档案 / 指标验证 的回归判据 (防回退)。

覆盖 (每节都真跑真读, 不 mock):
  1. 项目档案: 合并基线 + _append_bom_items; 缺口可枚举; 改 overlay ⇒ 合并 sha 变 (同源判据的抓手)
  2. 上下料场景 build: 幂等 (同输入两次 ⇒ 字节一致) · 在役父场景 sha 不变 · index 登记
  3. scene_edit --scene: 写只落在命名场景目录 (父场景 sha 不变) + 备份 + 回读
  4. 指标验证引用: 场景/通道里的 perf.* id 全部能在真源解析 (无悬空)
  5. 主参数 M: 能量公式自洽 (M = 1 + (E_kin+E_pot)/E_ref) 且落在范围 [0,8]

用法: python3 tools/tests/test_updown_scene_and_projects.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "tools"))
FAIL = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ⛔ ") + msg)
    if not cond:
        FAIL.append(msg)
    return cond


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def run(*args, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([PY] + list(args), cwd=ROOT, capture_output=True, text=True, env=e)


def sec1():
    print("1) 项目档案 (根据配置适配不同项目)")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import project_profile as pp                                                       # noqa: PLC0415
    b1, p1 = pp.load("PROJ-TH-TRAY")
    b2, p2 = pp.load("PROJ-LOAD-UNLOAD")
    check(p1["merged_sha256"] != p2["merged_sha256"], "两个项目合并 sha 不同 (%s ≠ %s)" % (p1["merged_sha256"][:8], p2["merged_sha256"][:8]))
    check(len(b2["bom"]["items"]) == len(b1["bom"]["items"]) + 3, "上下料项目 BOM = 基线 %d + 追加 3 = %d 项"
          % (len(b1["bom"]["items"]), len(b2["bom"]["items"])))
    ids = [i["id"] for i in b2["bom"]["items"]]
    check("B19" in ids and "B20" in ids and "B21" in ids, "追加项 B19/B20/B21 已在 items 里")
    check(all(not isinstance(i["price"], (int, float)) for i in b2["bom"]["items"] if i["id"] in ("B19", "B20", "B21")),
          "追加项价格为「待确认」形态 (None) — 不编数字")
    g = pp.gaps(b2)
    check(len(g) >= 8, "缺口可枚举 (%d 项, 例: %s)" % (len(g), g[0]))
    # 改 overlay ⇒ 合并 sha 必变
    tmp = os.path.join(ROOT, "config", "platform", "projects", "_TEST_TMP.json")
    json.dump({"pid": "_TEST_TMP", "note": "t", "project": {"name": "T"}}, open(tmp, "w", encoding="utf-8"))
    try:
        _a, pa = pp.load("_TEST_TMP")
        json.dump({"pid": "_TEST_TMP", "note": "t2", "project": {"name": "T2"}}, open(tmp, "w", encoding="utf-8"))
        _b, pb = pp.load("_TEST_TMP")
        check(pa["merged_sha256"] != pb["merged_sha256"], "改 overlay ⇒ 合并 sha 变 (文档一致性判据抓得到)")
    finally:
        os.path.exists(tmp) and os.remove(tmp)


def sec2():
    print("2) 上下料场景 build (幂等 + 不碰在役场景)")
    parent = os.path.join(ROOT, "data", "scene", "objects3d.json")
    s0 = sha(parent)
    r = run(os.path.join(ROOT, "tools", "scene_build_updown.py"))
    check(r.returncode == 0, "生成成功")
    d = os.path.join(ROOT, "data", "scene", "scenes", "SCN-07-UP")
    a1 = open(os.path.join(d, "objects3d.json"), "rb").read()
    a2 = open(os.path.join(d, "overlay_spec.json"), "rb").read()
    run(os.path.join(ROOT, "tools", "scene_build_updown.py"))
    check(open(os.path.join(d, "objects3d.json"), "rb").read() == a1 and open(os.path.join(d, "overlay_spec.json"), "rb").read() == a2,
          "幂等: 同输入两次 ⇒ 字节一致")
    check(sha(parent) == s0, "在役父场景 objects3d.json sha 未变")
    idx = json.load(open(os.path.join(ROOT, "data", "scene", "scenes", "index.json"), encoding="utf-8"))
    check("SCN-07-UP" in (idx.get("named_scenes") or {}), "index.json 已登记 SCN-07-UP (场景功能区下拉可见)")
    o = json.load(open(os.path.join(d, "overlay_spec.json"), encoding="utf-8"))
    check(len(o["markers"]) >= 4 and len(o["trajectories"]) >= 2, "标记 %d / 围栏 %d / 轨迹 %d"
          % (len(o["markers"]), len(o["fences"]), len(o["trajectories"])))


def sec3():
    print("3) scene_edit --scene (可视化编辑只落在命名场景目录)")
    parent = os.path.join(ROOT, "data", "scene", "overlay_spec.json")
    s0 = sha(parent)
    d = os.path.join(ROOT, "data", "scene", "scenes", "SCN-07-UP", "overlay_spec.json")
    before = json.load(open(d, encoding="utf-8"))
    n0 = len(before["markers"])
    r = run(os.path.join(ROOT, "tools", "scene_edit.py"), "--scene", "SCN-07-UP", "add", "--kind", "markers",
            "--data", json.dumps({"name": "回归测试点", "kind": "检查点", "pos": [0.5, 0.3, 0.2]}))
    check(r.returncode == 0 and "readback=True" in (r.stdout + r.stderr), "add 成功 + 回读一致")
    after = json.load(open(d, encoding="utf-8"))
    check(len(after["markers"]) == n0 + 1, "标记 %d → %d" % (n0, len(after["markers"])))
    check(sha(parent) == s0, "在役场景 overlay_spec.json sha 未变 (零影响)")
    check(len([f for f in os.listdir(os.path.dirname(d)) if ".bak_edit_" in f]) >= 1, "写前有备份")
    # 清掉测试点, 保持场景干净 (子命令是 rm 不是 remove)
    _new = [m for m in after["markers"] if m.get("id") not in [x.get("id") for x in before["markers"]]]
    rr = run(os.path.join(ROOT, "tools", "scene_edit.py"), "--scene", "SCN-07-UP", "rm", "--kind", "markers",
             "--id", _new[0]["id"]) if _new else None
    back = json.load(open(d, encoding="utf-8"))
    if len(back["markers"]) == n0:
        check(True, "rm 生效: 测试点已移除 (场景回到 %d 标记)" % n0)
    else:
        json.dump(before, open(d, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        check(False, "rm 未生效 (stdout=%s) ⇒ 已还原真源" % ((rr.stdout or rr.stderr)[-80:] if rr else "无新增标记"))


def sec4():
    print("4) 指标验证引用 (无悬空 id)")
    r = run(os.path.join(ROOT, "tools", "scene_metric_validate.py"), "--check-ids")
    check(r.returncode == 0 and "悬空 0" in r.stdout, r.stdout.strip()[:90])


def sec5():
    print("5) 主参数 M 能量标定 (公式自洽 + 范围)")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import master_param_m as M                                                         # noqa: PLC0415
    r = M.compute("PROJ-TH-TRAY")
    calc = 1.0 + (r["E_kin_J"] + r["E_pot_J"]) / r["E_ref_J"]
    check(abs(round(calc, 3) - r["M"]) < 0.002, "M = 1 + (E_kin+E_pot)/E_ref = %.3f (表内 %.3f)" % (calc, r["M"]))
    check(0.0 <= r["M"] <= 8.0, "M 落在流形范围 [0,8] = %s" % r["M"])
    check(bool(r["energy_level"]), "能级已给出 = %s" % r["energy_level"])
    mf = json.load(open(os.path.join(ROOT, "config", "calib", "zmax_manifold.json"), encoding="utf-8"))
    der = mf.get("_energy_derivation") or {}
    check("E_task_J" in der and der.get("formula", "").startswith("M = 1"), "真源里存了推导 (E_task=%s J)" % der.get("E_task_J"))
    check(mf.get("inertia") is False, "inertia 保持 false (零回归; 开二阶需 ΔV<0 证据)")


if __name__ == "__main__":
    print("═" * 74)
    for f in (sec1, sec2, sec3, sec4, sec5):
        f()
    print("═" * 74)
    print(("⛔ 失败 %d 项: %s" % (len(FAIL), FAIL)) if FAIL else "✅ 全部通过")
    sys.exit(1 if FAIL else 0)
