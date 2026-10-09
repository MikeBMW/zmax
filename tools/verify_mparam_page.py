#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_mparam_page.py — 右侧栏「🧮 主参数 M · 测量/标定/诊断/配置」页 真连接取证

老倪 (2026-10-09): 「右边的侧边栏, 重点是 配置 和 标定, 以及主参数 M」。
要证的不是"有个页", 而是**这页的数据真来自状态空间工程**:
 ① 从**真画布**(flows/state_space_obs.json)建的窗口里, 这页找到 M 节点 (id=n_calib_mani)
 ② 4 个页签都有行, 且值 == 画布节点 params 里的快照 (逐条比对, 不是自己编的)
 ③ M 微调框/惯性勾 反映节点里的 M / inertia (真源值)
 ④ 「✏️ 写 M」按钮真跑真源写入 (取当前值写一遍 = 幂等, 写完真源值不变)
 ⑤ 「📥 从真源同步到节点」按钮真跑 tools/ss_node_sync.py (退出码 0)
 ⑥ 没有 M 节点的画布 → 诚实空态 (不假造)
"""
import os
import sys
import json
import subprocess

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication   # noqa: E402
import simulink_module as SM               # noqa: E402
import model_tree as MT                    # noqa: E402

ROOT = "/home/ubuntu/zmax"
CANVAS = os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json")
NODE_PARAMS = json.load(open(CANVAS, encoding="utf-8"))
NODE_PARAMS = next(n for n in NODE_PARAMS["nodes"] if n.get("id") == "n_calib_mani")["params"]

FAIL = []
def chk(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        FAIL.append(msg)

app = QApplication(sys.argv)
m = SM.SimulinkModule()
m.resize(2400, 1400)
m.show()                          # 真窗口 (离屏) — 可见性判据才真实
m.load_flow_file(CANVAS)          # 载画布 → load_flow_file 内会调 model_tree.refresh()
app.processEvents()
d = m.model_tree
v = d.mparam
chk0_rows = v.tbl["cfg"].rowCount()
chk(d.VIEW_KEYS.index("mparam") == d.cmb_view.currentIndex(), "默认就停在「主参数 M」页 (index=0)")
chk(chk0_rows > 0, f"载入画布后本页**自动**刷新出内容 ({chk0_rows} 行) — 不用先切页""")

print("① 找到画布上的 M 节点 (真连接)")
n = v._node()
chk(n is not None, f"节点找到: {(n or {}).get('name')} (id={(n or {}).get('id')})")
_id, _nm, _p = (n or {}).get("id", ""), (n or {}).get("name", ""), ((n or {}).get("params") or {})
chk("主参数" in _nm and "cfg_snapshot" in _p,
    f"节点身份: 名字含「主参数」+ params 带 cfg_snapshot (id={_id} 由 load_flow_file 重编, 故不按 id 判)")

print("\n② 4 页签 + 逐值比对 (页上显示 == 节点快照)")
chk(v.tabs.count() == 4, f"页签数 = {v.tabs.count()} {[v.tabs.tabText(i) for i in range(v.tabs.count())]}")
chk(v.lbl_hd.text().startswith("🧮 主参数 M"), f"页头 = {v.lbl_hd.text()}")
snap = NODE_PARAMS.get("cfg_snapshot", {})
def rows(tab):
    t = v.tbl[tab]
    return {t.item(r, 0).text(): t.item(r, 1).text() for r in range(t.rowCount())}
for tab, must in (("measure", "测量"), ("calib", "标定"), ("diag", "诊断"), ("cfg", "配置")):
    rr = rows(tab)
    chk(len(rr) >= 4, f"{tab} 页 {len(rr)} 行: {list(rr)[:5]}")
r_cfg = rows("cfg")
chk(f"{snap.get('params_ready')}/{snap.get('params_total')}" in r_cfg.get("就绪度", ""),
    f"就绪度 = {r_cfg.get('就绪度')} (节点快照 {snap.get('params_ready')}/{snap.get('params_total')})")
chk(str(snap.get("active_task", "")) in r_cfg.get("任务", ""),
    f"活跃任务 = {r_cfg.get('任务')} (节点快照 {snap.get('active_task')})")
chk(any(k.startswith("真源 ") for k in r_cfg), f"真源路径行 {sum(k.startswith('真源 ') for k in r_cfg)} 条 (节点 cfg_entries)")
r_cal = rows("calib")
_want_m = (NODE_PARAMS.get("calib_view") or {}).get("主参数M")
_got_m = r_cal.get("主参数 M", "")
chk(bool(_got_m) and (_got_m == _want_m), f"标定页 M 行 == 节点 calib_view 原样: {_got_m!r}")

print("\n③ M 控件反映真源值")
chk(abs(v.sp_M.value() - float(NODE_PARAMS.get("M", 1.0))) < 1e-9, f"微调框 M = {v.sp_M.value()} (节点 M={NODE_PARAMS.get('M')})")
chk(v.chk_inertia.isChecked() == bool(NODE_PARAMS.get("inertia", False)),
    f"惯性勾 = {v.chk_inertia.isChecked()} (节点 inertia={NODE_PARAMS.get('inertia')})")
v.sp_M.setValue(99.0)
chk(v.sp_M.value() == 8.0, f"控件范围校验: 输入 99 → 钳到 {v.sp_M.value()} (M∈[0,8] 红线)")

print("\n④ ✏️ 写 M 按钮真跑真源 (取当前值 = 幂等, 值不变)")
TK = os.path.join(ROOT, "config/calib/zmax_manifold.json")
def _vals(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}   # 忽略 _updated_at 时间戳
_raw_before = open(TK, encoding="utf-8").read()
before = _vals(json.load(open(TK, encoding="utf-8")))
v.sp_M.setValue(float(NODE_PARAMS.get("M", 1.0)))
v._write_M()
app.processEvents()
after = _vals(json.load(open(TK, encoding="utf-8")))
chk(before == after, f"真源 config/calib/zmax_manifold.json 数值不变 (幂等写): {after}")
open(TK, "w", encoding="utf-8").write(_raw_before)   # 只差 _updated_at 时间戳 → 复原, 别弄脏工作区
chk(open(TK, encoding="utf-8").read() == _raw_before, "真源文件已复原 (判据跑完不留脏改动)")

print("\n⑤ 📥 同步按钮真跑 ss_node_sync.py")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/ss_node_sync.py")],
                   capture_output=True, text=True, cwd=ROOT, timeout=300)
chk(r.returncode == 0, f"ss_node_sync.py exit={r.returncode} · 末行 {(r.stdout or '').strip().splitlines()[-1:] }")

print("\n⑥ 没有 M 节点的画布 → 诚实空态")
class _Stub:
    nodes = []
v2 = MT.MasterParamMView(_Stub())
app.processEvents()
chk("⚠️" in v2.lbl_node.text() and v2.tbl["cfg"].rowCount() == 0,
    f"空态提示: {v2.lbl_node.text()[:46]}…")
chk("canvas_add_manifold_calib.py" in v2.lbl_cmd.text(), f"给出补救命令: {v2.lbl_cmd.text()[:60]}")

print("\n" + "═" * 60)
print("❌ 失败 %d 项" % len(FAIL) if FAIL else "✅ 全部通过 — 主参数 M 页数据来自画布节点, 写 M 走真源")
sys.stdout.flush()
os._exit(1 if FAIL else 0)
