#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结探针: 只复现 GUI 启动时的工程包导入链 (studio.py:258 → simulink_module → node_logic)。

用途: 本地/CI 在**真冻结包**里判定 `src/lerobot/engineering` 是否随包可达;
      失败时 rc=1 并打印与老倪现场同源的错误。
"""
import json
import os
import sys

out = {"frozen": bool(getattr(sys, "frozen", False)),
       "meipass": getattr(sys, "_MEIPASS", None),
       "sys_path_head": [p for p in sys.path[:6]]}
rc = 1
try:
    import node_logic as nl
    out["node_logic_keys"] = len(getattr(nl, "NODE_LOGIC", {}) or {})
    out["logic_home"] = os.path.basename(getattr(nl, "LOGIC_HOME", "") or "")
    out["canvas_json"] = getattr(nl, "CANVAS_JSON", "")
    out["canvas_exists"] = os.path.isfile(out["canvas_json"] or "")
    if int(out["node_logic_keys"]) < 100:
        raise RuntimeError("节点逻辑注册数 <100: 工程包没进包/不完整")
    if not out["canvas_exists"]:
        raise RuntimeError("画布真源 JSON 不在包内")
    rc = 0
except Exception as e:  # noqa: BLE001
    out["error"] = "%s: %s" % (type(e).__name__, e)
    out["cause"] = repr(getattr(e, "__cause__", None))
out["rc"] = rc
print(json.dumps(out, ensure_ascii=False, indent=1))
sys.exit(rc)
