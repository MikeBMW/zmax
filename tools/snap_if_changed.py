#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📸 只发变化的帧（2026-10-26 老倪: 「现在是 wifi 环境, 发图片之前看看是不是相同帧, 相同帧就不要发了」）

背景: WiFi 带宽有限, 而相机链路出问题时 HTTP 端会反复吐**同一张缓存图**(实测臂相机连抓 5 次
      md5 全同, 30524B)。这种图发出去既浪费带宽、又会把"冻结"误当成"现场就是这样"。

规则: 取一帧 → 与**上次成功发出的那一帧**比 md5
      · 不同  → 存盘并打印 `SEND <path>`（可以发）
      · 相同  → 打印 `SAME <path> age=<n>s`（不发, 只说"还是同一张"）
      计数落在 zmax_data/runtime/last_snap.json, 跨进程可续。

用法:
  ./gui-venv311/bin/python tools/snap_if_changed.py --cam arm
  ./gui-venv311/bin/python tools/snap_if_changed.py --cam all
  # 想看强制样本(排障用), 加 --force
"""
import argparse
import hashlib
import json
import os
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(REPO, "zmax_data", "runtime", "last_snap.json")
OUTDIR = os.path.join(REPO, "zmax_data", "runtime", "snaps")

CAMS = {
    "arm":     "http://127.0.0.1:8791/snapshot/arm.jpg",       # 机器人臂上 D405 (Orin)
    "local":   "http://127.0.0.1:8791/snapshot/local.jpg",     # 本机 USB 相机
    "central": "http://127.0.0.1:8791/snapshot/local2.jpg",    # 550C 中央相机
}


def _load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                 # noqa: BLE001
        return {}


def _save(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def grab(name, force=False, timeout=8.0):
    url = CAMS[name]
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            b = r.read()
    except Exception as e:                                            # noqa: BLE001
        return "ERR %-8s 取帧失败: %s" % (name, type(e).__name__)

    if not b:
        return "ERR %-8s 空帧" % name

    md5 = hashlib.md5(b).hexdigest()
    st = _load()
    prev = st.get(name) or {}
    same = (prev.get("md5") == md5) and not force

    if same:
        # 同一张: 不覆盖"上次发出"的记录, 只累加 skip 计数, 用来说明"是它没变, 不是我没抓"
        prev["skips"] = int(prev.get("skips") or 0) + 1
        prev["last_seen_ts"] = time.time()
        st[name] = prev
        _save(st)
        age = time.time() - float(prev.get("sent_ts") or time.time())
        return "SAME %-8s 与上次发出的同一张 (已 %ds, 累计跳过 %d 次) · md5 %s" % (
            name, int(age), prev["skips"], md5[:10])

    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, "%s_%s.jpg" % (name, time.strftime("%H%M%S")))
    with open(path, "wb") as f:
        f.write(b)
    st[name] = {"md5": md5, "sent_ts": time.time(), "path": path,
                "bytes": len(b), "skips": 0}
    _save(st)
    return "SEND %-8s %s · %dB · md5 %s" % (name, path, len(b), md5[:10])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="all", choices=list(CAMS) + ["all"])
    ap.add_argument("--force", action="store_true", help="忽略去重, 强制存图(排障用)")
    a = ap.parse_args()
    names = list(CAMS) if a.cam == "all" else [a.cam]
    rc = 0
    for n in names:
        line = grab(n, force=a.force)
        print(line, flush=True)
        if line.startswith("ERR"):
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
