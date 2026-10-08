#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""幂等注册「空间1~7」技能 (L2.goto_spaceN) —— 与号位技能同规格的三段单轴安全轨迹。

2026-10-08 修 (老倪: 「根治那个自适应抬升」):
  阶段1 就地抬升原来是**死写 50mm** ⇒ 只要臂比目标点位低 >50mm, 紧随其后的 keep_z 横移
  就会低于该点位高度 ⇒ 被 z_floor 拒发 ⇒ **整条计划零下发**(现场: 点开始建图 机器人一动不动,
  空间1/2 记在空中 z=0.3596 而臂在 0.2596 时必现)。
  现给阶段1 加 `adapt_point: true` + `adapt_margin_mm: 2` ⇒ 执行器算目标时取
  `max(当前z + dz_mm, 该点位z + margin)`, 保证横移高度永不低于目标点;
  臂本来就不低于该点位时照旧走 dz_mm 常规抬升 ⇒ **正常情况行为零变化**。
  同时执行器为 adapt_point 段给「到该点位本身必升的高度」豁免爬升闸(见 l2_daemon 爬升闸注释)。

幂等: 只重建 L2.goto_spaceN(points 里存在的 space1..spaceN), 其它技能一字不动。
点位真值在 data/skills/l2_atomic/space_points.json(老倪 8793 空间点控件记录)。
用法: python3 tools/register_space_skills.py [--dry]
"""
import argparse
import json
import os
import shutil
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
SP = os.path.join(REPO, "data/skills/l2_atomic/space_points.json")

LIFT_MARGIN_MM = 0.0    # 🔴 2026-10-08 老倪第四次纠正: 「不要总先上升, 都好几次了, 记住」
                        #    抬到"转移高度"这个配方本身就是错的 ⇒ 余量归零; 竖直只走到
                        #    **该点自身的高度**(dz_mm 给一个大负数, 让 max(cur+dz, point+margin) 恒等于 point_z)

def build_skill(n, pname):
    """四段: ①就地抬升(自适应) ②保持当前高度横移 ③降到正上方 30mm ④落到位(禁下压)"""
    return {
        "id": "L2.goto_space%d" % n,
        "name": "🚀 空间%d" % n,
        "icon": "🚀",
        "ros": "line_abs",
        "quat": "taught",
        "point": pname,
        "point_locked": True,
        "speed_max": 1000,
        "param": {},
        "guard": {"max_lin_mm": 1500.0, "z_floor_point": pname, "z_floor_offset_mm": 0},
        "steps": [
            {
                "stage": 1, "rel": True, "dz_mm": -1000.0,
                "adapt_point": True, "adapt_margin_mm": 0.0,
                "note": "阶段1 竖直抬到「该点 z + 40mm」(自适应 max(当前z, 该点z+40) ⇒ 既不盲抬也不低于目标) —— 纯竖直段",
                "guard": {"dz_down_limit_mm": 400},
                "tol_mm": 1.0, "timeout_s": 120, "dwell_s": 1.5,
            },
            {
                "stage": 2, "to": pname, "dz_mm": 0.0, "keep_z": True,
                "note": "阶段2 保持当前高度横移到该点正上方(keep_z) —— 纯水平段(2026-10-08 老倪「改」: 斜线会被 50102 奇异点拒发, 故拆成单轴)",
                "guard": {"dz_down_limit_mm": 400},
                "tol_mm": 1.0, "timeout_s": 240, "dwell_s": 1.5,
            },
            {
                "stage": 3, "to": pname, "dz_mm": 0.0,
                "note": "阶段3 竖直下落到位(到位即停, 禁下压) —— 纯竖直段",
                "guard": {"dz_down_limit_mm": 260},
                "tol_mm": 0.5, "timeout_s": 60, "dwell_s": 1.0,
            },
        ],
        "contact_guard": "阶段3 到位即停、禁下压; 若现场见触底/顶住, 把点位抬高 3~5mm 重录 —— 不改判据硬说成功",
        "note": "去现场记录的『空间%d』(8793 空间点控件记录, ROKAE SDK 真值) — 三段单轴安全轨迹: "
                "①竖直抬到(该点 z+40mm) ②保持高度横移(keep_z) ③竖直落到位; "
                "与号位技能同一条授权+收口链, 点位锁死不可由页面改写" % n,
        "group": "空间点(去这个点)",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    pts = json.load(open(SP, encoding="utf-8")).get("points", {})
    names = sorted([k for k in pts if k.startswith("space") and k[5:].isdigit()],
                   key=lambda k: int(k[5:]))
    if not names:
        print("space_points.json 里没有 spaceN 点 ⇒ 无事可做"); return

    reg = json.load(open(REG, encoding="utf-8"))
    is_list = isinstance(reg.get("skills"), list)
    skills = reg["skills"] if is_list else list(reg["skills"].values())

    made, kept = [], 0
    for pname in names:
        n = int(pname[5:])
        sk = build_skill(n, pname)
        hit = [i for i, s in enumerate(skills) if s.get("id") == sk["id"]]
        if hit:
            skills[hit[0]] = sk
        else:
            skills.append(sk)
        made.append(sk["id"])
    kept = len(skills) - len(made)
    print("将写入/重建 %d 个空间技能: %s" % (len(made), ", ".join(made)))
    print("其余技能 %d 个一字不动" % kept)
    if a.dry:
        print("(dry) 未写盘"); return

    bak = REG + ".bak_spaceadapt_%s" % time.strftime("%Y%m%d_%H%M%S")
    shutil.copyfile(REG, bak)
    reg["skills"] = skills if is_list else {s["id"]: s for s in skills}
    tmp = REG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    json.load(open(tmp, encoding="utf-8"))          # 语法自检
    os.replace(tmp, REG)
    print("已写盘 (备份 %s)" % os.path.basename(bak))
    print("回读核验:", json.load(open(REG, encoding="utf-8"))["skills"][0]["id"] if is_list else "dict-ok")


if __name__ == "__main__":
    main()
