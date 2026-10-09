# -*- coding: utf-8 -*-
"""任务配置生成器 —— 配置中心的**主要工程配置** (老倪: "例如上下料的任务配置")。

任务 (Task) 在层级里的位置:
    能力(feature.dbc) → 工序配方(8 段 25 条, 全集) → **任务配置(子集 + 覆盖)** → 工单(一次执行) → 单件记录
    · 任务是**可复用的作业定义**: 选哪些配方段 + 参数覆盖 + 触发/循环策略 + 验收判据
    · 工单是任务的一次执行 (1 盘 = 1 工单, 1 件 = 1 记录)

任务配置字段 (缺一不许进真源):
    task_id · name · recipe_type · scene_ref · site · applies_segments(适用的段)
    · variants(物料粒度) · overrides(参数覆盖) · trigger(怎么启动) · loop(循环策略)
    · targets(验收判据) · orders_rule · binding_hint · safety(继承站点 Sys-0)

真源 (只读):
    flows/scenes_5jobs.json      5 个场景 (对象/步骤/性能目标)
    tools/build_sheet.py         工序配方 RECIPE_STEPS / 安全节
    config/calib/zmax_calib.json 站点工程配置 (用于标注阻塞)
输出:
    config/tasks/tasks.json      任务配置真源 (生成物, 勿手改)
用法:
    python3 tools/task_build.py [--check] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
SCENES = os.path.join(ROOT, "flows", "scenes_5jobs.json")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
OUT = os.path.join(ROOT, "config", "tasks", "tasks.json")

SEG_ALL = ["0 料源与来料状态", "1 取件", "2 姿态准备", "3 识别与工位对接",
           "4 放置/插入", "5 拔出/取回", "6 分拣与回位", "7 节拍与循环"]

# scene_type → (任务类型, 适用段, 排除段, 覆盖参数, 触发, 循环, 工单规则)
PLAN = {
    "handle": dict(
        task_type="上下料搬运", applies=[s for s in SEG_ALL if s not in ("4 放置/插入", "5 拔出/取回")],
        excluded=["4 放置/插入", "5 拔出/取回"],
        overrides={"pick.close_force": 3.0, "pick.lift_h": 30, "pick.retry": 2,
                   "src.orient": "料盘/治具按定位孔朝向",
                   "sort.pass_tray": "不适用(不涉及分拣)", "cyc.dual_arm": "协作(一臂取盘一臂对接)"},
        trigger="料盘到位信号 / 手动按钮", loop="整盘连续(12 件/盘); 满盘→空盘切换",
        orders_rule="1 盘 = 1 工单; 1 件 = 1 条记录",
        note="上下料: 取盘→配送→对接→回位; 不涉及插入/拔出 ⇒ 配方段 4/5 不适用"),
    "fw_loading": dict(
        task_type="插拔+固件校验", applies=SEG_ALL, excluded=[],
        overrides={"ins.depth": 35.0, "ins.force_ctrl": "Fz>1kHz, 力峰≤5N", "ins.retry": 1,
                   "pull.wait_hmi": True, "pick.close_force": 3.0, "sort.rule": "AOI 各站失败累计→NG"},
        trigger="来料盒就位 / 上游工位放行信号", loop="单件循环; 连续 2 次抓取失败停机",
        orders_rule="1 批 = 1 工单; 1 件 = 1 条记录",
        note="插入深度 35mm 判到位 end_pose.x>0.750 (实测判据)"),
    "bi_aging": dict(
        task_type="老化箱插拔", applies=SEG_ALL, excluded=[],
        overrides={"ins.depth": None, "ins.retry": 1, "pull.wait_hmi": False,
                   "cyc.takt": "见场景性能目标"},
        trigger="老化箱槽位放行信号", loop="按槽位序列循环", orders_rule="1 轮 = 1 工单",
        note="插入深度按老化箱规格 (待现场确认)"),
    "thermal_chamber": dict(
        task_type="热海柜体插拔(电口+光口)", applies=SEG_ALL, excluded=[],
        overrides={"ins.depth": None, "ins.retry": 1, "pull.wait_hmi": False},
        trigger="柜体门开信号", loop="电口→光口 顺序循环", orders_rule="1 轮 = 1 工单",
        note="电口/光口两套插拔参数 (待现场确认)"),
    "ats_test": dict(
        task_type="检测插接", applies=SEG_ALL, excluded=[],
        overrides={"ins.depth": None, "ins.retry": 1, "pull.wait_hmi": True,
                   "sort.rule": "测试结果 PASS/FAIL 分拣"},
        trigger="测试台就绪信号", loop="到货即测", orders_rule="1 批 = 1 工单",
        note="核心挑战场景: 测试读取成功率 ≥99.9%"),
}

TIER = {"12槽": "L1 料盘级", "12穴位": "L1 料盘级", "20穴位": "L1 料盘级",
        "4定位孔": "L2 治具级", "单颗": "L3 单颗级", "12槽·L1料盘级": "L1 料盘级",
        "4定位孔·L2治具级": "L2 治具级", "光模块单颗·L3治具内": "L3 单颗级"}


def _sha16(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return None


def _dig(d, path):
    cur = d
    for k in str(path).split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def variants_of(scene):
    """从场景对象里抽物料粒度 (L1 料盘 / L2 治具 / L3 单颗)。"""
    fallback = ((("单颗", "光模块单颗"), "L3 单颗级"), (("治具", "插座", "子板"), "L2 治具级"),
                (("料盘", "盒", "托盘"), "L1 料盘级"))
    out, seen = [], set()
    for o in scene.get("objects", []):
        role, nm = str(o.get("role", "")), str(o.get("name", ""))
        lvl = TIER.get(role) or TIER.get(role.split("·")[-1])
        if not lvl:
            for keys, cand in fallback:
                if any(k in role or k in nm for k in keys):
                    lvl = cand
                    break
        if lvl and lvl not in seen:
            seen.add(lvl)
            out.append({"level": lvl, "name": o.get("name"), "role": role,
                        "size_mm": o.get("size_mm"), "pos": o.get("pos")})
    order = {"L1 料盘级": 0, "L2 治具级": 1, "L3 单颗级": 2}
    return sorted(out, key=lambda x: order.get(x["level"], 9))


def build(scene, calib, i):
    p = PLAN.get(scene["scene_type"], PLAN["ats_test"])
    gaps = [k for k, v in (("T_base_cam", "T_base_cam.value"), ("plane_z", "plane_z.value"),
                           ("cell_geometry.points", "cell_geometry.points"))
            if _dig(calib, v) is None]
    return {
        "task_id": f"TASK-{i:02d}-{scene['scene_id'].split('-', 2)[2]}",
        "name": scene["name"], "recipe_type": p["task_type"],
        "scene_ref": scene["scene_id"], "site": "SITE-A.ST11",
        "applies_segments": p["applies"], "excluded_segments": p["excluded"],
        "steps": [{"t": s.get("t"), "dur": s.get("dur"), "name": s.get("name"),
                   "desc": s.get("desc"), "force": s.get("force")}
                  for s in scene.get("steps", [])],
        "variants": variants_of(scene),
        "overrides": p["overrides"],
        "trigger": p["trigger"], "loop": p["loop"], "targets": scene.get("targets", {}),
        "orders_rule": p["orders_rule"],
        "binding_hint": "逐层选型(L2/L3/L4) + 站点 SITE-A.ST11; 真机域模型需站点几何齐",
        "safety": "继承站点 Sys-0 (急停/力阈值 Fz>5N/关节限位±3rad/光幕) — 任务不可覆盖",
        "blocked_by_site": gaps, "_note": p["note"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sc = json.load(open(SCENES, encoding="utf-8"))["scenes"]
    try:
        calib = json.load(open(CALIB, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        calib = {}
    tasks = [build(s, calib, int(s["scene_id"].split("-")[1])) for s in sc]
    doc = {"schema": "zmax-tasks/1.0",
           "note": "任务配置真源 (生成物: scenes_5jobs + 工序配方 + 站点配置)。任务 = 配方段子集 + 参数覆盖 + 触发/循环。",
           "sources": {"flows/scenes_5jobs.json": _sha16(SCENES),
                       "config/calib/zmax_calib.json": _sha16(CALIB),
                       "recipe": "tools/build_sheet.py#RECIPE_STEPS (8 段)"},
           "counts": {"tasks": len(tasks), "segments_total": len(SEG_ALL)},
           "tasks": tasks}
    txt = json.dumps(doc, ensure_ascii=False, indent=1)

    if a.check:
        old = open(OUT, encoding="utf-8").read() if os.path.isfile(OUT) else None
        same = old == txt
        print(f"  {'✅' if same else '❌'} config/tasks/tasks.json "
              f"({'内容一致' if same else '不一致 — 真源变了, 需重生成'})")
        return 0 if same else 2
    if a.json:
        print(txt); return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(txt)
    print(f"任务配置: {len(tasks)} 条 → config/tasks/tasks.json")
    print(f"{'任务ID':<22}{'类型':<16}{'段':>3}{'物料粒度':>6}  目标 / 阻塞")
    print("-" * 96)
    for t in tasks:
        print(f"{t['task_id']:<22}{t['recipe_type']:<16}{len(t['applies_segments']):>3}"
              f"{len(t['variants']):>6}  {t['targets']}"
              f"{'  ⛔缺站点几何' + str(len(t['blocked_by_site'])) + '项' if t['blocked_by_site'] else '  ✅'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
