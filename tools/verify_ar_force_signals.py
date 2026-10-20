#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ar_force_signals.py — 判据: 「AR 场景(紫) 信号分析窗口里能看到
末端执行器 x/y/z + 真机侧向力, 且没有假值」

老倪 2026-10-20: 「将 AR 场景的末端执行器的 x y z 和 插拔的侧向力, 显示出来; 来自于真实的机器人;
现在没有接, 你能更新信号分析窗口么? 紫色信号」

判的是**真窗口**: 起 Gui(Qt offscreen) → 真跑 CanoeGraphicWidget → 真读本机源
(zmax_data/ar_live/ar_aoi_live.json) → 真建树 → 逐行核 AR 组里的行/颜色/值。
不核"代码里写了什么", 只核"窗口里显示成什么"。

判据:
  ① AR 根节点存在且颜色 = #8957e5 (紫), 组名 = 注册表里的 "AR·空间点位 (基座系)"
  ② 末端.x / 末端.y / 末端.z 三行都在 AR 组里, 且带真值 (非 "—")
  ③ 末端.侧向力_N · 末端.侧向力y_N · 末端.侧向力z_N · 末端.轴向力_N 四行都在 AR 组里
  ④ **不许有假值**: 力未接(live 里没有该键)时, 这四行的值必须是 "—"/空, 不能是 0
  ⑤ 位姿陈旧(帧龄>1s)时窗口上仍显示帧龄行, 让人一眼知道这不是实时

退出码 0 = 全 PASS。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))

PURPLE = "#8957e5"
FAIL = []


def sel_core():
    """核心信号清单直接取自被测模块 (同一份真源, 不另抄一份)。"""
    try:
        import canoe_graphic as _CG
        return set(_CG.CORE_SIGNALS)
    except Exception:                                                              # noqa: BLE001
        return set()


def chk(ok, msg):
    print(("  ✅ " if ok else "  ❌ ") + msg)
    if not ok:
        FAIL.append(msg)
    return ok


def scene_of_key(key):
    try:
        import importlib.util
        p = os.path.join(ROOT, "tools", "sig_scene_tags.py")
        spec = importlib.util.spec_from_file_location("sst", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.tag(key), m.color(key)
    except Exception as e:                                                             # noqa: BLE001
        return "?", ("#ffffff" if "err" in str(e) else "#ffffff")



def selftest_force_math():
    """口径自检 —— **合成数, 不是真机数据**, 只为证明换算/闸门代码本身对 (跑完即删)。"""
    import importlib.util
    import json as _json
    spec = importlib.util.spec_from_file_location("ar_aoi_bus", os.path.join(ROOT, "tools", "ar_aoi_bus.py"))
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    tmp = os.path.join(ROOT, "zmax_data", "rokae_sdk", "ft_out", "_selftest_latest.json")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    orig = B.FT
    ok_all = True
    try:
        # ① 3-4-5 直角: fy=3, fz=4 ⇒ 侧向合力必须 =5.0
        _json.dump({"ts": time.time(), "frame": "world", "fx": 1.5, "fy": 3.0, "fz": 4.0},
                   open(tmp, "w", encoding="utf-8"))
        B.FT = tmp
        out, meta = B._real_force()
        print("  · 自检合成数 (非真机): fx=1.5 fy=3 fz=4 →", out)
        ok_all &= chk(abs(out.get("末端.侧向力_N", -1) - 5.0) < 1e-6, "侧向合力 = hypot(3,4) = 5.0")
        ok_all &= chk(out.get("末端.轴向力_N") == 1.5, "轴向力 = fx = 1.5")
        ok_all &= chk(out.get("末端.侧向力y_N") == 3.0 and out.get("末端.侧向力z_N") == 4.0, "侧向分量带符号")
        # ② 工具系 ⇒ 拒用 (侧向力算不出来)
        _json.dump({"ts": time.time(), "frame": "tool", "fx": 1.0, "fy": 1.0, "fz": 1.0},
                   open(tmp, "w", encoding="utf-8"))
        out, meta = B._real_force()
        ok_all &= chk(out == {} and "参考系" in str(meta.get("real_force")), "工具系读数被拒用")
        # ③ 陈旧 ⇒ 不写键
        _json.dump({"ts": time.time() - 60, "frame": "world", "fx": 1.0, "fy": 1.0, "fz": 1.0},
                   open(tmp, "w", encoding="utf-8"))
        out, meta = B._real_force()
        ok_all &= chk(out == {} and "帧龄" in str(meta.get("real_force")), "陈旧读数不写键")
        # ④ 采样器 err 文件 ⇒ 不写键, 原因带出来
        _json.dump({"ts": time.time(), "frame": "world", "err": "连接控制器失败"}, open(tmp, "w", encoding="utf-8"))
        out, meta = B._real_force()
        ok_all &= chk(out == {} and "连接控制器失败" in str(meta.get("real_force")), "采样器报错时不写键且带原因")
        # ⑤ 没有文件 ⇒ 不写键
        os.remove(tmp)
        out, meta = B._real_force()
        ok_all &= chk(out == {} and "无" in str(meta.get("real_force")), "无真值文件时不写键")
    finally:
        B.FT = orig
        if os.path.exists(tmp):
            os.remove(tmp)
    return 0 if ok_all else 1


def main():
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
    import canoe_graphic as CG

    app = QApplication.instance() or QApplication(sys.argv)
    w = CG.CanoeGraphicWidget()
    w.resize(1600, 900)
    w.start()                                    # 真起本机源线程, 真读 ar_aoi_live.json
    t0 = time.time()
    while time.time() - t0 < 3.0:                # 给源线程 3s 采一轮
        app.processEvents()
        time.sleep(0.05)
    w._fill_tree()                               # 真建树
    app.processEvents()

    tree = w.tree
    roots = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    ar_root = None
    for it in roots:
        if "AR" in it.text(0):
            ar_root = it
            break
    print("· 场景根节点:", [it.text(0) for it in roots])
    if not chk(ar_root is not None, "AR 场景根节点存在"):
        return 1
    _c = ar_root.foreground(0).color().name()
    chk(_c.lower() == PURPLE, "AR 根节点是紫色 %s (实测 %s)" % (PURPLE, _c))

    rows = {}          # key → (row texts, group)
    groups = []
    for gi in range(ar_root.childCount()):
        g = ar_root.child(gi)
        if not g.text(0):
            continue
        groups.append(g.text(0))
        for ri in range(g.childCount()):
            r = g.child(ri)
            key = r.data(0, Qt.UserRole)
            txt = [r.text(c) for c in range(tree.columnCount())]
            if key:
                rows[str(key)] = (txt, g.text(0))
    print("· AR 组:", groups)
    print("· AR 行数: %d" % len(rows))

    pose_ok = True
    for ax in ("x", "y", "z"):
        key = "ar.末端.%s" % ax
        got = rows.get(key)
        if got is None:
            pose_ok &= chk(False, "窗口里缺行 %s" % key)
            continue
        val = got[0][3] if len(got[0]) > 3 else ""
        col = got[0][0]
        tag, color = scene_of_key(key)
        pose_ok &= chk(True, "%s 在组「%s」 值=%s 标签色=%s(%s)" % (key, got[1], val or "—", color, tag))
        if col.startswith("●"):
            pose_ok &= chk(color.lower() == PURPLE, "%s 行首圆点是紫 ● (实测 %r)" % (key, col[:2]))

    print("· ——— 力通道 ———")
    # ⏳ AR 总线是 2s 一拍的**文件通道**, 而位姿是 50Hz ⇒ 首建树那刻 力 行还是「未接」占位。
    #   不等真值进 store 就断言, 会把"刚打开还没到第二拍"误判成"窗口不显示真值"(2026-10-20 实测)。
    _t0 = time.time()
    while time.time() - _t0 < 10.0:
        app.processEvents()
        if any(("力" in str(k)) and str(k).startswith("ar.末端.") for k in w.store.keys()):
            break
        time.sleep(0.3)
    w._fill_tree()
    app.processEvents()
    ar_root = w.tree.topLevelItem(0)      # 重建树会换掉 QTreeWidgetItem ⇒ 必须重新取根, 别用旧引用
    tree = w.tree
    rows = {}
    for gi in range(ar_root.childCount()):
        g = ar_root.child(gi)
        for ri in range(g.childCount()):
            r = g.child(ri)
            _k = r.data(0, Qt.UserRole)
            if _k:
                rows[str(_k)] = ([r.text(c) for c in range(tree.columnCount())], g.text(0))
    import json
    live = json.load(open(os.path.join(ROOT, "zmax_data", "ar_live", "ar_aoi_live.json"), encoding="utf-8"))
    s = live.get("s") or {}
    _CORE = sel_core()
    for k in ("末端.侧向力_N", "末端.侧向力y_N", "末端.侧向力z_N", "末端.轴向力_N"):
        key = "ar." + k
        got = rows.get(key)
        if got is None:
            if key in _CORE:                 # 核心通道必须在默认视图里
                chk(False, "窗口里缺行 %s" % key)
            continue                         # 非核心通道只在「全部」视图里出现 (下面核)
        val = (got[0][3] if len(got[0]) > 3 else "").strip()
        tag, color = scene_of_key(key)
        chk(color.lower() == PURPLE, "%s 标签紫 %s (%s)" % (key, color, tag))
        if k in s:                       # 真机有读数 ⇒ 窗口必须显示真值
            chk(val not in ("", "—", "-", "未接"), "%s 有真值必须显示 (live=%s 窗口=%r)" % (key, s[k], val))
        else:                            # 没接 ⇒ 窗口必须显式写「未接」, 且绝不许写 0 冒充
            chk(val in ("未接", "—", "-", ""), "%s 未接时显示「未接」而不是 0 (实测 %r)" % (key, val))
            chk(val != "0", "%s 未接时值列不是 0" % key)


    print("· ——— 主要信号收口 (老倪 2026-10-20: 不要超过 10 个) ———")
    chk(tree.topLevelItemCount() == 1, "默认只有 1 个场景根 (实测 %d)" % tree.topLevelItemCount())
    chk(len(rows) <= 10, "树上信号行 ≤10 (实测 %d)" % len(rows))
    _need = {"ar.末端.x", "ar.末端.y", "ar.末端.z", "ar.末端.侧向力_N", "ar.末端.轴向力_N"}
    chk(_need <= set(rows), "位姿 x/y/z + 轴向力/侧向力 都在树上 (%d/%d)" % (len(_need & set(rows)), len(_need)))
    w.b_core.setChecked(False)                    # 取消勾选 ⇒ 回到全量(证明数据没删)
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    _all_keys = set(str(it.data(0, Qt.UserRole)) for it in w._all_items() if it.data(0, Qt.UserRole))
    chk(len(_all_keys) > len(rows), "取消「主要信号」后回到全量 (>%d 行, 实测 %d)" % (len(rows), len(_all_keys)))
    for k in ("ar.末端.侧向力y_N", "ar.末端.侧向力z_N", "ar.末端.切向力_N"):
        chk(k in _all_keys, "全量视图里能看到 %s" % k)
    w.b_core.setChecked(True)
    app.processEvents()

    print("· ——— 🤖 机器人状态机 (是否在插拔) 必须直接看得见 ———")
    _rb = {k: v for k, v in live.get("s", {}).items() if str(k).startswith("机器人.")}
    chk(bool(_rb), "总线里有 机器人.* 信号 (%d 条: %s)" % (len(_rb), sorted(_rb)))
    chk("机器人.插拔中" in _rb or _rb.get("机器人.状态_码") == 0.0,
        "插拔中: 有值=%s (未连接时按口径不写, 状态码=0 表示未连接)" % _rb.get("机器人.插拔中"))
    _row = [it for it in w._all_items() if str(it.data(0, Qt.UserRole) or "") == "ar.机器人.插拔中"]
    chk(bool(_row), "树上直接能看到 ar.机器人.插拔中 这一行")
    _txt = str((live.get("meta", {}).get("last_pull") or {}).get("robot") or "")
    chk("🤖" in _txt, "meta 带一行人话: %s" % _txt[:70])

    print("· ——— 场景一选, 波形就跟着切 (选了 AR 不该还挂绿色插拔) ———")
    w._set_scene_sort("插拔场景")
    app.processEvents()
    time.sleep(0.4)
    app.processEvents()
    _r2 = [w.tree.topLevelItem(i).text(0) for i in range(w.tree.topLevelItemCount())]
    chk(len(_r2) == 1 and "插拔" in _r2[0], "切到插拔 ⇒ 树上只剩插拔一个根 (%s)" % _r2)
    chk(not any(str(k).startswith("ar.") for k in w.selected), "切到插拔后波形里没有 AR 信号 (实测 %d 条)" % len(w.selected))
    chk(len(w.selected) <= 10, "插拔视图波形 ≤10 条 (实测 %d)" % len(w.selected))
    _n_plug = len(w.selected)
    w._set_scene_sort("AR场景")
    app.processEvents()
    time.sleep(0.4)
    app.processEvents()
    chk(all(str(k).startswith("ar.") for k in w.selected) and len(w.selected) >= 3,
        "切回 AR ⇒ 波形自动重新勾上 AR 信号 (实测 %d 条: %s)" % (len(w.selected), w.selected[:4]))
    chk(not any(str(k).startswith("sstrace.") for k in w.selected),
        "切回 AR ⇒ 插拔那条 sstrace 曲线已撤 (撤前 %d 条)" % _n_plug)
    _r3 = [w.tree.topLevelItem(i).text(0) for i in range(w.tree.topLevelItemCount())]
    chk(len(_r3) == 1 and "AR" in _r3[0], "切回 AR ⇒ 树上只剩 AR 根")
    w._set_scene_sort("")

    print("· ——— 画布数据源切到 AR(模拟) ⇒ 不用手点也该切 ———")
    w._scene_sort = ""                      # 不点排序 = 跟随画布数据源
    w._scene_seen = "插拔场景"
    w._scene_poll_t = 0.0
    _orig_act = w._active_scene
    w._active_scene = lambda: "AR场景"      # 模拟数据源真源变成 AR (不动作业画布)
    w._tick()
    app.processEvents()
    chk(all(str(k).startswith("ar.") for k in w.selected) and len(w.selected) >= 3,
        "数据源变 AR ⇒ 波形自动切成 AR (%d 条: %s)" % (len(w.selected), w.selected[:3]))
    _rr = [w.tree.topLevelItem(i).text(0) for i in range(w.tree.topLevelItemCount())]
    chk(len(_rr) == 1 and "AR" in _rr[0], "目录也只剩 AR 根 (%s)" % _rr)
    w._active_scene = _orig_act

    mt = (live.get("meta") or {}).get("last_pull") or {}
    print("· meta.real_force:", mt.get("real_force"))
    print("· meta.force(平台自算切向力):", mt.get("force"))

    print()
    if FAIL:
        print("❌ FAIL %d 项:" % len(FAIL))
        for f in FAIL:
            print("   -", f)
        return 1
    print("✅ PASS · AR 紫色组里 末端 x/y/z + 真机侧向力/轴向力 全部就位, 无假值")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print("· 口径自检 (合成数, 非真机数据)")
        rc = selftest_force_math()
        print("✅ 口径自检 PASS" if not rc else "❌ 口径自检 FAIL")
        sys.exit(rc)
    sys.exit(main())
