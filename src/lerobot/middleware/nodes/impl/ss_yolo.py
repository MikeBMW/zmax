# -*- coding: utf-8 -*-
"""ss_yolo — 节点实现正文 (文件名 = 画布节点: ss_yolo)。

从 nodes/library.py 迁出 (2026-11-10 06:34)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_yolo   ·   registry key: ss_yolo
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _YOLO_CACHE,
    _yolo_capture,
    _yolo_capture_ar,
    _yolo_capture_real,
    _yolo_ensure_aligner,
    _yolo_pose_extra,
    os,
    time,
)

def node_ss_yolo(ctx):
    """🎯 YOLO 目标检测 — 真实执行: metaworld 渲染帧 → YOLO detect_3d → align() 替换 39D 段
    源码: yolo_state_aligner.py (YoloStateAligner / detect_3d / align) — 右键源码与真实执行同源, 断点可进
    🐛 2026-09-01: 原执行 detection_targets.py 清单(≠右键源码 yolo_state_aligner.py) → 断点永不命中"""
    log = ctx.get("log")
    import json as _json
    _now = time.monotonic()
    # 🔴 2026-10-29 老倪: 「节点必须实际运行, 接口必须对齐」——
    #   常驻循环 10Hz 每拍都做 metaworld 渲染太重, 用节流: 每 ZMAX_L2_PERIOD_S 秒真推理一次,
    #   其余拍**回放上次契约**(字段一模一样, 只多 cached_ago_s), 保证下游每拍都有值。
    _per = float(os.environ.get("ZMAX_L2_PERIOD_S", "0.5"))
    _c = _YOLO_CACHE.get("l2_out") or {}
    if _c.get("payload") is not None and (_now - float(_c.get("t") or 0.0)) < _per:
        _o = dict(_c["payload"])
        _o["cached_ago_s"] = round(_now - float(_c.get("t") or 0.0), 3)
        return {"out1": _o}
    try:
        import numpy as np
        _meta, _d2 = {}, None
        # 画布「数据源」节点选了 AR 场景 ⇒ 以画布为准 (老倪 2026-11-10); 环境变量只做兜底。
        #   10s 内写过的选择才认, 否则画布停机时会把 L2 死锁在 ar 上。
        _canvas_src = ""
        try:
            import time as _t
            from .shared_runtime import _SS_STATE as _SS
            _ds = _SS.get("data_source") or {}
            if (_t.time() - float(_ds.get("ts") or 0)) < 10.0:
                _canvas_src = str(_ds.get("src") or "").lower()
        except Exception:                                                    # noqa: BLE001
            _canvas_src = ""
        _src = (_canvas_src or os.environ.get("ZMAX_L2_SRC") or ctx.get("l2_src") or "sim").lower()
        if _src == "real":
            det3d, _d2, _meta = _yolo_capture_real(log)
            obs39, aligned = None, None
        elif _src == "ar":
            # 🎥 AR 场景源 (老倪 2026-11-10): 8802 渲染帧 → 渲染域权重 → 针孔反投影
            det3d, _d2, _meta = _yolo_capture_ar(log)
            obs39, aligned = None, None
        else:
            aligner = _yolo_ensure_aligner(log)
            det3d, obs39, _img = _yolo_capture(log, aligner)
            aligned = aligner.align(obs39, det3d)
        if aligned is not None:
            _YOLO_CACHE["aligned39"] = aligned
            # 🆕 2026-11-03: 打时间戳 —— 下游 43D 组装 (_ss_ensure_obs43) 要按新鲜度决定吃不吃它
            _YOLO_CACHE["aligned39_t"] = time.time()
        # 🆕 2026-10-28 老倪: L2 感知节点→plan 的唯一交界 = vision_points.json (由本节点写, 不由脚本写)
        try:
            from . import vision_points as _vp
            _meta = _meta if _src in ("real", "ar") else (_YOLO_CACHE.get("meta") or {})
            _d2 = _d2 if _src in ("real", "ar") else _YOLO_CACHE.get("det2d")
            _path, _verified, _np_ = _vp.publish_from_det(
                det3d, _d2, _meta,
                cam=("真机相机帧" if _src == "real" else ("AR 场景帧 (8802)" if _src == "ar" else "metaworld渲染帧")),
                kind=("ss_yolo_node_real" if _src == "real" else ("ss_yolo_node_ar" if _src == "ar" else "ss_yolo_node")),
                note="canvas node 🎯 YOLO 目标检测 (%s 源)" % _src,
                pose=_yolo_pose_extra())
            if log:
                log("📍 3D 观测点已发布 → %s · frame=%s · verified=%s · %d 点%s"
                    % (os.path.basename(_path), _meta.get("frame"), _verified, _np_,
                       (" · gaps=%s" % _meta.get("gaps")) if _meta.get("gaps") else ""))
        except Exception as _e:                                               # noqa: BLE001
            if log:
                log("⚠️ 3D 观测点发布失败: %s: %s" % (type(_e).__name__, _e))
        if log:
            n = len(det3d)
            det2d = _d2 if _src in ("real", "ar") else _YOLO_CACHE.get("det2d", {})
            desc = " ".join(
                f"{k}=[{v[0]:.3f},{v[1]:.3f},{v[2]:.3f}]"
                + (f" conf={det2d[k]['conf']:.2f}" if k in det2d else "")
                for k, v in sorted(det3d.items()))
            log(f"🎯 YOLO 目标检测 (真实, {_src} 源): {n}/3 目标 · {desc}"
                + ("" if _src == "real" else ""))
            if _src in ("real", "ar"):
                log("   2D: %s · 3D: %d 点%s" % (
                    {k: round(v["conf"], 2) for k, v in (det2d or {}).items()}, len(det3d),
                    "" if not _meta.get("gaps") else " · 缺证据 %s" % _meta.get("gaps")))
            elif aligned is not None:
                log(f"   39D 对齐 (align 真实执行): hand={np.round(aligned[0:3],3)} · "
                    f"光模块={np.round(aligned[4:7],3)} · hole={np.round(aligned[36:39],3)}")
        # 🔴 2026-10-29: 返回 dict 才能被壳认成「实现执行」(返回 True/False 会落成 "实现返回非 dict → 直通")
        #   out1 = 刚写盘的 vision_points 契约**原文** ⇒ 下游拿到的就是契约本身, 口径不可能漂。
        _payload = {}
        _op = locals().get("_path")
        if _op and os.path.exists(_op):
            try:
                with open(_op, encoding="utf-8") as _fh:
                    _payload = _json.load(_fh)
            except Exception:                                            # noqa: BLE001
                _payload = {}
        if not isinstance(_payload, dict) or not _payload:
            _payload = {"t": time.time(), "frame": (_meta or {}).get("frame"),
                        "verified": False, "units": "mm", "points": {},
                        "n_points": 0, "src": _src,
                        "gaps": list((_meta or {}).get("gaps") or [])}
        _payload["src_kind"] = _src
        _payload["cached_ago_s"] = 0.0
        _YOLO_CACHE["l2_out"] = {"t": _now, "payload": _payload}
        return {"out1": _payload}
    except Exception as e:
        if log:
            log(f"⚠️ YOLO 目标检测真实执行失败: {e}")
        return {"out1": None}


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_yolo
