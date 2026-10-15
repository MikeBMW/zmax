#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_dev_profiles.py — 把老倪 2026-10-15 定的「三产品开发分工」写进产品真源。

老倪: 「以后同步开发 550A 550B 550C 产品，A产品负责新技能、新算法、逻辑最多；B产品开通所有 TOPIC
最大化 debug，允许 vscode 联调；C产品稳定性优先，未经验证的算法都关闭，通讯以效率优先，不用发出
序列化 topic，只要在共享内存中快速传递信号，不用开启信号分析，不用开启 3D 场景，只需要远程旁路功能，
能够远程运行和真机部署」

只写 config/platform/zmax_product.json 的 products[*].dev_profile (人可编·进 git 的真源)；
不动 capabilities / releases / fingerprints / invariants / checks。
"""
from __future__ import annotations

import collections
import io
import json
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "config", "platform", "zmax_product.json")

OD = collections.OrderedDict
PROFILES = {
    "550A": OD([
        ("role", "开发版 · 新技能 / 新算法 / 最新逻辑都在这档"),
        ("chief_concern", "功能最全: 新技能、新算法、逻辑最多 (允许不稳定)"),
        ("new_algorithms", "on"),
        ("algorithm_gate", "先验不拦 (只看能不能跑通)"),
        ("logic_depth", "max"),
        ("topics", "core"),
        ("comm", "dds"),
        ("gui", OD([("signal_analysis", True), ("scene_3d", True)])),
        ("vscode_debug", True),
        ("remote_bypass", True),
        ("deploy", "仿真/台架为主, 真机按需"),
        ("notes", "新东西先在这档落地; 在役产线不用这档。"),
    ]),
    "550B": OD([
        ("role", "调试版 · 最大化 debug (看得到、能联调)"),
        ("chief_concern", "观测与可调试性优先: 所有 TOPIC 全开, 允许 VSCode 联调"),
        ("new_algorithms", "debug"),
        ("algorithm_gate", "全部可开 (逐条开关显式, 不默认静默降级)"),
        ("logic_depth", "high"),
        ("topics", "all"),
        ("comm", "dds"),
        ("gui", OD([("signal_analysis", True), ("scene_3d", True)])),
        ("vscode_debug", True),
        ("remote_bypass", True),
        ("deploy", "调试用真机/仿真皆可"),
        ("notes", "现场调试与取证用这档: 信号分析 / 3D 场景 / 全话题 / VSCode 断点都开。"),
    ]),
    "550C": OD([
        ("role", "量产版 · 稳定性优先"),
        ("chief_concern", "稳: 未经验证的算法全关; 通讯以效率优先 (不发序列化 topic, 共享内存直传)"),
        ("new_algorithms", "off"),
        ("algorithm_gate", "只允许 verified_algorithms 里的; 其余硬关 (不是「默认关」可被悄悄打开)"),
        ("logic_depth", "fixed"),
        ("topics", "none"),
        ("comm", "shm"),
        ("shm_dir", "/dev/shm/zmax_ss_engine"),
        ("gui", OD([("signal_analysis", False), ("scene_3d", False)])),
        ("vscode_debug", False),
        ("remote_bypass", True),
        ("remote_bypass_scope", "远程运行 · 真机部署 · 旁路调试"),
        ("deploy", "真机量产产线"),
        ("verified_algorithms", [
            "ActionModulator 八阶段状态机 + 阶段限速 + 否决",
            "FeedforwardAccelerator (左脑 MLP 快通道 + 域外解析守卫)",
            "安全执行边界 饱和限幅",
            "ManifoldEngine 势场导航 (驱动扭矩 T_drive=M·(−∇Φ))",
            "状态估计/校正 + 接触判别",
            "动作执行链 (MoveIt/SDK) 速度口径 mm/s 收口",
        ]),
        ("notes", "在役产线用这档: 只跑已验证算法; 信号走共享内存, 不开信号分析/3D, 只留远程旁路。"),
    ]),
}
NOTE = ("老倪 2026-10-15 定: 三产品同步开发 —— A=新技能/新算法/逻辑最多 (开发) · "
        "B=所有 TOPIC 全开 + 最大化 debug + 允许 VSCode 联调 (调试) · "
        "C=稳定性优先: 未验证算法全关、通讯效率优先 (不发序列化 topic, 共享内存直传)、"
        "不开信号分析/不开 3D 场景、只保留远程旁路 (远程运行 + 真机部署)。")


def main() -> int:
    d = json.load(open(P, encoding="utf-8"), object_pairs_hook=OD)
    b = P + ".bak_%s" % time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(P, b)
    for k, prof in PROFILES.items():
        assert k in d["products"], "产品档不存在: %s" % k
        d["products"][k]["dev_profile"] = prof
    d["dev_profile_schema"] = "zmax.product.dev_profile.v1"
    d["dev_profile_note"] = NOTE
    d["updated"] = "2026-10-15 (v5.50.730 · 三产品开发分工)"
    with io.open(P, "w", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    d2 = json.load(open(P, encoding="utf-8"))
    print("✅ 已写 %s\n   备份 %s" % (P, b))
    for k in ("550A", "550B", "550C"):
        p = d2["products"][k]["dev_profile"]
        print("   %s | %s | topics=%s comm=%s gui=%s vscode=%s 远程旁路=%s 算法=%s"
              % (k, p["role"], p["topics"], p["comm"], dict(p["gui"]), p["vscode_debug"],
                 p["remote_bypass"], p["new_algorithms"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
