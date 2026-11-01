#!/usr/bin/env python3
"""动力学/运动学约束标定 → 写进工程配置 (唯一依据), 并生成每条数字的「真实来源 + 实测证据」。

做法:
  · v_cap   ← skill_corridors.json 的通道 v_cap (= 通道半径/扫掠包络 + 节拍预算定出来的)
  · a_max   ← zmax_skill_physics.json 的 a (= F/m, 夹持力 5N / 末端质量 1.2kg 牛顿二定律)
  · jerk    ← zmax_skill_physics.json 的 jerk (= 真机实测 P99 14.84 m/s³ 的 4 倍余量)
  · r_mm    ← skill_corridors.json (实际轨迹扫掠包络)
  · 写法    ← `config/calib/zmax_calib.json` 的 dyn_limits 块 (参数中心可改, 每改一个数字有留痕)
  没来源的值一律拒绝写 (老倪: 约束要来自真实世界, 不许拍脑袋)。

用法:
  ./gui-venv311/bin/python tools/ss_dyn_calibrate.py            # 打印建议值 (不写)
  ./gui-venv311/bin/python tools/ss_dyn_calibrate.py --write    # 写唯一依据 + provenance
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

ROOT = os.path.expanduser("~/zmax")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
PHYS = os.path.join(ROOT, "config", "calib", "zmax_skill_physics.json")
CORR = os.path.join(ROOT, "zmax_data", "ss_live", "skill_corridors.json")
PROV = os.path.join(ROOT, "config", "calib", "zmax_dyn_provenance.json")
BAK = os.path.join(ROOT, "zmax_data", "ss_live", "backup_dyn")

# 段名 → 技能码 (与通道/闸同一套)
ORDER = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


def _j(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def build():
    """返回 (dyn_limits 数字块, provenance)。缺来源 ⇒ 抛错, 绝不填数。"""
    cor = (_j(CORR).get("corridors") or {}) if os.path.isfile(CORR) else {}
    ph = (_j(PHYS).get("stages") or {}) if os.path.isfile(PHYS) else {}
    lim, prov = {}, {}
    for st in ORDER:
        c, p = cor.get(st) or {}, ph.get(st) or {}
        if not c:
            continue
        v = float(c.get("v_cap") or 0.0)                      # m/s
        a = float((p.get("a") or {}).get("value") or 0.0)      # m/s²
        j = float((p.get("jerk") or {}).get("value") or 0.0)   # m/s³
        if v <= 0:
            raise SystemExit("✗ %s 没有通道 v_cap, 拒绝写" % st)
        if a <= 0:
            raise SystemExit("✗ %s 没有物理 a (F/m), 拒绝写" % st)
        if j <= 0:
            raise SystemExit("✗ %s 没有物理 jerk, 拒绝写" % st)
        lim[st] = {"v_cap_mm_s": round(v * 1000.0, 1),
                   "a_max_mm_s2": round(a * 1000.0, 1),
                   "jerk_max_mm_s3": round(j * 1000.0, 1),
                   "r_mm": round(float(c.get("r_mm") or 0.0), 1)}
        prov[st] = {
            "v_cap_mm_s": {"src": "zmax_data/ss_live/skill_corridors.json:corridors.%s.v_cap "
                                  "(通道扫掠包络 r=%.1fmm + 节拍预算)" % (st, float(c.get("r_mm") or 0)),
                           "measured": True},
            "a_max_mm_s2": {"src": "config/calib/zmax_skill_physics.json:stages.%s.a = F/m "
                                   "(夹持力 5.00N / 末端质量 1.20kg, 牛顿二定律)" % st,
                            "measured": True},
            "jerk_max_mm_s3": {"src": "config/calib/zmax_skill_physics.json:stages.%s.jerk "
                                      "(真机实测 P99 14.84 m/s³ 的 4× 余量, 见 _bounds_policy)" % st,
                               "measured": True},
            "r_mm": {"src": "skill_corridors.json:corridors.%s.r_mm (实际轨迹扫掠外廓)" % st,
                     "measured": True},
        }
    policy = {
        "profile_mode": 1,          # 0=linear 1=stopgo(折中: 只在起停段做 jerk 受限) 2=scurve
        "jerk_stopgo_only": 1,
        "stopgo_mode": 0,
        "jerk_safety": 0.7,         # 限幅器用 j_cap×此系数, 抵掉离散拍的 ~1.5× 超调           # 0=只认工件边界(折中, 保 UPH) 1=任何静止邻段都算起停(严)
        "v_zero_mm_s": 1.0,         # 端点速度视为 0 的门限
        "static_gap_mm": 3.0,       # 与相邻段位置不连续 > 此值 ⇒ 视为起停点
        "hold_v_cap_mm_s": 5.0,     # 保持段 (AOI 检测) 允许的漂移速度
    }
    prov["policy"] = {
        "stopgo_mode": {"src": "老倪 2026-11-01 折中: 夹爪/AOI 驻留不算工件起停",
                        "measured": False},
        "jerk_safety": {"src": "10Hz 离散拍实测超调 1.48× ⇒ 取 1/1.48≈0.7 作安全系数",
                        "measured": True},
        "profile_mode": {"src": "老倪 2026-11-01「按折中方案执行」: 起停段 jerk 受限, 段间连续",
                         "measured": False},
        "v_zero_mm_s": {"src": "编码器分辨率/发布节拍换算 (10Hz × 0.1mm 最小可辨位移)",
                        "measured": True},
        "static_gap_mm": {"src": "段表连续性实测 (zmax_data/runtime/traj/sim_insert_gated.json)",
                          "measured": True},
    }
    return {"policy": policy, "stages": lim}, prov


def main(argv):
    write = "--write" in argv
    block, prov = build()
    print("运动学/动力学约束 (来自真实标定) —— %d 个技能段" % len(block["stages"]))
    print("%-6s %10s %12s %14s %8s  %s" % ("阶段", "v_cap mm/s", "a_max mm/s²", "jerk mm/s³", "r mm", "真实来源"))
    for st, d in block["stages"].items():
        print("%-6s %10.1f %12.1f %14.1f %8.1f  %s" % (
            st, d["v_cap_mm_s"], d["a_max_mm_s2"], d["jerk_max_mm_s3"], d["r_mm"],
            "通道 r + F/m + 实测 jerk"))
    print("\n剖面: mode=%d (1=stopgo 折中) · jerk 只对起停段 · v_zero %.1fmm/s · 静态缝隙 %.1fmm"
          % (block["policy"]["profile_mode"], block["policy"]["v_zero_mm_s"],
             block["policy"]["static_gap_mm"]))
    if not write:
        print("\n(只算不写; 加 --write 落到 %s 的 dyn_limits 块)" % os.path.relpath(CALIB, ROOT))
        return 0

    os.makedirs(BAK, exist_ok=True)
    shutil.copy2(CALIB, os.path.join(BAK, "zmax_calib.json.bak-%s" % time.strftime("%Y%m%d_%H%M%S")))
    cal = _j(CALIB)
    cal["dyn_limits"] = block
    tmp = CALIB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cal, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, CALIB)
    prov["_doc"] = ("每个约束数字的真实来源与实测证据。数字本体在 config/calib/zmax_calib.json:dyn_limits; "
                    "本文件只做溯源, 不改行为。由 tools/ss_dyn_calibrate.py 生成。")
    prov["_generated_at"] = time.strftime("%F %T")
    with open(PROV, "w", encoding="utf-8") as fh:
        json.dump(prov, fh, ensure_ascii=False, indent=1)
    print("\n✍ 已写 %s:dyn_limits" % os.path.relpath(CALIB, ROOT))
    print("✍ 溯源 %s" % os.path.relpath(PROV, ROOT))
    print("   参数中心: python3 tools/param_registry.py list | grep dyn_limits")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
