#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「泰国摆盘项目 · System 1 配置」落进平台真源 (2026-10-10)

只改两处人工真源, 全部走备份 → 写入 → 回读核验:
  ① config/platform/zmax_platform.json
     · subsystems[sys1]  : rows / kpi / axes(cfg,cal,dia) —— 子系统配置真源 (= 配置中心「功能/性能」域 axes 来源)
     · product_features  : 追加 PF-Z100-09..13 摆盘功能清单 (供应链可逐条报价/验收)
  ② flows/scenes_5jobs.json + tools/task_build.py
     · 追加 SCN-06-TRAY 摆盘场景 + 任务计划 -> config/tasks/tasks.json
生成物 (config/tasks/tasks.json · config/mcd/*) 由各自生成器重算, 不手改。
"""
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAT = os.path.join(ROOT, "config", "platform", "zmax_platform.json")
SCENES = os.path.join(ROOT, "flows", "scenes_5jobs.json")
TS = time.strftime("%Y%m%d_%H%M%S")


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def jdump(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write("\n")


def backup(p):
    b = p + ".bak_" + TS
    shutil.copy2(p, b)
    return b


# ─────────────────────────────────────────────────────────────
# ① 平台真源: System 1 配置 + 摆盘功能清单
# ─────────────────────────────────────────────────────────────
SYS1_ROWS_ADD = [
    "🚀 L3 摆盘作业 (泰国项目) · 周转盘 → 上料 Tray 盘 取放循环",
]
SYS1_KPI_ADD = {
    "摆盘节拍": "单颗 CT ≤3.15s (PVT) / ≤8s (DVT) / ≤20s (EVT)",
    "摆盘成功率": "≥99% (PVT) / ≥95% (DVT) / 90% (EVT) · 人工干预即记不完整成功",
    "取放精度": "单边 ≤1mm · 角度 ≤1° (腕部相机 0.1–0.6m 区间内)",
    "连续作业": "连续自主 ≥12 盘周转盘 (硬下限 ≥6)",
    "换型": "换型 ≤30min · 新型号配置/学习 ≤3h",
}
SYS1_CFG_ADD = [
    "摆盘配方: 上料 Tray 盘 30 槽 / 4# 周转盘 规格与槽距 (固化项), 光照等柔性项由感知自适应",
    "光模块型号配方表 (12+ 型号: 100G/400G/800G · QSFP-DD/OSFP 尺寸与防呆槽)",
    "取放时序与力限 (吸附建立 ≤200ms · 保持 ≥5s · 放置下压上限)",
    "抓取顺序策略 (行优先/最短路径) 与选槽策略 (避开已占槽 · 预留槽)",
    "异常策略表 (抓取失败/槽位异常/工位被占/放入受阻): 自动重试 ≤3 → 退回安全位 → 告警",
    "断点续作开关与断点粒度 (工序阶段/抓取状态/物料 SN)",
    "推理步频 (每 N 步真推理) — 节拍与精度的折衷旋钮",
]
SYS1_CAL_ADD = [
    "盘面槽位几何 (Tray 30 槽 / 周转盘槽位) — 现场一次标定, 盘面坐标类参数的唯一真源",
    "放置面高度 plane_z 与盘面平行度",
    "腕部相机工作距离窗口 0.1–0.6m (±1mm/±1° 只在此区间成立; 头部/胸部相机为 ±5mm 级)",
]
SYS1_DIA_ADD = [
    "摆盘 CT 实测 (起止口径写死: 从吸取离盘到下一位就位)",
    "取放精度实测 (单边 mm / 角度 °, 同一位姿连续 30 次往返)",
    "槽位映射一致性 (放料到位 ±1mm · 槽位对号 100%)",
    "型号识别/空满三态混淆矩阵 (每类 ≥300 样本; POC 各 ≥98%)",
    "摆盘成功率分阶段核验 (EVT 90 / DVT 95 / PVT 99) — 与基线同源口径",
]

NEW_FEATURES = [
    dict(pf_id="PF-Z100-09", product_id="Z100",
         title="摆盘取放循环 (周转盘 → 上料 Tray 盘)",
         capability_ref="BO_ C1 完整作业执行 + BO_ C4 灵活翻转取放",
         subsys=["sys1", "sys0"], status="规划",
         kpi="单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载具与产品损伤 0",
         desc="从满料周转盘逐颗吸取光模块并放入上料 Tray 盘槽位, 周转盘空或 Tray 满即上报待人工补料/下料; 分 EVT(CT≤20s,90%)/DVT(≤8s,95%)/PVT(≤3.15s,99%) 三阶段验收",
         module_refs=["🧠 VLM 通用视觉编码器 (SmolVLA)", "🎯 Flow-Matching Action Head (DiT)",
                      "🚀 L3 · 长程序列规划 (记忆: 海马体)", "💪 L2 肌肉记忆技能库 (光模块抓放循环)"]),
    dict(pf_id="PF-Z100-10", product_id="Z100",
         title="多型号自适应换型 (12+ 型号 / ≥6 种摆放)",
         capability_ref="BO_ B1 目标识别定位 + BO_ B2 空间位姿感知",
         subsys=["sys1", "sys0"], status="规划",
         kpi="型号规格识别 100% (POC ≥98%) · 换型 ≤30min · 新型号配置/学习 ≤3h",
         desc="100G/400G/800G 与 QSFP-DD/OSFP 等 12+ 型号、≥6 种周转盘摆放方式自适应; 固化项(盘型/槽形)进配方, 柔性项(光照/堆叠/遮挡)由感知自适应; 极端情况回退预设轨迹与固定逻辑保证产线不中断",
         module_refs=["🎯 YOLO 目标检测", "📐 2D→3D 解算", "🧩 开放词汇分割 (SAM3 分割anything)"]),
    dict(pf_id="PF-Z100-11", product_id="Z100",
         title="料盘空满三态判定与选槽",
         capability_ref="BO_ B5 外观质量检测 + BO_ B2 空间位姿感知",
         subsys=["sys1", "sys0"], status="规划",
         kpi="空/满/异常三态判定 100% (POC ≥98%) · 单次判定 ≤500ms · 异常态拒送并告警",
         desc="判定载具空/满/异常三态, 决定是否继续在当前载具取放; 由盘面几何给出槽位坐标与占用状态, L3 决定抓取顺序与放料槽位, 避免基于错误状态动作",
         module_refs=["📐 板坐标系定位 (工序坐标系·免手眼)", "🎯 YOLO 目标检测"]),
    dict(pf_id="PF-Z100-12", product_id="Z100",
         title="摆盘断点续作与异常恢复",
         capability_ref="BO_ C1 完整作业执行 + BO_ F1 本地实时作业",
         subsys=["sys1", "sys0"], status="规划",
         kpi="自动重试 ≤3 次 · 断点续作成功率 ≥95% · 错误继续执行 0 (零容忍)",
         desc="抓取失败/槽位异常/工位被占/放入受阻四类异常逐项定义处置策略; 异常解除后从明确状态继续, 不带着未知状态自动续跑",
         module_refs=["🚀 L3 · 长程序列规划 (记忆: 海马体)", "🤖 机器人执行器"]),
    dict(pf_id="PF-Z100-13", product_id="Z100",
         title="连续无人化作业 (≥12 盘 / 单日 ≥20h)",
         capability_ref="BO_ F1 本地实时作业 + BO_ E2 边学边练",
         subsys=["sys1", "sys2"], status="规划",
         kpi="连续自主 ≥12 盘周转盘 (硬下限 ≥6) · 单日连续运行 ≥20h · 月 ≥28 天 · 寿命 ≥3 年",
         desc="无人工干预下的连续取送循环能力; 断点与状态持久化保证跨班次可恢复, 与 ROI 口径(回收期 ≤2 年)同步",
         module_refs=["💪 L2 肌肉记忆技能库 (光模块抓放循环)", "🚀 L3 · 长程序列规划 (记忆: 海马体)"]),
]


def patch_platform():
    backup(PLAT)
    d = jload(PLAT)
    s1 = [s for s in d["subsystems"] if s["system_id"] == "sys1"][0]
    before = json.dumps(s1, ensure_ascii=False, sort_keys=True)
    for r in SYS1_ROWS_ADD:
        if r not in s1.setdefault("rows", []):
            s1["rows"].append(r)
    s1.setdefault("kpi", {}).update(SYS1_KPI_ADD)
    ax = s1.setdefault("axes", {})
    for k, add in (("cfg", SYS1_CFG_ADD), ("cal", SYS1_CAL_ADD), ("dia", SYS1_DIA_ADD)):
        lst = ax.setdefault(k, [])
        for it in add:
            if it not in lst:
                lst.append(it)
    n_new = 0
    have = {f.get("pf_id") for f in d["product_features"]}
    for f in NEW_FEATURES:
        if f["pf_id"] not in have:
            d["product_features"].append(f)
            n_new += 1
    jdump(PLAT, d)
    # 回读核验
    d2 = jload(PLAT)
    s1b = [s for s in d2["subsystems"] if s["system_id"] == "sys1"][0]
    ok = (json.dumps(s1b, ensure_ascii=False, sort_keys=True) != before
          and all(r in s1b["rows"] for r in SYS1_ROWS_ADD)
          and all(it in s1b["axes"]["cfg"] for it in SYS1_CFG_ADD)
          and len(d2["product_features"]) == len(d["product_features"]))
    print("  ① 平台真源: sys1 axes cfg/cal/dia = %d/%d/%d · 新增产品特征 %d 条 · 回读核验 %s"
          % (len(s1b["axes"]["cfg"]), len(s1b["axes"]["cal"]), len(s1b["axes"]["dia"]),
             n_new, "✅" if ok else "❌"))
    return ok


# ─────────────────────────────────────────────────────────────
# ② 场景 + 任务
# ─────────────────────────────────────────────────────────────
SCENE = {
    "scene_id": "SCN-06-TRAY",
    "scene_type": "tray_filling",
    "name": "光模块摆盘 (周转盘 → 上料 Tray 盘)",
    "desc": "人工把满料周转盘与空上料 Tray 盘放到台面固定位; 机器人识别盘位与槽位, 从周转盘逐颗吸取光模块放入 Tray 盘, 直至周转盘空或 Tray 满并上报待人工补料/下料",
    "goal": "摆盘任务闭环 (Tray 盘满 / 周转盘空 时状态上报)",
    "targets": {
        "单颗CT": "≤3.15s (PVT)",
        "成功率": "≥99% (PVT)",
        "取放精度": "单边 ≤1mm / ≤1°",
        "连续": "≥12 盘周转盘",
    },
    "objects": [
        {"name": "R MPV车体", "pos": [0, 0, 0], "size_mm": [800, 500, 700],
         "role": "坐标系原点·面向+X方向"},
        {"name": "工作台", "pos": [1.2, 0, 0.75], "size_mm": [1500, 600, 750],
         "role": "车辆正前方·1500×600 台面"},
        {"name": "满料周转盘", "pos": [0.9, -0.3, 0.78], "size_mm": [330, 330, 40],
         "role": "台面左侧固定位·4# 周转盘(满料·堆叠可多层)"},
        {"name": "空上料Tray盘", "pos": [1.4, 0.25, 0.78], "size_mm": [330, 330, 40],
         "role": "台面右侧·30 槽·逐盘满料后人工换空盘(最多6盘)"},
        {"name": "光模块单颗", "pos": [0.9, -0.3, 0.82], "size_mm": [18, 9, 4],
         "role": "物料单颗·100G/400G/800G · 12+ 型号"},
        {"name": "作业工装", "pos": [1.15, 0, 0.78], "size_mm": [350, 350, 40],
         "role": "周转盘取料工位·全局相机二次定位"},
    ],
    "steps": [
        {"t": 0.0, "dur": 2.0,
         "name": "定位识别",
         "desc": "全局定位相机识别满料周转盘位置与堆叠层数、空 Tray 盘位置、工装位置; 取 1 盘周转盘到作业工装并二次拍照, 识别盘内光模块数量与坐标、Tray 空槽数量与坐标",
         "force": None},
        {"t": 2.0, "dur": 0.6,
         "name": "取件",
         "desc": "腕部相机对准目标光模块, 末端下降至吸附位, 真空建立(≤200ms)后抬起离盘",
         "force": None},
        {"t": 2.6, "dur": 1.0,
         "name": "转运对位",
         "desc": "沿安全轨迹转移至目标 Tray 槽位上方, 姿态对准槽口方向, 粗定位后 XYZ/姿态微调",
         "force": None},
        {"t": 3.6, "dur": 0.8,
         "name": "放入",
         "desc": "下降到放置面, 断真空释放光模块; 放置下压不超过配方上限, 姿态偏差 ≤1°",
         "force": None},
        {"t": 4.4, "dur": 0.3,
         "name": "判态循环",
         "desc": "判断周转盘是否空、Tray 盘是否满; 未满且盘未空则回到取件; 触发上报则暂停待人工补料/下料",
         "force": None},
    ],
    "performance": {
        "单颗CT": "≤3.15s (PVT) / ≤8s (DVT) / ≤20s (EVT)",
        "成功率": "EVT 90% / DVT 95% / PVT 99%, 人工干预即记不完整成功",
        "取放精度": "单边 ≤1mm · 角 ≤1°",
        "无损": "载具与产品损伤 0 (零容忍)",
    },
}


def patch_scenes():
    backup(SCENES)
    d = jload(SCENES)
    ids = [s["scene_id"] for s in d["scenes"]]
    if SCENE["scene_id"] not in ids:
        d["scenes"].append(SCENE)
        jdump(SCENES, d)
        added = True
    else:
        added = False
    d2 = jload(SCENES)
    ok = SCENE["scene_id"] in [s["scene_id"] for s in d2["scenes"]]
    print("  ② 场景真源: 现有 %d 场景 %s · 回读核验 %s"
          % (len(d2["scenes"]), "(新增 SCN-06-TRAY)" if added else "(已存在)", "✅" if ok else "❌"))
    return ok


def run(cmd, label):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-6:])
    print("  ▶ %s rc=%d\n%s" % (label, r.returncode, "\n".join("      " + x for x in tail.splitlines())))
    return r.returncode == 0


if __name__ == "__main__":
    print("═══ 落地「泰国摆盘项目 · System 1 配置」═══")
    ok1 = patch_platform()
    ok2 = patch_scenes()
    py = sys.executable
    # task_build 里的计划表需要 SCN-06 (见 tools/task_build.py 的 PLANS)
    ok3 = run([py, "tools/task_build.py"], "task_build.py → config/tasks/tasks.json")
    ok4 = run([py, "tools/engineering_db.py", "build"], "engineering_db.py build → 单一工程库")
    ok5 = run([py, "tools/mcd_build.py"], "mcd_build.py → 配置中心 (MCD/参数表)")
    print("═══ 结果: %s ═══" % ("全部成功" if all([ok1, ok2, ok3, ok4, ok5]) else "有失败项, 见上"))
    sys.exit(0 if all([ok1, ok2, ok3, ok4, ok5]) else 1)
