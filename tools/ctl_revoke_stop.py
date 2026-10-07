#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ctl_revoke_stop.py — 撤销授权 ⇒ **立即掐住在途动作** (8793 手动控制台 · 2026-09-29)。

老倪现场: 「http://10.163.146.78:8793/station 我都取消授权了，手臂怎么还在动；赶紧改好」
根因: 撤销只拦**新**命令。已经下发给控制器的那条(speed=8 走得很慢, 实测 30~90s 才到位)不会因为
      人点了撤销就停下 —— 画面里就是"取消了授权还在动"。

本进程是**带外**(out-of-band)的看门人: 与执行器/网页都解耦, 只盯 ctl_auth.json 的 epoch 变化。
  · epoch+1 且未授权 = 有人**显式撤销** ⇒ 若最近 ZMAX_STOP_WINDOW 秒内执行器真下发过动作
    (留痕 ~/zmax/zmax_data/l2_last_dispatch.json), 立刻对机器人调 `/robot_stop`(std_srvs/Trigger)
    把在途运动停下; 全程写审计(谁能查"谁在几点几分撤销、当时停了没有")。
  · 授权**到期**自动失效不算撤销(epoch 不变)⇒ 不叫停, 只记录。
  · 停机/复位类动作由执行器的白名单放行, 不受本闸门影响。

用法: ZMAX_STOP_WINDOW=180 python3 tools/ctl_revoke_stop.py     (systemd: zmax-ctl-stop.service)
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctl_auth as CA

HOST = os.environ.get("ZMAX_ROBOT_HOST", "tashan@192.168.23.66")
WINDOW = float(os.environ.get("ZMAX_STOP_WINDOW", "180"))
MARK = os.path.expanduser("~/zmax/zmax_data/l2_last_dispatch.json")
STATE = os.path.expanduser("~/zmax/zmax_data/ctl_last_stop.json")
CTL_LOG = "/tmp/zmax_ctl.log"
PRE = ("source /opt/ros/humble/setup.bash; for ws in /home/tashan/0810/*/install/setup.bash; "
       "do [ -f \"$ws\" ] && source \"$ws\" && break; done; export ROS_DOMAIN_ID=0; "
       "export FASTDDS_BUILTIN_TRANSPORTS=UDPv4; export ROS_LOCALHOST_ONLY=0; ")
POLL = float(os.environ.get("ZMAX_STOP_POLL", "0.5"))


def log(msg):
    print("[%s] %s" % (time.strftime("%F %T"), msg), flush=True)
    try:
        with open(CTL_LOG, "a", encoding="utf-8") as f:                  # 与网页同一条时间线
            f.write(json.dumps({"t": time.time(), "revoke_stop": str(msg)[:200]}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _dispatch_recent():
    try:
        d = json.loads(open(MARK, encoding="utf-8").read())
    except Exception:                                                   # noqa: BLE001
        return None, None
    age = time.time() - float(d.get("ts") or 0)
    return (d, age) if age <= WINDOW else (None, age)


def _sdk_stop():
    """🚚 SDK 腿下的叫停 (2026-10-07): 执行腿=本机 SDK 直连时, 停止**必须直达 SDK 代理**。

    为什么(实测): 下面 _robot_stop() 是 `ssh Orin → ros2 call /robot_stop`, 而产线 ROS 栈没在跑时
    它**叫不停**(返回 success=False)。SDK 腿在动臂 ⇒ 撤销授权必须能真的停住, 所以先走 SDK(ms 级)。
    返回 True=已投递停止(不代表控制器已确认, 但通道是活的); None=不是 SDK 腿, 走原路。
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "rokae"))
        import l2_transport_sdk as _T                                       # noqa: PLC0415
    except Exception as e:                                                  # noqa: BLE001
        log("⚠️ SDK 腿停止模块不可用(%s) ⇒ 只能走产线 /robot_stop" % str(e)[:70])
        return None
    if _T.transport() != "sdk":
        return None
    try:
        _T.stop("8793 撤销授权 ⇒ 立即叫停在途 SDK 动作", log)
        return True
    except Exception as e:                                                  # noqa: BLE001
        log("⚠️ SDK 腿停止投递异常: %s" % str(e)[:90])
        return False


def _robot_stop():
    """/robot_stop (std_srvs/Trigger) —— 受控停止(不是断电急停)。"""
    _sdk_ok = _sdk_stop()                     # 执行腿=sdk 时先走 SDK(不等 ssh 超时)
    cmd = PRE + 'timeout 20 ros2 service call /robot_stop std_srvs/srv/Trigger "{}"'
    t0 = time.time()
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, cmd],
                           capture_output=True, text=True, timeout=40)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:                                              # noqa: BLE001
        return (bool(_sdk_ok) if _sdk_ok is not None else False), \
               ("SDK 腿已投递停止(产线 /robot_stop 调用异常: %s)" % e if _sdk_ok
                else "调用异常: %s" % e), time.time() - t0
    ok = "success=True" in out.replace(" ", "")
    if _sdk_ok:
        return True, "SDK 腿已投递停止 · 产线 /robot_stop: %s" % out[-200:], time.time() - t0
    return ok, (out[-300:] if out else "(无输出)"), time.time() - t0


def main():
    st = CA.info()
    last_epoch, last_armed = st["epoch"], st["armed"]
    log("🔐 撤销看门人启动 · epoch=%s armed=%s · 停叫窗口=%.0fs · 标记=%s" % (last_epoch, last_armed, WINDOW, MARK))
    while True:
        time.sleep(POLL)
        try:
            st = CA.info()
        except Exception as e:                                          # noqa: BLE001
            log("读授权真源失败: %s" % str(e)[:80])
            continue
        ep, armed = st["epoch"], st["armed"]
        if ep == last_epoch:
            continue
        _revoked = (not armed) and ep > last_epoch
        last_epoch, last_armed = ep, armed
        if not _revoked:
            log("🔓 授权变更: epoch=%s armed=%s (非撤销, 不叫停)" % (ep, armed))
            continue
        d, age = _dispatch_recent()
        if not d:
            log("🔒 收到撤销(epoch=%s) · 近 %.0fs 内无真下发(或超窗 %.0fs) ⇒ 无需叫停"
                % (ep, round(age or -1.0, 1), WINDOW))
            _write_state({"ts": time.time(), "revoked_epoch": ep, "stopped": False,
                          "why": "窗口内无真下发"})
            continue
        log("🔒 收到撤销(epoch=%s) ⇒ 在途动作 %s(%.0fs 前下发) 立即叫停 /robot_stop"
            % (ep, d.get("skill") or d.get("kind") or "?", age))
        ok, out, dt = _robot_stop()
        log("%s /robot_stop %s (%.1fs) %s" % ("⏹ 已在途停止:" if ok else "⚠️ 停止调用未确认:", 
                                              "success" if ok else "无 success", dt, out[:160]))
        _write_state({"ts": time.time(), "revoked_epoch": ep, "stopped": bool(ok),
                      "dispatch": d, "dispatch_age_s": round(age, 1), "out": out[:300],
                      "ms": round(dt * 1000)})


def _write_state(d):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


if __name__ == "__main__":
    main()
