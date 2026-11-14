#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据 t_act_dim / t_act_pass: 认两条下发口径(直驱4维 / 215点6维)。"""
import io

P = "/home/ubuntu/zmax/src/lerobot/verification/verification_layer.py"
s = io.open(P, encoding="utf-8").read()

old = '''    def t_act_dim(self, np):
        ex = self._exec().RobotExecutor()
        u = np.asarray(ex.execute(np.zeros(4)), float)
        return u.shape[0] == 4, f"执行器输出 {u.shape[0]}D"'''
new = '''    def t_act_dim(self, np):
        ex = self._exec().RobotExecutor()
        a = ex.execute(np.zeros(4))
        u = np.asarray(a, float)
        src = (a.get("src") if isinstance(a, dict) else None) or "?"
        kind = {4: "直驱4维速度", 6: "215点6维关节"}.get(u.shape[0], "非法维度")
        return u.shape[0] in (4, 6), f"执行器输出 {u.shape[0]}D ({src} · {kind})"'''
assert old in s
s = s.replace(old, new, 1)

old2 = '''    def t_act_pass(self, np):
        ex = self._exec().RobotExecutor()
        u = np.asarray(ex.execute(np.array([0.1, 0.2, -0.1, 0.5])), float)
        return bool(np.isfinite(u).all()) and u.shape[0] == 4, f"指令透传有限: {np.round(u,3)}"'''
new2 = '''    def t_act_pass(self, np):
        ex = self._exec().RobotExecutor()
        a = ex.execute(np.array([0.1, 0.2, -0.1, 0.5]))
        u = np.asarray(a, float)
        src = (a.get("src") if isinstance(a, dict) else None) or "?"
        return (bool(np.isfinite(u).all()) and u.shape[0] in (4, 6)), f"指令透传({src}): {np.round(u,3)}"'''
assert old2 in s
s = s.replace(old2, new2, 1)

io.open(P, "w", encoding="utf-8").write(s)
print("ok · 判据已认两条口径")
