#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两路 AOI 真验收(金手指 10082 / 表面 10083): 触发 → 等判决(按 t 变化) → 量图。

为什么不能只看 capture_detect 的 200: 那只是“受理”, 判决在 /last_result; 而且
工件不在位时两路都会回 `count=0`(看着像合格) ⇒ 必须同时量原帧亮度 + 判据自报。

用法(在操作机上跑, 不占相机、不写产线文件):
    ./gui-venv311/bin/python scripts/aoi_two_route_verify.py [host]
    # 例: ./gui-venv311/bin/python scripts/aoi_two_route_verify.py 192.168.23.23

判读: 每路先看 origin 的 p95/亮区占比 —— 平场(p95≈mean·亮区占比≈0)或近黑 = **工件不在位/光源未开**,
此时 count=0 不代表合格; 再把 store_dir 下的两张原帧给人看。
"""
import json
import sys
import time
import urllib.request

import numpy as np
import cv2

OUT = "/tmp/aoi_verify"


def _req(url: str, data: bytes | None = None, timeout: int = 40) -> bytes:
    r = urllib.request.Request(url, data=data,
                               headers={"User-Agent": "zmax-probe",
                                        "Content-Type": "application/json"})
    return urllib.request.urlopen(r, timeout=timeout).read()


def _stats(b: bytes) -> dict:
    a = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_GRAYSCALE)
    if a is None:
        return {"err": "decode_fail", "bytes": len(b)}
    g = a.astype(np.float32)
    return {"size": list(a.shape[::-1]), "bytes": len(b),
            "mean": round(float(g.mean()), 1),
            "p50": round(float(np.percentile(g, 50)), 1),
            "p95": round(float(np.percentile(g, 95)), 1),
            "bright_frac": round(float((a > 120).mean()), 3),
            "sat250": round(float((a >= 250).mean()), 4),
            "dark25": round(float((a < 25).mean()), 4)}


def _wait_result(host: str, port: int, t0: float, budget: float = 45.0) -> dict:
    """轮询到 /last_result 的 t 比触发前新为止; 404 = 还没出, 不是故障。"""
    deadline = time.time() + budget
    last = {}
    while time.time() < deadline:
        time.sleep(2)
        try:
            d = json.loads(_req("http://%s:%d/last_result" % (host, port), timeout=10))
        except Exception as e:                                        # noqa: BLE001
            last = {"code": "ERR", "msg": str(e)[:80]}
            continue
        last = d
        t = d.get("t")
        if d.get("code") == 200 and t and str(t) != str(t0):
            return d
        if d.get("code") not in (200, 404):
            return d
    return last or {"code": "TIMEOUT"}


def verify(host: str, port: int, name: str) -> dict:
    print("=" * 12, port, name)
    t0 = None
    try:
        t0 = json.loads(_req("http://%s:%d/last_result" % (host, port), timeout=8)).get("t")
    except Exception:                                                 # noqa: BLE001
        pass
    try:
        print(" capture:", _req("http://%s:%d/capture_detect" % (host, port), b"{}", 60)
              .decode("utf-8", "ignore")[:100])
    except Exception as e:                                            # noqa: BLE001
        print(" capture 失败:", e)
        return {"port": port, "ok": False, "err": str(e)[:120]}

    t1 = time.time()
    res = _wait_result(host, port, t0)
    print(" last_result(%.1fs):" % (time.time() - t1), json.dumps(res, ensure_ascii=False)[:300])

    out = {"port": port, "name": name, "verdict": res.get("verdict"),
           "count": res.get("count"), "ms": res.get("ms"),
           "judge_ok": res.get("judge_ok"), "judge_why": res.get("judge_why"),
           "model_input_md5": res.get("model_input_md5")}
    for kind, tag in (("crop", "判据图"), ("origin&grab=1", "原帧")):
        try:
            b = _req("http://%s:%d/picture?kind=%s" % (host, port, kind), timeout=45)
            out[tag] = _stats(b)
            print(" %s: %s" % (tag, out[tag]))
        except Exception as e:                                        # noqa: BLE001
            out[tag] = {"err": str(e)[:80]}
            print(" %s: 失败 %s" % (tag, e))
    if port == 10082:
        try:
            reg = json.loads(_req("http://%s:%d/region" % (host, port), timeout=15))
            out["region"] = {"angle": reg.get("angle"), "focus": reg.get("focus"),
                             "crop_size": (reg.get("quality") or {}).get("crop_size"),
                             "gold_px": (reg.get("quality") or {}).get("gold_px")}
            print(" /region:", out["region"])
        except Exception as e:                                        # noqa: BLE001
            out["region"] = {"err": str(e)[:80]}
    return out


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.23.23"
    reports = [verify(host, 10082, "金手指"), verify(host, 10083, "表面")]
    # 判读口径(机器无关, 直接打出来, 免得下一次又要重推):
    print("\n==== 判读")
    for r in reports:
        o = r.get("原帧") or {}
        flat = isinstance(o.get("p95"), (int, float)) and o.get("p95", 0) - o.get("mean", 0) < 8
        dark = isinstance(o.get("mean"), (int, float)) and o["mean"] < 25
        if flat or dark:
            print(" %d %s: **取像端空场**(p95=%s mean=%s 亮区=%s) ⇒ `count=%s` 不能当合格, 要工件在位/开光源"
                  % (r["port"], r["name"], o.get("p95"), o.get("mean"), o.get("bright_frac"), r.get("count")))
        else:
            print(" %d %s: 画面有内容(mean=%s p95=%s); 判决=%s count=%s judge_ok=%s"
                  % (r["port"], r["name"], o.get("mean"), o.get("p95"),
                     r.get("verdict"), r.get("count"), r.get("judge_ok")))
    try:
        import os
        os.makedirs(OUT, exist_ok=True)
        for r in reports:
            for kind, fn in (("origin&grab=1", "origin"), ("crop", "judge")):
                try:
                    b = _req("http://%s:%d/picture?kind=%s" % (host, r["port"], kind), timeout=45)
                    open("%s/%d_%s.jpg" % (OUT, r["port"], fn), "wb").write(b)
                except Exception:                                     # noqa: BLE001
                    pass
        print("\n取证图已存:", OUT)
    except Exception:                                                 # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
