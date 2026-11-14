# -*- coding: utf-8 -*-
"""ss_aoi — 节点实现正文 (文件名 = 画布节点: ss_aoi)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_aoi   ·   registry key: ss_aoi

🔀 2026-11-10 老倪: 「光学质量检测 模块代码，要放到 /home/ubuntu/zmax/src/lerobot/policies，
   不要放到中间件」⇒ 算法真身全部在 `policies/aoi/`:
       policies/aoi/quality.py      一次完整巡检 (图像处理判定 → 话题值 → 业务 dict → 日志)
       policies/aoi/gold.py         金手指 10082 搬运真判决
       policies/aoi/gold_yolo.py    金手指 10082 本机 YOLO 推理
       policies/aoi/surface.py      表面   10083 本机重算
   本文件只做三件事 (铁律: 节点不许出现检测/判据/阈值逻辑):
       ① 取 context (拍频预算 + 目标帧)  ② 调算法层  ③ 原样返回算法层给的业务 dict

⚡ 2026-11-10 PURE 转正: 实测单拍 1.3~3.0s, 而引擎是 10Hz(100ms/拍) ⇒ **同步跑必拖死循环**。
   改为「异步 worker + 非阻塞读最新快照」:
       · worker 线程独立跑完整巡检 (含三路旁路), 周期 ZMAX_AOI_MIN_INTERVAL_S(默认 2.0s)
       · 节点每拍只读 worker 的最新结果 + 帧龄(age_s) + 序号(seq), 耗时 ~0μs
       · 还没出第一轮时返回 warming (pass=None), **不造 0**
   这样 AOI 以 ~0.4Hz 真更新, 10Hz 动作循环零阻塞 —— 两者解耦。
   老倪口径: 「实时数据须标拍照时间·帧龄」⇒ 快照里 ts / age_s / frame_age_s 都是真值。
"""

# 共享运行时/辅助函数仍在 shared_runtime —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _YOLO_CACHE,
    _ar_aoi_publish,
    _yolo_capture,
    _yolo_ensure_aligner,
    os,
)
# 算法层唯一入口 (policies 不 import middleware, 所以缓存/话题/日志全部注入)
from lerobot.policies.aoi.quality import inspect_aoi  # noqa: E402

import threading as _th
import time as _tm

# 🔴 实测节流 (上真机前必须): 三路旁路 = 2×HTTP(10082) + 1×HTTP(10083) + 1 次 YOLO 推理,
#   单拍实测 1.3~3.0s; 而引擎是 10Hz(100ms/拍预算) ⇒ **每拍都跑会把整个循环拖死**。
#   调度是节点的事(拍频预算), 不是算法的口径 ⇒ 节流留在这一层。
_W = {
    "th": None,          # worker 线程
    "lock": _th.Lock(),
    "out": None,         # 最近一次完整结果 (业务 dict)
    "ts": 0.0,           # 该结果的完成时刻 (time.time)
    "t_start": 0.0,      # 该轮开始时刻
    "seq": 0,            # 轮次序号
    "runs": 0,           # 真跑次数
    "errs": 0,           # 异常次数
    "last_err": None,
    "first_done": False,
}


def _aoi_interval():
    try:
        return max(0.5, float(os.environ.get("ZMAX_AOI_MIN_INTERVAL_S", "2.0")))
    except Exception:                                                   # noqa: BLE001
        return 2.0


def _grab_frame(log=None):
    """目标帧: 优先 YOLO 节点缓存帧, 无则同源采样一帧 (与 node_ss_yolo 一致)。"""
    img = _YOLO_CACHE.get("img")
    if img is not None:
        return img
    aligner = _yolo_ensure_aligner(log)
    _, _, img = _yolo_capture(log, aligner)
    return img


def _aoi_once():
    """一轮巡检 (取帧 → inspect_aoi → 写最新快照)。异常只记账, 不抛。

    单线程/单步档要靠它: 后台线程被禁后, 节点每拍最多推进一轮, 逻辑仍在主线程上可断点可单步。
    """
    t0 = _tm.time()
    try:
        img = _grab_frame(None)
        _out = inspect_aoi(img, log=None, cache=_YOLO_CACHE, publish=_ar_aoi_publish)
        if not isinstance(_out, dict):
            _out = {"kind": "aoi", "pass": None, "verdict": "bad_return",
                    "err": "算法层返回非 dict: %s" % type(_out).__name__, "items": []}
        with _W["lock"]:
            _W.update({"out": _out, "ts": _tm.time(), "t_start": t0,
                       "seq": _W["seq"] + 1, "runs": _W["runs"] + 1,
                       "first_done": True})
    except Exception as e:                                              # noqa: BLE001
        with _W["lock"]:
            _W.update({"errs": _W["errs"] + 1,
                       "last_err": "%s: %s" % (type(e).__name__, e),
                       "t_start": t0})
        # 失败也留一条可读输出 (接口对齐; pass=None 不冒充结果)
        with _W["lock"]:
            if _W["out"] is None:
                _W["out"] = {"kind": "aoi", "pass": None, "verdict": "unavailable",
                             "err": _W["last_err"], "items": [], "no_truth": True}
    return _tm.time() - t0


def _aoi_worker():
    """后台巡检线程 (多线程档): 一轮接一轮, 睡到下一周期 (扣掉本轮耗时)。"""
    while True:
        t0 = _tm.time()
        _aoi_once()
        _tm.sleep(max(0.05, _aoi_interval() - (_tm.time() - t0)))


def _ensure_worker():
    """懒启动 worker (daemon, 不阻塞进程退出)。首次调用返回 False = 还没出第一轮。"""
    import os as _os
    # 单线程/调试档**自动**关掉巡检(不依赖 env 是否被 VSCode 缓存吃掉):
    #   AOI 一轮要打 10082/10083 两个 HTTP, 内联跑会把 10Hz 主循环钉住 ⇒ decide() 不 tick、断点不进。
    #   生产(多线程)不受影响; 要在线看 AOI 就显式 ZMAX_AOI_ONLINE=1。
    _single_env = str(_os.environ.get("ZMAX_SINGLE_THREAD", "")).strip().lower() in ("1", "true", "yes", "on")
    _online = str(_os.environ.get("ZMAX_AOI_ONLINE", "")).strip().lower() in ("1", "true", "yes", "on")
    if _os.environ.get("ZMAX_AOI_OFF") == "1" or (_single_env and not _online):
        # 单线程调试档: AOI 巡检要打 10082/10083 两个 HTTP, 内联跑会把整拍卡住;
        # 调试状态空间时用 ZMAX_AOI_OFF=1 关掉, 生产不要设。
        return _W["first_done"]
    if _W["th"] is not None and _W["th"].is_alive():
        return _W["first_done"]
    with _W["lock"]:
        if _W["th"] is None or not _W["th"].is_alive():
            from lerobot.engineering.thread_policy import single as _single, spawn_or_inline
            if _single():
                # 单线程/单步档: 不起线程。每拍最多推进一轮(按巡检周期), 一轮的代码全在主线程
                _now = _tm.time()
                if _now - float(_W.get("last_inline") or 0.0) >= _aoi_interval():
                    _W["last_inline"] = _now
                    _aoi_once()
                return _W["first_done"]
            _W["th"] = spawn_or_inline("zmax-aoi-worker", _aoi_worker)
    return False


def _snapshot(now=None):
    """读最新快照 (非阻塞)。返回 (业务 dict | None, age_s, seq)。

    age_s = 距该结果完成已过多久 (帧龄口径); 由调用方决定是否降级。
    """
    now = now or _tm.time()
    with _W["lock"]:
        if _W["out"] is None:
            return None, None, _W["seq"]
        return dict(_W["out"]), round(now - _W["ts"], 2), _W["seq"]


def node_ss_aoi(ctx):
    """🔍 光学质量检测 — 端口包装 (逻辑全在 policies/aoi/quality.py)。

    真实执行在算法层 + 本文件的异步 worker。返回业务 dict, 并补 out1/out2 端口:
    画布声明 out1→sssched.in5(质量门) / out1→sssensor.in4(外观质量门)。
    """
    log = ctx.get("log") if isinstance(ctx, dict) else None
    try:
        _ensure_worker()
        _out, _age, _seq = _snapshot()
        _max_age = _aoi_interval() * 3.0          # 三轮没更新 ⇒ 标 stale, 但仍交真相
        if _out is None:
            _b = {"kind": "aoi", "pass": None, "verdict": "warming",
                  "why": "worker 首轮未完成", "items": [], "no_truth": True,
                  "seq": _seq, "age_s": None}
        else:
            _b = dict(_out)
            _b["seq"] = _seq
            _b["age_s"] = _age
            _b["stale"] = bool(_age is not None and _age > _max_age)
            if _b["stale"] and log:
                log("⏳ 光学质量检测快照已 %ss 未更新 (阈值 %ss)" % (_age, round(_max_age, 1)))
        return {"out1": dict(_b), "out2": dict(_b),
                "ok": _b.get("pass") is not None,
                **{k: v for k, v in _b.items()}}
    except Exception as e:                                              # noqa: BLE001
        if log:
            log("⚠️ 光学质量检测节点异常: %s: %s" % (type(e).__name__, e))
        _b = {"kind": "aoi", "pass": None, "verdict": "unavailable",
              "err": "%s: %s" % (type(e).__name__, e), "items": [], "no_truth": True}
        return {"out1": dict(_b), "out2": dict(_b), "ok": False, **_b}


def aoi_worker_stats():
    """给体检脚本/面板: worker 运行态 (真值, 不含估计)。"""
    with _W["lock"]:
        return {"alive": bool(_W["th"] and _W["th"].is_alive()), "seq": _W["seq"],
                "runs": _W["runs"], "errs": _W["errs"], "last_err": _W["last_err"],
                "age_s": (round(_tm.time() - _W["ts"], 2) if _W["ts"] else None),
                "interval_s": _aoi_interval()}


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_aoi
