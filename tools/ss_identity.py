#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🏷 流形引擎输出 topic 的**标识信息**块 (唯一依据现算, 不编数字)。

老倪 2026-10-14: 「先通过配置中心，配置成 插拔任务，然后运行状态空间，流形引擎的输出topic看到，
正在执行的任务、产品质数、主参数等标识信息」。

口径: 一帧物理量 (扭矩/势场/健康度) 单独看**不知道自己在为谁干活** ⇒ 每帧载荷都必须自带身份:
  ① 正在执行的任务  ← config/ss_task_binding.json 的 active_task → config/tasks/tasks.json
  ② 场景/站点       ← tools/ss_scene_switch.py 的唯一映射表 (任务→场景/SCN/颜色) + 任务 site
  ③ 产品 + 产品质数  ← src/lerobot/manifold/prime_structure.load_products()
                       (active_product / version_segment / prime / 能力数 / 能力质数签名)
  ④ 主参数          ← config/calib/zmax_manifold.json (M / dim / mode / diag) + 任务 overrides (工艺参数) + t_max
取不到的一律写 "唯一依据未登记" (绝不拿默认值糊); 每块都带 src, 可回读复核。

CLI:
    gui-venv311/bin/python tools/ss_identity.py            # 当前活跃任务/场景的标识块 (JSON)
    gui-venv311/bin/python tools/ss_identity.py --task TASK-06-TRAY
    gui-venv311/bin/python tools/ss_identity.py --flat     # 一行键=值 (给人看)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

F_TASKS = os.path.join(ROOT, "config", "tasks", "tasks.json")
F_BIND = os.path.join(ROOT, "config", "ss_task_binding.json")
F_MANIFOLD = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
REL = lambda p: os.path.relpath(p, ROOT)                                          # noqa: E731


def _load(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                             # noqa: BLE001
        return None


def active_task_id() -> str:
    """活跃任务唯一依据 = config/ss_task_binding.json (配置中心「活跃配置」写的那份)。"""
    return str((_load(F_BIND) or {}).get("active_task") or "")


def find_task(task_id: str = "") -> dict:
    d = _load(F_TASKS) or {}
    ts = d.get("tasks") if isinstance(d, dict) else d
    ts = ts or []
    tid = task_id or active_task_id()
    for t in ts:
        if str(t.get("task_id")) == tid:
            return t
    return {}


def scene_of(task_id: str) -> dict:
    """任务 → 场景/SCN/名字: 单一唯一依据 = tools/ss_scene_switch.py 的 TASK_SCENE。"""
    try:
        import ss_scene_switch as _s                                              # noqa: PLC0415
        m = (_s.TASK_SCENE or {}).get(str(task_id)) or {}
        return {"scn": m.get("scn") or "", "scene_name": m.get("scene") or "",
                "scene_color": m.get("color") or "", "src": "tools/ss_scene_switch.py:TASK_SCENE"}
    except Exception as e:                                                        # noqa: BLE001
        return {"scn": "", "scene_name": "", "scene_color": "",
                "src": "唯一依据未登记 (ss_scene_switch 读不到: %s)" % type(e).__name__}


def product_block() -> dict:
    """产品 + 产品质数 + 版本段 + 能力质数签名 (唯一依据 prime_structure.load_products)。"""
    out = {"product_id": "", "product_name": "", "version_segment": "", "product_prime": None,
           "n_capabilities": None, "cap_signature": None, "src": REL(
               os.path.join("config", "platform", "zmax_product.json"))}
    try:
        from lerobot.manifold import prime_structure as PS                        # noqa: PLC0415
        d = PS.load_products() or {}
        pid = str(d.get("active_product") or PS.active_product())
        pr = (d.get("products") or {}).get(pid) or {}
        sig = (d.get("capability_signatures") or {}).get(pid)
        if sig is None:
            sig = PS.cap_signature_of(pid)
        out.update({"product_id": pid, "product_name": pr.get("name") or "",
                    "version_segment": pr.get("version_segment") or "",
                    "product_prime": pr.get("prime"), "n_capabilities": len(pr.get("capabilities") or []),
                    "cap_signature": str(sig)})
    except Exception as e:                                                        # noqa: BLE001
        out["src"] = "唯一依据未登记 (prime_structure 读不到: %s)" % type(e).__name__
    return out


def main_params_block(metric_cfg: dict | None = None, task: dict | None = None) -> dict:
    """主参数 = 度量张量 M 尺度/形状 (config/calib/zmax_manifold.json) + 任务工艺 overrides + t_max。

    overrides 里既有力/深度这种**一句话参数**, 也有 pt.* 空间点这种长文本 ⇒ 载荷只带 ≤60 字符的标量项
    (最多 12 条), 其余只报**条数** (全量在 config/tasks/tasks.json#overrides, 不在这份载荷里灌).
    """
    m = metric_cfg if metric_cfg is not None else (_load(F_MANIFOLD) or {})
    met = (m.get("metric") or {}) if isinstance(m, dict) else {}
    t = task if task is not None else find_task()
    ov = (t.get("overrides") or {}) if isinstance(t, dict) else {}
    short, more = {}, 0
    for k, v in ov.items():
        sv = json.dumps(v, ensure_ascii=False)
        if len(sv) <= 60 and not str(k).startswith(("pt.", "pthist.")) and len(short) < 12:
            short[str(k)] = v
        else:
            more += 1
    return {"metric_M": m.get("M"), "metric_dim": met.get("dim"), "metric_mode": met.get("mode"),
            "metric_diag": met.get("diag"), "mapping": "配置单 → 主参数 M (tools/config_to_M.py: R1 dim/R2 mode/R3 形状/R5 scale)",
            "task_params": short, "task_params_more": more,
            "src": "%s + %s#overrides" % (REL(F_MANIFOLD), REL(F_TASKS))}


def identity(scene: str = "", task_id: str = "", metric_cfg: dict | None = None) -> dict:
    """组一份标识块 (给流形引擎输出载荷用)。scene 是 tap 里那帧的场景名, 原样带上便于对账。"""
    t = find_task(task_id)
    tid = str(t.get("task_id") or task_id or "")
    sc = scene_of(tid)
    if not tid:
        sc = dict(sc, src=sc.get("src", "") + " · 活跃任务唯一依据未登记")
    return {
        "task_id": tid or "唯一依据未登记",
        "task_name": str(t.get("name") or "唯一依据未登记"),
        "task_type": str(t.get("recipe_type") or "唯一依据未登记"),
        "scene": scene or sc.get("scn") or "唯一依据未登记",
        "scn": sc.get("scn") or "唯一依据未登记",
        "scene_name": sc.get("scene_name") or "唯一依据未登记",
        "site": str(t.get("site") or "唯一依据未登记"),
        "targets": t.get("targets") or {},
        **product_block(),
        "main_params": main_params_block(metric_cfg, t),
        "src": {"task": "%s:active_task → %s" % (REL(F_BIND), REL(F_TASKS)),
                "scene": sc.get("src"),
                "product": product_block_src(),
                "main_params": "config/calib/zmax_manifold.json + config/tasks/tasks.json#overrides"},
        "readonly": "只读标识 (不改画布/不下发动作; 与产品标识节点同源 prime_structure)",
    }


def product_block_src() -> str:
    return "src/lerobot/manifold/prime_structure.py:load_products → config/platform/zmax_product.json"


def flat(d: dict) -> list:
    """一行键=值 (给人看; 数字照唯一依据, 缺就是 唯一依据未登记)。"""
    mp = d.get("main_params") or {}
    return [
        ("任务", "%s · %s (%s)" % (d.get("task_id"), d.get("task_name"), d.get("task_type"))),
        ("场景", "%s · %s" % (d.get("scene"), d.get("scene_name"))),
        ("站点", d.get("site")),
        ("产品", "%s · %s · 版本段 %s" % (d.get("product_id"), d.get("product_name"), d.get("version_segment"))),
        ("产品质数", d.get("product_prime")),
        ("能力数 / 质数签名", "%s 项 / %s" % (d.get("n_capabilities"), str(d.get("cap_signature"))[:24] + "…")),
        ("主参数 M / dim / mode", "%s / %s / %s" % (mp.get("metric_M"), mp.get("metric_dim"), mp.get("metric_mode"))),
        ("工艺参数 (任务 overrides)", json.dumps(mp.get("task_params") or {}, ensure_ascii=False)),
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="流形引擎输出 topic 的标识块 (唯一依据现算)")
    ap.add_argument("--task", default="", help="指定任务 (默认取活跃配置)")
    ap.add_argument("--scene", default="", help="tap 里那帧的场景名 (默认按任务映射)")
    ap.add_argument("--flat", action="store_true", help="一行键=值")
    a = ap.parse_args(argv)
    d = identity(scene=a.scene, task_id=a.task)
    if a.flat:
        for k, v in flat(d):
            print("%-24s %s" % (k, v))
    else:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
