#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_probes.py — 【只读】性能指标的**采集器注册表** (评估分析的唯一采集口径)。

老倪 2026-10-15: 「在主界面的 评估分析 功能页, 要做系统的评估分析, 当前 5.50.735 版本是基线产品, 以后要从
这个版本评估分析后, 有性能提升才能升级; 在配置中心, 所有的性能指标, 都要科学的与基线版本做对比;
你来结合具身智能产品的实际性能, 设计一个 评估分析 功能页…你是专业的评测专家…要保证全局数据一致性,
你的工具是信号分析窗口, 3D场景窗口, 以及状态空间的元任务, 主参数, 以及 L2 原子技能的实际物理参数。」

设计原则 (评测纪律):
  1. **指标定义只有一个真源** = config/platform/zmax_perf_spec.json (58 条: A 运动学/B 视觉/C 电口/D 光口/
     E 节拍/F 环境)。本文件**只写"怎么量"**, 不抄指标名/目标值 —— 抄了就迟早两处打架。
  2. 每条采集结果必须带**证据类**: `实测` (有真源文件+帧龄) / `标定·配置` (来自标定真源或规格) /
     `推导` (由实测换算, 写明算式) / `未测` (没有采集条件 —— 绝不用 0 或设计值冒充实测)。
  3. 样本量不够 (n < 判定所需) ⇒ 记 `n` 并标 `样本不足`, **不出判定** —— 3 次插入算不出 3σ。
  4. 语义必须对得上: 物理量名字像 ≠ 同一个量 (例: L2 插入段 `s_step` 是"单拍位移上限", 不是"插深分辨率";
     摆盘 `dz` 是落位深度误差, 不是插拔 `插深终到误差`)。对不上就写"未测", 不硬套。

用法:
  from eval_probes import run_all
  rep = run_all()          # {metric_id: {value, unit, mode, src, age_s, n, note}}
"""
from __future__ import annotations

import glob
import json
import re
import math
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERF_SPEC = os.path.join(ROOT, "config", "platform", "zmax_perf_spec.json")
LIVE = os.path.join(ROOT, "zmax_data", "dataspace", "live.json")
SKILL_PHYS = os.path.join(ROOT, "zmax_data", "ss_live", "skill_phys.json")
TRACE = os.path.join(ROOT, "zmax_data", "ss_live", "trace_live.json")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
MANIFOLD = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
TASK_RUNS = os.path.join(ROOT, "zmax_data", "task_runs")
SKILL_CALIB = os.path.join(ROOT, "config", "calib", "zmax_skill_physics.json")

# 传感器/仪器类指标: 本机没有采集装置 (要与"没采"区分开 —— 这是"不能采")
NEED_INSTRUMENT = {
    "perf.AP_pose": "同上 (激光跟踪仪)",
    "perf.RP_angle": "同上 (角度分量 ±3σ)", "perf.res_joint": "单轴点动最小步 (编码器读值)",
    "perf.res_tcp": "微动级最小指令步 (宏微复合实测)", "perf.backlash": "ISO 230-2 双向定位 (测头)",
    "perf.settle": "阶跃指令后残差时间 (高速采集)",
    "perf.stiff": "5N 侧向力 + 位移读数 (百分表/激光)", "perf.sync_dual": "双臂协同轨迹逐点相对偏差",
    "perf.depth_noise": "平面目标连拍 ≥100 帧深度残差 (需相机)",
    "perf.pose6d_ang": "0.05°/0.1° 角度台阶工件 (需 6D 解算链)",
    "perf.slot_accuracy": "12+ 型号 × 满/缺/错位样本集 (需标注集)",
    "perf.illum_range": "可调光源扫照度 (需光源+相机)",
    "perf.force_res": "力传感器/电流估计最小可辨力 (需力传感器)",
    "perf.force_overshoot": "力-位移曲线峰值/稳态 (需插装真机)",
    "perf.force_curve_consistency": "每次插装力-位移曲线与标杆模板相关系数 (需标杆模板+真机)",
    "perf.mate_life": "同端子反复插拔 ≥500 次 (寿命试验台)", "perf.coplanarity": "端子共面度抽样 + 回归",
    "perf.fiber_bend_r": "抓取-转运-入槽全程曲率半径 (需路径+真机)", "perf.conn_mate_force": "光连接器对接力曲线 (需力传感器)",
    "perf.aa_res_lin": "自动对准线性分辨率 (需光功率计+对准台)", "perf.aa_res_ang": "自动对准角度分辨率 (同上)",
    "perf.aa_search": "自动对准搜索时间 (同上)", "perf.il_target": "插入损耗 (需光功率计/回损仪)",
    "perf.il_repeat": "插损重复性 (需光功率计)", "perf.rl_target": "回波损耗 (需回损仪)",
    "perf.opm_res": "光功率计分辨率 (仪器规格)", "perf.hold_drift": "保压漂移 (需长时间光功率监测)",
    "perf.face_clean": "端面洁净度 (需 IEC 61300-3-35 端面检测仪)",
    "perf.endurance": "连续自主作业盘数 (需连续跑 PVT 级盘数)",
    "perf.changeover": "换型时间 12+ 型号 (需现场换型实测)",
    "perf.mtbf": "MTBF/MTTR (需 EVT 后可靠性数据)", "perf.anomaly_recovery": "卡料/缺料/对位失败三类自恢复率 (需长跑)",
    "perf.esd_surface": "设备外壳表面电阻 (需表面电阻仪)", "perf.esd_friction_v": "摩擦电压 (需静电测试台)",
    "perf.cleanliness": "洁净度等级 (需尘埃粒子计数器)",
    "perf.temp_hum": "工作温湿度 (需温湿度记录仪)", "perf.noise": "噪声 dB(A) (需声级计)",
    "perf.power_air": "供电/气源 (需现场实测电压/气压)",
    "perf.insert_depth_res": "插入深度控制分辨率 (需微动轴+力位混合闭环)",
    "perf.D_INSERT_mm": "插深终到误差 (需插拔真机一轮)", "perf.contact_pressure": "金手指接触压力上限 (需插后镀层目检)",
    "perf.face_gap": "作业路径最近点间隙 (需路径后处理+激光位移复核)",
    "perf.latency_e2e": "采图→位姿输出 P95 (需打时间戳的视觉链真跑)", "perf.handeye_res": "靶 ≥12 位姿闭环残差 RMS (需重标定)",
}


def _now_age(p):
    """文件帧龄 (s); 文件不存在 ⇒ -1"""
    try:
        return time.time() - os.path.getmtime(p)
    except OSError:
        return -1.0


def _load(p, default=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                     # noqa: BLE001
        return default


def _cut(v):
    """未测统一的表示: None (绝不写 0 —— 0 是"测得是零", 与"没测"不是一回事)"""
    return None


def _untested(mid, why=""):
    return {"value": None, "mode": "未测", "src": "", "age_s": -1.0, "n": 0,
            "note": why or NEED_INSTRUMENT.get(mid, "")}


def _tray_summary():
    """摆盘链真实运行小结 (tools/…→ zmax_data/task_runs/TASK-06-TRAY/run_summary.json)"""
    p = os.path.join(TASK_RUNS, "TASK-06-TRAY", "run_summary.json")
    return _load(p) or {}, p


def _fw_chain():
    """插拔链真值帧 (流形引擎逐帧遥测: 度规/势能/阶段)"""
    c = sorted(glob.glob(os.path.join(TASK_RUNS, "TASK-01-FW", "chain_*.jsonl")))
    if not c:
        return [], ""
    p = c[-1]
    rows = []
    try:
        with open(p, encoding="utf-8") as fh:
            for ln in fh:
                if ln.strip():
                    rows.append(json.loads(ln))
    except Exception:                                                     # noqa: BLE001
        pass
    return rows, p


BOM = os.path.join(ROOT, "config", "platform", "zmax_project_bom.json")


def _bom_item(i):
    d = _load(BOM, {}) or {}
    items = ((d.get("bom") or {}).get("items") or [])
    return (items[i] if i < len(items) else {}), BOM


def _num(txt, pat):
    m = re.search(pat, str(txt))
    return float(m.group(1)) if m else None


def _decl(mid, i, cn_note, pat=r"([0-9]+(?:\.[0-9]+)?)", unit=None, as_text=False):
    """设计声明 (BOM/规格): value 是**声明值**, 不是我们量出来的 ⇒ mode=设计声明(BOM)"""
    it, p = _bom_item(i)
    note = str(it.get("note") or "")
    v = note if as_text else _num(note, pat)
    return {"value": v, "mode": "设计声明(BOM)", "unit": unit, "n": 1, "src": p, "age_s": _now_age(p),
            "note": "%s ← BOM 第%d项「%s」: %s (设计/厂商声明, **非现场实测**)" % (cn_note, i, it.get("name"), note)}


def p_envelope():
    return _decl("perf.envelope", 0, "单臂作业半径 (CR7 单臂半径)", r"半径\s*([0-9]+)", "mm")


def p_rp_pose():
    return _decl("perf.RP_pose", 0, "末端重复性 (厂商规格)", r"重复精度\s*([0-9.]+)", "mm")


def p_lift_repeat():
    return _decl("perf.lift_repeat", 9, "升降轴重复定位 (厂商规格)", r"定位\s*±?([0-9.]+)", "mm")


def p_safety_pl():
    return _decl("perf.safety_pl", 14, "安全功能等级 (BOM 选型)", unit="-", as_text=False) if False else {
        "value": None, "mode": "设计声明(BOM)", "unit": "-", "n": 1, "src": BOM, "age_s": _now_age(BOM),
        "note": "BOM 第14项 安全模块: PLd · Cat.3 (ISO 13849-1) —— **选型声明**, 现场风险评估未做 ⇒ 待现场实测",
        "extra": {"声明": "PLd · Cat.3", "待现场实测": True}}


def p_esd_ground():
    return {"value": None, "mode": "设计声明(BOM)", "unit": "Ω", "n": 1, "src": BOM, "age_s": _now_age(BOM),
            "note": "BOM 第13项 ESD 要求: 表面电阻 1e6–1e9Ω · 接地 <1Ω —— **设计要求**, 需接地电阻仪现场实测",
            "extra": {"声明": "表面 1e6–1e9Ω / 接地 <1Ω", "待现场实测": True}}


def p_vis_repeat():
    it, p = _bom_item(6)
    return {"value": None, "mode": "设计声明(BOM)", "unit": "mm", "n": 1, "src": p, "age_s": _now_age(p),
            "note": "BOM 第6项 腕部相机: %s —— **准确度规格**, 与「定位重复性 1σ」语义不同 ⇒ 只作参考, 需连拍实测" %
                    (it.get("note") or ""), "extra": {"声明": it.get("note"), "待现场实测": True}}


# ═══════════════════════════ 采集器 (每个指标一条: 怎么量) ═══════════════════════════
def p_cycle_s():
    d, p = _tray_summary()
    js = [j for j in (d.get("judges") or []) if isinstance(j.get("ct_s"), (int, float))]
    if not js:
        return _untested("perf.cycle_s", "无运行记录 (zmax_data/task_runs/TASK-06-TRAY/run_summary.json)")
    cts = [float(j["ct_s"]) for j in js]
    return {"value": max(cts), "mode": "实测", "unit": "s", "n": len(cts), "src": p, "age_s": _now_age(p),
            "note": "摆盘单颗取放周期 (整链真跑 · n=%d 取最大; 均值 %.3fs)" % (len(cts), sum(cts) / len(cts)),
            "extra": {"各颗": [round(c, 3) for c in cts], "takt_s": d.get("judges", [{}])[0].get("takt_s")}}


def p_cycle_split():
    d, p = _tray_summary()
    js = [j for j in (d.get("judges") or []) if isinstance(j.get("ct_s"), (int, float))]
    if not js:
        return _untested("perf.cycle_split", "需要分段耗时 (当前记录只有整段 ct_s)")
    if len(js) < 3:
        return {"value": None, "mode": "未测", "src": p, "age_s": _now_age(p), "n": len(js),
                "note": "样本不足 (%d 颗): 分段预算需 ≥3 颗可比样本" % len(js)}
    return {"value": max(float(j["ct_s"]) for j in js), "mode": "实测", "unit": "s", "n": len(js), "src": p,
            "age_s": _now_age(p), "note": "分段预算 ≤3.15s 需逐段计时; 当前可用的是整段 CT (上限口径)"}


def p_uph():
    d, p = _tray_summary()
    js = [j for j in (d.get("judges") or []) if isinstance(j.get("ct_s"), (int, float))]
    if not js:
        return _untested("perf.uph")
    ct = max(float(j["ct_s"]) for j in js)
    return {"value": round(3600.0 / ct, 1), "mode": "推导", "unit": "颗/h", "n": len(js), "src": p,
            "age_s": _now_age(p), "note": "推导式 3600 / CT(%0.3fs) = %0.1f 颗/h (未计换型/故障停机)" % (ct, 3600.0 / ct)}


def p_success_rate():
    d, p = _tray_summary()
    t, q = d.get("total"), d.get("placed")
    if not t:
        return _untested("perf.success_rate")
    return {"value": round(100.0 * float(q) / float(t), 2), "mode": "实测", "unit": "%", "n": int(t),
            "src": p, "age_s": _now_age(p),
            "note": "整链真跑 %d/%d 落位成功 (n=%d < 30 不足以定成功率置信区间, 值只作趋势)" % (q, t, t)}


def p_mate_align_repeat():
    d, p = _tray_summary()
    js = [j for j in (d.get("judges") or []) if isinstance(j.get("dx_mm"), (int, float))]
    if not js:
        return _untested("perf.mate_align_repeat")
    mx = max(math.hypot(float(j["dx_mm"]), float(j["dy_mm"])) for j in js)
    return {"value": round(mx, 3), "mode": "实测", "unit": "mm", "n": len(js), "src": p, "age_s": _now_age(p),
            "note": "对位残差矢量模最大值 (n=%d, **样本不足**: ≤0.05mm 是 30 次 3σ 口径 ⇒ 只报值不判定)" % len(js),
            "extra": {"dx_max": max(float(j["dx_mm"]) for j in js), "dy_max": max(float(j["dy_mm"]) for j in js),
                      "样本不足": True}}


def p_mate_angle_repeat():
    d, p = _tray_summary()
    js = [j for j in (d.get("judges") or []) if isinstance(j.get("yaw_err_deg"), (int, float))]
    if not js:
        return _untested("perf.mate_angle_repeat")
    return {"value": round(max(float(j["yaw_err_deg"]) for j in js), 4), "mode": "实测", "unit": "°", "n": len(js),
            "src": p, "age_s": _now_age(p),
            "note": "对插姿态角偏差最大值 (n=%d, 样本不足 ⇒ 只报值不判定)" % len(js), "extra": {"样本不足": True}}


def p_vis_scale():
    c = _load(CALIB, {}) or {}
    fx = (c.get("camera") or {}).get("fx")
    if not isinstance(fx, (int, float)) or fx <= 0:
        return _untested("perf.vis_scale", "相机内参 fx 缺失")
    d300 = 300.0
    return {"value": round(d300 / float(fx), 4), "mode": "推导", "unit": "mm/px", "n": 1, "src": CALIB,
            "age_s": _now_age(CALIB),
            "note": "像素当量 = 工作距离300mm / fx(%.2f) = %.4f mm/px (未含亚像素插值 0.05px 量级)" % (fx, d300 / fx)}


def p_handeye_res():
    c = _load(CALIB, {}) or {}
    t = (c.get("T_base_cam") or {})
    v = t.get("value")
    if v is None:
        rpt = sorted(glob.glob(os.path.join(ROOT, "config", "calib", "calib_report_*.json")))
        if not rpt:
            return {"value": None, "mode": "未标定", "src": CALIB, "age_s": _now_age(CALIB), "n": 0,
                    "note": "手眼未标定: T_base_cam.value = None (%s) ⇒ 无残差可评" % (t.get("_reason", "")[:48])}
    return {"value": None, "mode": "未标定", "src": CALIB, "age_s": _now_age(CALIB), "n": 0,
            "note": "手眼残差需重标定一份 calib_report (当前标定表里 T_base_cam 无值)"}


def p_contact_pressure():
    """金手指插入力上限 = L2 插入段的力包络 (标定真源, 真值可追)"""
    d = _load(SKILL_CALIB, {}) or {}
    st = ((d.get("stages") or d) or {}).get("插入") if isinstance(d.get("stages") or d, dict) else None
    if not isinstance(st, dict):
        return _untested("perf.contact_pressure", "标定真源里没有「插入」段")
    f = (st.get("F") or {})
    v = f.get("value")
    return {"value": v, "mode": "标定·配置", "unit": "N", "n": 1, "src": SKILL_CALIB, "age_s": _now_age(SKILL_CALIB),
            "note": "插入段力上限 = %.1fN (金手指保护; 原文: %s)" % (v if v is not None else -1, str(f.get("src"))[:44])}


def p_payload_ratio():
    it, p = _bom_item(0)
    return {"value": 1.4, "mode": "设计声明(BOM)", "unit": "-", "n": 1, "src": p, "age_s": _now_age(p),
            "note": "BOM 第0项 %s (负载 7kg) ÷ 实需 5kg = 1.4× ⇒ 达标线在 1.4 (**设计声明**, 非现场称重)" %
                    (it.get("note") or "")}


def p_sys_l2_physics():
    """⚖ 系统级: L2 原子技能物理合规率 (实测 v/a/s ≤ 标定包络 / 真源一致)"""
    d = _load(SKILL_PHYS, {}) or {}
    sk = d.get("skills") or {}
    if not sk:
        return _untested("perf.sys_l2_physics", "skill_phys.json 缺失 (技能派发服务没在跑?)")
    tot = bad = 0
    det = []
    for code, r in sk.items():
        if not str(code).startswith("SK") or not r.get("在职"):
            continue
        for k, lim, kk in (("v_mms", "v_cap", 1000.0), ("a_mms2", "a_max", 1000.0), ("s_mm", "s_max", 1000.0)):
            v, L = r.get(k), r.get(lim)
            if isinstance(v, (int, float)) and v >= 0 and isinstance(L, (int, float)) and L > 0:
                tot += 1
                if v > L * kk + 1e-6:
                    bad += 1
                    det.append("%s %s=%.2f>%.2f" % (code, k, v, L * kk))
    return {"value": round(100.0 * (tot - bad) / tot, 2) if tot else None, "mode": "实测", "unit": "%", "n": tot,
            "src": SKILL_PHYS, "age_s": _now_age(SKILL_PHYS),
            "note": "在职技能逐拍物理量全部落在标定包络内 (检查 %d 项; 违反 %d)" % (tot, bad),
            "extra": {"违反明细": det[:5]}}


def p_sys_channel():
    """📡 系统级: 遥测通道达标率 (登记 ↔ DDS 实收 ↔ 信号分析可见)"""
    d = _load(LIVE, {}) or {}
    t = d.get("topics") or {}
    if not t:
        return _untested("perf.sys_channel", "数据总线 live.json 缺失")
    live_t = {k: e for k, e in t.items() if isinstance(e.get("hz"), (int, float)) and e["hz"] > 0}
    ok = [k for k, e in live_t.items() if e.get("lamp") in ("green", "yellow")]
    nopub = [k for k, e in t.items() if k not in live_t]
    red = [k for k, e in live_t.items() if e.get("lamp") not in ("green", "yellow")]
    if not live_t:
        return _untested("perf.sys_channel", "登记话题全无发布端 (数据总线没起?)")
    return {"value": round(100.0 * len(ok) / len(live_t), 2), "mode": "实测", "unit": "%", "n": len(live_t),
            "src": LIVE, "age_s": _now_age(LIVE),
            "note": "有发布端话题健康 %d/%d (绿黄); 红: %s · 登记未接生产者 %d 条 (不计入分母)" %
                    (len(ok), len(live_t), (",".join(red) or "无"), len(nopub)),
            "extra": {"红": red, "未接生产者": nopub, "灯账": d.get("lamp_tally")}}


def p_sys_manifold():
    """🧮 系统级: 主参数 M 健康 (度规正定 + 条件数)"""
    rows, p = _fw_chain()
    if not rows:
        return _untested("perf.sys_manifold", "无插拔链真值帧 (task_runs/TASK-01-FW/chain_*.jsonl)")
    k_pd, k_lo, k_hi = "流形引擎.空间智能_度规正定", "流形引擎.空间智能_特征值下限", "流形引擎.空间智能_特征值上限"
    pds = [bool(r.get(k_pd)) for r in rows if k_pd in r]
    conds = []
    for r in rows:
        lo, hi = r.get(k_lo), r.get(k_hi)
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > 0:
            conds.append(hi / lo)
    if not conds:
        return _untested("perf.sys_manifold", "真值帧里没有特征值上下限")
    return {"value": round(max(conds), 1), "mode": "实测", "unit": "条件数", "n": len(conds), "src": p,
            "age_s": _now_age(p),
            "note": "度量张量条件数 (特征值上限/下限) 最大 %.1f · 正定 %d/%d 帧" % (max(conds), sum(pds), len(pds)),
            "extra": {"条件数明细": [round(c, 1) for c in conds]}}


def p_sys_consistency():
    """🔗 系统级: 全局数据一致性 (指标定义唯一真源 + 版本一致 + L2 包络同源)"""
    spec = _load(PERF_SPEC, {}) or {}
    n_spec = sum(len(g.get("metrics") or []) for g in (spec.get("groups") or []))
    bad = []
    ver_file = os.path.join(ROOT, "tools", "gui", "docs_sync.py")
    try:
        txt = open(ver_file, encoding="utf-8").read()
        if '"v5.50.735"' not in txt:
            bad.append("docs_sync 版本与基线不一致")
    except Exception:                                                     # noqa: BLE001
        bad.append("docs_sync 读不到")
    # L2 包络与标定真源逐条一致
    sp, cal = _load(SKILL_PHYS, {}) or {}, _load(SKILL_CALIB, {}) or {}
    for code, r in (sp.get("skills") or {}).items():
        st = str(r.get("stage") or "")
        c = ((cal.get("stages") or cal) or {}).get(st)
        if isinstance(c, dict) and isinstance((c.get("v") or {}).get("value"), (int, float)):
            if isinstance(r.get("v_cap"), (int, float)) and abs(r["v_cap"] - c["v"]["value"]) > 1e-6 and r.get("在职"):
                bad.append("%s v_cap≠标定真源" % code)
    return {"value": round(100.0 * (1 - len(bad) / max(1, n_spec)), 2), "mode": "实测", "unit": "%", "n": n_spec,
            "src": PERF_SPEC, "age_s": _now_age(PERF_SPEC),
            "note": "指标定义 %d 条来自唯一真源; 冲突 %d 项" % (n_spec, len(bad)), "extra": {"冲突": bad[:6]}}


# ═══════════════════ 评测补充指标 (不在 58 条里, 但这是具身产品的真实性能面) ═══════════════════
EXTRA = [
    {"id": "perf.sys_l2_physics", "cn": "L2 原子技能物理合规率", "unit": "%", "target": "≥100 (逐拍不越包络)",
     "how": "每拍 L2 实测 v/a/s 与标定包络 (config/calib/zmax_skill_physics.json) 比对", "probe": p_sys_l2_physics,
     "links": ["L2 原子技能物理参数", "信号分析"]},
    {"id": "perf.sys_channel", "cn": "遥测通道达标率", "unit": "%", "target": "≥95 (登记话题健康率)",
     "how": "topics.py 登记 ↔ DDS 实收 ↔ 信号分析可见 (zmax_data/dataspace/live.json)", "probe": p_sys_channel,
     "links": ["信号分析窗口", "全局数据空间"]},
    {"id": "perf.sys_manifold", "cn": "主参数 M 条件数", "unit": "条件数", "target": "≤10000 (有限且正定)",
     "how": "插拔链真值帧的度规特征值上限/下限; 正定性逐帧核对", "probe": p_sys_manifold,
     "links": ["主参数 M", "3D场景", "元任务"]},
    {"id": "perf.sys_consistency", "cn": "全局数据一致性", "unit": "%", "target": "≥100 (零冲突)",
     "how": "指标定义唯一真源 + 版本一致 + L2 包络与标定真源同源", "probe": p_sys_consistency,
     "links": ["工程库", "配置中心", "L2 物理参数"]},
]

PROBES = {
    "perf.cycle_s": p_cycle_s, "perf.cycle_split": p_cycle_split, "perf.uph": p_uph,
    "perf.success_rate": p_success_rate, "perf.mate_align_repeat": p_mate_align_repeat,
    "perf.mate_angle_repeat": p_mate_angle_repeat, "perf.vis_scale": p_vis_scale,
    "perf.handeye_res": p_handeye_res, "perf.contact_pressure": p_contact_pressure,
    "perf.payload_ratio": p_payload_ratio, "perf.envelope": p_envelope, "perf.RP_pose": p_rp_pose,
    "perf.lift_repeat": p_lift_repeat, "perf.safety_pl": p_safety_pl, "perf.esd_ground": p_esd_ground,
    "perf.vis_repeat": p_vis_repeat,
}


def metric_index():
    """指标定义索引 (唯一真源 perf_spec): {id: {cn, unit, target, how, std, stage, links, gid, gname}}"""
    spec = _load(PERF_SPEC, {}) or {}
    out = {}
    for g in (spec.get("groups") or []):
        for m in (g.get("metrics") or []):
            d = dict(m)
            d["gid"], d["gname"] = g.get("gid"), g.get("name")
            out[m["id"]] = d
    return out


def run_all():
    """跑全部采集器 → {metric_id: 采集结果}; 没有采集器的指标 = 未测 (带采集条件)。"""
    idx = metric_index()
    res = {}
    for mid, m in idx.items():
        fn = PROBES.get(mid)
        if fn is None:
            res[mid] = _untested(mid)
        else:
            try:
                res[mid] = fn()
            except Exception as e:                                        # noqa: BLE001
                res[mid] = {"value": None, "mode": "未测", "src": "", "age_s": -1.0, "n": 0,
                            "note": "采集器异常: %s: %s" % (type(e).__name__, str(e)[:80])}
        res[mid]["cn"] = m.get("cn")
        res[mid]["unit"] = res[mid].get("unit") or m.get("unit")
        res[mid]["target"] = m.get("target")
        res[mid]["how"] = m.get("how")
        res[mid]["stage"] = m.get("stage")
        res[mid]["group"] = "%s %s" % (m.get("gid"), m.get("gname"))
        res[mid]["extra_metric"] = False
    for em in EXTRA:
        try:
            r = em["probe"]()
        except Exception as e:                                            # noqa: BLE001
            r = {"value": None, "mode": "未测", "note": "采集器异常: %s" % str(e)[:80]}
        r.update({"cn": em["cn"], "unit": em.get("unit"), "target": em["target"], "how": em["how"],
                  "group": "★ 评测补充指标 (评测专家定义)", "extra_metric": True, "links": em.get("links")})
        res[em["id"]] = r
    return res


if __name__ == "__main__":
    r = run_all()
    ok = [(k, v) for k, v in r.items() if v.get("value") is not None]
    print("指标数 %d · 有采集结果 %d · 未测 %d" % (len(r), len(ok), len(r) - len(ok)))
    for k, v in ok:
        print("  %-26s %-10s %-8s n=%-3s %s" % (k, v.get("value"), v.get("unit") or "", v.get("n"),
                                                (v.get("note") or "")[:60]))
