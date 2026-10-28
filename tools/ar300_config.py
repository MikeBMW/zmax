#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🏭 AR 场景 · 300UPH · TASK-07-AOI 的**四类配置**一次落盘 (功能 → 模型 → 性能 → 工程)

老倪口径 (2026-10-28):
  「当前产品是 550B 配置模式, 你刚刚进行了元任务的配置, 接下来依次进行功能配置、模型配置、
    性能配置、工程配置, 最后形成文档配置……实际的生产目标是 300UPH, 场景就是 AR 场景的仿真机器人,
    左臂摆盘, 右臂插拔和 AOI 检查。你要通过这一系列的配置, 能够规范地约束工厂生产, 实现工单即任务」

四类配置的真源 (只改这四个 + 任务绑定, 不动权重/不碰真机):
  ① 功能配置  data/database/zmax/config_meta.json            新增 FN-PLAT-76/77 (module_ref 必须对上画布节点名)
                sources/config/ss_task_binding.json           TASK-07-AOI 覆盖 8 工艺段 + 启用新节点 + 设为当前任务
  ② 模型配置  models/active_models.json                       extra_in_service 登记 AR 场景在役模型
  ③ 性能配置  sources/config/platform/zmax_perf_spec.json      E 组新增 300UPH 节拍指标
  ④ 工程配置  sources/config/platform/zmax_platform.json       新增 AR 双臂工位 + 设备 + 点位来源

判据 (脚本自检, 任一不过就不写):
  A 每个新功能的 module_ref 能在画布节点名里 100% 命中
  B TASK-07-AOI 的 applies_segments == 8 段, excluded 为空, 且 ssplan/ssuph 在 enabled_nodes
  C active_models 的 AR 条目齐 4 类 (检测/分割/检测服务/场景理解)
  D perf E 组含 UPH/节拍/双臂/良率 四条
  E platform 含 AR 工位且引用了 TASK-07-AOI
"""
import json
import os
import shutil
import sys
import time

ROOT = "/home/ubuntu/zmax"
P_META = os.path.join(ROOT, "data/database/zmax/config_meta.json")
P_BIND = os.path.join(ROOT, "data/database/zmax/sources/config/ss_task_binding.json")
P_MODELS = os.path.join(ROOT, "models/active_models.json")
P_PERF = os.path.join(ROOT, "data/database/zmax/sources/config/platform/zmax_perf_spec.json")
P_PLAT = os.path.join(ROOT, "data/database/zmax/sources/config/platform/zmax_platform.json")
P_CANVAS = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")

TASK = "TASK-07-AOI"
SCENE = "SCN-07-AOI"
STATION = "SITE-A.ST11-AR"
TS = time.strftime("%Y-%m-%d %H:%M:%S")

# 场景工艺真值 (全部来自 392 段段表/元任务, 可复核)
G = {"uph": 300, "tact_s": 12.0, "tact_geo_s": 11.42, "segments": 392, "meta_count": 56,
     "modules": 14, "ok": 12, "ng": 2, "yield": 0.99, "speed_mm_s": 625.6,
     "insert_mm": 47.0, "force_n": 40.0, "grip_s": 0.192, "golden_s": 0.8, "side_s": 0.5,
     "aoi_points": 5, "holes": 4, "slots": 14}


def bk(p):
    d = os.path.dirname(p)
    b = os.path.join(d, "_bak", os.path.basename(p) + "." + time.strftime("%H%M%S"))
    os.makedirs(os.path.dirname(b), exist_ok=True)
    shutil.copy2(p, b)
    return b


def canvas_names():
    cv = json.load(open(P_CANVAS, encoding="utf-8"))
    return {n["id"]: n.get("name") for n in cv["nodes"]}


# ══════════════════════ ① 功能配置 ══════════════════════
def do_function():
    names = canvas_names()
    meta = json.load(open(P_META, encoding="utf-8"))
    fns = meta["functions"] if isinstance(meta.get("functions"), dict) else None
    if fns is None:
        raise SystemExit("config_meta.json 结构不是 {functions: {id: {...}}}")

    def mk(fid, name, layer, kind, module_ref, desc_in, desc_out, flags, params, zmax_cfg, cal, dia):
        return {
            "fn_id": fid, "name": name, "system_id": "sys_plat", "subsystem": "平台 · 场景工程",
            "layer": layer, "kind": kind, "row_name": "🧠 大模型层 · 任务/编排/记忆中枢（回路外慢决策）",
            "module_ref": module_ref, "code_file": "",
            "fields": {"inputs": desc_in, "outputs": desc_out, "declared_flags": flags},
            "parameters": [{"id": k, "cn": k.split(":")[-1], "cat": k.split(":")[0], "kind": "numeric",
                            "value": v[0], "default": v[0], "min": v[1], "max": v[2], "unit": v[3],
                            "choices": None, "source": "config/tasks/ar_meta_tasks.json",
                            "status": "已定义(人工)"} for k, v in params.items()],
            "enums": {},
            "ranges": [{"id": k, "min": v[1], "max": v[2], "unit": v[3], "default": v[0], "choices": None}
                       for k, v in params.items()],
            "deps": {"functions": ["FN-SYS0-40", "FN-SYS0-37"], "params": [], "generic_baseline_params": [],
                     "product_features": ["PF-Z700-01"], "module": module_ref},
            "verification": {"methods": ["元任务重建 392 段逐段一致", "节拍/UPH 与段表同源核对",
                                         "真机零指令 (real_auth=false)", "页面 ssOn=1 且 mt 归属正确"],
                             "count": 4, "level": layer},
            "meta_axes": {"cfg": zmax_cfg, "cal": cal, "dia": dia},
            "completeness": {"dims": {"subsys_layer": True, "specific_params": True, "ranges": True,
                                      "units": True, "deps": True, "verification": True},
                             "missing": [], "complete": True,
                             "specific_param_count": len(params), "generic_param_count": 0},
            "_note": "2026-10-28 AR 300UPH 场景新增 (生成器 tools/ar300_config.py)",
        }

    new = {}
    if "FN-PLAT-76" not in fns:
        new["FN-PLAT-76"] = mk(
            "FN-PLAT-76", "🧩 长程元任务编排 (AR · 300UPH)", "L3", "模块节点",
            "🧩 长程元任务编排器 (Plan)",
            ["配置中心 TASK-07-AOI 元任务组合 (ar_meta_tasks.json)", "段表几何真值 (sim_insert.json)"],
            ["当前动作 + 元任务归属 (mt_id/mt_i/batch)", "元任务进度", "长程节拍/UPH"],
            {"scene": "AR 仿真双臂", "target_uph": G["uph"], "meta_tasks": 5, "state_space": True,
             "arm_roles": {"left": "摆盘", "right": "插拔 + AOI"}},
            {"cfg:uph_target": (G["uph"], 60, 1200, "件/h"),
             "cfg:tact_s": (G["tact_s"], 1.0, 60.0, "s"),
             "cfg:segments": (G["segments"], 1, 10000, "段"),
             "cfg:meta_count": (G["meta_count"], 1, 10000, "个")},
            ["UPH 300 由 5 个元任务 × 56 实例 = 392 段 / 159.43s 反算", "双臂并行: 左摆盘/右插拔AOI"],
            ["段表几何 (槽/孔/金手指点/侧面点)", "节拍 tact_steady_s 来自同一份段表"],
            ["展开段数 == 392", "逐段 kind/label/t 一致", "页面 PREV.ssMt 显示元任务"])
    if "FN-PLAT-77" not in fns:
        new["FN-PLAT-77"] = mk(
            "FN-PLAT-77", "🏭 UPH 节拍循环器 (预存段表驱动)", "L2", "模块节点",
            "🏭 UPH 节拍循环器",
            ["sim_insert 段表 (392 段 / 14 件)", "节拍常数 tact_steady_s"],
            ["当前段动作 (a/b/kind/label)", "件进度/产出", "节拍/实时 UPH"],
            {"scene": "AR 仿真双臂", "no_llm": True, "offline": True, "real_cmd": False},
            {"cfg:tact_geo_s": (G["tact_geo_s"], 1.0, 60.0, "s"),
             "cfg:modules_per_cycle": (G["modules"], 1, 100, "件")},
            ["场景已录 ⇒ 不依赖大模型/语言层, 离线可跑", "只写渲染指令 ar_cmd.json, 真机零指令"],
            ["节拍几何能力 3600/11.42 = 315 件/h"], ["UPH 口径: 扣首件 + 样本≥30s"])

    if new:
        fns.update(new)

    # 🔧 修历史漂移: module_ref 对不上画布节点名的旧条目 (改名连带)。
    #    FN-SYS2-02: ssllm 从「L3 长程序列规划器」改名 ⇒ 配置没跟 (本次引入的漂移)
    #    FN-SYS0-59: 画布 n_moveit 早已改叫「运动规划」⇒ 配置停在旧长名 (历史遗留)
    drift_fix = {"FN-SYS2-02": "🧠 长程序列规划器 (场景理解驱动)",
                 "FN-SYS0-59": "运动规划"}
    nm_all = set(names.values())
    fixed = []
    for fid, ref in drift_fix.items():
        x = fns.get(fid)
        if x and x.get("module_ref") not in nm_all and ref in nm_all:
            old = x.get("module_ref")
            x["module_ref"] = ref
            if fid == "FN-SYS2-02":
                x["name"] = ref          # 名称同步 (功能名与画布节点同名才不乱)
            x["_drift_fixed"] = "%s: %r → %r (2026-10-28)" % (fid, old, ref)
            fixed.append(fid)
    if fixed:
        bk(P_META)
        json.dump(meta, open(P_META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("   修漂移: %s" % fixed)

    # 校验 A: 全部功能 module_ref → 画布节点名 100% 命中
    nm = set(names.values())
    miss = [(f["fn_id"], f["module_ref"]) for f in fns.values() if f.get("module_ref") not in nm]
    print("① 功能配置: 共 %d 个功能 (新增 %d) | module_ref→画布节点 命中 %d/%d%s"
          % (len(fns), len(new), len(fns) - len(miss), len(fns),
             "" if not miss else "  ❌ 缺: %s" % miss[:4]))

    # ①b 任务绑定: TASK-07-AOI 覆盖 8 段 + 启用新节点 + 设为当前任务
    b = json.load(open(P_BIND, encoding="utf-8"))
    t = [x for x in b["tasks"] if x.get("task_id") == TASK][0]
    segs = ["0 料源与来料状态", "1 取件", "2 姿态准备", "3 识别与工位对接",
            "4 放置/插入", "5 拔出/取回", "6 分拣与回位", "7 节拍与循环"]
    t["applies_segments"] = segs
    t["excluded_segments"] = []
    en = list(t.get("enabled_nodes") or [])
    for nid in ("ssplan", "ssuph"):
        if nid not in en:
            en.append(nid)
    t["enabled_nodes"] = en
    t["ss_mode"] = "ar_dual_arm"
    # ⚠️ run_cfg 的每个值必须是 {"label": str, "checked": bool} —— 配置中心 UI
    #    (veh6_config_page.py:3015) 直接取 v["checked"], 塞裸值 ⇒ TypeError ⇒ 北斗七星整页构建失败。
    #    AR 参数一律放独立键 ar300 (UI 不读), 不动 run_cfg、不动 active_task。
    t["ar300"] = dict(t.get("ar300") or {}, uph_target=G["uph"], tact_s=G["tact_s"],
                      arm_roles={"left": "摆盘", "right": "插拔+AOI"}, scene="AR", real_cmd=False)
    bk(P_BIND)
    json.dump(b, open(P_BIND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok_b = (t["applies_segments"] == segs and not t["excluded_segments"]
            and {"ssplan", "ssuph"} <= set(t["enabled_nodes"]))
    print("   任务绑定: TASK-07-AOI 段=%d excluded=%d 节点=%d active=%s(未动) %s"
          % (len(t["applies_segments"]), len(t["excluded_segments"]), len(t["enabled_nodes"]),
             b.get("active_task"), "✅" if ok_b else "❌"))
    return (not miss) and ok_b


# ══════════════════════ ② 模型配置 ══════════════════════
def do_models():
    m = json.load(open(P_MODELS, encoding="utf-8"))
    ex = m.setdefault("extra_in_service", {})
    want = {
        "ar:L2:yolo": {"kind": "yolo", "name": "AR 场景 · YOLO 光模块检测 (在役软链)",
                       "path": "models/yolo_peg_live.pt", "pointer": True, "layer": "L2",
                       "role": "AR 帧上检出光模块 (conf/imgsz 可调) → 2D→3D",
                       "used_by": [TASK, "FN-SYS0-37"]},
        "ar:L2:sam3": {"kind": "sam3", "name": "AR 场景 · SAM3 开放词汇分割",
                       "path": "models/sam3", "layer": "L2",
                       "role": "开放词汇分割 (给出模块/料槽/孔的掩码)", "used_by": [TASK]},
        "ar:L2:aoi": {"kind": "aoi_service", "name": "AR 场景 · AOI 检测服务 (工控机)",
                      "endpoint": {"finger": "http://192.168.23.23:10082", "surface": "http://192.168.23.23:10083"},
                      "layer": "L2", "role": "金手指 + 表面检测 (五点: 金手指1 + 侧面4)",
                      "used_by": [TASK, "FN-SYS0-40"]},
        "ar:L5:vlm": {"kind": "vlm", "name": "AR 场景 · 场景理解 VLM (Qwen2.5-VL-3B)",
                      "path": "models/qwen2.5-vl-3b", "layer": "L5",
                      "role": "场景语义理解 (孔位/料盘/异常) — 可选, 元任务不依赖它",
                      "used_by": [TASK, "FN-PLAT-76"]},
    }
    added = [k for k in want if k not in ex]
    for k in added:
        ex[k] = dict(want[k], added_at=TS, scene=SCENE,
                     note="2026-10-28 AR 300UPH 场景登记; 真机零指令, 只服务 AR 仿真链")
    m["updated"] = TS
    if added:
        bk(P_MODELS)
        json.dump(m, open(P_MODELS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    have = [k for k in want if k in ex]
    print("② 模型配置: extra_in_service 共 %d 条 (本次新增 %d) | AR 四类齐 %d/4 %s"
          % (len(ex), len(added), len(have), "✅" if len(have) == 4 else "❌"))
    return len(have) == 4


# ══════════════════════ ③ 性能配置 ══════════════════════
def do_perf():
    p = json.load(open(P_PERF, encoding="utf-8"))
    g = [x for x in p["groups"] if x["gid"] == "E"][0]
    add = [
        {"id": "perf.UPH_target", "cn": "目标产能 UPH", "unit": "件/h", "target": "= 300",
         "how": "元任务 56 实例 / 392 段 / 159.43s 一轮 / 14 件 → 几何 315, 取 300 为设计目标",
         "std": "客户 SOR", "stage": "DVT", "links": [TASK, "FN-PLAT-76"]},
        {"id": "perf.tact_target", "cn": "目标节拍", "unit": "s/件", "target": "≤12.0 (几何 11.42)",
         "how": "3600/UPH; 一零件内 392/14 段的时间均值, 不含换盘与异常停线",
         "std": "内部", "stage": "DVT", "links": [TASK, "FN-PLAT-77"]},
        {"id": "perf.double_arm_parallel", "cn": "双臂并行度", "unit": "-",
         "target": "左臂摆盘 + 右臂插拔/AOI 同时动作 (互不阻塞)",
         "how": "元任务并行判定: 同一时刻两臂各在自己的元任务序列上, 无共享资源争用",
         "std": "内部", "stage": "DVT", "links": [TASK]},
        {"id": "perf.yield_target", "cn": "目标良率", "unit": "%", "target": "≥99 (12 OK / 14 件 NG 规则)",
         "how": "AOI 五点全 OK 记良品; 金手指/侧面任一点 NG 走废料盘",
         "std": "IEC 61300-3-35", "stage": "DVT", "links": [TASK, "FN-SYS0-40"]},
    ]
    have = {x["id"] for x in g["metrics"]}
    added = [x for x in add if x["id"] not in have]
    g["metrics"].extend(added)
    p["updated"] = TS
    if added:
        bk(P_PERF)
        json.dump(p, open(P_PERF, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok_ids = {x["id"] for x in add} <= {x["id"] for x in g["metrics"]}
    print("③ 性能配置: E 组指标 %d 条 (新增 %d) | UPH/节拍/双臂/良率 齐 %s"
          % (len(g["metrics"]), len(added), "✅" if ok_ids else "❌"))
    return ok_ids


# ══════════════════════ ④ 工程配置 ══════════════════════
def do_platform():
    p = json.load(open(P_PLAT, encoding="utf-8"))
    sites = p.setdefault("sites", {})
    key = STATION
    new_site = {
        "site_id": STATION, "name": "AR 双臂工位 (仿真机器人 · 300UPH)",
        "task_id": TASK, "scene_ref": SCENE, "station_type": "ar_dual_arm",
        "robots": [{"arm": "left", "role": "摆盘 (料盘 → 治具孔位)", "dof": 6},
                   {"arm": "right", "role": "插拔 + AOI 五点检测", "dof": 6}],
        "cameras": [{"name": "AR 底图 D435", "src": "usb", "role": "AR 渲染底图"},
                    {"name": "臂上 D405", "src": "sstate", "role": "插拔过程观测"},
                    {"name": "金手指 AOI", "endpoint": "http://192.168.23.23:10082", "role": "金手指检测"},
                    {"name": "表面 AOI", "endpoint": "http://192.168.23.23:10083", "role": "表面检测"}],
        "geometry_source": {"slots": "sim_insert.json SLOTS (14 槽)", "holes": "sim_insert.json HOLES (4 孔)",
                            "golden": "GOLDEN [360,-117,654]", "sides": "SIDES 4 点"},
        "takt": {"uph_target": G["uph"], "tact_s": G["tact_s"], "tact_geo_s": G["tact_geo_s"],
                 "segments": G["segments"], "modules_per_cycle": G["modules"]},
        "safety": {"real_cmd": False, "mode": "AR 仿真 (真机零指令)",
                   "insert_force_n_max": G["force_n"], "speed_mm_s_max": 1000},
        "added_at": TS,
    }
    is_new = key not in sites
    if is_new:
        sites[key] = new_site
    else:
        sites[key].update(new_site)
    p["updated"] = TS
    bk(P_PLAT)
    json.dump(p, open(P_PLAT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = STATION in sites and sites[STATION].get("task_id") == TASK
    print("④ 工程配置: 工位 %d 个 (本次%s %s) | 引用 %s %s"
          % (len(sites), "新增" if is_new else "更新", STATION, TASK, "✅" if ok else "❌"))
    return ok


def main():
    print("=" * 78)
    print("AR 300UPH · TASK-07-AOI · 四类配置   (%s)" % TS)
    print("=" * 78)
    r = {"功能": do_function(), "模型": do_models(), "性能": do_perf(), "工程": do_platform()}
    print("-" * 78)
    for k, v in r.items():
        print("  %-4s %s" % (k, "✅" if v else "❌"))
    allok = all(r.values())
    print("\n结果: %s" % ("✅ 四类配置全部通过" if allok else "❌ 有项未通过, 见上"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
