# -*- coding: utf-8 -*-
"""金手指 10082 —— 「搬运」工控机真判决 (AOI 算法层)。

这里**不重算**判决: 金手指的真判决是工控机上的 YOLO(bestgf05088.pt.enc, imgsz=960,
吃同帧派生 960 方图), 本机没有那份权重 ⇒ 只能搬 /last_result 的判决/缺陷数/推理ms
+ /crop_info 的几何。要本机推理请用 gold_yolo.py (两条来源在话题名与 src 字段上分开)。

🔴 不编数: `/last_result` 的 404「尚无检测结果」= 本轮没检 ⇒ 判决=2(未检), 绝不填 0 冒充 OK。

调用方注入:
    cache    可写 dict (中间件 _YOLO_CACHE), 本模块只往里面放 "gold_aoi"
    publish  话题发布回调 publish(sig: dict, log) —— 由节点层提供
"""
from __future__ import annotations

import os
import time as _t

_DOWN_UNTIL = 0.0        # 不可达冷却到期时刻 (不在线时不拖 300UPH 节拍)
PORT = 10082


def gold_bypass(log=None, cache=None, publish=None, host=None):
    """搬运工控机金手指判决 → dict + 话题。失败返回 None / 降级 dict。"""
    global _DOWN_UNTIL
    try:
        import json as _json
        import socket as _sock
        import urllib.request as _urq
        if cache is None:
            cache = {}
        if _t.time() < _DOWN_UNTIL:
            _c = {"ok": False, "verdict": "unavailable", "code": 2,
                  "why": "10082 已知不可达 (冷却中, 不重复探)", "cached_down": True}
            cache["gold_aoi"] = _c
            return _c
        _host = host or os.environ.get("ZMAX_AOI_GOLD_HOST", "192.168.23.23")
        try:
            _sock.create_connection((_host, PORT), timeout=0.25).close()
        except OSError as _e:
            _DOWN_UNTIL = _t.time() + 60.0
            _c = {"ok": False, "verdict": "unavailable", "code": 2,
                  "why": f"{_host}:{PORT} 不可达 ({type(_e).__name__}), 60s 内不再探",
                  "cached_down": True}
            cache["gold_aoi"] = _c
            if log:
                log(f"🌑 金手指 {PORT} 旁路: {_c['why']} — 本机几何体检那一路不受影响")
            return _c

        def _get(path, timeout=1.2):
            _req = _urq.Request(f"http://{_host}:{PORT}{path}",
                                headers={"User-Agent": "zmax-probe"})   # 不带 UA 会被服务丢掉
            try:
                with _urq.urlopen(_req, timeout=timeout) as _r:
                    return _json.loads(_r.read().decode("utf-8", "replace"))
            except _urq.HTTPError as _he:
                # 404「尚无检测结果」是合法形态(本轮没触发拍照), 不是故障
                try:
                    return _json.loads(_he.read().decode("utf-8", "replace"))
                except Exception:                                      # noqa: BLE001
                    return {"code": _he.code, "msg": f"HTTP {_he.code}"}

        try:
            lr = _get("/last_result", 1.5)
        except Exception as _e:                                        # noqa: BLE001
            lr = {"code": 404, "msg": f"读取失败 {type(_e).__name__}"}
        try:
            ci = _get("/crop_info", 1.2)
        except Exception as _e:                                        # noqa: BLE001
            ci = {"code": 404, "msg": f"读取失败 {type(_e).__name__}"}

        _has = int(lr.get("code") or 0) == 200
        _v = str(lr.get("verdict") or "").upper()
        _code = 2 if not _has else (1 if _v in ("NG", "FAIL", "BAD") else 0)
        _jd = (ci.get("judge") or {}) if isinstance(ci, dict) else {}
        _nb = ci.get("bbox") or _jd.get("bbox") or []
        res = {
            "ok": _has, "kind": "gold_aoi",
            "verdict": (_v or ("未检" if _code == 2 else "OK")), "code": _code,
            "defects": lr.get("count"), "infer_ms": lr.get("ms"),
            "detect_type": lr.get("detect_type"),
            "n_keys": _jd.get("n_keys"),
            "pitch_px": _jd.get("lattice_pitch_px") or _jd.get("pitch"),
            "angle_deg": ci.get("angle"),
            "kept_rows": _jd.get("kept_rows") or _jd.get("key_row_span"),
            "bbox": list(_nb)[:4] if _nb else None,
            "judge_ver": _jd.get("ver") or ci.get("judge_ver"),
            "gold_file": lr.get("topview"), "model_input": lr.get("model_input"),
            "src": f"工控机 {_host}:{PORT} (/last_result + /crop_info, 同源搬运)",
            "why": (None if _has else (lr.get("msg") or "尚无检测结果")),
        }
        cache["gold_aoi"] = res

        _sig = {"AOI.判决": float(_code)}
        if res.get("defects") is not None:
            _sig["AOI.缺陷数"] = float(res["defects"])
        if res.get("infer_ms") is not None:
            _sig["AOI.推理_ms"] = float(res["infer_ms"])
        if res.get("n_keys") is not None:
            _sig["AOI.金手指根数"] = float(res["n_keys"])
        if res.get("angle_deg") is not None:
            _sig["AOI.倾角_deg"] = float(res["angle_deg"])
        if _nb and len(_nb) >= 4:
            _x, _y, _w, _h = [float(v) for v in list(_nb)[:4]]
            _sig["AOI.矩形中心_x"] = _x
            _sig["AOI.矩形中心_y"] = _y
            _sig["AOI.矩形宽_px"] = _w
            _sig["AOI.矩形高_px"] = _h
        _sig["AOI.拍照_epoch"] = float(_t.time())
        if publish:
            publish(_sig, log)

        if log:
            if _has:
                log(f"🎯 金手指 {PORT} 同源判决: {res['verdict']} · 缺陷 {res.get('defects')} · "
                    f"推理 {res.get('infer_ms')}ms · 根数 {res.get('n_keys')} · 倾角 {res.get('angle_deg')} "
                    f"(judge_ver={res.get('judge_ver')})")
            else:
                log(f"⏸ 金手指 {PORT} 同源判决: 未检 — {res.get('why')} (判决=2, 不冒充 OK)")
            log(f"   金手指话题已发出 ({len(_sig)} 个): "
                + " · ".join("%s=%g" % (k.split(".")[-1], v) for k, v in sorted(_sig.items())))
        return res
    except Exception as e:                                            # noqa: BLE001
        if log:
            log(f"⚠️ 金手指 {PORT} 旁路失败 (不影响本机几何体检): {type(e).__name__}: {e}")
        return None
