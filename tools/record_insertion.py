#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_insertion.py — 把"这一刻"的插入状态落成一条不可抵赖的记录 (只读)

写:
  zmax_data/evidence/insertion_<时间>.json   位姿/力/状态机/实时检测框/各帧来源与帧龄
  zmax_data/evidence/insertion_<时间>_arm.jpg  臂相机原帧 (同一刻)
  zmax_data/evidence/insertion_<时间>_rs.jpg   D435 原帧 (同一刻)
并 append 到 zmax_data/evidence/insertion_index.jsonl (一条一行, 便于以后回看)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

REPO = "/home/ubuntu/zmax"
OUT = os.path.join(REPO, "zmax_data", "evidence")


def j(url, timeout=8):
    try:
        return json.loads(urllib.request.urlopen(url, timeout=timeout).read().decode())
    except Exception as e:                                                    # noqa: BLE001
        return {"_err": "%s: %s" % (type(e).__name__, str(e)[:80])}


def fb(url, timeout=8):
    try:
        return urllib.request.urlopen(url, timeout=timeout).read()
    except Exception:                                                         # noqa: BLE001
        return b""


def jfile(p):
    try:
        return json.load(open(p), )
    except Exception as e:                                                    # noqa: BLE001
        return {"_err": "%s: %s" % (type(e).__name__, str(e)[:80])}


def main(note=""):
    os.makedirs(OUT, exist_ok=True)
    t = time.time()
    tag = time.strftime("%Y%m%d_%H%M%S", time.localtime(t))

    tcp = jfile(REPO + "/zmax_data/rokae_sdk/tcp_out/latest.json")
    ft = jfile(REPO + "/zmax_data/rokae_sdk/ft_out/latest.json")
    st = j("http://127.0.0.1:8797/api/robot_state")
    m3 = j("http://127.0.0.1:8797/api/module3d")
    cams = (j("http://127.0.0.1:8797/api/cams") or {}).get("cams") or {}

    rec = {
        "note": note,
        "ts": t,
        "time": time.strftime("%F %T", time.localtime(t)),
        "tcp_m": {k: tcp.get(k) for k in ("x", "y", "z", "a", "b", "c")},
        "tcp_age_s": round(t - float(tcp.get("ts") or 0), 2) if tcp.get("ts") else None,
        "force": {k: ft.get(k) for k in ("fx", "fy", "fz", "tx", "ty", "tz", "power", "mode", "op")},
        "force_axial_N": ft.get("fx"),
        "force_lateral_N": round((float(ft.get("fy") or 0) ** 2 + float(ft.get("fz") or 0) ** 2) ** 0.5, 2),
        "force_age_s": round(t - float(ft.get("ts") or 0), 2) if ft.get("ts") else None,
        "robot_state": {k: st.get(k) for k in ("code", "text", "stage", "inserting", "moving", "alarms")},
        "module3d": {k: m3.get(k) for k in ("ok", "locked", "box2d", "dims_mm", "dist_mm", "live")},
        "cams": {k: {x: (cams.get(k) or {}).get(x) for x in ("online", "age_s", "fps", "stalled")}
                 for k in ("arm", "rs", "local")},
    }
    pj = os.path.join(OUT, "insertion_%s.json" % tag)
    with open(pj, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)

    # 同一刻原帧 (证明"看到的就是记下的")
    for name, url in (("arm", "http://127.0.0.1:8797/snap/arm.jpg"),
                      ("rs", "http://127.0.0.1:8797/snap/rs.jpg")):
        b = fb(url)
        if b:
            with open(os.path.join(OUT, "insertion_%s_%s.jpg" % (tag, name)), "wb") as f:
                f.write(b)
    with open(os.path.join(OUT, "insertion_index.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": t, "time": rec["time"], "file": os.path.basename(pj),
                            "tcp_m": rec["tcp_m"], "axial_N": rec["force_axial_N"],
                            "lateral_N": rec["force_lateral_N"],
                            "stage": (rec["robot_state"] or {}).get("stage"),
                            "inserting": (rec["robot_state"] or {}).get("inserting"),
                            "note": note}, ensure_ascii=False) + "\n")
    print(json.dumps({k: rec[k] for k in ("time", "tcp_m", "force_axial_N", "force_lateral_N",
                                          "tcp_age_s", "force_age_s", "module3d")},
                     ensure_ascii=False, indent=2))
    print("落盘:", pj)
    return pj


if __name__ == "__main__":
    import sys
    main(" ".join(sys.argv[1:]) or "插入记录")
