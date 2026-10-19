#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""侧面检测 10083 旁路调试工具 (2026-10-20, 老倪「以后可以旁路调试侧面检测 10083 服务」)

为什么要有它: 现场排查侧面判据问题时, 走 8791/8793 那条链路会被 worker 的 0.25Hz 取图、
deglare、帧槽缓存层层包住, 看到的不是工控机原始输出。本工具**绕过**整条链路, 直接对
192.168.23.23:10083 说话, 只做四种事:

    status            版本 / 曝光 / 相机 / 判据阈值模式 (只读)
    setexpo US        改曝光档 (带 settle: 改完丢掉一帧, 治「紧跟的第一抓必 500」)
    snap              抓一张 origin 原图存盘 (500 自动重试, 间隔 ≥10s, 绝不连抓)
    judge             抓帧 → 本机 aoi_surface_rect 判据 → 与工控机内置 judge 并排对比
    watch             每 N 秒抓一帧存盘 + 打印指标 (默认 10s, 别低于 10)

实测坑(已内建, 别自己改回):
  · GET /picture?kind=origin&grab=1 冷启/被抢时回 500「图像抓取失败」(46B),
    重试第 2 次几乎必成; 但**连续**抓三次会把相机句柄打坏, 必须靠 KeepAlive 约 75s 拉起。
    ⇒ 本工具每次 grab 之间强制 sleep ≥10s, 最多重试 3 次。
  · POST /exposure 在相机未开时回 ok=False「参数已记住, 首次取帧初始化相机时生效」——
    这不是失败, 抓一帧之后即生效; 本工具会如实分两行报出。
  · 曝光定档: 5000us 是当前正确档 (commit a8013ce: 48000 下 Otsu 前景 1.000 搜不到)。
    改变它之前先想清楚, 判据图没了多半就是这一项。

用法:
    python3 tools/aoi_surface_bypass.py status
    python3 tools/aoi_surface_bypass.py setexpo 5000
    python3 tools/aoi_surface_bypass.py snap --out /tmp/s.jpg
    python3 tools/aoi_surface_bypass.py judge
    python3 tools/aoi_surface_bypass.py watch --seconds 60 --interval 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HOST = os.environ.get("ZMAX_AOI_SURFACE_HOST", "192.168.23.23")
PORT = int(os.environ.get("ZMAX_AOI_SURFACE_PORT", "10083"))
BASE = "http://%s:%d" % (HOST, PORT)
GRAB_GAP_S = float(os.environ.get("ZMAX_AOI_GRAB_GAP_S", "10"))   # 两个 grab 之间至少隔这么久
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get(path: str, timeout: float = 10.0) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.getcode(), r.read()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() if hasattr(e, "read") else b"")
    except Exception as e:                                             # noqa: BLE001
        return 0, str(e).encode()


def _post(path: str, timeout: float = 15.0) -> tuple[int, bytes]:
    req = urllib.request.Request(BASE + path, method="POST", data=b"")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.getcode(), r.read()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() if hasattr(e, "read") else b"")
    except Exception as e:                                             # noqa: BLE001
        return 0, str(e).encode()


def _json(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode("utf-8", "ignore"))
    except Exception:                                                  # noqa: BLE001
        return {}


def cmd_status(_a) -> int:
    code, raw = _get("/exposure")
    d = _json(raw)
    print("接口            http=%s" % code)
    print("版本            %s" % d.get("version", "?"))
    print("曝光(运行时)    us=%s gain=%s" % (d.get("us"), d.get("gain")))
    print("曝光(程序默认)  us=%s gain=%s" % ((d.get("default") or {}).get("us"), (d.get("default") or {}).get("gain")))
    print("相机打开        %s" % d.get("cam_open"))
    last = d.get("last") or {}
    if last:
        print("上次改档        ok=%s us_ok=%s reason=%s" % (last.get("ok"), last.get("us_ok"),
                                                        (last.get("reason") or "-")[:70]))
    c2, r2 = _get("/storage")
    s = _json(r2)
    print("存储            http=%s files_total=%s dir=%s" % (c2, s.get("files_total"), s.get("dir")))
    c3, r3 = _get("/crop_info")
    j = (_json(r3).get("judge") or {})
    if j:
        print("判据阈值模式    th_mode=%s th_bar=%s th_mod=%s bg_lvl=%s" % (
            j.get("th_mode"), j.get("th_bar"), j.get("th_mod"), j.get("bg_lvl")))
        print("判据结果        ok=%s why=%s" % (j.get("ok"), (j.get("why") or "-")[:70]))
    return 0


def cmd_setexpo(a) -> int:
    us = int(a.us)
    code, raw = _post("/exposure?us=%d&gain=%.1f" % (us, a.gain))
    d = _json(raw)
    print("POST /exposure?us=%d&gain=%.1f → http=%s" % (us, a.gain, code))
    print("  回执 ok=%s us_ok=%s cam_open=%s us=%s" % (d.get("ok"), d.get("us_ok"),
                                                   d.get("cam_open"), d.get("us")))
    if not d.get("ok"):
        print("  reason: %s" % (d.get("reason") or "-"))
        print("  ⇒ 参数已记住, 抓一帧即生效 (下面自动做)")
        jpg, msg = grab_origin(attempts=3)
        if jpg is None:
            print("  抓帧失败: %s" % msg)
            return 2
        print("  抓帧 ok (%d B) ⇒ 生效" % len(jpg))
    c2, r2 = _get("/exposure")
    print("  回读 us=%s gain=%s" % (_json(r2).get("us"), _json(r2).get("gain")))
    return 0


_last_grab_t = 0.0


def grab_origin(attempts: int = 3, timeout: float = 25.0):
    """抓一张 origin。500 就隔 GRAB_GAP_S 重试; 两次 grab 之间也强制隔开(不连抓)。"""
    global _last_grab_t
    err = ""
    for i in range(1, attempts + 1):
        gap = GRAB_GAP_S - (time.time() - _last_grab_t)
        if _last_grab_t and gap > 0:
            time.sleep(gap)
        code, raw = _get("/picture?kind=origin&grab=1", timeout=timeout)
        _last_grab_t = time.time()
        if code == 200 and len(raw) > 50000:
            return raw, "第%d次 ok %dB" % (i, len(raw))
        err = "第%d次 http=%s %dB %s" % (i, code, len(raw), raw[:60].decode("utf-8", "ignore"))
    return None, err


def cmd_snap(a) -> int:
    raw, msg = grab_origin(attempts=a.attempts)
    if raw is None:
        print("❌ 抓帧失败: %s" % msg)
        print("   ⇒ 冷启/被抢: 隔 10s 再试; 三次全 500 就等 KeepAlive(约75s) 拉起, 别手搓第二份")
        return 2
    out = a.out or "/tmp/aoi_surface_origin.jpg"
    with open(out, "wb") as f:
        f.write(raw)
    print("✅ %s (%d B) · %s" % (out, len(raw), msg))
    return 0


def cmd_judge(a) -> int:
    raw, msg = grab_origin(attempts=a.attempts)
    if raw is None:
        print("❌ 抓帧失败: %s" % msg)
        return 2
    path = a.out or "/tmp/aoi_surface_judge_probe.jpg"
    with open(path, "wb") as f:
        f.write(raw)
    import cv2
    import numpy as np
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import aoi_surface_rect as R
    im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    print("原图            %dx%d mean=%.1f p50=%d p99=%d 饱和(>=250)=%.2f%%" % (
        im.shape[1], im.shape[0], g.mean(), np.median(g), np.percentile(g, 99), 100 * (g >= 250).mean()))
    crop, ov, meta = R.surface_judge(im, out_long=a.out_long, return_overlay=True)
    if crop is None:
        print("本机判据        ❌ None · fg_frac=%s p99=%s" % (meta.get("fg_frac"), meta.get("p99")))
        print("                why=%s" % str(meta.get("why"))[:110])
    else:
        cg = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        print("本机判据        ✅ %dx%d 倾角=%.2f° 长宽比=%.2f fill=%.3f no_stretch=%s" % (
            crop.shape[1], crop.shape[0], meta.get("angle", 0), meta.get("aspect", 0),
            meta.get("fill", 0), meta.get("no_stretch")))
        print("                mean=%.1f 饱和=%.2f%% expand_px=%s" % (
            cg.mean(), 100 * (cg >= 250).mean(), meta.get("expand_px")))
        jp = path.replace(".jpg", "_judge.jpg")
        cv2.imwrite(jp, crop)
        print("                摆正图 → %s" % jp)
        if ov is not None:
            op = path.replace(".jpg", "_overlay.jpg")
            cv2.imwrite(op, ov)
            print("                整板图 → %s" % op)
    c3, r3 = _get("/crop_info")
    j = (_json(r3).get("judge") or {})
    print("工控机判据      ok=%s th_mode=%s th_bar=%s th_mod=%s" % (
        j.get("ok"), j.get("th_mode"), j.get("th_bar"), j.get("th_mod")))
    print("                why=%s" % str(j.get("why") or "-")[:110])
    if crop is not None and not j.get("ok"):
        print("⚠ 两套判据口径不一致: 本机检出、工控机未过 —— 先确认工件是否摆到观察位, 再谈阈值")
    return 0


def cmd_watch(a) -> int:
    t0 = time.time()
    n = 0
    while True:
        n += 1
        raw, msg = grab_origin(attempts=1)
        if raw is None:
            print("[%5.0fs] ❌ %s" % (time.time() - t0, msg))
        else:
            import cv2
            import numpy as np
            im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if im is None:
                print("[%5.0fs] ⚠ 帧解不出 (%dB)" % (time.time() - t0, len(raw)))
                if a.seconds and time.time() - t0 >= a.seconds:
                    break
                time.sleep(max(GRAB_GAP_S, a.interval))
                continue
            g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
            out = os.path.join(a.outdir, "probe_%02d.jpg" % n)
            os.makedirs(a.outdir, exist_ok=True)
            with open(out, "wb") as f:
                f.write(raw)
            print("[%5.0fs] ✅ mean=%.1f p99=%d 饱和=%.2f%% → %s" % (
                time.time() - t0, g.mean(), np.percentile(g, 99), 100 * (g >= 250).mean(), out))
        if a.seconds and time.time() - t0 >= a.seconds:
            break
        time.sleep(max(GRAB_GAP_S, a.interval))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="侧面检测 10083 旁路调试 (绕过 8791/8793 链路, 直连工控机)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="版本/曝光/相机/判据阈值模式 (只读)")

    p = sub.add_parser("setexpo", help="改曝光档 (带 settle)")
    p.add_argument("us", type=int)
    p.add_argument("--gain", type=float, default=1.8)

    p = sub.add_parser("snap", help="抓一张 origin 原图")
    p.add_argument("--out", default="")
    p.add_argument("--attempts", type=int, default=3)

    p = sub.add_parser("judge", help="抓帧 + 本机判据 + 与工控机判据对比")
    p.add_argument("--out", default="")
    p.add_argument("--out-long", type=int, default=1400)
    p.add_argument("--attempts", type=int, default=3)

    p = sub.add_parser("watch", help="循环抓帧观测 (间隔 ≥10s)")
    p.add_argument("--seconds", type=float, default=60)
    p.add_argument("--interval", type=float, default=10)
    p.add_argument("--outdir", default="/tmp/aoi_surface_watch")

    a = ap.parse_args()
    return {"status": cmd_status, "setexpo": cmd_setexpo, "snap": cmd_snap,
            "judge": cmd_judge, "watch": cmd_watch}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
