# -*- coding: utf-8 -*-
"""工单配置单 (Build Sheet) 生成器 —— 把"车辆配置单"这套搬到机器人产线。

类比映射 (汽车总装 → 机器人产线):
    VIN/车型/订单号      → 工单号 + 场景ID + 工件ID (单件唯一)
    动力总成/变速箱       → 机器人型号 + 末端工具 + DOF/负载/TCP
    颜色/内饰/选装包      → 工件变体 (物料规格/朝向) + 选项包 (扫码/AOI/EEPROM/分拣/老化)
    零件清单 BOM         → 来料盒(穴位)/治具/料盘(穴位)/耗材
    装配指令/工艺提示      → 工序配方 (逐步骤: 目标位姿/力/插入深度/判据/超时/重试)
    质量追溯             → 单件记录 + 判据快照 + binding_id
    (额外) 安全节         → Sys-0: 急停/力阈值/关节限位/光幕 (站点级, 任何工单不得覆盖)

四层配置 + 优先级 (谁说了算):
    L1 站点配置  config/calib/*         现场事实(坐标系/相机/TCP/机器人/安全) ← 永远最高, 只读
    L2 工序配方  工序模板(RECIPE)        工艺定型(取件→扫码→对位→插拔→分拣→回位) 参数化
    L3 工件变体  flows/scenes_5jobs.json 每种物料的尺寸/朝向/穴位/来料姿态
    L4 工单实例  本生成器输出            一批 N 件: 逐件 ID + 选项 + 参数覆盖
    优先级: 安全(G1) > 站点几何(G3) > 工单覆盖(G2) > 变体 > 配方默认

真源 (只读):
    flows/scenes_5jobs.json                        5 个作业场景 (对象坐标/穴位/步骤/性能目标)
    docs/orin-grasp-place-workflow.md              抓取放置工序实测判据 (抓取力/插入深度/容错/安全)
    config/calib/zmax_calib.json                   站点工程配置真值
    feature.dbc                                    A1 自主流转 / A2 工位对接 / C4 翻转取放 / C5 双臂协同

输出:
    config/orders/BS_<scene>.json                  逐场景工单配置单 (含防错校验链 + 参数就绪度)
用法:
    python3 tools/build_sheet.py [--scene SCN-02-HANDLE] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENES = os.path.join(ROOT, "flows", "scenes_5jobs.json")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
OUTDIR = os.path.join(ROOT, "config", "orders")

# ── L2 工序配方: 上下料/插拔工序的 8 段模板 (每段带参数定义: 真源·判据·级·权限) ──
# src: 参数真值来自哪   judge: 可执行判据   grade: G0..G4   perm: readonly/field/auth/version
RECIPE_STEPS = [
    dict(seg="0 料源与来料状态", params=[
        dict(id="src.tray_id", cn="来料盒/料盘 ID", src="site#calib.trays", judge="扫盒码与工单一致",
             grade="G3", perm="field"),
        dict(id="src.pocket_origin", cn="第 0 穴位坐标", src="site#calib.trays[0].origin",
             judge="示教后 std≤2mm", grade="G3", perm="field"),
        dict(id="src.pitch", cn="穴间距 (行/列)", src="site#calib.trays[0].pitch",
             judge="与实测 3 穴位反算误差≤0.5mm", grade="G3", perm="field"),
        dict(id="src.orient", cn="来料朝向", src="variant#scenes.objects[来料盒].role",
             judge="金手指面朝上", grade="G3", perm="field"),
        dict(id="src.empty_full", cn="空/满料检测", src="site#sensor.tray_state",
             judge="与已取件数一致", grade="G2", perm="readonly")]),
    dict(seg="1 取件", params=[
        dict(id="pick.tool", cn="工具选择 (夹爪/吸盘)", src="site#calib.tool_payload",
             judge="负载与 J 参数匹配", grade="G2", perm="auth"),
        dict(id="pick.close_force", cn="夹爪闭合力", src="recipe#pick.close_force=1~5N",
             judge="grasp_normal_force ≥ 5N 判抓取成功", grade="G1", perm="auth"),
        dict(id="pick.lift_h", cn="提升高度", src="recipe#pick.lift_h=30mm",
             judge="≥ 工件厚度+10mm 且不碰邻件", grade="G2", perm="auth"),
        dict(id="pick.retry", cn="抓取失败重试", src="recipe#pick.retry=2",
             judge="连续>2 次失败报错停机", grade="G1", perm="field")]),
    dict(seg="2 姿态准备", params=[
        dict(id="pose.flip", cn="是否翻转 180°", src="variant#scenes.steps[翻转].name",
             judge="翻转后目标面朝上 (C4)", grade="G2", perm="auth"),
        dict(id="pose.target_up", cn="目标朝上面", src="variant#derived",
             judge="与后续工序(扫码/插拔)要求一致", grade="G3", perm="field")]),
    dict(seg="3 识别与工位对接", params=[
        dict(id="align.vision", cn="视觉识别定位", src="feature#B1",
             judge="检出置信度≥阈值且位姿 std≤1mm", grade="G2", perm="readonly"),
        dict(id="align.station_tol", cn="工位对接公差", src="feature#A2 ±10mm",
             judge="对接偏差≤10mm 否则不作业", grade="G1", perm="readonly"),
        dict(id="align.scan", cn="扫码工位坐标", src="site#calib.stations.scanner",
             judge="扫码成功且 ID 与工单一致", grade="G3", perm="field")]),
    dict(seg="4 放置/插入", params=[
        dict(id="ins.depth", cn="插入深度", src="recipe#ins.depth (SCN-01: 35mm)",
             judge="end_pose.x > 0.750 (实测判据)", grade="G1", perm="auth"),
        dict(id="ins.force_ctrl", cn="力控频率/上限", src="recipe#ins.force (SCN-01: Fz>1kHz, ≤5N)",
             judge="力峰≤5N 且不超阈值", grade="G1", perm="auth"),
        dict(id="ins.retry", cn="插入重试", src="recipe#ins.retry=1",
             judge="二次尝试仍不到位 → NG", grade="G1", perm="field")]),
    dict(seg="5 拔出/取回", params=[
        dict(id="pull.wait_hmi", cn="等待测试结果 (HMI)", src="recipe#pull.wait_hmi=true",
             judge="收到测试结果才拔出", grade="G2", perm="field"),
        dict(id="pull.force", cn="拔出/夹持力", src="recipe#pull.force",
             judge="不超夹持力上限且工件无位移", grade="G1", perm="auth")]),
    dict(seg="6 分拣与回位", params=[
        dict(id="sort.pass_tray", cn="Pass 料盘", src="variant#scenes.objects[Pass料盘]",
             judge="12 穴位不越界·满盘切换", grade="G3", perm="field"),
        dict(id="sort.fail_tray", cn="Fail/NG 料盘", src="variant#scenes.objects[Fail料盘]",
             judge="ng_place_count 轮换不重位", grade="G3", perm="field"),
        dict(id="sort.rule", cn="分拣规则", src="recipe#sort.rule",
             judge="AOI 各站失败累计 → NG", grade="G2", perm="field")]),
    dict(seg="7 节拍与循环", params=[
        dict(id="cyc.takt", cn="单件节拍目标", src="scene#targets.performance",
             judge="达标率≥目标值", grade="G2", perm="auth"),
        dict(id="cyc.dual_arm", cn="双臂协同模式", src="feature#C5 (同步/协同/接力)",
             judge="模式与工序匹配且无干涉", grade="G2", perm="auth"),
        dict(id="cyc.guard", cn="循环守卫", src="recipe#cyc.guard",
             judge="pick_place_loop_done 信号正常", grade="G2", perm="readonly")]),
]

# ── Sys-0 安全 (站点级, 任何工单不得覆盖) ──
SAFETY = [
    dict(id="sf.estop", cn="急停检查", judge="动前/动中常闭", src="docs/orin-grasp-place-workflow.md#Sys-0"),
    dict(id="sf.force", cn="力阈值 Fz", judge=">5N 即停", src="同上"),
    dict(id="sf.joint", cn="关节限位", judge="±3rad", src="同上"),
    dict(id="sf.light_curtain", cn="光幕检测", judge="遮挡即停", src="同上"),
]

# ── 防错校验链 (Poka-yoke, 逐件; 任一不匹配 = 停线, 不许跳过) ──
POKA_YOKE = [
    ("扫工件码", "工件的 DMC/条码", "码与工单 order_no 一致"),
    ("查工单", "order_no → Build Sheet", "工单存在且未暂停"),
    ("选程序", "配方 + 工件变体", "变体与来料规格一致 (尺寸/朝向)"),
    ("校验资源", "工具/料位/机器人状态", "工具在位·料位有效·机器人就绪"),
    ("参数下发", "G2 参数写控制器", "回读与实际一致 (逐位)"),
    ("安全自检", "Sys-0 四项", "全通过才放行"),
    ("记录", "单件记录 + 判据快照 + binding_id", "记录落盘成功"),
]


def _dig(d, path):
    cur = d
    for k in str(path).split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def read_site():
    try:
        return json.load(open(CALIB, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def site_gaps(calib):
    gaps = []
    for k, p in (("T_base_cam", "T_base_cam.value"), ("plane_z", "plane_z.value"),
                 ("cell_geometry.points", "cell_geometry.points")):
        if _dig(calib, p) is None:
            gaps.append(k)
    return gaps


def tools_of(scene):
    """从场景对象里挑出与上下料相关的物料/治具 (BOM)。"""
    bom = []
    for o in scene.get("objects", []):
        nm, role = o.get("name", ""), o.get("role", "")
        if any(k in nm for k in ("料盘", "盒", "插座", "治具", "子板", "枪", "台")):
            bom.append({"name": nm, "pos": o.get("pos"), "size_mm": o.get("size_mm"), "role": role})
    return bom


OPT_BY_TYPE = {"fw_loading": ["扫码", "EEPROM 读写校验", "分拣"],
               "handle": ["扫码", "上下料搬运", "空满料盘切换"],
               "bi_aging": ["扫码", "老化箱插拔", "分拣"],
               "thermal_chamber": ["扫码", "电口插拔", "光口插拔"],
               "ats_test": ["扫码", "测试读取", "分拣"]}


def build(scene, calib, idx):
    st = scene.get("scene_type")
    bs = {
        "_note": "工单配置单 (Build Sheet)。真源: flows/scenes_5jobs.json + 工序配方 + config/calib。生成物, 勿手改。",
        "identity": {"order_no": f"BS-{scene['scene_id']}-{idx:04d}",
                     "scene_id": scene["scene_id"], "scene_type": st,
                     "name": scene.get("name"), "goal": scene.get("goal"),
                     "batch": "默认 1 批 (可覆盖)", "station": "SITE-A.ST11",
                     "robot": "珞石 Z700 (R MPV 上装)"},
        "variant": {"desc": scene.get("desc"),
                    "objects": [{"name": o.get("name"), "role": o.get("role")}
                                for o in scene.get("objects", [])],
                    "derived_from": "flows/scenes_5jobs.json#scenes[].objects"},
        "options": {"selected": OPT_BY_TYPE.get(st, []),
                    "_derived": f"按 scene_type={st} 推定; 待与产线工艺卡对齐"},
        "bom": tools_of(scene),
        "process": [{"t": s.get("t"), "dur": s.get("dur"), "name": s.get("name"),
                     "desc": s.get("desc"), "force": s.get("force")}
                    for s in scene.get("steps", [])],
        "recipe": [{"seg": r["seg"], "params": r["params"]} for r in RECIPE_STEPS],
        "targets": scene.get("targets", {}),
        "safety": SAFETY,
        "poka_yoke": [{"step": n, "check": c, "pass_if": p} for n, c, p in POKA_YOKE],
        "trace": {"per_unit": ["工件码", "工单号", "时间", "结果", "参数快照", "binding_id"],
                  "binding_id": "sha16(工件变体+站点+档位+覆盖)"},
    }
    # 参数就绪度: 每条配方参数是否有"真源 + 判据", 站点几何是否就位
    gaps = site_gaps(calib)
    params = [p for r in RECIPE_STEPS for p in r["params"]]
    bs["readiness"] = {
        "params": len(params),
        "site_ok": 9 - len(gaps), "site_missing": gaps,
        "blocked_by_site": [p["id"] for p in params
                            if any(k in p["src"] + p["judge"] for k in ("坐标", "工位", "穴"))
                            and gaps],
        "note": "站点几何未标定 ⇒ 一切「坐标类」参数不可信, 上下料无法定位 (需先补 T_base_cam/plane_z/cell_geometry)",
    }
    return bs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    scenes = json.load(open(SCENES, encoding="utf-8"))["scenes"]
    calib = read_site()
    os.makedirs(OUTDIR, exist_ok=True)
    made = []
    for s in [x for x in scenes if not a.scene or x["scene_id"] == a.scene]:
        try:  # 工单序号取场景编号 (SCN-02-...) —— 与筛选无关, 保证工单号稳定可复算
            idx = int(s["scene_id"].split("-")[1])
        except Exception:  # noqa: BLE001
            idx = 1
        bs = build(s, calib, idx)
        p = os.path.join(OUTDIR, f"BS_{s['scene_id']}.json")
        json.dump(bs, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        made.append((bs, p))

    if a.json:
        print(json.dumps([m[0] for m in made], ensure_ascii=False, indent=1))
        return 0

    print(f"工序配方: {len(RECIPE_STEPS)} 段 / {sum(len(r['params']) for r in RECIPE_STEPS)} 条参数"
          f" · 安全节 {len(SAFETY)} · 防错链 {len(POKA_YOKE)} 步")
    print(f"站点工程配置: 就位 {9-len(site_gaps(calib))}/9 · 缺 {', '.join(site_gaps(calib)) or '无'}")
    print()
    hdr = f"{'工单号':<22}{'场景':<34}{'BOM':>4}{'步骤':>5}{'参数':>5}  就绪"
    print(hdr); print("-" * len(hdr))
    for bs, p in made:
        r = bs["readiness"]
        print(f"{bs['identity']['order_no']:<22}{bs['identity']['name'][:32]:<34}"
              f"{len(bs['bom']):>4}{len(bs['process']):>5}{r['params']:>5}"
              f"  站点 {r['site_ok']}/9 → {os.path.basename(p)}")
    print()
    if site_gaps(calib):
        print(f"⛔ 全部工单受同一站点缺口阻塞: {', '.join(site_gaps(calib))} —— 上下料是"
              f"「坐标驱动」工序, 几何没标定就没有可信的穴位/工位坐标 (见各工单 readiness)")
    else:
        print("✅ 站点几何已就位, 工单可下发")
    return 0


if __name__ == "__main__":
    sys.exit(main())
