# -*- coding: utf-8 -*-
"""🛡 engine_gate.py — 「引擎是宪法, 策略是提案」的强制执行点 (L2 收口闸)

规矩(老倪 2026-11-24):
    任何**自动**动作下发, 载荷里必须带两样东西, 缺一个就拒:
        src_engine ∈ {ss_mani_eng, ss_mani10, ss_mani_flow}   ← 谁算的这条动作
        gate = {force_ok: true, conf_ok: true}                ← 引擎放行凭据
    人工点动 (方向键/示教/现场手动) 走 src_engine ∈ MANUAL_ENGINES, 记为 bypass, 不拦但必须留痕。

三档 (环境变量 ZMAX_ENGINE_GATE):
    enforce (生产) 缺字段 ⇒ 直接拒, 不建命令
    warn    (默认) 缺字段 ⇒ 照发, 但写 reject 记录 (用于上线前量"谁会缺")
    off            完全不检查 (只用于排障), 仍然留痕

留痕: zmax_data/ss_live/engine_gate.jsonl (5MB 自动轮转), 每条含 t / kind / ok / reason / src_engine。
"""
from __future__ import annotations

import json
import os
import time

ALLOWED_ENGINES = ("ss_mani_eng", "ss_mani10", "ss_mani_flow")
MANUAL_ENGINES = ("manual_jog", "keyboard", "operator", "teach")
_MODES = ("enforce", "warn", "off")
_LOG_MAX = 5 * 1024 * 1024


def mode() -> str:
    m = (os.environ.get("ZMAX_ENGINE_GATE") or "warn").strip().lower()
    return m if m in _MODES else "warn"


def _log_path() -> str:
    base = os.environ.get("ZMAX_SS_LIVE") or os.path.expanduser("~/zmax/zmax_data/ss_live")
    return os.path.join(base, "engine_gate.jsonl")


def record(rec: dict) -> None:
    p = _log_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.exists(p) and os.path.getsize(p) > _LOG_MAX:
            os.replace(p, p + ".1")
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:                                                   # noqa: BLE001
        pass                                                            # 记账失败不许影响控制


def validate(payload: dict | None, kind: str = "auto") -> dict:
    """返回 {'ok': bool, 'reason': str, 'bypass': bool, 'mode': str, 'src_engine': str}"""
    payload = payload if isinstance(payload, dict) else {}
    m = mode()
    src = str(payload.get("src_engine") or "").strip()
    gate = payload.get("gate") if isinstance(payload.get("gate"), dict) else {}
    res = {"ok": True, "reason": "", "bypass": False, "mode": m, "src_engine": src}

    if m == "off":
        res.update(reason="ZMAX_ENGINE_GATE=off(仅排障)", bypass=True)
    elif kind == "manual":
        if src and src not in MANUAL_ENGINES and src in ALLOWED_ENGINES:
            res["reason"] = "人工通道却带引擎签名(%s), 按引擎动作要求 gate" % src
            ok_f, ok_c = bool(gate.get("force_ok")), bool(gate.get("conf_ok"))
            if not (ok_f and ok_c):
                res["ok"] = False if m == "enforce" else True
                res["reason"] = "gate.force_ok/conf_ok 不满足 (force_ok=%s conf_ok=%s)" % (ok_f, ok_c)
        else:
            res.update(src_engine=src or "manual_jog", bypass=True, reason="人工点动(留痕不拦)")
    else:                                                                # auto
        if not src:
            res.update(ok=(m != "enforce"), reason="缺 src_engine (必须是 %s)" % " | ".join(ALLOWED_ENGINES))
        elif src in MANUAL_ENGINES:
            res.update(ok=False, reason="自动通道不许用人工签名 %s" % src)
        elif src not in ALLOWED_ENGINES:
            res.update(ok=(m != "enforce"), reason="未知 src_engine=%r (允许 %s)" % (src, " | ".join(ALLOWED_ENGINES)))
        elif not (bool(gate.get("force_ok")) and bool(gate.get("conf_ok"))):
            res.update(ok=(m != "enforce"),
                       reason="gate 不放行 force_ok=%s conf_ok=%s" % (bool(gate.get("force_ok")),
                                                                      bool(gate.get("conf_ok"))))
        else:
            res["reason"] = "引擎放行"

    if not res["ok"] or res["bypass"]:
        rec = {"t": round(time.time(), 3), "kind": kind, "ok": bool(res["ok"]),
               "mode": m, "src_engine": res["src_engine"], "bypass": bool(res["bypass"]),
               "reason": res["reason"],
               "skill": payload.get("skill") or payload.get("sk") or "",
               "target": payload.get("target") or payload.get("pose6") or ""}
        record(rec)
    return res


def check_or_reject(payload: dict | None, kind: str = "auto", logger=None) -> bool:
    """执行口调用点: True=放行, False=拒(调用方必须 return, 不许默认放行)。"""
    r = validate(payload, kind=kind)
    if not r["ok"]:
        msg = "⛔ 引擎闸拒绝(%s): %s · src_engine=%r" % (r["mode"], r["reason"], r["src_engine"])
        if logger:
            logger(msg)
        else:
            print(msg)
    return bool(r["ok"])
