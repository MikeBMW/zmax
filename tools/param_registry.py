#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""param_registry.py — 全局可改数字注册表 (数据一体化工程 · 2026-10-09 老倪)

老倪:
  「全局梳理所有可以更改的数字, 所有数字可以跟用户交互式编辑, 有默认值, 有调试参数, 有最大最小值;
    当改变任意数值, 均可链动 功能·性能·代码逻辑; 修改不同层的数据即表现出不同功能特性;
    从顶层产品性能的数据改变, 直接调整代码; 中间的代码要完整映射这个全局架构。」

一句话: **一个数字 → 一条链路** (产品性能 → 子系统 → 功能 → 模块 → 代码位置), 改数字必须能说清
        它动了什么、影响了什么、写回了哪个真源文件的哪一行。

五类数字 (颜色是 UI 用的用途色):
  🟡 calib    标定/真源参数    config/calib/*.json 叶子 (相机/外参/台面/工具/TCP/主参数 M)   [可写·走标定真源写口]
  🔵 canvas   画布节点数据      state_space 画布节点 params 的数值项 (帧数/维度/权重…)      [可写·走 flows.save_canvas]
  🟣 code     代码常量          源码里的模块级数值常量 (安全阈值/深度/步长/维度…)              [可写·带备份+语法校验+可回滚]
  🟢 platform 产品/性能指标     产品特征 KPI 目标 (插入成功率/精度/节拍…)                     [可写·真源 zmax_platform.json]
  🟠 switch   运行开关/调试     L3 模式/L4 推理频率/流形偏航/L2 兼容 等档位开关               [可写·枚举档位]

范围 (min/max/默认/单位/中文名) 真源: config/platform/param_spec.json (人可编, 缺省自动播种);
没有 spec 的数字**不猜范围**, 标 status="范围未定义" 并在 UI 里显式提示。

CLI: python3 tools/param_registry.py scan|stats|list|show <id>|set <id> <value> [--write]|verify|chain <id>|seed
"""
import ast
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
MANIFOLD = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
CANVAS = os.path.join(ROOT, "src", "lerobot", "engineering", "flows", "state_space_obs.json")
PLATFORM = os.path.join(ROOT, "config", "platform", "zmax_platform.json")
SPEC = os.path.join(ROOT, "config", "platform", "param_spec.json")
EVENTS_LEGACY = os.path.join(ROOT, "data", "database", "zmax", "param_events.jsonl")   # 旧 jsonl, 仅供一次性并入库; 新事件直接写库 param_events 表
# 🆕 2026-10-10 老倪: 「空间点的 7 个点已经标记了…我要改变空间点的位置, 如何在参数中心修改?」
#    —— 点位此前只躺在 data/skills/l2_atomic/space_points.json 里, 参数中心里查不到 ⇒ 接进来 (可写+回写+留痕)
SPACE = os.path.join(ROOT, "data", "skills", "l2_atomic", "space_points.json")
TAUGHT = os.path.join(ROOT, "data", "skills", "l2_atomic", "taught_points.json")   # 号位/示教点 (61 个点)

# 代码常量扫描范围 (只扫与链路直接相关的实现文件, 不做全仓乱扫)
CODE_FILES = [
    "src/lerobot/policies/left_right/state_space/safety.py",
    "src/lerobot/policies/left_right/state_space/planner.py",
    "src/lerobot/policies/left_right/state_space/cognition.py",
    "src/lerobot/policies/left_right/state_space/dynamics.py",
    "src/lerobot/policies/left_right/state_space/execution.py",
    "src/lerobot/policies/left_right/state_space/perception.py",
    "src/lerobot/policies/left_right/state_space/parallel.py",
    "src/lerobot/policies/left_right/state_space/focus_quality.py",
    "src/lerobot/policies/left_right/state_space/hil_bridge.py",
    "src/lerobot/engineering/nodes/library.py",
]
CODE_NAME_HINT = re.compile(r"(dim|size|thr|threshold|tol|margin|eps|limit|max|min|rate|scale|gain|beta|"
                            r"steps|every|speed|depth|frames|count|num_|n_|hz|ms|sec|pct|ratio|factor|"
                            r"weight|coef|align|gap|offset|cap|budget|window|len)", re.I)
CODE_SKIP = re.compile(r"^(VERSION|__|ROOT|DIR|PATH|URL|PORT|COLOR|C_|FONT|_|DPI|WIDTH_HEIGHT)$")

# 人工 spec (中文名/单位/min/max/默认/档位/影响说明) — 缺省由 build_spec_seed() 落成
# config/platform/param_spec.json, 之后以该文件为准 (人可编)
CURATED = {
    "calib:camera.K[0][0]": {"cn": "相机焦距 fx (像素)", "unit": "px", "min": 100, "max": 5000},
    "calib:camera.fy": {"cn": "相机焦距 fy (像素)", "unit": "px", "min": 100, "max": 5000},
    "calib:camera.cx": {"cn": "光心 cx (像素)", "unit": "px", "min": 0, "max": 4096},
    "calib:camera.cy": {"cn": "光心 cy (像素)", "unit": "px", "min": 0, "max": 4096},
    "calib:camera.K": {"cn": "相机内参矩阵 K (3x3)", "unit": "-"},
    "calib:T_base_cam": {"cn": "基座→相机 手眼外参 (4x4)", "unit": "m/rad",
                         "impact": "视觉伺服/3D 定位全部依赖; 改了直接影响抓取对位精度"},
    "calib:plane_z": {"cn": "工作台面高度 plane_z", "unit": "m", "min": 0.0, "max": 1.0,
                      "impact": "3D 反投影落点; 影响插入高度与安全下限"},
    "calib:depth_scale": {"cn": "深度尺度 (D405 = 0.1mm/单位)", "unit": "mm/单位", "min": 0.01, "max": 10.0},
    "calib:cell_geometry": {"cn": "工位几何 (点位/基准)", "unit": "m"},
    "calib:robot": {"cn": "机器人运动学/限位", "unit": "-"},
    "calib:tool_payload": {"cn": "工具负载 (质量/质心)", "unit": "kg/m"},
    "calib:control_tcp": {"cn": "TCP 控制点 (offset/欧拉)", "unit": "m/rad"},
    "calib:manifold_engine.M": {"cn": "主参数 M (流形引擎)", "unit": "-", "min": 0.0, "max": 10.0,
                                "impact": "L4 流形/势场/稳定性; 改档 = 改功能特性"},
    "code.insert_depth": {"cn": "插入深度 (m)", "unit": "m", "min": 0.0, "max": 0.05, "default": 0.002,
                          "impact": "L2 收口: 插入动作的下压量"},
    "switch.l3_mode": {"cn": "L3 全链模式", "unit": "-", "choices": ["off", "partial", "full"],
                       "impact": "L3 高级自动功能开关 (full=全链)"},
    "switch.l4_intact_every": {"cn": "L4 INTACT 推理间隔 (步)", "unit": "步", "min": 1, "max": 64, "default": 8},
    "switch.l4_intent_beta": {"cn": "L4 意图混合系数 β", "unit": "-", "min": 0.0, "max": 1.0, "default": 0.5},
    "switch.l4_intent_every": {"cn": "L4 意图推理间隔 (步)", "unit": "步", "min": 1, "max": 64, "default": 16},
    "switch.l2_compat": {"cn": "L2 兼容模式", "unit": "-", "choices": ["on", "off"], "default": "on"},
    "switch.flow_yaw": {"cn": "流形偏航 (仅 L4 90°档)", "unit": "deg", "min": -180, "max": 180},
}
CAT_COLOR = {"calib": "#ffc857", "canvas": "#4da3ff", "code": "#b07cff",
             "platform": "#00d4aa", "switch": "#ff9f43", "space": "#ff5fa2", "teach": "#c084fc"}
CAT_CN = {"calib": "标定/真源参数", "canvas": "画布节点数据", "code": "代码常量",
          "platform": "产品/性能指标", "switch": "运行开关", "space": "空间点", "teach": "号位/示教点"}


# ── 工具 ──────────────────────────────────────────────────────────────────
_PATH_TOK = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _path_tokens(ref):
    return [(m.group(1) if m.group(1) is not None else int(m.group(2))) for m in _PATH_TOK.finditer(ref)]


def _get_path(d, ref):
    """按 'camera.K[0]' 取值 (支持列表下标); 取不到返回 None."""
    cur = d
    for t in _path_tokens(ref):
        if isinstance(t, int):
            if not isinstance(cur, (list, tuple)) or t >= len(cur):
                return None
            cur = cur[t]
        else:
            if not isinstance(cur, dict) or t not in cur:
                return None
            cur = cur[t]
    return cur


def _path_exists(d, ref):
    """路径存在即为真 (值可以是 null —— 未标定缺口本来就是 null, 不能当成'读不到')"""
    cur = d
    for t in _path_tokens(ref):
        if isinstance(t, int):
            if not isinstance(cur, (list, tuple)) or t >= len(cur):
                return False
            cur = cur[t]
        else:
            if not isinstance(cur, dict) or t not in cur:
                return False
            cur = cur[t]
    return True


def _set_path(d, ref, value):
    toks = _path_tokens(ref)
    cur = d
    for i, t in enumerate(toks[:-1]):
        nxt = toks[i + 1]
        if isinstance(t, int):
            if not isinstance(cur, list) or t >= len(cur):
                return False
            cur = cur[t]
        else:
            if not isinstance(cur, dict):
                return False
            if t not in cur:
                cur[t] = [] if isinstance(nxt, int) else {}
            cur = cur[t]
    last = toks[-1]
    if isinstance(last, int):
        if not isinstance(cur, list) or last >= len(cur):
            return False
        cur[last] = value
    else:
        cur[last] = value
    return True


def _load(p, dflt=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                         # noqa: BLE001
        return dflt


def _unit_of(key):
    k = str(key).lower()
    for pat, u in (("_mm_per_px", "mm/px"), ("_mm", "mm"), ("mm", "mm"), ("deg", "deg"), ("_rad", "rad"),
                   ("rad", "rad"), ("_ms", "ms"), ("_s", "s"), ("hz", "Hz"), ("_pct", "%"),
                   ("px", "px"), ("_kg", "kg"), ("_m", "m")):
        if k.endswith(pat) or pat in k.split("_")[-1:]:
            return u
    return "-"


def _infer_range(v, spec):
    if "min" in spec or "max" in spec:
        return spec.get("min"), spec.get("max"), spec.get("status", "已定义")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None, None, "范围未定义"
    if isinstance(v, float) and 0.0 <= v <= 1.0:
        return 0.0, 1.0, "范围未定义"
    span = max(abs(float(v)) * 10.0, 1.0)
    return (-span if v < 0 else 0.0), span, "范围未定义"


def _spec_of(pid, extra=None):
    s = dict(CURATED.get(pid, {}))
    if extra:
        s.update(extra)
    return s


# ── 扫描: 五类数字 ────────────────────────────────────────────────────────
def scan_calib():
    out = []
    for path in (CALIB, MANIFOLD):
        d = _load(path, {})
        rel = os.path.relpath(path, ROOT)
        for k, v in (d or {}).items():
            if str(k).startswith("_"):
                continue
            if isinstance(v, (dict, list)):
                for ref, val in _walk(v, str(k)):
                    out.append(_mk("calib:%s" % ref, ref, val, rel, "json:%s" % ref, "calib"))
            elif isinstance(v, (int, float, bool)) or v is None:
                out.append(_mk("calib:%s" % k, k, v, rel, "json:%s" % k, "calib"))
    return out


def _scan_pts_file(path, group, group_cn_label):
    """通用: 把一个 *points.json (points.<点名>.pos[3]/quat[4]) 展开成可写参数。

    老倪 2026-10-10: 「所有点都要有参数, 可以修改」⇒ 空间点 + 号位示教点两套都按这个扫。
    范围口径: 位置 ±1.2m (工作包络, 抓取动作在 0.3~0.9m), 四元数 −1..1 (数学定义域)。
    """
    out = []
    d = _load(path, {})
    rel = os.path.relpath(path, ROOT)
    for nm, v in (d.get("points") or {}).items():
        if not isinstance(v, dict):
            continue
        desc = str(v.get("desc") or "")
        imp = desc[:70] if desc else "L2 MoveIt 运动规划起点 (%s)" % group_cn_label
        for i, val in enumerate(v.get("pos") or []):
            out.append(_mk("%s:%s.pos[%d]" % (group, nm, i), "%s.pos[%d]" % (nm, i), float(val), rel,
                           "json:points.%s.pos[%d]" % (nm, i), group,
                           extra={"cn": "%s · %s (m)" % (nm, "XYZ"[i]), "unit": "m",
                                  "min": -1.2, "max": 1.2, "fn_ref": "FN-SYS0-59", "sys_hint": "sys0",
                                  "impact": imp}))
        for i, val in enumerate(v.get("quat") or []):
            out.append(_mk("%s:%s.quat[%d]" % (group, nm, i), "%s.quat[%d]" % (nm, i), float(val), rel,
                           "json:points.%s.quat[%d]" % (nm, i), group,
                           extra={"cn": "%s · 四元数%s" % (nm, "xyzw"[i]), "unit": "-",
                                  "min": -1.0, "max": 1.0, "fn_ref": "FN-SYS0-59", "sys_hint": "sys0",
                                  "impact": imp}))
    return out


def scan_space():
    """🆕 2026-10-10: 空间点 (8793 站台页标定的 空间1..N, 真源 space_points.json)。"""
    return _scan_pts_file(SPACE, "space", "空间点")


def scan_teach():
    """🆕 2026-10-10: 号位/示教点 (真源 taught_points.json, 61 个点: slot1/2, insert_pose,
    金手指点1/2, aoi_gold_view, loop20_*/afx*_* 循环路点 …) —— 同样全部可在线改。"""
    return _scan_pts_file(TAUGHT, "teach", "号位/示教点")



def _walk(v, pre):
    if isinstance(v, dict):
        for k2, v2 in v.items():
            if str(k2).startswith("_"):
                continue
            if isinstance(v2, (dict, list)):
                yield from _walk(v2, "%s.%s" % (pre, k2))
            elif isinstance(v2, (int, float, bool)) or v2 is None:
                yield "%s.%s" % (pre, k2), v2
    elif isinstance(v, list):
        for i, v2 in enumerate(v):
            if isinstance(v2, (dict, list)):
                yield from _walk(v2, "%s[%d]" % (pre, i))
            elif isinstance(v2, (int, float, bool)) or v2 is None:
                yield "%s[%d]" % (pre, i), v2


CANVAS_META = {"state_space", "row_bg", "bg", "status", "hidden", "collapsed", "plane", "grid"}


def scan_canvas():
    out = []
    fl = _load(CANVAS, {})
    for n in fl.get("nodes", []) or []:
        p = n.get("params") or {}
        if not isinstance(p, dict):
            continue
        for k, v in p.items():
            if k.startswith("_") or k in CANVAS_META or not isinstance(v, (int, float, bool)):
                continue
            out.append(_mk("canvas:%s#%s" % (n.get("name", "?"), k), k, v,
                           os.path.relpath(CANVAS, ROOT), "canvas:%s.params.%s" % (n.get("name", "?"), k),
                           "canvas", sys_hint=n.get("name", "")))
    return out


KPI_NUM = re.compile(r"([<>≥≤]=?\s*)(\d+(?:\.\d+)?)\s*(%|mm|ms|s|Hz|kg|deg|N)?")


def scan_platform():
    """顶层产品性能的数字: KPI 文本里的量化目标 (插入成功率 ≥99% · 头到孔底 <4mm …), 可写回文本"""
    out = []
    d = _load(PLATFORM, {})
    for f in d.get("product_features", []) or []:
        kpi = str(f.get("kpi") or "")
        for i, m in enumerate(KPI_NUM.finditer(kpi)):
            item = _mk("platform:%s#%d" % (f.get("pf_id"), i), "kpi[%d]" % i, float(m.group(2)),
                       os.path.relpath(PLATFORM, ROOT), "kpi:%s#%d" % (f.get("pf_id"), i), "platform",
                       extra={"cn": "%s · %s" % (f.get("title", ""), kpi[max(0, m.start() - 8):m.end() + 3]),
                              "unit": m.group(3) or "-", "fn_ref": f.get("pf_id"),
                              "impact": "产品性能目标 (顶层定义): 改它 = 改验收口径 / 整机指标基线",
                              "sys_hint": ",".join(f.get("subsys", []) or [])})
            item["writable"] = True
            out.append(item)
    return out


def scan_code():
    out = []
    for rel in CODE_FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        try:
            tree = ast.parse(open(p, encoding="utf-8").read())
        except Exception:                                                     # noqa: BLE001
            continue
        src = open(p, encoding="utf-8").read().splitlines()
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            t = node.targets[0]
            if not isinstance(t, ast.Name) or not node.value.__class__ is ast.Constant:
                continue
            v = node.value.value
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            nm = t.id
            big = os.path.getsize(p) > 60000
            if CODE_SKIP.match(nm) or len(nm) < 3 or (big and not CODE_NAME_HINT.search(nm)):
                continue
            if not big and nm.lower() in ("width", "height", "dpi", "line_width", "font_size"):
                continue
            line = node.lineno
            out.append(_mk("code:%s#%s" % (rel, nm), nm, v, rel, "code:%s:%d" % (rel, line), "code",
                           extra={"line": line, "code_text": (src[line - 1] if line - 1 < len(src) else "").strip()}))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = list(node.args.args) + list(node.args.kwonlyargs)
            defs = list(node.args.defaults) + list(node.args.kw_defaults)
            if not defs:
                continue
            for a_, d_ in zip(args[-len(defs):], defs):
                if not isinstance(d_, ast.Constant) or not isinstance(d_.value, (int, float)) \
                        or isinstance(d_.value, bool):
                    continue
                an = a_.arg
                if len(an) < 3 or not CODE_NAME_HINT.search(an):
                    continue
                out.append(_mk("code:%s#%s:%s" % (rel, node.name, an), an, d_.value, rel,
                               "code:%s:%s:%d" % (rel, an, d_.lineno), "code",
                               extra={"line": d_.lineno, "cn": "%s(%s) 默认值" % (an, node.name),
                                      "code_text": (src[d_.lineno - 1] if d_.lineno - 1 < len(src) else "").strip()}))
    return out


def scan_switch():
    """运行开关/调试档位: 由 CURATED 声明 (枚举档位 + 默认值), 是「调试参数」的注册面。"""
    return [_mk(pid, pid.split(".", 1)[1], spec.get("default"), os.path.relpath(SPEC, ROOT),
                "spec:%s" % pid, "switch", extra={"sys_hint": spec.get("sys", "sys1")})
            for pid, spec in CURATED.items() if pid.startswith("switch.")]


def _mk(pid, name, value, src, ref, group, extra=None, sys_hint=""):
    spec = _spec_of(pid, extra)
    kind = ("enum" if spec.get("choices") else "bool" if isinstance(value, bool) else "numeric")
    lo, hi, st = _infer_range(value, spec)
    if isinstance(value, bool):
        lo, hi, st = 0, 1, "已定义"
    if value is None:
        st = "未标定(缺口)" if group == "calib" else "未定义"
        if spec.get("min") is not None or spec.get("max") is not None:
            st += " · 范围已定义"
    cn = spec.get("cn") or str(name)
    return {"param_id": pid, "group": group, "name": name, "cn": cn, "value": value,
            "default": spec.get("default", value), "min": lo, "max": hi, "step": spec.get("step"),
            "unit": spec.get("unit") or _unit_of(name), "choices": spec.get("choices"), "kind": kind,
            "source": src, "ref": ref, "writable": not str(pid).startswith("platform:"),
            "status": st, "line": spec.get("line"), "impact": spec.get("impact"),
            "fn_ref": spec.get("fn_ref"), "sys_hint": spec.get("sys_hint", sys_hint),
            "color": CAT_COLOR.get(group, "#9aa7b4"), "cat_cn": CAT_CN.get(group, group)}


def scan():
    ps = scan_calib() + scan_canvas() + scan_platform() + scan_code() + scan_switch() + scan_space() + scan_teach()
    seen, out = set(), []
    for p in ps:
        if p["param_id"] in seen:
            continue
        seen.add(p["param_id"])
        out.append(p)
    return sorted(out, key=lambda x: (x["group"], x["param_id"]))


# ── spec 播种 (人可编真源) ────────────────────────────────────────────────
def build_spec_seed(force=False):
    if os.path.exists(SPEC) and not force:
        return False
    d = {"_doc": "参数元数据真源 (人可编): 中文名/单位/默认/min/max/档位/影响说明/归属系统。"
                 "缺省范围由 tools/param_registry.py 自动播种, code=auto 的行可人工收紧。",
         "version": "1.0", "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
         "params": {}}
    for p in scan():
        if not p["writable"] and p["status"] == "范围未定义" and p["unit"] == "-":
            continue
        d["params"][p["param_id"]] = {"cn": p["cn"], "unit": p["unit"], "default": p["default"],
                                      "min": p["min"], "max": p["max"], "choices": p["choices"],
                                      "sys": p["sys_hint"] or None, "status": p["status"], "code": "auto"}
    for pid, spec in CURATED.items():
        d["params"].setdefault(pid, {}).update({k: spec[k] for k in spec if k != "impact"})
        if spec.get("impact"):
            d["params"][pid]["impact"] = spec["impact"]
        d["params"][pid]["code"] = "curated"
    os.makedirs(os.path.dirname(SPEC), exist_ok=True)
    with open(SPEC, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    return True


def registry():
    build_spec_seed()
    file_spec = (_load(SPEC, {}) or {}).get("params", {})
    ps = scan()
    for p in ps:
        s = file_spec.get(p["param_id"])
        if s:
            for k, kk in (("cn", "cn"), ("unit", "unit"), ("min", "min"), ("max", "max"),
                          ("choices", "choices"), ("impact", "impact"), ("sys", "sys_hint")):
                if s.get(k) not in (None, ""):
                    p[kk] = s[k]
            if s.get("default") is not None and p["status"] == "范围未定义":
                p["default"] = s["default"]
            if s.get("min") is not None or s.get("max") is not None:
                _code = s.get("code", "manual")
                if p["value"] is None:
                    p["status"] = "未定义 · 范围已给"
                elif _code in ("curated", "manual"):
                    p["status"] = "已定义(人工)"
                else:
                    p["status"] = "范围自动推断(未确认)"
            if p["value"] is None and p["group"] == "calib":
                p["status"] = "未标定(缺口)" if "已定义" not in p["status"] else "未标定(缺口) · 范围已定义"
            p["spec_code"] = s.get("code", "manual")
    groups = {}
    for p in ps:
        groups.setdefault(p["group"], []).append(p)
    return {"params": ps, "groups": groups, "by_id": {p["param_id"]: p for p in ps}}


# ── 影响链: 参数 → 功能 → 模块 → 代码 → KPI ──────────────────────────────
def effect_chain(pid, reg=None):
    reg = reg or registry()
    p = reg["by_id"].get(pid)
    if not p:
        return {"ok": False, "err": "参数不存在: %s" % pid}
    out = {"ok": True, "param": pid, "cn": p["cn"], "value": p["value"], "unit": p["unit"],
           "cat": p["cat_cn"], "source": p["source"], "ref": p["ref"], "functions": [], "modules": [],
           "code": [], "kpis": [], "systems": []}
    # 标定段 → 子系统/功能 (按段名归属)
    seg = pid.split(":", 1)[1].split(".")[0] if pid.startswith("calib:") else ""
    SEG2SYS = {"camera": "sys0", "T_base_cam": "sys0", "plane_z": "sys0", "depth_scale": "sys0",
               "cell_geometry": "sys0", "robot": "sys0", "tool_payload": "sys0", "control_tcp": "sys0",
               "manifold_engine": "sys2"}
    SEG2FN = {"camera": ["🎯 YOLO 目标检测", "🖼️ D405 真机取流"], "T_base_cam": ["🖼️ D405 真机取流"],
              "plane_z": ["🛠 动作解码"], "depth_scale": ["🖼️ D405 真机取流"],
              "cell_geometry": ["🛠 动作解码"], "manifold_engine": ["🏆 L4 专家自主功能 · 标定与流形世界模型"]}
    if seg in SEG2SYS:
        out["systems"].append(SEG2SYS[seg])
        out["modules"] += SEG2FN.get(seg, [])
    hint = p.get("sys_hint") or ""
    for s in re.findall(r"sys[012]", hint):
        out["systems"].append(s)
    if p["group"] == "canvas":
        node = pid.split(":", 1)[1].split("#")[0]
        out["functions"].append(node)
        out["modules"].append(node)
    if p["group"] == "code":
        out["code"].append({"file": p["source"], "line": p.get("line"), "symbol": p["name"],
                            "text": p.get("code_text", "")})
    if p.get("fn_ref"):
        out["kpis"].append(p["fn_ref"])
    # 代码常量按模块源码归属反查 (同文件的功能节点)
    if p["group"] == "calib":
        for f in SEG2FN.get(seg, []):
            if f not in out["functions"]:
                out["functions"].append(f)
    try:
        import importlib.util as _iu
        spec = _iu.spec_from_file_location("_edb", os.path.join(ROOT, "tools", "engineering_db.py"))
        if spec and spec.loader and os.path.exists(os.path.join(ROOT, "data/database/zmax/zmax_engineering.db")):
            edb = _iu.module_from_spec(spec)
            spec.loader.exec_module(edb)                                       # type: ignore[union-attr]
            D = edb.load()
            fns = D.get("functions", [])
            out["systems"] = sorted(set(out["systems"]))
            for f in fns:
                if f["name"] in out["modules"] or (out["systems"] and f["system_id"] in out["systems"]):
                    out["functions"].append("%s (%s)" % (f["name"], f["system_id"]))
            out["functions"] = sorted(dict.fromkeys(out["functions"]))[:24]
            for pf in D.get("product_features", []):
                if out["systems"] and any(s in (pf.get("subsys") or "") for s in out["systems"]):
                    out["kpis"].append("%s ← %s" % (pf["title"], pf["kpi"][:60]))
            out["kpis"] = list(dict.fromkeys(out["kpis"]))[:8]
    except Exception as e:                                                     # noqa: BLE001
        out["warn"] = "链路补全降级: %s" % e
    return out


# ── 写: 校验 → 备份 → 落真源 → 回读 ───────────────────────────────────────
def _validate(p, value):
    if p["kind"] == "bool":
        v = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on", "yes", "是")
        return v, None
    if p["kind"] == "enum":
        ch = p.get("choices") or []
        sv = str(value)
        if ch and sv not in [str(c) for c in ch]:
            return None, "档位非法: %s ∉ %s" % (sv, ch)
        return sv, None
    try:
        v = float(value)
    except Exception:                                                          # noqa: BLE001
        return None, "不是数字: %r" % (value,)
    if isinstance(p["value"], int) and float(v).is_integer():
        v = int(v)
    if p.get("min") is not None and v < p["min"]:
        return None, "低于最小 %s" % p["min"]
    if p.get("max") is not None and v > p["max"]:
        return None, "超过最大 %s" % p["max"]
    return v, None


def _backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    b = "%s.bak_%s" % (path, ts)
    shutil.copy2(path, b)
    return b


def _guard_point(path, ref, value):
    """点位写前哨 (2026-10-10): ① 包络 ±1.2m ② 互距 —— 防手误把点写进夹具/写到别的点身上。

    只拦**新产生**的重合对: 老数据里本来就有点挨得近(循环路点差 0.2µm), 不能因此把整份文件锁死。
    """
    if ref.rstrip().endswith("]") and ".pos[" in ref:
        try:
            if abs(float(value)) > 1.2:
                return False, "❌ pos 值 %.4f 超出工作包络 ±1.2m ⇒ 拒写" % float(value)
        except (TypeError, ValueError):
            return False, "❌ pos 值不是数字 ⇒ 拒写"
    d = json.loads(json.dumps(_load(path, {})))
    leaf = ref.split("json:", 1)[1]

    def _pts(x):
        return {k: [float(v) for v in vv.get("pos")]
                for k, vv in (x.get("points") or {}).items() if isinstance(vv, dict) and vv.get("pos")}

    before = _pts(d)
    if not _set_path(d, leaf, value):
        return False, "路径不可写: %s" % leaf
    after = _pts(d)
    b_pairs = {frozenset((a, b)) for a, b in itertools.combinations(before, 2)
               if math.dist(before[a], before[b]) < 0.001}
    new = [(a, b, math.dist(after[a], after[b])) for a, b in itertools.combinations(after, 2)
           if math.dist(after[a], after[b]) < 0.001 and frozenset((a, b)) not in b_pairs]
    if new:
        a, b, dist = new[0]
        return False, "❌ 改完 '%s' 与 '%s' 只差 %.2fmm (疑似手误写到别的点上) ⇒ 拒写" % (a, b, dist * 1000)
    return True, "包络/互距 ✓"


def _write_json_path(path, ref, value):
    ref = ref.split("json:", 1)[1]
    d = _load(path, {})
    if not _set_path(d, ref, value):
        return False, "路径不可写: %s" % ref
    bak = _backup(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    back = _read_json_path(path, ref)
    return (back == value), ("已写 %s (备份 %s)" % (os.path.basename(path), os.path.basename(bak)))


def _read_json_path(path, ref):
    # ref 可能已带/不带 "json:" 前缀 ( _write_json_path 内部已剥一次, 回读时别再炸 —— 2026-10-10 修)
    return _get_path(_load(path, {}), ref.split("json:", 1)[-1])


def _write_canvas_param(pid, value):
    node_name, key = pid.split(":", 1)[1].split("#", 1)
    fl = _load(CANVAS, {})
    hit = False
    for n in fl.get("nodes", []) or []:
        if n.get("name") == node_name:
            n.setdefault("params", {})[key] = value
            hit = True
    if not hit:
        return False, "画布节点没找到: %s" % node_name
    bak = _backup(CANVAS)
    with open(CANVAS, "w", encoding="utf-8") as f:
        json.dump(fl, f, ensure_ascii=False, indent=1)
    back = None
    for n in _load(CANVAS, {}).get("nodes", []) or []:
        if n.get("name") == node_name:
            back = (n.get("params") or {}).get(key)
    return (back == value), "已写画布 (备份 %s); 画布页需重新加载该工程生效" % os.path.basename(bak)


def _write_code_default(pid, value):
    """改函数签名里的默认值 (如 cognition.py 的 insert_depth=0.0005)"""
    rel = pid.split(":", 1)[1].split("#", 1)[0]
    arg = pid.split("#", 1)[1].split(":")[-1]
    path = os.path.join(ROOT, rel)
    lines = open(path, encoding="utf-8").read().splitlines(keepends=True)
    pat = re.compile(r"(\b%s\s*=\s*)(-?[\d.]+)" % re.escape(arg))
    hit = next((i for i, ln in enumerate(lines) if pat.search(ln)), None)
    if hit is None:
        return False, "没找到默认值 %s" % arg
    bak = _backup(path)
    lines[hit] = pat.sub(lambda m: m.group(1) + (repr(value) if not isinstance(value, int) else str(value)),
                         lines[hit], count=1)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    rc = subprocess.run([sys.executable, "-c", "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read())",
                         path], capture_output=True, text=True)
    if rc.returncode != 0:
        shutil.copy2(bak, path)
        return False, "语法校验失败已回滚"
    m2 = pat.search(open(path, encoding="utf-8").read().splitlines()[hit])
    back = float(m2.group(2)) if m2 else None
    return (back is not None and abs(back - float(value)) < 1e-12), \
        "已写 %s 第 %d 行 %s (备份 %s)" % (rel, hit + 1, arg, os.path.basename(bak))


def _write_platform_kpi(pid, value):
    """改 KPI 文本里的第 n 个数字 (顶层产品性能目标), 保留比较符/单位"""
    pf, idx = pid.split(":", 1)[1].split("#", 1)
    d = _load(PLATFORM, {})
    tgt = next((f for f in (d.get("product_features") or []) if f.get("pf_id") == pf), None)
    if tgt is None:
        return False, "产品特征不存在: %s" % pf
    kpi = str(tgt.get("kpi") or "")
    ms = list(KPI_NUM.finditer(kpi))
    i = int(idx)
    if i >= len(ms):
        return False, "KPI 文本里没有第 %d 个数字" % (i + 1)
    m = ms[i]
    new = kpi[:m.start(2)] + ("%.6g" % value) + kpi[m.end(2):]
    tgt["kpi"] = new
    bak = _backup(PLATFORM)
    with open(PLATFORM, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    back = None
    for f in _load(PLATFORM, {}).get("product_features", []) or []:
        if f.get("pf_id") == pf:
            back = str(f.get("kpi"))
    return (back == new), "已写产品性能目标: %s (备份 %s)" % (new[:60], os.path.basename(bak))


def _write_code_const(pid, value):
    rel = pid.split(":", 1)[1].split("#", 1)[0]
    sym = pid.split("#", 1)[1]
    path = os.path.join(ROOT, rel)
    src = open(path, encoding="utf-8").read()
    pat = re.compile(r"^(%s\s*=\s*)(-?[\d.]+)(\s*(?:#.*)?)$" % re.escape(sym), re.M)
    m = pat.search(src)
    if not m:
        return False, "没找到模块级常量赋值: %s" % sym
    lit = repr(value) if not isinstance(value, int) else str(value)
    new = pat.sub(lambda mm: mm.group(1) + lit + mm.group(3), src, count=1)
    bak = _backup(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    rc = subprocess.run([sys.executable, "-c", "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read())",
                         path], capture_output=True, text=True)
    if rc.returncode != 0:                          # 语法坏了立即回滚, 绝不留下坏文件
        shutil.copy2(bak, path)
        return False, "语法校验失败已回滚: %s" % (rc.stderr.strip().splitlines()[-1:] or "")
    back = None
    m2 = pat.search(open(path, encoding="utf-8").read())
    if m2:
        try:
            back = float(m2.group(2))
        except Exception:                                                      # noqa: BLE001
            back = None
    return (back is not None and abs(float(back) - float(value)) < 1e-12), \
        "已写 %s:%s (备份 %s)" % (rel, sym, os.path.basename(bak))


def _log_event(ev):
    """改数留痕 → 唯一工程库 (param_events 表)。2026-10-09 起不再写 jsonl (老倪: 所有数据整合进统一数据库)。"""
    ev = dict(ev)
    ev.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
    return _edb().log_param_event(ev)


_EDB_CACHE = {}


def _edb():
    """懒加载 tools/engineering_db.py (事件/参数的唯一落库口径都在那边)。"""
    if "m" in _EDB_CACHE:
        return _EDB_CACHE["m"]
    import importlib.util as _iu
    sp = _iu.spec_from_file_location("_edb_pr", os.path.join(ROOT, "tools", "engineering_db.py"))
    m = _iu.module_from_spec(sp)
    sp.loader.exec_module(m)
    _EDB_CACHE["m"] = m
    return m


def set_param(pid, value, write=False, reg=None):
    """校验 → (可选) 落真源 → 回读核对 → 返回链路影响。write=False 只做预览(dry-run)。"""
    reg = reg or registry()
    p = reg["by_id"].get(pid)
    if not p:
        return {"ok": False, "err": "参数不存在: %s" % pid}
    if not p["writable"]:
        return {"ok": False, "err": "该参数只读 (产品/性能指标真源在 zmax_platform.json, 请在平台页编辑)"}
    v, err = _validate(p, value)
    if err:
        return {"ok": False, "err": err, "param": pid, "range": [p.get("min"), p.get("max")], "unit": p["unit"]}
    res = {"ok": True, "param": pid, "cn": p["cn"], "old": p["value"], "new": v, "unit": p["unit"],
           "cat": p["cat_cn"], "source": p["source"], "written": False, "dry_run": not write}
    if write:
        if p["group"] == "calib":
            path = CALIB if "zmax_calib" in p["source"] else MANIFOLD
            ok, msg = _write_json_path(path, p["ref"], v)
        elif p["group"] == "platform":
            ok, msg = _write_platform_kpi(pid, v)
        elif p["group"] == "canvas":
            ok, msg = _write_canvas_param(pid, v)
        elif p["group"] == "space":
            # 🆕 空间点: 回写真源 data/skills/l2_atomic/space_points.json (带备份 + 回读核对)
            ok, msg = _guard_point(SPACE, p["ref"], v)
            if ok:
                ok, msg = _write_json_path(SPACE, p["ref"], v)
        elif p["group"] == "teach":
            # 🆕 号位/示教点: 回写真源 taught_points.json (同样带写前哨)
            ok, msg = _guard_point(TAUGHT, p["ref"], v)
            if ok:
                ok, msg = _write_json_path(TAUGHT, p["ref"], v)
        elif p["group"] == "code":
            ok, msg = (_write_code_default(pid, v) if ":" in pid.split("#", 1)[1]
                       else _write_code_const(pid, v))
        else:                       # switch: 记到 switch 真源文件 (运行开关档位)
            ok, msg = _write_json_path(SPEC.replace("param_spec.json", "run_switches.json"),
                                       "json:" + pid.split(".", 1)[1], v) if os.path.exists(
                SPEC.replace("param_spec.json", "run_switches.json")) else (True, "档位记录 (运行开关真源未建)")
        res["written"], res["msg"] = ok, msg
        res["ok"] = ok
        _log_event({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "param": pid, "cn": p["cn"], "old": p["value"],
                    "new": v, "unit": p["unit"], "cat": p["group"], "source": p["source"],
                    "written": ok, "msg": msg})
        reg = registry()
    res["chain"] = effect_chain(pid, reg)
    return res


def stats():
    reg = registry()
    g = {k: {"n": len(v), "writable": sum(1 for x in v if x["writable"]),
             "定义范围": sum(1 for x in v if x["status"] == "已定义"),
             "范围未定义": sum(1 for x in v if x["status"] == "范围未定义")} for k, v in reg["groups"].items()}
    return {"total": len(reg["params"]), "groups": g, "events": _edb().count_param_events()}


def verify():
    msgs, bad = [], []
    reg = registry()
    msgs.append("① 注册表 %d 个数字: %s" % (len(reg["params"]),
                                        " ".join("%s=%d" % (k, len(v)) for k, v in sorted(reg["groups"].items()))))
    spec_params = (_load(SPEC, {}) or {}).get("params", {})
    for p in reg["params"]:
        if not os.path.exists(os.path.join(ROOT, p["source"])):
            bad.append("真源文件不存在: %s (%s)" % (p["source"], p["param_id"]))
        if p["group"] == "switch" and p["param_id"] not in spec_params:
            bad.append("运行开关未在 spec 真源登记: %s" % p["param_id"])
        if p["group"] != "canvas" and p["ref"].startswith("json:") and p["group"] != "switch":
            _raw = _load(os.path.join(ROOT, p["source"]), {})
            _ref = p["ref"].split("json:", 1)[1]
            cur = _get_path(_raw, _ref)
            if not _path_exists(_raw, _ref):
                bad.append("真源路径读不到: %s (%s)" % (p["ref"], p["param_id"]))
            elif cur is not None and p["value"] is not None and abs(float(cur) - float(p["value"])) > 1e-9:
                bad.append("库值≠真源: %s 库=%s 源=%s" % (p["param_id"], p["value"], cur))
        if p["status"] == "已定义" and p["min"] is not None and p["max"] is not None:
            if float(p["min"]) > float(p["max"]):
                bad.append("min>max: %s" % p["param_id"])
    msgs.append("② 每个数字的真源可读 (库==源)")
    ids = {p["param_id"] for p in reg["params"]}

    def _has(suf):
        return any(suf in i for i in ids)

    for suf in ("manifold_engine.M", "plane_z", "camera.K["):
        (msgs if _has(suf) else bad).append("③ 关键参数在册 (后缀): %s" % suf)
    for chk in ("code:%s#%s" % (CODE_FILES[1], "VETO_TH"),):
        pass
    msgs.append("③ 关键参数在册 (主参数 M / plane_z / 相机内参 K)")
    for p in reg["params"]:
        if p["writable"] and p["kind"] == "numeric" and p["value"] is not None and "自动推断" not in p["status"]:
            v, err = _validate(p, p["value"])
            if err:
                bad.append("自校验失败: %s (%s)" % (p["param_id"], err))
    msgs.append("④ 已定义范围的数字自校验通过")
    return (not bad), msgs + (["❌ " + b for b in bad[:10]] if bad else ["✅ 全绿"])


# ── CLI ───────────────────────────────────────────────────────────────────
def main():
    a = sys.argv[1:] or ["stats"]
    cmd = a[0]
    if cmd == "scan" or cmd == "list":
        reg = registry()
        for p in reg["params"]:
            print("%-46s %-10s %-8s %-8s %-18s %s" % (p["param_id"][:46], p["cat_cn"], p["value"], p["unit"],
                                                      p["status"], ("可写" if p["writable"] else "只读")))
    elif cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=1))
    elif cmd == "seed":
        print("已播种 config/platform/param_spec.json" if build_spec_seed(force=True) else "spec 已存在")
    elif cmd == "show" or cmd == "chain":
        print(json.dumps(effect_chain(a[1]) if cmd == "chain" else
                         (registry()["by_id"].get(a[1]) or {"err": "无此参数"}), ensure_ascii=False, indent=1))
    elif cmd == "set":
        write = "--write" in a
        print(json.dumps(set_param(a[1], a[2], write=write), ensure_ascii=False, indent=1))
    elif cmd == "verify":
        ok, msgs = verify()
        for m in msgs:
            print("  " + m)
        print(("✅ 参数注册表判据全绿" if ok else "❌ 有失败"))
        sys.exit(0 if ok else 1)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
