# -*- coding: utf-8 -*-
"""MCD 描述生成器 (第一版, B1) —— 流形引擎标定·主参数 M 节点的描述文件真源。

把散在各处的"可测/可标/可诊断"的量, 收成一份机器可读的 MCD 描述 (对标 ASAM MCD-2MC / A2L)：
    config/mcd/zmax_mcd.json      四段: MEASUREMENT / CHARACTERISTIC / COMPU_METHOD / GROUPS (+DIAGNOSTICS)
    config/mcd/param_registry.json 参数注册表 (扁平, 带就绪度)

真源全部只读 —— 本脚本**不写任何标定值**(不调用 sync_calib(write=True), 不碰 calib.json 的在役读值)：
    config/calib/zmax_calib.json      工程配置 (相机内参/几何/TCP/负载/机器人)
    config/calib/zmax_manifold.json   流形引擎主参数 M / inertia
    feature.dbc                       功能配置 (能力 BO_ / 信号 SG_ / 节点 BU_ / 组合 CM_)
    src/lerobot/engineering/levels.py 档位契约 (L2/L3/L4/L5 必须还能干的事)
    src/lerobot/verification/verification_layer.py  诊断断言 FEATURES
    tools/gui/studio.py::ConfigModule 模型配置 (cfg_spec 六类标准参数 + Sys-11/12 超参)

用法:
    python3 tools/mcd_build.py            # 生成/刷新两份产物 + 打印就绪度
    python3 tools/mcd_build.py --check    # 幂等自检: 重算与盘上逐位比对, 不一致 exit 2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCD_DIR = os.path.join(ROOT, "config", "mcd")
MCD_JSON = os.path.join(MCD_DIR, "zmax_mcd.json")
REG_JSON = os.path.join(MCD_DIR, "param_registry.json")

CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
MANIFOLD = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
DBC = os.path.join(ROOT, "feature.dbc")
LEVELS_PY = os.path.join(ROOT, "src", "lerobot", "engineering", "levels.py")
VERIF_PY = os.path.join(ROOT, "src", "lerobot", "verification", "verification_layer.py")
STUDIO_PY = os.path.join(ROOT, "tools", "gui", "studio.py")


# ─────────────────────────── 工具 ───────────────────────────
def _jload(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def _sha16(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return None


def _dig(d, path, default=None):
    """按 'a.b.c' 取值 (容器缺一层就返回 default —— 不吞异常语义)。"""
    cur = d
    for k in str(path).split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


# ─────────────────────── 能力/档位/断言 现况 ───────────────────────
def read_feature_dbc():
    """解析 feature.dbc —— 只做计数与清单, 不改文件。"""
    out = {"nodes": [], "flows": [], "caps": [], "combos": {}, "cap_interfaces": {}, "cap_domain": {}}
    if not os.path.isfile(DBC):
        return out
    txt = open(DBC, encoding="utf-8").read()
    for ln in txt.splitlines():
        s = ln.strip()
        if s.startswith("BU_:"):
            out["nodes"] = s.split(":", 1)[1].split()
        elif s.startswith("FLOW_:"):
            out["flows"].append(s.split(":", 1)[1].split()[0])
        elif s.startswith("BO_ "):
            m = re.match(r"BO_\s+(\S+)\s+(.+?):\s*([A-Z/]+)\s+(\S+)", s)
            if m:
                cid, name, iface, dom = m.group(1), m.group(2), m.group(3), m.group(4)
                out["caps"].append(cid)
                out["cap_interfaces"][cid] = iface
                out["cap_domain"][cid] = dom
        elif s.startswith("CM_ "):
            m = re.match(r"CM_\s+(\S+):\s*(.*)", s)
            if m:
                out["combos"][m.group(1)] = m.group(2).split()
    return out


def read_levels():
    """读档位契约 LEVELS (正则, 不执行模块)。"""
    out = {}
    if not os.path.isfile(LEVELS_PY):
        return out
    txt = open(LEVELS_PY, encoding="utf-8").read()
    m = re.search(r"LEVELS\s*=\s*\{(.*?)\n\}", txt, re.S)
    if not m:
        return out
    for lv, name, must in re.findall(r'"(L\d)":\s*\{"name":\s*"([^"]*)",\s*\n\s*"must":\s*\[(.*?)\]', m.group(1), re.S):
        items = re.findall(r'"([^"]+)"', must)
        out[lv] = {"name": name, "must": items}
    return out


def read_features():
    """读诊断断言 FEATURES 清单 (id/域/分级)。"""
    rows = []
    if not os.path.isfile(VERIF_PY):
        return rows
    txt = open(VERIF_PY, encoding="utf-8").read()
    m = re.search(r"FEATURES\s*=\s*\[(.*?)\n\]", txt, re.S)
    if not m:
        return rows
    for t in re.findall(r'\("(F-[A-Z]\d\d)",\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",\s*"([^"]*)",\s*(None|"[^"]*"),\s*"(L\d)"\)', m.group(1)):
        rows.append({"id": t[0], "domain": t[1], "name": t[2], "where": t[3],
                     "mode": t[4], "auto": t[5] != "None", "level": t[6]})
    return rows


def read_cfg_spec_rows():
    """读模型配置六类标准参数总表 (studio.py::ConfigModule cfg_spec) —— 只取分类名与行数。"""
    if not os.path.isfile(STUDIO_PY):
        return []
    txt = open(STUDIO_PY, encoding="utf-8").read()
    m = re.search(r"cfg_spec\s*=\s*\[(.*?)\n\s*\]\n\s*cfg_models", txt, re.S)
    if not m:
        return []
    out = []
    for cat, body in re.findall(r'\("([^"]+)",\s*\[(.*?)\n\s*\]\)', m.group(1), re.S):
        params = re.findall(r'\n\s*\("([^"]+)",\s*\{', body)
        if params:
            out.append({"group": cat, "params": params})
    return out


# ─────────────────────── 参数规格 (curated 科学表) ───────────────────────
# 域: 模型配置 / 工程配置 / 功能配置 / 性能配置
# 级: G0 结构参数(非自由拟合) · G1 安全参数(红线, 只读) · G2 性能参数(可扫可写)
#     G3 场景参数(现场零运动示教) · G4 模型权重/版本(不可标, 只版本)
# 权限: readonly / field(现场) / auth(需真动授权) / version(只版本比对)
PARAM_SPEC = [
    # ── 工程配置: 坐标系/几何/单位 (设备事实, 最底层约束) ──
    dict(id="cam.K", cn="相机内参矩阵", domain="工程配置", grade="G3",
         src="config/calib/zmax_calib.json#camera.K", read=("calib", "camera.K"),
         unit="px", rng=None, dflt=None, perm="field",
         affects=["ssyolo", "ss2d3d", "n_board_frame"], feature=["B1", "B2"],
         judge="9 元素 · fx/fy>0 · 与 models/real_cam_calib.json 一致"),
    dict(id="cam.dist", cn="畸变系数", domain="工程配置", grade="G3",
         src="config/calib/zmax_calib.json#camera.dist", read=("calib", "camera.dist"),
         unit="-", rng=None, dflt=None, perm="field",
         affects=["ss2d3d"], feature=["B2"], judge="plumb_bob 5 元素"),
    dict(id="T_base_cam", cn="基座→相机 外参", domain="工程配置", grade="G3",
         src="config/calib/zmax_calib.json#T_base_cam.value", read=("calib", "T_base_cam.value"),
         unit="m/rad", rng=None, dflt=None, perm="field",
         affects=["ss2d3d", "n_realscene", "overlay"], feature=["B2"],
         judge="4x4 刚体 · 与板坐标系定位互校验 (rmse<2mm)"),
    dict(id="plane_z", cn="台面高度 (工作平面)", domain="工程配置", grade="G3",
         src="config/calib/zmax_calib.json#plane_z.value", read=("calib", "plane_z.value"),
         unit="m", rng=None, dflt=None, perm="field",
         affects=["ss2d3d", "robot_vision_3d"], feature=["B2"],
         judge="现场量一次 (夹爪或塞尺) · 与真机 TCP 实测台面高一致"),
    dict(id="depth_scale", cn="仿真单目深度尺度", domain="工程配置", grade="G2",
         src="config/calib/zmax_calib.json#depth_scale.value", read=("calib", "depth_scale.value"),
         unit="-", rng=[0.5, 1.5], dflt=0.9616, perm="auth",
         affects=["ss2d3d"], feature=["B2"],
         judge="探针实测均值 ±5% (真机走 RealSense 米制深度, 不用本项)"),
    dict(id="cell_geometry.points", cn="工位几何示教点", domain="工程配置", grade="G3",
         src="config/calib/zmax_calib.json#cell_geometry.points", read=("calib", "cell_geometry.points"),
         unit="m", rng=None, dflt=None, perm="field",
         affects=["ss2d3d", "n_moveit"], feature=["A2", "C2"],
         judge="peg_head/goal/aoi 三点齐 · 零运动示教 (ss_geom_calib.py)"),
    dict(id="robot.dof", cn="机器人自由度", domain="工程配置", grade="G0",
         src="config/calib/zmax_calib.json#robot.dof", read=("calib", "robot.dof"),
         unit="-", rng=[6, 7], dflt=6, perm="readonly",
         affects=["ssact", "sssensor", "moveit"], feature=["B4"],
         judge="=6 (XMS5-R800) · 与 urdf 一致"),
    dict(id="tool_payload.mass_kg", cn="末端负载质量", domain="工程配置", grade="G2",
         src="config/calib/zmax_calib.json#tool_payload.mass_kg", read=("calib", "tool_payload.mass_kg"),
         unit="kg", rng=[0, 5], dflt=1.51, perm="auth",
         affects=["ssact", "real_arm_motion"], feature=["C3"],
         judge="与控制器负载参数一致 (否则力控前馈偏)"),
    dict(id="control_tcp.offset_xyz_m", cn="控制 TCP 偏移", domain="工程配置", grade="G3",
         src="config/calib/zmax_calib.json#control_tcp.offset_xyz_m", read=("calib", "control_tcp.offset_xyz_m"),
         unit="m", rng=None, dflt=None, perm="field",
         affects=["ssact", "n_moveit", "teach_points"], feature=["C1", "C2"],
         judge="std≤2mm 且姿态偏差≤1° (多帧反解 verdict=刚体一致)"),
    # ── 性能配置: 主参数 M 与安全红线 ──
    dict(id="M", cn="流形引擎主参数 (等效惯量尺度)", domain="性能配置", grade="G0",
         src="config/calib/zmax_manifold.json#M", read=("manifold", "M"),
         unit="无量纲 (等效惯量尺度)", rng=[0.0, 8.0], dflt=1.0, perm="auth",
         affects=["ss_mani_eng", "ssmani_c", "ssmani_exp", "n_calib_mani"], feature=["D2"],
         judge="零回归: inertia=false 或 M=default ⇒ 逐位同旧一阶过阻尼; 有惯性时须 ΔV<0"),
    dict(id="M.inertia", cn="有惯性二阶演化开关", domain="性能配置", grade="G2",
         src="config/calib/zmax_manifold.json#inertia", read=("manifold", "inertia"),
         unit="bool", rng=[0, 1], dflt=False, perm="auth",
         affects=["ss_mani_eng"], feature=["D2"],
         judge="false=默认零回归; 打开后动量 ‖v‖ 有界且末端不过冲"),
    dict(id="safety.saturate", cn="动作饱和限幅", domain="性能配置", grade="G1",
         src="src/lerobot/policies/left_right/safety.py (saturate)", read=None,
         unit="-", rng=[0.0, 0.6], dflt=0.6, perm="readonly",
         affects=["sslimit", "ssact"], feature=["C3"],
         judge="红线: 只允许收紧, 放宽须现场一次性授权"),
    dict(id="safety.veto_th", cn="残差否决阈值", domain="性能配置", grade="G1",
         src="src/lerobot/policies/left_right/cognition.py (veto)", read=None,
         unit="-", rng=None, dflt=None, perm="readonly",
         affects=["sssched"], feature=["C3"],
         judge="红线: 逐轴 corr<0.5 全 veto 的收口闸, 不许放宽"),
    dict(id="perf.D_INSERT_mm", cn="插深终到误差指标", domain="性能配置", grade="G2",
         src="src/lerobot/verification/verification_layer.py#F-A02", read=None,
         unit="mm", rng=[0, 20], dflt=4.0, perm="readonly",
         affects=["ssfeat"], feature=["C1"],
         judge="实测 <4mm 判过 (F-A02)"),
    dict(id="perf.cycle_s", cn="节拍指标", domain="性能配置", grade="G2",
         src="docs/feature_dbc_spec.md + io_trace", read=None,
         unit="s", rng=[0, 60], dflt=6.0, perm="readonly",
         affects=["ssfeat"], feature=["C6"],
         judge="≤6s (宏微复合口径)"),
    # ── 功能配置: 能力组合 / 档位 ──
    dict(id="feature.combo", cn="能力组合 (feature.dbc CM_)", domain="功能配置", grade="G2",
         src="feature.dbc#CM_", read=("dbc", "combos"), unit="-", rng=None,
         dflt="JOB_MODEL 默认组合", perm="auth",
         affects=["sscap", "ssfeat", "整机能力"], feature=["G1"],
         judge="组合内每条能力都有实现节点 (match_node 非 None); 冲突=0"),
    dict(id="feature.cap_level", cn="能力档位", domain="功能配置", grade="G2",
         src="flows/state_space_obs.json#sscap.params.cap_level", read=None,
         unit="L2/L3/L4/L5", rng=None, dflt="L2", perm="auth",
         affects=["sscap", "全链"], feature=["G1"],
         judge="档位契约必须满足 (levels.check(): 该档节点全有逻辑 key, 缺口=0)"),
    dict(id="feature.dbc_version", cn="能力库版本", domain="功能配置", grade="G4",
         src="feature.dbc#VERSION", read=None, unit="-", rng=None, dflt="1.0",
         perm="version", affects=["全模型"], feature=["G1"], judge="入库 git, 演进可追溯"),
    # ── 模型配置: 见 cfg_spec (六类标准参数) + 在役权重 ──
    dict(id="model.arch_mode", cn="架构模式 (Sys-11 / Sys-11+12)", domain="模型配置", grade="G2",
         src="tools/gui/studio.py#ConfigModule.mode_group", read=None,
         unit="-", rng=None, dflt="Sys-11+12", perm="auth",
         affects=["训练链", "L2/L3/L4"], feature=["G1"],
         judge="切模态后 VLM/ActionHead/世界模型 参数组可用性一致"),
    dict(id="model.cfg_spec", cn="Lerobot 标准参数总表 (6 类)", domain="模型配置", grade="G2",
         src="tools/gui/studio.py#ConfigModule.cfg_spec", read=("cfgspec", None),
         unit="-", rng=None, dflt=None, perm="auth",
         affects=["ACT", "SmolVLA", "VLA-JEPA"], feature=["G1"],
         judge="三模型逐行可比; 导出 Excel 与表内逐位一致"),
    dict(id="model.ckpt_l2", cn="L2 在役权重 (YOLO)", domain="模型配置", grade="G4",
         src="models/yolo_peg_live.pt (软链)", read=None, unit="-", rng=None,
         dflt=None, perm="version", affects=["ssyolo"], feature=["B1"],
         judge="软链目标存在 · 版本台账可追溯 (yolo_weights_lineage)"),
    dict(id="model.ckpt_l3", cn="L3 在役权重 (SmolVLA LoRA)", domain="模型配置", grade="G4",
         src="outputs/train/**/checkpoints/last", read=None, unit="-", rng=None,
         dflt=None, perm="version", affects=["ssvlm", "ssdec"], feature=["C1"],
         judge="LoRA 必须 merge 后才算生效 (否则零动作伪装)"),
    dict(id="model.ckpt_l4", cn="L4 在役权重 (INTACT)", domain="模型配置", grade="G4",
         src="outputs/train/**/checkpoints/last", read=None, unit="-", rng=None,
         dflt=None, perm="version", affects=["ssintact", "swintact"], feature=["C1"],
         judge="反归一化按 ckpt 训练集同源 · 稳态延迟 <120ms"),
    dict(id="model.third_party", cn="第三方模型接入 (POD)", domain="模型配置", grade="G4",
         src="feature.dbc#BU_ THIRD_PARTY", read=None, unit="-", rng=None,
         dflt="未接入", perm="version", affects=["平台容器"], feature=["G1"],
         judge="登记 BU_ + 勾选 CM_ + 对齐 SG_ 三步齐"),
]

# ─────────────────────── 测量量 (只读) ───────────────────────
MEASUREMENT = [
    dict(id="tcp_pose", cn="末端位姿真值", unit="m/四元数",
         src="zmax_data/rokae_sdk/tcp_out/latest.json", rate="50Hz", judge="帧龄 <2s"),
    dict(id="joint_states", cn="六关节位置/速度", unit="rad / rad/s",
         src="zmax_data/rokae_sdk/tcp_out/latest.json#joint", rate="50Hz", judge="帧龄 <2s"),
    dict(id="residual", cn="状态校正残差", unit="-", src="io_trace (ssinnov)", rate="逐帧", judge="否决阈值内"),
    dict(id="contact_p", cn="接触概率", unit="0~1", src="cognition (contact)", rate="逐帧",
         judge="插入段 ≥0.9 · 分离度 >0.3"),
    dict(id="d_insert_mm", cn="实测插深误差", unit="mm", src="io_trace", rate="逐帧", judge="<4mm (F-A02)"),
    dict(id="eta_cjj", cn="效率 η", unit="CJ/J", src="energy_manifold", rate="逐轮", judge="完成态 η 高 / 未插入 η≈0"),
    dict(id="V_p", cn="性能流形耦合代价", unit="-", src="ssmani_p", rate="逐帧", judge="完成态收敛"),
    dict(id="frame_age", cn="各源文件帧龄", unit="s", src="stats/8793 + 各源 mtime", rate="1Hz", judge="≤2s"),
    dict(id="probe_code", cn="链路探活码", unit="HTTP", src="8793/8795/8891/Orin/工控机", rate="按需",
         judge="200=通 · 403=没带口令(合规) · 000=不可达"),
]

# ─────────────────────── 换算 (COMPU_METHOD) ───────────────────────
COMPU = [
    dict(id="cmm_speed", cn="腿速换算", expr="实际 mm/s ≈ (0.0935 × speed) ÷ 10",
         evidence="实测: 名义 14mm/s 的 50mm 抬升走 37.2s ⇒ 1.34mm/s; 想要 ~10mm/s 给 speed≈1000"),
    dict(id="cmm_depth", cn="D405 深度单位", expr="raw × 0.1 = mm", evidence="实测 raw 4013 = 401mm"),
    dict(id="cmm_clock", cn="时钟口径", expr="容器 t 比宿主早 8h (NTP 回拨) ⇒ 只用文件龄",
         evidence="已知历史现象, 勿据此报时钟异常"),
    dict(id="cmm_fresh", cn="新鲜度阈值", expr="帧龄 >2s 拒用; 录点 6 帧极差 >1e-4m ⇒ 还在动, 拒",
         evidence="录点三道闸 (8793/ctl/record_point)"),
]


def _cur(src_kind, key, sources):
    """取当前值 (只读真源)。"""
    kind, k = src_kind
    if kind == "calib":
        v = _dig(sources.get("calib") or {}, k)
    elif kind == "manifold":
        v = _dig(sources.get("manifold") or {}, k)
    elif kind == "dbc":
        v = (sources.get("dbc") or {}).get(k)
    elif kind == "cfgspec":
        v = sources.get("cfgspec")
    else:
        v = None
    return v


def build():
    calib, manifold = _jload(CALIB), _jload(MANIFOLD)
    dbc, levels, feats = read_feature_dbc(), read_levels(), read_features()
    cfgspec = read_cfg_spec_rows()
    src = {"calib": calib, "manifold": manifold, "dbc": dbc, "levels": levels,
           "features": feats, "cfgspec": cfgspec}

    chars, gaps, perms, grades = [], [], {}, {}
    for spec in PARAM_SPEC:
        rec = dict(spec)
        cur = _cur(spec["read"], None, src) if spec.get("read") else None
        rec["value"] = cur
        rec["ready"] = cur is not None
        if cur is None:
            rec["reason"] = ("现场未标定/未示教" if spec["grade"] == "G3"
                             else "真源非文件 (在役源码常量或权重) — 未做文件级描述"
                             if spec["perm"] == "readonly" else "未接线 (本项需实现期补真源)")
            gaps.append(spec["id"])
        grades[spec["grade"]] = grades.get(spec["grade"], 0) + 1
        perms[spec["perm"]] = perms.get(spec["perm"], 0) + 1
        chars.append(rec)

    groups = {}
    for c in chars:
        groups.setdefault(c["domain"], []).append(c["id"])

    mcd = {
        "_meta": {
            "schema": "zmax-mcd/1.0", "generated_at": time.strftime("%F %T"),
            "doc": "流形引擎标定·主参数 M 节点的 MCD 描述 (对标 ASAM MCD-2MC/A2L)。只描述, 不改在役值。",
            "sources": {
                "config/calib/zmax_calib.json": _sha16(CALIB),
                "config/calib/zmax_manifold.json": _sha16(MANIFOLD),
                "feature.dbc": _sha16(DBC),
                "src/lerobot/engineering/levels.py": _sha16(LEVELS_PY),
                "src/lerobot/verification/verification_layer.py": _sha16(VERIF_PY),
                "tools/gui/studio.py": _sha16(STUDIO_PY),
            },
            "counts": {"MEASUREMENT": len(MEASUREMENT), "CHARACTERISTIC": len(chars),
                       "COMPU_METHOD": len(COMPU), "DOMAINS": len(groups),
                       "ready": len(chars) - len(gaps), "gaps": len(gaps)},
        },
        "MEASUREMENT": MEASUREMENT,
        "CHARACTERISTIC": chars,
        "COMPU_METHOD": COMPU,
        "GROUPS": groups,
        "DIAGNOSTICS": {
            "assertions_total": len(feats),
            "assertions_auto": sum(1 for f in feats if f["auto"]),
            "by_level": {lv: sum(1 for f in feats if f["level"] == lv) for lv in ("L2", "L3", "L4")},
            "codes": [
                {"code": "MCD-E01", "cn": "真源陈旧 (帧龄超阈)", "src": "frame_age"},
                {"code": "MCD-E02", "cn": "参数越界 (超出 range)", "src": "CHARACTERISTIC.range"},
                {"code": "MCD-E03", "cn": "能力组合冲突 (同一参数被两条能力要求不同)", "src": "feature.combo"},
                {"code": "MCD-E04", "cn": "断言失败 (features 红项)", "src": "verification_layer"},
                {"code": "MCD-E05", "cn": "描述与在役读值不一致 (calib vs 运行时)", "src": "CHARACTERISTIC.value"},
            ],
        },
        "LEVELS": levels,
    }
    reg = {
        "_meta": {"schema": "zmax-param-registry/1.0", "generated_at": mcd["_meta"]["generated_at"],
                  "doc": "参数注册表 (扁平): 域×级×权限×就绪度。真源只读, 本表由 tools/mcd_build.py 生成。"},
        "params": chars,
        "summary": {"by_domain": {k: len(v) for k, v in groups.items()},
                    "by_grade": grades, "by_perm": perms,
                    "ready": len(chars) - len(gaps), "gaps": gaps},
        "feature_dbc": {"nodes": dbc["nodes"], "caps": dbc["caps"],
                        "combos": {k: len(v) for k, v in dbc["combos"].items()},
                        "cap_domains": {d: sum(1 for c in dbc["cap_domain"].values() if c == d)
                                        for d in sorted(set(dbc["cap_domain"].values()))}},
        "capability_map": [{"cap": c, "iface": dbc["cap_interfaces"].get(c, ""),
                            "domain": dbc["cap_domain"].get(c, "")} for c in dbc["caps"]],
        "levels": levels,
        "diagnostics": mcd["DIAGNOSTICS"],
    }
    return mcd, reg


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="幂等自检: 与盘上逐位比对")
    a = ap.parse_args()
    mcd, reg = build()
    txt_mcd, txt_reg = _dump(mcd), _dump(reg)
    c = mcd["_meta"]["counts"]

    if a.check:
        def _norm(txt):
            """比对时剔除易变字段 (生成时间戳) —— 幂等判据只看内容。"""
            try:
                o = json.loads(txt)
                o.get("_meta", {}).pop("generated_at", None)
                return json.dumps(o, ensure_ascii=False, sort_keys=True)
            except Exception:  # noqa: BLE001
                return txt

        ok = True
        for p, txt in ((MCD_JSON, txt_mcd), (REG_JSON, txt_reg)):
            old = open(p, encoding="utf-8").read() if os.path.isfile(p) else None
            same = (old is not None and _norm(old) == _norm(txt))
            ok &= same
            print(f"  {'✅' if same else '❌'} {os.path.relpath(p, ROOT)} "
                  f"({'内容一致 (时间戳除外)' if same else '内容不一致 — 真源变了, 需重生成'})")
        print(f"MCD 就绪度: {c['ready']}/{c['CHARACTERISTIC']} · 缺口 {c['gaps']}")
        return 0 if ok else 2

    os.makedirs(MCD_DIR, exist_ok=True)
    open(MCD_JSON, "w", encoding="utf-8").write(txt_mcd)
    open(REG_JSON, "w", encoding="utf-8").write(txt_reg)

    print(f"MCD 描述: {os.path.relpath(MCD_JSON, ROOT)}")
    print(f"参数注册表: {os.path.relpath(REG_JSON, ROOT)}")
    print(f"  段: MEASUREMENT {c['MEASUREMENT']} · CHARACTERISTIC {c['CHARACTERISTIC']} · "
          f"COMPU_METHOD {c['COMPU_METHOD']} · 域 {c['DOMAINS']}")
    print(f"  配置域: " + " · ".join(f"{k} {len(v)}" for k, v in mcd["GROUPS"].items()))
    print(f"  级分布: " + " · ".join(f"{k} {v}" for k, v in sorted(reg["summary"]["by_grade"].items())))
    print(f"  权限分布: " + " · ".join(f"{k} {v}" for k, v in sorted(reg["summary"]["by_perm"].items())))
    print(f"  capability: feature.dbc 节点 {len(reg['feature_dbc']['nodes'])} · 能力 {len(reg['feature_dbc']['caps'])} "
          f"· 域 {reg['feature_dbc']['cap_domains']} · 组合 {reg['feature_dbc']['combos']}")
    print(f"  档位契约: " + " · ".join(f"{k} 必须 {len(v['must'])} 项" for k, v in reg["levels"].items()))
    print(f"  诊断断言: {reg['diagnostics']['assertions_total']} 条 "
          f"(自动 {reg['diagnostics']['assertions_auto']} · {reg['diagnostics']['by_level']})")
    print(f"  就绪度: {reg['summary']['ready']}/{c['CHARACTERISTIC']} · 缺口 {c['gaps']}: {reg['summary']['gaps']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
