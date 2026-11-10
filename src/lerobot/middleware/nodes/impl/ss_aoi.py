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
       ① 取 context (节流间隔 + 目标帧)  ② 调算法层  ③ 原样返回算法层给的业务 dict
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

# 🔴 2026-11-10 实测节流 (上真机前必须): 三路旁路 = 2×HTTP(10082) + 1×HTTP(10083) + 1 次 YOLO 推理,
#   单拍实测 1.3~3.0s; 而引擎是 10Hz(100ms/拍预算) ⇒ **每拍都跑会把整个循环拖死**。
#   调度是节点的事(拍频预算), 不是算法的口径 ⇒ 节流留在这一层。
_AOI_LAST = {"t": 0.0, "out": None}


def node_ss_aoi(ctx):
    """🔍 光学质量检测 — 节点薄壳: 取帧 → policies/aoi/quality.inspect_aoi → 返回业务 dict。

    真实执行在算法层: policies/aoi/quality.py (本机图像处理判定 + 三路旁路 + AOI 话题)。
    双击源码指向 AOIQualityChecker.check; 断点可进 (正常 import, 不 exec 字符串)。
    """
    log = ctx.get("log")
    try:
        import time as _tm
        _iv = float(os.environ.get("ZMAX_AOI_MIN_INTERVAL_S", "2.0"))
        if _AOI_LAST["out"] is not None and (_tm.time() - _AOI_LAST["t"]) < _iv:
            _c = dict(_AOI_LAST["out"])
            _c["cached_ago_s"] = round(_tm.time() - _AOI_LAST["t"], 2)
            return _c                                  # 节流拍: 不重算、不重复发话题, 只回缓存
        # 目标帧: 优先用 YOLO 节点缓存帧, 无则同源采样一帧 (与 node_ss_yolo 一致)
        img = _YOLO_CACHE.get("img")
        if img is None:
            aligner = _yolo_ensure_aligner(log)
            _, _, img = _yolo_capture(log, aligner)
        _out = inspect_aoi(img, log=log, cache=_YOLO_CACHE, publish=_ar_aoi_publish)
        _AOI_LAST.update({"t": _tm.time(), "out": _out})     # 成功一轮才更新节流时间戳
        return _out
    except Exception as e:
        if log:
            log(f"⚠️ 光学质量检测真实执行失败: {e}")
        # 失败也要有输出 (老倪: 可以没有真值, 但必须有输出, 接口要对齐)
        return {"kind": "aoi", "pass": None, "verdict": "unavailable",
                "err": f"{type(e).__name__}: {e}", "items": [], "no_truth": True}


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_aoi
