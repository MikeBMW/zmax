#!/usr/bin/env python3
"""判据: 信号分析「场景标记 + 按色排序」与 AR 底图来源 —— 真跑, 不靠看代码 (老倪 2026-10-12 要求)。

覆盖:
  ① 标签真源: AR/AOI 信号 → AR场景(紫 #8957e5); 未分类 → 白 #ffffff
  ② 颜色/任务映射与 tools/ss_scene_switch.py **逐字一致**(不重写映射)
  ③ AR 底图来源清单(8797 /api/cams): 4 台相机都在册 + 状态空间视频源有真帧龄
  ④ 4 路快照是真 JPEG(魔数 ff d8) —— 底图确实来自状态空间工程视频源
  ⑤ 信号分析页真起(CanoeGraphicWidget, offscreen): 目录项带 ●/○ 场景标记 + 四个排序按钮齐 + 选色真置顶
用法: ./gui-venv311/bin/python tools/verify_sig_scene_tags.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS, FAIL, SKIP = [], [], []


def ck(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("✅" if ok else "❌", name, ("  · " + str(detail)) if detail else ""))


def ck_skip(name, detail=""):
    SKIP.append(name)
    print("  ⚠️ SKIP %s%s" % (name, ("  · " + str(detail)) if detail else ""))


def main() -> int:
    print("=== ① 标签真源 (tools/sig_scene_tags.py) ===")
    import sig_scene_tags as SST
    import ss_scene_switch as SSW
    ck("AR/AOI 信号 → AR场景", SST.tag("光学质量检测.判决") == "AR场景", SST.tag("光学质量检测.判决"))
    ck("ar. 前缀也认", SST.tag("ar.AOI.判决") == "AR场景", SST.tag("ar.AOI.判决"))
    ck("未分类 = 白", SST.tag("光模块头到孔_mm") == "" and SST.color("光模块头到孔_mm").lower() == "#ffffff",
       SST.color("光模块头到孔_mm"))
    reg = json.load(open(os.path.join(ROOT, "config", "topics", "scene_tags.json"), encoding="utf-8"))
    ck("注册表有计数", isinstance(reg.get("counts"), dict), reg.get("counts"))

    print("=== ② 颜色/任务映射与 ss_scene_switch 逐字一致 ===")
    for tid, m in SSW.TASK_SCENE.items():
        got = (SST.SCENE_COLOR or {}).get(m["scene"])
        ck("颜色一致 %s/%s" % (tid, m["scene"]), got == m["color"], "%s vs %s" % (got, m["color"]))
    ck("三色齐(绿/蓝/紫)", {SSW.TASK_SCENE[t]["color"] for t in SSW.TASK_SCENE} ==
       {"#2e8b57", "#1f6feb", "#8957e5"})

    print("=== ③ AR 底图来源清单 (8797 /api/cams) ===")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8797/api/cams", timeout=8) as r:
            camsdoc = json.loads(r.read().decode())
        cams = camsdoc.get("cams") or {}
        four = camsdoc.get("four") or []
        ck("4 台相机在册", all(k in cams for k in ("arm", "gold", "surface", "rs")), four)
        ck("默认底图 = 状态空间视频源(arm)", camsdoc.get("default") == "arm", camsdoc.get("default"))
        _srcs = {k: (cams.get(k) or {}).get("src") for k in ("arm", "gold", "surface")}
        ck("arm/gold/surface 标 sstate(状态空间视频源)", all(v == "sstate" for v in _srcs.values()), _srcs)
        _age = (cams.get("arm") or {}).get("age_s")
        ck("arm 有真帧龄(视频源活着)", isinstance(_age, (int, float)) and _age < 30, _age)
    except Exception as e:                                                        # noqa: BLE001
        ck("AR 服务 /api/cams 可读", False, "%s: %s" % (type(e).__name__, e))

    print("=== ④ 4 路快照是真 JPEG (底图来自状态空间视频源) ===")
    for k in ("arm", "gold", "surface", "rs"):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8797/snap/%s.jpg" % k, timeout=15) as r:
                b = r.read()
            ck("snap/%s.jpg 真 JPEG" % k, b[:2] == b"\xff\xd8" and len(b) > 8000, "%d B" % len(b))
        except Exception as e:                                                    # noqa: BLE001
            ck("snap/%s.jpg 可取" % k, False, "%s: %s" % (type(e).__name__, e))

    print("=== ⑤ 信号分析页: 场景标记 + 四色排序按钮 (真起窗口) ===")
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        import canoe_graphic as CG
        w = CG.CanoeGraphicWidget()
        btns = getattr(w, "_scene_btns", {})
        ck("四个排序按钮齐(白/绿/蓝/紫)", set(btns.keys()) == {"", "插拔场景", "摆盘场景", "AR场景"},
           sorted(btns.keys()))
        ck("默认 = 全部(白)", getattr(w, "_scene_sort", None) == "", getattr(w, "_scene_sort", None))
        # 塞进真信号(带 ar. 前缀的 AR 信号 + 一个未分类), 重建目录
        import time as _t
        for key, col in (("ar.光学质量检测.判决", "#ff0000"), ("sstrace.光模块头到孔_mm", "#00ff00")):
            b = CG.SignalBuffer(key, col, "test")
            b.push(_t.time(), 0.0)
            w.store.bufs[key] = b
        # ar. 那一组只在「全部来源」范围下显示(3D 范围只列 sstrace.*, 这是既有口径) ⇒ 判据要在全部范围下看
        w.scope = "all"
        w._fill_tree()
        _dots, _colors, _plain = [], [], []
        def _walk(it):
            for i in range(it.childCount()):
                c = it.child(i)
                t = c.text(0)
                if t.startswith("● "):
                    _dots.append(t); _colors.append(c.foreground(0).color().name())
                elif t.startswith("○ "):
                    _plain.append(t)
                _walk(c)
        for i in range(w.tree.topLevelItemCount()):
            _walk(w.tree.topLevelItem(i))
        ck("AR 信号带 ● 且染成紫 #8957e5", any(c.lower() == "#8957e5" for c in _colors), _colors[:3])
        ck("未分类带 ○ (白圈)", len(_plain) >= 1, _plain[:2])
        # 排序: 选 🟣 AR ⇒ AR 项秩 0, 未分类项秩 1
        w._set_scene_sort("AR场景")
        ck("AR 置顶(秩0) / 未分类(秩1)",
           w._scene_rank("ar.光学质量检测.判决") == 0 and w._scene_rank("sstrace.光模块头到孔_mm") == 1)
        ck("标题行给出 当前场景 + 各色计数", "计数" in (w._scene_lab.text() or ""), w._scene_lab.text()[:90])
        w._set_scene_sort("")
        ck("切回 全部(白) = 不排序(都秩 0)", w._scene_rank("sstrace.光模块头到孔_mm") == 0)
        w.close()
    except Exception as e:                                                        # noqa: BLE001
        import traceback
        ck("信号分析页真起并标记", False, "%s: %s" % (type(e).__name__, e))
        traceback.print_exc()

    print("\n=== 汇总: PASS %d · FAIL %d · SKIP %d ===" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("❌ 不通过: %s" % ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
