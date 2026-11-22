#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tool_load_probe.py — 只读: 读控制器工程里的工具/工件负载 (RT 会话里没设 load 会让腕关节硬扛)
用法: bash tools/rokae_sdk_run.sh --script tool_load_probe.py
"""
import json, os, socket, sys
sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect((IP, 9)); lip = s.getsockname()[0]; s.close()
r = x.xMateRobot(); r.connectToRobot(IP, lip)
ec = {}
try:
    infos = r.toolsInfo(ec)
    out = []
    for t in infos:
        d = {"name": str(getattr(t, "name", "")), "isHeld": bool(getattr(t, "isHeld", False))}
        ld = getattr(t, "load", None)
        if ld is not None:
            d["mass_kg"] = float(getattr(ld, "mass", float("nan")))
            d["cog_m"] = [round(float(v), 4) for v in list(getattr(ld, "cog", []))[:3]]
            d["inertia"] = [round(float(v), 5) for v in list(getattr(ld, "inertia", []))[:3]]
        out.append(d)
    print(json.dumps({"ec": ec, "tools": out}, ensure_ascii=False, default=str))
except Exception as e:
    print(json.dumps({"ec": ec, "exc": "%s: %s" % (type(e).__name__, e)}, ensure_ascii=False))
try:
    r.disconnectFromRobot({})
except Exception:
    pass
