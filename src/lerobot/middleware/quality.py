# -*- coding: utf-8 -*-
"""物理量质检 (质量告警的真正依据)。

老倪 2026-10-17: 「质量告警窗口有功能么? 你真的在报警么? 你的报警要面向物理值不符合物理规律,
   超过最大值 / 过最小值等」

之前所谓"告警"只看 QoS/频率/丢包 (总线层面), 从不看**信号值本身**; 于是页面永远是空的,
或者只在话题没数据时闪一条 —— 那不是质量告警, 是心跳监视。

本模块只看"这个数对不对":
  ① 数值有效性: NaN / inf / 非数值
  ② 量程: 参数中心给的 min/max (mw_signal ← params) —— 超上限 / 低于下限
  ③ 物理规律 (名称即语义, 不猜):
       · prob/probability/ratio/rate/ok_rate/p_* ∈ [0,1] (或百分比 ≤100)
       · mass/inertia/stiffness/damping ≥ 0
       · temperature ≥ -273.15 °C
       · pressure ≥ 0
       · 角度类 |deg| ≤ 720, 关节速度 |vel| ≤ 1000
  ④ 单位缺失: 有值但没单位 (warn, 不是 fail —— 物理量不能没单位)
  ⑤ 相邻帧跳变: |Δ| > span*10 或 > 1e6 (warn, 多半是单位错/串帧)

判定值: "ok" / "warn" / "fail" / "unknown" (unknown = 没有量程也没有物理规则可用, 如实标注)
"""
from __future__ import annotations

import math

_PCT = ("pct", "percent", "百分比")
_PROB = ("prob", "probability", "confidence", "score", "ratio", "rate", "ok_rate", "success_rate",
         "p_ok", "p_succ", "p_hold", "likelihood")
_NONNEG = ("mass", "inertia", "stiffness", "damping", "friction", "torque_limit", "capacity",
           "n_", "count", "bytes", "num")
_TEMP = ("temp", "temperature", "t_amb", "celsius")
_PRESS = ("pressure", "press", "bar", "kpa", "mpa")
_ANGLE = ("deg", "angle", "yaw", "pitch", "roll", "theta", "q1", "q2", "q3", "q4", "q5", "q6", "q7")
_VEL = ("vel", "omega", "speed")


def _f(v):
    try:
        if isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def check_field(name, value, unit=None, vmin=None, vmax=None):
    """单个信号值 → (verdict, 说明)。verdict ∈ ok/warn/fail/unknown。"""
    nm = str(name or "").lower()
    x = _f(value)
    if x is None:
        if value is None or value == "":
            return "warn", "值为空 (没有实测)"
        return "fail", "非数值: %r" % (value,)
    if math.isnan(x):
        return "fail", "NaN (计算发散/未初始化)"
    if math.isinf(x):
        return "fail", "inf (溢出)"

    lo = _f(vmin)
    hi = _f(vmax)
    _plo, _phi = phys_range(nm)
    _src = "声明"
    if lo is None and _plo is not None:
        lo, _src = _plo, "物理规律"
    if hi is None and _phi is not None:
        hi, _src = _phi, "物理规律"
    if lo is not None and x < lo:
        return "fail", "低于下限: %s < %s%s (%s)" % (_n(x), _n(lo), _u(unit), _src)
    if hi is not None and x > hi:
        return "fail", "超上限: %s > %s%s (%s)" % (_n(x), _n(hi), _u(unit), _src)

    # 物理规律 (按信号名语义; 只在没有显式量程或量程更宽时才补这一刀)
    if any(k in nm for k in _PROB):
        cap = 100.0 if any(k in nm for k in _PCT) else 1.0
        if x < 0 or x > cap:
            return "fail", "概率/比例越界: %s ∉ [0, %s]" % (_n(x), _n(cap))
    if any(k in nm for k in _NONNEG) and x < 0:
        return "fail", "质量/刚度/计数类不允许负值: %s%s" % (_n(x), _u(unit))
    if any(k in nm for k in _TEMP) and x < -273.15:
        return "fail", "温度低于绝对零度: %s%s" % (_n(x), _u(unit))
    if any(k in nm for k in _PRESS) and x < 0:
        return "fail", "压力不允许负值: %s%s" % (_n(x), _u(unit))
    if any(k in nm for k in _ANGLE) and abs(x) > 720:
        return "warn", "角度异常 (>720°): %s%s" % (_n(x), _u(unit))
    if any(k in nm for k in _VEL) and abs(x) > 1000:
        return "warn", "速度异常 (>1000): %s%s" % (_n(x), _u(unit))

    if (lo is not None or hi is not None) or any(k in nm for k in _PROB + _NONNEG + _TEMP + _PRESS):
        if not str(unit or "").strip() and any(k in nm for k in ("mass", "inertia", "temp", "pressure",
                                                                "vel", "omega", "force", "torque")):
            return "warn", "有值无单位: %s (物理量必须带单位)" % _n(x)
        return "ok", "" if (lo is None and hi is None) else "在 [%s, %s]%s" % (_n(lo), _n(hi), _u(unit))
    return "unknown", "无量程/无物理规则 (无法判定, 不假装 OK)"


def _n(x):
    if x is None:
        return "—"
    if isinstance(x, float):
        return ("%.6g" % x)
    return str(x)


def _u(u):
    return (" " + str(u)) if u else ""


def scan_frames(frames, jump_span=10.0):
    """frames: [dict(topic, name, value, unit, vmin, vmax, prev)] → 告警列表。

    每条: {level, object, rule, msg}
    """
    out = []
    for fr in frames or []:
        name = fr.get("name")
        v = fr.get("value")
        unit, vmin, vmax = fr.get("unit"), fr.get("vmin"), fr.get("vmax")
        topic = fr.get("topic") or ""
        verdict, why = check_field(name, v, unit, vmin, vmax)
        obj = "%s · %s" % (topic, name) if topic else str(name)
        if verdict in ("fail", "warn"):
            out.append({"level": verdict, "object": obj, "rule": _rule_of(why), "msg": why})
        # 跳变
        x, p = _f(v), _f(fr.get("prev"))
        if x is not None and p is not None:
            span = abs((_f(vmax) or 0.0) - (_f(vmin) or 0.0))
            step = abs(x - p)
            lim = max(span * jump_span, 1e6 if span == 0 else 0.0)
            if lim and step > lim:
                out.append({"level": "warn", "object": obj, "rule": "jump",
                            "msg": "相邻帧跳变 %s → %s (Δ=%s, 阈值 %s)" % (_n(p), _n(x), _n(step), _n(lim))})
    return out


def _rule_of(msg: str) -> str:
    for k, tag in (("NaN", "nan"), ("inf", "inf"), ("非数值", "type"), ("低于下限", "range_low"),
                   ("超上限", "range_high"), ("越界", "physical"), ("不允许负值", "physical"),
                   ("绝对零度", "physical"), ("无单位", "unit"), ("值为空", "empty"),
                   ("角度异常", "physical"), ("速度异常", "physical")):
        if k in msg:
            return tag
    return "rule"


def summarize(alerts):
    """告警 → 一行摘要 (给页面顶部/日志)。"""
    from collections import Counter
    c = Counter(a.get("level") for a in alerts or [])
    return "🔴 fail %d · 🟡 warn %d" % (c.get("fail", 0), c.get("warn", 0)) if alerts else "无告警"


# ─────────────────── 单位/量程的"兜底推断" (无声明时用, 显示带 * 标推断) ───────────────────
_UNIT_SUFFIX = [
    ("_mm", "mm"), ("_nm", "Nm"), ("_um", "um"), ("_cm", "cm"), ("_km", "km"),
    ("_deg", "deg"), ("_rad", "rad"), ("_deg_s", "deg/s"), ("_ms", "ms"), ("_us", "us"),
    ("_kg", "kg"), ("_kgm2", "kg·m²"), ("_n", "N"), ("_nm2", "Nm"), ("_pct", "%"),
    ("_hz", "Hz"), ("_khz", "kHz"), ("_v", "V"), ("_a", "A"), ("_w", "W"), ("_wh", "Wh"),
    ("_bar", "bar"), ("_kpa", "kPa"), ("_mpa", "MPa"), ("_c", "°C"), ("_k", "K"),
    ("_s", "s"), ("_m", "m"), ("_mps", "m/s"), ("_rpm", "rpm"),
]

# 名称 → 物理上必然成立的区间 (与声明量程并存, 取交集; 只用于判"越界", 不用于显示设计值)
_PHYS_RANGE = [
    (("prob", "probability", "confidence", "ratio", "rate", "ok_rate", "success_rate", "p_ok"), (0.0, 1.0)),
    (("pct", "percent", "百分比"), (0.0, 100.0)),
    (("mass", "inertia", "stiffness", "damping", "friction", "capacity"), (0.0, None)),
    (("temp", "temperature"), (-273.15, None)),
    (("pressure", "press", "bar", "kpa", "mpa"), (0.0, None)),
    (("deg", "angle", "yaw", "pitch", "roll", "theta"), (-720.0, 720.0)),
    (("vel", "omega", "speed"), (-1000.0, 1000.0)),
    (("hz", "fps", "rate_hz"), (0.0, 10000.0)),
    (("age_s", "latency", "jitter"), (0.0, 3600.0)),
]


def infer_unit(name: str):
    """按字段名后缀推断单位 (返回 unit 或 None)。调用方必须标明这是**推断**值。"""
    nm = str(name or "").lower()
    for suf, u in _UNIT_SUFFIX:
        if nm.endswith(suf):
            return u
    return None


def phys_range(name: str):
    """按字段名语义给出物理上必然成立的 (min, max); 没有就给 (None, None)。"""
    nm = str(name or "").lower()
    for keys, rng in _PHYS_RANGE:
        if any(k in nm for k in keys):
            return rng
    return None, None
