#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register_lissa_fc.py — 把「里萨如力控插拔」注册成**计划节点** (画布/计划树可点的 L2 技能)。

为什么要注册这一条(而不是沿用 L2.lissa_insert):
  L2.lissa_insert 走产线 ROS 服务 /lissajous_force_search —— 2026-10-20 现场实测该服务**不在图上**
  (Orin 只有 44 个服务, 无 /lissajous_force_search, robot_driver 未跑), 调用必然 `waiting for service...`。
  现在真正跑通的是 xCoreSDK 直连脚本 `tools/rokae/insert_sdk_fc.py`(位置空间李萨如 + 六维力被动看门狗),
  由 `tools/lissa_fc.py` 封装成"本地脚本 + 参数"的形态 ⇒ 与 L2.aoi_gold_align 同一种 script 型节点。

注册内容:
  · L2.lissa_fc   🔌 里萨如力控插拔(SDK直连)  —— travel_mm 正=插 / 负=拔, 单节点跑完一段
  · L2.seat_fc    ⬇️ 一步直插到位点(SDK直连)  —— 给示教点就驻点直插, 力看门狗兜底
参数与脚本一一对应, 名字与 insert_sdk_fc.py 的 CLI 同名(改参数不用改代码)。

安全口径(写进 note, 节点本身不放宽):
  轴向硬红线 40N / 实际停手 ≤34N(脚本内 clamp) · 侧向 20N · 力矩 10Nm · 力停手后自动沿轴退 1.5mm 卸力。
"""
from __future__ import annotations

import json
import os
import shutil
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(REPO, "data/skills/l2_atomic/registry.json")

COMMON_NOTE = ("xCoreSDK 直连(不依赖 Orin ROS 运动栈): 位置空间李萨如 + 六维力被动看门狗, "
               "不进控制器力控模式(硬接触下 fcStart 必报 41451 Cart Velocity OverLimit 下电)。"
               "轴向硬红线 40N / 停手 ≤34N, 侧向 20N, 力矩 10Nm; 任何力停手后自动沿轴退 1.5mm 卸力"
               "(stop() 只保持位置, 楔紧时力会自涨到 100N+)。速度档实测: speed2≈1.9mm/s, speed8≈6.6mm/s。")


def _param(default, unit, lo, hi, label):
    return {"default": default, "unit": unit, "min": lo, "max": hi, "label": label}


def lissa_fc_skill():
    return {
        "id": "L2.lissa_fc",
        "name": "🔌 里萨如力控插拔 (SDK直连)",
        "icon": "🔌",
        "ros": "script",
        "script": "tools/lissa_fc.py",
        "args": ["--mode", "lissa"],
        "dry_default": False,
        "param": {
            "travel_mm": _param(50.0, "mm", -120.0, 120.0, "推进量 (+插 / −拔)"),
            "speed": _param(2.0, "档", 0.5, 15.0, "速度档 (2≈1.9mm/s, 8≈6.6mm/s)"),
            "amp": _param(0.2, "mm", 0.05, 1.5, "侧向摆幅 (大摆幅找孔, 进孔后收小)"),
            "step": _param(0.5, "mm", 0.1, 2.0, "每段轴向推进"),
            "stop_n": _param(30.0, "N", 5.0, 34.0, "轴向停手 (硬红线 40N)"),
            "lat_max": _param(20.0, "N", 5.0, 30.0, "侧向停手 (防划伤)"),
            "tq_max": _param(10.0, "Nm", 2.0, 15.0, "力矩停手"),
            "adm_k": _param(0.08, "", 0.0, 0.3, "侧向导纳系数 (0=关)"),
            "timeout": _param(180.0, "s", 20.0, 400.0, "脚本内部超时"),
        },
        "guard": {"max_lin_mm": 140, "note": "单节点单段 ≤140mm; 长行程分段发, 每段重新取力基线"},
        "note": "【里萨如力控插拔·SDK直连】tools/lissa_fc.py (转发 insert_sdk_fc.py --mode lissa)。" + COMMON_NOTE,
        "group": "插拔",
    }


def seat_fc_skill():
    return {
        "id": "L2.seat_fc",
        "name": "⬇️ 一步直插到位点 (SDK直连)",
        "icon": "⬇️",
        "ros": "script",
        "script": "tools/lissa_fc.py",
        "args": ["--mode", "seat"],
        "dry_default": False,
        "point_locked": True,
        "param": {
            "seat_pos": _param("0.811571,0.230612,0.184349", "x,y,z", 0.0, 0.0, "到位点 (示教点坐标)"),
            "seat_rpy": _param("3.12260,-1.47094,0.07103", "rad", 0.0, 0.0, "到位姿态 rpy"),
            "approach_mm": _param(12.0, "mm", 5.0, 60.0, "轴向前置 (⚠️ 快段必须停在孔口之前)"),
            "fast_speed": _param(6.0, "档", 1.0, 15.0, "快段档位"),
            "speed": _param(2.0, "档", 0.5, 8.0, "末段直插档位"),
            "stop_n": _param(30.0, "N", 5.0, 34.0, "轴向停手 (硬红线 40N)"),
            "lat_max": _param(20.0, "N", 5.0, 30.0, "侧向停手"),
            "tq_max": _param(10.0, "Nm", 2.0, 15.0, "力矩停手"),
            "timeout": _param(180.0, "s", 20.0, 400.0, "脚本内部超时"),
        },
        "guard": {"max_lin_mm": 200, "note": "接近段+末段一次排队; 已在接近点更深处则跳过接近段, 禁止反向后退"},
        "note": "【一步直插·SDK直连】tools/lissa_fc.py --mode seat。插入到位_1020c=[0.811571,0.230612,0.184349] "
                "rpy=[3.12260,-1.47094,0.07103]。⚠️ 实测坑: seat 点距孔口约 50mm, approach_mm 给小了(如12)会让"
                "快段直接冲进孔口, speed15 在孔口 1mm 内顶出 35.8N 把模块楔死 —— 快段只到孔口前 ~60mm。"
                + COMMON_NOTE,
        "group": "插拔",
    }


def main() -> int:
    reg = json.load(open(REG, encoding="utf-8"))
    bak = os.path.join("/tmp", "registry.json.prelissafc_%d" % time.time())
    shutil.copy2(REG, bak)
    ids = [s["id"] for s in reg["skills"]]
    made = []
    for sk in (lissa_fc_skill(), seat_fc_skill()):
        if sk["id"] in ids:
            reg["skills"][ids.index(sk["id"])] = sk
            made.append(("覆盖更新", sk["id"], sk["name"]))
        else:
            at = max(i for i, x in enumerate(reg["skills"]) if x["id"].startswith("L2.")) + 1
            reg["skills"].insert(at, sk)
            made.append(("新增", sk["id"], sk["name"]))
        ids = [s["id"] for s in reg["skills"]]
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 回读自检(缺一条等于没注册)
    allsk = json.load(open(REG, encoding="utf-8"))["skills"]
    chk = {s["id"]: s for s in allsk if s["id"] in ("L2.lissa_fc", "L2.seat_fc")}
    assert set(chk) == {"L2.lissa_fc", "L2.seat_fc"}, "回读缺技能"
    for sid, s in chk.items():
        assert s["ros"] == "script" and s["script"] == "tools/lissa_fc.py", "%s 不是 script 型" % sid
        assert os.path.isfile(os.path.join(REPO, s["script"])), "%s 脚本不存在" % sid
        assert isinstance(s["param"], dict) and len(s["param"]) >= 5, "%s 参数太少" % sid
        assert s["param"]["stop_n"]["max"] <= 34.0, "%s 轴向停手上限越红线" % sid
        assert "gripper" not in json.dumps(s, ensure_ascii=False), "%s 混入夹爪步骤" % sid
    for act, sid, sname in made:
        print("✅ %s %s「%s」" % (act, sid, sname))
    print("   技能总数 %d · 备份 %s" % (len(allsk), bak))
    print("   L2.lissa_fc: travel_mm 正=插/负=拔, 侧向摆幅/速度/三轴停手全可调")
    print("   L2.seat_fc : 给到位点一步直插, 快段只到孔口前")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
