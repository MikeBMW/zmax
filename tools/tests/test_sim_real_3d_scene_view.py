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
    seg = seg[:seg.find("\nclass ", 10) + 1]        # 页类整段 (L2/L3/L4 已删除)
    check("brick" not in seg.lower(), "Sim&Real 页段内 brick 相关代码 0 处")
    check("功能积木" not in seg, "页段内无「功能积木」字样")
    check("brick" not in src.lower(), "全 studio.py 无 brick 残留 (定义也删了)")

    print("2) Sim&Real 页真建 + 3D 视图卡置顶")
    check("updown_scene_view" in seg and "_upv_build" in seg, "页内已挂 updown_scene_view.build_card")
    print("2b) L2/L3/L4 页签已删除 + 3D 视图占满")
    for k in ("scene_tabs", "_build_l2_tab", "_build_l3_tab", "_build_l4_tab", "_make_step_card"):
        check(k not in src, "studio.py 无 %s 残留" % k)
    check("bl.addWidget(_upv_build(self), 1)" in seg, "3D 卡以 stretch=1 占满剩余高度")
    uvs = open(os.path.join(ROOT, "tools", "gui", "updown_scene_view.py"), encoding="utf-8").read()
    check("setMinimumHeight(560)" in uvs, "3D 视图最小高度 560")
    check("def fit_view" in uvs and "resizeEvent" in uvs, "自适应取景 + 尺寸变化自动重取景")
    check("_sr_build" not in seg and "from sim_real_page import" not in seg,
          "只挂一个场景编辑器 (旧表格编辑器 build_body 已摘除)")
    check("QSplitter" in open(os.path.join(ROOT, "tools", "gui", "updown_scene_view.py"),
                              encoding="utf-8").read(), "视图/元素面板之间有 QSplitter (拖分隔条放大)")
    _uv = open(os.path.join(ROOT, "tools", "gui", "updown_scene_view.py"), encoding="utf-8").read()
    check("视图全屏" in _uv and "setHandleWidth" in _uv, "有「⛶ 视图全屏」+ 可拖分隔条 (handleWidth)")
    check("场景变体" not in open(os.path.join(ROOT, "tools", "gui", "sim_real_page.py"),
                              encoding="utf-8").read().split("老倪")[0], "「🎬 场景变体 / 🗺 建图资产」统计行已删除")
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
        # 自适应取景判据: 画面内容要铺开 (横向跨度占视口 >45%), 不能缩成一小撮
        xs = [i % im.size[0] for i, p in enumerate(px)
              if not (abs(p[0] - 11) < 8 and abs(p[1] - 15) < 8 and abs(p[2] - 20) < 8)]
        span = (max(xs) - min(xs)) / float(im.size[0]) if xs else 0.0
        check(span > 0.45, "自适应取景: 画面横向跨度占视口 %.0f%% (>45%%)" % (span * 100))
        check(teal > 300, "对象盒青绿像素 %d (>300)" % teal)
        check(blue > 300, "轨迹蓝像素 %d (>300)" % blue)
        print("     取证图: %s" % out)

    print("4) 场景下拉与数据源")
    opts = U.scene_options()
    labels = [o[0] for o in opts]
    # 老倪 2026-10-10 收敛: 下拉只两条 (标签改中文, sid 在 itemData 里)
    check([o[2] for o in opts] == ["SIM-PEG-L4", SID], "下拉 = 插拔场景 + 上下料场景: %s" % labels)
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
    v._set_sel({"kind": "objects", "i": 0, "wp": None})
    ok = v._write({"center": [round(o0[0] + 0.02, 5), o0[1], o0[2]]}, "回归测试平移")
    now = [float(x) for x in U.load_scene(SDIR)["objects"][0]["center"]]
    check(ok and abs(now[0] - (o0[0] + 0.02)) < 1e-6, "写回生效: %s → %s" % (o0, now))
    baks = [f for f in os.listdir(SDIR) if ".bak_edit_" in f]
    check(len(baks) >= 1, "写前有备份 (%d 个)" % len(baks))
    check(sha(parent_o) == s_o, "在役场景 objects3d.json sha 未变")
    check(_sem(parent_v) == s_v, "在役场景 overlay_spec 语义内容未变 (忽略发布器刷新的 ts/updated_at)")
    v._set_sel({"kind": "objects", "i": 0, "wp": None})
    v._write({"center": o0}, "回归测试还原")
    back = [float(x) for x in U.load_scene(SDIR)["objects"][0]["center"]]
    check(abs(back[0] - o0[0]) < 1e-6, "已还原 %s" % back)
    for f in baks:
        try:
            os.remove(os.path.join(SDIR, f))
        except OSError:
            pass

    print("7) 多场景库 + 四类元素都能选/改 (位置·轨迹)")
    opts = U.scene_options()
    ids = [o[2] for o in opts]
    check(len([i for i in ids if i]) == 2, "场景库露脸 %d 条 (插拔 + 上下料)" % len([i for i in ids if i]))
    check(ids == ["SIM-PEG-L4", "SCN-07-UP"], "下拉 = 插拔场景 + 上下料场景 (老倪 2026-10-10 收敛): %s" % ids)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "scene_registry.py"), "--check"],
                       cwd=ROOT, capture_output=True, text=True)
    check(r.returncode == 0, "scene_registry --check 全绿 (%s)" % (r.stdout or "").strip().splitlines()[-1][:60])
    sv = U.SceneView3D(SDIR, SID, status_cb=lambda s: None)
    # ① 四类元素各自可命中 (模拟点选)
    hitn = {}
    for k in U.KINDS:
        sv.kind_filter = k
        for i, it in enumerate(sv.data.get(k) or []):
            a = U.anchor_of(it, k) if k != "trajectories" else next(
                ([float(x) for x in w] for w in (it.get("waypoints") or []) if isinstance(w, list) and len(w) == 3), None)
            if not a:
                continue
            q, _ = sv._proj(a)
            from PyQt5.QtCore import QPoint
            h = sv._hit(QPoint(int(q.x()), int(q.y())))
            if h and h["kind"] == k:
                hitn[k] = i
                break
    check(set(hitn) == set(U.KINDS), "四类元素都能在 3D 里点中: %s" % hitn)
    # ② 四类元素各自真写回 + 还原 (标记/围栏/轨迹 = 老倪要的"位置、轨迹")
    from PyQt5.QtCore import QPoint  # noqa: F401
    for k, key in (("markers", "pos"), ("fences", "shape"), ("trajectories", "waypoints")):
        lst = sv.data.get(k) or []
        if not lst:
            check(False, "%s 场景里没有可测元素" % k)
            continue
        i = hitn.get(k, 0)
        sv.kind_filter = k
        it = lst[i]
        if k == "trajectories":
            wp = 0
            base = [float(x) for x in it["waypoints"][wp]]
            sv._set_sel({"kind": k, "i": i, "wp": wp})
            patch = U.move_patch(it, k, [base[0] + 0.02, base[1], base[2]], wp)
            ok = sv._write(patch, "回归 轨迹航点", k)
            now = [float(x) for x in U.load_scene(SDIR)[k][i]["waypoints"][wp]]
            check(ok and abs(now[0] - (base[0] + 0.02)) < 1e-6, "轨迹航点写回 %s → %s" % (base, now))
            sv._set_sel({"kind": k, "i": i, "wp": wp})
            sv._write(U.move_patch(it, k, base, wp), "回归 轨迹还原", k)
        else:
            a = U.anchor_of(it, k)
            sv._set_sel({"kind": k, "i": i, "wp": None})
            patch = U.move_patch(it, k, [a[0] + 0.02, a[1], a[2]])
            ok = sv._write(patch, "回归 %s 平移" % k, k)
            now = U.anchor_of(U.load_scene(SDIR)[k][i], k)
            check(ok and abs(now[0] - (a[0] + 0.02)) < 1e-6, "%s 写回 %s → %s" % (U.KIND_CN[k], a, now))
            sv._set_sel({"kind": k, "i": i, "wp": None})
            sv._write(U.move_patch(it, k, a), "回归 %s 还原" % k, k)
        back = (U.anchor_of(U.load_scene(SDIR)[k][i], k) if k != "trajectories"
                else [float(x) for x in U.load_scene(SDIR)[k][i]["waypoints"][wp]])
        check(abs(back[0] - (base[0] if k == "trajectories" else a[0])) < 1e-6, "%s 已还原 %s" % (U.KIND_CN[k], back))
    for f in [x for x in os.listdir(SDIR) if ".bak_edit_" in x]:
        try:
            os.remove(os.path.join(SDIR, f))
        except OSError:
            pass

    print("8) 仿真场景 (画布 3D 视图的插拔光模块) 进场景管理: 可选 / 可编辑 / 可运行")
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import sim_scene_def as SSD
    opts = U.scene_options()
    sim = [o for o in opts if o[2] == "SIM-PEG-L4"]
    check(bool(sim), "场景下拉含仿真场景 SIM-PEG-L4: %s" % [o[0][:40] for o in sim][:1])
    check(bool(sim and sim[0][3]), "带运行元数据: %s" % (sim[0][3] if sim else None))
    SIMDIR = os.path.join(ROOT, "data", "scene", "scenes", "SIM-PEG-L4")
    truth = SSD.load()["scenes"]["SIM-PEG-L4"]["objects"]
    ondisk = U.load_scene(SIMDIR, "SIM-PEG-L4")["objects"]
    same = all(any(d["name"] == o["name"] and [round(float(x), 4) for x in d["center"]] == [round(float(x), 4) for x in o["center"]]
                   for d in ondisk) for o in truth)
    check(same and len(ondisk) == len(truth), "3D 视图读到的几何 == 仿真真源 (%d 对象)" % len(ondisk))
    check(SSD.check() == 0, "真源 ↔ 两个生成器 ↔ XML 注入 四处一致 (改一处不同步会报错)")
    # 可编辑: 改真源 ⇒ 目录同步 + 生成器仍一致 (编辑真生效, 不是只改产物)
    _tt = [o for o in truth if "geom=tt_disc" in str(o.get("source", ""))][0]
    _old = list(_tt["center"])
    _nm = _tt["name"]
    r = SSD.apply_patch("objects", _nm, {"center": [_old[0] + 0.01, _old[1], _old[2]]})
    _now = [o for o in U.load_scene(SIMDIR, "SIM-PEG-L4")["objects"] if o["name"] == _nm][0]["center"]
    check(r.get("ok") and abs(_now[0] - (_old[0] + 0.01)) < 1e-6, "编辑落真源 + 目录同步: %s (%s)" % (_now, _nm))
    _rc = SSD.check()
    SSD.apply_patch("objects", _nm, {"center": _old})
    check(_rc == 0, "编辑后 真源/生成器/XML 仍一致 (rc=%s)" % _rc)
    check(all(abs(a - b) < 1e-6 for a, b in zip(
        [o for o in U.load_scene(SIMDIR, "SIM-PEG-L4")["objects"] if o["name"] == _nm][0]["center"], _old)),
        "已还原 %s (%s)" % (_old, _nm))
    # 可运行: 入口存在 + 真能被调用
    tool, args, eta, prod, cwd, renv = SSD.run_cmd()
    check(os.path.exists(os.path.join(ROOT, tool)), "运行入口存在: %s %s (约 %ss)" % (tool, args, eta))
    # 必须与画布 L4 档同一条调用: cwd=tools + MUJOCO_GL=egl (+ EGL device 0), 否则 headless 渲染起不来
    check(cwd.rstrip("/").endswith("/tools"), "运行 cwd 与画布一致 (=tools): %s" % cwd)
    check(renv.get("MUJOCO_GL") == "egl" and renv.get("MUJOCO_EGL_DEVICE") == "0",
          "运行 env 与画布一致: %s" % renv)
    hr = subprocess.run([sys.executable, os.path.join(ROOT, tool), "--help"], cwd=cwd,
                        capture_output=True, text=True, timeout=240)
    check(hr.returncode == 0 and "--seed" in hr.stdout, "入口真可调用 (--help rc=%s)" % hr.returncode)
    uvs = open(os.path.join(ROOT, "tools", "gui", "updown_scene_view.py"), encoding="utf-8").read()
    check("▶ 运行仿真" in uvs and "class RunThread" in uvs and "产物" in uvs,
          "页内有「▶ 运行仿真」+ 后台线程 + 跑完报产物/时间")
    card2 = U.build_card(None)
    cmb2 = card2.findChildren(type(card2.view).__mro__[0]) or []
    from PyQt5.QtWidgets import QComboBox as _QCB, QPushButton as _QPB
    cb = card2.findChildren(_QCB)[0]
    si = next((i for i in range(cb.count()) if (cb.itemData(i) or {}).get("sid") == "SIM-PEG-L4"), None)
    check(si is not None, "页内下拉能定位到仿真场景 (index=%s)" % si)
    if si is not None:
        cb.setCurrentIndex(si)
        app.processEvents()
        check(len(card2.view.data["objects"]) == len(truth), "切到仿真场景后视图载入 %d 对象" % len(card2.view.data["objects"]))
        br = [b for b in card2.findChildren(_QPB) if "运行仿真" in b.text()]
        check(bool(br) and br[0].isEnabled(), "「▶ 运行仿真」按钮已启用")

    print("9) 场景清单收敛 + 插拔场景几何对齐 metaworld 真模型")
    _opts = U.scene_options()
    _sids = [o[2] for o in _opts]
    check(_sids == ["SIM-PEG-L4", "SCN-07-UP"], "下拉只有两条: 插拔场景 + 上下料场景 → %s" % _sids)
    check(all(("插拔场景" in _opts[0][0]) and ("上下料场景" in _opts[1][0]) for _ in [0]),
          "中文名: %s | %s" % (_opts[0][0][:22], _opts[1][0][:22]))
    _r1 = SSD.export_mujoco_truth("SIM-PEG-L4", write=False)
    _r2 = SSD.export_mujoco_truth("SIM-PEG-L4", write=False)
    check(_r1.get("ok") and len(_r1["objects"]) >= 20,
          "从 MuJoCo 真模型导出几何: %s" % _r1.get("msg"))
    _k = lambda r: [(o["name"], tuple(o["center"]), tuple(o["size"])) for o in r["objects"]]
    check(_k(_r1) == _k(_r2), "导出幂等 (两次逐字一致, %d 对象)" % len(_r1["objects"]))
    _disk = SSD.load()["scenes"]["SIM-PEG-L4"]["objects"]
    check(len(_disk) == len(_r1["objects"]) and
          all(any(o["name"] == d["name"] and [round(float(v), 4) for v in o["center"]] == d["center"]
                  for d in _disk) for o in _r1["objects"]),
          "真源几何 == MuJoCo 模型实测 (逐字, %d 对象)" % len(_disk))
    _tbl = [o for o in _r1["objects"] if o["name"] == "工作台面"]
    check(bool(_tbl) and _tbl[0]["size"] == [1.4, 0.8, 0.054],
          "台面真值 1.4×0.8×0.054 m (手写版曾误写 0.8×0.8) → %s" % (_tbl[0]["size"] if _tbl else None))
    _peg = [o for o in _r1["objects"] if o["name"] == "光模块 (peg)"]
    check(bool(_peg) and _peg[0]["size"] == [0.24, 0.016, 0.0398],
          "光模块真值 (侧插平放: 长 0.24 沿 x · 截面 0.04×0.016) → %s" % (_peg[0]["size"] if _peg else None))
    check(any(m["name"] == "site:hole" for m in _r1["markers"]),
          "孔口来自 MuJoCo site 真值: %s" % [m["name"] for m in _r1["markers"]])
    check(all("MuJoCo 模型实测" in o.get("source", "") for o in _disk), "每个对象都标出处 (MuJoCo 模型实测)")
    check(SSD.check() == 0, "真源判据 (含 MuJoCo 对齐) 全绿")
    # ⚠️ 类方法走 self.scene_id (曾写成闭包里的 view.scene_id → GUI 一拖就 NameError 崩, 实测崩过)
    _src = open(os.path.join(ROOT, "tools", "gui", "updown_scene_view.py"), encoding="utf-8").read()
    check("apply_patch(kind, str(_id), patch, scene_id=view.scene_id" not in _src,
          "类方法 (SceneView3D._write) 必须用 self.scene_id, 不许引用闭包名 view")
    _sv2 = U.SceneView3D(os.path.join(ROOT, "data", "scene", "scenes", "SIM-PEG-L4"), "SIM-PEG-L4",
                         status_cb=lambda s: None)
    _nm2 = _sv2.data["objects"][0]["name"]
    _c2 = list(_sv2.data["objects"][0]["center"])
    _ok2 = _sv2._write({"center": [_c2[0], _c2[1], _c2[2]]}, "判据直调拖动写路径", "objects", _nm2)
    check(_ok2 is not False, "类方法写路径真能跑 (不崩, 对象 %s): %s" % (_nm2, _ok2))
    _sv2.reload()

    print("6) 在役场景只读保护")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "scene_edit.py"), "--scenes"],
                       cwd=ROOT, capture_output=True, text=True)
    check("SCN-07-UP" in r.stdout, "scene_edit --scenes 列出上下料场景")
    v2 = U.SceneView3D(os.path.join(ROOT, "data", "scene"), None, status_cb=lambda s: None)
    v2._set_sel({"kind": "objects", "i": 0, "wp": None} if v2.data["objects"] else None)
    if v2.sel is not None:
        before = sha(parent_o)
        v2._write({"center": [0.5, 0.5, 0.2]}, "在役写测试")
        check(sha(parent_o) == before, "在役场景写被拒 ⇒ sha 未变")

    print("═" * 70)
    print(("⛔ 失败 %d 项: %s" % (len(FAIL), FAIL)) if FAIL else "✅ 全部通过")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
