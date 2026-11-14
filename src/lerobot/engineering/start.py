#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""start.py — **工程入口** (Z-MAX 统一状态空间 · 工厂调度)

老倪 2026-11-14:「启动程序, 在这里(src/lerobot/engineering), 是工程入口, 起名为 start.py」。

三层各司其职 (别再混成"一个纯 tick 循环"):
    ① 入口   = 本文件                             启动/收口, 打状态机与策略表, 装每拍钩子
    ② 状态机 = policies/left_right/state_space/scheduler_fsm.py::DispatchFSM
                                                   13 状态 + 每状态策略(层配比/限速/力否决) + 证据守卫
    ③ 引擎   = tools/ss_canvas_loop.py              10Hz 逐节点执行; 调制器每拍用状态机策略融合+过闸

为什么状态机不在这里 new: 调制器是每拍新建的(safety_limit_impl:252), 状态若跟它 new 就永远停在
「接近」 ⇒ 状态是进程级事实, 用 scheduler_fsm.get_fsm() 单例。

跑法:
    ./gui-venv311/bin/python src/lerobot/engineering/start.py
    SS_MODE=full ...        # insert(默认) / full(插拔+AOI闭环) / tray(摆盘)
    ZMAX_FSM=0 ZMAX_ORCH=0  # 对照旧行为(零回归)
VSCode: 选「🧠 后端工程 · 调度状态机 (start.py)」按 F5。
"""
import fcntl
import os
import signal
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))          # src/lerobot/engineering
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))   # 仓库根
for _p in (os.path.join(_ROOT, "src"), os.path.join(_ROOT, "tools"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("ZMAX_FSM", "1")
os.environ.setdefault("ZMAX_ORCH", "1")


def _say(msg: str) -> None:
    """绕开引擎的降噪重定向(loop_quiet 会把 print 收进 /tmp/ss_canvas_loop.log),
    入口自己的话必须直接写真正的 stdout —— 否则 F5 之后终端一片空白, 看着像没启动。"""
    try:
        sys.__stdout__.write(msg + "\n")
        sys.__stdout__.flush()
    except Exception:                                                    # noqa: BLE001
        pass


_LOCK_FH = None


def _acquire_single_instance() -> bool:
    """单实例锁 —— 生产纪律: 一个进程只能有一个工程入口。

    为什么必须有: 状态机是进程级单例, 两个入口进程 = 两个状态机, 会**双写** ss_live/ss_fsm.json;
    而且技能派发宿主(dispatch_inproc.owner)只认一个, 第二个会被拒, 现场表现就是"一会儿动一会儿不动",
    很难查。锁用 flock(LOCK_NB): 进程一退出内核自动释放, 不会留脏锁。
    """
    global _LOCK_FH
    path = os.environ.get("ZMAX_START_LOCK", "/tmp/zmax_start.lock")
    fh = open(path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.environ["ZMAX_LOCK_HELD_PID"] = str(os.getpid())   # 同进程内引擎(engine.main)看到它就不再抢锁
    except OSError:
        fh.seek(0)
        owner = (fh.read() or "").strip() or "未知"
        _say("⛔ 已有工程入口在运行 (pid %s · 锁 %s) ⇒ 拒绝重复启动" % (owner, path))
        return False
    fh.seek(0)
    fh.truncate()
    fh.write("%d\n" % os.getpid())
    fh.flush()
    _LOCK_FH = fh                      # 持有到进程结束
    return True


def _install_signals() -> None:
    """优雅停止: systemd stop / Ctrl+C 都要打一行再退, 不要留下"不知道是不是还在跑"的状态。"""
    def _term(signum, _frame):
        _say("🛑 收到信号 %d (SIGTERM=15 / SIGINT=2) ⇒ 停止工程" % signum)
        raise KeyboardInterrupt
    for _s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_s, _term)
        except Exception:                                               # noqa: BLE001
            pass


_AUTH_MOD = []          # 模块只加载一次(以前每拍 importlib exec 一次, 10Hz 也会拖慢拍子)
_AUTH_CACHE = {"ts": 0.0, "st": None}


def _auth_probe(min_interval=2.0):
    """🔐 查真动授权(唯一依据 tools/ctl_auth.py), 带 2s 缓存。

    返回 {"armed","debug","mode","left_s","epoch","ip","label","path"} —— 页面/执行器/入口同一份。
    为什么要缓存: hook 每拍都问授权, 以前每拍 importlib.exec_module 一遍, 等于每拍读盘+编译。
    """
    import importlib.util as _ilu
    now = time.time()
    if _AUTH_CACHE["st"] is not None and (now - _AUTH_CACHE["ts"]) < min_interval:
        return _AUTH_CACHE["st"]
    try:
        if not _AUTH_MOD:
            _sp = _ilu.spec_from_file_location(
                "_zmax_ctl_auth", os.path.join(_ROOT, "tools", "ctl_auth.py"))
            _m = _ilu.module_from_spec(_sp)
            _sp.loader.exec_module(_m)
            _AUTH_MOD.append(_m)
        st = _AUTH_MOD[0].info()
    except Exception as e:                                              # noqa: BLE001
        st = {"armed": False, "debug": False, "mode": "window", "left_s": 0.0, "epoch": 0,
              "ip": "", "revoked_at": 0, "path": "",
              "label": "读不到 ctl_auth.py: %s" % str(e)[:60]}
        _AUTH_CACHE.update({"ts": now, "st": dict(st)})
        return st
    left = st.get("left_s")
    if st.get("armed") and st.get("debug"):
        label = "已授权 · 调试档(无时间限制) · 只能由前端『撤销』结束"
    elif st.get("armed"):
        label = "已授权 · 定时档 · 剩 %d 分 %02d 秒(到点自动失效)" % (
            int((left or 0) // 60), int((left or 0) % 60))
    elif st.get("revoked_at"):
        label = "未授权 · 已被撤销(%s)" % time.strftime("%H:%M:%S", time.localtime(st["revoked_at"]))
    else:
        label = "未授权 · 授权窗已过期(剩 %.0f 秒)" % (left or 0.0)
    st["label"] = label
    _AUTH_CACHE.update({"ts": now, "st": dict(st)})
    return st


def _offline_guard():
    """调试档离线护栏: 任何节点对**外网**的联网调用立即失败(<1ms), 不占用整拍。

    为什么需要: 单线程档 spawn_or_inline 会把"后台联网"改成当场同步执行, 于是 L5/DeepSeek、
    VLM、AOI、INTACT-RPC 任何一个卡住都会把 10Hz 主循环钉在 socket 上 ⇒ decide() 不 tick,
    断点永远不命中(2026-11-14 反复出现: l5_intent.py:137 / scene_vlm.py:195 / http 各种)。
    逐节点打补丁是打地鼠; 这里在 socket 层一次性兜住: 环回(127.0.0.1/::1)放行(8793/8797 要通),
    其余一律 OSError, 节点按"没值"降级, 节拍照走。

    开关: 单线程档 或 ZMAX_LLM_OFF=1 时生效; ZMAX_LLM_ONLINE=1 可临时解除。
    """
    def _on(k: str) -> bool:
        return str(os.environ.get(k, "")).strip().lower() in ("1", "true", "yes", "on")

    if not ((_on("ZMAX_SINGLE_THREAD") or _on("ZMAX_LLM_OFF")) and not _on("ZMAX_LLM_ONLINE")):
        return
    import socket

    _LOOP = ("127.", "::1", "localhost", "0.0.0.0")   # ⚠️ 绝不能含 ""(那会让所有主机都算本地)

    def _is_local(host):
        h = str(host or "")
        return any(h.startswith(x) for x in _LOOP) or h in ("::1", "localhost")

    _orig_cc = socket.create_connection

    def _cc(address, *a, **k):
        if not _is_local(address[0] if isinstance(address, (tuple, list)) and address else address):
            raise OSError("offline(debug): 外网联网被禁止, 不占节拍 → %s" % (address,))
        return _orig_cc(address, *a, **k)

    socket.create_connection = _cc
    _orig_connect = socket.socket.connect

    def _connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(
                address[0] if isinstance(address, (tuple, list)) else address):
            raise OSError("offline(debug): 外网联网被禁止, 不占节拍 → %s" % (address,))
        return _orig_connect(self, address)

    socket.socket.connect = _connect
    print("🔌 调试档离线护栏已开: 外网联网立即失败, 环回放行(8793/8797 可用)", flush=True)


def _debug_defaults():
    """调试档(单线程)的**自带默认值** —— 不依赖 .vscode/launch.json 里的 env。

    为什么必须自带(2026-11-14 反复踩): GUI 每次启动会用模板重写 .vscode/launch.json
    (simulink_module._vscode_launch_cfg), 把我加进去的 ZMAX_AOI_OFF/ZMAX_SKIP_IDS/
    ZMAX_TRAJ_CHUNK 全冲掉 ⇒ F5 起来的进程只剩 ZMAX_SINGLE_THREAD=1, 于是 AOI/L5/渲染
    又把主循环钉住, decide() 不 tick, 断点"永远不进"。
    这里 setdefault: 配置文件里显式给了就以配置为准, 没给就用这套安全默认。
    """
    def _on(k: str) -> bool:
        return str(os.environ.get(k, "")).strip().lower() in ("1", "true", "yes", "on")

    _single = _on("ZMAX_SINGLE_THREAD")
    _online = _on("ZMAX_LLM_ONLINE") or _on("ZMAX_AOI_ONLINE")
    if not _single or _online:
        return
    _d = {
        "ZMAX_LLM_OFF": "1",            # L5/DeepSeek/VLM 一律不联网
        "ZMAX_AOI_OFF": "1",            # 不做 10082/10083 巡检(内联会卡整拍)
        "ZMAX_FULL_EVERY": "999999",    # 不跑整张画布, 只跑核心链
        "ZMAX_TRAJ_CHUNK": "1",         # 断点一停, 最多多走 1 点
        "ZMAX_SKIP_IDS": "ssyolo,ssllm,ssreason,n_vlm_llm,n_dsvl,ss_l5,ss_seg,ssaoi,ssvlm,ssllm_in,ssintact,ssintact_dec,swintact,ss_lora_l4,ssmani_exp,ss_mem_l3,ssbg_vlm,ss_man,n_geoplan,swds,swvideo,n_realscene,ssrender,ssdec,ss2d3d,ss_lora_l3",
        "ZMAX_CORE_IDS": "ssobs,sssensor,ssff,ssest,sspred,ssinnov,sssched,sslimit,ssact,sstactile,n_exec",
        "SS_VLM_TIMEOUT": "8",
    }
    _set = []
    for k, v in _d.items():
        if not str(os.environ.get(k, "")).strip():
            os.environ[k] = v
            _set.append(k)
    if _set:
        print("🧪 调试档自带默认 env: " + ", ".join(_set), flush=True)


def main() -> int:
    _a0 = _auth_probe()                      # ⏱ 第一件事: 你有没有在前端授权, 现在就知道
    _say("")
    _say("🔐 真动授权 (唯一依据 %s)" % (_a0.get("path") or "zmax_data/ctl_auth.json"))
    _say("   %s %s" % ("✅" if _a0.get("armed") else "⛔", _a0.get("label")))
    _say("   epoch=%s · ip=%s · mode=%s" % (_a0.get("epoch"), _a0.get("ip") or "-",
                                            _a0.get("mode") or "window"))
    if _a0.get("armed"):
        _say("   → 全流程会立即开始下发; 前端点『🔒 立即撤销授权』会当场停(每段下发前都复查)")
    else:
        _say("   → 全流程原地等授权: 前端 8793 工位总览 →『🔓 授权真动』(30 分钟 / 调试·无限) 两步确认")
    if not _acquire_single_instance():
        return 2
    _install_signals()
    if os.environ.get("ZMAX_STEP_MODE") == "1":
        from lerobot.engineering import step_mode        # 单步纪律: 节点不许脱离调用栈自己跑
        step_mode.install()
    from lerobot.policies.left_right.state_space.scheduler_fsm import STATES, POLICY, get_fsm
    _debug_defaults()
    _offline_guard()
    import ss_canvas_loop as engine                                  # 执行腿(10Hz 引擎)

    mode = os.environ.get("SS_MODE", "insert")
    fsm = get_fsm(mode=mode)
    fsm._dump()                       # 初始状态落盘: 页面/终端第一眼看到"调度器在哪"

    _say("🧠 工程入口 start.py · 调度状态机 = 工厂调度 (小脑/基底节口径)")
    _say("   状态集合 (%d): %s" % (len(STATES), " → ".join(STATES)))
    _say("   模式 %s · 状态机 %s · 仲裁器 %s · 状态文件 %s"
         % (mode, os.environ.get("ZMAX_FSM"), os.environ.get("ZMAX_ORCH"), fsm.FSM_JSON))
    _say("   每状态策略  (层配比 L3/L4/L2 · 限速 m/s · 力否决 N)")
    for s in STATES:
        p = POLICY[s]
        _say("     %-7s L3 %.2f · L4 %.2f · L2 %.2f · v≤%.3f · Fveto %.0fN"
             % (s, p["w_L3"], p["w_L4"], p["w_L2"], p["v_cap"], p["f_veto_n"]))
    _say("   执行腿: tools/ss_canvas_loop.py — 10Hz 逐节点; 状态机只做调度, 动作仍过物理闸")

    flow = None
    if os.environ.get("ZMAX_AUTO_TRAJ") == "1":          # 全流程自动执行(授权即跑, 215 点)
        from lerobot.policies.left_right.state_space.real_traj_flow import RealTrajFlow
        flow = RealTrajFlow(chunk=int(os.environ.get("ZMAX_TRAJ_CHUNK") or 10),
                            speed=float(os.environ.get("ZMAX_TRAJ_SPEED") or 20),
                            dwell_ms=int(os.environ.get("ZMAX_TRAJ_DWELL_MS") or 120),
                            dry=os.environ.get("ZMAX_TRAJ_DRY") == "1")
        _say("   全流程: 授权即自动执行 · 进度写 zmax_data/ss_live/traj_flow.json")
        if os.environ.get("ZMAX_STEP_MODE") != "1":
            # 连续模式: 引擎一次全量 pass 要几十秒(重推理节点), 不能用拍子带全流程 ⇒ 独立 1Hz 驱动。
            # 单步模式(🐞)下不起这条线程: 那边由每拍 hook 驱动, 你点一步走一步, 不许后台偷跑。
            import threading
            def _drive_flow():                                            # noqa: ANN202
                while True:
                    try:
                        flow.tick()
                    except Exception:                                     # noqa: BLE001
                        pass
                    time.sleep(1.0)
            threading.Thread(target=_drive_flow, name="zmax-traj-flow", daemon=True).start()
            _say("   驱动: zmax-traj-flow 1Hz · 单步档则由每拍 hook 驱动(无后台)")

    last = [fsm.state]
    _last_auth = [_a0.get("armed"), _a0.get("mode")]

    def hook(n_tick, traces):
        _a = _auth_probe()                                   # 授权变了当场说一声(撤销要紧)
        _sig = [_a.get("armed"), _a.get("mode")]
        if _sig != _last_auth:
            _last_auth[:] = _sig
            _say("🔐 授权变化: %s %s" % ("✅" if _a.get("armed") else "⛔", _a.get("label")))
        if flow is not None and os.environ.get("ZMAX_STEP_MODE") == "1":
            try:                                         # 单步档: 每拍推进一次(你在操作, 它才动)
                flow.tick()
            except Exception as _e:                      # noqa: BLE001
                _say("⚠ 全流程异常: %s: %s" % (type(_e).__name__, str(_e)[:80]))
        st = fsm.state
        if st == last[0]:
            return
        p = fsm.policy()
        _say("🔀 tick=%d 状态 %s → %s · %s | L3 %.2f L4 %.2f L2 %.2f · v≤%.3f"
             % (n_tick, last[0], st, fsm.last_reason,
                p["w_L3"], p["w_L4"], p["w_L2"], p["v_cap"]))
        last[0] = st

    engine.TICK_HOOK = hook
    engine.main()                     # 阻塞: 引擎循环; 每拍回调 hook
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _say("停止")
