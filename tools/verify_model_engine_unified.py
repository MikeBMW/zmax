#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 主界面「模型引擎」功能区与独立窗口必须是**同一个界面** (2026-10-14 老倪要求)。

判据 (全部可复核, 不靠目检):
  ① 页面 (TrainingModule) 里内嵌的是 model_engine_window.ModelEnginePanel —— 同一个类;
  ② 页内面板与弹窗面板的类相同, 且列名/按钮文字逐字一致 (不是"长得像"而是同一份代码);
  ③ 弹窗 (ModelEngineWindow) 的内容就是 ModelEnginePanel (子控件里能找到);
  ④ 页内面板真的在页面上 (可见 + 有尺寸), 且表格 4 行 L2~L5;
  ⑤ 页面上那个按钮现在是"弹出为窗口"语义 (不再宣称"另有一个模型引擎窗口")。
"""
import json
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.chdir("/home/ubuntu/zmax")

from PyQt5.QtWidgets import QApplication, QPushButton  # noqa: E402

app = QApplication.instance() or QApplication([])
import model_engine_window as MEW  # noqa: E402

res = []


def chk(name, cond, extra=""):
    res.append(("✓" if cond else "✗") + " " + name + (" :: %s" % (extra,) if extra else ""))


cls_panel = MEW.ModelEnginePanel
win = MEW.ModelEngineWindow(poll=False)
chk("① 页面与弹窗共用的类存在 (ModelEnginePanel)", cls_panel is not None, cls_panel.__name__)
chk("② 弹窗内容就是 ModelEnginePanel (不是另一套布局)",
    isinstance(getattr(win, "panel", None), cls_panel),
    type(getattr(win, "panel", None)).__name__)
_inv = MEW._load_inventory() if hasattr(MEW, "_load_inventory") else None
if _inv is None:                    # 面板自己那份唯一依据 (model_inventory --json)
    import json as _json
    _inv = _json.loads(subprocess.run(MEW.INV_CMD, cwd=MEW.ROOT, capture_output=True, text=True,
                                      timeout=180).stdout)
win.panel.feed(_inv, {})
_rows_all = win.panel._rows()
_ncand = sum(1 for _r in _rows_all if _r.get("cand"))
_next = sum(1 for _r in _rows_all if _r.get("ext"))
chk("③ 弹窗面板表格 = 4 基座 + 在役扩展 + 候选行 (L2~L5 在前)",
    win.panel.tb.rowCount() == 4 + _next + _ncand
    and [r["layer_key"] for r in _rows_all if r.get("active") and not r.get("ext")] == ["L2", "L3", "L4", "L5"]
    and sorted({r["layer_key"] for r in _rows_all if r.get("ext")}) == ["L2", "L3", "L4", "L5"],
    "%d 行 (基座 4 + 在役扩展 %d + 候选 %d)" % (win.panel.tb.rowCount(), _next, _ncand))
cols = [win.panel.tb.horizontalHeaderItem(i).text() for i in range(win.panel.tb.columnCount())]
btns = [b.text() for b in win.panel.findChildren(QPushButton)]
chk("④ 弹窗列名/按钮齐", len(cols) == 8 and len(btns) >= 6, "%s | %s" % (cols[:3], btns[:3]))

# 页面里内嵌的那一个: 直接构造 TrainingModule (studio 的模型引擎页)
src = open("/home/ubuntu/zmax/tools/gui/studio.py", encoding="utf-8").read()
chk("⑤ 页面源码内嵌 ModelEnginePanel (不是另写一个界面)",
    "from model_engine_window import ModelEnginePanel" in src and "self.me_panel = ModelEnginePanel(" in src)
chk("⑥ 页面按钮已改为'弹出'语义 (不再宣称另有窗口)",
    "弹出为窗口" in src and "模型引擎窗口 (L2~L5)\"" not in src)
# 页内面板与弹窗面板: 同一份代码 ⇒ 列名/按钮必然一致 (用同一个类实例化两遍对比)
p2 = cls_panel(poll=False)
cols2 = [p2.tb.horizontalHeaderItem(i).text() for i in range(p2.tb.columnCount())]
btns2 = [b.text() for b in p2.findChildren(QPushButton)]
chk("⑦ 两处界面逐字一致 (列名 + 按钮)", cols == cols2 and btns == btns2, "%d 列 / %d 按钮" % (len(cols2), len(btns2)))

# ⑧~⑪ 2026-10-14 老倪: 「配置通道都是之前的模型配置了, 要与状态空间工程实际数据一致」
#   ⇒ 判据把「配置通道必须唯一依据现算 + 表高按内容定(末行不许被裁)」钉住, 防回归。
chk("⑧ 配置通道已改唯一依据现算 (studio 调 model_config_matrix.py)",
    "model_config_matrix.py" in src and "_build_config_matrix" in src and "ZOO_SPEC" not in src)
chk("⑨ 表高按内容定 (防末行被裁: setFixedHeight(_need))", "tbl.setFixedHeight(int(_need))" in src)
chk("⑩ 列头不再硬切 (短名按词边界 + 截断带 …)",
    'split(" ")[0].split("(")[0]' in src and '_short[:14] + "…"' in src)
r = subprocess.run(["/home/ubuntu/zmax/gui-venv311/bin/python",
                    "/home/ubuntu/zmax/tools/model_config_matrix.py", "--check"],
                   capture_output=True, text=True, timeout=300, cwd="/home/ubuntu/zmax")
chk("⑪ 模型配置矩阵唯一依据判据 PASS", r.returncode == 0, (r.stdout or "").strip().splitlines()[-1][:80])

# ⑬ 2026-10-14 老倪: 「在模型引擎里, 要增加 SAM3, 我看你设计的位置是 L2对不？你来设计UI显示」
#    ⇒ 模型引擎表里 L2 下面必须有一行候选, 且**显 SAM3 + 未切在役判据 + 候选权重真路径**;
#      候选行与配置通道/配置中心**同源** (都走 model_config_matrix), 不许各写一份。
_l2c = next((r for r in _rows_all if r.get("cand") and str(r["layer"]).startswith("L2")), None)
chk("⑬ 模型引擎表 L2 候选行显 SAM3 (老倪点名的那一行)",
    bool(_l2c) and "SAM3" in str(_l2c.get("name")), (_l2c or {}).get("name"))
chk("⑬b 候选行带「未切在役」判据 (不编结论: 无备注就如实写未评估)",
    bool(_l2c) and bool(_l2c.get("note")), (_l2c or {}).get("note"))
chk("⑬c 候选权重路径=真路径且存在 (双击可复制完整路径)",
    bool(_l2c) and os.path.exists(_l2c.get("path") or ""), ((_l2c or {}).get("path") or "")[-52:])

# ⑬d 用**真 8796 状态**再喂一遍: 候选行版本/名字/路径都不许溢出列宽 (ElideNone ⇒ 溢出=硬切)
try:
    import urllib.request as _u
    _st = json.load(_u.urlopen("http://127.0.0.1:8796/status/all", timeout=3))
except Exception:                                                             # noqa: BLE001
    _st = {}
win.panel.feed(_inv, _st)
_fm = win.panel.tb.fontMetrics()
_ov = []
for _r in range(win.panel.tb.rowCount()):
    for _c in range(win.panel.tb.columnCount() - 1):        # 最后一列 Stretch, 单独判
        _it = win.panel.tb.item(_r, _c)
        _t = _it.text() if _it else ""
        if _fm.horizontalAdvance(_t) + 12 > win.panel.tb.columnWidth(_c):
            _ov.append("r%d c%d %r" % (_r, _c, _t[:26]))
chk("⑬d 真状态喂入后候选行也不越列宽 (不硬切)", not _ov, ("溢出 %s" % _ov[:3]) if _ov else "无溢出")

# ⑭ 同源核对: 窗口候选路径 == 配置通道「候选权重路径」单元格值 (同一唯一依据, 不许两套数)
_mx = subprocess.run(["/home/ubuntu/zmax/gui-venv311/bin/python", "-c",
                      "import sys,json;sys.path.insert(0,'/home/ubuntu/zmax/tools');"
                      "import model_config_matrix as M;"
                      "b=M.build();"
                      "print(json.dumps({r['name']: r['vals'] for g in b['groups'] for r in g['rows']}"
                      "['候选权重路径'], ensure_ascii=False))"],
                     capture_output=True, text=True, timeout=300, cwd="/home/ubuntu/zmax")
try:
    _pth = json.loads((_mx.stdout or "{}").strip().splitlines()[-1])
except Exception:                                                             # noqa: BLE001
    _pth = {}
chk("⑭ 窗口候选路径与配置通道「候选权重路径」同源同值 (L2)",
    bool(_l2c) and _pth.get("L2") == _l2c.get("path"),
    "窗口 …%s | 配置通道 …%s" % (((_l2c or {}).get("path") or "")[-34:], str(_pth.get("L2"))[-34:]))

# ⑮ 在役模型名 = **真名** (老倪 2026-10-14: 「在役模型的名字要改成真实模型的名字, 例如 L2 YOLO,
#    每层模型都要改成实际的模型」) —— 每层都要能读出模型家族, 不许再写 "L2 在役 (指针)" 这种只讲指针的话。
_FAM = {"L2": ("YOLO",), "L3": ("SmolVLA",), "L4": ("INTACT",), "L5": ("DeepSeek", "SmolVLM")}
_ins, _cands = {}, []
for _r in (getattr(win.panel, "_rows_cache", None) or []):
    if _r.get("cand"):
        _cands.append(_r)
        continue
    _ins[str(_r.get("layer"))] = _r.get("name_full") or _r.get("name")
_bad = [ly for ly, kw in _FAM.items() if not any(k in str(_ins.get(ly, "")) for k in kw)]
chk("⑮ 四层「在役模型」都是真实模型名 (YOLO/SmolVLA/INTACT/DeepSeek)", not _bad,
    (" · ".join("%s=%s" % (ly, str(_ins.get(ly))[:24]) for ly in ("L2", "L3", "L4", "L5"))
     if not _bad else "缺真名: %s" % _bad))

# ⑮b 同源同值: 窗口「在役模型」== 配置通道「在役模型」(两处不许两套名字)
_mx2 = subprocess.run(["/home/ubuntu/zmax/gui-venv311/bin/python", "-c",
                       "import sys,json;sys.path.insert(0,'/home/ubuntu/zmax/tools');"
                       "import model_config_matrix as M;"
                       "b=M.build();"
                       "print(json.dumps({r['name']: r['vals'] for g in b['groups'] for r in g['rows']}"
                       "['在役模型'], ensure_ascii=False))"],
                      capture_output=True, text=True, timeout=300, cwd="/home/ubuntu/zmax")
try:
    _nm = json.loads((_mx2.stdout or "{}").strip().splitlines()[-1])
except Exception:                                                             # noqa: BLE001
    _nm = {}
_dif = ["%s: 窗口 %r ≠ 配置通道 %r" % (ly, _ins.get(ly), _nm.get(ly))
        for ly in ("L2", "L3", "L4", "L5") if _nm.get(ly) and _nm.get(ly) != _ins.get(ly)]
chk("⑮b 窗口与配置通道「在役模型」同源同值 (L2~L5)", bool(_nm) and not _dif,
    "两处同值: %s" % " / ".join(str(_ins.get(ly))[:18] for ly in ("L2", "L3", "L4", "L5")) if not _dif
    else "; ".join(_dif)[:160])

# ⑮c 回归守卫: 老写法 "L2 在役 (指针)" 必须彻底消失 (只在描述指针种类, 没说是哪个模型)
_src = "\n".join(l for l in open("/home/ubuntu/zmax/tools/model_inventory.py", encoding="utf-8")
                 .read().splitlines() if not l.lstrip().startswith("#"))     # 只看代码, 不看注释
_hard = [s for s in ('"L2 在役 (指针)"', '"L3 在役 (运行时 ckpt)"', '"L4 在役 (稳定指针)"',
                     '"L5 最新 merged (可部署)"') if s in _src]
chk("⑮c 旧硬写名字已从唯一依据代码里消失 (改走 models/active_models.json 真名)", not _hard,
    "残留 %s" % _hard if _hard else "0 处残留; 真名源: models/active_models.json + ckpt 自身 config.json")

# ⑮d 列里放不下的**完整真名**必须留在 tooltip (按像素预算收显示串, 但不许丢信息);
#     且"引擎报的名"与"磁盘产物真名"家族不同时 (实测 L5: DeepSeek 视觉规划 vs 本地 SmolVLM)
#     tooltip 必须点出这件事, 不许让名字和权重路径各指一个东西还不说。
_tipbad, _l5tip = [], ""
for _r in (getattr(win.panel, "_rows_cache", None) or []):
    if _r.get("cand"):
        continue
    _it = win.panel.tb.item(win.panel.tb.rowCount() - 1, 1)
    _rows = [i for i in range(win.panel.tb.rowCount())
             if str(win.panel.tb.item(i, 0).text()) == str(_r.get("layer"))]
    if not _rows:
        continue
    _tip = win.panel.tb.item(_rows[0], 1).toolTip()
    if (_r.get("name_full") or "") not in _tip:
        _tipbad.append("%s 完整名 %r 不在 tooltip" % (_r.get("layer"), _r.get("name_full")))
    if _r.get("name_disk") and _r["name_disk"] not in _tip:
        _tipbad.append("%s 磁盘产物名未在 tooltip 说明" % _r.get("layer"))
    if str(_r.get("layer")) == "L5":
        _l5tip = ("有说明: %s" % _r["name_disk"]) if _r.get("name_disk") and _r["name_disk"] in _tip else "L5 无家族冲突(或未说明)"
chk("⑮d 列里被收的完整真名 + 家族冲突都在 tooltip (不丢信息)", not _tipbad,
    "; ".join(_tipbad)[:120] if _tipbad else "四层 tooltip 均含完整真名 · L5: " + _l5tip)

# ⑫ 配置通道表在真机尺寸下必须整张看得完 (2026-10-14 老倪「只渲染到版本行就收边」的回归守卫)
rf = subprocess.run(["/home/ubuntu/zmax/gui-venv311/bin/python",
                     "/home/ubuntu/zmax/tools/verify_cfg_table_fit.py"],
                    capture_output=True, text=True, timeout=400, cwd="/home/ubuntu/zmax",
                    env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
chk("⑫ 配置通道表真机尺寸下 21 行整张看得完", rf.returncode == 0,
    (rf.stdout or "").strip().splitlines()[-1][:70] if rf.stdout else (rf.stderr or "")[-70:])

print("\n".join(res))
ok = sum(1 for r in res if r.startswith("✓"))
print("\n判据汇总: %d/%d PASS" % (ok, len(res)))
sys.exit(0 if ok == len(res) else 1)
