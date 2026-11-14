#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 executor 的 [action] 打印行补上「这一拍真正下发的口径」(直驱 vs 215点)。"""
import io

P = "/home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/execution.py"
s = io.open(P, encoding="utf-8").read()

old = '''                      ("%.2f" % d_mm) if d_mm is not None else "?",
                      g if g is not None else "?", gs))'''
new = '''                      ("%.2f" % d_mm) if d_mm is not None else "?",
                      g if g is not None else "?", gs)
                  + (" | 下发=%s" % _eff_out(act)))'''
assert old in s, "锚点没找到"
s = s.replace(old, new, 1)

helper = '''

def _eff_out(act):
    """这一拍真正下发的口径: 直驱(ss) 还是 215 点回放。

    为什么要打: 执行器 src=ss 时, 节点里的直驱护栏可能没放行 ⇒ 实际落盘/下发的是 215 点。
    终端只看 src 会以为下发的是直驱位姿, 于是又对不上。这里给出护栏的判决。
    """
    try:
        from lerobot.policies.left_right.state_space import direct_drive_guard as _g
        v = _g.last() or {}
        if str(act.get("src")) == "ss" and not v.get("allow"):
            return "215点(护栏 mode=%s ok=%s/%s)" % (v.get("mode"), v.get("ok_ticks"), v.get("need"))
        return "直驱/ss"
    except Exception:                                       # noqa: BLE001
        return "?"
'''
assert "\n\nclass Action(dict):" in s
s = s.replace("\n\nclass Action(dict):", helper + "\n\nclass Action(dict):", 1)

io.open(P, "w", encoding="utf-8").write(s)
print("ok · 已加 下发口径")
