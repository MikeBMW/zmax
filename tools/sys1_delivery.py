#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""System 1 交付包生成器 — 泰国摆盘项目 (2026-10-10)

把「单一工程库」里已经定义好的 System 1 配置 (功能清单 / 配置项 / 性能指标 / 接口契约 /
供货边界 / 缺口) 导成一个可发放给供应商的独立包。

真源: data/database/zmax/zmax_engineering.db (单文件=一套工程) + config/platform/zmax_platform.json
不产生第二份真相: 本工具只读, 输出到 outputs/sys1_delivery/ 供发放。

用法:
  python3 tools/sys1_delivery.py                # 生成交付包
  python3 tools/sys1_delivery.py --show         # 只在终端打印清单, 不落盘
"""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
OUT_ROOT = os.path.join(ROOT, "outputs", "sys1_delivery")
PROJ = "泰国摆盘项目 (光模块 周转盘 → 上料 Tray 盘)"
SYS_ID = "sys1"
PROD = "Z100"

# ── 供货边界 (Sys-1 交什么 / 不交什么) ──────────────────────────────
SCOPE_IN = [
    "L3 动作执行: 把 Sys-2 给出的意图/条件, 转成可执行的动作序列 (VLA-T 动作 + Z-Flow 引导)",
    "摆盘取放循环的策略与序列规划 (取件 → 转运对位 → 放入 → 判态循环)",
    "多型号/多摆放自适应的配方选择 (12+ 型号 · ≥6 种摆放)",
    "异常处置与断点续作决策 (重试/换策略/退回安全位)",
    "运行状态与事件上报 (阶段/成功/失败/异常码/断点/CT 计时)",
]
SCOPE_OUT = [
    "不供相机 / 机械臂 / 夹爪 / 真空等硬件本体",
    "不供站点几何真值 (K / plane_z / cell_geometry / 盘面槽位) — 现场标定, 由 Sys-0 提供",
    "不供安全红线 (急停/限速/禁区) — Sys-1 只读消费, 不产生否决权",
    "不供 L2 底层力控/伺服回路 (Sys-0 收口)",
]

# ── 接口契约 (Sys-1 的门: 上游给什么, 下游收什么) ──────────────────
CONTRACT = {
    "输入": [
        {"from": "Sys-2 (意图/条件)", "item": "任务号 + 物料型号 + 目标盘位/槽位策略 + 速度/力上限 (只给意图, 不给轨迹)"},
        {"from": "Sys-0 (感知)", "item": "目标位姿 T_base_obj (m/rad) · 抓取点/放置点 · 盘面槽位几何与占用状态"},
        {"from": "Sys-0 (真值)", "item": "相机内参 K · 放置面 plane_z · T_base_cam (标定件, 现场一次标定)"},
        {"from": "Sys-0 (图像)", "item": "腕部相机 RGB (工作距离 0.1–0.6m, 精度窗口) + 全局定位相机"},
        {"from": "Sys-0 (状态)", "item": "关节/末端位姿 · 夹爪开合 · 真空压力 · 力/力矩"},
    ],
    "输出": [
        {"to": "Sys-0 (执行)", "item": "动作块 (位姿序列 @ 推理步频) · 夹爪/真空指令 · 力控参数 (由 L2 势函数收口)"},
        {"to": "Sys-2 (上报)", "item": "阶段/成功/失败/异常码 · 断点信息 · 单颗 CT 计时 · 料盘空/满事件 · 型号识别结果"},
    ],
    "节拍/时延": [
        {"item": "单颗 CT (PVT)", "value": "≤3.15s", "note": "起止口径写死: 从吸取离盘到下一位就位"},
        {"item": "动作块下发", "value": "≥10Hz (待实测标定)", "note": "缺口: 未纳入诊断断言, 需补"},
        {"item": "型号识别单帧", "value": "≤100ms", "note": "父项 sOPE-06 写 ≤200ms ⇒ 已统一取子项"},
    ],
}

# ── 工程师清单 → 评审后指标 (阶段化 + 口径修正) ─────────────────────
METRICS = [
    ("节拍 CT", "单颗取放 ≤3.15s (PVT) / ≤8s (DVT) / ≤20s (EVT)",
     "起止 = 从吸取离盘到下一位就位; 不含人工换盘/补料时间", "SA01-02 / IDX-03", "修正口径"),
    ("成功率", "≥99% (PVT) / ≥95% (DVT) / 90% (EVT)",
     "人工干预即记不完整成功; 统计样本按 30 槽 × ≥12 盘 = 360 颗, 不采用 ≥1000 次口径", "SA01-01 / IDX-03", "修正口径"),
    ("取放精度", "单边 ≤1mm · 角 ≤1°",
     "仅在腕部相机 0.1–0.6m 工作距离内成立 (头部双目 1m 处为 ±5mm 级)", "SA01-04 / sOPE-02", "修正冲突"),
    ("位姿估计", "±1mm / ±1° (腕部, 0.1–0.6m)",
     "头部双目 @1m ≤±5mm; 胸部 @0.5m ≤±5mm ⇒ 不得笼统写 ±1mm", "sOPE-02 / HW-08/09/36", "修正冲突"),
    ("吸附建立", "≤200ms", "吸附保持 ≥5s; 真空建立失败判重试", "sOPE-06-01", "保留"),
    ("二值柔性退出", "≤50ms", "力分辨率 0.1N·m", "sOPE-04/05", "保留"),
    ("空满判定", "空/满/异常三态 100% (POC ≥98%)", "每类 ≥300 样本混淆矩阵; 异常态拒送并告警", "sOPE-08", "修正口径"),
    ("型号规格识别", "100% (POC ≥98%)", "12+ 型号; 误识别致错误抓取 = 0 (单帧准确率 ≥99.5% 为另一口径, 需分列)", "sOPE-06", "修正父子倒挂"),
    ("换型", "≤30min; 新型号配置/学习 ≤3h", "固化项进配方, 柔性项自适应", "sOPE-09", "保留"),
    ("连续作业", "≥12 盘周转盘 (硬下限 ≥6) · 单日 ≥20h · 月 ≥28 天",
     "两个数并列是矛盾: 验收取 ≥12 盘, ≥6 盘仅作为早期阶段下限", "SA01-05", "消歧"),
    ("损伤", "载具与产品损伤 = 0", "零容忍项, 逐条单列, 不与百分比指标混排", "SA01-04 / sOPE-06", "修正混排"),
]

GAPS = [
    ("站点几何", "T_base_cam / plane_z / cell_geometry.points 未标定 ⇒ 坐标类参数与工单全部阻塞", "现场标定后重跑 config_center check"),
    ("性能真源", "perf.D_INSERT_mm / perf.cycle_s 未落地到 verif 真源 (摆盘以 CT 为主, 插入深度不适用)", "摆盘任务改挂 cyc.takt 判据, 不再引用 ins.*"),
    ("档位契约", "feature.cap_level / feature.dbc_version 未定义 ⇒ 档位级验收无口径", "补 feature.dbc 版本与能力档位"),
    ("能力库", "摆盘能力暂挂 C1/C4/B1/B2 平台级能力, 未新增项目级能力条目", "如需供应链逐条报价, 再评估是否加 I 组能力"),
    ("模型在役", "model.ckpt_l3 (VLA-T/Z-Flow 权重) 未登记在役哈希", "登记权重路径 + sha256"),
]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    s = c.execute("select * from subsystems where system_id=?", (SYS_ID,)).fetchone()
    sys1 = dict(s) if s else {}
    if sys1.get("kpi"):
        sys1["kpi"] = json.loads(sys1["kpi"])
    if sys1.get("rows"):
        try:
            sys1["rows"] = json.loads(sys1["rows"])
        except Exception:
            pass
    feats = [dict(r) for r in c.execute(
        "select pf_id,title,capability_ref,subsys,kpi,status,descr,module_refs "
        "from product_features where product_id=? order by pf_id", (PROD,))]
    for f in feats:
        for k in ("subsys", "module_refs"):
            if isinstance(f.get(k), str):
                try:
                    f[k] = json.loads(f[k])
                except Exception:
                    pass
    fns = [dict(r) for r in c.execute(
        "select fn_id,name,layer,kind,module_ref from functions where system_id=?", (SYS_ID,))]
    axes = {}
    for r in c.execute("select axis,idx,item,src from fn_axes where fn_id like 'FN-SYS1%' order by axis,idx"):
        axes.setdefault(r["axis"], [])
        if r["item"] not in axes[r["axis"]]:
            axes[r["axis"]].append(r["item"])
    params = [dict(r) for r in c.execute(
        "select param_id,name,cn,value,\"default\",unit,status,module_ref,impact "
        "from params where sys_id=? order by param_id", (SYS_ID,))]
    return sys1, feats, fns, axes, params


def build_doc(sys1, feats, fns, axes, params):
    pl = json.load(open(os.path.join(ROOT, "config", "platform", "zmax_platform.json"), encoding="utf-8"))
    platform = {"platform": pl.get("platform"), "products": [p.get("product_id") for p in pl.get("products", [])]}
    return {
        "format": "zmax-sys1-delivery",
        "version": "1.0",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "project": PROJ,
        "system": {"system_id": SYS_ID, "name": sys1.get("name"), "level": sys1.get("level"),
                   "role": sys1.get("role"), "hardware": sys1.get("hardware")},
        "platform": platform,
        "scope": {"交付范围": SCOPE_IN, "不在范围": SCOPE_OUT},
        "kpi": sys1.get("kpi", {}),
        "function_list": [
            {"fn_id": f["fn_id"], "name": f["name"], "layer": f["layer"], "kind": f["kind"],
             "module_ref": f["module_ref"]} for f in fns],
        "product_features": feats,
        "config_axes": axes,
        "switch_params": params,
        "interface_contract": CONTRACT,
        "metrics": [{"指标": a, "目标": b, "口径": c, "来源条目": d, "处理": e} for a, b, c, d, e in METRICS],
        "gaps": [{"项": a, "现状": b, "处置": c} for a, b, c in GAPS],
    }


def render_md(doc):
    L = []
    A = L.append
    A("# System 1 交付配置说明 (供应商版)")
    A("")
    A("项目: %s  " % doc["project"])
    A("子系统: %s (%s)  " % (doc["system"]["name"], doc["system"]["level"]))
    A("生成时间: %s  ·  格式: %s v%s" % (doc["generated_at"], doc["format"], doc["version"]))
    A("")
    A("## 1. 定位与供货边界")
    A("")
    A("角色: %s" % doc["system"]["role"])
    A("硬件: %s" % doc["system"]["hardware"])
    A("")
    A("**交付范围**")
    for x in doc["scope"]["交付范围"]:
        A("- %s" % x)
    A("")
    A("**不在范围 (由其它子系统/现场负责)**")
    for x in doc["scope"]["不在范围"]:
        A("- %s" % x)
    A("")
    A("## 2. 性能指标 (已按评审口径统一)")
    A("")
    A("| 指标 | 目标 | 口径 | 来源条目 | 处理 |")
    A("|---|---|---|---|---|")
    for m in doc["metrics"]:
        A("| %s | %s | %s | %s | %s |" % (m["指标"], m["目标"], m["口径"], m["来源条目"], m["处理"]))
    A("")
    A("## 3. 接口契约")
    A("")
    for k, rows in doc["interface_contract"].items():
        A("**%s**" % k)
        A("")
        for r in rows:
            src = r.get("from") or r.get("to") or "—"
            val = r.get("value", "")
            note = r.get("note", "")
            A("- `%s` → %s%s%s" % (src, r.get("item", ""),
                                   ("  **%s**" % val) if val else "",
                                   ("  (%s)" % note) if note else ""))
        A("")
    A("## 4. 功能清单 (System 1 功能节点)")
    A("")
    A("| 功能 ID | 名称 | 层 | 类型 | 引擎模块 |")
    A("|---|---|---|---|---|")
    for f in doc["function_list"]:
        A("| %s | %s | %s | %s | %s |" % (f["fn_id"], f["name"], f["layer"], f["kind"], f["module_ref"]))
    A("")
    A("## 5. 摆盘产品功能条目 (可逐条验收 / 逐条报价)")
    A("")
    for f in doc["product_features"]:
        A("### %s · %s" % (f["pf_id"], f["title"]))
        A("")
        A("- 适用子系统: %s" % (f.get("subsys") or []))
        A("- 关联平台能力: %s" % (f.get("capability_ref") or ""))
        A("- 指标: %s" % (f.get("kpi") or ""))
        A("- 状态: %s" % (f.get("status") or ""))
        if f.get("descr"):
            A("- 说明: %s" % f["descr"])
        A("")
    A("## 6. 配置项 (子系统 cfg/cal/dia 轴 · 在配置中心可改)")
    A("")
    for axis, label in (("cfg", "可配置项 (cfg)"), ("cal", "标定项 (cal)"), ("dia", "诊断项 (dia)")):
        items = doc["config_axes"].get(axis, [])
        A("**%s — %d 项**  (每个 System 1 功能节点各持一份)" % (label, len(items)))
        A("")
        for i, it in enumerate(items, 1):
            A("%2d. %s" % (i, it))
        A("")
    A("## 7. 在役开关参数")
    A("")
    A("| 参数 | 中文 | 值 | 单位 | 状态 |")
    A("|---|---|---|---|---|")
    for p in doc["switch_params"]:
        A("| %s | %s | %s | %s | %s |" % (p["param_id"], p["cn"], p["value"], p["unit"] or "-", p["status"]))
    A("")
    A("## 8. 缺口与依赖 (发放前必须知会供应商)")
    A("")
    A("| 项 | 现状 | 处置 |")
    A("|---|---|---|")
    for g in doc["gaps"]:
        A("| %s | %s | %s |" % (g["项"], g["现状"], g["处置"]))
    A("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="只打印, 不落盘")
    a = ap.parse_args()
    sys1, feats, fns, axes, params = load()
    if a.show:
        print(json.dumps({"system": sys1.get("name"), "rows": sys1.get("rows"),
                          "kpi": sys1.get("kpi"), "functions": [f["fn_id"] for f in fns],
                          "features": [f["pf_id"] for f in feats],
                          "axes": {k: len(v) for k, v in axes.items()}},
                         ensure_ascii=False, indent=1))
        return
    doc = build_doc(sys1, feats, fns, axes, params)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT_ROOT, "sys1_%s" % ts)
    os.makedirs(out, exist_ok=True)
    # 1) 机器可读
    with open(os.path.join(out, "sys1_config.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    # 2) 供应商可读
    md = render_md(doc)
    with open(os.path.join(out, "sys1_供货配置说明.md"), "w", encoding="utf-8") as f:
        f.write(md)
    # 3) 功能清单 CSV
    with open(os.path.join(out, "sys1_功能清单.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["类型", "ID", "名称", "层/子系统", "指标或模块", "状态"])
        for x in doc["function_list"]:
            w.writerow(["功能节点", x["fn_id"], x["name"], x["layer"], x["module_ref"], ""])
        for x in doc["product_features"]:
            w.writerow(["产品功能条目", x["pf_id"], x["title"], "·".join(x.get("subsys") or []),
                        x.get("kpi", ""), x.get("status", "")])
        for m in doc["metrics"]:
            w.writerow(["性能指标", m["来源条目"], m["指标"], m["目标"], m["口径"], m["处理"]])
    # 4) manifest (可核验)
    man = {"format": doc["format"], "version": doc["version"], "generated_at": doc["generated_at"],
           "project": doc["project"], "source_db": os.path.relpath(DB, ROOT),
           "source_db_sha256": sha256(DB),
           "source_platform": "config/platform/zmax_platform.json",
           "files": {}}
    for n in sorted(os.listdir(out)):
        man["files"][n] = {"bytes": os.path.getsize(os.path.join(out, n)),
                           "sha256": sha256(os.path.join(out, n))}
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    print("✅ System 1 交付包: %s" % out)
    for n, v in man["files"].items():
        print("   %-28s %8d B" % (n, v["bytes"]))
    print("\n发放: 整包 tar 后交供应商; 核验: 比对 manifest.json 内 sha256")
    print("包内 sys1_config.json 为机器可读真源导出, sys1_供货配置说明.md 为供应商版本")


if __name__ == "__main__":
    main()
