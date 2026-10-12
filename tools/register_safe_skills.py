#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_safe_skills.py — 幂等注册「安全点N」回点技能 (L2.goto_safeN)

2026-10-12 老倪: 「金手指 点1 点2 安全点, 侧面点 准备点/侧面点0~3 —— 都变成 标记模式和运动模式」。
  · 标记模式(记/清)由 8793 的 /ctl/record_point · /ctl/clear_point 收口(点页即可);
  · **运动模式**要真的能走过去 ⇒ 每个已记录的安全点需要一个回点技能。
    安全点是"退让/停靠"位, 与空间点同性质(可能跨大距离、可能比当前低) ⇒ 轨迹规格照抄
    空间点技能(approved 版, 2026-10-08 老倪「不要总先上升」后定的四段单轴):
      ①就地竖直抬到「该点 z + 0」(自适应 max(当前z, 该点z)) ②保持该高度横移(keep_z)
      ③(仅空间点有的一段)本轮不需要 —— 安全点与空间点同构, 直接沿用三段:
        ①自适应竖直 ②keep_z 横移 ③竖直落到该点(到位即停, 禁下压)
  · 只重建 L2.goto_safeN(N = taught_points.json 里 安全点1..N 存在的那些), **其它技能一字不动**;
    写盘前备份 + 语法自检 + 回读核验。

用法: python3 tools/register_safe_skills.py [--dry]
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
TP = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")
WHITELIST = os.path.join(REPO, "data/skills/l2_atomic/ctl_abs_skills.json")


def build_skill(n, pname):
    """三段单轴安全轨迹(与空间点同规格; 详见 register_space_skills.py 的车轱辘话注释)。"""
    return {
        "id": "L2.goto_safe%d" % n,
        "name": "🛟 安全点%d" % n,
        "icon": "🛟",
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
                "note": "阶段1 竖直抬到「该点 z」(自适应 max(当前z, 该点z) ⇒ 既不盲抬也不低于目标) —— 纯竖直段",
                "guard": {"dz_down_limit_mm": 400},
                "tol_mm": 1.0, "timeout_s": 120, "dwell_s": 1.5,
            },
            {
                "stage": 2, "to": pname, "dz_mm": 0.0, "keep_z": True,
                "note": "阶段2 保持该高度横移到安全点正上方(keep_z) —— 纯水平段(斜线会被 50102 奇异点拒发, 故拆单轴)",
                "guard": {"dz_down_limit_mm": 400},
                "tol_mm": 1.0, "timeout_s": 240, "dwell_s": 1.5,
            },
            {
                "stage": 3, "to": pname, "dz_mm": 0.0,
                "note": "阶段3 竖直落到安全点(到位即停, 禁下压) —— 纯竖直段",
                "guard": {"dz_down_limit_mm": 260},
                "tol_mm": 0.5, "timeout_s": 60, "dwell_s": 1.0,
            },
        ],
        "contact_guard": "阶段3 到位即停、禁下压; 若现场见触底/顶住, 把点位抬高 3~5mm 重录 —— 不改判据硬说成功",
        "note": "去现场记录的『安全点%d』(8793 金手指窗口记录, ROKAE SDK 真值) — 三段单轴安全轨迹: "
                "①竖直抬到该点高度 ②保持高度横移 ③竖直落到位; 与号位/空间点同一条授权+收口链, 点名锁死" % n,
        "group": "安全点(去这个点)",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    pts = json.load(open(TP, encoding="utf-8")).get("points", {})
    hits = [k for k in pts if re.fullmatch(r"安全点\d{1,2}", str(k))]
    hits.sort(key=lambda k: int(re.fullmatch(r"安全点(\d{1,2})", k).group(1)))
    if not hits:
        print("taught_points.json 里没有 安全点N ⇒ 无事可做"); return

    reg = json.load(open(REG, encoding="utf-8"))
    is_list = isinstance(reg.get("skills"), list)
    skills = reg["skills"] if is_list else list(reg["skills"].values())
    n_all = len(skills)

    made = []
    for pname in hits:
        n = int(re.fullmatch(r"安全点(\d{1,2})", pname).group(1))
        sk = build_skill(n, pname)
        idx = [i for i, s in enumerate(skills) if s.get("id") == sk["id"]]
        if idx:
            skills[idx[0]] = sk
        else:
            skills.append(sk)
        made.append(sk["id"])

    print("将写入/重建 %d 个安全点技能: %s" % (len(made), ", ".join(made)))
    print("其余技能 %d 个一字不动(技能总数 %d → %d)" % (n_all - len(made), n_all, len(skills)))
    if a.dry:
        print("(dry) 未写盘"); return

    bak = REG + ".bak_safe_%s" % time.strftime("%Y%m%d_%H%M%S")
    shutil.copyfile(REG, bak)
    reg["skills"] = skills if is_list else {s["id"]: s for s in skills}
    tmp = REG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    json.load(open(tmp, encoding="utf-8"))          # 语法自检
    os.replace(tmp, REG)
    back = json.load(open(REG, encoding="utf-8"))
    got = [s["id"] for s in (back["skills"] if is_list else back["skills"].values())
           if str(s.get("id", "")).startswith("L2.goto_safe")]
    print("已写盘 (备份 %s) · 回读核验: %s (共 %d 条)" % (os.path.basename(bak), got, len(got)))

    # 顺带把技能 id 加进**热读白名单覆盖层**(加回点按钮不必重启 8793 推流服务)
    try:
        wl = json.load(open(WHITELIST, encoding="utf-8"))
        sk_map = wl.setdefault("skills", {})
        added = []
        for pname in hits:
            n = int(re.fullmatch(r"安全点(\d{1,2})", pname).group(1))
            sid = "L2.goto_safe%d" % n
            if sid not in sk_map:
                sk_map[sid] = "🛟 安全点%d" % n
                added.append(sid)
        if added:
            wl["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            shutil.copyfile(WHITELIST, WHITELIST + ".bak_safe_%s" % time.strftime("%Y%m%d_%H%M%S"))
            tmp2 = WHITELIST + ".tmp"
            with open(tmp2, "w", encoding="utf-8") as f:
                json.dump(wl, f, ensure_ascii=False, indent=2)
            json.load(open(tmp2, encoding="utf-8"))
            os.replace(tmp2, WHITELIST)
            print("白名单覆盖层 +%d: %s (热读, 不用重启推流服务)" % (len(added), ", ".join(added)))
        else:
            print("白名单覆盖层已含全部安全点技能(未改)")
    except Exception as e:                                                        # noqa: BLE001
        print("⚠️ 白名单覆盖层写入失败(技能已注册, 手动补即可): %s" % str(e)[:140])


if __name__ == "__main__":
    sys.exit(main())
