#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_link.py — 工控机 AOI 程序的客户端 (10082 金手指 / 10083 表面)

老倪 2026-10-11: 「AR你要完成 AOI检查, 你要联合工控机的AOI程序, 能够完成缺陷检测,
完成金手指的矩形图形的搜索, 以及侧边的位置修正」

语义(照 zmax-aoi-service 技能的实测口径, 别记错):
- `POST /capture_detect` 回 {"code":200,"msg":"success"} **只是受理**(拍照进队列), 不是合格判决;
- 真判决在 `GET /last_result` (verdict/count/defects/ms), 刚拍完可能是 404「尚无检测结果」⇒ 必须轮询;
- `/region?grab=1` = 原图坐标系里的金手指区域(定向框 quad / bbox) + 倾角 + 对焦清晰度;
- `/crop_info` = 裁剪质量(score/残余倾角/金覆盖/键数 judge)。
本模块**只读 + 单次触发**, 不做批量轮询; 所有调用带 UA(不带 UA 会被服务丢掉)。
"""
from __future__ import annotations

import json
import time
import urllib.request

HOST = "192.168.23.23"
PORTS = {"gf": 10082, "housing": 10083}
UA = {"User-Agent": "zmax-probe/ar", "Accept": "*/*"}


def _req(path: str, port: int = 10082, method: str = "GET", timeout: float = 20.0, body=None):
    url = "http://%s:%d%s" % (HOST, PORTS.get(str(port), port), path)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    r = urllib.request.Request(url, data=data, method=method, headers=UA)
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return {"ok": True, "http": resp.status, "bytes": len(raw), "ms": round((time.time() - t0) * 1000, 1),
                    "raw": raw}
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read()
        except Exception:                                                        # noqa: BLE001
            pass
        return {"ok": False, "http": e.code, "bytes": len(raw), "ms": round((time.time() - t0) * 1000, 1),
                "raw": raw, "err": "HTTP %d" % e.code}
    except Exception as e:                                                       # noqa: BLE001
        return {"ok": False, "http": 0, "bytes": 0, "ms": round((time.time() - t0) * 1000, 1),
                "raw": b"", "err": "%s: %s" % (type(e).__name__, str(e)[:120])}


def _json_of(r):
    try:
        return json.loads(r["raw"].decode("utf-8", "ignore") or "{}")
    except Exception:                                                            # noqa: BLE001
        return {}


def health(port=10082):
    """只读体检: 端口/路由/落盘张数 (不拍照、不取帧)。"""
    out = {}
    for path in ("/storage", "/crop_info", "/last_result"):
        r = _req(path, port)
        out[path] = {"ok": r["ok"], "http": r["http"], "ms": r["ms"], "body": _json_of(r)}
    return out


def detect(port=10082, wait_s=45.0, poll=1.5):
    """真拍一张 + 等判决: 缺陷检测 (返回 verdict/count/defects/ms)。"""
    t0 = time.time()
    post = _req("/capture_detect", port, method="POST", timeout=30)
    acpt = _json_of(post)
    res, last = None, None
    while time.time() - t0 < wait_s:
        r = _req("/last_result", port, timeout=15)
        j = _json_of(r)
        last = {"http": r["http"], "body": j}
        if r["ok"] and (j.get("verdict") is not None or j.get("count") is not None):
            res = j
            break
        time.sleep(poll)
    return {"ok": bool(res), "port": PORTS.get(str(port), port),
            "capture": {"ok": post["ok"], "http": post["http"], "ms": post["ms"], "body": acpt},
            "verdict": (res or {}).get("verdict"), "count": (res or {}).get("count"),
            "defects": (res or {}).get("defects"), "infer_ms": (res or {}).get("ms"),
            "files": {k: (res or {}).get(k) for k in ("topview", "model_input", "origin") if (res or {}).get(k)},
            "total_s": round(time.time() - t0, 2), "last_result": last}


def region(port=10082, grab=True):
    """金手指区域的**矩形图形搜索**: quad/bbox/倾角 + 外接矩形 + 侧边位置修正量。"""
    r = _req("/region" + ("?grab=1" if grab else ""), port, timeout=30)
    j = _json_of(r)
    out = {"ok": r["ok"] and bool(j), "http": r["http"], "ms": r["ms"], "region": j}
    q = j.get("region") or j
    quad = q.get("quad") or q.get("box") or None
    bb = q.get("bbox") or None
    ang = q.get("angle")
    out["quad"], out["bbox"], out["angle_deg"] = quad, bb, ang
    if quad and len(quad) >= 4:
        try:
            import cv2
            import numpy as np
            pts = np.asarray(quad, dtype=np.float32).reshape(-1, 2)
            (cx, cy), (w, h), a = cv2.minAreaRect(pts)
            out["rect"] = {"cx": round(float(cx), 1), "cy": round(float(cy), 1),
                           "w": round(float(w), 1), "h": round(float(h), 1), "angle_deg": round(float(a), 2)}
            # 侧边位置修正: 目标 = 区域水平居中(原图宽的一半) + 倾角归零; 换算 mm 需要实测雅可比(没有就只报 px)
            W = float(q.get("image_w") or q.get("width") or 2448)
            out["side_fix"] = {"dx_px": round(float(cx) - W / 2.0, 1),
                               "angle_deg": round(float(a if abs(a) <= 45 else a - 90), 2),
                               "px_per_mm": None,
                               "note": "dx_px>0 = 工件在画面偏右(要往 -x 修正); 倾角 = 要反旋的角度。"
                                       "px→mm 需现场雅可比(校准后填 px_per_mm)"}
        except Exception as e:                                                   # noqa: BLE001
            out["rect_err"] = str(e)[:100]
    return out


def crop_info(port=10082):
    r = _req("/crop_info", port, timeout=15)
    return {"ok": r["ok"], "http": r["http"], "body": _json_of(r)}


def inspect(port=10082):
    """缺陷检测 + 矩形搜索 + 侧边修正 一次跑完 (AR/AOI 面板用)。"""
    d = detect(port)
    g = region(port, grab=False)                      # 用刚拍的那帧 (不带 grab, 不抢相机)
    c = crop_info(port)
    judge = ((c.get("body") or {}).get("judge") or {})
    return {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "port": PORTS.get(str(port), port),
            "detect": d, "region": g, "judge": {"ver": (c.get("body") or {}).get("judge_ver") or judge.get("ver"),
                                                "n_keys": judge.get("n_keys"), "state": judge.get("state")},
            "verdict_line": "%s · 缺陷 %s · 推理 %sms" % (d.get("verdict"), d.get("count"), d.get("infer_ms"))}


if __name__ == "__main__":
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "health"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 10082
    fn = {"health": health, "detect": detect, "region": region, "crop": crop_info, "inspect": inspect}[which]
    print(json.dumps(fn(port), ensure_ascii=False, indent=1)[:4000])
