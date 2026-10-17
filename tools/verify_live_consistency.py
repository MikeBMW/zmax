# -*- coding: utf-8 -*-
"""判据: 数据空间 Trace 必须**实时**且与「信号分析」窗口同源同值。

老倪 2026-10-17: 「数据空间的信号, 怎么不动呢? 要实时运行啊」
             + 「保证全局数据空间的信号, 与信号分析窗口的数据, 保持一致」
"""
import sys, os, time, json, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from lerobot.middleware import live_signals as L

fails = []
def ck(name, ok, info=""):
    print(("%s %s" % ("✅" if ok else "❌", name)) + ((" · " + info) if info else ""))
    if not ok:
        fails.append(name)

# ① 同源: 数据空间读的文件 == 信号分析窗口 SOURCES 里那三份
src = open("tools/gui/canoe_graphic.py", encoding="utf-8").read()
for key, (rel, tag, _k) in L.SOURCES.items():
    ck("信号分析窗口读 %s" % rel, rel in src, key)

# ② 实时: 三份文件都在 3s 内更新
tp = L.topics()
ck("实时话题 ≥3", len(tp) >= 3, str({k: len(v['fields']) for k, v in tp.items()}))
ck("帧龄都 <3s", all(v["age_s"] < 3.0 for v in tp.values()),
   str({k: v["age_s"] for k, v in tp.items()}))

# ③ 同值: 直接读文件 vs provider, 逐信号相等
p = os.path.join(L.ROOT, "zmax_data/ss_live/trace_live.json")
raw = json.load(open(p, encoding="utf-8"))
prov = tp["zmax/ss_state"]["fields"]
mism = [(k, raw.get(k), prov.get(k)) for k in ("末端_x", "末端_y", "光模块头到孔_mm")
        if k in raw and abs(float(raw[k]) - float(prov.get(k, 1e9))) > 1e-9]
ck("与文件逐信号相等", not mism, str(mism))

# ④ 会动: 1.2s 后同名字段值发生变化
a = dict(L.topics()["zmax/ss_state"]["fields"])
time.sleep(1.3)
b = dict(L.topics()["zmax/ss_state"]["fields"])
chg = [k for k in a if k in b and a[k] != b[k]]
ck("1.3s 内有信号在变 (≥10 个)", len(chg) >= 10, "%d 个, 例: %s" % (len(chg), chg[:4]))

# ⑤ 名字口径: Signal 用源文件真实键 (不是另起中文名)
ck("Signal 保留源键 (末端_x 等)", "末端_x" in prov and "估计误差_mm" in prov,
   str([k for k in list(prov)[:5]]))

print("\n%s" % ("✅ 全部通过" if not fails else "❌ 失败: %s" % fails))
sys.exit(0 if not fails else 1)
