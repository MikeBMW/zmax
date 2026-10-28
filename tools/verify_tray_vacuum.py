#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 摆盘场景末端 = 真空吸盘 (不是夹爪); 插拔场景仍是夹爪; 两场景对象盘点"""
import json, os, sys, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = "/home/ubuntu/zmax"
sys.path[:0] = [ROOT + "/tools/gui", ROOT + "/tools", ROOT + "/src"]
FAIL = []
def chk(c, m):
    print(("  \u2705 " if c else "  \u2717 ") + m)
    if not c: FAIL.append(m)

# ① 场景对象盘点 (回答「摆盘场景怎么还有插拔的光模块」)
def names(sid):
    d = json.load(open("%s/data/scene/scenes/%s/objects3d.json" % (ROOT, sid), encoding="utf-8"))
    return [str(o.get("name") or "") for o in (d.get("objects") or [])]
tray, peg = names("SS-TRAY-PLACE"), names("SS-EPI-CORNER")
n_tray_mod = sum(1 for n in tray if "光模块" in n)
n_peg_blk = sum(1 for n in peg if "孔座" in n or "夹具" in n)
n_tray_ji = sum(1 for n in tray if "孔座" in n or "夹具" in n)
print("  摆盘 %d 对象: 光模块 x%d(料盘里, 摆盘工件) · tray盘隔板 x%d · 孔座/夹具 x%d"
      % (len(tray), n_tray_mod, sum(1 for n in tray if "隔板" in n), n_tray_ji))
print("  插拔 %d 对象: 孔座/夹具 x%d · 光模块 x%d" % (len(peg), n_peg_blk, sum(1 for n in peg if "光模块" in n)))
chk(n_tray_mod >= 3 and n_tray_ji == 0, "① 摆盘场景的对象构成对: 有料盘/工件光模块, 没有插拔的孔座夹具")
chk(n_peg_blk >= 9, "① 插拔场景特征物在插拔场景 (孔座/夹具 x%d) —— 不是被搬到摆盘里" % n_peg_blk)

import ss_dreamview as SV
# ② 工具判定 (唯一依据)
stub = types.SimpleNamespace(scene_id="SS-TRAY-PLACE")
k_tray = SV.DreamView3D._tool_kind(stub)
print("  摆盘 → 工具 %s (依据 %s)" % (k_tray, getattr(stub, "_tool_reason", "?")))
chk(k_tray == "vacuum" and "真空" in getattr(stub, "_tool_reason", ""), "② 摆盘 ⇒ 真空吸盘, 依据来自活跃任务/场景唯一依据")
stub2 = types.SimpleNamespace(scene_id="SS-EPI-CORNER")
k_peg = SV.DreamView3D._tool_kind(stub2)
chk(k_peg == "gripper", "② 插拔 ⇒ 两指夹爪 (依据 %s)" % getattr(stub2, "_tool_reason", "?"))

# ③ 真起 3D 视图: 摆盘 → 夹爪隐/吸盘显; 插拔 → 反过来
built = False
try:
    from PyQt5 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    w = SV.DreamView3D()
    for sid, want_vac in (("SS-TRAY-PLACE", True), ("SS-EPI-CORNER", False)):
        w.scene_id = sid
        os.environ["ZMAX_SCENE_DIR"] = "%s/data/scene/scenes/%s" % (ROOT, sid)
        w._build_scene(); app.processEvents()
        arm = (w._gl_items or {}).get("arm") or []
        ix = w._arm_idx
        vis = {k: arm[ix[k]].visible() for k in ("jaw_l", "jaw_r", "vac_stem", "vac_disc", "vac_hose")}
        print("   %s: %s" % (sid, vis))
        ok = (not vis["jaw_l"] and not vis["jaw_r"] and vis["vac_stem"] and vis["vac_disc"]) if want_vac else \
             (vis["jaw_l"] and vis["jaw_r"] and not vis["vac_stem"] and not vis["vac_disc"])
        chk(ok, "③ %s: %s" % (sid, "夹爪收起 + 吸盘可见" if want_vac else "夹爪可见 + 吸盘收起"))
        if want_vac:
            try:                                    # 动态帧也要能摆吸盘 (不崩)
                w._n = 1; w._update_frame(0); app.processEvents()
                chk(True, "③ 摆盘 _update_frame 不崩 (吸盘跟着末端走)")
            except Exception as e:
                chk(False, "③ _update_frame 异常: %r" % (e,))
    built = True
except Exception as e:
    print("  (3D 视图离屏起不来: %s: %s) → 以工具判定 + 源码接线为准" % (type(e).__name__, str(e)[:90]))
src = open(ROOT + "/tools/gui/ss_dreamview.py", encoding="utf-8").read()
chk("arm_vac_disc" in src and "setVisible(not _vac)" in src and "真空吸盘" in src, "④ 源码接线: 吸盘几何 + 夹爪按工具收起 + 说明")
chk(built, "⑤ 真起 3D 视图完成 (离屏 %s)" % ("OK" if built else "未起"))
print("\n%s  (%d 项失败)" % ("TRAY-VACUUM PASS" if not FAIL else "TRAY-VACUUM FAIL", len(FAIL)))
sys.exit(0 if not FAIL else 1)
