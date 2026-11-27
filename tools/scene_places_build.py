#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景位置细胞(place cells)库构建器 —— 工程参数中心的「3D 元素精确坐标」单一真源。

老倪 2026-11-09:
  「这些 3D 元素的坐标在哪里? 状态空间工程的参数中心, 应该记录 3D 场景元素的精确坐标;
    ar3d 是可视化的窗口, 但是工程配置中, 要有所有的配置坐标; L2 层的记忆库, 要记录所有这些
    位置信息, 与大脑神经元的位置细胞同样作用。」

所以: 坐标不许散在页面常量/围栏 JSON/示教点/AR 活数据里各说各话, 由本脚本从各**测量真源**
汇总成一张表 `data/skills/l2_atomic/place_cells.json`, 每个元素一枚「位置细胞」:
    id / kind / pos_mm(base_link) / size_mm / shape / parent / tags / prov(出处+精度+测量时间)

真源(只读, 本脚本不发明数字):
  1. zmax_data/ar_rs/fences.json            —— 工装/料盘/42 槽/插孔/检测设备/横梁 (实测 AABB, 米)
  2. data/skills/l2_atomic/space_points.json —— 示教空间点 1~8 (真机 TCP 真值 + 姿态)
  3. zmax_data/ar_live/ar_aoi_live.json      —— AOI 站点(金手指点1/2·侧面点0~3·准备/安全点)
  4. tools/web/tcp-ar.html 常量              —— 结构件(箱体 CHS / 实验桌 TAB / 地面 FLR / 顶视相机 TCAM)
  5. zmax_data/ar_mujoco/ar_env.xml          —— 仿真场景件(只用于对拍, 不当真值)

用法:
  python3 tools/scene_places_build.py            # 构建 + 自检 + 写库
  python3 tools/scene_places_build.py --check    # 只自检不写(对比库里已存的, 报漂移)
  python3 tools/scene_places_build.py --json     # 只打印摘要 JSON
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "data", "skills", "l2_atomic", "place_cells.json")

SRC_FENCES = os.path.join(REPO, "zmax_data", "ar_rs", "fences.json")
SRC_SPACE = os.path.join(REPO, "data", "skills", "l2_atomic", "space_points.json")
SRC_AOI = os.path.join(REPO, "zmax_data", "ar_live", "ar_aoi_live.json")
SRC_TAUGHT = os.path.join(REPO, "data", "skills", "l2_atomic", "taught_points.json")
SRC_PAGE = os.path.join(REPO, "tools", "web", "tcp-ar.html")
SRC_XML = os.path.join(REPO, "zmax_data", "ar_mujoco", "ar_env.xml")


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:12]


def _mm(v):
    return round(float(v) * 1000.0, 2)


def _slug(s):
    """中文/emoji 名字 → 稳定 id 段(去 emoji 与标点, 数字保留)。"""
    s = re.sub(r"[^\w\u4e00-\u9fa5]+", "", s or "")
    return s or "x"


# ─────────────────────────── 1. 围栏/工装 (fences.json) ───────────────────────────
def _tray_of(name):
    """槽 → 所属料盘 id 段。命名真源: 槽N=右臂料盘 · 左槽N=左臂料盘 · 下槽N=下料盘。"""
    if name.startswith("左槽"):
        return "tray.left"
    if name.startswith("下槽"):
        return "tray.out"
    if name.startswith("槽"):
        return "tray.right"
    return None


def read_fences():
    d = json.load(open(SRC_FENCES, encoding="utf-8"))
    items = d.get("items", d if isinstance(d, list) else [])
    cells, idx_boxes = [], []
    TRAY_IDS = {"🧰 黑色料盘(实测)": "tray.right", "🧰 左臂料盘(顶视左侧·Y+)": "tray.left",
                "🧰 下料盘(第三·14槽)": "tray.out", "🗑 废料盘(不良品·无槽位)": "tray.waste"}
    FIX_IDS = {"🔌 光模块插孔(口767→814·实测)": "socket.optical",
               "长方体-侧面检测相机": "fixture.side_cam",
               "前方相机(深度实测)": "fixture.front_cam",
               "检测设备": "fixture.inspect_station",
               "长方体-上横梁": "fixture.cross_beam"}
    for i, it in enumerate(items):
        if it.get("type") != "box":
            continue                       # line = 原子技能包络/围栏折线, 不是场景元素
        name = (it.get("name") or "").strip()
        p1, p2 = it.get("p1"), it.get("p2")
        if not p1 or not p2:
            continue
        lo = [min(a, b) for a, b in zip(p1, p2)]
        hi = [max(a, b) for a, b in zip(p1, p2)]
        pos = [_mm((a + b) / 2) for a, b in zip(lo, hi)]
        size = [_mm(b - a) for a, b in zip(lo, hi)]
        parent = _tray_of(name)
        if parent:
            kind = "slot"
        elif "料盘" in name or "废料盘" in name:
            kind = "tray"
        elif "插孔" in name:
            kind = "socket"
        elif "相机" in name:
            kind = "fixture.camera"
        elif "横梁" in name:
            kind = "fixture.structure"
        elif "检测" in name:
            kind = "fixture.station"
        else:
            kind = "fixture"
        cid = ("cell." + TRAY_IDS[name]) if name in TRAY_IDS else (
            ("cell." + FIX_IDS[name]) if name in FIX_IDS else
            "cell." + (parent + "." + _slug(re.sub(r"^左槽|^下槽|^槽", "slot", name)) if parent
                       else _slug(name)))
        tags = []
        if kind == "slot":
            tags = ["抓取", "放置", "占位"]
        elif kind == "tray":
            tags = ["容器", "抓取面"]
        elif kind == "socket":
            tags = ["插入", "检测", "对位"]
        cells.append({
            "id": cid, "name": name, "kind": kind, "shape": "box",
            "pos_mm": pos, "size_mm": size, "parent": ("cell." + parent) if parent else None,
            "enabled": bool(it.get("enabled")), "tags": tags,
            "prov": {"src": "zmax_data/ar_rs/fences.json", "key": "items[%d]" % i,
                     "precision": "measured", "note": (it.get("note") or "")[:120]},
        })
        idx_boxes.append((name, lo, hi, cid))
    # 料盘自身也要有细胞(它们已在上面按 kind=tray 收进), 这里只补 槽→料盘 的父子关系检查
    return cells, idx_boxes


# ─────────────────────────── 2. 示教空间点 ───────────────────────────
def read_space_points():
    d = json.load(open(SRC_SPACE, encoding="utf-8"))
    pts = d.get("points") or {}
    out = []
    for name, v in pts.items():
        pos = v.get("pos")
        if not pos:
            continue
        out.append({
            "id": "cell.teach." + _slug(name), "name": name, "kind": "teach_point", "shape": "point",
            "pos_mm": [_mm(x) for x in pos], "size_mm": None, "parent": None,
            "quat": v.get("quat"), "abc_deg": v.get("abc"), "tags": ["示教", "可达点"],
            "prov": {"src": "data/skills/l2_atomic/space_points.json", "key": "points.%s" % name,
                     "precision": "measured_tcp", "measured_at": v.get("recorded_at"),
                     "note": (v.get("desc") or "")[:120],
                     "spread_pos_mm": round(float(v.get("spread_pos_m") or 0) * 1000, 4)},
        })
    return out, d.get("frame"), d.get("updated_at")


# ─────────────────────────── 3. AOI 站点 (AR 活数据) ───────────────────────────
def read_aoi():
    if not os.path.isfile(SRC_AOI):
        return [], None
    d = json.load(open(SRC_AOI, encoding="utf-8"))
    s = d.get("s") or {}
    out = []
    for k in s:
        if not k.endswith(".x"):
            continue
        base = k[:-2]
        try:
            pos = [_mm(s[base + ".x"]) if False else round(float(s[base + ".x"]), 2),
                   round(float(s[base + ".y"]), 2), round(float(s[base + ".z"]), 2)]
        except Exception:
            continue
        kind = "live_probe" if base in ("末端",) else "station"
        out.append({
            "id": "cell.aoi." + _slug(base), "name": base, "kind": kind, "shape": "point",
            "pos_mm": pos, "size_mm": None, "parent": None,
            "tags": [] if kind == "live_probe" else ["检测", "对位"],
            "prov": {"src": "zmax_data/ar_live/ar_aoi_live.json", "key": "s.%s" % base,
                     "precision": "measured", "note": "AR·空间点位(基座系), 单位已是 mm"},
        })
    return out, d.get("t") or d.get("ts") or d.get("updated_at")


# ─────────────────────────── 3b. 示教点位台账 (taught_points.json, 69 点) ───────────────────────────
_STATION_NAMES = {"金手指点1", "金手指点2", "侧面点0", "侧面点1", "侧面点2", "侧面点3",
                  "准备点", "安全点1", "正向观察位", "aoi_gold_view"}


def _taught_kind(k):
    if re.fullmatch(r"slot\d+", k):
        return "approach_pose", ["抓取", "号位"]
    if _STATION_NAMES.__contains__(k):
        return "station", ["检测", "观察位"]
    if k.startswith(("loop", "afx")):
        return "tuning_anchor", ["微调", "调试锚点"]
    return "motion_anchor", ["动作锚点"]


def read_taught():
    if not os.path.isfile(SRC_TAUGHT):
        return [], None
    d = json.load(open(SRC_TAUGHT, encoding="utf-8"))
    pts = d.get("points") or {}
    out = []
    for name, v in pts.items():
        pos = v.get("pos") if isinstance(v, dict) else v
        if not pos:
            continue
        kind, tags = _taught_kind(name)
        m = re.fullmatch(r"slot(\d+)", name)
        parent = "cell.tray.right" if (m or name.startswith("gp1_s")) else None
        c = {
            "id": "cell.taught." + _slug(name),
            "name": name, "kind": kind, "shape": "point",
            "pos_mm": [_mm(x) for x in pos], "size_mm": None, "parent": parent,
            "quat": (v.get("quat") if isinstance(v, dict) else None),
            "abc_deg": (v.get("abc") if isinstance(v, dict) else None),
            "tags": tags,
            "prov": {"src": "data/skills/l2_atomic/taught_points.json", "key": "points.%s" % name,
                     "precision": "measured_tcp",
                     "measured_at": (v.get("recorded_at") if isinstance(v, dict) else None) or d.get("updated_at"),
                     "note": "示教点位台账(真机 TCP 实录, base_link, 米→mm)"},
        }
        if m:
            c["slot_ref"] = "cell.tray.right.slot" + m.group(1)   # 号位N ↔ 槽N(几何中心) 的对应
        out.append(c)
    return out, d.get("updated_at")


# ─────────────────────────── 4. 结构件 (页面常量, 正则抽取) ───────────────────────────
def _const(src, name):
    m = re.search(r"var\s+%s\s*=\s*\{([^}]*)\}" % name, src)
    if not m:
        return None
    kv = {}
    for part in m.group(1).split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k, v = k.strip(), v.strip()
        try:
            kv[k] = float(v)
        except ValueError:
            continue
    return kv


def read_page_constants():
    src = open(SRC_PAGE, encoding="utf-8").read()
    cells = []
    chs, tab, tcam = _const(src, "CHS"), _const(src, "TAB"), _const(src, "TCAM")
    flr = re.search(r"var\s+FLR\s*=\s*\{([^}]*)\}", src)

    if chs:
        L, W, H, cy = chs.get("L"), chs.get("W"), chs.get("H"), chs.get("cy", 0.0)
        cells.append({
            "id": "cell.structure.chassis", "name": "移动底盘箱体(两臂安装座)", "kind": "structure",
            "shape": "box", "pos_mm": [0.0, _mm(cy), _mm(-H / 2.0)],
            "size_mm": [_mm(L), _mm(W), _mm(H)], "parent": None,
            "tags": ["底座", "臂安装面"], "frame_local": "top=z0=臂安装面",
            "prov": {"src": "tools/web/tcp-ar.html", "key": "var CHS",
                     "precision": "design", "note": "顶板=两臂安装面=桌面 z=0; 本体%s+轮露出%s mm" % (
                         _mm(chs.get("HB", 0)), _mm(H - chs.get("HB", 0)))},
        })
    if tab:
        x0, x1, cy, w, t = tab.get("x0"), tab.get("x1"), tab.get("cy"), tab.get("w"), tab.get("t")
        cells.append({
            "id": "cell.structure.table", "name": "实验桌(工作台)", "kind": "structure", "shape": "box",
            "pos_mm": [_mm((x0 + x1) / 2.0), _mm(cy), _mm(-t / 2.0)],
            "size_mm": [_mm(x1 - x0), _mm(w), _mm(t)], "parent": None,
            "tags": ["工位", "工作台"],
            "prov": {"src": "tools/web/tcp-ar.html", "key": "var TAB", "precision": "design",
                     "note": "桌面 1600(y)×600(x)×30 · 4 腿 45×45 到地面 · 桌沿离箱体前脸 50mm"},
        })
    if flr:
        m = re.search(r"x:\[([-\d.]+),([-\d.]+)\],\s*y:\[([-\d.]+),([-\d.]+)\],\s*z:([-\d.]+)", flr.group(1))
        if m:
            x0, x1, y0, y1, z = [float(g) for g in m.groups()]
            cells.append({
                "id": "cell.structure.floor", "name": "地面层(轮底/桌腿落地)", "kind": "structure",
                "shape": "plane", "pos_mm": [0.0, 0.0, _mm(z)],
                "size_mm": [_mm(x1 - x0), _mm(y1 - y0), 0.0], "parent": None,
                "extent_mm": {"x": [_mm(x0), _mm(x1)], "y": [_mm(y0), _mm(y1)]},
                "tags": ["地面", "碰撞下界"],
                "prov": {"src": "tools/web/tcp-ar.html", "key": "var FLR", "precision": "design",
                         "note": "与 base 工作平面 z=0 差 750mm"},
            })
    if tcam:
        m = re.search(r"return\s+(0\.\d+);\s*\n\}", src[src.find("function axis1H"):src.find("function axis1H") + 400])
        axis1 = float(m.group(1)) if m else None      # 立柱高 = 1 轴高度(URDF joint_1 z)
        cells.append({
            "id": "cell.sensor.top_cam", "name": "顶视相机(两臂之间立柱+RealSense)", "kind": "sensor",
            "shape": "cylinder", "pos_mm": [0.0, _mm(tcam.get("y", 0)),
                                            round(axis1 * 1000, 1) if axis1 else None],
            "size_mm": [_mm(2 * tcam.get("r", 0)), None, round(axis1 * 1000, 1) if axis1 else None],
            "parent": None,
            "tilt_deg": tcam.get("tilt"), "fov_deg": [tcam.get("fovH"), tcam.get("fovV")],
            "tags": ["第三视角", "具身相机"],
            "prov": {"src": "tools/web/tcp-ar.html", "key": "var TCAM + axis1H()", "precision": "design",
                     "note": "柱心 x=0(两臂之间), y=%.3f m; 柱高=1轴高度 %.3f m(URDF joint_1); 相机俯角%s°" % (
                         tcam.get("y", 0), axis1 or 0, tcam.get("tilt"))},
        })
    return cells


# ─────────────────────────── 5. 仿真场景(只对拍) ───────────────────────────
def read_mujoco():
    if not os.path.isfile(SRC_XML):
        return {}
    src = open(SRC_XML, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'<geom\s+name="([^"]+)"\s+type="(\w+)"\s+pos="([^"]+)"\s+size="([^"]+)"', src):
        name, typ, pos, size = m.groups()
        p = [_mm(v) for v in pos.split()]
        out[name] = {"type": typ, "pos_mm": p, "size_mm": [_mm(v) for v in size.split()]}
    for m in re.finditer(r'<body\s+name="([^"]+)"\s+pos="([^"]+)"', src):
        name, pos = m.groups()
        out.setdefault(name, {})["pos_mm"] = [_mm(v) for v in pos.split()]
    return out


# ─────────────────────────── 组装 + 邻接 + 对拍 ───────────────────────────
def build():
    fence_cells, idx = read_fences()
    sp_cells, sp_frame, sp_at = read_space_points()
    aoi_cells, aoi_at = read_aoi()
    taught_cells, taught_at = read_taught()
    page_cells = read_page_constants()
    mj = read_mujoco()

    cells = fence_cells + sp_cells + aoi_cells + taught_cells + page_cells
    by_id = {c["id"]: c for c in cells}
    dup = sorted({c["id"] for c in cells if sum(1 for x in cells if x["id"] == c["id"]) > 1})
    assert not dup, "位置细胞 id 撞车(会静默覆盖, 必须一物一 id): %s" % dup[:6]

    # 邻接: 同盘相邻槽(按 Y 序) + 每个槽到插孔的距离 —— 位置细胞之间的「联系强度」
    trays = [c for c in cells if c["kind"] == "tray"]
    slots = [c for c in cells if c["kind"] == "slot"]
    socket = next((c for c in cells if c["kind"] == "socket"), None)
    adj = {}
    for parent in [t["id"] for t in trays]:
        group = sorted([s for s in slots if s.get("parent") == parent], key=lambda s: -s["pos_mm"][1])
        for i, s in enumerate(group):
            n = {}
            for j in (i - 1, i + 1):
                if 0 <= j < len(group):
                    d = sum((a - b) ** 2 for a, b in zip(s["pos_mm"], group[j]["pos_mm"])) ** 0.5
                    n[group[j]["id"]] = {"d_mm": round(d, 1), "rel": "同盘邻槽"}
            if socket and socket["pos_mm"][0] is not None:
                d = sum((a - b) ** 2 for a, b in zip(s["pos_mm"], socket["pos_mm"])) ** 0.5
                n[socket["id"]] = {"d_mm": round(d, 1), "rel": "插孔"}
            adj[s["id"]] = n

    # 对拍 1: 插孔 fence 包络 vs 页面插拔箭头端点(767→814 · y228 · z278)
    checks = []
    if socket:
        arrow = re.findall(r"a:\[(0\.\d+),(0\.\d+),(0\.\d+)\],\s*b:\[(0\.\d+),(0\.\d+),(0\.\d+)\]",
                           open(SRC_PAGE, encoding="utf-8").read())
        apts = set()
        for a in arrow:                                    # 箭头两端都收(口 767 / 到位 814)
            apts.add(tuple(round(float(v) * 1000, 1) for v in a[:3]))
            apts.add(tuple(round(float(v) * 1000, 1) for v in a[3:]))
        mouth = exists = None
        for p in apts:
            if abs(p[1] - socket["pos_mm"][1]) < 2 and abs(p[2] - socket["pos_mm"][2]) < 2:
                if mouth is None or p[0] < mouth[0]:
                    mouth = p
                if exists is None or p[0] > exists[0]:
                    exists = p
        if mouth and exists:
            lo_x = socket["pos_mm"][0] - socket["size_mm"][0] / 2
            hi_x = socket["pos_mm"][0] + socket["size_mm"][0] / 2
            ok = abs(lo_x - mouth[0]) <= 2 and abs(hi_x - exists[0]) <= 2
            checks.append({"id": "socket.fence_vs_page_arrow", "ok": ok,
                           "detail": "fence x[%.1f,%.1f] vs 页面口%.0f/到位%.0f mm" % (lo_x, hi_x, mouth[0], exists[0])})
    # 对拍 2: 槽 是否落在其料盘盒内
    bad = []
    for s in slots:
        t = by_id.get(s.get("parent") or "")
        if not t:
            bad.append(s["id"])
            continue
        for k in range(3):
            half = t["size_mm"][k] / 2.0
            if abs(s["pos_mm"][k] - t["pos_mm"][k]) > half + 1:
                bad.append("%s(轴%d 偏离%.1fmm)" % (s["id"], k, abs(s["pos_mm"][k] - t["pos_mm"][k]) - half))
                break
    checks.append({"id": "slot.inside_parent_tray", "ok": not bad, "detail": "; ".join(bad[:4]) or "42 槽全在所属料盘盒内(±0mm 容差 1mm)"})

    # 对拍 3: 仿真 gold_module 落在哪个实际细胞里 —— 像素级判据(L2 真机取景)靠这条
    gm = (mj.get("gold_module") or {}).get("pos_mm")
    if gm:
        hit = None
        for c in slots:
            half = [c["size_mm"][k] / 2.0 for k in range(3)]
            if all(abs(gm[k] - c["pos_mm"][k]) <= half[k] + 30 for k in range(3)):
                hit = c["name"]
                break
        checks.append({"id": "sim.gold_module_in_scene", "ok": hit is not None,
                       "detail": "仿真模块 %s mm → %s(±30mm 判定)" % (gm, hit or "无细胞覆盖(槽/盘间空隙)")})

    # 对拍 4: 仿真 vs 真实 的结构件(只报差异, 不算错 —— 仿真简化了轮子/桌子)
    chs = by_id.get("cell.structure.chassis")
    mjc = mj.get("chassis")
    if chs and mjc:
        dz = abs(chs["pos_mm"][2] - mjc["pos_mm"][2])
        checks.append({"id": "sim.chassis_vs_page", "ok": True,
                       "detail": "页面中心z=%.1f(高%.0f) vs 仿真中心z=%.1f(高%.0f) —— 仿真无轮, 顶面 -12mm 板; 差%.0fmm 属已知简化" % (
                           chs["pos_mm"][2], chs["size_mm"][2], mjc["pos_mm"][2], mjc["size_mm"][2] * 2, dz)})

    # 对拍 5: 号位N(抓取位姿) ↔ 槽N(几何中心) 的偏移是否一致 —— 一致性=示教可信, 散=有人手抖/槽位错
    offs = []
    for n in range(1, 8):
        pose = next((c for c in taught_cells if c["name"] == "slot%d" % n), None)
        geo = by_id.get("cell.tray.right.slot%d" % n)
        if not pose or not geo:
            continue
        offs.append([round(pose["pos_mm"][k] - geo["pos_mm"][k], 1) for k in range(3)])
    if len(offs) >= 3:
        mean = [round(sum(o[k] for o in offs) / len(offs), 1) for k in range(3)]
        dev = max(max(abs(o[k] - mean[k]) for k in range(3)) for o in offs)
        checks.append({"id": "taught.slot_approach_offset", "ok": dev <= 20,
                       "detail": "号位-槽 偏移均值%s mm · %d 个号位最大偏离 %.1fmm(≤20 判一致)" % (
                           mean, len(offs), dev)})

    # 对拍 6: 示教 插入口/插入点 vs 围栏 插孔包络
    if socket:
        lo_x = socket["pos_mm"][0] - socket["size_mm"][0] / 2
        hi_x = socket["pos_mm"][0] + socket["size_mm"][0] / 2
        mo = next((c for c in taught_cells if c["name"] == "光模块插入口"), None)
        en = next((c for c in taught_cells if c["name"] in ("光模块插入点", "插入到位_1020c")), None)
        if mo and en:
            ok = abs(mo["pos_mm"][0] - lo_x) <= 2 and abs(en["pos_mm"][0] - hi_x) <= 3
            checks.append({"id": "socket.taught_vs_fence", "ok": ok,
                           "detail": "围栏 x[%.1f,%.1f] vs 示教 口%.1f/到位%.1f mm" % (
                               lo_x, hi_x, mo["pos_mm"][0], en["pos_mm"][0])})

    counts = {}
    for c in cells:
        counts[c["kind"]] = counts.get(c["kind"], 0) + 1

    # 缺口清单(工程诚实项): 配置里"没有坐标"的东西必须显式列出来, 否则等于假装齐全
    gaps = []
    taught_names = {c["name"] for c in taught_cells}
    no_grasp = [c["name"] for c in slots if c.get("parent") == "cell.tray.right"
                and "slot" + c["name"].replace("槽", "") not in taught_names]
    if no_grasp:
        gaps.append({"id": "grasp_pose_missing", "n": len(no_grasp),
                     "detail": "无示教抓取位姿(号位)的槽: %s" % ",".join(no_grasp[:6]),
                     "impact": "这些槽 L3 不能自动抓, 只能几何对准后手示教"})
    trays_no_pose = sorted({s.get("parent") for s in slots} - {"cell.tray.right"})
    if trays_no_pose:
        gaps.append({"id": "tray_grasp_pose_missing", "n": len(trays_no_pose),
                     "detail": "左盘/下盘/废料盘无任何号位示教: %s" % ",".join(trays_no_pose),
                     "impact": "摆盘/下料只能用几何中心 + 现算姿态, 不是示教真值"})
    gaps.append({"id": "aoi_live_partial_xyz", "n": 10,
                 "detail": "ar_aoi_live.json 里 10 个点名只有 .x(金手指点1/2·侧面点0~3·准备点·安全点1·空间点1/7), 缺 y/z",
                 "impact": "AR 页这几个点按台账(taught_points)画, 不走 live 值; 若要实时位置必须补全写入端"})
    gaps.append({"id": "page_constants_not_measured", "n": 3,
                 "detail": "箱体/实验桌/地面 三件只有设计尺寸(页面常量), 无实测",
                 "impact": "碰撞判定可用; 若要 mm 级工位标定需一次实测"})
    doc_gaps = gaps

    doc = {
        "schema": "zmax.scene_places/1",
        "frame": "base_link",
        "unit": "mm",
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "build_tool": "tools/scene_places_build.py",
        "note": "工程参数中心: 场景 3D 元素精确坐标(位置细胞)。本文件由构建器从测量真源汇总, 禁止手改; "
                "页面(tcp-ar.html)与 L2 记忆库共用这一套 id。",
        "sources": [
            {"file": "zmax_data/ar_rs/fences.json", "md5": md5(SRC_FENCES), "n": len(json.load(open(SRC_FENCES))["items"])},
            {"file": "data/skills/l2_atomic/space_points.json", "md5": md5(SRC_SPACE),
             "n": len(json.load(open(SRC_SPACE)).get("points") or {}), "frame": sp_frame, "updated_at": sp_at},
            {"file": "zmax_data/ar_live/ar_aoi_live.json", "md5": md5(SRC_AOI) if os.path.isfile(SRC_AOI) else None,
             "n": len(aoi_cells), "updated_at": aoi_at,
             "note": "该文件只有「末端」给全 xyz, 其余点名只有 .x —— 现场口径缺口, 位置以 taught_points 为准"},
            {"file": "data/skills/l2_atomic/taught_points.json", "md5": md5(SRC_TAUGHT),
             "n": len(taught_cells), "updated_at": taught_at, "frame": "base_link",
             "note": "示教点位台账 69 点: 号位1~7 / 金手指点 / 侧面点 / 插入口·插入点 / 微调环"},
            {"file": "tools/web/tcp-ar.html", "md5": md5(SRC_PAGE), "n": len(page_cells),
             "note": "只抽结构件常量 CHS/TAB/FLR/TCAM, 页面不是坐标真源 —— 抽出后页面与 L2 用同一套数字"},
            {"file": "zmax_data/ar_mujoco/ar_env.xml", "md5": md5(SRC_XML) if os.path.isfile(SRC_XML) else None,
             "n": len(mj), "note": "仿真对拍用, 不当真值"},
        ],
        "counts": counts,
        "total": len(cells),
        "cells": cells,
        "adjacency": adj,
        "checks": checks,
        "gaps": doc_gaps,
    }
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只自检, 不写库")
    ap.add_argument("--json", action="store_true", help="只打印摘要 JSON")
    a = ap.parse_args()
    doc = build()

    if a.json:
        print(json.dumps({"counts": doc["counts"], "total": doc["total"],
                          "checks": doc["checks"]}, ensure_ascii=False, indent=1))
        return 0 if all(c["ok"] for c in doc["checks"]) else 1

    print("场景位置细胞: 共 %d 枚 = %s" % (doc["total"],
          " · ".join("%s %d" % (k, v) for k, v in sorted(doc["counts"].items(), key=lambda kv: -kv[1]))))
    for c in doc["checks"]:
        print(("  %s %-28s %s" % ("✅" if c["ok"] else "❌", c["id"], c["detail"])))
    if a.check:
        if os.path.isfile(OUT):
            old = json.load(open(OUT, encoding="utf-8"))
            drift = [x["id"] for x in old["cells"]] != [x["id"]] if False else None
            same = [c["id"] for c in old["cells"]] == [c["id"] for c in doc["cells"]]
            moved = []
            om = {c["id"]: c for c in old["cells"]}
            for c in doc["cells"]:
                o = om.get(c["id"])
                if o and o.get("pos_mm") != c.get("pos_mm"):
                    moved.append("%s %s→%s" % (c["id"], o.get("pos_mm"), c.get("pos_mm")))
            print("库内对比: id 集%s · 移动 %d 枚%s" % ("一致" if same else "有变", len(moved),
                  ("" if not moved else " :: " + "; ".join(moved[:5]))))
        else:
            print("库内对比: 尚无 %s" % os.path.relpath(OUT, REPO))
        return 0 if all(c["ok"] for c in doc["checks"]) else 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    json.dump(doc, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print("已写 %s (%.1f KB)" % (os.path.relpath(OUT, REPO), os.path.getsize(OUT) / 1024.0))
    return 0 if all(c["ok"] for c in doc["checks"]) else 1


if __name__ == "__main__":
    sys.exit(main())
