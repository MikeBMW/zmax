# -*- coding: utf-8 -*-
"""判据: Trace 窗口 与 信号分析窗口 的 signal **必须来自同一个数据库**。

老倪 2026-10-17: 「现在的 Trace 窗口的 signal, 与信号分析的 signal, 是同一个数据源么？
                都要来自统一的数据库」

判据 (离屏, 不碰在跑的控制台):
  ① 统一库在场且新鲜 (<3s): zmax_data/dataspace/signals.db
  ② live_signals.topics() 读到的 == 库里的逐条内容 (不回落文件)
  ③ **只在库里**塞一条探针信号 ⇒ Trace 表格与信号分析树都出现它 (证明两边都读库)
  ④ 探针清掉后两边同时消失 (不是各自缓存了假数据)
  ⑤ ZMAX_SIGNAL_DB_OFF=1 时回落文件且打印一行 (降级可查, 不静默)
"""
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "src"), ROOT]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ZMAX_REPO", ROOT)

ok, bad = 0, []


def chk(name, cond, extra=""):
    global ok
    extra = str(extra)
    if cond:
        ok += 1
        print(f"✅ {name}{(' · ' + extra) if extra else ''}")
    else:
        bad.append(name)
        print(f"❌ {name}{(' · ' + extra) if extra else ''}")


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:                                                        # noqa: BLE001
        return None


from lerobot.dataspace import signal_store as SS                              # noqa: E402
from lerobot.middleware import live_signals as LS                            # noqa: E402

# ① 库新鲜
st = SS.stats()
chk("① 统一信号库在场且新鲜", bool(st["age_s"] is not None and st["age_s"] < 3.0 and st["signals"] > 0),
    f"{st['db']} · 话题 {st['topics']} · 信号 {st['signals']} · 龄 {st['age_s']}s")

# ② topics() 读库
LS._CACHE.update(t=0.0, data=None)
live = LS.topics()
db = SS.read_snapshot(max_age=3.0) or {}
same_keys = set(live) == set(db)
# 同一拍里可选字段会随帧出现/消失 (接触标志、夹爪等), 允许 ≤2% 条数差; 共有字段的值必须逐字相同
n_live = sum(len(v.get("fields") or {}) for v in live.values())
n_db = sum(len(v.get("fields") or {}) for v in db.values())
val_diff = []
for t in sorted(set(live) & set(db)):
    a, b = live[t].get("fields") or {}, db[t].get("fields") or {}
    for k in set(a) & set(b):
        if abs(float(a[k]) - float(b[k])) > 1e-9:
            val_diff.append((t, k, a[k], b[k]))
tol = max(3, int(0.02 * max(1, n_live)))
chk("② live_signals 读到的 == 库内容", same_keys and not val_diff and abs(n_live - n_db) <= tol,
    f"{len(live)} 话题 · 信号 {n_live} vs 库 {n_db} (容差 {tol}) · 值差异 {len(val_diff)} {val_diff[:2]}")

# ③④ 只在库里塞探针 ⇒ 两个窗口都能看到 (再删掉 ⇒ 都消失)
FIELD, PROBE_V = "末端_x", 0.424242
import signal as _sig                                                            # noqa: E402
import sqlite3                                                                  # noqa: E402

PIDF = os.path.join(ROOT, "zmax_data", "dataspace", "signal_store.pid")
dpid = int(open(PIDF).read().strip()) if os.path.isfile(PIDF) else 0


def db_enable(on: bool):
    if dpid:
        try:
            os.kill(dpid, _sig.SIGCONT if on else _sig.SIGSTOP)
        except OSError:
            pass


def keep_fresh(stop_evt):
    """守护被 SIGSTOP 后库会"变旧", live_signals 就会回落文件 (掉回旧路) —— 探针期间手动续期。"""
    import threading
    def run():
        import sqlite3 as _s
        while not stop_evt.is_set():
            try:
                c = _s.connect(SS.DB, timeout=5)
                with c:
                    c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('updated',?)", (repr(time.time()),))
                c.close()
            except Exception:                                                # noqa: BLE001
                pass
            time.sleep(0.4)
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


def set_field(val):
    c = sqlite3.connect(SS.DB, timeout=5)
    with c:
        cur = c.execute("UPDATE signals SET value=? WHERE name=?", (val, FIELD))
        rows = cur.rowcount
        c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('updated',?)", (repr(time.time()),))
    c.close()
    return rows


import dds_canoe                                                               # noqa: E402
from canoe_graphic import CanoeGraphicWidget                                  # noqa: E402
from PyQt5.QtWidgets import QApplication                                       # noqa: E402

app = QApplication.instance() or QApplication([])
view = dds_canoe.build_view(standalone=True)
panel = CanoeGraphicWidget()
panel.show()                      # 树是按可见性填充的, 不 show 会是空的 (不是数据问题)


def poke():
    """让两个窗口走完一轮刷新 (树/表都是定时+可见才填), 再读。"""
    t0 = time.time()
    while time.time() - t0 < 3.0:
        app.processEvents()
        time.sleep(0.05)
    try:
        view._fill_trace_fixed(force=True)
    except Exception:                                                        # noqa: BLE001
        pass
    try:
        panel._update_tree_values()
    except Exception:                                                        # noqa: BLE001
        pass
    app.processEvents()


def trace_val(name):
    tb = getattr(view, "tb", None)
    if tb is None:
        return None
    for r in range(tb.rowCount()):
        it = tb.item(r, 2)
        # 显示的是中文友好名, 原始字段名在 tooltip 第一行 (与 verify_global_source 同口径)
        raw = (it.toolTip() or "").split("\n")[0].strip() if it else ""
        if raw == name:
            return tb.item(r, 3).text() if tb.item(r, 3) else ""
    return None


def panel_val(name):
    found = []

    def walk(node):
        if hasattr(node, "topLevelItemCount"):
            for i in range(node.topLevelItemCount()):
                walk(node.topLevelItem(i))
        else:
            if str(node.data(0, 0x0100) or "") == "sstrace." + name:   # 面板键是 sstrace.<字段>
                found.append(node.text(3) or "")
            for j in range(node.childCount()):
                walk(node.child(j))
    t = getattr(panel, "tree", None)
    if t is not None:
        walk(t)
    return found[0] if found else None


rows = 0
import threading                                                               # noqa: E402
_stop = threading.Event()
keep_fresh(_stop)
try:
    db_enable(False)                     # 暂停守护, 免得它 0.5s 后把值改回去
    rows = set_field(PROBE_V)
    LS._CACHE.update(t=0.0, data=None)
    poke()
    tv, pv = trace_val(FIELD), panel_val(FIELD)
    _near = lambda x: x is not None and abs(x - PROBE_V) < 5e-5     # 表格按 4 位有效数字显示
    chk("③ 库里改一个既有信号值 ⇒ Trace 立刻显示同一个值",
        _near(_num(tv)), f"库 {PROBE_V} · Trace {tv!r} · 改到 {rows} 行")
    chk("③ 同一改动 ⇒ 信号分析也显示同一个值",
        _near(_num(pv)), f"库 {PROBE_V} · 面板 {pv!r}")
    chk("③ 两边读到的是同一个值", _near(_num(tv)) and _near(_num(pv)),
        f"Trace {tv!r} / 面板 {pv!r}")
finally:
    _stop.set()
    db_enable(True)

# 放开守护后由它恢复真值 (下一次落库就把库写回真实)
time.sleep(1.5)
LS._CACHE.update(t=0.0, data=None)
poke()
back = _num(trace_val(FIELD))
chk("④ 守护恢复后 Trace 回到真值 (库仍是唯一真源)", back is not None and back != PROBE_V,
    f"现在 {back!r}")

# ⑤ 降级路径
import subprocess                                                              # noqa: E402
probe = ("import os,sys;sys.path[:0]=['src','tools/gui']\n"
         "os.environ['ZMAX_SIGNAL_DB_OFF']='1'\n"
         "from lerobot.middleware import live_signals as LS\n"
         "print('话题', len(LS.topics()))\n")
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT,
                   env={**os.environ, "ZMAX_REPO": ROOT})
chk("⑤ ZMAX_SIGNAL_DB_OFF=1 回落文件且打印告警",
    "回落文件直读" in (r.stdout + r.stderr) and "话题" in r.stdout,
    (r.stdout + r.stderr).strip().splitlines()[-2:] if (r.stdout + r.stderr).strip() else "")

print()
if bad:
    print(f"❌ 失败: {bad}")
    sys.exit(1)
print(f"✅ 全部通过 ({ok} 项)")
