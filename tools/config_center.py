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
    hdr = f"{'任务ID':<20}{'类型':<16}{'工艺步骤':<34}{'段':>3}{'粒度':>4}  目标"
    print(hdr); print("-" * len(hdr))
    for t in ts:
        steps = " → ".join(s["name"] for s in t.get("steps", []))
        if len(steps) > 32:
            steps = steps[:31] + "…"
        print(f"{t['task_id']:<20}{t['recipe_type']:<16}{steps:<34}"
              f"{len(t['applies_segments']):>3}{len(t['variants']):>4}  {t['targets']}")
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
    for s in t["steps"]:
        d = str(s.get("desc") or "")
        print(f"      · {s['name']}({s.get('dur', '?')}s): {d[:76]}"
              + (f"   力: {s['force']}" if s.get("force") else ""))
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


def _ssbind():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import ss_task_bind as sb
    return sb


def cmd_bind(a):
    """任务 × 状态空间工程 绑定 (一个工程承载全部任务)。"""
    sb = _ssbind()
    try:
        doc = sb.build()
    except SystemExit as e:
        print(f"⛔ {e}"); return 2
    if a.arg:  # 看单个任务的配置清单
        t = next((x for x in doc["tasks"] if x["task_id"] == a.arg), None)
        if not t:
            print(f"⛔ 无此任务: {a.arg}"); return 2
        print(f"【{t['task_id']}】{t['name']}  ← 状态空间工程里的配置清单")
        print(f"  工程     : {doc['project']['name']}  {doc['project']['canvas_file']}")
        print(f"      {doc['project']['nodes']} 节点 / {doc['project']['links']} 连线 · "
              f"md5 {doc['project']['canvas_md5'][:12]} · 活跃 {doc['active_task']}")
        print(f"  工艺步骤 : " + " → ".join(
            f"{s['name']}({s.get('dur', '?')}s)" for s in t.get("steps", [])))
        for s in t.get("steps", []):
            d = str(s.get("desc") or "")
            if d:
                print(f"      · {s['name']}: {d[:78]}" + (f"   力: {s['force']}" if s.get("force") else ""))
        print(f"  适用段   : {len(t['applies_segments'])}/{len(sb.SEG_ALL)}  " + " · ".join(t['applies_segments']))
        if t["excluded_segments"]:
            print(f"  不适用段 : " + " · ".join(t["excluded_segments"]))
        print(f"  启用节点 : {len(t['enabled_nodes'])}  " + ", ".join(t["enabled_nodes"][:12])
              + (" …" if len(t["enabled_nodes"]) > 12 else ""))
        print(f"  禁用节点 : {len(t['disabled_nodes'])}  " + (", ".join(t["disabled_nodes"]) or "无"))
        print(f"  六档位   : " + " · ".join(f"{v['label']}={'开' if v['checked'] else '关'}"
                                            for v in t["run_cfg"].values()))
        print(f"  参数覆盖 : {json.dumps(t['overrides'], ensure_ascii=False)}")
        print(f"  触发/循环: {t['trigger']} · {t['loop']}      判据: {t['targets']}")
        if t["blocked_by_site"]:
            print(f"  ⛔ 阻塞  : 站点几何未标定 {t['blocked_by_site']} ⇒ 任务不可下发")
        return 0
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1)); return 0
    p, cov = doc["project"], doc["coverage"]
    print(f"状态空间工程: {p['name']} · {p['canvas_file']}")
    print(f"  {p['nodes']} 节点 / {p['links']} 连线 · md5 {p['canvas_md5'][:12]} · 活跃任务 {doc['active_task']}")
    print(f"  段覆盖 {cov['covered_by_segments']}/{cov['nodes']} 节点 (未覆盖 {len(cov['uncovered'])})")
    print(f"  一个工程承载 {len(doc['tasks'])} 个任务:")
    hdr = f"  {'任务ID':<18}{'启用':>5}{'禁用':>5}  档位(开)"
    print(hdr); print("  " + "-" * 90)
    for t in doc["tasks"]:
        on = [v["label"] for v in t["run_cfg"].values() if v["checked"]]
        print(f"  {t['task_id']:<18}{len(t['enabled_nodes']):>5}{len(t['disabled_nodes']):>5}  "
              f"{' · '.join(on)}")
    print("\n看某任务的配置清单: python3 tools/config_center.py bind TASK-01-FW")
    return 0


def cmd_activate(a):
    sb = _ssbind()
    if not a.arg:
        print("⛔ 用法: config_center.py activate <TASK_ID>"); return 2
    doc = sb.build(a.arg)
    if not any(t["task_id"] == a.arg for t in doc["tasks"]):
        print(f"⛔ 无此任务: {a.arg}"); return 2
    txt = json.dumps(doc, ensure_ascii=False, indent=1)
    open(sb.OUT, "w", encoding="utf-8").write(txt)
    print(f"✅ 已把状态空间工程(主工程)的活跃任务切到 {a.arg}")
    print(f"   写盘 config/ss_task_binding.json · 工程文件导出: python3 tools/config_center.py project")
    return 0


def cmd_node(a):
    """『🧮 标定诊断测量 · 主参数 M』节点 —— 看它挂着的配置 / 写入同步。

    这是**唯一一条把配置清单落到状态空间工程**的路: 配置中心(读) ←→ 画布节点(挂载点)。
    """
    import json as _json
    p = os.path.join(ROOT, "src", "lerobot", "engineering", "flows", "state_space_obs.json")
    sys.path.insert(0, os.path.join(ROOT, "src"))
    try:
        from lerobot.engineering import flows
        d, probs = flows.load_canvas()
    except Exception as e:  # noqa: BLE001
        print(f"⛔ 读画布失败: {type(e).__name__}: {e}"); return 1
    n = next((x for x in d["nodes"] if x.get("id") == "n_calib_mani"), None)
    if n is None:
        print("⛔ 画布上没有 n_calib_mani 节点"); return 1
    pp = n.get("params") or {}
    if a.arg in ("write", "sync", "--write"):
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "ss_node_sync.py")],
                           capture_output=True, text=True, timeout=300)
        print(r.stdout.strip() or r.stderr.strip())
        return r.returncode
    snap = pp.get("cfg_snapshot") or {}
    print(f"状态空间工程 · 节点 {n['id']}  ({os.path.relpath(p, ROOT)})")
    print(f"  名称   : {n.get('name')}")
    print(f"  角色   : {pp.get('cfg_role') or '—(未写入配置, 跑: config_center.py node write)'}")
    print(f"  校验   : {'✅ 通过' if not probs else probs[:2]}")
    if snap:
        s = snap
        print(f"  快照   : 参数 {s.get('params_ready')}/{s.get('params_total')} (缺 {s.get('params_gap')})"
              f" · 任务 {s.get('tasks')} · 活跃 {s.get('active_task')} · 工单 {s.get('orders')}"
              f" · 断言 {s.get('assertions')}")
    ent = pp.get("cfg_entries") or {}
    if ent:
        print(f"  配置项 ({len(ent)}):")
        for k, v in ent.items():
            print(f"      · {k:<8} {v}")
    for key, title in (("measure_view", "测量"), ("calib_view", "标定"), ("diagnose_view", "诊断"),
                       ("task_layer", "任务层")):
        v = pp.get(key)
        if v:
            print(f"  {title}视图: " + _json.dumps(v, ensure_ascii=False)[:260])
    print("\n写入/刷新: python3 tools/config_center.py node write    (只改这一个节点, 自动备份)")
    print("只比对   : python3 tools/ss_node_sync.py --check")
    return 0


def cmd_project(a):
    sb = _ssbind()
    path = a.arg or os.path.join(ROOT, "data", "database", "zmax", "archive", "状态空间工程_按任务导出.zmaxproj")
    doc = sb.build()
    if not os.path.isfile(sb.OUT):
        open(sb.OUT, "w", encoding="utf-8").write(json.dumps(doc, ensure_ascii=False, indent=1))
    r = sb.export_project(doc, path)
    print(f"{'✅' if r['verified'] else '❌'} 状态空间工程文件: {r['path']}  ({r['bytes']} B)")
    print(f"   schema {r['schema']} · 画布 {r['nodes']} 节点 · 任务 {r['tasks']} 条 · 活跃 {r['active_task']}")
    print(f"   档位(开): {' · '.join(r['run_cfg_on'])}")
    print(f"   回读核验: {'✅ 一致' if r['verified'] else '❌ 不一致'}")
    print(f"   用控制台: 文件 → 📂 加载工程文件 → 选这个文件 (自动备份画布)")
    return 0 if r["verified"] else 2


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
        "tasks": cmd_tasks, "task": cmd_task, "bind": cmd_bind, "activate": cmd_activate,
        "node": cmd_node, "project": cmd_project,
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
