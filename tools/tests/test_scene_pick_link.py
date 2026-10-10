#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归: 3D 视口 ↔ 场景编辑清单 双向联动 (老倪 2026-10-10 要求)。

判据 (需 DISPLAY, 真 GL 渲染; offscreen 下投影矩阵不可靠):
  ① 点选命中: 对象盒中心投屏 → pick_at 回来必须是它自己, 或世界距 ≤40mm 的紧邻/上层同类件;
  ② 高亮: highlight(name) → 清单当前行 = 该对象 且 视口高亮框在位 (visible);
  ③ 反向: 切清单行 → _hl_name 跟着变;
  ④ 点空白 (画面角落) 不允许空指针/异常。

跑法: DISPLAY=:0 MUJOCO_GL=egl python tools/tests/test_scene_pick_link.py
注: 一个进程里连开两个场景 = 两个 GL 视图, 会刷 "Error while drawing item" 警告 ——
    这是已记录的单 GL 视图约束 (qt-gl 坑 1), 不是本功能缺陷; 判据只看 ✅/❌ 计数。
"""
import os
import sys

os.environ.setdefault("ZMAX_SCENE_EDIT_QUIET", "1")
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_ok = 0
_bad = 0


def _chk(cond, msg):
    global _ok, _bad
    if cond:
        _ok += 1
        print("  ✅ %s" % msg)
    else:
        _bad += 1
        print("  ❌ %s" % msg)


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication([])
    import numpy as np
    import ss_dreamview as DV
    import dreamview_scene_edit as DE

    for sid, targets in (("SS-TRAY-PLACE", ("机器人·夹爪左", "光模块 2 (在料盘里)", "tray盘·底板")),
                         ("SS-EPI-CORNER", ("机器人·夹爪左", "光模块 (peg)", "夹具/孔座 (peg_block)"))):
        d = os.path.join(ROOT, "data", "scene", "scenes", sid)
        if not os.path.isdir(d):
            print("  ⏭ 跳过 %s (场景目录不在)" % sid)
            continue
        os.environ["ZMAX_SCENE_DIR"] = d
        tr, meta = DV.load_episode()
        tr = dict(tr or {})
        tr["_meta"] = meta
        dv = DV.DreamView3D(tr, None, on_top=False)
        dv.resize(1150, 820)
        dv.show()
        app.processEvents()
        att = DE.attach_scene_edit(dv)
        app.processEvents()
        att.refresh_list()
        app.processEvents()
        print("[%s] 清单 %d 行 · 叠层线框 %d" % (sid, att.lst.count(), len(att.overlay_items)))
        boxes = att._obj_boxes()
        _chk(len(boxes) > 0, "%s: 对象盒非空 (%d)" % (sid, len(boxes)))
        _chk(att._matrices() is not None, "%s: 自建 proj@view 矩阵可用" % sid)
        names = [b[0] for b in boxes]
        for nm in targets:
            if nm not in names:
                print("  ⏭ %s 无此对象, 跳过" % nm)
                continue
            b = [x for x in boxes if x[0] == nm][0]
            q = att._project(b[1])
            _chk(q is not None, "%s: %s 可投影到屏幕" % (sid, nm))
            if q is None:
                continue
            got = att.pick_at(q[0], q[1])
            gb = [x for x in boxes if x[0] == got]
            dw = float(np.linalg.norm(np.array(gb[0][1]) - np.array(b[1]))) if gb else 9.9
            _chk(got == nm or dw <= 0.040, "%s: 点 %s 投屏处 → %r (世界距 %.3fm)" % (sid, nm, got, dw))
        nm0 = targets[0]
        att.highlight(nm0, from_3d=True)
        cur = att.lst.currentItem()
        row_nm = cur.data(0x0100) if cur is not None else None
        _chk(row_nm == nm0, "%s: highlight → 清单当前行 = %s (实得 %r)" % (sid, nm0, row_nm))
        _chk(att._hl_item is not None and att._hl_item.visible(), "%s: 视口高亮框在位" % sid)
        r2 = min(5, att.lst.count() - 1)
        att.lst.setCurrentRow(r2)
        app.processEvents()
        nm2 = att.lst.item(r2).data(0x0100)
        _chk(att._hl_name == nm2, "%s: 反向联动 清单第 %d 行 (%s) → _hl_name=%r" % (sid, r2, nm2, att._hl_name))
        try:
            att.pick_at(2.0, float(dv.view.height()) - 2.0)
            _chk(True, "%s: 点空白不崩" % sid)
        except Exception as e:                                                  # noqa: BLE001
            _chk(False, "%s: 点空白异常 %r" % (sid, e))
        att.clear_highlight()
        _chk(att._hl_name is None, "%s: clear_highlight 复位" % sid)
    print("\n结果: %d 过 / %d 败" % (_ok, _bad))
    return 0 if _bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
