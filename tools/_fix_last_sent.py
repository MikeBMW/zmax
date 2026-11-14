#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「最后真正发出去的那一点」落盘(last_sent.json), 让 action 在轮间空档也显示已发出的点。

老倪 2026-11-14: 「return action 那句我已经停止了, 那再次断点, 不应该是上一次发出的点的位置么?」
  现状: 运行中 exec_index = start+done (已发出的点) ✔;
        但轮与轮之间的空档(容器刚退出、游标已 +1、还没派下一点)会退回 cursor
        ⇒ 那一刻 action 显示的是**下一个待发点**, 与"已发出"相反。
  改法: flow 每成功派单就写 last_sent.json{start,n,ts}; exec_index 在"没在跑"时优先取它。
"""
import io

# ── ① flow: 派单成功后落盘 last_sent ──
PF = "/home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/real_traj_flow.py"
s = io.open(PF, encoding="utf-8").read()

old = '''        if r.get("ok"):
            self.rounds += 1
            self._post_cursor = self.cursor
            self._post_t = now'''
new = '''        if r.get("ok"):
            self.rounds += 1
            self._post_cursor = self.cursor
            self._post_t = now
            self._mark_sent(body)'''
assert old in s, "flow ok 分支锚点没找到"
s = s.replace(old, new, 1)

helper = '''
    def _mark_sent(self, body):
        """记下**最后真正发出去的那一点**(断点/空档时 action 要显示它, 不是下一个待发点)。"""
        try:
            d = {"start": int(body.get("start") or 0), "n": int(body.get("n") or 1),
                 "cursor": int(self.cursor), "round": int(self.rounds), "ts": time.time()}
            tmp = SENT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(tmp, SENT)
        except Exception:                                          # noqa: BLE001
            pass

'''
anchor = "    def _send(self" if "    def _send(self" in s else None
if anchor is None:
    # 退回: 插在 class 里第一个 def 之前不容易, 直接挂在 _mark_sent 调用点上方的方法前
    import re
    m = re.search(r"\n    def [a-zA-Z_]+\(", s)
    assert m, "找不到方法插入点"
    s = s[:m.start()] + "\n" + helper.rstrip("\n") + s[m.start():]
else:
    s = s.replace(anchor, helper.strip("\n") + "\n\n" + anchor, 1)

# 常量 SENT(与 POSE 同一目录)
old_c = 'POSE = os.path.join(REPO, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")'
new_c = old_c + '\nSENT = os.path.join(REPO, "zmax_data", "rokae_sdk", "last_sent.json")'
assert old_c in s
s = s.replace(old_c, new_c, 1)

io.open(PF, "w", encoding="utf-8").write(s)
print("ok · flow 会写 last_sent.json")

# ── ② action_bus: exec_index 空档时取 last_sent ──
PB = "/home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/action_bus.py"
b = io.open(PB, encoding="utf-8").read()

old_e = '''    st = _traj_state()
    if not st.get("running"):
        return None
    fr = _frames()'''
new_e = '''    st = _traj_state()
    fr = _frames()
    if not st.get("running"):
        # 轮间空档: 用**最后真正发出去**的那一点, 而不是 cursor(那是下一个待发点)
        try:
            d = json.load(open(_SENT, encoding="utf-8"))
            if time.time() - float(d.get("ts") or 0) < 300.0:
                return max(0, min(int(d.get("start") or 0), len(fr) - 1))
        except Exception:                                          # noqa: BLE001
            pass
        return None'''
assert old_e in b, "action_bus exec_index 锚点没找到"
b = b.replace(old_e, new_e, 1)

# 常量 _SENT
old_l = 'LATEST = os.path.join(_ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")'
if old_l in b:
    b = b.replace(old_l, old_l + '\n_SENT = os.path.join(_ROOT, "zmax_data", "rokae_sdk", "last_sent.json")', 1)
else:
    raise SystemExit("找不到 LATEST 常量, 请手工加 _SENT")

io.open(PB, "w", encoding="utf-8").write(b)
print("ok · action_bus 空档取 last_sent")
