# -*- coding: utf-8 -*-
"""⚙️ 动作执行器 (L2 收口 · 授权/闸/到位) — 读 l2_daemon 真值状态与最近事件

老倪 2026-10-28「把执行链上的节点按顺序迁出来」——
  实现正文从 registry 大文件 nodes/library.py 迁到本文件；library.node_exec 只剩薄壳转调，
  右键「打开源代码」直接落到本文件 `run()`（registry key = `n_exec`）。

执行链位置: 运动规划 → ⚙️ 动作执行器 (L2 收口 · 授权/闸/到位) → 动作执行器 → 机器人执行器
铁律: 只读真值 / 不造数 / 不下发动作 (下发只走 l2_daemon + 8793 授权)。
本文件正文与迁移前逐字一致 (仅补显式 import 与文件头)。
"""
from __future__ import annotations


def run(ctx):
    import json as _json
    import os as _os
    import time as _time
    out = {"node": "n_exec"}
    base = _os.path.expanduser("~/zmax/zmax_data/ss_live")
    sp = _os.path.join(base, "exec_state.json")
    try:
        st = _json.load(open(sp, encoding="utf-8"))
        age = _time.time() - float(st.get("t_pub") or st.get("t") or 0.0)
        out.update({"phase": st.get("phase"), "seg": st.get("seg"), "n_seg": st.get("n_seg"),
                    "skill": st.get("skill"), "target": st.get("target"), "pos": st.get("pos"),
                    "residual_mm": st.get("residual_mm"), "speed_mm_s": st.get("speed_mm_s"),
                    "transport": st.get("transport"), "blocked_by": st.get("blocked_by") or "",
                    "auth_epoch": st.get("auth_epoch"), "age_s": round(age, 2)})
    except Exception as e:
        out["state_error"] = "%s: %s" % (type(e).__name__, str(e)[:80])
    try:
        ev = _os.path.join(base, "exec_events.jsonl")
        tail = []
        with open(ev, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            for ln in f.read().decode("utf-8", "ignore").splitlines()[-3:]:
                try:
                    tail.append(_json.loads(ln))
                except Exception:
                    pass
        out["last_events"] = tail
    except Exception:
        pass
    # 2026-10-31: 白名单里带上 n_exec 后这个节点每拍(10Hz)都跑, 直打一行会把终端刷满
    #   (老倪「不允许再有 tick」)。改成: 状态键变了立刻打 + 最长 5s 一行心跳; 调试时仍看得到每段变化。
    _k = (out.get("phase"), out.get("seg"), out.get("n_seg"), out.get("target"),
          out.get("blocked_by"), out.get("state_error"))
    _now = _time.time()
    if _k != _PRINT_LAST["k"] or _now - _PRINT_LAST["t"] >= 5.0:
        _PRINT_LAST.update(k=_k, t=_now)
        print("[执行器节点] " + _json.dumps(out, ensure_ascii=False)[:400])
    return out


_PRINT_LAST = {"k": None, "t": 0.0}
