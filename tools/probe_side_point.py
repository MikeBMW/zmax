#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_side_point.py — 单步走到某个轨迹点, 立刻请求 AOI 检测, 验证该点是否落在判据 ROI 内

用途: 表面检测(#172 侧面点0) / 金手指检测(#156) 这类"必须是精确落点"的验证。
逐个点试, 找出 module_bbox 完整落在 roi 内、module_aspect 接近 4.22/6.65 的那一个。

用法:
  python3 tools/probe_side_point.py --idx 172 --port 10083
  python3 tools/probe_side_point.py --idx 172 --port 10083 --idx2 171 --idx2 180
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request

AR = "http://127.0.0.1:8797"
HOST = "192.168.23.23"


def _get(url, t=15):
    return json.loads(urllib.request.urlopen(url, timeout=t).read().decode("utf-8", "replace"))


def _post(url, body=None, t=60):
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"} if body else {})
    return json.loads(urllib.request.urlopen(req, timeout=t).read().decode("utf-8", "replace"))


def wait_idle(max_s=90):
    """等 8797 上一段跑完"""
    t0 = time.time()
    while time.time() - t0 < max_s:
        try:
            d = _get(AR + "/api/arm/step_traj/status", 20)
            if not d.get("running"):
                return d.get("cursor")
            print("  等 8797 空闲… cursor=%s running=True" % d.get("cursor"), flush=True)
        except Exception as e:                                          # noqa: BLE001
            print("  status 超时/失败: %s" % str(e)[:60], flush=True)
        time.sleep(4)
    return None


def goto(idx):
    """走到第 idx 点 (8797 语义: start+n = 到达点)"""
    cur = wait_idle()
    if cur is None:
        print("  ✗ 8797 一直 busy, 放弃")
        return None
    print("  当前 cursor=%s → 目标 #%d" % (cur, idx), flush=True)
    if cur > idx:
        print("  ✗ 当前 %s 已越过目标 %d, 不能反向单步(会触发 jump 保护)" % (cur, idx))
        return None
    body = {"start": int(cur), "n": int(idx - cur), "speed": 20, "dwell_ms": 300}
    if body["n"] <= 0:
        print("  ✗ n<=0")
        return None
    print("  派单 %s" % json.dumps(body), flush=True)
    r = _post(AR + "/api/arm/step_traj", body)
    print("  → %s" % json.dumps(r, ensure_ascii=False)[:220], flush=True)
    if not r.get("ok"):
        return None
    st = _get(AR + "/api/arm/step_traj/status", 20)
    print("  到达 cursor=%s running=%s" % (st.get("cursor"), st.get("running")), flush=True)
    return st.get("cursor")


def detect(port):
    print("  🔫 POST /capture_detect @%d" % port, flush=True)
    t0 = time.time()
    r = _post("http://%s:%d/capture_detect" % (HOST, port), None, 120)
    print("  → %s (%.2fs)" % (json.dumps(r, ensure_ascii=False), time.time() - t0), flush=True)
    time.sleep(12)
    lr = _get("http://%s:%d/last_result" % (HOST, port), 15)
    print("  n=%s ms=%s count=%s verdict=%s judge_ok=%s"
          % (lr.get("n"), lr.get("ms"), lr.get("count"), lr.get("verdict"), lr.get("judge_ok")), flush=True)
    if lr.get("judge_why"):
        print("  judge_why = %s" % str(lr["judge_why"])[:160], flush=True)
    if lr.get("defects"):
        print("  defects = %s" % json.dumps(lr["defects"], ensure_ascii=False)[:260], flush=True)
    return lr


def crop_info(port):
    try:
        ci = _get("http://%s:%d/crop_info" % (HOST, port), 12)
        j = ci.get("judge") or {}
        if isinstance(j, dict) and j:
            print("  【判据定位】bbox_rot=%s  aspect=%s  roi=%s  ok=%s"
                  % (j.get("module_bbox_rot"), j.get("module_aspect"), j.get("roi"), j.get("ok")), flush=True)
            if j.get("right_edge_src"):
                print("    right_edge_src = %s" % j.get("right_edge_src"), flush=True)
            if j.get("why"):
                print("    why = %s" % str(j.get("why"))[:140], flush=True)
    except Exception as e:                                              # noqa: BLE001
        print("  crop_info 失败: %s" % str(e)[:60], flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idx", type=int, required=True)
    ap.add_argument("--idx2", type=int, action="append", default=[])
    ap.add_argument("--port", type=int, default=10083)
    a = ap.parse_args()
    targets = [a.idx] + list(a.idx2)
    for k, idx in enumerate(targets):
        print("\n=== 目标 #%d (端口 %d) ===" % (idx, a.port), flush=True)
        if goto(idx) is None:
            print("  跳过 #%d" % idx, flush=True)
            continue
        detect(a.port)
        crop_info(a.port)
        if k < len(targets) - 1:
            print("  等 3s…", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
