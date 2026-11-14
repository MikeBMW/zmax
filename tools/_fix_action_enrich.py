#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 action_bus 的对账字段抽成 _enrich(), from_action / from_traj215 共用一份。"""
import io
import re

P = "/home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/action_bus.py"
s = io.open(P, encoding="utf-8").read()

# 1) 把 from_action 里那段内联块换成 _enrich(out)
start = s.index("    # 🎯 2026-11-14 老倪「还是没有对应上」")
end = s.index("    _mm, _age = grip_meas()", start)
s = s[:start] + "    out = _enrich(out)\n" + s[end:]

# 2) 插入 _enrich 定义(放在 from_action 之前)
helper = '''def _enrich(act):
    """给 action 补**对账用**字段 —— 老倪拿 action 和机器人屏幕对数字时缺的就是这些。

    pose_now   : 机器人此刻实测位姿(与 action 同格式, 带 age_s)
    delta_mm   : action(目标) − 实测, 三个分量; 差多少一目了然
    i_nearest  : 实测位姿最近的 215 点(仅参考; 轨迹来回经过同一片区域时会跳, 不作判据)
    dispatch   : 运行中的派单事实 {start, n, done, cursor}
    """
    if not act:
        return act
    try:
        _t = read_pose()
        if _t:
            act["pose_now"] = _t
            if act.get("x") is not None and _t.get("x") is not None:
                act["delta_mm"] = [round(float(act["x"]) - float(_t["x"]), 2),
                                   round(float(act["y"]) - float(_t["y"]), 2),
                                   round(float(act["z"]) - float(_t["z"]), 2)]
            act["i_nearest"] = nearest_index()
        _st = _traj_state()
        if _st.get("running"):
            act["dispatch"] = {"start": _st.get("start"), "n": _st.get("n"),
                               "done": _st.get("done"), "cursor": _st.get("cursor")}
    except Exception:                                                      # noqa: BLE001
        pass
    return act


def from_action(act, deny=""):'''
s = s.replace("def from_action(act, deny=\"\"):", helper, 1)

io.open(P, "w", encoding="utf-8").write(s)
print("ok · _enrich 已就位, 行数", len(s.splitlines()))
