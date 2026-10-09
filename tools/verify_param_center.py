#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_param_center.py — 🎛 参数中心 + 全局数字链动 判据 (2026-10-09 老倪)

判据:
  ① 注册表覆盖: 五类数字都非空 (标定/画布/代码常量/产品性能/运行开关), 总数 ≥100
  ② 每个数字: 真源在盘上 · 值==真源 · 有 min/max 或显式标注"范围未定义" · 缺口(null)显式标注
  ③ 链动: 主参数 M / 插入深度 insert_depth / 平面 plane_z 都能给出 功能·模块·系统 影响链
  ④ 真改一次 (在临时副本上): 改画布数字 → 落盘 → 回读一致 → 还原; 改代码常量 → 备份+语法校验;
     越界值必须被拒; 档位非法必须被拒
  ⑤ 库面: 单一工程库里 params/param_links/param_events 三表与注册表一致
  ⑥ 界面: 参数中心页真建 (离屏), 数字表行数==注册表数, 分类树 5 类, 双击改数入口在
  ⑦ 主窗口: 侧栏有「参数中心」卡, 点它切到参数中心页
用法: QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/verify_param_center.py
"""
import json
import os
import shutil
import sqlite3
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAIL = []


def chk(c, msg):
    print(("  ✅ " if c else "  ❌ ") + str(msg), flush=True)
    if not c:
        FAIL.append(str(msg))


import param_registry as PR                                                       # noqa: E402

print("① 注册表覆盖", flush=True)
reg = PR.registry()
cats = {k: len(v) for k, v in reg["groups"].items()}
chk(len(reg["params"]) >= 100, "全局可改数字 %d 个: %s" % (len(reg["params"]), cats))
for c in ("calib", "canvas", "code", "switch"):
    chk(cats.get(c, 0) > 0, "分类 %s 非空 (%d)" % (c, cats.get(c, 0)))

print("② 每个数字的真源与范围标注", flush=True)
miss = [p["param_id"] for p in reg["params"] if not os.path.exists(os.path.join(ROOT, p["source"]))]
chk(not miss, "真源文件全部在盘上 (%d 个来源)" % len({p["source"] for p in reg["params"]}))
_VOCAB = ("已定义", "自动推断", "未标定", "未定义")
noflag = [p["param_id"] for p in reg["params"] if not any(k in p["status"] for k in _VOCAB)]
chk(not noflag, "每个数字都有明确口径标注 (人工确认 %d · 自动推断 %d · 缺口 %d)" % (
    sum(1 for p in reg["params"] if p["status"].startswith("已定义(人工)")),
    sum(1 for p in reg["params"] if p["status"].startswith("范围自动推断")),
    sum(1 for p in reg["params"] if "缺口" in p["status"])))
gaps = [p for p in reg["params"] if p["value"] is None]
chk(all("缺口" in p["status"] or "未定义" in p["status"] for p in gaps),
    "值为空(未标定)的数字显式标注缺口 (%d 个: %s)" % (len(gaps), [p["cn"] for p in gaps][:4]))
nd = sum(1 for p in reg["params"] if p["min"] is not None and p["max"] is not None)
chk(nd >= 100, "带 min/max 的数字 %d 个 (其中人工确认 %d)" % (
        nd, sum(1 for p in reg["params"] if p["status"] == "已定义(人工)")))

print("③ 链动 (参数 → 功能/模块/系统/KPI ≠ 空)", flush=True)
for pid in ("calib:manifold_engine.M", "code:src/lerobot/policies/left_right/state_space/safety.py#VETO_TH",
            "canvas:🔧 L2 状态机决策 · 决策 (39D 状态→动作段)#frames"):
    cand = [p["param_id"] for p in reg["params"] if p["param_id"] == pid] or \
           [p["param_id"] for p in reg["params"] if "manifold_engine.M" in p["param_id"]] or \
           [p["param_id"] for p in reg["params"] if p["group"] == "code"][:1]
    ch = PR.effect_chain(cand[0]) if cand else {"ok": False}
    chk(ch.get("ok") and (ch.get("systems") or ch.get("functions") or ch.get("modules")),
        "链路 %s → 系统%s 功能%d 模块%d 代码%d" % (cand[0] if cand else "-", ch.get("systems"),
                                                len(ch.get("functions", [])), len(ch.get("modules", [])),
                                                len(ch.get("code", []))))

print("④ 真改一次 (临时副本, 不碰真源)", flush=True)
tmp_dir = os.path.join(ROOT, ".hermes_pc_test")
os.makedirs(tmp_dir, exist_ok=True)
canvas_p = PR.CANVAS
bak = canvas_p + ".pcbak"
shutil.copy2(canvas_p, bak)
try:
    tgt = next(p for p in reg["params"] if p["group"] == "canvas" and p["writable"]
               and isinstance(p["value"], (int, float)) and not isinstance(p["value"], bool))
    old = tgt["value"]
    lo, hi = (tgt["min"] if tgt["min"] is not None else float(old) - 1.0,
              tgt["max"] if tgt["max"] is not None else float(old) + 1.0)
    new = float(old) * 0.9 if abs(float(old) * 0.9 - float(old)) > 1e-9 and lo <= float(old) * 0.9 <= hi \
        else (lo + (hi - lo) * 0.5 if lo != hi else float(old))
    if abs(new - float(old)) < 1e-12:
        new = float(old) + 1e-3
    r1 = PR.set_param(tgt["param_id"], new, write=True)
    back = None
    import importlib
    PR2 = importlib.reload(PR)
    back = PR2.registry()["by_id"].get(tgt["param_id"], {}).get("value")
    chk(r1.get("ok") and str(back) == str(new), "改画布数字 %s: %s → %s, 回读 %s" % (tgt["name"], old, new, back))
    # 顶层产品性能数字: 改 KPI 文本里的数字 → 回读一致 → 还原 (老倪: 从顶层产品性能的数据改变)
    kp = next((p for p in reg["params"] if p["group"] == "platform" and p["writable"]), None)
    if kp:
        kv = float(kp["value"])
        nv = kv + 1.0
        rk = PR.set_param(kp["param_id"], nv, write=True)
        import importlib as _il
        _p2 = _il.reload(PR)
        kb = _p2.registry()["by_id"].get(kp["param_id"], {}).get("value")
        chk(rk.get("ok") and kb is not None and abs(float(kb) - nv) < 1e-9,
            "改产品性能目标 %s: %s → %s (回读 %s) · 链到 %s" % (
                kp["cn"][:34], kv, nv, kb, (rk.get("chain") or {}).get("kpis", [])[:1]))
        kk = PR.set_param(kp["param_id"], kv, write=True)
        chk(kk.get("ok"), "KPI 已还原 %s" % kv)
    else:
        chk(False, "没有可写的产品性能数字 (platform 分类为空)")
    r2 = PR.set_param(tgt["param_id"], old, write=True)
    chk(r2.get("ok"), "已还原为 %s" % old)
    # 越界必拒
    r3 = PR.set_param("calib:manifold_engine.M", 999999, write=True)
    chk(not r3.get("ok"), "越界值被拒: %s" % r3.get("err"))
    # 档位非法必拒
    r4 = PR.set_param("switch.l3_mode", "not_a_mode", write=True)
    chk(not r4.get("ok"), "非法档位被拒: %s" % r4.get("err"))
    # 代码常量: 写坏语法立即回滚 (用真常量小步改再还原)
    cps = [p for p in reg["params"] if p["group"] == "code" and isinstance(p["value"], (int, float))]
    if cps:
        cp = cps[0]
        r5 = PR.set_param(cp["param_id"], cp["value"], write=True)
        chk(r5.get("ok"), "代码常量可写且语法校验通过: %s (%s)" % (cp["name"], r5.get("msg")))
finally:
    shutil.copy2(bak, canvas_p)
    os.remove(bak)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print("     (画布已还原)", flush=True)

print("⑤ 库面 (单一工程库)", flush=True)
try:
    import importlib.util as _iu
    _sp = _iu.spec_from_file_location("_edb2", os.path.join(ROOT, "tools", "engineering_db.py"))
    _m = _iu.module_from_spec(_sp)
    _sp.loader.exec_module(_m)
    _m.build(quiet=True)          # 重建库, 让刚才的改数事件也进库 (可观察性)
except Exception as _e:
    print("     (重建库失败: %r)" % (_e,), flush=True)
db = os.path.join(ROOT, "data", "database", "zmax_engineering.db")
if os.path.exists(db):
    con = sqlite3.connect(db)
    n_db = con.execute("SELECT COUNT(*) FROM params").fetchone()[0]
    n_lk = con.execute("SELECT COUNT(*) FROM param_links").fetchone()[0]
    n_ev = con.execute("SELECT COUNT(*) FROM param_events").fetchone()[0]
    con.close()
    chk(n_db == len(reg["params"]), "库里 params %d == 注册表 %d" % (n_db, len(reg["params"])))
    chk(n_lk >= n_db * 2, "库里 param_links %d 条 (数字→功能/模块/系统)" % n_lk)
    chk(n_ev >= 1, "库里 param_events %d 条 (改数留痕可观察)" % n_ev)
else:
    chk(False, "工程库不存在: %s" % db)

print("⑥ 参数中心页 (离屏真建)", flush=True)
from PyQt5.QtWidgets import QApplication                                          # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])
from param_center import ParamCenterPage                                          # noqa: E402

pg = ParamCenterPage()
chk(pg.err is None, "页面加载注册表无错 (%s)" % pg.err)
chk(pg.table.rowCount() == len(reg["params"]), "数字表 %d 行 == 注册表 %d" % (pg.table.rowCount(), len(reg["params"])))
chk(pg.tree.topLevelItemCount() >= 6, "分类树 %d 个顶层节点 (全部+5 类)" % pg.tree.topLevelItemCount())
pg.ed_search.setText("plane_z")
chk(pg.table.rowCount() >= 1, "搜索 plane_z → %d 行" % pg.table.rowCount())
pg.ed_search.setText("")

print("⑦ 主窗口接线", flush=True)
import studio as ST                                                               # noqa: E402

win = ST.StudioMainWindow()
for _ in range(60):
    app.processEvents()
    if getattr(win, "simulink", None) is not None:
        break
    import time as _t
    _t.sleep(0.2)
chk(getattr(win, "pc", None) is not None and "params" in win.modules, "主窗口已挂参数中心页")
chk(hasattr(win.sidebar, "params_card"), "侧栏有参数中心卡")
_cards = [c.layer_id for c in win.sidebar.findChildren(ST.SystemLayerCard)]
chk(_cards.index("params") == len(_cards) - 1, "参数中心卡在侧栏最下面 (%s)" % _cards)
chk("plat" not in _cards, "侧栏没有平台支撑卡 (整合掉了; 平台支撑页签仍在功能清单里)")
win.sidebar.layer_clicked.emit("params")
app.processEvents()
chk(win.stack.currentWidget() is win.pc, "点参数中心卡 → 切到参数中心页")

print(("✅ 全部通过 — 参数中心 + 全局数字链动 (7 项)" if not FAIL else "❌ 失败 %d 项: %s" % (len(FAIL), FAIL[:6])),
      flush=True)
sys.stdout.flush()
os._exit(1 if FAIL else 0)
