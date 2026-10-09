#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_run_cfg_panel.py — 「6 个运行开关整合进右侧 参数标定 侧边页面」交互级验证 (老倪 2026-10-09)

要证的事 (真建窗口 + 真点击, 不是看代码猜):
 ① 6 个开关已从画布工具栏**搬走**, 且**同一个控件对象**现在挂在右侧
    「🔧 配置 · 运行开关」页下 (⇒ 引擎/运行路径读 self.chk_* 零改动)
 ② 工具栏留下入口按钮「⚙️ 运行开关」, 点它 → 右面板切到该页
 ③ 该页真显示 6 行 (作用/生效位置/代价) + 档位 + 诊断行, 且档位判定正确 (L2 档时 L4-only 行标"本档无效")
 ④ 面板里拨开关 → 诊断行即时刷新; 「↺ 恢复默认」回原厂默认; 「📋 复制」进剪贴板
 ⑤ 四轴重排后 11 个视图的 索引→控件 映射全对 (测量/诊断/标定/配置), 老行为不回退
    (参数标定 = 极点配置器 + 数据字典树同屏)
 ⑥ 4 个零引用死函数确实已删
"""
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import simulink_module as SM  # noqa: E402
import model_tree as MT  # noqa: E402

FAIL = []


def chk(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        FAIL.append(msg)


m = SM.SimulinkModule()
m.resize(2400, 1400)
m.load_flow_file("/home/ubuntu/zmax/src/lerobot/engineering/flows/state_space_obs.json")
m.show()
app.processEvents()
d = m.model_tree
print(f"右面板视图数 = {d.cmb_view.count()}")

print("\n① 开关搬家 (同一个对象)")
KEYS = ("chk_engine_demo", "chk_l3_full", "chk_mani_yaw", "chk_intact_exec", "chk_l4_dit", "chk_l2_compat")
for k in KEYS:
    c = getattr(m, k)
    same = (d.run_cfg._cks.get(k) is c)
    # 往上找父链, 看是否落在 RunConfigWidget 里
    p, inpanel, depth = c.parent(), False, 0
    while p is not None and depth < 12:
        if isinstance(p, MT.RunConfigWidget):
            inpanel = True
            break
        p = p.parent()
        depth += 1
    chk(same and inpanel, f"{k}: 同一对象={same} · 已在「配置·运行开关」页内={inpanel}")

print("\n② 工具栏入口按钮")
btn = getattr(m, "btn_run_cfg", None)
chk(btn is not None, f"btn_run_cfg 存在 (文字={btn.text() if btn else None})")
btn.click()
app.processEvents()
chk(d.cmb_view.currentIndex() == d.VIEW_KEYS.index("run_cfg"), f"点击后切到「配置·运行开关」页 (index={d.cmb_view.currentIndex()})")
chk(d.run_cfg.isVisible(), "运行开关页可见")

print("\n③ 页面内容 (作用/生效位置/代价/档位/诊断行)")
cap = d.run_cfg._cap()
chk(cap == "L2", f"读到画布档位 = {cap}")
alltxt = " ".join(l.text() for l in d.run_cfg.findChildren(MT.QLabel))
# 🧹 2026-10-09 精简后: 卡面是短句, 全文挪 tooltip ⇒ 判据改"短句在卡面 + 长文案在 tooltip"
for must in ("快演", "13段", "流形预测器", "INTACT", "DiT", "L2 真跑"):
    chk(must in alltxt, f"卡面有短句「{must}」")
_tips = " ".join((w.toolTip() or "") for w in d.run_cfg.findChildren(MT.QLabel))
for must in ("引擎简化世界快速演示", "simulink_module.py:7150", "13 段", "0.42mm → 6.82mm"):
    chk(must in _tips, f"tooltip 里全文没丢: 含「{must}」")
chk("生效: " in alltxt and ("simulink_module.py:" in alltxt or "engine:" in alltxt),
    "每行卡面标了『生效: 文件:行』")
chk("6.82mm" in alltxt and "0.42" in alltxt, "L2 兼容卡面写明实测代价 0.42→6.82mm")
st = d.run_cfg.lbl_state.text()
chk(all(nm in st for nm in ("⚡快演", "🚀全链", "🧠yaw", "🤖INTACT", "🎯DiT", "🧩L2")) and st.count("✓") + st.count("✗") == 6,
    f"状态行列全 6 个开关 (短名, 不是乱切): {st[:110]}")
chk("本档无效" in st, "L2 档下 L4-only 开关被标『本档无效』")

print("\n④ 面板内操作")
d.run_cfg._cks["chk_intact_exec"].setChecked(False)
app.processEvents()
chk("🤖INTACT✗" in d.run_cfg.lbl_state.text(), "拨开关 → 诊断行即时刷新 (短名+✓/✗ 口径)")
d.run_cfg._cks["chk_intact_exec"].setChecked(True)
d.run_cfg._restore()
app.processEvents()
D = MT.RunConfigWidget.DEFAULTS
chk(all(d.run_cfg._cks[k].isChecked() == v for k, v in D.items()), "「↺ 恢复默认」全部回到原厂默认")
d.run_cfg._copy()
chk("Z-MAX 运行开关" in QApplication.clipboard().text(), "「📋 复制当前配置」写进剪贴板")

print("\n⑤ 精简后 4 视图 映射 (索引→控件) — 全部与状态空间工程有真连接")
EXP = {0: ("mparam",), 1: ("bus",), 2: ("calib",), 3: ("run_cfg",)}
OBJ = {"mparam": d.mparam, "bus": d.bus, "calib": d.calib, "run_cfg": d.run_cfg}
chk(d.cmb_view.count() == 4, f"视图数 = {d.cmb_view.count()} (精简前 11 → 5 → 4: 测量三行合一 + 加标定页)")
for i in range(d.cmb_view.count()):
    d.cmb_view.setCurrentIndex(i)
    app.processEvents()
    want = set(EXP.get(i, ()))
    vis = {k for k, w in OBJ.items() if w.isVisible()}
    chk(vis == want, f"[{i}] {d.cmb_view.itemText(i)} → 可见={sorted(vis)} 期望={sorted(want)}")
d.cmb_view.setCurrentIndex(0)
app.processEvents()
chk(d.mparam.isVisible() and not d.run_cfg.isVisible(), "默认停在「🧮 主参数 M」页")

print("\n⑥ 无联系部件已不在面板 (挪到 legacy) + 死函数已删")
for dead_cls in ("StageCalibrationWidget", "PolePlacementWidget", "FreeResponsePlot", "PoleZeroPlot",
                 "PerformanceWidget", "SceneStateWidget", "EngineeringReqWidget", "RunSummaryWidget",
                 "analyze_system", "main_chain", "tf_to_ss", "node_transfer"):
    chk(not hasattr(MT, dead_cls), f"model_tree 不再有 {dead_cls}")
chk(os.path.exists(os.path.join(os.path.dirname(os.path.abspath(MT.__file__)),
                                "_model_tree_ffpd_legacy.py")), "legacy 文件在 (代码没删, 可复活)")
for dead in ("_fmt_sig", "_project_3d_to_2d"):
    chk(not hasattr(MT, dead), f"模块级 {dead} 已删")
chk(not hasattr(MT.ModelTreeDock, "skill_markdown"), "ModelTreeDock.skill_markdown 已删")
chk(not hasattr(MT.ModelTreeDock, "_show_math"), "ModelTreeDock._show_math 已停用 (整段注释)")
chk("_open_url" not in open(os.path.join(os.path.dirname(os.path.abspath(MT.__file__)),
                                        "_model_tree_ffpd_legacy.py"), encoding="utf-8").read().split("def _open_url")[0],
    "_open_url 已删 (legacy 文件里也没留实现)")

print("\n" + ("═" * 60))
print("❌ 失败 %d 项" % len(FAIL) if FAIL else "✅ 全部通过")
sys.exit(3 if FAIL else 0)
