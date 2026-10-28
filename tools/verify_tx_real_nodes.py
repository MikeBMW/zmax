# -*- coding: utf-8 -*-
"""判据: Trace / 信号分析的 **Tx 列只能是画布节点名 (或 —)**, 不许出现进程/服务/.py 名字。

老倪 2026-10-17: 「万有引力表进程，怎么能在 Tx 的发送节点呢？也没有万有引力这个节点啊」

口径 (与 Rx 一致): Tx = 画布节点名; 没有画布节点 ⇒ "—"; 进程名只能出现在"来源", 不许进 Tx。
"""
import json
import os
import re
import sys

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


from lerobot.middleware import attribution as A                               # noqa: E402

# 节点名唯一依据 = 画布/工程库经 attribution 读出来的那份 (面板与 Trace 用的是同一个字典)
NAMES = set(str(v) for v in (A._load_nodes() or {}).values() if v)
chk("画布节点名读到", len(NAMES) > 50, f"{len(NAMES)} 个")

from lerobot.middleware import attribution as A                               # noqa: E402
from lerobot.middleware import live_signals as LS                             # noqa: E402

snap = LS.topics()
tx_count = {}
for topic, rec in snap.items():
    pre = A.LIVE_PREFIX.get(topic)
    for name in (rec.get("fields") or {}):
        k = f"{pre}.{name}" if pre else str(name)
        t = A.tx_of(k)
        tx_count[t] = tx_count.get(t, 0) + 1

BANNED = re.compile(r"\.py\b|进程|服务|bridge|tap|\d+Hz", re.I)
leak = [t for t in tx_count if BANNED.search(t)]
chk("Tx 里没有进程名/服务名/.py", not leak, f"{len(leak)} 种 {leak[:4]}")

# 允许三种: 画布节点名 / "—" / 原子技能阶段标签 (① 接近 · SK01, 早前按老倪要求加的);
# 入端口行会是多个上游节点 "A / B / C" —— 逐段校验。
STAGE = re.compile(r"^[①-⑧]\s*\S+\s*·\s*SK0[1-8]$")


def _ok_tx(t):
    if t in ("—", ""):
        return True
    return all(part.strip() in NAMES or STAGE.match(part.strip())
               for part in str(t).split(" / ") if part.strip())


strangers = [t for t in tx_count if not _ok_tx(t)]
chk("Tx 全是画布节点名 / 阶段标签 / —", not strangers, f"{len(strangers)} 种 {strangers[:4]}")

grav = {t: n for t, n in tx_count.items() if "引力" in t or "gravity" in t.lower()}
chk("万有引力表信号不再挂进 Tx", not grav, f"{grav}")

# UI 侧复核: Trace 表格里 Tx 列 (第 7 列) 的取值也必须满足同一口径
import dds_canoe                                                              # noqa: E402
from PyQt5.QtWidgets import QApplication                                      # noqa: E402

app = QApplication.instance() or QApplication([])
v = dds_canoe.build_view(standalone=True)
try:
    import time as _t
    _t0 = _t.time()
    while _t.time() - _t0 < 3.0:
        app.processEvents()
        _t.sleep(0.05)
    v._fill_trace_fixed(force=True)
    app.processEvents()
except Exception:                                                             # noqa: BLE001
    pass
ui_tx = set()
for r in range(v.tb.rowCount()):
    it = v.tb.item(r, 7)
    if it:
        ui_tx.add(it.text())
ui_bad = sorted(t for t in ui_tx if BANNED.search(t))
chk("Trace 表格 Tx 列无进程名", not ui_bad, f"{ui_bad[:4]}")
ui_strange = sorted(t for t in ui_tx if not _ok_tx(t))
chk("Trace 表格 Tx 列全是节点名 / 阶段标签 / —", not ui_strange, f"{ui_strange[:4]}")

print()
if bad:
    print(f"❌ 失败: {bad}")
    sys.exit(1)
print(f"✅ 全部通过 ({ok} 项) · Tx 取值 {len(tx_count)} 种 · Trace 行 {v.tb.rowCount()}")
