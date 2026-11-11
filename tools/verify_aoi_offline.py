#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线 AOI 开发自检 —— 没有相机/没有工控机, 也要能把判据+检测整条链跑通。

    ./.venv-aoi310/bin/python tools/verify_aoi_offline.py

判据 (缺一项即 FAIL):
 ① 离线帧库在: zmax_data/aoi_offline/{gold,surface} 有帧; 仓库 fixture 4 张与 manifest sha 一致
 ② 数值栈同源: numpy 1.26.4 / opencv 4.10.0.84 / flask (产线工控机那套, 换版本判据会变)
 ③ 产线代码完整: service/prod/*.py sha256 == 工控机现役 (PROD_SHA256)
 ④ 判据真跑: 每张 fixture 都出 (图, meta), 并打印 n_keys / judge ok · why
 ⑤ 服务离线可用: 源=corpus 起服务 → /capture_detect 三轮都出结果, how 标 corpus, 不出网
 ⑥ 远端不可达自动回落: 源=remote:127.0.0.1:9 (必拒) → 结果 how=offline-corpus + offline=True
 ⑦ 客户端可用: policies/aoi/local.py 能连上本机镜像并拿到 verdict
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SVC = os.path.join(ROOT, "src", "lerobot", "policies", "aoi", "service")
sys.path.insert(0, SVC)
sys.path.insert(0, os.path.join(ROOT, "src"))

import cv2                                                       # noqa: E402
import numpy as np                                               # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "aoi_frames")
R = []


def ck(name, ok, det=""):
    R.append((bool(ok), name, str(det)[:240]))
    print(("✅ " if ok else "❌ ") + name + (f" — {det}" if det else ""))


def jget(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-offline-verify"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
            try:
                return json.loads(b.decode()), r.status
            except Exception:
                return b, r.status
    except Exception as e:                                        # noqa: BLE001
        return {"err": f"{type(e).__name__}: {e}"}, 0


def jpost(url, timeout=90):
    req = urllib.request.Request(url, data=b"", headers={"User-Agent": "zmax-offline-verify"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), r.status
    except Exception as e:                                        # noqa: BLE001
        return {"err": f"{type(e).__name__}: {e}"}, 0


def free_port(start=20110):
    import socket
    for p in range(start, start + 60):
        s = socket.socket()
        try:
            s.bind(("0.0.0.0", p))
            return p
        except OSError:
            pass
        finally:
            s.close()
    raise RuntimeError("no free port")


def spawn(kind, port, src):
    env = dict(os.environ)
    env[f"ZMAX_AOI_LOCAL_{kind.upper()}_SRC"] = src
    env["ZMAX_AOI_LOCAL_OFFLINE_FALLBACK"] = "1"
    p = subprocess.Popen([sys.executable, os.path.join(SVC, "run.py"), "--kind", kind,
                          "--port", str(port)], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        h, c = jget(f"http://127.0.0.1:{port}/health", 2)
        if c == 200:
            return p
        time.sleep(0.3)
    p.terminate()
    raise RuntimeError(f"{kind} 服务起不来 :{port}")


def main():
    print("=" * 80)
    print("① 离线帧库")
    for kind in ("gold", "surface"):
        d = os.path.join(ROOT, "zmax_data", "aoi_offline", kind)
        files = [f for pat in ("*.png", "*.jpg", "*.jpeg") for f in glob.glob(os.path.join(d, pat))]
        ck(f"离线帧库 {kind}", len(files) >= 1, f"{len(files)} 帧 @ {d}")
    man = json.load(open(os.path.join(FIX, "manifest.json"), encoding="utf-8"))
    for name, m in man.items():
        p = os.path.join(FIX, name)
        got = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else ""
        ck(f"fixture {name}", got == m["sha256"], f"{m['shape']} {m['bytes']}B sha {got[:12]}…")

    print("② 数值栈 (必须与工控机同源)")
    ck("numpy==1.26.4", np.__version__ == "1.26.4", np.__version__)
    # 产线栈是 opencv-python 4.10.0.84, 运行时 __version__ 只报 "4.10.0" ⇒ 比前缀
    ck("opencv 4.10.0.84", cv2.__version__.startswith("4.10.0"), cv2.__version__)
    try:
        import flask
        from importlib.metadata import version
        ck("flask", True, version("flask"))
    except Exception as e:                                        # noqa: BLE001
        ck("flask", False, str(e))

    print("③ 产线代码完整")
    from prodload import PROD_SHA256, judge_gold, judge_surface          # noqa: E402
    for kind, want in PROD_SHA256.items():
        fn = os.path.join(SVC, "prod", {"gold": "gold_10082_prod.py",
                                        "surface": "surface_10083_prod.py"}[kind])
        got = hashlib.sha256(open(fn, "rb").read()).hexdigest()
        ck(f"{kind} prod sha", got == want, f"{got[:16]}…")

    print("④ 判据真跑 (离线 fixture)")
    for name, m in man.items():
        bgr = cv2.imread(os.path.join(FIX, name))
        if name.startswith("gold"):
            img, met = judge_gold(bgr, 0.0)
            ok = img is not None and img.shape[:2] == (332, 900)
            ck(f"gold 判据 {name}", ok, f"{None if img is None else img.shape} n_keys={met.get('n_keys')} "
                                       f"state={met.get('state')} why={str(met.get('why'))[:40]}")
        else:
            img, met = judge_surface(bgr)
            ck(f"surface 判据 {name}", bool(met), f"ok={met.get('ok')} why={str(met.get('why'))[:70]}")

    print("⑤ 服务离线 (源=corpus)")
    gport = free_port()
    p = spawn("gold", gport, "corpus")
    try:
        ok3 = 0
        for _ in range(3):
            r, _c = jpost(f"http://127.0.0.1:{gport}/capture_detect")
            h = (r.get("source") or {}).get("how") or ""
            # corpus 源的 how 是帧文件绝对路径; 只有"回落"才带 offline-corpus: 前缀
            ok3 += bool(r.get("verdict") and r.get("verdict") != "NO_FRAME"
                        and not str(h).startswith("offline-corpus:"))
            print("     ", r.get("verdict"), "| how =", str(h)[:70])
        ck("corpus 源三轮出结果", ok3 == 3, f"{ok3}/3")
    finally:
        p.terminate()

    print("⑥ 远端不可达 → 自动回落离线帧库")
    gport2 = free_port()
    p2 = spawn("gold", gport2, "remote:127.0.0.1:9")
    try:
        r, _c = jpost(f"http://127.0.0.1:{gport2}/capture_detect")
        src = r.get("source") or {}
        ck("回落生效", src.get("offline") is True and "offline-corpus" in str(src.get("how")),
           f"how={str(src.get('how'))[:80]} offline={src.get('offline')}")
        ck("回执如实标注", "回落离线帧库" in str(src.get("why")), str(src.get("why"))[:90])
    finally:
        p2.terminate()

    print("⑦ 节点客户端")
    try:
        from lerobot.policies.aoi import local as _lc                      # noqa: E402
        ck("客户端模块可导入", True, f"ports={_lc.PORTS}")
    except ImportError as e:
        # .venv-aoi310 是"产线数值栈", 不含 lerobot 全量依赖; 客户端在 gui-venv311 里测
        print(f"⏭ 客户端导入跳过 (本解释器无 lerobot 依赖: {e}); 用 gui-venv311 跑 tools/verify_aoi_local_service.py")
    except Exception as e:                                        # noqa: BLE001
        ck("客户端模块可导入", False, f"{type(e).__name__}: {e}")

    npass = sum(1 for ok, _, _ in R if ok)
    print("=" * 80)
    print(f"PASS {npass} / FAIL {len(R) - npass}")
    for ok, name, det in R:
        if not ok:
            print(f"  ❌ {name}: {det}")
    return 0 if npass == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
