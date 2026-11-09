# -*- coding: utf-8 -*-
"""ss_aoi — 节点实现正文 (文件名 = 画布节点: ss_aoi)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_aoi   ·   registry key: ss_aoi
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _YOLO_CACHE,
    _YOLO_DIR,
    _ar_aoi_publish,
    _gold_bypass,
    _load_mod,
    _surface_bypass,
    _yolo_capture,
    _yolo_ensure_aligner,
    os,
)

def node_ss_aoi(ctx):
    """🔍 光学质量检测 — 真实执行: 目标帧 → quality_check.py AOIQualityChecker 图像处理缺陷检测,
    并把 AOI 话题 (判决/缺陷数/划伤/污点/清晰度/灰度偏差/边缘占比/取像体检) 发到 AR/AOI 信号总线。
    源码: policies/yolo_3d/quality_check.py (AOIQualityChecker.check) — 右键源码与真实执行同源, 断点可进
    🐛 2026-09-02: 原只加载 detection_targets.json 清单 (无实际检测) → 改为真实帧图像处理检测
    🔁 2026-10-11: 「外观质量检测」→「光学质量检测」(老倪); 新增 AOI 话题发布 (信号分析页可看)"""
    log = ctx.get("log")
    try:
        qc_path = os.path.join(_YOLO_DIR, "quality_check.py")
        qc = _load_mod("yolo_3d.quality_check", qc_path)    # 正常 import (断点可绑)
        # 目标帧: 优先用 YOLO 节点缓存帧, 无则同源采样一帧 (与 node_ss_yolo 一致)
        img = _YOLO_CACHE.get("img")
        if img is None:
            aligner = _yolo_ensure_aligner(log)
            _, _, img = _yolo_capture(log, aligner)
        checker = qc.AOIQualityChecker()
        res = checker.check(img)
        _YOLO_CACHE["aoi"] = res
        # 🔍 发出 AOI 话题: 值全取自本轮真实检测结果 (quality_check.check 的字段), 缺的键不写
        _sig = {"光学质量检测.判决": 0.0 if res.get("pass") else 1.0}
        for _k, _f in (("光学质量检测.划伤数", "scratch"), ("光学质量检测.污点数", "blob"),
                       ("光学质量检测.清晰度", "focus"), ("光学质量检测.灰度偏差", "gray_dev"),
                       ("光学质量检测.边缘占比", "edge_frac")):
            _v = res.get(_f)
            if isinstance(_v, (int, float)):
                _sig[_k] = float(_v)
        if isinstance(res.get("scratch"), (int, float)) and isinstance(res.get("blob"), (int, float)):
            _sig["光学质量检测.缺陷数"] = float(res["scratch"]) + float(res["blob"])
        _qv = str(((res.get("quality") or {}).get("verdict") or "")).lower()
        if _qv:
            _sig["光学质量检测.取像体检"] = float({"ok": 0, "overexposed": 1, "too_dark": 2,
                                                  "gaps_washed": 3}.get(_qv, 4))
        _ar_aoi_publish(_sig, log)
        # 取像参数 + 取像体检先上屏: 2026-10-08 实测教训 —— 参数不对(自动曝光开着)时谈缺陷判定没有意义
        _q = res.get("quality") or {}
        if log:
            log(qc.AOIQualityChecker.camera_profile_line())
            log(qc.AOIQualityChecker.production_profile_line())   # 产线在工控机 / 调试在本仓库(旁路关系)
            if _q:
                _mark = {"ok": "✅", "overexposed": "🔴", "too_dark": "🌑", "gaps_washed": "🌫️"}.get(_q.get("verdict"), "❔")
                log(f"{_mark} 取像体检: {_q.get('verdict')} — {_q.get('why')}")
        if log:
            for it in res.get("items", []):
                v = it["value"] if it["value"] is not None else it.get("note", "—")
                log(f"🔍 {it['target_id']} {it['defect']}: {v} (判据 {it['threshold']}) → "
                    f"{'✅' if it['pass'] else '❌'}")
            log(f"🔍 光学质量检测 (真实图像处理): {qc.summarize(res)} (quality_check.py)")
            log(f"🔍 AOI 话题已发出 ({len(_sig)} 个): " + " · ".join("%s=%g" % (k.split('.')[-1], v)
                                                                  for k, v in sorted(_sig.items())))
        _gold_bypass(log)             # 🆕 10082 金手指同源搬运转发 (工控机 YOLO 真判决)
        _surface_bypass(log)          # 🆕 10083 表面旁路 (4060 本机), 失败不影响金手指那一路
        # 🔴 2026-10-29 接口对齐: 原来 return bool ⇒ 壳判定「实现返回非 dict → 直通」⇒ 下游
        #    ssplan/ssdec 拿不到 AOI 判决。改为发业务字典 (与 INTACT 节点同一口径)。
        _items = []
        for _it in (res.get("items") or [])[:12]:
            _items.append({"id": _it.get("target_id"), "defect": _it.get("defect"),
                           "value": _it.get("value"), "threshold": _it.get("threshold"),
                           "pass": bool(_it.get("pass")),
                           "note": _it.get("note")})
        return {"kind": "aoi", "pass": bool(res.get("pass")),
                "verdict": (_q.get("verdict") if _q else None),
                "verdict_why": (_q.get("why") if _q else None),
                "scratch": res.get("scratch"), "blob": res.get("blob"),
                "focus": res.get("focus"), "gray_dev": res.get("gray_dev"),
                "edge_frac": res.get("edge_frac"),
                "defect_n": (int(res.get("scratch") or 0) + int(res.get("blob") or 0))
                            if isinstance(res.get("scratch"), (int, float)) else None,
                "items": _items,
                "sig_n": len(_sig),
                "src": "quality_check.AOIQualityChecker (本机图像处理)",
                "remote": (f"10083 {(_AOI_REMOTE.get('surface') or '未接')}"
                           if isinstance(globals().get("_AOI_REMOTE"), dict) else "10083 未接"),
                "no_truth": True}
    except Exception as e:
        if log:
            log(f"⚠️ 光学质量检测真实执行失败: {e}")
        # 失败也要有输出 (老倪: 可以没有真值, 但必须有输出, 接口要对齐)
        return {"kind": "aoi", "pass": None, "verdict": "unavailable",
                "err": f"{type(e).__name__}: {e}", "items": [], "no_truth": True}


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_aoi
