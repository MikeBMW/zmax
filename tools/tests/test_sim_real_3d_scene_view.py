#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sim&Real 页 · 3D 可编辑场景视图 回归判据 (老倪 2026-10-10)

老倪: 「在哪呢仿真场景？删掉 Sim&Real 的功能积木部分，我要上下料的可编辑窗口，3D 渲染的场景，类似 dreamview 的 3D 场景」

判据 (每条真跑真读, 不 mock):
  1. 功能积木已从 Sim&Real 页删除 (studio.py 里 brick 相关代码 0 处; 页内不再有该面板)
  2. Sim&Real 页真建起来 (PluggingSceneModule, offscreen) 且第一块就是 3D 场景视图卡
  3. 3D 视图真渲染出像素 (非背景像素 > 8000; 对象青绿 / 轨迹蓝 都 > 300)
  4. 场景下拉含 SCN-07-UP (上下料); 数据源 = 场景真源 (6 对象/4 标记/1 围栏/2 轨迹)
  5. 拖动写回真落盘 (scene_edit 备份+回读) 且**在役场景 sha 不变**; 测完自动还原
  6. 在役场景选择时写操作被拒 (只读预览保护)

用法: QT_QPA_PLATFORM=offscreen python3 tools/tests/test_sim_real_3d_scene_view.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
FAIL = []
SID = "SCN-07-UP"
SDIR = os.path.join(ROOT, "data", "scene", "scenes", SID)


def check(cond, msg):
    print(("  ✅ " if cond else "  ⛔ ") + msg)
    if not cond:
        FAIL.append(msg)
    return cond


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    from PyQt5.QtWidgets import QApplication, QGroupBox                            # noqa: PLC0415
    app = QApplication.instance() or QApplication(sys.argv)
    import updown_scene_view as U                                                   # noqa: PLC0415
    from PIL import Image                                                           # noqa: PLC0415

    print("1) 功能积木已删除")
    src = open(os.path.join(ROOT, "tools", "gui", "studio.py"), encoding="utf-8").read()
    seg = src[src.find("class PluggingSceneModule"):]
    seg = seg[:seg.find("def _build_l2_tab")]
    check("brick" not in seg.lower(), "Sim&Real 页段内 brick 相关代码 0 处")
    check("功能积木" not in seg, "页段内无「功能积木」字样")
    check("brick" not in src.lower(), "全 studio.py 无 brick 残留 (定义也删了)")

    print("2) Sim&Real 页真建 + 3D 视图卡置顶")
    check("updown_scene_view" in seg and "_upv_build" in seg, "页内已挂 updown_scene_view.build_card")
    check(seg.find("_upv_build") < seg.find("_sr_build"), "3D 场景视图卡在表格编辑器之前 (置顶)")
    try:
        import studio                                                              # noqa: PLC0415
        page = studio.PluggingSceneModule()
        page.resize(1200, 900)
        page.show()
        app.processEvents()
        cards = [g for g in page.findChildren(QGroupBox) if "3D" in (g.title() or "")]
        check(len(cards) >= 1, "页内找到 3D 视图卡: %s" % [c.title() for c in cards][:2])
        view = getattr(cards[0], "view", None) if cards else None
        check(view is not None, "卡片里有 SceneView3D 实例")
    except Exception as e:                                                          # noqa: BLE001
        check(False, "页面构建失败: %r" % (e,))
        view = None

    print("3) 3D 真渲染像素")
    if view is not None:
        view.resize(900, 470)
        app.processEvents()
        view.repaint()
        app.processEvents()
        out = "/tmp/upv_page_view.png"
        view.grab().save(out)
        im = Image.open(out).convert("RGB")
        px = list(im.getdata())
        nonbg = sum(1 for p in px if not (abs(p[0] - 11) < 8 and abs(p[1] - 15) < 8 and abs(p[2] - 20) < 8))
        teal = sum(1 for p in px if p[1] > 140 and p[0] < 120 and p[2] > 90)
        blue = sum(1 for p in px if p[2] > 180 and p[0] < 110)
        check(nonbg > 8000, "非背景像素 %d (>8000)" % nonbg)
        check(teal > 300, "对象盒青绿像素 %d (>300)" % teal)
        check(blue > 300, "轨迹蓝像素 %d (>300)" % blue)
        print("     取证图: %s" % out)

    print("4) 场景下拉与数据源")
    opts = U.scene_options()
    labels = [o[0] for o in opts]
    check(any(SID in x for x in labels), "下拉含 %s: %s" % (SID, labels))
    d = U.load_scene(SDIR)
    check(len(d["objects"]) == 6 and len(d["markers"]) == 4 and len(d["fences"]) == 1 and len(d["trajectories"]) == 2,
          "场景真源 6 对象/4 标记/1 围栏/2 轨迹")
    check("上下料" in str((d.get("meta") or {}).get("name")), "场景名 = %s" % (d.get("meta") or {}).get("name"))

    print("5) 拖动写回真落盘 + 在役场景零影响")
    parent_o = os.path.join(ROOT, "data", "scene", "objects3d.json")
    parent_v = os.path.join(ROOT, "data", "scene", "overlay_spec.json")
    s_o = sha(parent_o)
    # ⚠️ overlay_spec.json 有**实时发布器**在刷 (ts/updated_at 每轮变, 且它只写 deleted/scene),
    #    所以不能比文件 sha ⇒ 比语义内容 (去掉易变字段)。
    #    l5live 是"当前取帧状态"(自带 ts, 每轮刷新) ⇒ 也属易变, 一并排除。
    _vol = ("ts", "updated_at", "l5live")

    def _sem(p):
        d = json.load(open(p, encoding="utf-8"))
        for k in _vol:
            d.pop(k, None)
        return json.dumps(d, ensure_ascii=False, sort_keys=True)

    s_v = _sem(parent_v)
    v = U.SceneView3D(SDIR, SID, status_cb=lambda s: None)
    o0 = [float(x) for x in v.data["objects"][0]["center"]]
    v.sel = 0
    ok = v._write({"center": [round(o0[0] + 0.02, 5), o0[1], o0[2]]}, "回归测试平移")
    now = [float(x) for x in U.load_scene(SDIR)["objects"][0]["center"]]
    check(ok and abs(now[0] - (o0[0] + 0.02)) < 1e-6, "写回生效: %s → %s" % (o0, now))
    baks = [f for f in os.listdir(SDIR) if ".bak_edit_" in f]
    check(len(baks) >= 1, "写前有备份 (%d 个)" % len(baks))
    check(sha(parent_o) == s_o, "在役场景 objects3d.json sha 未变")
    check(_sem(parent_v) == s_v, "在役场景 overlay_spec 语义内容未变 (忽略发布器刷新的 ts/updated_at)")
    v.sel = 0
    v._write({"center": o0}, "回归测试还原")
    back = [float(x) for x in U.load_scene(SDIR)["objects"][0]["center"]]
    check(abs(back[0] - o0[0]) < 1e-6, "已还原 %s" % back)
    for f in baks:
        try:
            os.remove(os.path.join(SDIR, f))
        except OSError:
            pass

    print("6) 在役场景只读保护")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "scene_edit.py"), "--scenes"],
                       cwd=ROOT, capture_output=True, text=True)
    check("SCN-07-UP" in r.stdout, "scene_edit --scenes 列出上下料场景")
    v2 = U.SceneView3D(os.path.join(ROOT, "data", "scene"), None, status_cb=lambda s: None)
    v2.sel = 0 if v2.data["objects"] else None
    if v2.sel is not None:
        before = sha(parent_o)
        v2._write({"center": [0.5, 0.5, 0.2]}, "在役写测试")
        check(sha(parent_o) == before, "在役场景写被拒 ⇒ sha 未变")

    print("═" * 70)
    print(("⛔ 失败 %d 项: %s" % (len(FAIL), FAIL)) if FAIL else "✅ 全部通过")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
