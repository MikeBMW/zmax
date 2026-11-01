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
                             "champ_x": v.get("champ_x"), "io": v.get("io")}
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
        trajs["REAL:%s" % sid] = {
            "id": "REAL:%s" % sid, "kind": "taught", "skill": sid, "stage": "",
            "frames": len(pts), "dt": None,
            "path": [{"name": p.get("name"), "pos": p.get("pos"), "quat": p.get("quat")} for p in pts],
            "u": [], "executable": True, "exec_note": "点位序列: move_line 逐点下发 (真机示教真值)",
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

    print("技能 %d 条 (原子 %d + 组合 %d + 示教 %d)" % (len(skills), n_at, n_cp, n_mu))
    print("点位 %d 个 (示教库 %d)" % (len(points), n_pt))
    print("工艺卡 %d 张 · 编排序列 %d 份" % (len(cards), len(seqs)))
    print("标杆 %d 桶 (并集: %s)" % (len(champs), ", ".join("%s=%d" % (x["file"], x["buckets"]) for x in champ_src)))
    n_exec = sum(1 for v in trajs.values() if v.get("executable"))
    print("理想轨迹 %d 条 (真机可下发 %d · 仿真标杆 %d)" % (len(trajs), n_exec, len(trajs) - n_exec))
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
