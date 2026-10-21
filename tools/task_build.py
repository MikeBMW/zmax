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
sys_path_tools = os.path.join(ROOT, "tools")
if sys_path_tools not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path_tools)
import pt_pose as _pose                                                     # noqa: E402  姿态 a b c 唯一口径

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
    "tray_filling": dict(
        task_type="摆盘取放",
        applies=[s for s in SEG_ALL if s not in ("5 拔出/取回",)],
        excluded=["5 拔出/取回"],
        overrides={"pick.vac_establish_ms": 200, "pick.hold_s": 5, "pick.retry": 3,
                   "place.down_force_max": "配方上限(防压伤)", "place.angle_tol_deg": 1.0,
                   "src.orient": "周转盘槽位朝向", "cyc.takt": "单颗 ≤3.15s (PVT)",
                   "sort.pass_tray": "不适用(摆盘不分拣)"},
        trigger="满料周转盘到位 / Tray 盘满或周转盘空信号",
        loop="单颗循环; 周转盘空或 Tray 满 → 上报待人工补料/下料",
        orders_rule="1 盘 = 1 工单; 1 颗 = 1 条记录",
        note="摆盘: 周转盘→上料Tray盘取放; 不涉及插入/拔出 ⇒ 配方段 5 不适用; "
             "CT 起止口径写死=从吸取离盘到下一位就位"),
    "ar_aoi": dict(
        task_type="光学质量检测",
        # 检测型任务: 只用到 来料状态/识别对接/分拣回位/节拍 四段 (取件/姿态/插拔不适用)
        applies=["0 料源与来料状态", "3 识别与工位对接", "6 分拣与回位", "7 节拍与循环"],
        excluded=["1 取件", "2 姿态准备", "4 放置/插入", "5 拔出/取回"],
        overrides={"aoi.port_gold": 10082, "aoi.port_surface": 10083,
                   "aoi.cam": "RealSense D435 (AR 底图 · 独占 :8797)",
                   "aoi.weights": "models/yolo_peg_live.pt (在役软链)",
                   "aoi.side_fix": "侧边位置修正 Delta x 一次给全",
                   "aoi.judge_png": "判据图 914x348 等比(真实金手指 ROI · 不拉伸) 可导出",
                   "sort.rule": "AOI 判决 PASS/FAIL 累计→NG"},
        trigger="AR 场景就位 (RealSense 有帧) / 工控机 AOI 就绪信号",
        loop="单件循环; 判决 + 判据图落盘后进入下一件",
        orders_rule="1 件 = 1 条记录 (判据图 + 判决 + 时间戳)",
        # 老倪: 「模型对应 Automated Optical Inspection 自动光学检测 的 L5 自主进化程序」
        model_ref={"layer": "L5",
                   "program": "Automated Optical Inspection 自动光学检测 · L5 自主进化程序",
                   "entry": "tools/l5_plan_and_gen.py + tools/aoi_link.py (工控机 10082/10083 客户端)",
                   "charter": "docs/L5_AUTONOMOUS_EVOLUTION.md",
                   "node": "🔍 光学质量检测 (画布节点 · 发出 AOI 全部话题)",
                   "capability": "BO_ B5 光学质量检测"},
        note="AOI: AR 实拍底图 + 工控机 AOI 联合检查 (金手指 10082 / 表面 10083) + 光模块检测 + 相机系 3D 位姿; "
             "不涉及取件/姿态/放置/拔出 ⇒ 配方段 1/2/4/5 不适用; 模型 = L5 自主进化程序"),
    # 🆕 2026-10-21: 光纤端面检测及清理设备 (技协 rev1.0) 的上料缓存工位
    #   对应 /autoLight 第 1~3 步: 人工上料 → 缓存1 → 缓存2 → 主流线缓存位(顶升 + 分离接料)
    "al1_cache": dict(
        task_type="上料缓存·载具搬运取放",
        applies=["0 料源与来料状态", "1 取件", "3 识别与工位对接", "7 节拍与循环"],
        excluded=["2 姿态准备", "4 放置/插入", "5 拔出/取回", "6 分拣与回位"],
        overrides={
            "src.carrier": "载具承载 1PCS/载具 (MPO-8FC / MPO-16FC)",
            "src.cache_max": 15,
            "pick.magnet": "磁吸锁附 (磁吸板×2) + 定位轴套×2 + 夹具初定位销",
            "pick.float_mm": 0.5,
            "scan.bind": "产品二维码 ↔ 载具二维码 (全链路追溯)",
            "lift.sep": "主流线顶升模组顶升 + 分离模组伸出接料",
            "cyc.takt": "CT ≤70s (8-FC) / ≤134s (16-FC); UPH ≥51 / ≥26; OEE ≥85%",
            "sort.pass_tray": "不适用 (分拣在流程第 7 步, 本任务不含)",
        },
        trigger="人工上料到位 / 缓存缺料信号",
        loop="单载具循环; 载具托盘缓存 ≤15PCS 满则停送",
        orders_rule="1 载具 = 1 条记录 (产品码 ↔ 载具码 + 检测结果)",
        note="光纤端面检测及清理设备(技协 rev1.0) 第 1~3 步: 人工上料→缓存1→缓存2→主流线缓存位; "
             "无姿态/插入/拔出/分拣 ⇒ 配方段 2/4/5/6 不适用; 数据源=载具承载 1PCS/载具",
    ),
}


# ── 🥽 任务7 AOI 示教点位(含"更新记录")写进任务配置 (老倪 2026-10-12) ──────────────────
def teach_point_overrides(dir_rel="reports/aoi_points"):
    """把示教点位台账写进任务配置的 overrides —— 让「金手指点1 的位置」在**配置中心的配置里**就能查到。

    老倪: 「更新记录这个 金手指点1 的位置, 要在配置中心的配置里找到这个数据」
      · pt.<点名>     = 位置(x,y,z) + 记录时间 + 真源文件      (读 reports/aoi_points/<点名>.json)
      · pthist.<点名> = 更新次数 + 最近一次 old→new           (读 <点名>.history.jsonl)
      · pt.dir        = 台账目录
    只**读**台账生成配置(不反向写台账): 台账改了重跑 build 即同步, 单一真源不打架。
    """
    # 姿态 a b c 用**唯一口径** tools/pt_pose.py(8793 页面 / 记录脚本 / 配置中心 同一份实现)——
    #   老倪 2026-10-12: 「配置中心的点, 除了位置, 还得有 a b c, 6 个数字都要记录」。
    def _abc_s(rec):
        return _pose.abc_str(rec)

    out = {"pt.dir": dir_rel}
    # 🔲 2026-10-12 老倪: 「配置中心, 也要有空间点1~7 的配置位置」—— 空间点真源是
    #   data/skills/l2_atomic/space_points.json (8793 标记模式下记的 7+1 个空间点), 只读摊进配置:
    #   pt.空间点N = x/y/z + 记录时间 + 真源文件 ⇒ 配置中心那张表自动多出这几行(单一真源, 不另写)。
    sp_rel = "data/skills/l2_atomic/space_points.json"
    out["pt.space_dir"] = sp_rel
    try:
        with open(os.path.join(ROOT, sp_rel), encoding="utf-8") as fh:
            spj = json.load(fh)
        for k, v in sorted((spj.get("points") or {}).items()):
            pos = (v or {}).get("pos") or []
            if not isinstance(pos, list) or len(pos) != 3:
                continue
            ks = str(k)
            nm = ("空间点" + ks[5:]) if ks.startswith("space") else ks
            out["pt." + nm] = ("x=%.6f y=%.6f z=%.6f m · %s · 记录 %s · %s"
                               % (pos[0], pos[1], pos[2], _abc_s(v),
                                  (v or {}).get("recorded_at") or "-", sp_rel))
    except Exception:                                                           # noqa: BLE001
        pass
    d = os.path.join(ROOT, dir_rel)
    try:
        files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    except OSError:
        return out
    for f in files:
        try:
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                j = json.load(fh)
        except Exception:                                                       # noqa: BLE001
            continue
        pos = j.get("pos") or []
        if not isinstance(pos, list) or len(pos) != 3:
            continue
        nm = str(j.get("point") or f[:-5])
        out["pt." + nm] = ("x=%.6f y=%.6f z=%.6f m · %s · 记录 %s · %s/%s"
                           % (pos[0], pos[1], pos[2], _abc_s(j), j.get("recorded_at") or "-", dir_rel, f))
        hp = os.path.join(d, nm + ".history.jsonl")
        if os.path.exists(hp):
            lines = []
            try:
                with open(hp, encoding="utf-8") as fh:
                    for x in fh.read().splitlines():
                        if x.strip():
                            lines.append(json.loads(x))
            except Exception:                                                   # noqa: BLE001
                lines = []
            if lines:
                last = lines[-1]
                op = (last.get("old") or {}).get("pos") or []
                np_ = last.get("new_pos") or []
                out["pthist." + nm] = ("%d 次更新 · 最近 %s: %s → %s"
                                       % (len(lines),
                                          last.get("replaced_at") or last.get("ts") or "-",
                                          ("(%.6f, %.6f, %.6f)" % tuple(op)) if len(op) == 3 else "?",
                                          ("(%.6f, %.6f, %.6f)" % tuple(np_)) if len(np_) == 3 else "?"))
    return out


_PT = teach_point_overrides()
PLAN["ar_aoi"]["overrides"].update(_PT)

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
    p = PLAN.get(scene["scene_type"])
    if p is None:
        # 🚫 无配方计划(PLAN)的场景**不再静默套 ATS 配方** —— 那会造出一条"类型/段/覆盖全错"的任务。
        #    场景照旧留在 scenes_5jobs.json (只读真源), 只是不入任务清单; 要建任务 = 在 PLAN 里加一条。
        return None
    gaps = [k for k, v in (("T_base_cam", "T_base_cam.value"), ("plane_z", "plane_z.value"),
                           ("cell_geometry.points", "cell_geometry.points"))
            if _dig(calib, v) is None]
    out = {
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
    if p.get("model_ref"):            # 任务绑定的模型 (老倪: 任务7 AOI → L5 自主进化程序)
        out["model_ref"] = p["model_ref"]
    return out


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
    tasks, skipped = [], []
    for s in sc:
        t = build(s, calib, int(s["scene_id"].split("-")[1]))
        (tasks.append(t) if t else skipped.append("%s (%s)" % (s["scene_id"], s["scene_type"])))
    if skipped:
        print("⏭ 无配方计划(PLAN), 未入任务清单: " + " · ".join(skipped)
              + "  —— 要建任务请在 tools/task_build.py 的 PLAN 里加一条")
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
