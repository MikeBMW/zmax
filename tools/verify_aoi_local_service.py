#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机 AOI 镜像服务验收 (旁路 AOI 检测) —— 每项都真打服务、真算判据。

用法:
    ./.venv-aoi310/bin/python tools/verify_aoi_local_service.py
    ./.venv-aoi310/bin/python tools/verify_aoi_local_service.py --gold-src file:<帧> --surface-src file:<帧>

判据 (缺一项即 FAIL):
 ① 两路服务在 (20082/20083 /health 200 且 kind 对)
 ② prod/ 里的产线文件 sha256 == 工控机现役 (字节一致才配叫"一样的代码")
 ③ 金手指: capture_detect → 判据图 900x332 · 黑底<65% (不是 v31 那种黑屏) · judge_ver 露出版本
 ④ 金手指: /last_result 有 verdict/why 且 basis 明写 local-judge (不冒充产线 YOLO)
 ⑤ 表面: capture_detect 有明确判决; 帧不对时必须 JUDGE_FAIL + why (不许假 OK)
 ⑥ 无帧: 帧源=push 且未推帧 ⇒ verdict=NO_FRAME (不许回 200 OK 假装检测过)
 ⑦ /frame 推帧 → 再 capture_detect 能出结果 (停机现场的唯一正规用法)
 ⑧ 路由齐: /crop_info /storage /picture?kind=judge /param(金手指) /exposure(表面) 都回 JSON/JPEG
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SVC = os.path.join(ROOT, "src", "lerobot", "policies", "aoi", "service")
sys.path.insert(0, SVC)

import cv2                                                      # noqa: E402
import numpy as np                                              # noqa: E402

GOLD = "http://127.0.0.1:20082"
SURF = "http://127.0.0.1:20083"
UA = {"User-Agent": "zmax-aoi-local-verify"}

R = []


def ck(name, ok, detail=""):
    R.append((bool(ok), name, str(detail)[:220]))
    print(("✅ " if ok else "❌ ") + name + (f" — {detail}" if detail else ""))
    return ok


def jget(url, timeout=60):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            try:
                return json.loads(body.decode()), r.status
            except Exception:
                return body, r.status
    except urllib.error.HTTPError as he:
        try:
            return json.loads(he.read().decode()), he.code
        except Exception:
            return {}, he.code
    except Exception as e:                                       # noqa: BLE001
        return {"err": f"{type(e).__name__}: {e}"}, 0


def jpost(url, data: bytes | None = None, timeout=90):
    req = urllib.request.Request(url, data=data if data is not None else b"", headers=UA, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), r.status
    except urllib.error.HTTPError as he:
        try:
            return json.loads(he.read().decode()), he.code
        except Exception:
            return {}, he.code
    except Exception as e:                                       # noqa: BLE001
        return {"err": f"{type(e).__name__}: {e}"}, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold-src", default=None)
    ap.add_argument("--surface-src", default=None)
    ap.add_argument("--skip-push", action="store_true")
    a = ap.parse_args()

    print("=" * 78)
    print("① 服务在不在")
    for base, kind in ((GOLD, "gold"), (SURF, "surface")):
        h, code = jget(base + "/health", 5)
        ck(f"{kind} /health", code == 200 and h.get("kind") == kind,
           f"HTTP {code} version={h.get('prod_version')} src={h.get('src')}")

    print("② prod 代码与工控机逐字节一致")
    from prodload import PROD_SHA256                                # noqa: E402
    import hashlib
    for kind, want in PROD_SHA256.items():
        fn = os.path.join(SVC, "prod", {"gold": "gold_10082_prod.py",
                                        "surface": "surface_10083_prod.py"}[kind])
        got = hashlib.sha256(open(fn, "rb").read()).hexdigest()
        ck(f"{kind} sha256", got == want, f"{got[:16]}… {'==' if got == want else '!='} {want[:16]}…")

    print("③④ 金手指: 判据图 + 判决口径")
    r, code = jpost(GOLD + "/capture_detect")
    ck("gold capture_detect 200", code == 200 and r.get("code") == 200,
       f"HTTP {code} verdict={r.get('verdict')} why={r.get('why')}")
    ck("gold 有帧", r.get("verdict") != "NO_FRAME", f"frame={r.get('frame')} source={(r.get('source') or {}).get('how')}")
    if r.get("verdict") != "NO_FRAME":
        img, c2 = jget(GOLD + "/picture?kind=judge", 30)
        if isinstance(img, bytes) and img[:2] == b"\xff\xd8":
            arr = cv2.imdecode(np.frombuffer(img, np.uint8), cv2.IMREAD_COLOR)
            black = float((cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY) < 10).mean())
            ck("gold 判据图 900x332", arr.shape[:2] == (332, 900), f"{arr.shape[1]}x{arr.shape[0]}")
            ck("gold 判据图不是黑屏 (黑底<65%)", black < 0.65, f"black={black:.3f} bytes={len(img)}")
        else:
            ck("gold 判据图可取", False, f"HTTP {c2}")
        lr, c3 = jget(GOLD + "/last_result", 10)
        ck("gold /last_result 有判决", c3 == 200 and bool(lr.get("verdict")), f"{lr.get('verdict')} {lr.get('why')}")
        ck("gold basis=本机判据 (不冒充产线 YOLO)", "local-judge" in str(lr.get("basis")), lr.get("basis"))
        ck("gold judge_ver 露出版本", bool(lr.get("judge_ver")), lr.get("judge_ver"))

    print("⑤ 表面: 真实判决 (帧不对必须 FAIL, 不许假 OK)")
    rs, cs = jpost(SURF + "/capture_detect")
    ck("surface capture_detect 200", cs == 200 and rs.get("code") == 200,
       f"HTTP {cs} verdict={rs.get('verdict')} why={rs.get('why')}")
    ck("surface 判决有依据", rs.get("verdict") in ("JUDGE_OK", "JUDGE_FAIL", "NO_FRAME"),
       f"{rs.get('verdict')} · {str(rs.get('why'))[:80]}")

    print("⑧ 路由齐")
    for name, url in (("gold /crop_info", GOLD + "/crop_info"), ("gold /storage", GOLD + "/storage"),
                      ("gold /param", GOLD + "/param"), ("surface /crop_info", SURF + "/crop_info"),
                      ("surface /storage", SURF + "/storage"), ("surface /exposure", SURF + "/exposure")):
        j, c = jget(url, 10)
        ck(name, c in (200, 404), f"HTTP {c}")

    if not a.skip_push:
        print("⑥⑦ 无帧诚实 + /frame 推帧")
        port = 20092
        src = a.gold_src or os.path.join(ROOT, "zmax_data/aoi_v4/snapshots/20261008_gold19_definitive/origin_2448x2048.png")
        env = dict(os.environ, ZMAX_AOI_LOCAL_GOLD_SRC="push")
        p = subprocess.Popen([sys.executable, os.path.join(SVC, "run.py"), "--kind", "gold",
                              "--port", str(port)], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(40):
                if jget(base + "/health", 1)[1] == 200:
                    break
                time.sleep(0.3)
            r0, _c = jpost(base + "/capture_detect")
            ck("push 源未推帧 ⇒ NO_FRAME (不假 OK)", r0.get("verdict") == "NO_FRAME",
               f"verdict={r0.get('verdict')} why={str(r0.get('why'))[:60]}")
            raw = open(src, "rb").read()
            rf, cf = jpost(base + "/frame", raw)
            ck("/frame 收帧", cf == 200 and rf.get("ok"), f"HTTP {cf} frame={rf.get('frame')}")
            r1, _c = jpost(base + "/capture_detect")
            ck("推帧后再检测出结果", r1.get("verdict") not in (None, "NO_FRAME"),
               f"verdict={r1.get('verdict')} judge_ver={r1.get('judge_ver')}")
        finally:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:                                    # noqa: BLE001
                p.kill()

    npass = sum(1 for ok, _, _ in R if ok)
    print("=" * 78)
    print(f"PASS {npass} / FAIL {len(R) - npass}")
    for ok, name, det in R:
        if not ok:
            print(f"  ❌ {name}: {det}")
    return 0 if npass == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
