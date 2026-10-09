#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ensure_cam_param.py — 保证工控机取像档位与 4060 侧落盘一致(重启后自动复原)。

背景: 10082/10083 服务自启只跑 set_auto_off()+文件默认档, **不读落盘**; 只有部署器 ⑤b(本轮有变更时)还原。
      普通重启必丢档位 ⇒ 现场档位(如点2 的 40000us×8)静默回默认 20000 ⇒ 行带乱跳/判据图变。
用法(只读/幂等, 正常态零副作用):
    ./gui-venv311/bin/python tools/aoi/ensure_cam_param.py            # 检查并按需复原
    ./gui-venv311/bin/python tools/aoi/ensure_cam_param.py --check     # 只看不写
建议 cron(4060 侧, 未启用——需现场确认后再挂):
    @reboot sleep 200 && cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/aoi/ensure_cam_param.py >> /tmp/aoi_param_guard.log 2>&1
    */2 * * * * cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/aoi/ensure_cam_param.py >> /tmp/aoi_param_guard.log 2>&1
"""
import json
import os
import sys
import time
import urllib.request

PERSIST = os.path.expanduser("~/zmax/zmax_data/aoi_v4/cam_param_persist.json")
HOST = "192.168.23.23"
UA = {"User-Agent": "zmax-probe"}


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def main():
    check_only = "--check" in sys.argv
    try:
        d = json.load(open(PERSIST, encoding="utf-8")) or {}
    except Exception as e:                                                       # noqa: BLE001
        print("[param-guard] 无落盘档位文件: %r" % (e,))
        return 0
    rc = 0
    for port, e in sorted(d.items()):
        want_ex, want_gn = e.get("exposure_us"), e.get("gain_db")
        if not want_ex and not want_gn:
            continue
        try:
            now = _get("http://%s:%s/param" % (HOST, port)).get("now") or {}
        except Exception as ex:                                                  # noqa: BLE001
            print("[param-guard] %s 读 /param 失败(服务没起?): %r" % (port, ex))
            continue
        cur_ex, cur_gn = now.get("exposure_us"), now.get("gain_db")
        # 容差: 曝光 1us / 增益 0.01dB
        drift = (want_ex and abs(float(cur_ex or 0) - float(want_ex)) > 1.0) or \
                (want_gn and abs(float(cur_gn or 0) - float(want_gn)) > 0.01)
        if not drift:
            continue
        print("[param-guard] %s 档位漂了 now=%s×%s 应为 %s×%s%s"
              % (port, cur_ex, cur_gn, want_ex, want_gn, " (--check 只报)" if check_only else ""))
        if check_only:
            rc = 3
            continue
        q = []
        if want_ex:
            q.append("exposure=%g" % float(want_ex))
        if want_gn:
            q.append("gain=%g" % float(want_gn))
        try:
            r = _get("http://%s:%s/param?%s" % (HOST, port, "&".join(q)))
            back = (r.get("now") or {})
            ok = bool(r.get("ok")) and abs(float(back.get("exposure_us") or 0) - float(want_ex or 0)) <= 1.0
            print("[param-guard] %s 复原 ⇒ ok=%s now=%s×%s" % (port, ok, back.get("exposure_us"), back.get("gain_db")))
            rc = 0 if ok else 4
        except Exception as ex:                                                  # noqa: BLE001
            print("[param-guard] %s 复原失败: %r" % (port, ex))
            rc = 4
    return rc


if __name__ == "__main__":
    sys.exit(main())
