#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_aoi_side_scan_skill.py — 沉淀『AOI 侧面巡检』组合技能 (2026-10-13)

老倪 2026-10-13: 「我开示教 AOI 侧面点位 更新 侧面点0..3 … 你要学习路径，同时建图。
                  记录完点位后，你来插值规划平滑过渡轨迹 … 同步保存项目工程配置数据」
              + 「迭代后保存数据，技能，共享记忆」

本脚本把本轮示教固化成 L2 技能(可复用、可回溯):
  · 肌肉技能 data/skills/l2_muscle/L2_MUSCLE_AOI_SIDE_SCAN.json
      - points: 侧面点0..3 (pos+quat 逐位取自 AOI 台账 reports/aoi_points/*.json, 不手抄)
      - steps: goto 0→1→2→3, 每步带平滑过渡轨迹引用 (config/aoi/side_path.json + 它的 sha256)
      - envelope: 逐段长度/峰值速度/平滑性 (直接搬 side_path.json, 不重算)
  · 组合技能登记进 data/skills/l2_atomic/registry.json 的 composite (幂等, 只加法)
  · 每次变更追加 data/skills/CHANGELOG.jsonl

铁律(register_surface_pt*.py 同规格):
  · 点位真值只在台账/技能库, 本脚本**不内嵌坐标**(引用 point 名 + 校验 sha256 同源)
  · 回点类运动必须 ros=line_abs + quat="taught" (位置和姿态都回示教点)
  · 不新开第二套写者: 本脚本只读台账, 写技能库/registry

用法: gui-venv311/bin/python tools/register_aoi_side_scan_skill.py [--dry]
"""
import argparse
import hashlib
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSDIR = os.path.join(ROOT, "data/skills/l2_muscle")
REG = os.path.join(ROOT, "data/skills/l2_atomic/registry.json")
LOG = os.path.join(ROOT, "data/skills/CHANGELOG.jsonl")
SIDE = os.path.join(ROOT, "config/aoi/side_path.json")
TPOINTS = os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json")
SID = "L2.MUSCLE.AOI_SIDE_SCAN"
PTS = ["侧面点0", "侧面点1", "侧面点2", "侧面点3"]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def logev(kind, extra=None):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    ev = {"t": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "skill": SID}
    ev.update(extra or {})
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    side = json.load(open(SIDE, encoding="utf-8"))
    tp = json.load(open(TPOINTS, encoding="utf-8"))
    tp = tp.get("points") or tp
    problems = []
    points_out = {}
    for i, nm in enumerate(PTS):
        led_p = os.path.join(ROOT, "reports/aoi_points/%s.json" % nm)
        if not os.path.exists(led_p):
            problems.append("台账缺 %s" % nm)
            continue
        led = json.load(open(led_p, encoding="utf-8"))
        pos_led = [float(x) for x in led["pos"][:3]]
        quat = [float(x) for x in (led.get("quat") or [0, 0, 0, 1])]
        sk = tp.get(nm) or {}
        pos_sk = [float(x) for x in (sk.get("pos") or [])[:3]]
        pos_side = [float(x) for x in (side.get("point_xyz") or [])[i][:3]]
        d1 = max(abs(x - y) for x, y in zip(pos_led, pos_sk)) if pos_sk else -1
        d2 = max(abs(x - y) for x, y in zip(pos_led, pos_side)) if pos_side else -1
        if d1 < 0 or d1 > 1e-9:
            problems.append("%s 台账≠技能库 (%.3g)" % (nm, d1))
        if d2 < 0 or d2 > 1e-4:
            problems.append("%s 台账≠side_path (%.3g)" % (nm, d2))
        points_out[nm] = {"pos": pos_led, "quat": quat, "recorded_at": led.get("recorded_at"),
                          "source": led.get("source", "rokae_xcoresdk/endInRef")}
    if problems:
        print("❌ 同源自检未过, 不沉淀技能:")
        for p in problems:
            print("   -", p)
        return 1

    steps = []
    for i, nm in enumerate(PTS):
        steps.append({"op": "move", "to": nm, "ros": "line_abs", "quat": "taught", "skill": "L2.goto_surface_pt%d" % i,
                      "transition": ("就地起步" if i == 0 else "从 %s 走五次多项式平滑过渡 (端点 v=a=0, 25 采样点/段)" % PTS[i - 1])})
    steps.append({"op": "hold", "note": "到达即停: 每段端点速度/加速度为零(不冲过观察位), 二阶差分 %.3g m" % (side.get("smoothness") or {}).get("max_2nd_diff_m", 0)})

    sk = {"id": SID, "name": "🔍 AOI 侧面巡检 (示教4点 + 平滑过渡轨迹)", "layer": "L2", "kind": "muscle_memory",
          "version": 1, "group": "AOI检测",
          "source": "现场示教 %s (老倪手摇, 位姿唯一依据 xcoresdk endInRef 直采 20Hz)" % (side.get("created") or ""),
          "created": time.strftime("%Y-%m-%d %H:%M:%S"),
          "points": points_out,
          "steps": steps,
          "trajectory": {"file": "config/aoi/side_path.json", "sha256": sha256(SIDE),
                         "interp": side.get("interp"), "n_pts": len(side.get("trajectory") or []),
                         "segments": side.get("segments"), "smoothness": side.get("smoothness"),
                         "source_session": side.get("source_session")},
          "skill_refs": ["L2.goto_surface_pt0", "L2.goto_surface_pt1", "L2.goto_surface_pt2", "L2.goto_surface_pt3"],
          "guard": {"dz_down_limit_mm": 20, "why": "回示教点类技能铁律: 相对当前下降 >20mm 拒发"},
          "notes": ["点位真值 = reports/aoi_points/*.json + taught_points.json (同刻同值, 本文件为快照)",
                    "执行前逐步校验; 运动中零下发须走 8793 授权窗"]}

    p = os.path.join(MUSDIR, "%s.json" % SID.replace(".", "_"))
    os.makedirs(MUSDIR, exist_ok=True)
    upd = os.path.exists(p)
    if upd:
        old = json.load(open(p, encoding="utf-8"))
        sk["version"] = int(old.get("version", 1)) + 1
        sk["prev_version"] = old.get("version", 1)
    if a.dry:
        print("── dry: 将写 %s (v%s)%s" % (p, sk["version"], " [更新]" if upd else " [新建]"))
        print(json.dumps(sk, ensure_ascii=False, indent=1)[:900])
        return 0
    json.dump(sk, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    logev("update" if upd else "create", {"file": os.path.basename(p), "version": sk["version"],
                                          "points": len(sk["points"]), "traj_sha256": sk["trajectory"]["sha256"]})

    reg = json.load(open(REG, encoding="utf-8"))
    comp = reg.setdefault("composite", [])
    ent = {"id": SID, "name": sk["name"], "steps_file": "data/skills/l2_muscle/%s.json" % SID.replace(".", "_"),
           "group": "AOI检测", "point_source": "reports/aoi_points/*.json"}
    old_ent = next((c for c in comp if c.get("id") == SID), None)
    if old_ent is None:
        comp.append(ent)
        reg_added = True
    else:
        old_ent.update(ent)
        reg_added = False
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    logev("registry_%s" % ("add" if reg_added else "update"), {"composite_total": len(comp)})

    # 回读自证
    back = json.load(open(p, encoding="utf-8"))
    ok = (back["id"] == SID and len(back["points"]) == 4
          and back["trajectory"]["sha256"] == sha256(SIDE)
          and all(abs(a - b) < 1e-9 for nm in PTS
                  for a, b in zip(back["points"][nm]["pos"], json.load(open(os.path.join(ROOT, "reports/aoi_points/%s.json" % nm), encoding="utf-8"))["pos"][:3]))
          and any(c.get("id") == SID for c in json.load(open(REG, encoding="utf-8"))["composite"]))
    print("── 技能沉淀 ──")
    print(" %s %s (v%s, %d 点, %d 步)" % ("已更新" if upd else "已新建", p, back["version"], len(back["points"]), len(back["steps"])))
    print(" 轨迹引用 config/aoi/side_path.json sha256 %s…" % back["trajectory"]["sha256"][:16])
    print(" registry composite: %s (共 %d 条)" % ("新增" if reg_added else "已更新", len(comp)))
    print(" 回读自证(4点逐位==台账 + 轨迹sha256 + registry 命中): %s" % ("✅ 通过" if ok else "❌ 未过"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
