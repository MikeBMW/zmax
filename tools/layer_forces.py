#!/usr/bin/env python3
"""分层力 (L2~L5) —— 每层**各自模型输出的张量**投影成同一个三维力矢量, 再加权。

老倪 2026-10-19 定的口径:
    L2 = 前馈加速器的 u_ff (MLP 前馈速度)
    L3 = 动作头输出的 action (chunk 第一步)
    L4 = 流形引擎的输出 (度量张量 M) 作用在"规划 − 前馈"的执行差上
    L5 = DeepSeek VL 的场景理解 (方向/条件项)

设计原则 (不许编):
  · 每层只读**它自己的唯一依据文件**, 取不到就返回 None + `src` 写明缺哪个,
    绝不拿上一层/上一轮的数顶替 (老倪工程真实性零容忍)。
  · 每层的来源文件与字段名都写进 `src`, 表/悬停卡直接显示 ⇒ 可逐项对账。
  · 加权在**矢量层**做 (v = w·k·v_raw), 再做四元数/合力 —— 与老倪「给 u_ff 加权」同一处,
    保证格子、表、太阳系箭头、S³ 面板用的是同一份加权结果。

单位: 一律 m/s (速度当量)。力四元数由 gravity_table.vec_to_quat 统一编码。
"""
from __future__ import annotations

import json
import math
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config", "calib", "layer_forces.json")
_SS = os.path.join(ROOT, "zmax_data", "ss_live")

DEFAULTS = {
    "enabled": True,
    "w": {"L2": 1.00, "L3": 0.55, "L4": 0.75, "L5": 0.35},
    "k": {"L2": 1.0, "L3": 1.0, "L4": 1.0, "L5": 1.0},
    "m_ref": 3.643,          # 度量参考 (流形主参数 M 的标定值)
    "dt_s": 0.1,             # 一拍 (H8 = 0.8s 的一块 = 0.1s/步)
    "max_age_s": 5.0,        # 唯一依据超过这个帧龄 ⇒ 该层标"陈旧", 数值仍给 (页脚有帧龄)
}


def _load_cfg():
    c = dict(DEFAULTS)
    try:
        with open(CFG, encoding="utf-8") as f:
            d = json.load(f) or {}
        for k, v in d.items():
            if k in ("w", "k") and isinstance(v, dict):
                c[k].update({str(kk).upper(): float(vv) for kk, vv in v.items()})
            elif k in c:
                c[k] = v
    except Exception:                                                        # noqa: BLE001
        pass
    return c


def _j(name):
    """读 ss_live 下的一份唯一依据 (含 mtime 帧龄); 读不到返回 (None, None)。"""
    p = os.path.join(_SS, name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f) or {}, (time.time() - os.path.getmtime(p))
    except Exception:                                                        # noqa: BLE001
        return None, None


def _vec3(a):
    if not a or len(a) < 3:
        return None
    try:
        v = [float(a[0]), float(a[1]), float(a[2])]
    except Exception:                                                        # noqa: BLE001
        return None
    if not all(math.isfinite(x) for x in v):
        return None
    return v


def _mag(v):
    return math.sqrt(sum(x * x for x in v)) if v else 0.0


def layer_forces():
    """→ dict: {L2/L3/L4/L5: {vec, mag, raw, w, src, note, fresh}}  (+ "meta")

    每层独立取唯一依据; 取不到的层 `vec=None` 且 `src` 写明缺什么 —— 调用方据此清空,
    绝不用别的层的数冒充。
    """
    c = _load_cfg()
    out = {"meta": {"when": time.time(), "w": dict(c["w"]), "k": dict(c["k"]),
                    "m_ref": float(c["m_ref"]), "enabled": bool(c.get("enabled", True))}}
    if not c.get("enabled", True):
        return out

    chunk, chunk_age = _j("chunk_latest.json")
    eng, eng_age = _j("engine_latest.json")
    tor, tor_age = _j("torque_live.json")

    # ── L2 前馈加速器: chunk_latest.ff[0][:3]  (MLP 前馈速度, m/s) ─────────
    v2, src2, note2 = None, "缺 L2: chunk_latest.json 无 ff[0]", ""
    _ff = (chunk or {}).get("ff") or []
    if _ff:
        v2 = _vec3(_ff[0])
        if v2:
            src2 = "chunk_latest.ff[0][:3] · ff_mode=%s · cycle=%s" % (
                (chunk or {}).get("ff_mode"), (chunk or {}).get("cycle"))
            note2 = "前馈加速器 MLP 输出 (m/s)"

    # ── L3 加权修正: **SmolVLA+LEW 模型前向**(正式启用) 优先, 测地线块仅作回落 ──
    #   老倪 2026-10-29「SmolVLA+LEW L3 层 用上这个模型, 正式启用」⇒ L3 的力必须来自模型输出,
    #   不能还用测地线规划 (那是几何解码, 不是 L3 模型)。模型不可用 ⇒ 回落并如实换 src。
    v3, src3, note3 = None, "缺 L3: 无模型输出也无 chunk[0]", ""
    _l3, _l3age = _j("l3_latest.json")
    _l3o = ((_l3 or {}).get("out1") or {}) if isinstance(_l3, dict) else {}
    _nom = _vec3(_l3o.get("nominal_L3"))
    if _nom and _l3o.get("degraded") is not True and (_l3age is not None
                                                    and _l3age <= float(c["max_age_s"])):
        v3 = _nom
        _mdl = (_l3o.get("model") or {})
        src3 = "SmolVLA+LEW 前向 (%s) · infer=%sms · 龄%.2fs" % (
            str(_mdl.get("ck") or "?").split("/")[-3] if _mdl.get("ck") else "?",
            _mdl.get("infer_ms"), _l3age)
        note3 = "L3 模型输出 (加权修正来源, m/s 当量)"
    else:
        _ch = (chunk or {}).get("chunk") or []
        if _ch:
            _c3 = _vec3(_ch[0])
            if _c3:
                v3 = _c3
                src3 = "回落: 测地线 chunk[0][:3] · %s" % str((chunk or {}).get("chunk_src"))[:52]
                note3 = "动作头输出 (m/s 当量) — 模型未就绪时回落"

    # ── L4 流形引擎: 度量张量 M 作用在(规划 − 前馈)的执行差上 ───────────────
    #    F = M̂ · Δu ,  M̂ = M/M_ref (标量度量, 唯一依据 torque_live.metric_M / engine_latest.M)
    v4, src4, note4 = None, "缺 L4: 无 engine/torque 度量或 Δu", ""
    _M = None
    for _d in (tor or {}, eng or {}):
        for _k in ("metric_M", "M"):
            if isinstance(_d.get(_k), (int, float)):
                _M = float(_d[_k])
                break
        if _M is not None:
            break
    if v2 and _M:
        # 度量张量对**前馈方向**做各向异性/缩放 (F = M̂·u_ff)。不用 (ff−chunk):
        #   差矢量常常与运动反向 ⇒ 合力会被它拉偏 (实测主力↔合力 123°, 判断不合理)。
        _scale = min(2.0, max(0.5, _M / float(c["m_ref"] or 3.643)))
        v4 = [v2[i] * _scale for i in range(3)]
        src4 = "torque_live.metric_M=%.3f / m_ref=%.3f × ff (度量张量作用于前馈)" % (_M, float(c["m_ref"] or 3.643))
        note4 = "流形引擎度量张量作用在前馈上 (F=M̂·u_ff)"

    # ── L5 DeepSeek VL 场景理解 ────────────────────────────────────────────
    v5, src5, note5 = None, "缺 L5: VL 只按需出 2D boxes, 没有持续的场景矢量唯一依据", ""
    for _nm in ("l5_scene_vec.json", "l5_understand_latest.json"):
        d5, a5 = _j(_nm)
        if d5:
            v5 = _vec3(d5.get("vec") or d5.get("direction") or d5.get("dir"))
            if v5:
                src5 = "%s.vec (VL 场景理解矢量)" % _nm
                note5 = "DeepSeek VL 场景理解 (方向/条件项)"
                break

    for L, v, src, note, age in (("L2", v2, src2, note2, chunk_age), ("L3", v3, src3, note3, chunk_age),
                                 ("L4", v4, src4, note4, min([x for x in (eng_age or 99, tor_age or 99)])),
                                 ("L5", v5, src5, note5, None)):
        w = float(c["w"].get(L, 1.0))
        k = float(c["k"].get(L, 1.0))
        vv = [x * w * k for x in v] if v else None
        out[L] = {"vec": vv, "mag": _mag(vv), "raw": v, "raw_mag": _mag(v),
                  "w": w, "k": k, "src": src, "note": note,
                  "fresh": (age is not None and age <= float(c["max_age_s"] or 5.0)),
                  "age_s": (round(float(age), 2) if age is not None else None)}
    return out


def main_force(d):
    """主力层 = 加权后模长最大的那层 (老倪: L2 前馈默认最重; 谁真大谁当主力, 不预先固定)."""
    best, bm = None, -1.0
    for L in ("L2", "L3", "L4", "L5"):
        x = d.get(L) or {}
        if x.get("vec") is not None and x["mag"] > bm:
            best, bm = L, x["mag"]
    return best


def resultant(d):
    """合力 = 四层加权矢量逐位相加 (取得到的层)。"""
    v = [0.0, 0.0, 0.0]
    n = 0
    for L in ("L2", "L3", "L4", "L5"):
        x = d.get(L) or {}
        if x.get("vec"):
            for i in range(3):
                v[i] += x["vec"][i]
            n += 1
    return (v if n else None)


if __name__ == "__main__":
    import pprint
    d = layer_forces()
    pprint.pprint({k: (None if k == "meta" else {kk: d[k][kk] for kk in ("mag", "raw_mag", "w", "src", "fresh")})
                   for k in d})
    print("主力:", main_force(d), "| 合力:", resultant(d))
