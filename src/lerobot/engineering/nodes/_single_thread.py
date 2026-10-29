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
    if log:
        log("🔒 单线程执行闸: torch=%s interop=%s cv2=%s · 进程线程 %d · 主线程 %s"
            % (r.get("torch"), r.get("torch_interop"), r.get("cv2"),
               r.get("py_threads"), r.get("main")))
    return r


def in_caller_thread():
    """节点是否就在主调用线程里执行 (单线程模式下恒 True; 有后台线程时能一眼看出来)。"""
    return threading.current_thread() is threading.main_thread()


def brk(tag=""):
    """🎯 代码内置断点 — VSCode 的 UI 断点在动态加载模块上绑不住时的兜底。

    老倪 2026-10-29「右键进入源码, 断点怎么还不好使」: UI 断点是否命中取决于 debugpy 能否把
    "文件:行" 绑到已加载的模块上 (spec_from_file_location 加载的模块历史上绑不住)。
    这条不依赖绑定: 环境变量命中就调 breakpoint() —— debugpy 会接管 sys.breakpointhook,
    在 VSCode 里停在**这一行**, 调用栈、局部变量都在。

    用法 (env 里设, 不用改代码):
      ZMAX_DEBUG_BREAK=1              → 所有打了 brk() 的地方都停 (最啰嗦)
      ZMAX_DEBUG_BREAK=actuator       → 只停执行器 (RobotExecutor.execute)
      ZMAX_DEBUG_BREAK=actuator,grav  → 停多个, 逗号分隔
    不设 = 完全不执行 (生产零影响, 也不多一次函数调用外的开销)。
    """
    spec = os.environ.get("ZMAX_DEBUG_BREAK", "")
    if not spec:
        return
    if spec in ("1", "*", "all") or (tag and tag in spec.split(",")):
        breakpoint()
