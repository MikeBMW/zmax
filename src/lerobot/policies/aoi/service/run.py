# -*- coding: utf-8 -*-
"""命令行入口: 起本机 AOI 镜像服务。

    python src/lerobot/policies/aoi/service/run.py --kind gold    --port 20082
    python src/lerobot/policies/aoi/service/run.py --kind surface --port 20083
    # 一次起两路
    python src/lerobot/policies/aoi/service/run.py --both

解释器: 必须用装了 numpy1.26.4/opencv4.10.0.84/flask 的那个 (工控机数值栈),
        本仓库为它建了 `.venv-aoi310`:
        uv pip install --python .venv-aoi310/bin/python numpy==1.26.4 opencv-python==4.10.0.84 flask
"""
from __future__ import annotations

import argparse
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["gold", "surface"])
    ap.add_argument("--port", type=int)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--both", action="store_true", help="同时起 20082(金手指) + 20083(表面)")
    a = ap.parse_args()
    import app as appmod
    if a.both:
        jobs = [(("gold"), 20082), (("surface"), 20083)]
        for k, p in jobs[1:]:
            threading.Thread(target=appmod.run, args=(k, p, a.host), daemon=True).start()
        appmod.run("gold", 20082, a.host)
        return
    if not a.kind or not a.port:
        ap.error("需要 --kind 与 --port (或用 --both)")
    appmod.run(a.kind, a.port, a.host)


if __name__ == "__main__":
    main()
