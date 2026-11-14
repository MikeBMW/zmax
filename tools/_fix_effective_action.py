#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""让 execute() 返回的 action 就是**真正下发的那一份**(直驱闸未放行 ⇒ 直接给 215 点)。

背景(老倪 2026-11-14): 「self._print_action(action, chk) 这里断, 也没有对上」——
  断点里的 action 是执行器算的**直驱位姿(实测+u·dt)**, 而节点层因为护栏没放行,
  实际下发的是 **215 点回放** ⇒ 断点里的数与机器人永远对不上。
改法: 把"换口径"这一步从节点层前移到执行器, 断点看到的 action 即真机在执行的那份。
可关: ZMAX_EXEC_EFFECTIVE=0
"""
import io

P = "/home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/execution.py"
s = io.open(P, encoding="utf-8").read()

# ── ① 215 点 frames 加 mtime 缓存(每拍都要取, 不能每拍 parse 1MB json) ──
old_load = '''        d = json.load(open(_TRAJ_JSON, encoding="utf-8"))
        fr = d.get("frames") or []
        if not fr:
            return None'''
new_load = '''        fr = _traj_frames()
        if not fr:
            return None'''
assert old_load in s
s = s.replace(old_load, new_load, 1)

cache_fn = '''

_TRAJ_FRAMES = {"mt": -1.0, "frames": []}


def _traj_frames():
    """215 点 frames —— 按 mtime 缓存(单线程每拍都要取, 不能每拍 parse 1MB)。"""
    try:
        mt = os.path.getmtime(_TRAJ_JSON)
    except Exception:                                          # noqa: BLE001
        return []
    if _TRAJ_FRAMES["mt"] == mt and _TRAJ_FRAMES["frames"]:
        return _TRAJ_FRAMES["frames"]
    try:
        d = json.load(open(_TRAJ_JSON, encoding="utf-8"))
        fr = d.get("frames") or []
    except Exception:                                          # noqa: BLE001
        return []
    _TRAJ_FRAMES["mt"], _TRAJ_FRAMES["frames"] = mt, fr
    return fr


def traj215_target(cursor=None):'''
assert "\n\ndef traj215_target(cursor=None):" in s
s = s.replace("\n\ndef traj215_target(cursor=None):", cache_fn, 1)

# ── ② execute(): 正常档算完 ss 后, 先换成本拍真正下发的口径 ──
old_call = '''        action = self._act_ss(action, chk)
        self._print_action(action, chk)
        return action'''
new_call = '''        action = self._act_ss(action, chk)
        # 🎯 2026-11-14 老倪「这里断也没有对上」：直驱闸没放行时，节点层会把直驱换成 215 点。
        #    换口径前移到执行器 ⇒ 断点里看到的 action 就是**真正下发**的那份，不会再看错。
        action = self._effective(action, chk)
        self._print_action(action, chk)
        return action'''
assert old_call in s
s = s.replace(old_call, new_call, 1)

# ── ③ _effective() ──
eff = '''
    @staticmethod
    def _effective(act, chk):
        """把「本拍真正下发的 action」算出来(与节点层同一判断, 只此一处口径)。

        · 直驱闸放行(guard.allow) ⇒ 保持 src=ss 的直驱位姿
        · 没放行 ⇒ 换成 215 点当前点(关节+位姿+夹爪计划), 并把直驱速度留在 u 里溯源
        关掉: ZMAX_EXEC_EFFECTIVE=0(退回"执行器只出直驱, 由节点层换口径"的旧行为)
        """
        if str(os.environ.get("ZMAX_EXEC_EFFECTIVE", "1")).strip() in ("0", "false", "False"):
            return act
        if str(act.get("src")) != "ss":
            return act
        try:
            from . import direct_drive_guard as _g
            v = _g.last() or {}
        except Exception:                                          # noqa: BLE001
            v = {}
        if v.get("allow"):
            return act
        _t = traj215_target()
        if _t is None:
            return act
        _a = RobotExecutor._act_traj215(_t, chk)
        _why = "215 点回放 · 直驱闸未放行(mode=%s ok=%s/%s)" % (
            v.get("mode"), v.get("ok_ticks"), v.get("need"))
        _a["why"] = _why
        _a["fallback"] = _a.get("fallback") or "直驱闸未放行 ⇒ 215 点"
        _a["dd_u"] = [float(x) for x in (act.get("u") or [])]      # 保留直驱速度, 便于溯源
        _a["dd_pose"] = act.get("pose")
        _a["total"] = _t.get("total")
        return _a
'''
anchor = '''    # ─────────────────────── 🖨 终端可见的实时位姿(return action 之前) ───────────────────────'''
assert anchor in s
s = s.replace(anchor, eff.strip("\n") + "\n\n" + anchor, 1)

io.open(P, "w", encoding="utf-8").write(s)
print("ok · _effective 已接入, _traj_frames 缓存已加")
