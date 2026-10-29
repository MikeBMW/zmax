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
    # 🔴 2026-10-29: 显式关掉机制 (日常跑不想被内置断点打扰时设 ZMAX_BREAK_OFF=1)。
    #   注意: 文件开关 BREAK 仍然优先 (那是人主动 touch 的, 语义就是"我要停")。
    if os.environ.get("ZMAX_BREAK_OFF") == "1":
        return
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
    # 未设 env: **只记录不停** —— 2026-10-29 老倪「又卡死了, 断点用鼠标点不到了」:
    #   GUI 主线程一 breakpoint() 整界面就冻结, 鼠标点不动, 连打新断点都做不了。
    #   所以默认值必须是"不打扰": 想停只有两条显式路 ——
    #     ① touch zmax_data/ss_live/BREAK (上面已处理, 无条件停)
    #     ② ZMAX_DEBUG_BREAK=actuator (每次停) / =1 (全停)
    #   UI 断点已能正常绑定 (library/_ss_import 与 engine/_load 都改回 spec + sys.modules),
    #   日常调试点红点就够, 不需要这里替他自动停。
    _say("到达 (默认不停; 想停设 ZMAX_DEBUG_BREAK=%s 或 touch zmax_data/ss_live/BREAK)" % _key)
    return
