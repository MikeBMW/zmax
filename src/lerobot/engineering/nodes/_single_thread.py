"""🔒 单线程执行闸 — 除 GUI 显示之外, 所有节点都在调用线程里算, 不起后台线程。

老倪 2026-10-29: 「550B VSCode 变成单线程模式, 除了显示的 GUI, 其它所有的 node 节点, 全都单线程运行」。

为什么还要这一层:
  studio.py:38-59 已经在**解释器早期**把 OMP/MKL/OPENBLAS/NUMEXPR/VECLIB/TORCH 压成 1 ——
  那是唯一能改 BLAS 线程池的时机, 晚了 OpenBLAS 已经建好线程池, 再 set 也没用。
  但剩下三类 env 管不到, 必须运行期压:
    ① torch 自己的 intra-op / inter-op 线程池 (env 只影响首次初始化, 已有实例要 set_num_threads)
    ② OpenCV 的 cv2.setNumThreads (YOLO 前处理 resize/dnn 会自己开池)
    ③ 节点代码里显式起的 threading.Thread (如 L3 推理的 infer_async) ⇒ 由调用侧改走同步分支
开关: ZMAX_SINGLE_THREAD=1 且 ZMAX_MULTI_THREAD≠1 ⇒ 生效。
      要跑基准/批量推理时 ZMAX_MULTI_THREAD=1 显式关掉, 不做静默切换。
"""
import os
import threading

_DONE = {"v": None}


def enabled():
    """是否要求单线程执行 (与 studio.py / vscode_launch.py 同一口径)。"""
    return (os.environ.get("ZMAX_SINGLE_THREAD", "") == "1"
            and os.environ.get("ZMAX_MULTI_THREAD", "") != "1")


def enforce(log=None):
    """把运行期还能改的线程池压到 1, 返回实测值 (不是声称)。重复调用只做一次。"""
    if not enabled():
        # 🔴 2026-10-29: 启动时把真实状态打出来 —— 老倪查断点/单线程时, 先要能一眼看出
        #   "env 到底有没有进进程" (实测曾出现 launch.json 的 env 一项都没进进程的情况)
        if not _DONE.get("said_off"):
            _DONE["said_off"] = True
            print("🔓 单线程闸: 未启用 (ZMAX_SINGLE_THREAD=%r / ZMAX_MULTI_THREAD=%r) · "
                  "ZMAX_DEBUG_BREAK=%r · OMP=%r"
                  % (os.environ.get("ZMAX_SINGLE_THREAD"), os.environ.get("ZMAX_MULTI_THREAD"),
                     os.environ.get("ZMAX_DEBUG_BREAK"), os.environ.get("OMP_NUM_THREADS")),
                  flush=True)
        return {"enabled": False, "why": "ZMAX_SINGLE_THREAD!=1"}
    if _DONE["v"] is not None:
        return _DONE["v"]

    r = {"enabled": True, "main": threading.current_thread().name,
         "py_threads": threading.active_count()}

    try:
        import torch                                                       # noqa: PLC0415
        torch.set_num_threads(1)
        try:
            torch.set_num_interop_threads(1)
        except Exception as e:                                             # noqa: BLE001
            r["interop_note"] = "%s (已初始化, 说明本来就是 1)" % type(e).__name__
        r["torch"] = int(torch.get_num_threads())
        r["torch_interop"] = (int(torch.get_num_interop_threads())
                              if hasattr(torch, "get_num_interop_threads") else None)
    except Exception as e:                                                 # noqa: BLE001
        r["torch"] = "n/a (%s)" % type(e).__name__

    try:
        import cv2                                                         # noqa: PLC0415
        cv2.setNumThreads(1)
        r["cv2"] = int(cv2.getNumThreads())
    except Exception as e:                                                 # noqa: BLE001
        r["cv2"] = "n/a (%s)" % type(e).__name__

    r["env"] = {k: os.environ.get(k) for k in
                ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "TORCH_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")}
    _DONE["v"] = r
    _msg = ("🔒 单线程闸: torch=%s interop=%s cv2=%s · 进程线程 %d · ZMAX_DEBUG_BREAK=%r"
            % (r.get("torch"), r.get("torch_interop"), r.get("cv2"),
               r.get("py_threads"), os.environ.get("ZMAX_DEBUG_BREAK")))
    if log:
        log(_msg)
    else:
        try:
            print(_msg, flush=True)
        except Exception:                                                  # noqa: BLE001
            pass
    return r


def in_caller_thread():
    """节点是否就在主调用线程里执行 (单线程模式下恒 True; 有后台线程时能一眼看出来)。"""
    return threading.current_thread() is threading.main_thread()


_SEEN = set()          # 没设 env 时的"首次停"去重 (否则 10Hz 每帧都停, 界面直接死)
_ANNOUNCED = set()     # 每个 tag 只播报一次"到达/未停"，避免刷屏
_LAST_STOP = {}        # tag → 上次真停的 monotonic 时间 (按时间间隔去重, 不是"只停一次")
_GAP = float(os.environ.get("ZMAX_BREAK_GAP", "1.5"))   # 同一 tag 两次停的最小间隔(秒)


def brk(tag=""):
    """🎯 代码内置断点 — 不依赖 debugpy 对动态加载模块的文件:行绑定。

    老倪 2026-10-29「右键进源码, 断点还是不进」实证结论:
      ① 右键「运行节点」的调用路径确实会走到执行器 (模拟实测: execute 被调用, 日志正常打;
         StateSpaceSim.run 实测 execute 被调 369 次)
      ② 但调试进程 /proc/<pid>/environ 里 ZMAX_DEBUG_BREAK / ZMAX_SINGLE_THREAD 全空
         ⇒ launch.json 的 env 没进进程 (VSCode 用的不是这份 launch 配置), brk() 一次都没执行
    所以两种触发方式并存, 后者不需要任何 env:
      · 显式: ZMAX_DEBUG_BREAK=1/*/all 全停; =tag1,tag2 按 tag 停
      · 自动: 没设 env 但调试器已连接 (F5 起的会话) ⇒ **每个 tag 只停第一次**
        (只停一次是为了不把 10Hz/每帧的节点刷成无限暂停; 想每次都停就显式设 tag)
    每个 tag 首次到达时打一行状态 (停/未停 + 原因) —— 让人能从日志判断断点到底走没走到。
    """
    _key = tag or "-"
    # 🔴 2026-10-29 最硬的开关: 存在 zmax_data/ss_live/BREAK 就无条件 breakpoint()
    #   (不判断 env, 不判断 debugpy 是否连通 —— 用来判定"代码到没到"和"调试器有没接管")
    _HERE = os.path.abspath(__file__)
    # nodes → engineering → lerobot → src → zmax (5 层, 别少一层: 少一层会指到 src/zmax_data 而永远不命中)
    _RT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))))
    _FLAG = os.path.join(_RT, "zmax_data", "ss_live", "BREAK")
    if os.path.exists(_FLAG):
        if "flag:" + _key not in _ANNOUNCED:
            _ANNOUNCED.add("flag:" + _key)
            try:
                print("🔴 [brk:%s] 命中文件开关 %s → 停" % (_key, _FLAG), flush=True)
            except Exception:                                              # noqa: BLE001
                pass
        breakpoint()
        return

    spec = os.environ.get("ZMAX_DEBUG_BREAK", "")

    def _say(msg):
        if _key in _ANNOUNCED:
            return
        _ANNOUNCED.add(_key)
        try:
            print("🔴 [brk:%s] %s" % (_key, msg), flush=True)
        except Exception:                                              # noqa: BLE001
            pass

    if spec:
        if spec in ("1", "*", "all") or (tag and tag in spec.split(",")):
            _say("命中 ZMAX_DEBUG_BREAK=%r → 停" % spec)
            breakpoint()
        else:
            _say("ZMAX_DEBUG_BREAK=%r 不含本 tag → 不停" % spec)
        return
    # 未设 env: 调试会话里按时间间隔停 —— 让"想调试"这件事不依赖 launch.json 是否生效。
    # 🔴 2026-10-29 老倪「启动能进, 运行之后不进」: 原来这里是 _SEEN 去重 ⇒ 每个 tag 一辈子只停
    #   一次, 启动时停完就再也不停了。改成时间窗: 距上次真停 ≥ _GAP 秒就再停一次。
    #   这样"每一轮运行都能停一次", 又不会因为引擎一轮调 369 次而把界面刷死。
    import time as _tm                                                   # noqa: PLC0415
    _now = _tm.monotonic()
    if _now - _LAST_STOP.get(_key, -1e9) < _GAP:
        return
    try:
        import debugpy                                                  # noqa: PLC0415
        _conn = bool(debugpy.is_client_connected())
    except Exception:                                                   # noqa: BLE001
        _conn = False
    if not _conn:
        _say("到达, 但调试器未连接 → 不停 (env 也没设)")
        return
    _LAST_STOP[_key] = _now
    if _key not in _ANNOUNCED:
        _ANNOUNCED.add(_key)
        try:
            print("🔴 [brk:%s] 调试器已连接 + 未设 env → 停 "
                  "(之后每 %.1fs 最多停一次; 想每次都停设 ZMAX_DEBUG_BREAK=%s)"
                  % (_key, _GAP, _key), flush=True)
        except Exception:                                              # noqa: BLE001
            pass
    breakpoint()
