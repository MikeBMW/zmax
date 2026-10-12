#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**配置单 → 主参数 M** 的显式映射 (可审计, 唯一真源实现)。

老倪 2026-10-12 口述 (原话):
> 配置中心的参数, 要映射到主参数 M, 即我的配置单定下来, 主参数就被决定下来, 这个逻辑在**主参数 M 节点**实现,
> 主要是映射关系; 主参数 M 的功能, 要由**流形引擎节点**实现, 通过一个结构, 承接要实现的功能。

即**同一件事的两端**:
  · 主参数 M 节点 (画布 `n_calib_mani`) = **配置单 → M 的映射关系** (本模块 `compute_M`)
  · 流形引擎节点 (画布 `ss_mani_eng`)   = **用 M 实现功能** (度量几何/健康度 H/扭矩 τ) —— 消费 `M_SPEC`

主参数 M 的数学口径 (真源 src/lerobot/manifold/metric_field.py):
      度量张量  g_ij(x) = M · G_ij(x),   det G(x) = 1,  M ∈ [0, 8]
  · **M**  = 度量的**整体尺度** (物理=等效惯量尺度; a = F/M, 与旧标量语义逐字一致)
  · **G**  = 度量的**形状** (各向异性方向 + 随状态变化)

## 显式映射表 (配置项 → M 的哪个分量; 每条都写清来源依据 —— 老倪铁律: 不许编数字)

| 规则 | 目标分量 | 映射 | 来源依据 |
|---|---|---|---|
| R1 | **dim** (位姿自由度) | 工序含腕部姿态控制(旋转/翻转/姿态/腕部) ⇒ 6 (位姿 6 轴); 否则 3 (位置 3 轴) | 任务工序真源 config/tasks/tasks.json; metric_field 口径「位置 3 轴 / 位姿 6 轴」 |
| R2 | **mode** | 存在平移-姿态/图面-深度**耦合** ⇒ `full`; 同类轴**公差比 ≥1.25** ⇒ `diag`; 否则 `isotropic` | 性能指标真源 config/platform/zmax_perf_spec.json (工艺公差/耦合指标) + 任务配置 |
| R3 | **diag / components** (形状 G, det=1) | 各轴刚度 g_轴 ∝ 1/ε_轴 (公差不许偏的轴 ⇒ 距离更"贵"), 归一 det G = 1 | 逐轴工艺公差真源 (下方逐条列出 R3-各轴来源) |
| R4 | **gain** (状态相关 G(x)=G0+Σx_k G_k) | 动态交互场景 ⇒ 需现场辨识 G_k; 系数**待标定** (缺省 0 = 常度量) | MCD 设计 §6 可辨识性 (有限差分敏感性 S=∂J/∂参数) ⇒ 留实测入口 |
| R5 | **scale = M** | M = 1 + (½·m_eff·v_peak² + m_eff·g·h) / E_ref | 能量标定真源 tools/master_param_m.py + config/calib/zmax_calib.json#tool_payload.mass_kg + 任务工序速度 |

真源 (只读, 不造数; 缺就如实标缺):
  config/tasks/tasks.json · config/mcd/param_registry.json · config/mcd/zmax_mcd.json ·
  config/ss_task_binding.json · config/cc_snapshot.json · config/platform/zmax_perf_spec.json ·
  config/calib/zmax_manifold.json (可写真源) · config/calib/zmax_calib.json

写盘 (可选): 经 tools/zmax_params.py 的写盘闸门 (非正定拒写) 落 config/calib/zmax_manifold.json 的
  M / metric 段, 并写回画布节点 `n_calib_mani` 的 params (m_mapping / m_calc / m_loaded_at / m_source)。

用法:
    gui-venv311/bin/python tools/config_to_M.py                       # 活跃任务, 打印映射
    gui-venv311/bin/python tools/config_to_M.py --task TASK-06-TRAY    # 指定配置单
    gui-venv311/bin/python tools/config_to_M.py --all --json
    gui-venv311/bin/python tools/config_to_M.py --task TASK-06-TRAY --write   # 写 M 真源 + 节点
"""
from __future__ import annotations

import hashlib
import importlib.util as _ilu
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

# ── 真源路径 ──────────────────────────────────────────────────────────────────
F_TASKS = os.path.join(ROOT, "config", "tasks", "tasks.json")
F_REG = os.path.join(ROOT, "config", "mcd", "param_registry.json")
F_MCD = os.path.join(ROOT, "config", "mcd", "zmax_mcd.json")
F_BIND = os.path.join(ROOT, "config", "ss_task_binding.json")
F_CC = os.path.join(ROOT, "config", "cc_snapshot.json")
F_PERF = os.path.join(ROOT, "config", "platform", "zmax_perf_spec.json")
F_MANIFOLD = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")      # 可写真源 (软链)
F_CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")

NODE_ID = "n_calib_mani"
CANVAS_CANDIDATES = ("data/database/zmax/sources/canvas/state_space_obs.json",
                     "src/lerobot/engineering/flows/state_space_obs.json",
                     "flows/state_space_obs.json")

# ── 显式映射表 (可审计的规则元数据; compute_M 会为每条填上"本次实际取值") ──────────
MAPPING_RULES = [
    {"id": "R1", "target": "dim", "what": "位姿自由度 (度量维数)",
     "rule": "工序含腕部姿态控制(旋转/翻转/姿态/腕部) ⇒ dim=6 (位姿 6 轴); 否则 dim=3 (位置 3 轴)",
     "source": "config/tasks/tasks.json 工序真源 + metric_field 口径 (位置 3 轴 / 位姿 6 轴)"},
    {"id": "R2", "target": "mode", "what": "度量形状参数化 (isotropic/diag/full)",
     "rule": "存在平移-姿态 / 图面-深度耦合 ⇒ full; 同类轴公差比 ≥1.25 ⇒ diag; 否则 isotropic",
     "source": "config/platform/zmax_perf_spec.json (工艺公差/耦合指标) + config/tasks/tasks.json 任务配置"},
    {"id": "R3", "target": "diag|components", "what": "形状 G 各轴刚度 (det G=1)",
     "rule": "各轴刚度 g_轴 ∝ 1/ε_轴 (公差越小 ⇒ 该轴距离越贵); det 归一 ⇒ 尺度全归 M",
     "source": "逐轴工艺公差真源 (见 mapping_table 里 R3 的 eps_sources)"},
    {"id": "R4", "target": "gain", "what": "状态相关度量 G(x)=G0+Σ_k x_k G_k",
     "rule": "动态交互场景 ⇒ 需现场辨识 G_k; 系数待标定 (缺省 0 ⇒ 常度量, 零回归)",
     "source": "MCD 设计 §6 可辨识性 (有限差分敏感性) ⇒ 标'待标定' + 留实测入口"},
    {"id": "R5", "target": "scale(M)", "what": "度量整体尺度 = 等效惯量尺度",
     "rule": "M = 1 + (½·m_eff·v_peak² + m_eff·g·h) / E_ref   →  clamp[0,8]",
     "source": "tools/master_param_m.py 能量标定真源 + config/calib/zmax_calib.json#tool_payload.mass_kg "
               "+ config/tasks/tasks.json 工序速度"},
]

# 位姿自由度关键词 (只在**工序步骤**里认, 避免把图像的'倾角'/'位姿叠加'误判为臂的自由度)
_POSE_KW = ("旋转", "翻转", "姿态", "定向", "朝向")
# 耦合证据关键词 (平移↔姿态 / 图面↔深度 / 手眼闭环)
_COUPLE_KW = ("侧边", "Δx", "手眼", "TSAI", "闭环", "耦合", "对齐", "AA", "有源")


# ───────────────────────── 基础工具 ─────────────────────────
def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                           # noqa: BLE001
        return d


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _num(s):
    """取字符串里第一个数 (含小数/负号)。找不到 → None (不猜)。"""
    m = re.search(r"([-+]?\d+(?:\.\d+)?)", str(s))
    return float(m.group(1)) if m else None


def _mm_num(s):
    """取字符串里第一个带 mm 的数。"""
    m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*mm", str(s))
    return float(m.group(1)) if m else None


def _deg_num(s):
    """取字符串里第一个带 ° 的数。"""
    m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*°", str(s))
    return float(m.group(1)) if m else None


def _reload(name, relpath):
    """按文件路径加载 projects/tools 下的独立模块 (与画布节点同一套加载法)。"""
    p = relpath if os.path.isabs(relpath) else os.path.join(ROOT, relpath)
    spec = _ilu.spec_from_file_location(name, p)
    m = _ilu.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


# ───────────────────────── 真源装载 ─────────────────────────
def load_bundle(root: str | None = None) -> dict:
    """读全部配置真源 (只读; 缺项如实标 missing)。"""
    R = root or ROOT
    b = {
        "tasks": _j(os.path.join(R, "config/tasks/tasks.json"), {}) or {},
        "param_registry": _j(os.path.join(R, "config/mcd/param_registry.json"), {}) or {},
        "mcd": _j(os.path.join(R, "config/mcd/zmax_mcd.json"), {}) or {},
        "binding": _j(os.path.join(R, "config/ss_task_binding.json"), {}) or {},
        "cc_snapshot": _j(os.path.join(R, "config/cc_snapshot.json"), {}) or {},
        "perf": _j(os.path.join(R, "config/platform/zmax_perf_spec.json"), {}) or {},
        "manifold": _j(os.path.join(R, "config/calib/zmax_manifold.json"), {}) or {},
        "calib": _j(os.path.join(R, "config/calib/zmax_calib.json"), {}) or {},
    }
    b["missing"] = [k for k, v in b.items() if not v]
    return b


def perf_metric(perf: dict, mid: str) -> dict | None:
    """在 perf_spec 的 groups[*].metrics 里按 id 找指标 (真源字段, 不自算)。"""
    for g in (perf.get("groups") or []):
        for m in (g.get("metrics") or []):
            if m.get("id") == mid:
                return m
    return None


def _m_val(perf: dict, mid: str):
    """指标目标值里第一个数 (mm/°/s/…)。"""
    m = perf_metric(perf, mid)
    return (_num(m.get("target")) if m else None), (m.get("target") if m else None)


def _reg_param(reg: dict, pid: str) -> dict | None:
    for p in (reg.get("params") or []):
        if p.get("id") == pid:
            return p
    return None


def active_task_id(bundle: dict) -> str:
    """活跃配置单: 优先任务绑定 (真源), 否则第一张配置单。"""
    tid = (bundle.get("binding") or {}).get("active_task")
    if tid:
        return tid
    ts = (bundle.get("tasks") or {}).get("tasks") or []
    return ts[0].get("task_id", "") if ts else ""


def find_task(bundle: dict, task_id: str | None) -> dict:
    ts = (bundle.get("tasks") or {}).get("tasks") or []
    tid = task_id or active_task_id(bundle)
    for t in ts:
        if t.get("task_id") == tid:
            return t
    return ts[0] if ts else {}


# ───────────────────────── R1: dim ─────────────────────────
def derive_dim(task: dict) -> dict:
    hits = []
    for s in (task.get("steps") or []):
        txt = "%s %s" % (s.get("name", ""), s.get("desc", ""))
        for k in _POSE_KW:
            if k in txt:
                hits.append("step[%s]: 命中'%s' ← %s" % (s.get("name"), k, str(s.get("desc"))[:60]))
                break
    dim = 6 if hits else 3
    return {"id": "R1", "target": "dim", "value": dim,
            "rule": MAPPING_RULES[0]["rule"], "source": MAPPING_RULES[0]["source"],
            "evidence": ("工序要求腕部姿态控制 ⇒ 位姿 6 轴" if hits else "工序无姿态自由度 ⇒ 位置 3 轴"),
            "hits": hits or ["工序步骤无姿态控制关键词 ⇒ dim=3"]}


# ───────────────────────── R2/R3: mode + 形状 ─────────────────────────
def has_coupling(task: dict) -> list:
    """耦合证据 (平移↔姿态 / 图面↔深度 / 手眼闭环)。"""
    hits = []
    blob = json.dumps({k: task.get(k) for k in ("overrides", "targets", "steps")}, ensure_ascii=False)
    for k in _COUPLE_KW:
        if k in blob:
            hits.append("命中'%s'" % k)
    return hits


def derive_tolerances(task: dict, perf: dict, bundle: dict) -> dict:
    """逐轴工艺公差 (mm / °) + 逐条来源。优先级: 任务显式 > 工序步骤 > 性能指标真源。"""
    eps, src = {}, {}
    # ① 侧向 (x,y): 任务 targets 里的"精度/偏差" → 工序步骤里的"偏差<X mm" → perf.mate_align_repeat
    lat, lsrc = None, ""
    for k, v in (task.get("targets") or {}).items():
        if ("精度" in str(k) or "偏差" in str(k)):
            n = _mm_num(v) or _num(v)
            if n:
                lat, lsrc = n, "tasks.targets[%s]=%s" % (k, v)
                break
    if lat is None:
        for s in (task.get("steps") or []):
            n = _mm_num(s.get("desc"))
            if n and any(w in str(s.get("desc")) for w in ("偏差", "精度", "对准", "对位")):
                lat, lsrc = n, "tasks.steps[%s].desc=%s" % (s.get("name"), str(s.get("desc"))[:60])
                break
    if lat is None:
        n, tgt = _m_val(perf, "perf.mate_align_repeat")
        lat, lsrc = (n or 0.05), "perf_spec#perf.mate_align_repeat=%s" % tgt
    eps["x"] = eps["y"] = lat
    src["x"] = src["y"] = lsrc
    # ② 深度 (z): 有插装工序 ⇒ perf.insert_depth_res (插深分辨率); 否则与侧向同 (无偏向)
    ins = any(str(k).startswith("ins.") for k in (task.get("overrides") or {})) or \
        any(w in json.dumps(task.get("steps"), ensure_ascii=False) for w in ("插入", "直推", "插光纤", "插电口"))
    if ins:
        n, tgt = _m_val(perf, "perf.insert_depth_res")
        eps["z"] = n or 0.02
        src["z"] = "perf_spec#perf.insert_depth_res=%s (任务含插装工序 ⇒ 用插深控制分辨率)" % tgt
    else:
        eps["z"], src["z"] = lat, "(无插装 ⇒ 深度与侧向同公差: %s)" % lsrc
    # ③ 姿态 (dim=6 才有): 任务 place.angle_tol_deg → tasks 里的"≤X°" → perf.mate_angle_repeat
    ang, asrc = None, ""
    for k, v in (task.get("overrides") or {}).items():
        if "angle" in str(k).lower() or "姿态" in str(k):
            n = _deg_num(v) or _num(v)
            if n:
                ang, asrc = n, "tasks.overrides[%s]=%s" % (k, v)
                break
    if ang is None:
        for k, v in (task.get("targets") or {}).items():
            n = _deg_num(v)
            if n:
                ang, asrc = n, "tasks.targets[%s]=%s" % (k, v)
                break
    if ang is None:
        n, tgt = _m_val(perf, "perf.mate_angle_repeat")
        ang, asrc = (n or 0.10), "perf_spec#perf.mate_angle_repeat=%s" % tgt
    eps["rx"] = eps["ry"] = eps["rz"] = ang
    src["rx"] = src["ry"] = src["rz"] = asrc
    return {"eps": eps, "src": src}


def derive_shape(task: dict, dim: int, tol: dict) -> dict:
    """R2 + R3: mode + diag/components (各轴刚度 ∝ 1/公差, 归一 det=1)。"""
    eps, src = tol["eps"], tol["src"]
    axis = ["x", "y", "z"] + (["rx", "ry", "rz"] if dim == 6 else [])
    # 轴间公差比 (只在**同类**物理量内比: 线性 mm 与角度 ° 不同量纲, 不混比)
    lin = [eps[a] for a in ("x", "y", "z") if a in axis]
    r_lin = (max(lin) / min(lin)) if (lin and min(lin) > 0) else 1.0
    coup = has_coupling(task)
    if coup:
        mode = "full"
        why = "存在平移↔姿态/图面↔深度耦合证据 ⇒ 允许非对角分量的 full 度量"
        ev = coup
    elif r_lin >= 1.25:
        mode = "diag"
        why = "同类轴公差比 %.2f ≥ 1.25 ⇒ 各轴刚度不等 ⇒ diag 度量" % r_lin
        ev = ["ε_xy=%.4g mm · ε_z=%.4g mm ⇒ 比 %.2f" % (eps["x"], eps["z"], r_lin)]
    else:
        mode = "isotropic"
        why = "各轴公差一致 (比 %.2f < 1.25) ⇒ 各向同性 (G=I, Γ=0, 零回归)" % r_lin
        ev = ["同类轴公差一致 (比 %.2f)" % r_lin]
    w = {a: (1.0 / eps[a] if eps[a] and eps[a] > 0 else 1.0) for a in axis}     # 刚度 ∝ 1/公差
    out = {"id": "R2+R3", "target": "mode|diag|components", "value": mode, "rule": MAPPING_RULES[1]["rule"],
           "source": MAPPING_RULES[1]["source"], "reason": why, "evidence": ev,
           "tolerance_sources": {a: src[a] for a in axis}, "axis_stiffness_raw": w,
           "axis_tolerance": {a: eps[a] for a in axis}, "axis_order": axis,
           "diag": None, "components": None}
    if mode in ("diag", "full"):
        # diag: 顺次给出各轴刚度 (MetricField.shape_from_diag 会归一 det=1)
        out["diag"] = [round(w[a], 9) for a in axis]
        if mode == "full":
            # full 用 Cholesky 因子 (下三角, 行主序) 表达: L=diag(sqrt(w)) ⇒ 退化为对角;
            # 非对角 (真耦合) 分量**待标定** ⇒ 置 0 (结构就位, 现场辨识后填入) —— 不编数
            import numpy as _np
            v = []
            for i, a in enumerate(axis):
                for j in range(i + 1):
                    v.append(round(float(_np.sqrt(w[a])) if i == j else 0.0, 9))
            out["components"] = v
            out["offdiag_note"] = ("非对角(真耦合)分量待现场辨识: 有限差分敏感性 S=∂J/∂参数; "
                                   "当前置 0 ⇒ 度量退化对角 (与 diag 等价), 结构已就位")
    return out


# ───────────────────────── R4: gain (状态相关) ─────────────────────────
def derive_gain(task: dict, dim: int) -> dict:
    scene = str(task.get("scene_ref") or "")
    dyn = any(w in json.dumps(task, ensure_ascii=False) for w in ("实时", "AR", "闭环", "在线", "飞拍"))
    n = dim
    return {"id": "R4", "target": "gain", "value": None,
            "rule": MAPPING_RULES[3]["rule"], "source": MAPPING_RULES[3]["source"],
            "status": "待标定" if dyn else "不需要 (静态任务 ⇒ 常度量)",
            "evidence": (["场景 %s 含实时/闭环交互 ⇒ 需要状态相关度量 G(x)" % scene] if dyn
                         else ["场景 %s 为静态工序 ⇒ 常度量 (gain=None) 即够" % scene]),
            "expected_shape": [n, n, n],
            "measure_hook": ("现场辨识: 扫状态 x_k 量目标函数 J, 有限差分 S=∂J/∂G_k; "
                             "|S| 落噪声带内 ⇒ 报'本场不可辨识'(不填假数); 写入 metric.gain 后启用")}


# ───────────────────────── R5: scale (M) ─────────────────────────
def _task_to_project(task: dict) -> str:
    """任务 → 能量标定项目 (master_param_m.PROJECTS)。来源: recipe_type 关键词。"""
    rt = str(task.get("recipe_type") or "")
    if "摆盘" in rt or "取放" in rt:
        return "PROJ-TH-TRAY"
    return "PROJ-LOAD-UNLOAD"


def _max_step_speed(task: dict):
    """从工序步骤描述里取最大线速度 (m/s)。真源: 任务工序。"""
    best, who = None, ""
    for s in (task.get("steps") or []):
        for m in re.finditer(r"([-+]?\d+(?:\.\d+)?)\s*m/s", str(s.get("desc", ""))):
            v = float(m.group(1))
            if best is None or v > best:
                best, who = v, "step[%s] 命中'%s'" % (s.get("name"), m.group(0))
    return best, who


def derive_scale(task: dict, bundle: dict) -> dict:
    """R5: 能量标定公式 (与 tools/master_param_m.py 同源同式)。"""
    MP = _reload("master_param_m", "tools/master_param_m.py")
    project = _task_to_project(task)
    P = MP.PROJECTS[project]
    tool = ((bundle.get("calib") or {}).get("tool_payload") or {}).get("mass_kg")
    tsrc = "config/calib/zmax_calib.json#tool_payload.mass_kg"
    if tool is None:
        tool, tsrc = 1.0, "假设(可标定): tool_payload 缺, 暂按 1.0kg"
    part = 0.025
    m_eff = float(tool) + part
    v_parsed, vsrc = _max_step_speed(task)
    if v_parsed is not None:
        v, v_source = v_parsed, "工序真源 %s (tasks.json)" % vsrc
    else:
        v, v_source = float(P["v_peak_mps"]), "假设(可标定) 继承 %s: %s" % (project, P["v_src"])
    h, h_source = float(P["stroke_m"]), P["stroke_src"]
    e_kin = 0.5 * m_eff * v * v
    e_pot = m_eff * MP.G * h
    e_task = e_kin + e_pot
    M = 1.0 + e_task / MP.E_REF
    M = max(MP.M_RANGE[0], min(MP.M_RANGE[1], round(M, 3)))
    return {"id": "R5", "target": "scale", "value": M,
            "rule": MAPPING_RULES[4]["rule"], "source": MAPPING_RULES[4]["source"],
            "project": project, "project_name": P["name"],
            "m_eff_kg": round(m_eff, 4),
            "inputs": {"夹具/吸嘴 kg": float(tool), "工件 kg": part, "v_peak_mps": v, "stroke_m": h},
            "input_sources": {"夹具/吸嘴": tsrc, "工件": "真源: 光模块 QSFP 级 ≈25g (master_param_m 注释)",
                              "峰值速度": v_source, "行程": h_source},
            "E_kin_J": round(e_kin, 4), "E_pot_J": round(e_pot, 4), "E_task_J": round(e_task, 4),
            "E_ref_J": MP.E_REF, "energy_level": MP.energy_level(M),
            "formula": "M = 1 + (½·m_eff·v² + m_eff·g·h) / E_ref   (E_ref=%.1f J, g=%.2f m/s²)" % (MP.E_REF, MP.G)}


# ───────────────────────── 汇总: compute_M ─────────────────────────
def compute_M(task_id: str | None = None, bundle: dict | None = None,
              root: str | None = None) -> dict:
    """**配置单 → 主参数 M** (唯一映射函数; 主参数 M 节点 = 本函数)。

    返回 {ok, task_id, dim, mode, scale(M), diag, components, gain, metric, mapping_table, audit_sha}。
    """
    b = bundle or load_bundle(root)
    task = find_task(b, task_id)
    tid = task.get("task_id", "")
    r1 = derive_dim(task)
    tol = derive_tolerances(task, b.get("perf") or {}, b)
    r23 = derive_shape(task, r1["value"], tol)
    r4 = derive_gain(task, r1["value"])
    r5 = derive_scale(task, b)
    metric = {"dim": r1["value"], "mode": r23["value"],
              "diag": r23["diag"], "components": r23["components"], "gain": r4["value"]}
    table = [r1, r23, r4, r5]
    audit = {"task_id": tid, "task_name": task.get("name", ""), "recipe_type": task.get("recipe_type", ""),
             "scene_ref": task.get("scene_ref", ""), "metric": metric, "mapping_table": table}
    return {"ok": True, "task_id": tid, "name": task.get("name", ""), "recipe_type": task.get("recipe_type", ""),
            "scene_ref": task.get("scene_ref", ""),
            "dim": r1["value"], "mode": r23["value"], "scale": r5["value"],
            "diag": r23["diag"], "components": r23["components"], "gain": r4["value"],
            "energy_level": r5["energy_level"], "E_task_J": r5["E_task_J"],
            "metric": metric, "mapping_table": table, "audit_sha": _sha(audit),
            "sources": {"tasks": "config/tasks/tasks.json", "bind": "config/ss_task_binding.json",
                        "perf": "config/platform/zmax_perf_spec.json", "reg": "config/mcd/param_registry.json",
                        "mcd": "config/mcd/zmax_mcd.json", "cc": "config/cc_snapshot.json"},
            "missing": b.get("missing") or []}


# ───────────────────────── 写盘: M 真源 (带非正定闸门) ─────────────────────────
def write_master_param(spec: dict, root: str | None = None, write_M: bool = True) -> dict:
    """把 spec 的 M/metric 写进真源 config/calib/zmax_manifold.json (经 zmax_params 写盘闸门)。

    **非正定拒写** (闸门在 zmax_params.write_manifold_metric + 本处预检): 非法形状直接返回 ok=False, 不碰盘。
    """
    zp = _reload("zmax_params", "tools/zmax_params.py")
    from lerobot.manifold.metric_field import raw_shape_positive_definite                     # noqa: PLC0415
    dim, mode = int(spec["dim"]), str(spec["mode"])
    diag, comps = spec.get("diag"), spec.get("components")
    ok_pd, mn = raw_shape_positive_definite(dim, mode, diag, comps)
    if not ok_pd:
        return {"ok": False, "gate": "非正定 (归一化前 min_eig %.4g ≤ 0 或 det ≤ 0) ⇒ 拒写" % mn,
                "dim": dim, "mode": mode, "min_eig": mn}
    r_metric = zp.write_manifold_metric(dim=dim, mode=mode, diag=diag, comps=comps)
    if not r_metric.get("ok"):
        return {"ok": False, "gate": r_metric.get("why") or "metric 写盘被拒", "metric": r_metric}
    r_M = None
    if write_M:
        r_M = zp.write_manifold_M(float(spec["scale"]), None)      # inertia=None ⇒ 保持现状 (不代开)
    back = zp.manifold_metric()
    return {"ok": True, "dest": r_metric.get("dest"), "min_eig": r_metric.get("min_eig"),
            "metric_readback": back, "M_write": r_M}


# ───────────────────────── 写盘: 画布节点 params ─────────────────────────
def canvas_path(root: str | None = None) -> str:
    R = root or ROOT
    for rel in CANVAS_CANDIDATES:
        p = os.path.join(R, rel)
        if os.path.isfile(p):
            return p
    return os.path.join(R, CANVAS_CANDIDATES[-1])


def _find_node(d: dict):
    for n in (d.get("nodes") or []):
        pr = n.get("params") or {}
        if n.get("id") == NODE_ID or pr.get("manifold_calib") \
                or "标定诊断测量" in str(n.get("name", "")) or "主参数 M" in str(n.get("name", "")):
            return n
    return None


def node_params(spec: dict) -> dict:
    """该写进主参数 M 节点的稳定字段 (不含时间戳 ⇒ 幂等可判)。"""
    return {"m_role": "配置单 → 主参数 M 的**映射关系** (本节点 = 决策端); 用 M 的功能在流形引擎节点",
            "m_source": "tools/config_to_M.py",
            "m_source_symbol": "def compute_M(",
            "m_task": spec["task_id"],
            "m_dim": spec["dim"], "m_mode": spec["mode"], "m_scale": spec["scale"],
            "m_diag": spec["diag"], "m_components": spec["components"], "m_gain": spec["gain"],
            "m_energy_level": spec["energy_level"], "m_E_task_J": spec["E_task_J"],
            "m_metric": spec["metric"],
            "m_mapping": spec["mapping_table"],
            "m_audit_sha": spec["audit_sha"],
            "m_sources": spec["sources"]}


def write_into_node(spec: dict, root: str | None = None, dry: bool = False) -> dict:
    """把映射结果写回画布节点 `n_calib_mani` 的 params (只写 m_* 键; id/端口/连线不动)。"""
    from lerobot.engineering import flows                                                  # noqa: PLC0415
    d, probs = flows.load_canvas()
    if probs:
        return {"ok": False, "err": "画布校验不过: %s" % (list(probs)[:3],)}
    node = _find_node(d)
    if node is None:
        return {"ok": False, "err": "画布上找不到主参数 M 节点 (%s)" % NODE_ID}
    params = node.setdefault("params", {})
    want = node_params(spec)
    want["m_loaded_at"] = time.strftime("%F %T")
    changed = [k for k, v in want.items()
               if json.dumps(params.get(k), ensure_ascii=False, sort_keys=True)
               != json.dumps(v, ensure_ascii=False, sort_keys=True)]
    if dry:
        return {"ok": True, "dry": True, "node": node.get("id"), "would_write": changed}
    params.update(want)
    p, bak = flows.save_canvas(d, reason="config_to_M")
    d2, probs2 = flows.load_canvas()
    n2 = _find_node(d2)
    p2 = (n2 or {}).get("params") or {}
    ok = (not probs2) and p2.get("m_audit_sha") == spec["audit_sha"] and p2.get("m_loaded_at") == want["m_loaded_at"]
    return {"ok": bool(ok), "node": (n2 or {}).get("id"), "written": changed,
            "backup": os.path.basename(bak) if bak else "", "canvas": os.path.relpath(p, ROOT),
            "nodes": len(d2.get("nodes") or []), "links": len(d2.get("links") or []),
            "loaded_at": want["m_loaded_at"]}


# ───────────────────────── CLI ─────────────────────────
def _print_spec(s: dict):
    print("═" * 78)
    print("配置单 %s — %s (%s)  scene=%s" % (s["task_id"], s["name"], s["recipe_type"], s.get("scene_ref", "")))
    print("  ┌─ 主参数 M = 度量张量 g_ij(x) = M·G_ij(x), det G=1")
    print("  │  dim      = %d      (R1: 位姿自由度)" % s["dim"])
    print("  │  mode     = %-9s (R2: 形状参数化)" % s["mode"])
    print("  │  scale(M) = %-7g  (R5: 能量标定, 能级 %s, E_task=%.3f J)" % (s["scale"], s["energy_level"], s["E_task_J"]))
    print("  │  diag     = %s" % s["diag"])
    print("  │  comps    = %s" % s["components"])
    print("  └─ gain     = %s" % s["gain"])
    for r in s["mapping_table"]:
        print("  [%s] %-14s → %s" % (r["id"], r["target"], r.get("value")))
        print("        规则: %s" % r["rule"])
        print("        依据: %s" % r["source"])
        _ev = r.get("evidence") or r.get("hits") or []
        if isinstance(_ev, str):
            _ev = [_ev]
        _extra = r.get("hits") if isinstance(r.get("hits"), list) else []
        for e in (list(_ev) + list(_extra))[:5]:
            print("        · %s" % e)
        if r.get("axis_tolerance"):
            for a in r.get("axis_order") or []:
                print("        · 轴 %-3s ε=%-8.4g 来源: %s" % (a, r["axis_tolerance"][a], r["tolerance_sources"][a]))
        if r["id"] == "R5":
            for k, v in (r.get("input_sources") or {}).items():
                print("        · 输入 %-10s 来源: %s" % (k, v))
    print("  审计哈希 audit_sha = %s" % s["audit_sha"][:16])
    print("═" * 78)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="配置单 → 主参数 M 的显式映射")
    ap.add_argument("--task", default=None, help="配置单 task_id (缺省=活跃任务)")
    ap.add_argument("--all", action="store_true", help="全部配置单")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="写 M 真源 + 画布节点")
    ap.add_argument("--no-node", action="store_true", help="只写 M 真源, 不写画布节点")
    a = ap.parse_args(argv)
    b = load_bundle()
    if b["missing"]:
        print("⚠️ 缺真源: %s" % ", ".join(b["missing"]))
    ids = [t.get("task_id") for t in (b["tasks"].get("tasks") or [])] if a.all else [a.task or active_task_id(b)]
    out = {}
    for tid in ids:
        s = compute_M(tid, bundle=b)
        out[tid] = s
        if a.json:
            continue
        _print_spec(s)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    if a.write:
        for tid, s in out.items():
            w = write_master_param(s)
            print("[%s] 写 M 真源: %s" % (tid, "✅" if w.get("ok") else "⛔ " + str(w.get("gate"))))
            if w.get("ok"):
                print("     回读 metric = %s · M = %s · 闸门 min_eig = %.4g"
                      % (w["metric_readback"].get("mode"), w["M_write"]["M"] if w.get("M_write") else "?",
                         w.get("min_eig", float("nan"))))
                if not a.no_node:
                    wn = write_into_node(s)
                    print("     写节点 %s: %s (改了 %s)" % (wn.get("node"), "✅" if wn.get("ok") else "❌",
                                                            ",".join(wn.get("written") or []) or "无变化"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
