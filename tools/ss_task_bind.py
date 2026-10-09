#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务 × 状态空间工程 —— 绑定层 (老倪: 「这些任务，都用一个状态空间这一个工程」)

一个工程, 多任务: **同一个状态空间工程** 承载全部任务, 任务只是工程里的一份"配置清单"。
    · 工程   = 画布真源 src/lerobot/engineering/flows/state_space_obs.json (89 节点 / 184 连线)
    · 任务   = 工程内的一份配置: 适用配方段 + 参数覆盖 + 档位 + 触发/循环 + 验收判据
    · 绑定   = 把任务清单挂到**这一个**工程上, 记下画布指纹(md5+节点/连线数); 画布变了 ⇒ 指纹不符, 提示重绑
    · 切换   = 只改 active_task, **不换工程文件**; 导出的 .zmaxproj 一个文件带全部任务

机械推导 (不手写映射, 可复算):
  ① 段→节点: 每个配方段给关键词表, 在 节点 id+name+desc 上匹配 ⇒ 段覆盖的节点集
  ② 任务启用集 = ∪(applies_segments 的节点) ; 任务禁用集 = 只被 excluded_segments 命中的节点
     (例: 上下料任务不适用「4 放置/插入」⇒ 插入/流形/INTACT 类节点被禁用)
  ③ 六档位由段机械推出: 含段 4/5 ⇒ L3全链/流形yaw/L4 INTACT/L4→DiT 开; 含段 1/3 ⇒ L2 兼容开;
     不含段 4/5 (纯搬运) ⇒ ⚡引擎快演 开

真源(只读): config/tasks/tasks.json · 画布真源 · config/calib/zmax_calib.json
输出: config/ss_task_binding.json (绑定真源, 生成物)
用法:
    python3 tools/ss_task_bind.py [--check] [--json] [--task TASK-01-FW] [--activate TASK-01-FW]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
TASKS = os.path.join(ROOT, "config", "tasks", "tasks.json")
OUT = os.path.join(ROOT, "config", "ss_task_binding.json")

# ① 配方段 → 节点关键词 (在 节点 id+name+desc 上匹配; 关键词来自画布真实节点文本)
SEG_NODES = {
    "0 料源与来料状态": ["数据源", "环境渲染", "metaworld 数据源", "真机信号", "任务指令"],
    "1 取件": ["YOLO 目标检测", "2D→3D", "触觉感知", "抓取", "下降", "融合定位"],
    "2 姿态准备": ["意图解码", "动作头", "Flow-Matching", "姿态", "翻转"],
    "3 识别与工位对接": ["融合", "定位", "标定层", "目标识别", "对位"],
    "4 放置/插入": ["插入", "流形", "INTACT", "专家预测", "潜空"],
    "5 拔出/取回": ["抬起", "转移", "完成", "拔出", "取回"],
    "6 分拣与回位": ["外观质量", "Feature 功能清单", "质量门", "AOI"],
    "7 节拍与循环": ["动作调制", "安全执行边界", "能力档位", "技能库", "记忆", "序列编排"],
}
SEG_ALL = list(SEG_NODES.keys())


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


def canvas():
    """读画布真源 (只读)。返回 (data, errors, path)"""
    from lerobot.engineering import flows
    d, probs = flows.load_canvas()
    return d, list(probs or []), flows.canvas_path()


def node_text(n):
    return " ".join([str(n.get("id") or ""), str(n.get("name") or ""),
                     str((n.get("params") or {}).get("desc") or "")])[:400]


def seg_node_map(nodes):
    """段 → [节点 id] (关键词匹配, 可复算)"""
    m = {}
    for seg, kws in SEG_NODES.items():
        hit = []
        for n in nodes:
            if n.get("type") in ("row_bg", "bg"):
                continue
            t = node_text(n)
            if any(k in t for k in kws):
                hit.append(n.get("id"))
        m[seg] = hit
    return m


def derive_run_cfg(applies):
    """③ 六档位由段机械推出 (属性名与 project_file.RUN_CHECKS 逐字一致)"""
    has_ins = ("4 放置/插入" in applies) or ("5 拔出/取回" in applies)
    has_perc = ("1 取件" in applies) or ("3 识别与工位对接" in applies)
    has_aoi = "6 分拣与回位" in applies
    return {
        "chk_engine_demo": {"label": "⚡引擎快演", "checked": not has_ins},
        "chk_l3_full": {"label": "🚀 L3 全链(插拔+AOI)", "checked": has_ins or has_aoi},
        "chk_mani_yaw": {"label": "🧠 流形 yaw 执行", "checked": has_ins},
        "chk_intact_exec": {"label": "🤖 L4 用 INTACT 节点执行", "checked": has_ins},
        "chk_l4_dit": {"label": "🎯 L4 意图 → DiT 精炼", "checked": has_ins},
        "chk_l2_compat": {"label": "🧩 L2 兼容 (前馈 MLP + YOLO)", "checked": has_perc},
    }


def _structural_md5(d):
    """**结构指纹**: 只取结构 (id/type/name/位置/端口/连线), 剔除配置挂载键 (cfg_*/..._view/task_layer)。

    为什么: 「标定诊断测量 · 主参数 M」节点自己挂着配置快照 (含工程指纹), 若指纹算上这些挂载键,
    写一次节点 ⇒ 指纹变 ⇒ 绑定过期 ⇒ 再写 ⇒ 死循环。结构指纹让"写配置进节点"不影响工程身份。
    """
    cfg_keys = ("cfg_role", "cfg_entries", "cfg_snapshot", "measure_view", "calib_view",
                "diagnose_view", "task_layer")
    nodes = []
    for n in d.get("nodes") or []:
        nn = dict(n)
        p = dict(nn.get("params") or {})
        for k in cfg_keys:
            p.pop(k, None)
        nn["params"] = p
        nodes.append(nn)
    blob = json.dumps({"nodes": nodes, "links": d.get("links") or []},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.md5(blob.encode()).hexdigest()


def build(activate=None):
    tk = _j(TASKS, {})
    if not tk:
        raise SystemExit("⛔ 缺 config/tasks/tasks.json —— 先跑 tools/task_build.py")
    d, probs, path = canvas()
    if probs:
        raise SystemExit("⛔ 画布校验不过, 拒绝绑定: %s" % probs[:3])
    nodes = d.get("nodes") or []
    smap = seg_node_map(nodes)
    covered = sorted({nid for v in smap.values() for nid in v})
    task_ids = [t["task_id"] for t in tk["tasks"]]
    tasks = []
    for t in tk["tasks"]:
        on, only_excl = set(), set()
        for seg in t["applies_segments"]:
            on |= set(smap.get(seg, []))
        for seg in t.get("excluded_segments", []):
            only_excl |= set(smap.get(seg, []))
        disabled = sorted(only_excl - on)
        tasks.append({
            "task_id": t["task_id"], "name": t["name"], "recipe_type": t["recipe_type"],
            "scene_ref": t["scene_ref"], "site": t["site"],
            "steps": [{"t": s.get("t"), "dur": s.get("dur"), "name": s.get("name"),
                       "desc": s.get("desc"), "force": s.get("force")}
                      for s in t.get("steps", [])],
            "applies_segments": t["applies_segments"],
            "excluded_segments": t.get("excluded_segments", []),
            "enabled_nodes": sorted(on), "disabled_nodes": disabled,
            "overrides": t["overrides"], "trigger": t["trigger"], "loop": t["loop"],
            "targets": t["targets"], "orders_rule": t["orders_rule"],
            "safety": t["safety"], "blocked_by_site": t.get("blocked_by_site", []),
            "run_cfg": derive_run_cfg(t["applies_segments"]),
        })
    # 活跃任务的持久化真源: ① 命令行 --activate ② 已有绑定文件里的 active_task ③ tasks.json ④ 第一条
    persisted = (_j(OUT, {}) or {}).get("active_task")
    default_active = activate or persisted or tk.get("active_task") or task_ids[0]
    if default_active not in task_ids:
        default_active = task_ids[0]
    md5 = _structural_md5(d)
    doc = {
        "_meta": {"schema": "zmax.statespace.taskbinding/1",
                  "generated_at": time.strftime("%F %T"),
                  "doc": "任务 × 状态空间工程 绑定 (一个工程承载全部任务; 生成物, 勿手改)",
                  "sources": {"config/tasks/tasks.json": _sha16(TASKS),
                              "canvas": os.path.relpath(path, ROOT)}},
        "project": {"name": "状态空间工程 · 主工程", "canvas_file": os.path.relpath(path, ROOT),
                    "canvas_md5": md5, "nodes": len(nodes), "links": len(d.get("links") or [])},
        "active_task": default_active,
        "segment_node_map": smap,
        "coverage": {"nodes": len(nodes), "covered_by_segments": len(covered),
                     "uncovered": sorted({n.get("id") for n in nodes
                                          if n.get("type") not in ("row_bg", "bg")} - set(covered))},
        "tasks": tasks,
    }
    return doc


def export_project(doc, path):
    """导出一个工程文件 (.zmaxproj): 画布 + 按任务的 6 档位 + **全部任务清单** 段。

    一个工程承载全部任务 (老倪: 「这些任务，都用一个状态空间这一个工程」)。
    schema 与 project_file 一致 ⇒ 控制台「文件 → 加载工程文件」可直接打开;
    多出来的 `task_binding` 段是扩展, load_project 只读 canvas/run_cfg/ui, 不影响加载。
    """
    sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
    import project_file as pf
    from lerobot.engineering import flows
    d, probs = flows.load_canvas()
    if probs:
        raise SystemExit("⛔ 画布校验不过, 拒绝导出: %s" % probs[:3])
    act = next(t for t in doc["tasks"] if t["task_id"] == doc["active_task"])
    proj = {
        "schema": pf.SCHEMA,
        "saved_at": time.strftime("%F %T"),
        "saved_by": "Z-MAX 配置中心 · 🧩 状态空间工程 (任务配置)",
        "zmax_version": pf._ver(),
        "note": f"任务配置 {doc['active_task']} ({act['name']}) · 一个工程承载 "
                f"{len(doc['tasks'])} 个任务 · 站点 {act['site']}",
        "canvas_source": flows.canvas_path(),
        "canvas_fingerprint": {"md5": doc["project"]["canvas_md5"], "stats": flows.stats(d)},
        "canvas": d,
        "run_cfg": act["run_cfg"],                       # 按任务机械推出的 6 档位
        "ui": {"canvas_stack_index": None},
        "task_binding": {                                # 扩展段: 任务清单 + 段→节点映射
            "active_task": doc["active_task"],
            "project": doc["project"],
            "segment_node_map": doc["segment_node_map"],
            "tasks": [{k: t[k] for k in ("task_id", "name", "recipe_type", "scene_ref", "site",
                                         "steps", "applies_segments", "excluded_segments",
                                         "enabled_nodes", "disabled_nodes", "overrides", "trigger",
                                         "loop", "targets", "orders_rule", "blocked_by_site")}
                      for t in doc["tasks"]],
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, str(path))
    # 回读核验 (写盘不算完成, 回读一致才算)
    back = json.load(open(path, encoding="utf-8"))
    ok = (back.get("schema") == pf.SCHEMA
          and len((back.get("canvas") or {}).get("nodes") or []) == doc["project"]["nodes"]
          and len((back.get("task_binding") or {}).get("tasks") or []) == len(doc["tasks"])
          and len(back.get("run_cfg") or {}) == 6)
    return {"path": os.path.abspath(str(path)), "bytes": os.path.getsize(str(path)),
            "schema": back.get("schema"), "nodes": len((back.get("canvas") or {}).get("nodes") or []),
            "tasks": len((back.get("task_binding") or {}).get("tasks") or []),
            "run_cfg_on": [v["label"] for v in (back.get("run_cfg") or {}).values() if v.get("checked")],
            "active_task": (back.get("task_binding") or {}).get("active_task"),
            "verified": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--task", default=None)
    ap.add_argument("--activate", default=None)
    ap.add_argument("--export", default=None, help="导出工程文件 (.zmaxproj) 路径")
    a = ap.parse_args()
    doc = build(a.activate)
    txt = json.dumps(doc, ensure_ascii=False, indent=1)

    if a.export:
        if not os.path.isfile(OUT):
            open(OUT, "w", encoding="utf-8").write(txt)
        r = export_project(doc, a.export)
        print(f"{'✅' if r['verified'] else '❌'} 工程文件 {r['path']}  ({r['bytes']} B)")
        print(f"   schema {r['schema']} · 画布 {r['nodes']} 节点 · 任务 {r['tasks']} 条 · 活跃 {r['active_task']}")
        print(f"   档位(开): {' · '.join(r['run_cfg_on'])}")
        print(f"   回读核验: {'✅ 一致' if r['verified'] else '❌ 不一致'}")
        return 0 if r["verified"] else 2

    if a.check:
        old = open(OUT, encoding="utf-8").read() if os.path.isfile(OUT) else None
        if old:
            try:
                same = json.loads(old) and {k: v for k, v in json.loads(old).items() if k != "_meta"} == \
                       {k: v for k, v in doc.items() if k != "_meta"}
            except Exception:  # noqa: BLE001
                same = False
        else:
            same = False
        print(f"  {'✅' if same else '❌'} config/ss_task_binding.json "
              f"({'内容一致 (时间戳除外)' if same else '不一致 — 真源变了, 需重绑定'})")
        return 0 if same else 2
    if a.json:
        print(txt); return 0
    if a.activate:
        open(OUT, "w", encoding="utf-8").write(txt)
        print(f"✅ 已激活 {doc['active_task']} (写盘 config/ss_task_binding.json)")
        return 0
    if a.task:
        t = next((x for x in doc["tasks"] if x["task_id"] == a.task), None)
        if not t:
            print(f"⛔ 无此任务: {a.task}"); return 2
        print(json.dumps(t, ensure_ascii=False, indent=1)); return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(txt)
    p, cov = doc["project"], doc["coverage"]
    print(f"工程: {p['name']}  {p['canvas_file']}")
    print(f"      {p['nodes']} 节点 / {p['links']} 连线 · md5 {p['canvas_md5'][:12]}")
    print(f"段覆盖: {cov['covered_by_segments']}/{cov['nodes']} 节点被配方段覆盖 "
          f"(未覆盖 {len(cov['uncovered'])}: {', '.join(cov['uncovered'][:8])}{' …' if len(cov['uncovered'])>8 else ''})")
    print(f"活跃任务: {doc['active_task']}")
    print()
    hdr = f"{'任务ID':<18}{'启用节点':>8}{'禁用节点':>8}  档位(开): "
    print(hdr); print("-" * 96)
    for t in doc["tasks"]:
        on = [v["label"] for v in t["run_cfg"].values() if v["checked"]]
        print(f"{t['task_id']:<18}{len(t['enabled_nodes']):>8}{len(t['disabled_nodes']):>8}  "
              f"{' · '.join(on)}")
    print(f"\n→ config/ss_task_binding.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
