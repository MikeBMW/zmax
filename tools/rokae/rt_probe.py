#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rt_probe.py — 只读探测 xCoreSDK 的实时(RT)控制接口面, 不发运动

用法(容器内):
  bash tools/rokae_sdk_run.sh --script rt_probe.py            # 只连+列接口, 不切模式
  bash tools/rokae_sdk_run.sh --script rt_probe.py --switch   # 额外: 切 RtCommandMode 列 RT 对象方法, 再切回 Nrt
"""
import json
import os
import sys

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
SWITCH = "--switch" in sys.argv


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False, default=str), flush=True)


def main():
    r = x.Robot_T_Industrial_6 if hasattr(x, "Robot_T_Industrial_6") else None
    try:
        r = x.xMateRobot()          # 与仓库其它脚本一致的构造方式(见 sdk_ctl.py)
    except Exception as e:                                               # noqa: BLE001
        out(err_ctor="%s: %s" % (type(e).__name__, e))
    try:
        r.connectToRobot(IP)
        out(connected=True, ip=IP, power=str(r.powerState({})), op=str(r.operationState({})),
            mode=str(r.motionControlMode({})) if hasattr(r, "motionControlMode") else None)
    except Exception as e:                                               # noqa: BLE001
        out(err_connect="%s: %s" % (type(e).__name__, e))
        return
    names = [n for n in dir(r) if any(k in n.lower() for k in ("rt", "servo", "realtime"))]
    out(robot_rt_like_methods=sorted(names))
    mods = [n for n in dir(x) if any(k in n.lower() for k in ("rt", "servo", "realtime"))]
    out(module_rt_like=sorted(mods))
    try:
        out(get_rt_callable=callable(getattr(r, "getRtMotionController", None)))
    except Exception as e:                                               # noqa: BLE001
        out(err_getrt="%s: %s" % (type(e).__name__, e))
    if not SWITCH:
        try:
            r.disconnectFromRobot()
        except Exception:                                                # noqa: BLE001
            pass
        out(done="只读模式, 未切模式; 加 --switch 才切 RtCommandMode")
        return
    # ---- 切 RT 模式, 列 RT 对象方法, 立刻切回 ----
    try:
        ec = {}
        r.setMotionControlMode(x.MotionControlMode.RtCommandMode, ec)
        out(switch_rt_ec=ec, op_after=str(r.operationState({})))
        rt = r.getRtMotionController()
        out(rt_type=str(type(rt)), rt_methods=sorted([n for n in dir(rt) if not n.startswith("_")])[:80])
        for nm in ("servoJ", "servoP", "moveStart", "moveStop", "setServoJ", "rtStart", "rtStop"):
            if hasattr(rt, nm):
                try:
                    out(**{"rt_has_" + nm: str(getattr(rt, nm).__doc__)[:200]})
                except Exception:                                        # noqa: BLE001
                    pass
    except Exception as e:                                               # noqa: BLE001
        out(err_rt="%s: %s" % (type(e).__name__, e))
    finally:
        try:
            ec2 = {}
            r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec2)
            out(switched_back=ec2, op=str(r.operationState({})))
        except Exception as e:                                           # noqa: BLE001
            out(err_back="%s: %s" % (type(e).__name__, e))
        try:
            r.disconnectFromRobot()
        except Exception:                                                # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
