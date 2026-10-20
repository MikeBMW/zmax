#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_rs_camera.py — USB RealSense D435 判据 (真取帧 · 真看像素 · 真独占)

判据(全过才 PASS, 任一 FAIL 直接非零退出):
  J1 独占: /dev/video* 里只有 **一个** 进程持有 D435 的节点(都在 8789 那个进程里)
  J2 小服务出帧: /health n 增长, age_s < 1.0
  J3 帧是新的: 间隔 1.2s 两张 /snap.jpg, 字节都 > 20KB 且 md5 不同 (不是冻帧)
  J4 像素不黑: 640x480, mean > 30, 暗(<8) 占比 < 50%
  J5 经 AR 服务仍通: 8797/snap/rs.jpg 200 且 > 20KB; /api/rs_info ok=true frames>0 age<2
  J6 /api/cams 的 rs online=true (页面顶栏帧龄才有数)

用法: ./gui-venv311/bin/python tools/verify_rs_camera.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

RS = "http://127.0.0.1:8789"
AR = "http://127.0.0.1:8797"
FIVE_STAR = "Intel(R) RealSense"


def get(url, timeout=12):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def jget(url, timeout=12):
    return json.loads(get(url, timeout).decode("utf-8"))


def holders():
    """谁开着 D435 的 UVC 节点(按 /proc/*/fd 反查, 不信 ps 名字)。"""
    try:
        nodes = set()
        for n in os.listdir("/dev"):
            if not n.startswith("video"):
                continue
            p = "/dev/" + n
            try:
                with open("/sys/class/video4linux/%s/name" % n) as f:
                    if FIVE_STAR in f.read():
                        nodes.add(p)
            except OSError:
                pass
        out = {}
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                for fd in os.listdir("/proc/%s/fd" % pid):
                    try:
                        t = os.readlink("/proc/%s/fd/%s" % (pid, fd))
                    except OSError:
                        continue
                    if t in nodes:
                        try:
                            with open("/proc/%s/cmdline" % pid, "rb") as f:
                                cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace")[:110]
                        except OSError:
                            cmd = "?"
                        out.setdefault(pid, (cmd, set()))[1].add(t)
            except OSError:
                continue
        return out
    except Exception:                                                      # noqa: BLE001
        return {}


def main():
    res = []

    def chk(name, ok, detail):
        res.append((name, bool(ok), detail))
        print(("PASS " if ok else "FAIL ") + name + " · " + detail, flush=True)

    # J1 独占
    h = holders()
    procs = [(p, c) for p, (c, _n) in h.items()]
    ok1 = len(procs) == 1 and "rs_service.py" in procs[0][1]
    chk("J1 独占(单进程持有 D435)", ok1,
        "持有者=%s" % (["%s:%s" % (p, c.split("/")[-1]) for p, c in procs] or "无"))

    # J2 出帧
    try:
        a = jget(RS + "/health")
        time.sleep(1.5)
        b = jget(RS + "/health")
        ok2 = b.get("ok") and (b.get("n") or 0) > (a.get("n") or 0) and (b.get("age_s") or 9) < 1.0
        chk("J2 小服务出帧", ok2, "n %s→%s · age %ss" % (a.get("n"), b.get("n"), b.get("age_s")))
    except Exception as e:                                                 # noqa: BLE001
        chk("J2 小服务出帧", False, "%s: %s" % (type(e).__name__, str(e)[:90]))

    # J3 新帧
    try:
        j1 = get(RS + "/snap.jpg")
        time.sleep(1.2)
        j2 = get(RS + "/snap.jpg")
        ok3 = len(j1) > 20000 and len(j2) > 20000 and hashlib.md5(j1).hexdigest() != hashlib.md5(j2).hexdigest()
        chk("J3 帧是新的(非冻帧)", ok3,
            "%d B / %d B · md5 %s… ≠ %s…" % (len(j1), len(j2),
                                              hashlib.md5(j1).hexdigest()[:6], hashlib.md5(j2).hexdigest()[:6]))
    except Exception as e:                                                 # noqa: BLE001
        chk("J3 帧是新的(非冻帧)", False, "%s: %s" % (type(e).__name__, str(e)[:90]))
        j1 = None

    # J4 像素
    try:
        from PIL import Image
        import numpy as np
        a = np.asarray(Image.open(io.BytesIO(j1)).convert("L")).astype("float32")
        mean, dark = float(a.mean()), float((a < 8).mean() * 100)
        ok4 = a.shape[:2] == (480, 640) and mean > 30 and dark < 50
        chk("J4 像素不黑", ok4, "%dx%d · mean=%.1f · 暗=%.1f%%" % (a.shape[1], a.shape[0], mean, dark))
    except Exception as e:                                                 # noqa: BLE001
        chk("J4 像素不黑", False, "%s: %s" % (type(e).__name__, str(e)[:90]))

    # J5 经 AR 服务
    try:
        b = get(AR + "/snap/rs.jpg", 20)
        i = jget(AR + "/api/rs_info", 20)
        ok5 = len(b) > 20000 and i.get("ok") and (i.get("frames") or 0) > 0 and (i.get("age_s") or 9) < 2
        chk("J5 AR 服务代理可用", ok5,
            "%d B · frames=%s · age=%ss · depth_valid=%s" % (len(b), i.get("frames"), i.get("age_s"),
                                                             (i.get("depth") or {}).get("valid_ratio")))
    except Exception as e:                                                 # noqa: BLE001
        chk("J5 AR 服务代理可用", False, "%s: %s" % (type(e).__name__, str(e)[:90]))

    # J6 /api/cams
    try:
        c = jget(AR + "/api/cams", 20)["cams"]["rs"]
        ok6 = bool(c.get("online")) and (c.get("age_s") is None or c["age_s"] < 3)
        chk("J6 /api/cams rs 在线", ok6, "online=%s age=%ss" % (c.get("online"), c.get("age_s")))
    except Exception as e:                                                 # noqa: BLE001
        chk("J6 /api/cams rs 在线", False, "%s: %s" % (type(e).__name__, str(e)[:90]))

    bad = [n for n, ok, _ in res if not ok]
    print("\n%d/%d PASS" % (len(res) - len(bad), len(res)) + (" · FAIL: " + ", ".join(bad) if bad else ""))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
