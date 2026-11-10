# -*- coding: utf-8 -*-
"""光学质量检测 —— 算法层主链 (取像判定口径 + 话题映射 + 业务报告)。

老倪 2026-11-10 定的架构:
    「def node_ss_aoi(ctx) 这个应该是 AOI 的算法，怎么能在中间件里呢?
      AOI 算法，在 /home/ubuntu/zmax/src/lerobot/policies 算法路径，统一管理」

分工 (依赖方向只能 policies ← middleware):
    policies/aoi/quality.py      本文件: **一次完整光学质量巡检**的算法真身
                                 (图像处理判定 → AOI 话题值 → 业务 dict → 日志行)
    middleware/nodes/impl/ss_aoi.py  节点薄壳: 取帧 + 节流 + 调 inspect_aoi + 返回

本文件**不 import lerobot.middleware**; 缓存(cache)、话题发布(publish)、日志(log)
一律由调用方注入 —— 否则算法层反向依赖节点层。

本机判定内核: policies/yolo_3d/quality_check.py::AOIQualityChecker (DET-AOI-01~04
+ 取像健康度)。这里只做「口径收口」: 哪些量上话题、缺陷数怎么合成、报告长什么样,
绝不另写一套阈值。

三路旁路 (互不替代, 来源必须可区分) 也在这里串起来, 因为它们都是 AOI 算法:
    gold.py       金手指 10082 —— 搬运工控机 /last_result 真判决 (remote-10082)
    gold_yolo.py  金手指 10082 —— 本机 YOLO 推理 (local-yolo)
    surface.py    表面   10083 —— 本机 surface_judge 重算 (local-judge)
"""
from __future__ import annotations

# 取像体检 verdict → 枚举值 (进总线必须数字化; 未知一律 4 = 未判定, 不冒充 ok)
QUALITY_ENUM = {"ok": 0, "overexposed": 1, "too_dark": 2, "gaps_washed": 3}
QUALITY_MARK = {"ok": "✅", "overexposed": "🔴", "too_dark": "🌑", "gaps_washed": "🌫️"}

# (话题名, check() 结果里的字段) —— 节点侧不再持有这张表, 口径只有这一处
_SIGNAL_FIELDS = (
    ("光学质量检测.划伤数", "scratch"),
    ("光学质量检测.污点数", "blob"),
    ("光学质量检测.清晰度", "focus"),
    ("光学质量检测.灰度偏差", "gray_dev"),
    ("光学质量检测.边缘占比", "edge_frac"),
)


def quality_signals(res):
    """`AOIQualityChecker.check()` 结果 → AOI 话题值字典 (信号分析页 ar.* 前缀)。

    只写**本轮真算出来的量**; 缺键就不写 (不填 0 冒充)。判决用 0/1 编码 (0=PASS)。
    """
    sig = {}
    if not isinstance(res, dict):
        return sig
    # ① 总判决: 0.0 = 通过, 1.0 = 不通过 (未出数时 pass 为 None ⇒ 不写)
    if res.get("pass") is not None:
        sig["光学质量检测.判决"] = 0.0 if res.get("pass") else 1.0
    # ② 五个原始量
    for name, field in _SIGNAL_FIELDS:
        v = res.get(field)
        if isinstance(v, (int, float)):
            sig[name] = float(v)
    # ③ 缺陷数 = 划痕 + 污点 (两个都在才算, 缺一不算)
    if isinstance(res.get("scratch"), (int, float)) and isinstance(res.get("blob"), (int, float)):
        sig["光学质量检测.缺陷数"] = float(res["scratch"]) + float(res["blob"])
    # ④ 取像体检: 参数不健康的帧上谈缺陷没有意义 (2026-10-08 教训) ⇒ 单独上屏
    qv = str(((res.get("quality") or {}).get("verdict") or "")).lower()
    if qv:
        sig["光学质量检测.取像体检"] = float(QUALITY_ENUM.get(qv, 4))
    return sig


def quality_items(res, limit=12):
    """判定明细 → 可 JSON 化的条目 (None 值保留, 由调用方按 note 展示)。"""
    items = []
    for it in (res.get("items") or [])[:limit]:
        items.append({"id": it.get("target_id"), "defect": it.get("defect"),
                      "value": it.get("value"), "threshold": it.get("threshold"),
                      "pass": bool(it.get("pass")), "note": it.get("note")})
    return items


def quality_report(res, sig_n=0, gold_yolo=None, gold_remote=None, surface=None):
    """检测结果 → 节点对外业务 dict (接口口径在这里收口, 节点不再拼字段)。

    `pass` 为 None = 未出数; 下游 ssplan/ssdec 以 `kind == "aoi"` 识别。
    """
    res = res or {}
    q = res.get("quality") or {}
    scratch = res.get("scratch")
    blob = res.get("blob")
    defect_n = (int(scratch or 0) + int(blob or 0)) if isinstance(scratch, (int, float)) else None
    return {
        "kind": "aoi",
        "pass": (None if res.get("pass") is None else bool(res.get("pass"))),
        "verdict": (q.get("verdict") if q else None),
        "verdict_why": (q.get("why") if q else None),
        "scratch": scratch, "blob": blob,
        "focus": res.get("focus"), "gray_dev": res.get("gray_dev"), "edge_frac": res.get("edge_frac"),
        "defect_n": defect_n,
        "items": quality_items(res),
        "sig_n": sig_n,
        "src": "quality_check.AOIQualityChecker (本机图像处理)",
        "gold_yolo": (None if not gold_yolo else {
            "n": gold_yolo.get("n"), "best_conf": gold_yolo.get("best_conf"),
            "present": gold_yolo.get("present"), "infer_ms": gold_yolo.get("infer_ms"),
            "src": gold_yolo.get("src"), "gate": gold_yolo.get("gate")}),
        "gold_remote": gold_remote,
        # 表面那一路的真实结论取自算法层回写的缓存 (旧实现读一个从未定义的 _AOI_REMOTE
        # ⇒ 页面永远显示"未接", 与日志里"未出图/verdict"自相矛盾)
        "remote": "10083 " + str(surface or "未接"),
        "no_truth": True,
    }


def log_quality(res, sig, log):
    """把这一拍的口径写进画布日志 (只做格式化, 数值全部来自本轮结果)。"""
    if not log:
        return
    try:
        from lerobot.policies.yolo_3d.quality_check import AOIQualityChecker as _QC, summarize as _sum
        log(_QC.camera_profile_line())        # 取像参数先上屏
        log(_QC.production_profile_line())    # 产线在工控机 / 调试在本仓库(旁路关系)
    except Exception:                                                      # noqa: BLE001
        _sum = None
    q = res.get("quality") or {}
    if q:
        log("%s 取像体检: %s — %s" % (QUALITY_MARK.get(q.get("verdict"), "❔"),
                                     q.get("verdict"), q.get("why")))
    for it in res.get("items", []):
        v = it.get("value")
        v = v if v is not None else it.get("note", "—")
        log("🔍 %s %s: %s (判据 %s) → %s" % (it["target_id"], it["defect"], v, it["threshold"],
                                             "✅" if it["pass"] else "❌"))
    if _sum is not None:
        log("🔍 光学质量检测 (真实图像处理): %s (quality_check.py)" % _sum(res))
    if sig:
        log("🔍 AOI 话题已发出 (%d 个): %s" % (
            len(sig), " · ".join("%s=%g" % (k.split(".")[-1], v) for k, v in sorted(sig.items()))))


def inspect_quality(frame, log=None, cache=None, publish=None, checker=None):
    """本机图像处理判定 → (结果 dict, 话题 dict)。**不含**三路旁路。

    frame 为 None 时返回未出数结果 (调用方如实记 gap, 不造 0)。
    """
    if frame is None:
        return ({"pass": None, "items": [], "quality": {"verdict": "unavailable", "why": "无帧"}}, {})
    from lerobot.policies.yolo_3d.quality_check import AOIQualityChecker
    ck = checker or AOIQualityChecker()
    res = ck.check(frame)
    sig = quality_signals(res)
    if cache is not None:
        cache["aoi"] = res
    if sig and publish:
        publish(sig, log)
    log_quality(res, sig, log)
    return res, sig


def inspect_aoi(frame, log=None, cache=None, publish=None):
    """🖼 一次完整光学质量巡检: 本机图像处理判定 + 三路旁路 (金手指搬运/本机YOLO/表面)。

    这是 `node_ss_aoi` 唯一的算法入口。返回节点对外的业务 dict
    (与 INTACT 等节点同一口径: 发业务字典而不是 bool)。
    """
    if cache is None:
        cache = {}
    res, sig = inspect_quality(frame, log=log, cache=cache, publish=publish)

    _gy = gold_yolo = _gold = gold_remote = _surf = surface = None
    try:
        from .gold_yolo import gold_yolo_bypass
        _gy = gold_yolo_bypass(log=log, cache=cache, publish=publish)   # 本机 YOLO 推理
    except Exception as e:                                                 # noqa: BLE001
        if log:
            log(f"⚠️ 金手指本机 YOLO 旁路跳过: {type(e).__name__}: {e}")
    try:
        from .gold import gold_bypass
        _gold = gold_bypass(log=log, cache=cache, publish=publish)      # 搬运 10082 真判决
        gold_remote = (cache.get("gold_aoi") or {}).get("verdict")
    except Exception as e:                                                 # noqa: BLE001
        if log:
            log(f"⚠️ 金手指搬运旁路跳过: {type(e).__name__}: {e}")
    try:
        from .surface import surface_bypass
        _surf = surface_bypass(log=log, cache=cache, publish=publish)   # 10083 本机重算
        _sa = cache.get("surface_aoi") or {}
        surface = _sa.get("verdict") or _sa.get("why")
    except Exception as e:                                                 # noqa: BLE001
        if log:
            log(f"⚠️ 表面旁路跳过: {type(e).__name__}: {e}")

    return quality_report(res, sig_n=len(sig), gold_yolo=gold_yolo or _gy,
                          gold_remote=gold_remote, surface=surface)


__all__ = ["inspect_quality", "inspect_aoi", "quality_signals", "quality_report",
           "quality_items", "log_quality", "QUALITY_ENUM", "QUALITY_MARK"]
