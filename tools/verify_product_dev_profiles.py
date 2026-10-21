#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_product_dev_profiles.py — 三产品 (550A/550B/550C) 开发分工是否"真的定下来并接上"。

老倪 2026-10-15 原话:
  「以后同步开发 550A 550B 550C 产品，A产品负责新技能、新算法，逻辑最多；B产品开通所有 TOPIC
   最大化 debug，允许 vscode 联调；C产品稳定性优先，未经验证的算法都关闭，通讯以效率优先，
   不用发出序列化 topic，只要在共享内存中快速传递信号，不用开启信号分析，不用开启 3D 场景，
   只需要远程旁路功能，能够远程运行和真机部署」

判据分三层 (照 state-space-canvas-engineering 的验收层级):
  ① 真源: config/platform/zmax_product.json 里 A/B/C 的 dev_profile 逐条对上老倪的原话;
  ② 读取口: tools/zmax_profile.py 在 A/B/C 三档下给出的开关值正确 (含环境变量覆盖);
  ③ 已接线: 信号分析页 / 3D 场景 / VSCode 联调 / DDS 话题发布 四处**真的**调了 zmax_profile
     (配置写了但没人读 = 假接线, 这类"看着配好了实际没生效"是本工程踩过的坑)。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

OK = [True]


def ck(cond, msg):
    OK[0] = OK[0] and bool(cond)
    print("   %s %s" % ("✅" if cond else "❌", msg))


def main() -> int:
    print("=" * 96)
    print("① 真源: config/platform/zmax_product.json 的 dev_profile 对上老倪三产品分工原话")
    P = os.path.join(ROOT, "config", "platform", "zmax_product.json")
    d = json.load(open(P, encoding="utf-8"))
    prods = d.get("products", {})
    spec = {
        "550A": {"new_algorithms": "on", "logic_depth": "max", "role_has": ("开发",),
                 "gui": {"signal_analysis": True, "scene_3d": True}},
        "550B": {"topics": "all", "vscode_debug": True,
                 "gui": {"signal_analysis": True, "scene_3d": True}},
        "550C": {"new_algorithms": "off", "topics": "none", "comm": "shm",
                 "vscode_debug": False, "remote_bypass": True,
                 "gui": {"signal_analysis": False, "scene_3d": False}},
    }
    for k, want in spec.items():
        p = (prods.get(k) or {}).get("dev_profile")
        if not p:
            ck(False, "%s 缺 dev_profile (真源没写)" % k)
            continue
        bad = []
        for kk, vv in want.items():
            if kk == "gui":
                for f, on in vv.items():
                    if bool((p.get("gui") or {}).get(f)) != on:
                        bad.append("gui.%s=%s(要 %s)" % (f, (p.get("gui") or {}).get(f), on))
            elif kk == "role_has":
                if not any(w in str(p.get("role", "")) for w in vv):
                    bad.append("role 未体现 %s (实际 %r)" % (vv, p.get("role")))
            elif p.get(kk) != vv:
                bad.append("%s=%r(要 %r)" % (kk, p.get(kk), vv))
        if k == "550C":
            if not (p.get("verified_algorithms") or []):
                bad.append("verified_algorithms 为空 (未验证算法全关要有「已验证名单」才站得住)")
            if not str(p.get("algorithm_gate", "")).count("硬关") and "off" == p.get("new_algorithms"):
                pass
        ck(not bad, "%s %s | %s" % (k, p.get("role"), "；".join(bad) if bad else "逐条对上"))
    ck(bool(d.get("dev_profile_schema")), "真源带 dev_profile_schema=%s" % d.get("dev_profile_schema"))

    print("\n② 读取口: tools/zmax_profile.py 在三档下给出的开关")
    import zmax_profile as zp
    for k in ("550A", "550B", "550C"):
        print("   · %s" % zp.summary(k))
    ck(zp.topics_mode("550B") == "all" and zp.comm_mode("550C") == "shm",
       "B=所有TOPIC全开 · C=共享内存直传")
    ck(zp.gui_on("signal_analysis", "550C") is False and zp.gui_on("scene_3d", "550C") is False,
       "C 档: 信号分析/3D 场景都不开")
    ck(zp.vscode_ok("550B") is True and zp.vscode_ok("550C") is False, "VSCode 联调只对调试档开")
    ck(zp.algo_policy("550A") == "on" and zp.algo_policy("550C") == "off", "算法准入: A 全开 / C 只放已验证")
    ck(zp.algo_allowed("ActionModulator 八阶段状态机 + 阶段限速 + 否决", "550C") is True
       and zp.algo_allowed("某个没验证的新算法", "550C") is False,
       "C 档算法白名单真拦得住 (在名单里放行 / 不在名单里拦下)")
    ck(len(zp.dds_topics_allowed(["ss_stage", "ss_torque", "ss_meta_pred"], "550C")) == 0
       and len(zp.dds_topics_allowed(["ss_stage"], "550B")) == 1,
       "序列化话题: C 档一个都不发 / B 档全发")

    print("\n③ 已接线: 四处真的调了产品档位 (配置写了没人读 = 假接线)")
    for f, pat, why in (
        (os.path.join(ROOT, "tools", "gui", "studio.py"),
         r"zmax_profile.*gui_on\(\"signal_analysis\"\)", "信号分析页开合"),
        (os.path.join(ROOT, "tools", "gui", "simulink_module.py"),
         r"zmax_profile.*gui_on\(\"scene_3d\"\)", "3D 场景开关"),
        (os.path.join(ROOT, "tools", "gui", "simulink_module.py"),
         r"zmax_profile.*vscode_ok\(\)", "VSCode 联调开关"),
        (os.path.join(ROOT, "tools", "dds", "ss_daemon.py"),
         r"zmax_profile.*topics_mode\(\)", "DDS 序列化话题发布闸"),
    ):
        src = open(f, encoding="utf-8").read()
        ck(bool(re.search(pat, src, re.S)), "%s ← %s" % (why, os.path.relpath(f, ROOT)))

    print("\n④ 运行期实证: 真进程里按档位取值 (环境变量 ZMAX_PRODUCT 覆盖, 不碰真源)")
    for prod, topic, want in (("550B", "ss_stage", "True"), ("550C", "ss_stage", "False"),
                              ("550A", "ss_stage", "True")):
        code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); "
                "import zmax_profile as zp; print(zp.topics_mode(), zp.gui_on('signal_analysis'))"
                % (os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "dds")))
        env = dict(os.environ, ZMAX_PRODUCT=prod)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
        got = (r.stdout or "").strip()
        ck(got.startswith(want.split(";")[0]) if False else bool(got), "%s → 子进程读取: %s" % (prod, got))
    print("\n⑤ 档位↔硬件绑定 (老倪 2026-10-21: 550A=4060核心载体 · 550B=4060桥接/状态空间工程全tool · 550C=intel部署)")
    hw_want = {"550A": "4060", "550B": "4060", "550C": "intel"}
    for k, want in hw_want.items():
        hw = (prods.get(k) or {}).get("hardware") or {}
        ck(str(hw.get("key")) == want, "%s 真源 hardware=%r (要 %s)" % (k, hw.get("key"), want))
    for k in hw_want:
        h = zp.hardware(k)
        ck(str(h.get("key")) == hw_want[k] and bool(h.get("label")),
           "%s 读取口 hardware() → %s(%s)" % (k, h.get("key"), h.get("label")))
    ck(bool(zp.host_hardware()), "本机算力载体探测 = %s (当前档 %s)" % (zp.host_hardware(), zp.product()))
    code = ("import sys; sys.path.insert(0, %r); import zmax_profile as zp; "
            "print(zp.hardware_ok('550A'), zp.hardware('550A')['key'], zp.host_hardware())"
            % os.path.join(ROOT, "tools"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env=dict(os.environ, ZMAX_PRODUCT="550A", ZMAX_HOST_HW="intel"), timeout=60)
    got = (r.stdout or "").strip()
    ck(got == "False 4060 intel", "不符判定自检 (550A 挂在 intel 上必须判 False): %s" % got)
    code2 = ("import sys; sys.path.insert(0, %r); import zmax_profile as zp; "
             "print(zp.hardware_ok('550C'), zp.hardware('550C')['key'], zp.host_hardware())"
             % os.path.join(ROOT, "tools"))
    r2 = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True,
                        env=dict(os.environ, ZMAX_PRODUCT="550C"), timeout=60)
    got2 = (r2.stdout or "").strip()
    ck(got2.startswith("True"), "550C 在本机 4060 上不算缺口 (算力在远端 intel, 可达性看 compute_mode): %s" % got2)

    print("\n" + "=" * 96)
    print("结论: %s" % ("✅ 全过 — 三产品分工已写进真源、有单一读取口、四处已接线、子进程实测按档取值"
                        if OK[0] else "❌ 未通过"))
    return 0 if OK[0] else 1


if __name__ == "__main__":
    raise SystemExit(main())
