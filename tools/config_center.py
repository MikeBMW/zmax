#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VEH.6 配置中心 · 操作面 (命令行等价物)

配置中心的操作 = 读一份**描述**(config/mcd/zmax_mcd.json, 对标 A2L) + 对真源做读写。
本工具就是这套操作的可复制、可脚本化版本 —— GUI 里每个按钮都是它的外壳:

    GUI 按钮        →  本工具命令
    ─────────────────────────────────────────────────────────────
    首页·域树        →  config_center.py
    参数表(三列)      →  config_center.py list 工程配置
    点开一行          →  config_center.py show cam.K
    复制真源路径      →  config_center.py open cam.K
    工艺域·配方       →  config_center.py recipe
    工艺域·工件变体    →  config_center.py variants
    工艺域·工单列表    →  config_center.py orders
    生成工单          →  config_center.py order --scene SCN-02-HANDLE
    诊断带·全链校验    →  config_center.py check

三列的含义 (MCD): 测量=当前值/真源/时间戳 · 标定=权限/写入 · 诊断=判据
    python3 tools/config_center.py [--json] <命令> [参数]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
MCD = os.path.join(ROOT, "config", "mcd", "zmax_mcd.json")
REG = os.path.join(ROOT, "config", "mcd", "param_registry.json")
MATCH = os.path.join(ROOT, "config", "mcd", "match_matrix.json")
ORDERS = os.path.join(ROOT, "config", "orders")
TASKS = os.path.join(ROOT, "config", "tasks", "tasks.json")
DOMAINS = ["模型配置", "工程配置", "功能配置", "性能配置", "工艺·工单"]


def _j(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def _sha16(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return None


def _need_mcd():
    d = _j(MCD)
    if not d:
        print("⛔ 缺描述文件 config/mcd/zmax_mcd.json —— 先跑: python3 tools/mcd_build.py")
        sys.exit(2)
    return d


def _fresh(d):
    """描述新鲜度: 描述里记的每个真源 sha16 与当前文件比对。"""
    src = (d.get("_meta") or {}).get("sources") or {}
    bad = []
    for rel, h in src.items():
        cur = _sha16(os.path.join(ROOT, rel))
        if cur != h:
            bad.append(rel)
    return bad


# ── 命令 ────────────────────────────────────────────────────────────
def cmd_overview(a):
    d = _need_mcd()
    reg = _j(REG, {})
    bad = _fresh(d)
    chars = d["CHARACTERISTIC"]
    print(f"VEH.6 配置中心 · 总览     描述 {d['_meta']['schema']} @ {d['_meta']['generated_at']}"
          f"   真源同步: {'✅' if not bad else '❌ ' + ', '.join(bad)}")
    print()
    print(f"{'域':<12}{'参数':>4}{'就绪':>7}  缺口")
    print("-" * 78)
    for dom in DOMAINS:
        if dom == "工艺·工单":
            from build_sheet import RECIPE_STEPS, SAFETY, POKA_YOKE
            n = sum(len(r["params"]) for r in RECIPE_STEPS) + len(SAFETY)
            site = [c for c in chars if c["domain"] == "工程配置" and not c.get("ready")]
            print(f"{dom:<12}{n:>4}{'—':>7}  站点几何未定 ⇒ 坐标类参数不可信（缺 {len(site)} 项）")
            continue
        cs = [c for c in chars if c["domain"] == dom]
        ready = [c for c in cs if c.get("ready")]
        gaps = [c["id"] for c in cs if not c.get("ready")]
        print(f"{dom:<12}{len(cs):>4}{f'{len(ready)}/{len(cs)}':>7}  "
              f"{', '.join(gaps[:4])}{' …' if len(gaps) > 4 else ''}")
    m = _j(MATCH, {})
    if m:
        s = m.get("SUMMARY", {})
        blocked = [r["model"] for r in m.get("MODELS", []) if not r["usable_now"]]
        print()
        print(f"模型×工程配置匹配: 可用 {s.get('usable_now')}/{s.get('models')}"
              f"  ⛔ 受阻: {', '.join(blocked) or '无'}")
    ords = sorted(glob.glob(os.path.join(ORDERS, "BS_*.json")))
    tk = _j(TASKS, {})
    print(f"任务配置: {len(tk.get('tasks', []))} 条   ·   工单: {len(ords)} 份"
          f"  ({', '.join(os.path.basename(x)[3:-5] for x in ords)})")
    print()
    print("下一步(可复制):")
    print("  python3 tools/config_center.py tasks            # 任务配置(主要内容)")
    print("  python3 tools/config_center.py task TASK-02-HANDLE")
    print("  python3 tools/config_center.py list 工程配置")
    print("  python3 tools/config_center.py order --task TASK-02-HANDLE")
    print("  python3 tools/config_center.py check")
    return 0


def cmd_list(a):
    d = _need_mcd()
    dom = a.arg
    cs = [c for c in d["CHARACTERISTIC"] if not dom or c["domain"] == dom]
    if not cs:
        print(f"⛔ 没有域 '{dom}'（可选: {' / '.join(DOMAINS)}）")
        return 2
    if a.json:
        print(json.dumps(cs, ensure_ascii=False, indent=1)); return 0
    print(f"{'参数':<26}{'级':<4}{'权限':<10}{'测量: 真源/值':<42}{'诊断: 判据'}")
    print("-" * 118)
    for c in cs:
        v = c.get("value")
        vs = ("缺失 ⛔" if v is None else
              (f"{v[0]:.4g}…" if isinstance(v, list) and v else str(v)[:18]))
        src = os.path.basename(str(c["src"]).split("#")[0])
        meas = f"{src} | {vs}"
        print(f"{c['id']:<26}{c['grade']:<4}{c['perm']:<10}{meas:<42}{str(c['judge'])[:44]}")
    return 0


def cmd_show(a):
    d = _need_mcd()
    c = next((x for x in d["CHARACTERISTIC"] if x["id"] == a.arg), None)
    if not c:
        print(f"⛔ 无此参数: {a.arg}"); return 2
    if a.json:
        print(json.dumps(c, ensure_ascii=False, indent=1)); return 0
    print(f"【{c['id']}】{c['cn']}")
    print(f"  域/级/权限 : {c['domain']} / {c['grade']} / {c['perm']}")
    print(f"  真源        : {c['src']}")
    print(f"  当前值      : {c.get('value')}     就绪: {'✅' if c.get('ready') else '⛔ ' + str(c.get('reason',''))}")
    print(f"  单位/范围/默认: {c.get('unit')} / {c.get('rng')} / {c.get('dflt')}")
    print(f"  影响面(节点) : {', '.join(c.get('affects') or []) or '—'}")
    print(f"  关联能力     : {', '.join(c.get('feature') or []) or '—'}")
    print(f"  诊断判据     : {c['judge']}")
    print(f"  对比命令     : python3 tools/config_center.py open {c['id']}")
    return 0


def cmd_open(a):
    """给出真源文件的绝对路径与定位串 (GUI 里就是「📋 复制路径」按钮)。"""
    d = _need_mcd()
    c = next((x for x in d["CHARACTERISTIC"] if x["id"] == a.arg), None)
    tot = d["CHARACTERISTIC"]
    m = next((x for x in (d.get("MEASUREMENT") or []) if x["id"] == a.arg), None)
    if not c and not m:
        print(f"⛔ 无此参数: {a.arg}"); return 2
    e = c or m
    rel, _, key = str(e["src"]).partition("#")
    p = os.path.join(ROOT, rel)
    print(f"{e['id']} → {p}" + (f"   键: {key}" if key else ""))
    if not os.path.isfile(p):
        print("  ⚠ 文件不存在 (真源未落地)")
    if c:
        print(f"  写入路径: {c.get('read')}")
        print(f"  改法: python3 tools/config_center.py show {c['id']}   # 看判据与权限后再动")
    return 0


def cmd_recipe(a):
    from build_sheet import RECIPE_STEPS, SAFETY, POKA_YOKE
    if a.json:
        print(json.dumps({"recipe": RECIPE_STEPS, "safety": SAFETY,
                          "poka_yoke": POKA_YOKE}, ensure_ascii=False, indent=1)); return 0
    print(f"工艺域 · 上下料/插拔工序配方   共 {len(RECIPE_STEPS)} 段 / "
          f"{sum(len(r['params']) for r in RECIPE_STEPS)} 条参数   (安全节 {len(SAFETY)} 条在工作单之外)")
    for r in RECIPE_STEPS:
        print()
        print(f"── {r['seg']}")
        for p in r["params"]:
            print(f"   {p['id']:<20}{p['grade']:<4}{p['perm']:<9}{p['cn']:<16}判据: {p['judge'][:52]}")
    print()
    print("防错校验链: " + " → ".join(f"{i+1}.{n}" for i, (n, *_ ) in enumerate(POKA_YOKE)))
    return 0


def cmd_tasks(a):
    d = _j(TASKS)
    if not d:
        print("⛔ 还没有任务配置 —— 生成: python3 tools/task_build.py"); return 2
    ts = d["tasks"]
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1)); return 0
    print(f"工艺域 · 任务配置 ({len(ts)} 条, 真源 config/tasks/tasks.json)")
    hdr = f"{'任务ID':<20}{'类型':<16}{'适用段':>5}{'粒度':>4}  {'触发':<22}目标"
    print(hdr); print("-" * len(hdr))
    for t in ts:
        print(f"{t['task_id']:<20}{t['recipe_type']:<16}{len(t['applies_segments']):>5}"
              f"{len(t['variants']):>4}  {t['trigger'][:20]:<22}{t['targets']}")
    print("\n看一条详情: python3 tools/config_center.py task TASK-02-HANDLE")
    return 0


def cmd_task(a):
    d = _j(TASKS)
    if not d:
        print("⛔ 无任务配置 —— 先跑 python3 tools/task_build.py"); return 2
    t = next((x for x in d["tasks"] if x["task_id"] == a.arg), None)
    if not t:
        print(f"⛔ 无此任务: {a.arg} (可选: {', '.join(x['task_id'] for x in d['tasks'])})"); return 2
    if a.json:
        print(json.dumps(t, ensure_ascii=False, indent=1)); return 0
    print(f"【{t['task_id']}】{t['name']}")
    print(f"  任务类型 : {t['recipe_type']}    场景: {t['scene_ref']}    站点: {t['site']}")
    print(f"  适用配方段: {len(t['applies_segments'])}/{len(t['applies_segments'])+len(t['excluded_segments'])}"
          f"  " + " · ".join(x[:6] for x in t["applies_segments"]))
    if t["excluded_segments"]:
        print(f"  不适用段 : " + " · ".join(t["excluded_segments"]) + "   ← " + t["_note"])
    print(f"  步骤     : " + " → ".join(s["name"] for s in t["steps"]))
    print(f"  物料粒度 : " + " · ".join(f"{v['level']}({v['name']} {v.get('size_mm')})" for v in t["variants"]))
    print(f"  参数覆盖 : {json.dumps(t['overrides'], ensure_ascii=False)}")
    print(f"  触发/循环: {t['trigger']} · {t['loop']}")
    print(f"  验收判据 : {t['targets']}")
    print(f"  工单规则 : {t['orders_rule']}")
    print(f"  组配建议 : {t['binding_hint']}")
    print(f"  安全     : {t['safety']}")
    if t["blocked_by_site"]:
        print(f"  ⛔ 阻塞   : 站点几何未标定 {t['blocked_by_site']} ⇒ 坐标类参数不可信, 任务不可下发")
    print(f"  生成工单 : python3 tools/config_center.py order --scene {t['scene_ref']}")
    return 0


def cmd_variants(a):
    sc = _j(os.path.join(ROOT, "flows", "scenes_5jobs.json"), {}).get("scenes", [])
    if a.json:
        print(json.dumps([{"scene_id": s["scene_id"], "type": s["scene_type"],
                           "name": s["name"], "targets": s.get("targets"),
                           "objects": s.get("objects")} for s in sc], ensure_ascii=False, indent=1)); return 0
    print(f"工艺域 · 工件变体 (来自 flows/scenes_5jobs.json, {len(sc)} 个场景)")
    for s in sc:
        tl = " · ".join(f"{o['name']}({o.get('role')})" for o in s.get("objects", [])[:4])
        print(f"\n  {s['scene_id']:<16}{s['name']}")
        print(f"   目标: {s.get('targets')}")
        print(f"   物料: {tl}")
    return 0


def cmd_orders(a):
    fs = sorted(glob.glob(os.path.join(ORDERS, "BS_*.json")))
    if not fs:
        print("⛔ 还没有工单 —— 生成: python3 tools/config_center.py order"); return 2
    out = [_j(f, {}) for f in fs]
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1)); return 0
    print(f"工艺域 · 工单 ({len(fs)} 份)")
    hdr = f"{'工单号':<24}{'场景':<30}{'BOM':>4}{'步骤':>5}  站点就绪"
    print(hdr); print("-" * len(hdr))
    for b in out:
        i, r = b["identity"], b.get("readiness", {})
        print(f"{i['order_no']:<24}{str(i['name'])[:28]:<30}{len(b.get('bom',[])):>4}"
              f"{len(b.get('process',[])):>5}  {r.get('site_ok','?')}/9")
    print("\n看一份详情: python3 tools/config_center.py order --scene SCN-02-HANDLE")
    return 0


def cmd_order(a):
    import build_sheet as BS
    ref = a.scene
    if a.task:  # 支持按任务生成工单 (任务 → 场景)
        d = _j(TASKS, {})
        t = next((x for x in d.get("tasks", []) if x["task_id"] == a.task), None)
        if not t:
            print(f"⛔ 无此任务: {a.task}"); return 2
        ref = t["scene_ref"]
    sc = _j(os.path.join(ROOT, "flows", "scenes_5jobs.json"), {}).get("scenes", [])
    sel = [s for s in sc if not ref or s["scene_id"] == ref]
    if not sel:
        print(f"⛔ 无此场景: {a.scene}"); return 2
    calib = BS.read_site()
    for s in sel:
        idx = int(s["scene_id"].split("-")[1])
        b = BS.build(s, calib, idx)
        p = os.path.join(ORDERS, f"BS_{s['scene_id']}.json")
        os.makedirs(ORDERS, exist_ok=True)
        json.dump(b, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if a.json:
            print(json.dumps(b, ensure_ascii=False, indent=1)); continue
        print(f"✅ 已生成 {os.path.relpath(p, ROOT)}")
        print(f"   工单号 {b['identity']['order_no']} · 目标 {b['targets']}")
        print(f"   物料   {len(b['bom'])} 项: " + ", ".join(x["name"] for x in b["bom"]))
        print(f"   步骤   {len(b['process'])}: " + " → ".join(x["name"] for x in b["process"]))
        r = b["readiness"]
        print(f"   就绪   站点 {r['site_ok']}/9 · 缺 {', '.join(r['site_missing']) or '无'}")
        if r["site_missing"]:
            print(f"   ⛔ {r['note']}")
    return 0


def cmd_check(a):
    d = _need_mcd()
    reg = _j(REG, {})
    ok = True
    print("VEH.6 全链校验")
    bad = _fresh(d)
    print(f"  ① 描述与真源同步 : {'✅ ' + str(len(d['_meta']['sources'])) + ' 个真源一致' if not bad else '❌ 变了: ' + ', '.join(bad)}")
    ok &= not bad
    g = [c["id"] for c in d["CHARACTERISTIC"] if not c.get("ready")]
    site = [x for x in g if x in ("T_base_cam", "plane_z", "cell_geometry.points")]
    print(f"  ② 站点几何      : {'✅ 就位' if not site else '⛔ 未标定 ' + ', '.join(site) + ' ⇒ 坐标类参数不可信'}")
    ok &= not site
    m = _j(MATCH, {})
    if m:
        s = m["SUMMARY"]
        bl = [r["model"] for r in m["MODELS"] if not r["usable_now"]]
        print(f"  ③ 模型×工程配置 : {'✅ ' if not bl else '⛔ '}可用 {s['usable_now']}/{s['models']}"
              f"{' · 受阻 ' + ', '.join(bl) if bl else ''}")
        ok &= not bl
    f = os.path.join(ROOT, "feature.dbc")
    caps = sum(1 for ln in open(f, encoding="utf-8") if ln.startswith("BO_")) if os.path.isfile(f) else 0
    print(f"  ④ 能力库        : {'✅' if caps else '⛔'} feature.dbc BO_ {caps} 条")
    ok &= caps > 0
    diag = (d.get("DIAGNOSTICS") or {})
    tot, auto = diag.get("assertions_total", "?"), diag.get("assertions_auto", "?")
    byl = diag.get("by_level") or {}
    print(f"  ⑤ 诊断断言      : ✅ {tot} 条 (自动 {auto}"
          f"{' · ' + ' '.join(f'{k} {v}' for k, v in byl.items()) if byl else ''})")
    g1 = [c["id"] for c in d["CHARACTERISTIC"] if c["grade"] == "G1"]
    g1editable = [c["id"] for c in d["CHARACTERISTIC"] if c["grade"] == "G1" and c["perm"] != "readonly"]
    print(f"  ⑥ 安全红线      : {'✅ G1 全只读 ' if not g1editable else '❌ 有编辑口 '}{g1} ")
    ok &= not g1editable
    ords = sorted(glob.glob(os.path.join(ORDERS, "BS_*.json")))
    print(f"  ⑦ 工单          : {'✅' if ords else '⛔'} {len(ords)} 份"
          f"{' · 全部受站点缺口阻塞' if site and ords else ''}")
    print()
    print("总判: " + ("✅ 通过" if ok else "⛔ 有阻塞项 (见上, 站点几何是共同根因)"))
    return 0 if ok else 1


CMDS = {"overview": cmd_overview, "list": cmd_list, "show": cmd_show, "open": cmd_open,
        "recipe": cmd_recipe, "variants": cmd_variants, "orders": cmd_orders,
        "tasks": cmd_tasks, "task": cmd_task,
        "order": cmd_order, "check": cmd_check}


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--scene", default=None)
    ap.add_argument("--task", default=None)
    ap.add_argument("cmd", nargs="?", default="overview")
    ap.add_argument("arg", nargs="?")
    a = ap.parse_args()
    fn = CMDS.get(a.cmd)
    if not fn:
        print(__doc__)
        return 2
    return fn(a)


if __name__ == "__main__":
    sys.exit(main() or 0)
