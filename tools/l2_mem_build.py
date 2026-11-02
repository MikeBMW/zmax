#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 / 刷新 L2 记忆库 (data/memory/l2_store) —— 全部条目回真源现算, 不手抄数字。

真源:
  技能·原子     data/skills/l2_atomic/registry.json      (99 条原语 + 3 组合)
  技能·示教     data/skills/l2_muscle/*.json             (5 个: 抓放循环/抓取/演示学习/重学/AOI侧扫)
  固定点位      data/datasets/points/*.json              (现场示教 tcp pos/quat + 夹爪/运动配方)
  工艺卡        data/database/zmax/sources/config/orders/BS_*.json  (Build Sheet, 工艺编排)
  工艺编排     卡片 process/recipe + 段表口径            (段序列 + 计划/实测时长)
  标杆          data/muscle_memory.json + src/data/muscle_memory.json (取并集, 同桶留 n_ok 大的)
  实测台账      data/memory/ar_muscle.json               (n / mean_t / plan_t)

用法:
  ./gui-venv311/bin/python tools/l2_mem_build.py            # 重建 + 同步旧库
  ./gui-venv311/bin/python tools/l2_mem_build.py --dry      # 只统计不落盘
  ./gui-venv311/bin/python tools/l2_mem_build.py --no-legacy-sync
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.memory import l2_store as S            # noqa: E402


def _j(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                             # noqa: BLE001
        return default


def _sha(p):
    try:
        return S._sha_file(p)
    except Exception:                                             # noqa: BLE001
        return ""


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _rel(p):
    return os.path.relpath(p, ROOT)


# ─────────────────────────────────────────── 1. 技能: 原子 + 组合
def collect_atomic(skills):
    p = os.path.join(ROOT, "data/skills/l2_atomic/registry.json")
    d = _j(p, {}) or {}
    for s in d.get("skills") or []:
        params = []
        for pn, pv in (s.get("param") or {}).items():
            params.append({"name": pn, "default": pv.get("default"), "unit": pv.get("unit"),
                           "min": pv.get("min"), "max": pv.get("max"), "label": pv.get("label")})
        skills[s["id"]] = {
            "id": s["id"], "name": s.get("name") or s["id"], "icon": s.get("icon", ""),
            "kind": "atomic", "layer": "L2", "ros": s.get("ros"), "axis": s.get("axis"),
            "params": params, "returns": {"ok": "bool", "moved": "mm"},
            "pre": ["idle", "automatic"], "verify": {"判据": "到位误差 ≤ 1mm · 无碰撞"},
            "steps": [], "tags": ["原子", "常驻"], "src": _rel(p), "sha": _sha(p), "at": _now(),
            "desc": s.get("desc") or "",
        }
    for c in d.get("composite") or []:
        steps_file = c.get("steps_file") or ""
        skills[c["id"]] = {
            "id": c["id"], "name": c.get("name") or c["id"], "kind": "composite", "layer": "L2",
            "ros": "(组合)", "axis": "", "params": [], "returns": {"ok": "bool"},
            "pre": ["idle"], "verify": {"判据": "逐步到位"},
            "steps": [{"op": "skill_file", "path": steps_file}], "tags": ["组合"],
            "src": _rel(p), "sha": _sha(p), "at": _now(), "desc": "组合技能: 步骤文件 %s" % steps_file,
        }
    return len(d.get("skills") or []), len(d.get("composite") or [])


# ─────────────────────────────────────────── 2. 技能: 示教/循环 + 其点位
KIND_BY_ID = {"AOI": "aoi", "DEMO": "demo", "CYCLE": "cycle", "PICK": "pick", "RELEARN": "demo"}


def collect_muscle(skills, points):
    n = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "data/skills/l2_muscle/*.json"))):
        d = _j(p, {}) or {}
        sid = d.get("id") or os.path.basename(p).replace(".json", "")
        kind = "cycle"
        for k, v in KIND_BY_ID.items():
            if k in sid.upper():
                kind = v
                break
        pts = []
        for pn, pv in (d.get("points") or {}).items():
            rec = {"pos": pv.get("pos"), "quat": pv.get("quat"), "desc": pv.get("desc", ""),
                   "src": _rel(p), "sha": _sha(p), "at": pv.get("recorded_at") or _now(),
                   "skill": sid}
            key = "%s@%s" % (pn, sid)
            points[key] = rec
            if pn not in points:                      # 裸名也放一份 (最常见查询)
                points[pn] = dict(rec, alias_of=key)
            pts.append({"name": pn, "pos": pv.get("pos"), "quat": pv.get("quat")})
        steps = []
        for st in (d.get("steps") or []):
            steps.append({k: st[k] for k in st if k in ("op", "to", "ros", "args", "note", "skill",
                                                        "quat", "transition", "speed")})
        skills[sid] = {
            "id": sid, "name": d.get("name") or sid, "kind": kind, "layer": "L2",
            "version": d.get("version") or 1, "group": d.get("group", ""),
            "ros": "l2_ros2_bridge (ROS2 → Orin)", "axis": "",
            "params": [{"name": k, "default": v} for k, v in (d.get("params") or {}).items()],
            "returns": {"ok": "bool", "frames": "int"},
            "pre": (d.get("guard") or []), "verify": d.get("verify") or {},
            "steps": steps, "points": pts, "tags": [kind], "desc": d.get("source", ""),
            "src": _rel(p), "sha": _sha(p), "at": _now(),
        }
        n += 1
    return n


# ─────────────────────────────────────────── 3. 固定点位 (示教真值)
def collect_points(points):
    n = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "data/datasets/points/*.json"))):
        d = _j(p, {}) or {}
        for pn, pv in (d.get("points") or {}).items():
            if pn in points:
                continue
            points[pn] = {"pos": pv.get("tcp_position_m") or pv.get("pos"),
                          "quat": pv.get("tcp_quat_xyzw") or pv.get("quat"),
                          "desc": pv.get("desc", ""), "src": _rel(p), "sha": _sha(p),
                          "at": d.get("saved_at") or _now()}
            n += 1
        for rk in ("grasp_recipe", "motion_recipe"):
            if d.get(rk):
                points["__recipe__:" + rk] = {"pos": None, "quat": None, "recipe": d[rk],
                                              "src": _rel(p), "sha": _sha(p), "at": _now(),
                                              "desc": "工艺配方 (非点位)"}
    return n


# ─────────────────────────────────────────── 4. 工艺卡 + 工艺编排序列
def collect_cards(cards, seqs, ledger):
    n = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "data/database/zmax/sources/config/orders/BS_*.json"))):
        d = _j(p, {}) or {}
        ident = d.get("identity") or {}
        scene_id = ident.get("scene_id") or os.path.basename(p).replace("BS_", "").replace(".json", "")
        cid = ident.get("order_no") or scene_id          # 工单号唯一 (SCN-07-AOI 有 4 张工单)
        proc = d.get("process") or []
        steps = proc if isinstance(proc, list) else (proc.get("steps") or [])
        cards[cid] = {
            "id": cid, "scene_id": scene_id, "identity": ident,
            "order_no": ident.get("order_no"), "name": ident.get("name"),
            "scene_type": ident.get("scene_type"), "goal": ident.get("goal"),
            "station": ident.get("station"), "robot": ident.get("robot"),
            "process": proc, "steps": steps, "recipe": d.get("recipe") or {},
            "targets": d.get("targets") or {}, "safety": d.get("safety") or {},
            "poka_yoke": d.get("poka_yoke") or {}, "trace": d.get("trace") or {},
            "options": (d.get("options") or {}).get("selected") or [],
            "src": _rel(p), "sha": _sha(p), "at": _now(),
            "段数": len(steps),
        }
        # 工艺编排: 段序列 + 节拍口径 (计划 = 段表 plan_t, 实测 = 台账 mean_t)
        kinds = []
        for st in steps:
            kk = st.get("kind") or st.get("类型") or st.get("action") or ""
            if kk and kk not in kinds:
                kinds.append(kk)
        kinds = kinds or list((ledger or {}).keys())
        seqs[cid] = {
            "scene": scene_id, "order_no": cid, "order_no": ident.get("order_no"), "段数": len(steps),
            "段序列": [{"i": i + 1, "op": (st.get("op") or st.get("动作") or st.get("kind") or ""),
                        "目标": (st.get("to") or st.get("target") or ""),
                        "时长计划_s": st.get("t") or st.get("duration")}
                       for i, st in enumerate(steps)],
            "节拍口径": {k: {"plan_s": (ledger.get(k) or {}).get("plan_t"),
                             "实测_s": (ledger.get(k) or {}).get("mean_t"),
                             "n": (ledger.get(k) or {}).get("n")} for k in kinds},
            "src": _rel(p), "sha": _sha(p), "at": _now(),
        }
        n += 1
    return n


# ─────────────────────────────────────────── 5. 标杆 (并集) + 台账
def collect_champs():
    merged, used = {}, []
    for p in (os.path.join(ROOT, "data/muscle_memory.json"),
              os.path.join(ROOT, "src/data/muscle_memory.json")):
        d = _j(p, {}) or {}
        used.append({"file": _rel(p), "buckets": len(d), "sha": _sha(p)})
        for k, v in d.items():
            if not isinstance(v, dict) or not v.get("champ_u"):
                continue
            cur = merged.get(k)
            if cur is None or (v.get("n_ok") or 0) > (cur.get("n_ok") or 0):
                merged[k] = {"n_ok": v.get("n_ok"), "champ_u": v.get("champ_u"),
                             "champ_x": v.get("champ_x"), "io": v.get("io"),
                             # 2026-11-02 老倪「桶键要补工艺点维度」: 标杆帧实测是归一化/相对量
                             # (io.entry≈[0.005,0.601,0.195]), 不是 base_link 也不是 sim_base mm,
                             # 且不带点位名 ⇒ **无法**定位到槽/孔, 只能标 scene|stage。不许硬编点位。
                             "frame": "归一化(仿真/相对; 非 base_link, 非 sim_base mm)",
                             "points_ref": None,
                             "why_no_points": "标杆帧无点名义 + 非物理坐标 ⇒ 定位不到槽/孔; 工艺点级请查 traj REAL:* 与 corridors"}

    return merged, used
    return merged, used


def collect_ledger():
    p = os.path.join(ROOT, "data/memory/ar_muscle.json")
    d = _j(p, {}) or {}
    kinds = {}
    for k, v in (d.get("kinds") or {}).items():
        mt, pt = v.get("mean_t"), v.get("plan_t")
        kinds[k] = {"n": v.get("n"), "mean_t": mt, "plan_t": pt,
                    "ratio": round(mt / pt, 3) if (mt and pt) else None}
    return kinds, _rel(p), _sha(p)


# ─────────────────────────────────────────── 6. 理想轨迹库 (可调用)
def collect_trajs(champs, skills):
    """理想轨迹 = 三段来源, 统一成 {id, kind, skill, frames, dt, path/u, executable, src, sha}:

      sim_champ   仿真固化标杆的整段 u/x 序列 (可预览/可做前馈参考, 不是真机坐标 → executable=False)
      taught      现场示教技能的「点位序列」(真机 tcp pos+quat, executable=True)
      spline      示教 4 点做五次插值的稠密路径 (config/aoi/side_path.json, 75 点, executable=True)
      demo_file   手把手录制文件 (索引不复制: 路径+行数+sha, executable=True 按文件回放)
    """
    trajs = {}
    # (a) 仿真标杆
    for k, b in champs.items():
        seed, stage = (k.split("|") + ["", ""])[:2]
        trajs["SIM:%s|%s" % (seed, stage)] = {
            "id": "SIM:%s|%s" % (seed, stage), "kind": "sim_champ", "skill": "", "stage": stage,
            "frames": len(b.get("champ_u") or []), "dt": 0.05,
            "path": (b.get("champ_x") or [])[:400], "u": (b.get("champ_u") or [])[:400],
            "executable": False, "exec_note": "仿真归一化序列, 给人看/给前馈参考; 真机走示教或稠密路径",
            "n_ok": b.get("n_ok"), "src": "data/muscle_memory.json", "at": _now(),
        }
    # (b) 示教技能的点位序列
    for sid, s in skills.items():
        pts = s.get("points") or []
        if not pts:
            continue
        # 🔴 2026-11-02: 示教轨迹原来是 dt=None 的"裸点位" ⇒ 只能逐点 move_line, 节拍靠执行器猜。
        #   现回真源读每个点的 t_demo_s / dwell_s, 算出量内时序 (duration + 每段 dt),
        #   并保留点名 (home/slot/safe/align/grasp/up1...) —— 那是唯一能对上"工艺点"的字段。
        raw = _j(os.path.join(ROOT, s.get("src") or ""), {}) or {}
        rawp = raw.get("points") if isinstance(raw.get("points"), dict) else {}
        t_list, dt_list, timing = [], [], "none"
        names = [p.get("name") for p in pts]
        for i, p in enumerate(pts):
            rp = rawp.get(p.get("name")) or {}
            if rp.get("t_demo_s") is not None:
                t_list.append(float(rp["t_demo_s"]))
                timing = "t_demo_s"
            elif t_list:
                t_list.append(None)
        if timing == "t_demo_s":
            t_list = [t for t in t_list if t is not None]
            dt_list = [round(t_list[i + 1] - t_list[i], 3) for i in range(len(t_list) - 1)]
        else:
            for p in pts:
                rp = rawp.get(p.get("name")) or {}
                d = rp.get("dwell_s")
                if d is not None:
                    dt_list.append(round(float(d), 3))
                    timing = "dwell_s"
            if dt_list and sum(1 for x in dt_list if x > 60) > len(dt_list) / 2:
                dt_list, timing = [], "none"
        good = [x for x in dt_list if 0 < x <= 60]
        trajs["REAL:%s" % sid] = {
            "id": "REAL:%s" % sid, "kind": "taught", "skill": sid, "stage": "",
            "frames": len(pts), "dt": (sorted(good)[len(good) // 2] if good else None),
            "timed": bool(good), "timing_src": timing,
            "duration_s": (round(sum(good), 3) if good else None),
            "dt_list": dt_list, "t_s": (t_list if timing == "t_demo_s" else None),
            "point_names": names,
            "path": [{"name": p.get("name"), "pos": p.get("pos"), "quat": p.get("quat")} for p in pts],
            "u": [], "executable": True,
            "exec_note": ("点位序列 + 时序(%s): 按 dt 逐点 move_line, 可复现节拍" % timing if good else
                          "点位序列 (无时序): move_line 逐点下发, 节拍由执行器定 (真机示教真值)"),
            "src": s.get("src"), "sha": s.get("sha"), "at": _now(),
        }
    # (c) AOI 侧面稠密路径
    p = os.path.join(ROOT, "config/aoi/side_path.json")
    d = _j(p, {}) or {}
    if d.get("trajectory"):
        trajs["REAL:SCN-07-AOI|side_path"] = {
            "id": "REAL:SCN-07-AOI|side_path", "kind": "spline", "skill": "L2.MUSCLE.AOI_SIDE_SCAN",
            "stage": "", "frames": len(d["trajectory"]), "dt": 0.05,
            "path": d["trajectory"], "u": [], "executable": True,
            "exec_note": "五次插值稠密点 (%s), 逐帧 move_line" % (d.get("interp") or ""),
            "src": _rel(p), "sha": _sha(p), "at": _now(),
        }
    # (d) 手把手录制文件 (索引, 不复制)
    for f in ("zmax_data/demo_pose_193713.txt", "zmax_data/demo_grip_193713.txt"):
        fp = os.path.join(ROOT, f)
        if not os.path.exists(fp):
            continue
        n = sum(1 for _ in open(fp, "rb"))
        trajs["REAL:DEMO:%s" % os.path.basename(f).replace(".txt", "")] = {
            "id": "REAL:DEMO:%s" % os.path.basename(f).replace(".txt", ""), "kind": "demo_file",
            "skill": "L2.MUSCLE.DEMO_RELEARN", "stage": "", "frames": n, "dt": None,
            "path": [], "u": [], "executable": True,
            "exec_note": "录制文件索引 (%d 行, 按文件回放, 不复制进库)" % n,
            "src": _rel(fp), "sha": _sha(fp), "at": _now(),
        }
    return trajs


# ─────────────────────────────────────────── main
# ─────────────────────────────────────────── 8. 约束通道 (每个工艺点一条)
# 🔴 键的语义 = 「从哪个工艺点 → 到哪个工艺点 | 阶段」。
#   2026-11-02 实测: 阶段名不能决定点位 —— 对位/插入/完成 都发生在**孔**上 (对位=孔口上方 340→278),
#   接近/下降/抓取/抬起 在**槽**上 (240→218 / 218→118 / 抬 118→218), 转移 是 槽→孔。
#   早期按"阶段→固定点位"归组 ⇒ 抓取系 5 段全落进孔, end_err 62~222mm; 现按每条机动自己的起终点认点。


def collect_corridors():
    """🧊 约束通道库 —— 老倪 2026-11-02「固定轨迹/固定工艺 ⇒ 技能应预先有每个工艺点的通道数据」。

    真源: zmax_data/ss_live/skill_corridors.json (实跑机动折线) + config/points/cell_points.json (点位几何)。
    键 = 起点工艺点->终点工艺点|阶段 (工艺点认法: 水平距离 ≤25mm 就近槽位/孔口/孔底)。
    每段两级:
      real  该起终点组合有实跑机动 ⇒ axis=真实折线, L=均值, n_poly=次数
      geom  没有实跑 ⇒ axis=点位几何 + 本阶段同形段的中位 z 偏置 (标 geom, 不是实测)
    """
    import numpy as np
    cp = _j(os.path.join(ROOT, "config/points/cell_points.json")) or {}
    cpath = os.path.join(ROOT, "zmax_data/ss_live/skill_corridors.json")
    cj = _j(cpath) or {}
    sha = _sha(cpath)
    sp = {s["name"]: np.asarray(s["pos"], float) for s in (cp.get("slots") or [])}
    hp = {h["name"]: {"mouth": np.asarray(h["mouth"], float),
                      "insert": np.asarray(h["insert"], float)} for h in (cp.get("holes") or [])}
    if not sp or not hp or not cj.get("corridors"):
        return {}, {}

    def _near(p, cand, cap, xy=True):
        bn, bd = None, 1e18
        for n, q in cand.items():
            dd = np.asarray(q, float) - np.asarray(p, float)
            d = float(np.linalg.norm(dd[:2])) if xy else float(np.linalg.norm(dd))
            if d < bd:
                bn, bd = n, d
        return (bn if bd <= cap else None), bd

    def _lbl(pt):
        """认这是哪个工艺点: 槽X / 孔Y (含落在孔口还是孔底) / None。"""
        s_, d_ = _near(pt, sp, 25.0)
        if s_:
            return s_, "slot", sp[s_]
        for ref in ("mouth", "insert"):
            h_, hd = _near(pt, {n: v[ref] for n, v in hp.items()}, 25.0)
            if h_:
                return h_, "hole", hp[h_][ref]
        return None, None, None

    out, stats, shapes = {}, {}, {}
    for stage, c in (cj.get("corridors") or {}).items():
        r = float(c.get("r_mm") or 0.0)
        s_tick = float(c.get("s_tick_mm") or 0.0)
        v_al = float(c.get("v_along_cap") or 0.0)
        tact = c.get("tact_s")
        groups = {}
        for poly in (c.get("polys") or []):
            P = np.asarray(poly, float)
            if P.ndim != 2 or len(P) < 2:
                continue
            ls, ts, ps = _lbl(P[0])
            le, te, pe = _lbl(P[-1])
            if not ls or not le:
                continue
            key = "%s->%s|%s" % (ls, le, stage)
            g = groups.setdefault(key, {"n": 0, "L": 0.0, "best": None, "err": 1e18,
                                        "ls": ls, "le": le, "ts": ts, "te": te,
                                        "dzs": [], "dze": []})
            g["n"] += 1
            g["L"] += float(np.sum(np.linalg.norm(np.diff(P, axis=0), axis=1)))
            g["dzs"].append(float(P[0][2] - ps[2]))
            g["dze"].append(float(P[-1][2] - pe[2]))
            miss = float(np.linalg.norm((P[-1] - pe)[:2]))
            if miss < g["err"]:
                g["err"], g["best"] = miss, P
        for key, g in groups.items():
            out[key] = {"key": key, "stage": stage, "from": g["ls"], "to": g["le"],
                        "kind": "real", "zero_travel": bool(g["L"] / max(1, g["n"]) < 1.0),
                        "r_mm": r, "L_mm": round(g["L"] / max(1, g["n"]), 2), "n_poly": g["n"],
                        "s_tick_mm": s_tick, "v_along_cap": v_al, "tact_s": tact,
                        "axis": [[round(float(x), 2) for x in q] for q in g["best"]],
                        "end_err_mm": round(g["err"], 2),
                        "src": _rel(cpath), "sha": sha, "at": _now()}
            sh = (g["ts"], g["te"])
            shapes.setdefault((stage, sh), {"dzs": [], "dze": [], "r_mm": r,
                                            "s_tick_mm": s_tick, "v_along_cap": v_al, "tact_s": tact,
                                            "n": 0})
            sh_ = shapes[(stage, sh)]
            sh_["dzs"] += g["dzs"]
            sh_["dze"] += g["dze"]
            sh_["n"] += g["n"]
        stats[stage] = True

    # 几何补: 按本阶段出现过的"形状"(槽→槽 / 槽→孔 / 孔→孔) 铺满所有工艺点组合
    n_geom = 0
    for (stage, (ts, te)), sh in shapes.items():
        dzs = float(np.median(sh["dzs"])) if sh["dzs"] else 0.0
        dze = float(np.median(sh["dze"])) if sh["dze"] else 0.0
        if ts == "slot" and te == "slot":
            combos = [(a, a) for a in sp]
        elif ts == "slot" and te == "hole":
            combos = [(a, b) for a in sp for b in hp]
        else:
            combos = [(b, b) for b in hp]
        for ls, le in combos:
            key = "%s->%s|%s" % (ls, le, stage)
            if key in out:
                continue
            ps = sp[ls]
            pe = hp[le]["insert"] if stage == "完成" else (hp[le]["mouth"] if te == "hole" else sp[le])
            a = np.array([ps[0], ps[1], ps[2] + dzs], float)
            b = np.array([pe[0], pe[1], pe[2] + dze], float)
            L = float(np.linalg.norm(b - a))
            out[key] = {"key": key, "stage": stage, "from": ls, "to": le, "kind": "geom",
                        "zero_travel": bool(L < 1.0),
                        "r_mm": sh["r_mm"], "L_mm": round(L, 2), "n_poly": 0,
                        "s_tick_mm": sh["s_tick_mm"], "v_along_cap": sh["v_along_cap"],
                        "tact_s": sh["tact_s"],
                        "axis": [[round(float(x), 2) for x in a], [round(float(x), 2) for x in b]],
                        "end_err_mm": None,
                        "src": "config/points/cell_points.json + %s" % _rel(cpath),
                        "sha": sha, "at": _now()}
            n_geom += 1
    return out, {"stages": len(stats), "real": len(out) - n_geom, "geom": n_geom}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-legacy-sync", action="store_true")
    a = ap.parse_args()

    skills, points, cards, seqs = {}, {}, {}, {}
    n_at, n_cp = collect_atomic(skills)
    n_mu = collect_muscle(skills, points)
    n_pt = collect_points(points)
    champs, champ_src = collect_champs()
    ledger, ledger_src, ledger_sha = collect_ledger()
    n_cd = collect_cards(cards, seqs, ledger)
    trajs = collect_trajs(champs, skills)
    corrs, corr_meta = collect_corridors()

    print("技能 %d 条 (原子 %d + 组合 %d + 示教 %d)" % (len(skills), n_at, n_cp, n_mu))
    print("点位 %d 个 (示教库 %d)" % (len(points), n_pt))
    print("工艺卡 %d 张 · 编排序列 %d 份" % (len(cards), len(seqs)))
    print("标杆 %d 桶 (并集: %s)" % (len(champs), ", ".join("%s=%d" % (x["file"], x["buckets"]) for x in champ_src)))
    n_exec = sum(1 for v in trajs.values() if v.get("executable"))
    print("理想轨迹 %d 条 (真机可下发 %d · 仿真标杆 %d)" % (len(trajs), n_exec, len(trajs) - n_exec))
    print("约束通道 %d 条 (实跑 %d + 几何推导 %d · %d 阶段 · 键=起点->终点|阶段)"
          % (len(corrs), corr_meta.get("real", 0), corr_meta.get("geom", 0), corr_meta.get("stages", 0)))
    print("台账 %d 类 · 最差 ratio %.2f" % (len(ledger),
                                        max([v["ratio"] for v in ledger.values() if v["ratio"]] or [0])))
    if a.dry:
        return 0

    # 备份旧库 (留最近 3 份)
    if os.path.isdir(S.STORE) and os.listdir(S.STORE):
        bak = S.STORE + ".bak." + time.strftime("%Y%m%d_%H%M%S")
        shutil.copytree(S.STORE, bak)
        olds = sorted(glob.glob(S.STORE + ".bak.*"))
        for o in olds[:-3]:
            shutil.rmtree(o, ignore_errors=True)
        print("旧库备份 →", os.path.basename(bak))

    S.put_skills(list(skills.values()), writer="n_l2_muscle", mode="replace")
    S.put_points(points, writer="ss_mem_l2", mode="replace")
    S.put_cards(cards, writer="ss_mem_l2", mode="replace")
    S.put_seqs(seqs, writer="ss_mem_l2", mode="replace")
    S.put_champs(champs, writer="ss_mem_l2")
    S.put_ledger(ledger, writer="ss_mem_l2", src=ledger_src)
    S.put_trajs(trajs, writer="ss_mem_l2")
    S.put_corridors(corrs, writer="ss_mem_l2")
    idx = S.index()
    print("落库 → %s  计数 %s" % (_rel(S.STORE), idx.get("counts")))
    print("指纹 %s" % json.dumps({k: v["sha"] for k, v in idx["banks"].items()}, ensure_ascii=False))

    # 收敛标杆分叉: 三份 → 一份 (canonical = champs.json), 旧两份改写为并集
    if not a.no_legacy_sync:
        for p in (os.path.join(ROOT, "data/muscle_memory.json"),
                  os.path.join(ROOT, "src/data/muscle_memory.json")):
            old = _j(p, {}) or {}
            if len(old) > len(champs):
                print("⚠️ %s 比并集多 (%d > %d) —— 不覆盖, 请人工确认" % (_rel(p), len(old), len(champs)))
                continue
            with open(p + ".bak", "w", encoding="utf-8") as f:
                json.dump(old, f, ensure_ascii=False)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(champs, f, ensure_ascii=False)
            print("标杆同步 → %s (%d 桶, 旧版 %d 留存 %s.bak)" % (_rel(p), len(champs), len(old), _rel(p)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
