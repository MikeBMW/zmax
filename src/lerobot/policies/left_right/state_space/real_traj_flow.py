# -*- coding: utf-8 -*-
"""real_traj_flow.py — 真机 215 点全流程自动执行 (状态空间工程内, 非临时脚本)

老倪 2026-11-14:「以当前机器人的运行为基础, 运行 start.py, 单步或 F5 连续运行, 就完成真实轨迹 215 步。
  以前要前端手动输入 215 个点再点运行; 现在从 VSCode 跑就自动全流程, 只要前端授权就自动执行。」

设计口径 (为什么这样写):
  · 执行腿只有一条: 8797 `/api/arm/step_traj`(容器直连控制器 + MoveAbsJ 逐点 + 到位才下一点)。
    这里**不自己造下发路径**, 只做"分段 + 授权轮询 + 进度取证", 免得出现第二条真源。
  · 授权是**唯一开关**: 每个分段下发前都读 `zmax_data/ctl_auth.json`; 没授权就停在这一步等,
    写状态给前端看(`等授权`), 授权窗口一开就自动往下走 —— 不需要人再点。
  · 全同步、单线程: 无 thread、无 timer。tick() 由引擎/入口每拍调用一次(默认 10Hz),
    单步调试时你停在任何一行, 机器人也停在原地(没有后台线程偷偷推进)。
  · 分段: 每轮 10 点(可调), 一轮结束看 status 再决定下一轮; 任一段失败按 stage 处理:
      jump  → 调 align 把游标挪到真机最近点(防瞬移)
      auth  → 回 WAIT_AUTH 等授权
      end   → DONE
      busy  → 等上一轮结束
状态文件: zmax_data/ss_live/traj_flow.json (给 8797 /api/arm/traj_flow 与页面横幅读)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

def _find_repo() -> str:
    """从本文件往上找仓库根(以 tools/web/real_traj_joints.json 为锚, 不数层级)。"""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isfile(os.path.join(d, "tools", "web", "real_traj_joints.json")):
            return d
        d = os.path.dirname(d)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", ".."))


REPO = _find_repo()

PLAN = os.path.join(REPO, "tools", "web", "real_traj_joints.json")
GRIP = os.path.join(REPO, "tools", "web", "real_traj_grip.json")
AUTH = os.path.join(REPO, "zmax_data", "ctl_auth.json")
STS = os.path.join(REPO, "zmax_data", "ss_live", "traj_flow.json")
POSE = os.path.join(REPO, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
SENT = os.path.join(REPO, "zmax_data", "rokae_sdk", "last_sent.json")
API = os.environ.get("ZMAX_AR_API", "http://127.0.0.1:8797")


def _say(msg: str) -> None:
    try:
        import sys
        sys.__stdout__.write(msg + "\n")
        sys.__stdout__.flush()
    except Exception:                                                   # noqa: BLE001
        pass


def _get(path: str, timeout: float = 6.0):
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _post(path: str, body: dict, timeout: float = 20.0):
    data = json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def auth_state() -> dict:
    """授权状态 —— 唯一依据 tools/ctl_auth.py(与 8793 页面/执行器同一份)。

    认两种形态: window(30 分钟到点失效) / debug(调试档, 无时间限制)。
    """
    try:
        import importlib.util as _ilu
        _sp = _ilu.spec_from_file_location("_zmax_ctl_auth",
                                           os.path.join(REPO, "tools", "ctl_auth.py"))
        _ca = _ilu.module_from_spec(_sp)
        _sp.loader.exec_module(_ca)
        return _ca.info()
    except Exception as e:                                              # noqa: BLE001
        return {"armed": False, "debug": False, "mode": "window", "left_s": 0.0,
                "epoch": 0, "err": "%s: %s" % (type(e).__name__, str(e)[:60])}


def _auth_left() -> float:
    """授权剩余秒数; 调试档 = inf; <=0 或已撤销 = 未授权 (fail-closed)。"""
    st = auth_state()
    if st.get("armed") and st.get("debug"):
        return float("inf")
    return float(st.get("left_s") or 0.0)


def auth_label() -> str:
    """一句人话: 已授权(调试·无限) / 已授权(剩 N 分) / 未授权(过期 N 分)。"""
    st = auth_state()
    if st.get("armed") and st.get("debug"):
        return "已授权(调试档 · 无时间限制) · epoch=%s" % st.get("epoch")
    if st.get("armed"):
        left = float(st.get("left_s") or 0.0)
        return "已授权(剩余 %.0f 分 %.0f 秒) · epoch=%s" % (left // 60, left % 60, st.get("epoch"))
    left = float(st.get("left_s") or 0.0)
    if st.get("revoked_at"):
        return "未授权(已被撤销)"
    return "未授权(授权窗已过期 %.0f 分)" % ((0 - left) / 60.0) if left <= 0 and st.get("epoch") else "未授权(从未授权)"


def _pose():
    try:
        d = json.load(open(POSE, encoding="utf-8"))
        p = d.get("tcp") or d.get("pose") or []
        j = d.get("joint") or d.get("joints") or []
        age = time.time() - float(d.get("ts") or 0)
        return {"tcp_mm": [round(float(v) * 1000.0, 1) for v in p[:3]] if len(p) >= 3 else None,
                "joint_deg": [round(float(v) * 57.2958, 2) for v in j[:6]] if len(j) >= 6 else None,
                "age_s": round(age, 2)}
    except Exception:                                                   # noqa: BLE001
        return {"tcp_mm": None, "joint_deg": None, "age_s": None}


class RealTrajFlow:
    """215 点全流程 (授权即跑)。phase: WAIT_AUTH → RUN → DONE / ABORT。"""


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
    def __init__(self, chunk: int = 10, speed: float = 20.0, dry: bool = False,
                 dwell_ms: int = 120):
        self.chunk = max(1, int(chunk))
        self.speed = float(speed)
        self.dwell_ms = int(dwell_ms)
        self.dry = bool(dry)
        self.phase = "WAIT_AUTH"
        self.cursor = 0
        self.total = 0
        self.rounds = 0
        self.last_msg = "启动: 等前端授权(8793 『🔓 授权真动』两步确认)"
        self.t_last_post = 0.0
        self.t_last_poll = 0.0
        self.done = False
        self._reset_tried = False
        self._post_cursor = -1          # 上一次下发时所在的游标(防同一段重复下发)
        self._post_t = 0.0
        self.keep = os.environ.get("ZMAX_TRAJ_KEEP") == "1"      # 不重置: 从游标继续
        try:
            self.total = len((json.load(open(PLAN, encoding="utf-8")) or {}).get("frames") or [])
        except Exception:                                               # noqa: BLE001
            self.total = 0
        self._dump()
        _say("🤖 全流程: 轨迹 %d 点 · 每轮 %d 点 · 速度 %.0f%% · %s"
             % (self.total, self.chunk, self.speed, "演练(dry)" if self.dry else "真机"))

    # ---------- 取证 ----------
    def _dump(self) -> None:
        try:
            os.makedirs(os.path.dirname(STS), exist_ok=True)
            snap = {"phase": self.phase, "cursor": self.cursor, "total": self.total,
                    "rounds": self.rounds, "chunk": self.chunk, "speed": self.speed,
                    "dry": self.dry, "last_msg": self.last_msg,
                    "auth_left_s": (None if _auth_left() == float("inf")
                                    else round(max(0.0, _auth_left()), 1)),
                    "auth_mode": auth_state().get("mode"),
                    "auth_label": auth_label(),
                    "pose": _pose(), "ts": time.time(),
                    "src": "src/lerobot/policies/left_right/state_space/real_traj_flow.py"}
            tmp = STS + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False)
            os.replace(tmp, STS)
        except Exception:                                               # noqa: BLE001
            pass

    # ---------- 每拍 ----------
    def tick(self) -> None:
        if self.done:
            return
        now = time.time()
        st = {}
        if now - self.t_last_poll >= 1.0:                # 1Hz 看执行腿状态
            self.t_last_poll = now
            try:
                st = _get("/api/arm/step_traj/status") or {}
            except Exception as e:                                       # noqa: BLE001
                st = {"_err": "%s: %s" % (type(e).__name__, str(e)[:60])}

        if st.get("running"):
            self.phase = "RUN"
            self.cursor = int(st.get("cursor") or self.cursor)
            self.last_msg = "运行中: 第 %d/%d 点 (本轮 %s/%s)" % (
                self.cursor + 1, self.total, st.get("done"), st.get("n"))
            self._dump()
            return

        if st.get("cursor") is not None:
            _c = int(st.get("cursor") or 0)
            if not st.get("running") and _c + 2 < self.cursor:
                # 🔴 服务端游标回退(align/复位)后必须跟着退: 原来只做 max(), flow 会永远超前于 8797,
                #    于是每轮都判 jump → align → 服务端还在原地 ⇒ 死循环, 臂一步不动(2026-11-14 实测)。
                self.cursor = _c
                self._post_cursor = -1
            else:
                self.cursor = max(self.cursor, _c)
        if not st.get("running") and st.get("done"):
            # 演练/单轮结束时 8797 只在真机模式下推进 cursor ⇒ 这里按 start+done 兜底推进
            self.cursor = max(self.cursor, int(st.get("start") or 0) + int(st.get("done") or 0))
        if (self.total and self.cursor >= self.total and not self._reset_tried
                and not self.keep):
            # 走完一轮了: 老倪要的是"从 VSCode 跑一遍完整 215 步" ⇒ 游标回起点(这一轮只做一次)
            self._reset_tried = True
            try:
                rr = _post("/api/arm/step_traj", {"reset": True})
                self.cursor = 0
                self.last_msg = "游标回起点, 准备整轮 215 点: %s" % (rr.get("msg") or "")
                _say("↺ " + self.last_msg)
                self._dump()
                return
            except Exception as e:                                       # noqa: BLE001
                self.last_msg = "重置失败: %s" % str(e)[:70]
        if self.total and self.cursor >= self.total:
            if self.phase != "DONE":
                self.phase = "DONE"
                self.last_msg = "全流程完成: %d/%d 点 (共 %d 轮)" % (self.cursor, self.total, self.rounds)
                _say("✅ " + self.last_msg)
                self._dump()
            return

        # 未授权 ⇒ 停在原地等(不重发, 不空转)
        left = _auth_left()
        if not self.dry and left <= 0:
            if self.phase != "WAIT_AUTH":
                _say("⏳ 等授权: 剩余 %.0fs · 当前第 %d/%d 点" % (left, self.cursor + 1, self.total))
            self.phase = "WAIT_AUTH"
            self.last_msg = "等授权(8793 『🔓 授权真动』· 目前第 %d/%d 点)" % (
                self.cursor + 1, max(1, self.total))
            self._dump()
            return

        # 授权有效 ⇒ 继续下一段 (限频 + 防重复: 上一段还没推进游标就不再下发)
        if now - self.t_last_post < 3.0 and self.phase == "RUN":
            return
        if (self._post_cursor >= 0 and self.cursor <= self._post_cursor
                and not st.get("running") and (now - self._post_t) < 30.0):
            return
        self.t_last_post = now
        self.phase = "RUN"
        body = {"n": self.chunk, "speed": self.speed, "dwell_ms": self.dwell_ms}
        if self.cursor > 0:
            body["start"] = int(self.cursor)      # 显式给游标: 演练档 8797 不自己推进, 不能靠它推
        if self.dry:
            body["dry"] = True
        try:
            # 🎯 后端只认 action(状态空间工程的最终输出); 现在 src=traj215 ⇒ 照旧回放 215 点
            #    src=ss 且 ZMAX_ACTION_SS_EXEC=1 才切到状态空间下发(接口未落地 ⇒ 明确报错, 不静默)
            _act = None
            try:
                from . import action_bus as _ab
                _act = _ab.read()
                if _act and str(_act.get("src")) == "ss" and \
                        os.environ.get("ZMAX_ACTION_SS_EXEC") != "1":
                    _act = dict(_act, src="traj215",
                                why="action 想走 ss, 但 ZMAX_ACTION_SS_EXEC 未开 ⇒ 回放 215 点")
                if _act and str(_act.get("src")) == "ss":
                    self.last_msg = "action 想走 ss, 但接管未实现(需 8797 位姿下发接口) ⇒ 本段仍回放 215 点"
            except Exception:                                          # noqa: BLE001
                _act = None
            # 👀 让 VSCode 的「终端」每段都看得见一行(以前只写 json, 控制台一片安静 ⇒ 用户以为没动)
            print("📤 派单 n=%s start=%s speed=%s dwell=%sms · 第 %d 轮 · 游标 %d/%d"
                  % (body.get("n"), body.get("start"), body.get("speed"), body.get("dwell_ms"),
                     self.rounds, self.cursor, self.total), flush=True)
            if _act:
                print("🎯 action[%s] x=%.2f y=%.2f z=%.2f a=%.2f b=%.2f c=%.2f i=%s · %s"
                      % (_act.get("src"), _act.get("x") or 0, _act.get("y") or 0, _act.get("z") or 0,
                         _act.get("a") or 0, _act.get("b") or 0, _act.get("c") or 0,
                         _act.get("i"), str(_act.get("why"))[:60]), flush=True)
            # 🛑 可断点锚(在本进程里 ⇒ VSCode 会真的停下来, 变量面板能看 n/start/speed):
            #    触发: touch /tmp/zmax_stop_at_dispatch   继续: rm 掉
            #    有调试器 ⇒ debugpy.breakpoint(); 没有 ⇒ pdb.set_trace()
            if os.environ.get("ZMAX_STOP_AT_DISPATCH") == "1" or os.path.exists("/tmp/zmax_stop_at_dispatch"):
                try:
                    import debugpy
                    if debugpy.is_client_connected():
                        debugpy.breakpoint()
                    else:
                        import pdb
                        pdb.set_trace()
                except Exception:                                          # noqa: BLE001
                    pass
            r = _post("/api/arm/step_traj", body)
        except Exception as e:                                           # noqa: BLE001
            self.last_msg = "下发失败(%s): %s" % (type(e).__name__, str(e)[:80])
            self._dump()
            return
        stage = str(r.get("stage") or "")
        if r.get("ok"):
            self.rounds += 1
            self._post_cursor = self.cursor
            self._post_t = now
            self._mark_sent(body)
            self.last_msg = "已下发第 %d 轮: %s" % (self.rounds, r.get("msg") or "")
            _say("▶ " + self.last_msg)
        elif stage == "jump":
            # 真机不在轨迹附近 ⇒ 让 8797 把游标对齐到最近点, 再继续
            try:
                ra = _post("/api/arm/step_traj", {"align": True})
                if ra.get("cursor") is not None:      # 对齐后以服务端为准, 否则 flow 游标仍超前
                    self.cursor = int(ra["cursor"])
                    self._post_cursor = -1
                self.last_msg = "对齐到真机最近点: %s" % (ra.get("msg") or ra.get("err") or "")
                _say("◎ " + self.last_msg)
            except Exception as e:                                       # noqa: BLE001
                self.last_msg = "对齐失败: %s" % str(e)[:70]
        elif stage == "end":
            self.phase, self.done = "DONE", True
            self.last_msg = "轨迹末端: %s" % (r.get("err") or "")
        elif stage == "auth":
            self.phase = "WAIT_AUTH"
            self.last_msg = "等授权: %s" % (r.get("err") or "")
        elif stage == "busy":
            self.last_msg = "上一轮还在跑: %s" % (r.get("err") or "")
        else:
            self.last_msg = "被拒(%s): %s" % (stage or "?", (r.get("err") or "")[:90])
            if str(r.get("hint") or ""):
                self.last_msg += " · " + str(r.get("hint"))[:60]
        self._dump()
