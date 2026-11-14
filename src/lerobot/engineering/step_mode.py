# -*- coding: utf-8 -*-
"""step_mode.py — 单步模式守卫 (ZMAX_STEP_MODE=1)

老倪 2026-11-14:「单步运行, 能够走过全局所有逻辑。就是让所有逻辑节点, 等待我的操作,
不允许任何节点, 单独违规自己运行。」

这条纪律在代码里的含义: 任何节点都不得在**调用栈之外**执行逻辑。
  · 后台线程 / 线程池  ⇒ 改成**内联同步执行**(就地跑在调用者的栈上, 断点能停, 单步能进)
  · 子进程 / os.system / fork ⇒ **拒绝**并点名(哪个文件哪一行要起它), 因为跨进程无法单步
  · 引擎的"快车道"(同拍第二次 prj.step) ⇒ 关掉, 保证一拍 = 一趟, 单步不乱序

只在本模式下生效, 生产默认关闭: 不改任何业务语义, 只把"偷偷跑"的部分拉回调用栈。
"""
import atexit
import os
import subprocess
import sys
import threading

_STATE = {"inline": [], "refused": []}
_INSTALLED = [False]


def _say(msg: str) -> None:
    try:
        sys.__stdout__.write(msg + "\n")
        sys.__stdout__.flush()
    except Exception:                                                   # noqa: BLE001
        pass


def _caller() -> str:
    """找出真正要起线程/子进程的那个工程文件:行 —— 点名用, 不猜。"""
    try:
        import traceback
        for fr in reversed(traceback.extract_stack()[:-2]):
            f = fr.filename or ""
            if "/site-packages/" in f or "step_mode.py" in f:
                continue
            if "/zmax/" in f or "/lerobot/" in f:
                return "%s:%d" % (f.replace("/home/ubuntu/zmax/", ""), fr.lineno)
    except Exception:                                                   # noqa: BLE001
        pass
    return "?"


class _Done:
    """ThreadPoolExecutor.submit 的替代返回: 已经同步算完了, 只装作 Future。"""

    def __init__(self, value=None, exc=None):
        self._v, self._e = value, exc

    def result(self, timeout=None):
        if self._e is not None:
            raise self._e
        return self._v

    def exception(self, timeout=None):
        return self._e

    def done(self):
        return True

    def cancel(self):
        return False


def install(allow_popen: bool = False) -> None:
    if _INSTALLED[0]:
        return
    _INSTALLED[0] = True

    # ① 线程 → 内联同步
    _orig_start = threading.Thread.start

    def _start(self):                                                  # noqa: ANN001
        name = getattr(self, "name", "?")
        if str(name).startswith("pydevd"):
            return _orig_start(self)
        tgt = getattr(self, "_target", None)
        args = getattr(self, "_args", ()) or ()
        kwargs = getattr(self, "_kwargs", {}) or {}
        if tgt is None:
            _STATE["refused"].append(name)
            _say("⛔ STEP: 线程 %s 没有 target, 拒绝启动 (来源 %s)" % (name, _caller()))
            return
        _STATE["inline"].append(name)
        _say("⇄ STEP: 线程 %-18s → 内联同步执行 (来源 %s)" % (name, _caller()))
        tgt(*args, **kwargs)

    threading.Thread.start = _start

    # ② 线程池 → 同步
    try:
        from concurrent.futures import ThreadPoolExecutor
        _orig_submit = ThreadPoolExecutor.submit

        def _submit(self, fn, *a, **kw):                               # noqa: ANN001
            _STATE["inline"].append("ThreadPool")
            try:
                return _Done(fn(*a, **kw))
            except BaseException as e:                                 # noqa: BLE001
                return _Done(exc=e)

        ThreadPoolExecutor.submit = _submit
    except Exception:                                                  # noqa: BLE001
        pass

    # ③ 子进程 → 拒绝(跨进程无法单步), 点名是谁要起
    _orig_popen_init = subprocess.Popen.__init__
    if not allow_popen:

        _allow = [s for s in (os.environ.get("ZMAX_STEP_ALLOW_POPEN") or "").split(",") if s.strip()]

        def _in_node_compute() -> bool:
            """是否由"节点计算"这条栈发起的 —— 只拦这个。

            库初始化(import metaworld/torch 之类)自己起的探针子进程跟业务逻辑无关,
            拦了反而把节点打成残废; 真正要禁的是"节点在 tick 之外偷偷起进程干活"。
            """
            import traceback
            for fr in traceback.extract_stack():
                f = fr.filename or ""
                if f.endswith("middleware/node.py") or "/nodes/impl/" in f:
                    return True
            return False

        def _popen(self, *a, **kw):                                    # noqa: ANN001
            cmd = " ".join(str(x) for x in (a[0] if a else kw.get("args") or []))
            probe = " -c " in cmd          # 库探针(python -c 一行)不是业务逻辑, 放行
            if probe or any(s in cmd for s in _allow) or not _in_node_compute():
                return _orig_popen_init(self, *a, **kw)
            src = _caller()
            _STATE["refused"].append(src)
            _say("⛔ STEP: 拒绝子进程 (来源 %s): %s" % (src, cmd[:160]))
            raise RuntimeError("STEP_MODE: 子进程被拒绝 (%s)" % src)

        subprocess.Popen.__init__ = _popen

        _orig_system = os.system

        def _system(cmd):                                              # noqa: ANN001
            src = _caller()
            _STATE["refused"].append(src)
            _say("⛔ STEP: 拒绝 os.system(%r) (来源 %s)" % (str(cmd)[:40], src))
            return 1

        os.system = _system

    def _report():
        if not (_STATE["inline"] or _STATE["refused"]):
            _say("STEP 汇总: 本进程没有任何节点试图脱离调用栈运行 ✔")
            return
        _say("STEP 汇总: 内联同步 %d 次 · 拒绝 %d 次"
             % (len(_STATE["inline"]), len(_STATE["refused"])))
        for nm in dict.fromkeys(_STATE["inline"]):
            _say("    ⇄ 内联: %s" % nm)
        for nm in dict.fromkeys(_STATE["refused"]):
            _say("    ⛔ 拒绝: %s" % nm)

    # ④ 把库内并行也算子压到 1: 单步模式下"只有一个执行栈"要连 BLAS/torch 一起收
    try:
        import torch
        torch.set_num_threads(1)
    except Exception:                                                  # noqa: BLE001
        pass

    atexit.register(_report)
    _say("🐞 单步模式已启用: 后台线程→内联 · 子进程→拒绝 · 快车道→关 · 一拍一趟")
