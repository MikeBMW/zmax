#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 状态空间 → AR 场景 指令通道 (🥽 虚拟臂驱动, 真机零指令)

链路:  🏭 UPH 节拍循环器(n_uph_tact) --写--> zmax_data/ss_live/ar_cmd.json
        --读--> 8797 GET /api/ar/cmd --轮询--> 页面 plantAtAR() 驱动虚拟臂

判据:
  ① 节点按拍写出 ar_cmd.json, 字段齐全 (seq/mod/kind/a/b/u/t_seg)
  ② 段序号推进, u 恒在 [0,1], 件号在 1..14
  ③ 8797 /api/ar/cmd 读到 fresh=true 且 a/b/u 有效
  ④ 停写 >3s 后 fresh=false (页面必须回落自身播放, 不能卡死)
  ⑤ 全程无真机下发: exec_switches.real_auth 仍为 False, ctl_auth 未 armed
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = "/home/ubuntu/zmax"
os.environ["ZMAX_UPH_AR_PUB"] = "1"          # 开: 节点每拍写渲染指令
os.environ["ZMAX_UPH_SPEED"] = "8"           # 加速 8 倍, 10s 真实 = 80s 虚拟
sys.path.insert(0, os.path.join(REPO, "src"))

from lerobot.middleware.nodes import n_uph as N              # noqa: E402  外壳(走 registry)
from lerobot.engineering.nodes import uph_tact_impl as IMPL   # noqa: E402  真实现

CMD = os.path.expanduser("~/zmax/zmax_data/ss_live/ar_cmd.json")
URL = "http://127.0.0.1:8797/api/ar/cmd"
fails = []


def ck(ok, name, extra=""):
    print("%s %s %s" % ("✅" if ok else "❌", name, ("· " + extra) if extra else ""))
    if not ok:
        fails.append(name)


def get(url):
    with urllib.request.urlopen(url, timeout=8) as r:
        return json.load(r)


# ── 跑 40 拍 ────────────────────────────────────────────────
IMPL.reset()
seqs, us, mods = [], [], []
for _ in range(40):
    N.compute({})
    time.sleep(0.25)
    try:
        d = json.load(open(CMD, encoding="utf-8"))
        seqs.append(d.get("seq"))
        us.append(d.get("u"))
        mods.append(d.get("mod"))
    except Exception:                                        # noqa: BLE001
        pass

d = json.load(open(CMD, encoding="utf-8"))
need = ("seq", "mod", "kind", "a", "b", "u", "t_seg", "src")
miss = [k for k in need if d.get(k) is None]
ck(not miss, "① ar_cmd.json 字段齐全", "缺=%s src=%s" % (miss or "无", d.get("src")))
ck(d.get("src") == "ss_uph_tact", "① 指令来源=节点 ss_uph_tact", str(d.get("src")))

ck(len(set(seqs)) > 8, "② 段序号在推进", "采到 %d 个不同 seq (max=%s)" % (len(set(seqs)), max(seqs)))
ck(all(0.0 <= float(u) <= 1.0 for u in us if u is not None), "② 段内进度 u 恒在 [0,1]",
   "u范围 %.3f~%.3f" % (min(us), max(us)))
ck(all(1 <= int(m) <= 14 for m in mods if m is not None), "② 件号在 1..14",
   "件号范围 %d~%d" % (min(mods), max(mods)))

# ── 接口侧 ─────────────────────────────────────────────────
api = get(URL)
ck(api.get("ok") and api.get("fresh"), "③ /api/ar/cmd fresh=true",
   "age=%ss seq=%s kind=%s" % (api.get("age_s"), api.get("seq"), api.get("kind")))
a, b, u = api.get("a"), api.get("b"), api.get("u")
ck(bool(a) and bool(b) and len(a) == 3 and len(b) == 3, "③ a/b 是 3 维 mm 坐标", "a=%s b=%s u=%s" % (a, b, u))

# ── 过期回落 ───────────────────────────────────────────────
if os.environ.get("ZMAX_SKIP_STALE") == "1":
    print("⏭ ④ 跳过(常驻服务 zmax-ss-canvas-loop 在持续写, 新鲜度由它维持)")
else:
    time.sleep(4.0)
    api2 = get(URL)
    ck(not api2.get("fresh"), "④ 停写 4s 后 fresh=false(页面回落自身播放)",
       "age=%ss note=%s" % (api2.get("age_s"), api2.get("note")))

# ── 真机零指令 ─────────────────────────────────────────────
sw = json.load(open(os.path.expanduser("~/zmax/zmax_data/ss_live/exec_switches.json"), encoding="utf-8"))
auth = subprocess.run(["python3", "/home/ubuntu/zmax/tools/ctl_auth.py", "check"],
                      capture_output=True, text=True, timeout=20).stdout
ck(not sw.get("real_auth"), "⑤ 真机开关仍为关", "real_auth=%s" % sw.get("real_auth"))
_aj = {}
try:
    _aj = json.loads(auth[:auth.rfind("}") + 1])   # 输出=JSON + 末尾一行 check() 摘要
except Exception:                                            # noqa: BLE001
    pass
_armed = _aj.get("armed")
ck(_armed is False, "⑤ ctl_auth 未授权(armed=false)",
   "armed=%s left_s=%s" % (_armed, _aj.get("left_s")))

print()
print("=" * 60)
print("全部通过 ✅" if not fails else "失败 %d 项 ❌ → %s" % (len(fails), fails))
sys.exit(0 if not fails else 1)
