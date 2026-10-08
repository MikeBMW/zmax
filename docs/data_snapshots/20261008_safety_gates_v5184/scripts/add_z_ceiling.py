#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「空间点1~7 = 安全区域，不要上升太高」落成硬闸门:
  ① l2_transport_sdk.py: 新增 taught_z_ceiling()(读 7 个点最高 z + 余量) 并把 env_box 的 z 上限夹到它
     ⇒ 代理每 0.15s 的真值扫掠闸门也一并收口(它能抓住 MoveJ 关节摆升这种"计划外升高")
  ② l2_daemon.py: 每个阶段目标 z 高于天花板 ⇒ **拒发**(单段/多段都拦, 不再只吼不拦)
  ③ 语法自检 + 回读核验"""
import ast
import os
import shutil
import time

REPO = "/home/ubuntu/zmax"
SDK = os.path.join(REPO, "tools/rokae/l2_transport_sdk.py")
DMN = os.path.join(REPO, "tools/l2_daemon.py")
ts = time.strftime("%Y%m%d_%H%M%S")

HELPER = '''

# 🧱 安全区天花板 (2026-10-08 老倪: 「给你的空间点1~7, 就是安全区域, 你要参考, 不要上升的太高」)
#    安全区由**已教点位**定义 ⇒ 天花板 = 所有空间点里最高那个 z + 余量。动态读, 改点位自动跟着变。
TAUGHT_Z_MARGIN_M = 0.05        # 最高点位之上留 50mm 余量(点位本身都可直达, 高于此即出安全区)


def taught_z_ceiling():
    """安全区天花板(m): 空间点最高 z + TAUGHT_Z_MARGIN_M。读不到点位时退回 None(不拦)。"""
    try:
        _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data/skills/l2_atomic/space_points.json")
        pts = (json.load(open(_p, encoding="utf-8")) or {}).get("points") or {}
        zs = [float((v or {}).get("pos", [0, 0, 0])[2]) for v in pts.values() if (v or {}).get("pos")]
        if not zs:
            return None
        return max(zs) + TAUGHT_Z_MARGIN_M
    except Exception:                                                          # noqa: BLE001
        return None
'''

# ── ① SDK 侧 ──
s = open(SDK, encoding="utf-8").read()
if "taught_z_ceiling" in s:
    print("  ① SDK 已有天花板, 跳过")
else:
    assert "\ndef env_box():" in s, "找不到 env_box 定义"
    shutil.copy2(SDK, SDK + ".bak_zceiling_" + ts)
    s = s.replace("\ndef env_box():", HELPER + "\ndef env_box():", 1)
    old_ret = '        return {a: [float(env[a][0]), float(env[a][1])] for a in ("x", "y", "z") if a in env}'
    assert old_ret in s, "找不到 env_box 的 return"
    new_ret = '''        box = {a: [float(env[a][0]), float(env[a][1])] for a in ("x", "y", "z") if a in env}
        # 🧱 天花板收口: 扫掠闸门只认安全区高度(2026-10-08 老倪: 空间点1~7 就是安全区域)
        _ceil = taught_z_ceiling()
        if _ceil and "z" in box and box["z"][1] > _ceil:
            box["z"] = [box["z"][0], _ceil]
        return box'''
    s = s.replace(old_ret, new_ret, 1)
    open(SDK, "w", encoding="utf-8").write(s)
    print("  ① SDK: 已加 taught_z_ceiling() + env_box 的 z 上限夹到天花板 ✓")

# ── ② 执行器侧 ──
d = open(DMN, encoding="utf-8").read()
if "🧱 安全区天花板" in d:
    print("  ② 执行器已有天花板闸, 跳过")
else:
    shutil.copy2(DMN, DMN + ".bak_zceiling_" + ts)
    anchor = '''        log("🌍 环境校验 阶段 %d/%d: %s" % (i, n, env_msg))'''
    assert anchor in d, "找不到环境校验日志锚点"
    add = anchor + '''
        # 🧱 安全区天花板闸 (2026-10-08 老倪: 「给你的空间点1~7, 就是安全区域, 你要参考, 不要上升的太高」)
        #    安全区 = 已教点位定义 ⇒ 天花板 = 最高点位 z + 50mm。单段/多段**都硬拦**
        #    (旧爬升闸只对 >=2 段硬拦, 单段直发只吼 ⇒ 单段"去某个高点"能溜过去, 正是 10-22 事故的缝)
        try:
            _ceil = l2_transport_sdk.taught_z_ceiling()
            if _ceil and pl.get("pos") and float(pl["pos"][2]) > _ceil + 1e-6:
                log("🧱 阶段 %d/%d 拒发: 目标 z=%.4f 高于**安全区天花板** %.4f (最高空间点 z=%.4f + 50mm)"
                    " —— 老倪 2026-10-08: 空间点1~7 就是安全区域, 不要上升太高" %
                    (i, n, float(pl["pos"][2]), _ceil, _ceil - 0.05))
                return "阶段 %d 拒发: z=%.4f 超安全区天花板 %.4f" % (i, float(pl["pos"][2]), _ceil)
            log("🧱 阶段 %d/%d 高度检查: 目标 z=%.4f ≤ 安全区天花板 %.4f ✅" % (i, n, float(pl["pos"][2]), _ceil))
        except Exception as _e:                                                  # noqa: BLE001
            log("🧱 阶段 %d/%d 高度检查跳过(%s)" % (i, n, str(_e)[:40]))'''
    d = d.replace(anchor, add, 1)
    # 确保 import 了 l2_transport_sdk
    if "import l2_transport_sdk" not in d and "l2_transport_sdk" not in d.split("def ")[0]:
        print("  ⚠️ 执行器没 import l2_transport_sdk, 需要补 —— 先停手")
    open(DMN, "w", encoding="utf-8").write(d)
    print("  ② 执行器: 已加天花板硬闸(单段也拦) ✓")

# ── ③ 自检 ──
ast.parse(open(SDK, encoding="utf-8").read())
ast.parse(open(DMN, encoding="utf-8").read())
print("  ③ 语法 ✅ 两个文件都过")
s2, d2 = open(SDK, encoding="utf-8").read(), open(DMN, encoding="utf-8").read()
print("  ③ 回读: SDK taught_z_ceiling=%d 处 · 执行器天花板闸=%d 处 · l2_transport_sdk 引用=%d 处"
      % (s2.count("taught_z_ceiling"), d2.count("🧱 安全区天花板"), d2.count("l2_transport_sdk")))
