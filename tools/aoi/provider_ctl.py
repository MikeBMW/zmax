#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工控机「取图 provider」远控 (起/停/查) —— 配合本机 AOI 镜像做旁路检测。

相机线 + OPT SDK 只在工控机, 所以工控机侧只需要一个"快门": tools/aoi/cam_provider.py
在工控机上跑, 只做 抓帧 → JPEG → HTTP; 判据/检测全在 4060 (policies/aoi/service)。

    gui-venv311/bin/python tools/aoi/provider_ctl.py status --port 10083
    gui-venv311/bin/python tools/aoi/provider_ctl.py start  --port 10083 --sn D265250099 --exposure 80000 --gain 1.8
    gui-venv311/bin/python tools/aoi/provider_ctl.py stop   --port 10083

🔴 相机独占: start 前会先停掉该端口上的 AOI 程序 (同一台相机不能两份)。
   要回产线程序: 先 stop, 再按原来的方式起 cam_surface_10083_work_v20.py。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import aoi_remote_deploy as A                                        # noqa: E402

PC = "192.168.23.23"
PROVIDER = r"D:\xspace\ultralytics_AOI\cam_provider.py"
PY = r"D:\xspace\ultralytics_AOI\venv\Scripts\python.exe"
LOG = r"D:\xspace\ultralytics_AOI\provider_{port}.log"


def status(port: int) -> dict:
    try:
        req = urllib.request.Request(f"http://{PC}:{port}/health",
                                     headers={"User-Agent": "zmax-provider-ctl"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception as e:                                           # noqa: BLE001
        return {"ok": False, "port": port, "why": f"{type(e).__name__}: {e}"}


def start(port: int, sn: str, exposure: float, gain: float) -> str:
    # 🔴 不要对整段 PowerShell 用 .format(): PS 的 { } 会被当成占位符 (实测 KeyError ' $id=$c')。
    #    一律用字符串拼接。
    log = LOG.replace("{port}", str(port))
    ps = ('$c=Get-NetTCPConnection -LocalPort ' + str(port) + ' -State Listen -EA SilentlyContinue; '
          'if($c){ $id=$c.OwningProcess; Stop-Process -Id $id -Force; "stopped old pid " + $id }; '
          'Start-Sleep -Seconds 3; '
          '$sh=New-Object -ComObject WScript.Shell; '
          '$cmd="cmd /c cd /d D:\\xspace\\ultralytics_AOI && ' + PY + ' ' + PROVIDER +
          ' --port ' + str(port) + ' --sn ' + sn + ' --exposure ' + str(exposure) +
          ' --gain ' + str(gain) + ' >> ' + log + ' 2>&1"; '
          '$sh.Run($cmd,0,$false); "launched provider on ' + str(port) + '"')
    return A.remote(ps, wait=90, label="provider_start_%d" % port)


def stop(port: int) -> str:
    ps = ('$c=Get-NetTCPConnection -LocalPort ' + str(port) + ' -State Listen -EA SilentlyContinue; '
          'if($c){ $id=$c.OwningProcess; Stop-Process -Id $id -Force; "stopped pid " + $id } '
          'else { "nothing on ' + str(port) + '" }')
    return A.remote(ps, wait=60, label=f"provider_stop_{port}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["start", "stop", "status"])
    ap.add_argument("--port", type=int, default=10083)
    ap.add_argument("--sn", default="D265250099")
    ap.add_argument("--exposure", type=float, default=80000)
    ap.add_argument("--gain", type=float, default=1.8)
    a = ap.parse_args()
    if a.cmd == "status":
        print(json.dumps(status(a.port), ensure_ascii=False, indent=2))
    elif a.cmd == "stop":
        print(stop(a.port))
        print(json.dumps(status(a.port), ensure_ascii=False))
    else:
        print(start(a.port, a.sn, a.exposure, a.gain))
        for _ in range(30):
            st = status(a.port)
            if st.get("ok"):
                print(json.dumps(st, ensure_ascii=False))
                return
            import time
            time.sleep(2)
        print("起不来, 看工控机 " + LOG.format(port=a.port))


if __name__ == "__main__":
    main()
