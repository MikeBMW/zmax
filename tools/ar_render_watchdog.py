#!/usr/bin/env python3
"""AR 渲染站看门狗 —— 8802 拿不到 GL 上下文时自愈重启.

背景 (2026-10-29 实锤):
  zmax-ar-render 在开机 16:59:50 就起来了, 那时桌面会话还没把 X 授权给服务进程,
  mujoco 构造抛 `FatalError: gladLoadGL error`; 服务内的 while True + sleep(3) 会一直重试,
  但 X 授权一旦错过就不会自己补 ⇒ 实测 3.5 小时 n=0 / truth.tcpL,tcpR 全空 / 页面看着"双臂不动".
  重启服务即刻恢复 (ok:true · n=277 · calib.ok:true · gold_px=2642).

判据只看 /status.json 三件: ok / n / err.
  · ok != true 且 err 非空, 连续 STRIKES 次  → restart
  · n 连续 STRIKES 次没前进 (服务在跑但渲染线程死了)  → restart

只读 /status.json, 不动 /control, 不发运动指令.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

PORT = int(os.environ.get("AR_RENDER_PORT", "8802"))
STRIKES = int(os.environ.get("AR_RENDER_STRIKES", "3"))
STATE = os.environ.get("AR_RENDER_WD_STATE", "/run/zmax_ar_render_wd.json")
UNIT = os.environ.get("AR_RENDER_UNIT", "zmax-ar-render")


def status() -> dict:
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/status.json" % PORT, timeout=4) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:                                                   # noqa: BLE001
        return {"ok": False, "err": "status_read_failed: %s: %s" % (type(e).__name__, e), "n": None}


def load_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                        # noqa: BLE001
        return {"bad": 0, "last_n": None, "same_n": 0, "restarts": 0, "last_restart": None}


def save_state(d: dict) -> None:
    try:
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, STATE)
    except Exception:                                                        # noqa: BLE001
        pass


def main(force: bool = False) -> int:
    st = load_state()
    s = status()
    ok = bool(s.get("ok"))
    n = s.get("n")
    err = s.get("err")
    now = time.strftime("%F %T")

    if ok and n is not None:
        st["bad"] = 0
        if st.get("last_n") is not None and n == st.get("last_n"):
            st["same_n"] = int(st.get("same_n") or 0) + 1
        else:
            st["same_n"] = 0
        st["last_n"] = n
        save_state(st)
        if st["same_n"] >= STRIKES:
            print("%s  渲染帧停在 n=%s 已 %d 次 ⇒ 重启 %s" % (now, n, st["same_n"], UNIT))
            return do_restart(st)
        print("%s  ok n=%s gold_px=%s" % (now, n, s.get("gold_px")))
        return 0

    st["bad"] = int(st.get("bad") or 0) + 1
    save_state(st)
    print("%s  ✗ ok=%s err=%s (连续 %d/%d)" % (now, ok, str(err)[:110], st["bad"], STRIKES))
    if st["bad"] >= STRIKES or force:
        return do_restart(st)
    return 0


def do_restart(st: dict) -> int:
    try:
        subprocess.run(["sudo", "-n", "systemctl", "restart", UNIT], check=False, timeout=60)
        st["bad"] = 0
        st["same_n"] = 0
        st["last_n"] = None
        st["restarts"] = int(st.get("restarts") or 0) + 1
        st["last_restart"] = time.strftime("%F %T")
        save_state(st)
        print("已重启 %s (累计 %d 次)" % (UNIT, st["restarts"]))
        time.sleep(12)
        s2 = status()
        print("回读: ok=%s n=%s gold_px=%s err=%s" % (s2.get("ok"), s2.get("n"),
                                                    s2.get("gold_px"), str(s2.get("err"))[:90]))
        return 0 if s2.get("ok") else 1
    except Exception as e:                                                   # noqa: BLE001
        print("重启失败: %s: %s" % (type(e).__name__, e))
        return 2


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
